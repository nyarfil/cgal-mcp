#include "wave_b_operations.h"

#include "../artifact_io.h"
#include "../sha256.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/grid_simplify_point_set.h>
#include <CGAL/hierarchy_simplify_point_set.h>
#include <CGAL/jet_estimate_normals.h>
#include <CGAL/jet_smooth_point_set.h>
#include <CGAL/mst_orient_normals.h>
#include <CGAL/number_utils.h>
#include <CGAL/Point_set_processing_3/internal/Neighbor_query.h>
#include <CGAL/pca_estimate_normals.h>
#include <CGAL/property_map.h>
#include <CGAL/random_simplify_point_set.h>
#include <CGAL/remove_outliers.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <limits>
#include <locale>
#include <map>
#include <random>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace cgal_master::wave_b {
namespace {

using Processing_kernel = CGAL::Exact_predicates_inexact_constructions_kernel;
using Processing_point = Processing_kernel::Point_3;
using Processing_vector = Processing_kernel::Vector_3;
using Point_normal = std::pair<Processing_point, Processing_vector>;
using Point_normals = std::vector<Point_normal>;

constexpr std::size_t kMaxArtifactBytes = 512ULL * 1024ULL * 1024ULL;
constexpr std::size_t kMaxPointCount = 10000000;
const std::set<std::string> kLengthUnits = {"mm", "cm", "m"};
constexpr double kMinimumProcessingSpan = 1e-100;
constexpr double kMaximumProcessingCoordinate = 1e100;
constexpr double kMaximumTranslationToSpanRatio = 1e6;

void require_wave_b_kernel(const Request& request) {
  if (request.kernel != "package_recommended") {
    throw WorkerError(
        "UNSUPPORTED_ADAPTER", "UNSUPPORTED_KERNEL",
        "Point-set processing revision 1 is built for package_recommended "
        "(CGAL::Exact_predicates_inexact_constructions_kernel); requested "
        "precision is not silently substituted");
  }
}

void require_pointset_input(const ArtifactInput& input,
                            const std::string& expected_type,
                            const std::string& expected_format) {
  if (input.type != expected_type) {
    throw WorkerError("INVALID_INPUT", "INPUT_TYPE_MISMATCH",
                      "Expected " + expected_type + ", received " + input.type);
  }
  if (input.format != expected_format) {
    throw WorkerError("INVALID_INPUT", "INPUT_FORMAT_MISMATCH",
                      "Expected " + expected_format + ", received " + input.format);
  }
  if (kLengthUnits.count(input.unit) == 0) {
    throw WorkerError("INVALID_INPUT", "UNSUPPORTED_UNIT",
                      "Point-set units must be one of mm, cm, or m");
  }
}

std::string verified_bytes(const ArtifactInput& input) {
  std::error_code error;
  const auto canonical = std::filesystem::canonical(input.path, error);
  if (error || !std::filesystem::is_regular_file(canonical, error) || error) {
    throw WorkerError("INVALID_INPUT", "INPUT_NOT_REGULAR_FILE",
                      "Point-set input must resolve to a regular file");
  }
  const auto size = std::filesystem::file_size(canonical, error);
  if (error) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Cannot stat point-set input");
  }
  if (size > kMaxArtifactBytes) {
    throw WorkerError("RESOURCE_LIMIT", "ARTIFACT_SIZE_LIMIT_EXCEEDED",
                      "Point-set input exceeds the worker byte limit");
  }
  std::ifstream input_stream(canonical, std::ios::binary);
  if (!input_stream) {
    throw WorkerError("INVALID_INPUT", "INPUT_OPEN_FAILED",
                      "Cannot open point-set input");
  }
  std::string bytes((std::istreambuf_iterator<char>(input_stream)),
                    std::istreambuf_iterator<char>());
  if (!input_stream.eof() && input_stream.fail()) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Cannot read point-set input");
  }
  if (sha256_bytes(bytes) != input.sha256) {
    throw WorkerError("INVALID_INPUT", "DIGEST_MISMATCH",
                      "Point-set input sha256 does not match the bytes parsed");
  }
  return bytes;
}

double finite_number(const std::string& token, const std::string& code,
                     std::size_t line) {
  double result = 0;
  const char* begin = token.data();
  const char* end = begin + token.size();
  // Floating from_chars accepts representable subnormals without the
  // platform-specific ERANGE exception raised by stod on glibc.  It is also
  // locale-independent.  Permit the explicit '+' accepted by XYZ/PLY decimal
  // syntax; reject underflow to zero, overflow, suffixes, and hex literals.
  const bool explicit_plus = begin != end && *begin == '+';
  if (explicit_plus) ++begin;
  const auto parsed = std::from_chars(begin, end, result, std::chars_format::general);
  if (begin == end || (explicit_plus && (*begin == '-' || *begin == '+')) ||
      parsed.ec != std::errc{} || parsed.ptr != end ||
      !std::isfinite(result)) {
    throw WorkerError("INVALID_INPUT", code,
                      "Finite numeric values are required on line " +
                          std::to_string(line));
  }
  return result;
}

std::vector<Processing_point> read_xyz(const ArtifactInput& input) {
  require_pointset_input(input, "PointSet3", "xyz");
  std::istringstream stream(verified_bytes(input));
  stream.imbue(std::locale::classic());
  std::vector<Processing_point> points;
  std::string line;
  std::size_t line_number = 0;
  while (std::getline(stream, line)) {
    ++line_number;
    if (line_number == 1 && line.size() >= 3 &&
        static_cast<unsigned char>(line[0]) == 0xEF &&
        static_cast<unsigned char>(line[1]) == 0xBB &&
        static_cast<unsigned char>(line[2]) == 0xBF) {
      line.erase(0, 3);
    }
    const auto comment = line.find('#');
    if (comment != std::string::npos) line.erase(comment);
    std::istringstream tokens(line);
    tokens.imbue(std::locale::classic());
    std::string x, y, z, extra;
    if (!(tokens >> x)) continue;
    if (!(tokens >> y >> z) || (tokens >> extra)) {
      throw WorkerError("INVALID_INPUT", "MALFORMED_XYZ",
                        "Each nonblank XYZ line must have exactly x y z");
    }
    points.emplace_back(finite_number(x, "MALFORMED_XYZ", line_number),
                        finite_number(y, "MALFORMED_XYZ", line_number),
                        finite_number(z, "MALFORMED_XYZ", line_number));
    if (points.size() > kMaxPointCount) {
      throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED",
                        "Point-set input exceeds the worker point limit");
    }
  }
  if (points.empty()) {
    throw WorkerError("PRECONDITION_FAILED", "EMPTY_POINT_SET",
                      "Point-set input must not be empty");
  }
  return points;
}

Point_normals read_ascii_ply_normals(const ArtifactInput& input) {
  require_pointset_input(input, "PointSet3Normals", "ply");
  std::istringstream stream(verified_bytes(input));
  stream.imbue(std::locale::classic());
  std::string line;
  if (!std::getline(stream, line)) {
    throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PLY",
                      "PointSet3Normals accepts ASCII PLY 1.0 only");
  }
  if (!line.empty() && line.back() == '\r') line.pop_back();
  if (line != "ply" || !std::getline(stream, line)) {
    throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PLY",
                      "PointSet3Normals accepts ASCII PLY 1.0 only");
  }
  if (!line.empty() && line.back() == '\r') line.pop_back();
  if (line != "format ascii 1.0") {
    throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PLY",
                      "PointSet3Normals accepts ASCII PLY 1.0 only");
  }
  static const std::set<std::string> scalar_types = {
      "char",  "uchar",  "short", "ushort", "int",     "uint",
      "int8",  "uint8",  "int16", "uint16", "int32",   "uint32",
      "float", "double", "float32", "float64"};
  std::size_t count = 0;
  bool have_vertex = false;
  bool have_end_header = false;
  std::vector<std::string> properties;
  std::size_t line_number = 2;
  while (std::getline(stream, line)) {
    ++line_number;
    if (!line.empty() && line.back() == '\r') line.pop_back();
    std::istringstream header(line);
    std::vector<std::string> fields;
    std::string field;
    while (header >> field) fields.push_back(field);
    if (fields.empty()) continue;
    if (fields == std::vector<std::string>{"end_header"}) {
      have_end_header = true;
      break;
    }
    if (fields.front() == "element") {
      if (fields.size() == 3 && fields[1] == "vertex") {
        if (have_vertex) {
          throw WorkerError("INVALID_INPUT", "MALFORMED_PLY",
                            "PLY must contain one valid vertex element");
        }
        std::size_t consumed = 0;
        try {
          const auto parsed = std::stoull(fields[2], &consumed);
          if (consumed != fields[2].size() ||
              parsed > (std::numeric_limits<std::size_t>::max)()) {
            throw std::out_of_range("PLY vertex count");
          }
          count = static_cast<std::size_t>(parsed);
        } catch (const std::exception&) {
          throw WorkerError("INVALID_INPUT", "MALFORMED_PLY", "Invalid PLY vertex count");
        }
        have_vertex = true;
      } else {
        throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PLY",
                          "PLY faces and non-vertex elements are not accepted");
      }
    } else if (fields.front() == "property") {
      if (!have_vertex || fields.size() != 3 ||
          scalar_types.count(fields[1]) == 0 ||
          std::find(properties.begin(), properties.end(), fields[2]) !=
              properties.end()) {
        throw WorkerError("INVALID_INPUT", "MALFORMED_PLY", "Unsupported PLY property");
      }
      properties.push_back(fields[2]);
    } else if (fields.front() != "comment" && fields.front() != "obj_info") {
      throw WorkerError("INVALID_INPUT", "MALFORMED_PLY", "Unsupported PLY header line");
    }
  }
  if (!have_end_header || !have_vertex || count == 0 || count > kMaxPointCount) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_PLY", "Missing or invalid PLY vertex data");
  }
  const auto position = [&](const std::string& name) -> std::size_t {
    const auto it = std::find(properties.begin(), properties.end(), name);
    if (it == properties.end()) {
      throw WorkerError("INVALID_INPUT", "MISSING_NORMAL_PROPERTY",
                        "PLY requires x, y, z, nx, ny, and nz properties");
    }
    return static_cast<std::size_t>(std::distance(properties.begin(), it));
  };
  const auto x = position("x"), y = position("y"), z = position("z");
  const auto nx = position("nx"), ny = position("ny"), nz = position("nz");
  Point_normals result;
  result.reserve(count);
  for (std::size_t index = 0; index < count; ++index) {
    if (!std::getline(stream, line)) {
      throw WorkerError("INVALID_INPUT", "MALFORMED_PLY", "PLY ended before all vertices");
    }
    ++line_number;
    if (!line.empty() && line.back() == '\r') line.pop_back();
    std::istringstream values(line);
    std::vector<std::string> tokens;
    std::string token;
    while (values >> token) tokens.push_back(token);
    if (tokens.size() != properties.size()) {
      throw WorkerError("INVALID_INPUT", "MALFORMED_PLY", "PLY vertex property count mismatch");
    }
    result.emplace_back(
        Processing_point(finite_number(tokens[x], "MALFORMED_PLY", line_number),
                         finite_number(tokens[y], "MALFORMED_PLY", line_number),
                         finite_number(tokens[z], "MALFORMED_PLY", line_number)),
        Processing_vector(finite_number(tokens[nx], "MALFORMED_PLY", line_number),
                          finite_number(tokens[ny], "MALFORMED_PLY", line_number),
                          finite_number(tokens[nz], "MALFORMED_PLY", line_number)));
  }
  while (std::getline(stream, line)) {
    if (line.find_first_not_of(" \t\r") != std::string::npos) {
      throw WorkerError("INVALID_INPUT", "MALFORMED_PLY", "PLY has trailing data");
    }
  }
  return result;
}

std::size_t affine_rank(const std::vector<Processing_point>& points) {
  if (points.empty()) return 0;
  const auto first = points.begin();
  auto second = std::find_if(first + 1, points.end(), [&](const auto& p) { return p != *first; });
  if (second == points.end()) return 0;
  auto third = std::find_if(second + 1, points.end(), [&](const auto& p) {
    return !CGAL::collinear(*first, *second, p);
  });
  if (third == points.end()) return 1;
  auto fourth = std::find_if(third + 1, points.end(), [&](const auto& p) {
    return !CGAL::coplanar(*first, *second, *third, p);
  });
  return fourth == points.end() ? 2 : 3;
}

void require_supported_numeric_scale(
    const std::vector<Processing_point>& points) {
  double min_x = (std::numeric_limits<double>::max)();
  double min_y = min_x;
  double min_z = min_x;
  double max_x = -(std::numeric_limits<double>::max)();
  double max_y = max_x;
  double max_z = max_x;
  double max_abs = 0;
  for (const auto& point : points) {
    const auto x = CGAL::to_double(point.x());
    const auto y = CGAL::to_double(point.y());
    const auto z = CGAL::to_double(point.z());
    max_abs = (std::max)({max_abs, std::abs(x), std::abs(y), std::abs(z)});
    min_x = (std::min)(min_x, x);
    min_y = (std::min)(min_y, y);
    min_z = (std::min)(min_z, z);
    max_x = (std::max)(max_x, x);
    max_y = (std::max)(max_y, y);
    max_z = (std::max)(max_z, z);
  }
  if (max_abs > kMaximumProcessingCoordinate) {
    throw WorkerError(
        "PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
        "Point coordinates exceed the safe binary64 processing range");
  }
  const auto span = (std::max)({max_x - min_x, max_y - min_y, max_z - min_z});
  if (!std::isfinite(span) || span < kMinimumProcessingSpan) {
    throw WorkerError(
        "PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
        "Point-set span is below the safe binary64 processing range");
  }
  if (max_abs / span > kMaximumTranslationToSpanRatio) {
    throw WorkerError(
        "PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
        "Point-set translation-to-span ratio exceeds the safe binary64 processing range");
  }
}

void require_neighborhood(const std::vector<Processing_point>& points, unsigned int neighbors,
                          const char* field) {
  if (neighbors < 2 || points.size() <= neighbors) {
    throw WorkerError("PRECONDITION_FAILED", "INVALID_NEIGHBORHOOD",
                      std::string(field) + " must be at least 2 and smaller than point count");
  }
  if (affine_rank(points) < 2) {
    throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_2",
                      "Point-set processing requires at least affine rank 2");
  }
}

void require_local_surface_neighborhoods(
    std::vector<Processing_point>& points, unsigned int neighbors) {
  using Neighbor_query =
      CGAL::Point_set_processing_3::internal::Neighbor_query<
          Processing_kernel, std::vector<Processing_point>&,
          CGAL::Identity_property_map<Processing_point>>;
  Neighbor_query query(points, CGAL::Identity_property_map<Processing_point>());
  std::vector<Processing_point> local;
  local.reserve(static_cast<std::size_t>(neighbors) + 1);
  for (const auto& point : points) {
    local.clear();
    query.get_points(point, neighbors, Processing_kernel::FT(0),
                     std::back_inserter(local));
    if (local.size() < 3 || affine_rank(local) < 2) {
      throw WorkerError(
          "PRECONDITION_FAILED", "LOCAL_NEIGHBORHOOD_RANK_LT_2",
          "Every processing neighborhood must contain a rank-2 local surface");
    }
  }
}

void require_parameters(const Json& parameters, const std::set<std::string>& allowed) {
  for (auto it = parameters.begin(); it != parameters.end(); ++it) {
    if (!allowed.count(it.key())) {
      throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PARAMETER",
                        "Unsupported Wave B parameter: " + it.key());
    }
  }
}

unsigned int required_uint(const Json& parameters, const char* name, unsigned int min,
                           unsigned int maximum = (std::numeric_limits<unsigned int>::max)()) {
  if (!parameters.contains(name) || !parameters.at(name).is_number_unsigned()) {
    throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                      std::string(name) + " must be an unsigned integer");
  }
  const auto value = parameters.at(name).get<std::uint64_t>();
  if (value < min || value > maximum) {
    throw WorkerError("INVALID_INPUT", "INVALID_PARAMETER",
                      std::string(name) + " is outside its supported range");
  }
  return static_cast<unsigned int>(value);
}

bool required_bool(const Json& parameters, const char* name) {
  if (!parameters.contains(name) || !parameters.at(name).is_boolean()) {
    throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                      std::string(name) + " must be boolean");
  }
  return parameters.at(name).get<bool>();
}

double typed_length(const Json& value, const std::string& artifact_unit, const char* name,
                    bool positive = false) {
  if (!value.is_object() || value.size() != 2 || !value.contains("value") ||
      !value.contains("unit") || !value.at("value").is_number() ||
      !value.at("unit").is_string()) {
    throw WorkerError("INVALID_INPUT", "INVALID_TYPED_LENGTH",
                      std::string(name) + " must be {value, unit}");
  }
  const auto amount = value.at("value").get<double>();
  const auto unit = value.at("unit").get<std::string>();
  if (!std::isfinite(amount) || kLengthUnits.count(unit) == 0) {
    throw WorkerError("INVALID_INPUT", "INVALID_TYPED_LENGTH",
                      std::string(name) + " must use finite mm, cm, or m values");
  }
  if (positive ? amount <= 0 : amount < 0) {
    throw WorkerError("INVALID_INPUT", "INVALID_TYPED_LENGTH",
                      std::string(name) + " has an invalid sign");
  }
  const auto factor = [](const std::string& value) {
    if (value == "mm") return 1.0;
    if (value == "cm") return 10.0;
    return 1000.0;
  };
  const auto converted = amount * factor(unit) / factor(artifact_unit);
  if (!std::isfinite(converted) || converted < 0 ||
      (positive && converted <= 0)) {
    throw WorkerError(
        "INVALID_INPUT", "INVALID_TYPED_LENGTH",
        std::string(name) +
            " is not finite and representable with the required sign after unit conversion");
  }
  return converted;
}

double required_typed_length(const Json& parameters,
                             const std::string& artifact_unit,
                             const char* name, bool positive = false) {
  if (!parameters.contains(name)) {
    throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                      std::string(name) + " is required");
  }
  return typed_length(parameters.at(name), artifact_unit, name, positive);
}

std::filesystem::path output_for(const Request& request, const std::string& filename) {
  return output_path(checked_output_dir(request), filename);
}

std::filesystem::path temporary_for(const Request& request,
                                    const std::string& filename) {
  const auto destination = output_for(request, filename);
  const auto temporary =
      destination.parent_path() /
      ("." + filename + "." + staging_filename_token(request.request_id) +
       ".tmp");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("IO_FAILURE", "TEMPORARY_OUTPUT_EXISTS",
                      "Temporary point-set output path is not clean");
  }
  return temporary;
}

void write_xyz(const Request& request, const std::vector<Processing_point>& points,
               const std::string& filename) {
  const auto destination = output_for(request, filename);
  const auto temporary = temporary_for(request, filename);
  std::ofstream stream(temporary, std::ios::binary);
  stream.imbue(std::locale::classic());
  stream << std::setprecision(17);
  for (const auto& point : points) stream << point.x() << ' ' << point.y() << ' ' << point.z() << '\n';
  stream.close();
  if (!stream) {
    std::filesystem::remove(temporary);
    throw WorkerError("IO_FAILURE", "OUTPUT_WRITE_FAILED", "Cannot write XYZ output");
  }
  commit_output(temporary, destination);
}

void write_ply_normals(const Request& request, const Point_normals& points,
                       const std::string& filename) {
  const auto destination = output_for(request, filename);
  const auto temporary = temporary_for(request, filename);
  std::ofstream stream(temporary, std::ios::binary);
  stream.imbue(std::locale::classic());
  stream << "ply\nformat ascii 1.0\nelement vertex " << points.size()
         << "\nproperty double x\nproperty double y\nproperty double z\n"
            "property double nx\nproperty double ny\nproperty double nz\nend_header\n";
  stream << std::setprecision(17);
  for (const auto& [point, normal] : points) {
    stream << point.x() << ' ' << point.y() << ' ' << point.z() << ' '
           << normal.x() << ' ' << normal.y() << ' ' << normal.z() << '\n';
  }
  stream.close();
  if (!stream) {
    std::filesystem::remove(temporary);
    throw WorkerError("IO_FAILURE", "OUTPUT_WRITE_FAILED", "Cannot write PLY normals output");
  }
  commit_output(temporary, destination);
}

Json pointset_output(const std::filesystem::path& path, const std::string& unit) {
  return Json{{"slot", "points"}, {"type", "PointSet3"}, {"unit", unit},
              {"format", "xyz"}, {"path", portable_path(path)}};
}

Json normals_output(const std::filesystem::path& path, const std::string& unit) {
  return Json{{"slot", "points"}, {"type", "PointSet3Normals"}, {"unit", unit},
              {"format", "ply"}, {"path", portable_path(path)}};
}

Json finish_points(const Request& request, const std::vector<Processing_point>& points,
                   std::size_t input_count, Json metrics) {
  if (points.empty()) {
    throw WorkerError("VALIDATION_FAILED", "EMPTY_POINT_SET_OUTPUT",
                      "Point-set transform produced no points");
  }
  const auto path = output_for(request, "points.xyz");
  write_xyz(request, points, "points.xyz");
  metrics["input_point_count"] = input_count;
  metrics["output_point_count"] = points.size();
  metrics["output_affine_rank"] = affine_rank(points);
  metrics["effective_kernel"] = "CGAL::Exact_predicates_inexact_constructions_kernel";
  return success_result(request, Json::array({pointset_output(path, request.inputs.front().unit)}),
                        std::move(metrics));
}

Json run_remove_outliers(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 1) throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH", "pointset.remove_outliers requires one PointSet3 input");
  require_parameters(request.parameters, {"neighbors", "threshold_percent", "threshold_distance"});
  auto points = read_xyz(request.inputs.front());
  require_supported_numeric_scale(points);
  const auto neighbors = required_uint(request.parameters, "neighbors", 2);
  require_neighborhood(points, neighbors, "neighbors");
  if (!request.parameters.contains("threshold_percent") || !request.parameters.at("threshold_percent").is_number()) {
    throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER", "threshold_percent must be a number in [0,100]");
  }
  const auto percent = request.parameters.at("threshold_percent").get<double>();
  if (!std::isfinite(percent) || percent < 0 || percent > 100) throw WorkerError("INVALID_INPUT", "INVALID_PARAMETER", "threshold_percent must be in [0,100]");
  const auto distance = required_typed_length(
      request.parameters, request.inputs.front().unit, "threshold_distance");
  const auto input_count = points.size();
  const auto first = CGAL::remove_outliers<CGAL::Sequential_tag>(
      points, neighbors, CGAL::parameters::threshold_percent(percent).threshold_distance(distance));
  const auto removed = static_cast<std::size_t>(std::distance(first, points.end()));
  points.erase(first, points.end());
  return finish_points(request, points, input_count,
                       Json{{"neighbors", neighbors}, {"threshold_percent", percent},
                            {"threshold_distance", { {"value", distance}, {"unit", request.inputs.front().unit} }},
                            {"removed_point_count", removed}});
}

Json run_grid_simplify(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 1) throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH", "pointset.simplify.grid requires one PointSet3 input");
  require_parameters(request.parameters, {"cell_size", "min_points_per_cell"});
  auto points = read_xyz(request.inputs.front());
  require_supported_numeric_scale(points);
  if (affine_rank(points) < 2) throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_2", "Grid simplification requires affine rank 2 or 3");
  const auto size = required_typed_length(
      request.parameters, request.inputs.front().unit, "cell_size", true);
  for (const auto& point : points) {
    if (!std::isfinite(CGAL::to_double(point.x()) / size) ||
        !std::isfinite(CGAL::to_double(point.y()) / size) ||
        !std::isfinite(CGAL::to_double(point.z()) / size)) {
      throw WorkerError(
          "PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
          "Coordinate-to-cell-size ratios must be finite for grid simplification");
    }
  }
  const auto minimum = required_uint(request.parameters, "min_points_per_cell", 1);
  const auto input_count = points.size();
  const auto first = CGAL::grid_simplify_point_set(points, size,
      CGAL::parameters::min_points_per_cell(minimum));
  points.erase(first, points.end());
  return finish_points(request, points, input_count,
                       Json{{"cell_size", {{"value", size}, {"unit", request.inputs.front().unit}}},
                            {"min_points_per_cell", minimum}, {"removed_point_count", input_count - points.size()}});
}

Json run_random_simplify(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 1) throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH", "pointset.simplify.random requires one PointSet3 input");
  require_parameters(request.parameters, {"removed_percentage", "seed"});
  auto points = read_xyz(request.inputs.front());
  if (!request.parameters.contains("removed_percentage") || !request.parameters.at("removed_percentage").is_number()) throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER", "removed_percentage must be a number in [0,100]");
  const auto percentage = request.parameters.at("removed_percentage").get<double>();
  if (!std::isfinite(percentage) || percentage < 0 || percentage > 100) throw WorkerError("INVALID_INPUT", "INVALID_PARAMETER", "removed_percentage must be in [0,100]");
  const auto seed = required_uint(request.parameters, "seed", 0,
                                  (std::numeric_limits<std::uint32_t>::max)());
  const auto input_count = points.size();
  // CGAL 6.2.1 random_simplify_point_set() calls its documented compatibility
  // shuffle without accepting a generator.  Seed the input permutation here,
  // using a fully specified engine and modulo selection, so the mandatory
  // protocol seed materially controls the result before the CGAL algorithm is
  // invoked.  This avoids pretending that CGAL::get_default_random() controls
  // that implementation (it does not).
  std::mt19937_64 seeded_permutation(seed);
  for (std::size_t index = points.size(); index > 1; --index) {
    const auto selected = static_cast<std::size_t>(seeded_permutation() % index);
    std::swap(points[index - 1], points[selected]);
  }
  const auto first = CGAL::random_simplify_point_set(points, percentage);
  points.erase(first, points.end());
  return finish_points(request, points, input_count,
                       Json{{"removed_percentage", percentage}, {"seed", seed},
                            {"removed_point_count", input_count - points.size()}, {"deterministic", true}});
}

Json run_hierarchy_simplify(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 1) throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH", "pointset.simplify.hierarchy requires one PointSet3 input");
  require_parameters(request.parameters, {"cluster_size", "maximum_variation"});
  auto points = read_xyz(request.inputs.front());
  require_supported_numeric_scale(points);
  if (affine_rank(points) < 2) throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_2", "Hierarchy simplification requires affine rank 2 or 3");
  const auto cluster_size = required_uint(request.parameters, "cluster_size", 1);
  if (!request.parameters.contains("maximum_variation") || !request.parameters.at("maximum_variation").is_number()) throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER", "maximum_variation must be a positive number");
  const auto variation = request.parameters.at("maximum_variation").get<double>();
  if (!std::isfinite(variation) || variation <= 0) throw WorkerError("INVALID_INPUT", "INVALID_PARAMETER", "maximum_variation must be positive");
  const auto input_count = points.size();
  const auto first = CGAL::hierarchy_simplify_point_set(points,
      CGAL::parameters::size(cluster_size).maximum_variation(variation));
  points.erase(first, points.end());
  return finish_points(request, points, input_count,
                       Json{{"cluster_size", cluster_size}, {"maximum_variation", variation},
                            {"removed_point_count", input_count - points.size()}});
}

Json run_jet_smooth(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 1) throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH", "pointset.smooth.jet requires one PointSet3 input");
  require_parameters(request.parameters, {"neighbors", "degree_fitting", "degree_monge"});
  auto points = read_xyz(request.inputs.front());
  require_supported_numeric_scale(points);
  const auto neighbors = required_uint(request.parameters, "neighbors", 2);
  require_neighborhood(points, neighbors, "neighbors");
  require_local_surface_neighborhoods(points, neighbors);
  const auto degree_fitting = required_uint(request.parameters, "degree_fitting", 1, 4);
  const auto degree_monge = required_uint(request.parameters, "degree_monge", 1, 4);
  if (degree_monge > degree_fitting) {
    throw WorkerError("PRECONDITION_FAILED", "MONGE_DEGREE_EXCEEDS_FITTING",
                      "degree_monge must not exceed degree_fitting");
  }
  const auto minimum_samples =
      (degree_fitting + 1) * (degree_fitting + 2) / 2;
  if (points.size() < minimum_samples) {
    throw WorkerError("PRECONDITION_FAILED", "INSUFFICIENT_JET_SAMPLES",
                      "Point count is insufficient for the fitting degree");
  }
  const auto input_count = points.size();
  const auto source = points;
  CGAL::jet_smooth_point_set<CGAL::Sequential_tag>(points, neighbors,
      CGAL::parameters::degree_fitting(degree_fitting).degree_monge(degree_monge));
  return finish_points(request, points, input_count,
                       Json{{"neighbors", neighbors}, {"degree_fitting", degree_fitting},
                            {"degree_monge", degree_monge},
                            {"coordinates_modified", points != source}});
}

constexpr double kUnitNormalTolerance = 1e-6;

double normal_length(const Processing_vector& normal) {
  return std::hypot(CGAL::to_double(normal.x()), CGAL::to_double(normal.y()),
                    CGAL::to_double(normal.z()));
}

void require_nonzero_normals(const Point_normals& points) {
  for (const auto& [unused, normal] : points) {
    const double x = CGAL::to_double(normal.x());
    const double y = CGAL::to_double(normal.y());
    const double z = CGAL::to_double(normal.z());
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z) ||
        (x == 0 && y == 0 && z == 0)) {
      throw WorkerError("VALIDATION_FAILED", "DEGENERATE_NORMAL",
                        "Normal estimation produced a zero or nonfinite normal");
    }
  }
}

void require_unit_normals(const Point_normals& points,
                          const std::string& error_class,
                          const std::string& code) {
  for (const auto& [unused, normal] : points) {
    const auto length = normal_length(normal);
    if (!std::isfinite(length) ||
        std::abs(length - 1.0) > kUnitNormalTolerance) {
      throw WorkerError(error_class, code,
                        "Normal vectors must be unit length within 1e-6");
    }
  }
}

Json run_estimate_normals(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 1) throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH", "pointset.normals.estimate requires one PointSet3 input");
  require_parameters(request.parameters, {"method", "neighbors", "degree_fitting"});
  auto points = read_xyz(request.inputs.front());
  require_supported_numeric_scale(points);
  const auto neighbors = required_uint(request.parameters, "neighbors", 2);
  require_neighborhood(points, neighbors, "neighbors");
  require_local_surface_neighborhoods(points, neighbors);
  if (!request.parameters.contains("method") || !request.parameters.at("method").is_string()) throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER", "method must be pca or jet");
  const auto method = request.parameters.at("method").get<std::string>();
  Point_normals normals;
  normals.reserve(points.size());
  for (const auto& point : points) normals.emplace_back(point, Processing_vector(0, 0, 0));
  if (method == "pca") {
    if (request.parameters.contains("degree_fitting")) throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PARAMETER", "degree_fitting applies to jet estimation only");
    CGAL::pca_estimate_normals<CGAL::Sequential_tag>(normals, neighbors,
        CGAL::parameters::point_map(CGAL::First_of_pair_property_map<Point_normal>()).normal_map(CGAL::Second_of_pair_property_map<Point_normal>()));
  } else if (method == "jet") {
    const auto degree = required_uint(request.parameters, "degree_fitting", 1, 4);
    const auto minimum_samples = (degree + 1) * (degree + 2) / 2;
    if (points.size() < minimum_samples) {
      throw WorkerError("PRECONDITION_FAILED", "INSUFFICIENT_JET_SAMPLES",
                        "Point count is insufficient for the fitting degree");
    }
    CGAL::jet_estimate_normals<CGAL::Sequential_tag>(normals, neighbors,
        CGAL::parameters::point_map(CGAL::First_of_pair_property_map<Point_normal>()).normal_map(CGAL::Second_of_pair_property_map<Point_normal>()).degree_fitting(degree));
  } else {
    throw WorkerError("INVALID_INPUT", "UNKNOWN_NORMAL_METHOD", "method must be pca or jet");
  }
  require_nonzero_normals(normals);
  require_unit_normals(normals, "VALIDATION_FAILED", "NON_UNIT_NORMAL_OUTPUT");
  const auto path = output_for(request, "points.ply");
  write_ply_normals(request, normals, "points.ply");
  Json metrics = {{"method", method}, {"neighbors", neighbors}, {"input_point_count", points.size()},
                  {"output_point_count", normals.size()}, {"output_affine_rank", affine_rank(points)},
                  {"effective_kernel", "CGAL::Exact_predicates_inexact_constructions_kernel"}};
  if (method == "jet") metrics["degree_fitting"] = request.parameters.at("degree_fitting");
  return success_result(request, Json::array({normals_output(path, request.inputs.front().unit)}), std::move(metrics));
}

Json run_orient_normals_mst(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 1) throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH", "pointset.normals.orient_mst requires one PointSet3Normals input");
  require_parameters(request.parameters, {"neighbors", "drop_unoriented"});
  auto points = read_ascii_ply_normals(request.inputs.front());
  std::vector<Processing_point> positions;
  positions.reserve(points.size());
  for (const auto& pair : points) positions.push_back(pair.first);
  require_supported_numeric_scale(positions);
  const auto neighbors = required_uint(request.parameters, "neighbors", 2);
  require_neighborhood(positions, neighbors, "neighbors");
  require_nonzero_normals(points);
  require_unit_normals(points, "PRECONDITION_FAILED", "NON_UNIT_NORMAL_INPUT");
  const bool drop_unoriented = required_bool(request.parameters, "drop_unoriented");
  const auto first_unoriented = CGAL::mst_orient_normals(
      points, neighbors,
      CGAL::parameters::point_map(CGAL::First_of_pair_property_map<Point_normal>()).normal_map(CGAL::Second_of_pair_property_map<Point_normal>()));
  const auto oriented = static_cast<std::size_t>(std::distance(points.begin(), first_unoriented));
  const auto unoriented = points.size() - oriented;
  if (unoriented > 0 && !drop_unoriented) {
    throw WorkerError("VALIDATION_FAILED", "UNORIENTED_NORMALS",
                      "MST could not orient every normal; set drop_unoriented true to explicitly retain the oriented subset");
  }
  if (drop_unoriented) points.erase(first_unoriented, points.end());
  if (points.empty()) throw WorkerError("VALIDATION_FAILED", "EMPTY_ORIENTED_POINT_SET", "MST left no oriented normals");
  require_nonzero_normals(points);
  require_unit_normals(points, "VALIDATION_FAILED", "NON_UNIT_NORMAL_OUTPUT");
  const auto path = output_for(request, "points.ply");
  write_ply_normals(request, points, "points.ply");
  return success_result(request, Json::array({normals_output(path, request.inputs.front().unit)}),
                        Json{{"neighbors", neighbors}, {"input_point_count", oriented + unoriented},
                             {"output_point_count", points.size()}, {"oriented_point_count", oriented},
                             {"unoriented_point_count", unoriented}, {"drop_unoriented", drop_unoriented},
                             {"normal_orientation", "mst_consistent_component"},
                             {"effective_kernel", "CGAL::Exact_predicates_inexact_constructions_kernel"}});
}

using Point_key = std::tuple<double, double, double>;
using Oriented_normal_key =
    std::tuple<double, double, double, double, double, double>;

Point_key point_key(const Processing_point& point) {
  return {CGAL::to_double(point.x()), CGAL::to_double(point.y()),
          CGAL::to_double(point.z())};
}

double canonical_zero(double value) { return value == 0 ? 0.0 : value; }

Oriented_normal_key oriented_normal_key(const Point_normal& value) {
  double x = canonical_zero(CGAL::to_double(value.second.x()));
  double y = canonical_zero(CGAL::to_double(value.second.y()));
  double z = canonical_zero(CGAL::to_double(value.second.z()));
  if (x < 0 || (x == 0 && y < 0) || (x == 0 && y == 0 && z < 0)) {
    x = -x;
    y = -y;
    z = -z;
  }
  const auto [px, py, pz] = point_key(value.first);
  return {px, py, pz, canonical_zero(x), canonical_zero(y),
          canonical_zero(z)};
}

template <class Value, class KeyFunction>
bool is_multiset_subset(const std::vector<Value>& candidate,
                        const std::vector<Value>& source,
                        KeyFunction key_function) {
  using Key = decltype(key_function(std::declval<Value>()));
  std::map<Key, std::size_t> available;
  for (const auto& value : source) ++available[key_function(value)];
  for (const auto& value : candidate) {
    const auto key = key_function(value);
    const auto found = available.find(key);
    if (found == available.end() || found->second == 0) return false;
    --found->second;
  }
  return true;
}

void require_same_unit(const ArtifactInput& candidate,
                       const ArtifactInput& source) {
  if (candidate.unit != source.unit) {
    throw WorkerError("INVALID_INPUT", "UNIT_MISMATCH",
                      "Candidate and source point-set units must match");
  }
}

Json basic_checks(const std::vector<Processing_point>& positions,
                  bool normals_present) {
  const auto rank = affine_rank(positions);
  if (positions.size() < 3 || rank < 2) {
    throw WorkerError(
        "VALIDATION_FAILED", "POINTSET_INSUFFICIENT_RANK",
        "Point set must have at least three points and affine rank 2 or 3");
  }
  return Json{{"valid", true},
              {"finite_coordinates", true},
              {"point_count_valid", true},
              {"point_count", positions.size()},
              {"affine_rank_valid", true},
              {"affine_rank", rank},
              {"normals_present", normals_present},
              {"normal_vectors_nonzero",
               normals_present ? Json(true) : Json(nullptr)},
              {"normal_vectors_unit",
               normals_present ? Json(true) : Json(nullptr)}};
}

std::vector<Processing_point> positions_of(const Point_normals& values) {
  std::vector<Processing_point> result;
  result.reserve(values.size());
  for (const auto& value : values) result.push_back(value.first);
  return result;
}

Json finish_validation(const Request& request, Json report) {
  report["status"] = "pass";
  const auto destination = output_for(request, "validation.json");
  const auto temporary = temporary_for(request, "validation.json");
  std::ofstream output(temporary, std::ios::binary);
  output << report.dump() << '\n';
  output.close();
  if (!output) {
    std::filesystem::remove(temporary);
    throw WorkerError("IO_FAILURE", "OUTPUT_WRITE_FAILED",
                      "Cannot write point-set validation report");
  }
  commit_output(temporary, destination);
  return success_result(
      request,
      Json::array({Json{{"slot", "validation"},
                        {"type", "ValidationReport"},
                        {"unit", "none"},
                        {"format", "json"},
                        {"path", portable_path(destination)}}}),
      std::move(report));
}

void require_no_parameters(const Request& request, const char* operation) {
  if (!request.parameters.empty()) {
    throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PARAMETER",
                      std::string(operation) + " accepts no parameters");
  }
}

Json run_pointset_validator(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 1) {
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "pointset.validate.basic requires one point-set input");
  }
  require_no_parameters(request, "pointset.validate.basic");
  const auto& input = request.inputs.front();
  if (input.type == "PointSet3" && input.format == "xyz") {
    return finish_validation(request, basic_checks(read_xyz(input), false));
  }
  if (input.type == "PointSet3Normals" && input.format == "ply") {
    const auto normals = read_ascii_ply_normals(input);
    require_nonzero_normals(normals);
    require_unit_normals(normals, "VALIDATION_FAILED", "NON_UNIT_NORMAL");
    return finish_validation(request,
                             basic_checks(positions_of(normals), true));
  }
  throw WorkerError(
      "INVALID_INPUT", "INPUT_TYPE_OR_FORMAT_MISMATCH",
      "Validator accepts PointSet3/xyz or PointSet3Normals/ply");
}

Json run_subset_validator(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 2) {
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "pointset.validate.subset requires candidate then source");
  }
  require_parameters(
      request.parameters,
      {"neighbors", "threshold_percent", "threshold_distance", "cell_size",
       "min_points_per_cell", "removed_percentage", "seed", "cluster_size",
       "maximum_variation"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto candidate = read_xyz(request.inputs[0]);
  auto source = read_xyz(request.inputs[1]);
  auto report = basic_checks(candidate, false);
  if (candidate.size() > source.size()) {
    throw WorkerError("VALIDATION_FAILED", "POINT_COUNT_INCREASED",
                      "Subset transform increased point count");
  }
  if (!is_multiset_subset(candidate, source, point_key)) {
    throw WorkerError("VALIDATION_FAILED", "POINT_NOT_FROM_SOURCE",
                      "Subset transform output contains a point absent from source");
  }
  if (request.parameters.contains("removed_percentage")) {
    const auto& value = request.parameters.at("removed_percentage");
    if (!value.is_number()) {
      throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                        "removed_percentage must be a number in [0,100]");
    }
    const auto percentage = value.get<double>();
    if (!std::isfinite(percentage) || percentage < 0 || percentage > 100) {
      throw WorkerError("INVALID_INPUT", "INVALID_PARAMETER",
                        "removed_percentage must be in [0,100]");
    }
    const auto expected_count = static_cast<std::size_t>(
        static_cast<double>(source.size()) * ((100.0 - percentage) / 100.0));
    if (candidate.size() != expected_count) {
      throw WorkerError("VALIDATION_FAILED", "UNEXPECTED_RANDOM_SAMPLE_COUNT",
                        "Random simplification output count disagrees with removed_percentage");
    }
    report["expected_output_point_count"] = expected_count;
    report["random_sample_count_matches"] = true;
  }
  std::vector<Processing_point> expected;
  std::string reference_algorithm;
  if (request.parameters.contains("threshold_percent")) {
    if (request.parameters.size() != 3 ||
        !request.parameters.contains("neighbors") ||
        !request.parameters.contains("threshold_distance")) {
      throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                        "Outlier reference requires neighbors, threshold_percent, and threshold_distance");
    }
    expected = source;
    require_supported_numeric_scale(expected);
    const auto neighbors = required_uint(request.parameters, "neighbors", 2);
    require_neighborhood(expected, neighbors, "neighbors");
    const auto percent_value = request.parameters.at("threshold_percent");
    if (!percent_value.is_number()) {
      throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                        "threshold_percent must be a number in [0,100]");
    }
    const auto percent = percent_value.get<double>();
    if (!std::isfinite(percent) || percent < 0 || percent > 100) {
      throw WorkerError("INVALID_INPUT", "INVALID_PARAMETER",
                        "threshold_percent must be in [0,100]");
    }
    const auto distance = required_typed_length(
        request.parameters, request.inputs[1].unit, "threshold_distance");
    const auto first = CGAL::remove_outliers<CGAL::Sequential_tag>(
        expected, neighbors,
        CGAL::parameters::threshold_percent(percent)
            .threshold_distance(distance));
    expected.erase(first, expected.end());
    reference_algorithm = "remove_outliers";
  } else if (request.parameters.contains("cell_size")) {
    if (request.parameters.size() != 2 ||
        !request.parameters.contains("min_points_per_cell")) {
      throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                        "Grid reference requires cell_size and min_points_per_cell");
    }
    expected = source;
    require_supported_numeric_scale(expected);
    if (affine_rank(expected) < 2) {
      throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_2",
                        "Grid simplification requires affine rank 2 or 3");
    }
    const auto size = required_typed_length(
        request.parameters, request.inputs[1].unit, "cell_size", true);
    for (const auto& point : expected) {
      if (!std::isfinite(CGAL::to_double(point.x()) / size) ||
          !std::isfinite(CGAL::to_double(point.y()) / size) ||
          !std::isfinite(CGAL::to_double(point.z()) / size)) {
        throw WorkerError("PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
                          "Coordinate-to-cell-size ratios must be finite for grid simplification");
      }
    }
    const auto minimum =
        required_uint(request.parameters, "min_points_per_cell", 1);
    const auto first = CGAL::grid_simplify_point_set(
        expected, size, CGAL::parameters::min_points_per_cell(minimum));
    expected.erase(first, expected.end());
    reference_algorithm = "grid_simplify_point_set";
  } else if (request.parameters.contains("removed_percentage")) {
    if (request.parameters.size() != 2 ||
        !request.parameters.contains("seed")) {
      throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                        "Random reference requires removed_percentage and seed");
    }
    expected = source;
    const auto percentage = request.parameters.at("removed_percentage").get<double>();
    const auto seed = required_uint(request.parameters, "seed", 0,
                                    (std::numeric_limits<std::uint32_t>::max)());
    std::mt19937_64 seeded_permutation(seed);
    for (std::size_t index = expected.size(); index > 1; --index) {
      const auto selected =
          static_cast<std::size_t>(seeded_permutation() % index);
      std::swap(expected[index - 1], expected[selected]);
    }
    const auto first = CGAL::random_simplify_point_set(expected, percentage);
    expected.erase(first, expected.end());
    reference_algorithm = "random_simplify_point_set";
  } else if (request.parameters.contains("cluster_size")) {
    if (request.parameters.size() != 2 ||
        !request.parameters.contains("maximum_variation")) {
      throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                        "Hierarchy reference requires cluster_size and maximum_variation");
    }
    expected = source;
    require_supported_numeric_scale(expected);
    if (affine_rank(expected) < 2) {
      throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_2",
                        "Hierarchy simplification requires affine rank 2 or 3");
    }
    const auto cluster_size = required_uint(request.parameters, "cluster_size", 1);
    const auto variation_value = request.parameters.at("maximum_variation");
    if (!variation_value.is_number()) {
      throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                        "maximum_variation must be a positive number");
    }
    const auto variation = variation_value.get<double>();
    if (!std::isfinite(variation) || variation <= 0) {
      throw WorkerError("INVALID_INPUT", "INVALID_PARAMETER",
                        "maximum_variation must be positive");
    }
    const auto first = CGAL::hierarchy_simplify_point_set(
        expected,
        CGAL::parameters::size(cluster_size).maximum_variation(variation));
    expected.erase(first, expected.end());
    reference_algorithm = "hierarchy_simplify_point_set";
  } else if (!request.parameters.empty()) {
    throw WorkerError("INVALID_INPUT", "INVALID_PARAMETER_SET",
                      "Subset validator parameters do not identify one algorithm");
  }
  if (!reference_algorithm.empty()) {
    if (candidate != expected) {
      throw WorkerError(
          "VALIDATION_FAILED", "SUBSET_REFERENCE_MISMATCH",
          "Subset transform output disagrees with the deterministic CGAL reference");
    }
    report["cgal_reference_match"] = true;
    report["reference_algorithm"] = reference_algorithm;
  }
  report["source_point_count"] = source.size();
  report["candidate_point_count"] = candidate.size();
  report["count_not_increased"] = true;
  report["candidate_is_source_subset"] = true;
  report["point_count_not_increased"] = true;
  report["candidate_is_source_multiset_subset"] = true;
  return finish_validation(request, std::move(report));
}

Json run_smoothed_validator(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 2) {
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "pointset.validate.smoothed requires candidate then source");
  }
  require_parameters(request.parameters,
                     {"neighbors", "degree_fitting", "degree_monge"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto candidate = read_xyz(request.inputs[0]);
  auto source = read_xyz(request.inputs[1]);
  auto report = basic_checks(candidate, false);
  if (candidate.size() != source.size()) {
    throw WorkerError("VALIDATION_FAILED", "POINT_COUNT_CHANGED",
                      "Smoothing must preserve point count");
  }
  const auto neighbors = required_uint(request.parameters, "neighbors", 2);
  require_supported_numeric_scale(source);
  require_neighborhood(source, neighbors, "neighbors");
  require_local_surface_neighborhoods(source, neighbors);
  const auto degree_fitting =
      required_uint(request.parameters, "degree_fitting", 1, 4);
  const auto degree_monge =
      required_uint(request.parameters, "degree_monge", 1, 4);
  if (degree_monge > degree_fitting) {
    throw WorkerError("PRECONDITION_FAILED", "MONGE_DEGREE_EXCEEDS_FITTING",
                      "degree_monge must not exceed degree_fitting");
  }
  const auto minimum_samples =
      (degree_fitting + 1) * (degree_fitting + 2) / 2;
  if (source.size() < minimum_samples) {
    throw WorkerError("PRECONDITION_FAILED", "INSUFFICIENT_JET_SAMPLES",
                      "Point count is insufficient for the fitting degree");
  }
  auto expected = source;
  CGAL::jet_smooth_point_set<CGAL::Sequential_tag>(
      expected, neighbors,
      CGAL::parameters::degree_fitting(degree_fitting)
          .degree_monge(degree_monge));
  if (candidate != expected) {
    throw WorkerError("VALIDATION_FAILED", "SMOOTHING_REFERENCE_MISMATCH",
                      "Smoothed coordinates disagree with the deterministic CGAL reference");
  }
  const bool modified = expected != source;
  report["source_point_count"] = source.size();
  report["candidate_point_count"] = candidate.size();
  report["point_count_preserved"] = true;
  report["cgal_reference_match"] = true;
  report["coordinates_modified"] = modified;
  return finish_validation(request, std::move(report));
}

Json run_normals_estimated_validator(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 2) {
    throw WorkerError(
        "INVALID_INPUT", "INPUT_COUNT_MISMATCH",
        "pointset.validate.normals_estimated requires candidate then source");
  }
  require_parameters(request.parameters,
                     {"method", "neighbors", "degree_fitting"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto candidate = read_ascii_ply_normals(request.inputs[0]);
  auto source = read_xyz(request.inputs[1]);
  require_nonzero_normals(candidate);
  require_unit_normals(candidate, "VALIDATION_FAILED", "NON_UNIT_NORMAL");
  auto report = basic_checks(positions_of(candidate), true);
  if (candidate.size() != source.size()) {
    throw WorkerError("VALIDATION_FAILED", "POINT_COUNT_CHANGED",
                      "Normal estimation must preserve point count");
  }
  for (std::size_t index = 0; index < source.size(); ++index) {
    if (candidate[index].first != source[index]) {
      throw WorkerError("VALIDATION_FAILED", "POINT_POSITION_CHANGED",
                        "Normal estimation changed a point position or order");
    }
  }
  const auto neighbors = required_uint(request.parameters, "neighbors", 2);
  require_supported_numeric_scale(source);
  require_neighborhood(source, neighbors, "neighbors");
  require_local_surface_neighborhoods(source, neighbors);
  if (!request.parameters.contains("method") ||
      !request.parameters.at("method").is_string()) {
    throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                      "method must be pca or jet");
  }
  const auto method = request.parameters.at("method").get<std::string>();
  Point_normals expected;
  expected.reserve(source.size());
  for (const auto& point : source)
    expected.emplace_back(point, Processing_vector(0, 0, 0));
  if (method == "pca") {
    if (request.parameters.contains("degree_fitting")) {
      throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PARAMETER",
                        "degree_fitting applies to jet estimation only");
    }
    CGAL::pca_estimate_normals<CGAL::Sequential_tag>(
        expected, neighbors,
        CGAL::parameters::point_map(
            CGAL::First_of_pair_property_map<Point_normal>())
            .normal_map(CGAL::Second_of_pair_property_map<Point_normal>()));
  } else if (method == "jet") {
    const auto degree =
        required_uint(request.parameters, "degree_fitting", 1, 4);
    const auto minimum_samples = (degree + 1) * (degree + 2) / 2;
    if (source.size() < minimum_samples) {
      throw WorkerError("PRECONDITION_FAILED", "INSUFFICIENT_JET_SAMPLES",
                        "Point count is insufficient for the fitting degree");
    }
    CGAL::jet_estimate_normals<CGAL::Sequential_tag>(
        expected, neighbors,
        CGAL::parameters::point_map(
            CGAL::First_of_pair_property_map<Point_normal>())
            .normal_map(CGAL::Second_of_pair_property_map<Point_normal>())
            .degree_fitting(degree));
  } else {
    throw WorkerError("INVALID_INPUT", "UNKNOWN_NORMAL_METHOD",
                      "method must be pca or jet");
  }
  require_nonzero_normals(expected);
  require_unit_normals(expected, "VALIDATION_FAILED", "NON_UNIT_NORMAL_REFERENCE");
  for (std::size_t index = 0; index < candidate.size(); ++index) {
    const auto candidate_length = normal_length(candidate[index].second);
    const auto expected_length = normal_length(expected[index].second);
    const auto dot = CGAL::to_double(candidate[index].second * expected[index].second) /
                     (candidate_length * expected_length);
    if (!std::isfinite(dot) ||
        std::abs(dot) < 1.0 - kUnitNormalTolerance) {
      throw WorkerError(
          "VALIDATION_FAILED", "ESTIMATED_NORMAL_REFERENCE_MISMATCH",
          "Estimated normal direction disagrees with the CGAL reference");
    }
  }
  report["source_point_count"] = source.size();
  report["candidate_point_count"] = candidate.size();
  report["point_count_preserved"] = true;
  report["positions_preserved"] = true;
  report["point_positions_preserved"] = true;
  report["normal_vectors_nonzero"] = true;
  report["normal_vectors_unit"] = true;
  report["local_surface_neighborhoods_valid"] = true;
  report["cgal_reference_direction_match"] = true;
  return finish_validation(request, std::move(report));
}

Json run_normals_oriented_validator(const Request& request) {
  require_wave_b_kernel(request);
  if (request.inputs.size() != 2) {
    throw WorkerError(
        "INVALID_INPUT", "INPUT_COUNT_MISMATCH",
        "pointset.validate.normals_oriented requires candidate then source");
  }
  require_parameters(request.parameters, {"neighbors", "drop_unoriented"});
  const bool drop_unoriented =
      required_bool(request.parameters, "drop_unoriented");
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto candidate = read_ascii_ply_normals(request.inputs[0]);
  const auto source = read_ascii_ply_normals(request.inputs[1]);
  require_nonzero_normals(candidate);
  require_nonzero_normals(source);
  require_unit_normals(candidate, "VALIDATION_FAILED", "NON_UNIT_NORMAL");
  require_unit_normals(source, "VALIDATION_FAILED", "NON_UNIT_NORMAL");
  auto report = basic_checks(positions_of(candidate), true);
  if ((!drop_unoriented && candidate.size() != source.size()) ||
      (drop_unoriented && candidate.size() > source.size())) {
    throw WorkerError("VALIDATION_FAILED", "ORIENTATION_COUNT_CONTRACT_FAILED",
                      "Oriented-normal point count violates drop_unoriented");
  }
  if (!is_multiset_subset(candidate, source, oriented_normal_key)) {
    throw WorkerError(
        "VALIDATION_FAILED", "ORIENTED_NORMAL_NOT_FROM_SOURCE",
        "Normal orientation output changed positions or normal magnitudes");
  }
  const auto neighbors = required_uint(request.parameters, "neighbors", 2);
  const auto source_positions = positions_of(source);
  require_supported_numeric_scale(source_positions);
  require_neighborhood(source_positions, neighbors, "neighbors");
  auto expected = source;
  const auto first_unoriented = CGAL::mst_orient_normals(
      expected, neighbors,
      CGAL::parameters::point_map(
          CGAL::First_of_pair_property_map<Point_normal>())
          .normal_map(CGAL::Second_of_pair_property_map<Point_normal>()));
  const auto expected_unoriented = static_cast<std::size_t>(
      std::distance(first_unoriented, expected.end()));
  if (expected_unoriented > 0 && !drop_unoriented) {
    throw WorkerError("VALIDATION_FAILED", "UNORIENTED_NORMALS",
                      "MST reference could not orient every source normal");
  }
  if (drop_unoriented) expected.erase(first_unoriented, expected.end());
  if (candidate.size() != expected.size()) {
    throw WorkerError("VALIDATION_FAILED", "MST_REFERENCE_COUNT_MISMATCH",
                      "Oriented-normal count disagrees with the CGAL MST reference");
  }
  for (std::size_t index = 0; index < candidate.size(); ++index) {
    if (candidate[index].first != expected[index].first) {
      throw WorkerError("VALIDATION_FAILED", "MST_REFERENCE_ORDER_MISMATCH",
                        "Oriented-normal positions/order disagree with the CGAL MST reference");
    }
    const auto dot = CGAL::to_double(candidate[index].second * expected[index].second);
    if (!std::isfinite(dot) || dot < 1.0 - kUnitNormalTolerance) {
      throw WorkerError("VALIDATION_FAILED", "MST_ORIENTATION_REFERENCE_MISMATCH",
                        "Normal signs disagree with the CGAL MST reference");
    }
  }
  report["source_point_count"] = source.size();
  report["candidate_point_count"] = candidate.size();
  report["positions_preserved_or_subset"] = true;
  report["normal_directions_preserved_up_to_sign"] = true;
  report["drop_policy_honored"] = true;
  report["point_count_not_increased"] = true;
  report["point_count_preserved"] =
      !drop_unoriented ? Json(true) : Json(nullptr);
  report["positions_and_normals_preserved_up_to_sign"] = true;
  report["drop_unoriented_contract_satisfied"] = true;
  report["normal_vectors_nonzero"] = true;
  report["normal_vectors_unit"] = true;
  report["cgal_mst_reference_match"] = true;
  return finish_validation(request, std::move(report));
}

OperationDefinition make_definition(std::string id, std::vector<std::string> inputs,
                                    std::string output, std::string role,
                                    std::function<Json(const Request&)> execute,
                                    Json info) {
  OperationDefinition definition{std::move(id), 1, std::move(inputs), std::move(output),
                                 std::move(role), std::move(execute)};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel = "CGAL::Exact_predicates_inexact_constructions_kernel";
  definition.dependencies = {"Point_set_processing_3", "Eigen3"};
  definition.info = std::move(info);
  return definition;
}

}  // namespace

OperationDefinition remove_outliers_operation() {
  return make_definition(
      "pointset.remove_outliers", {"PointSet3"}, "PointSet3", "transform",
      run_remove_outliers,
      {{"source_header", "CGAL/remove_outliers.h"},
       {"input_format", "xyz"},
       {"output_format", "xyz"},
       {"required_parameters",
        {"neighbors", "threshold_percent", "threshold_distance"}},
       {"validators",
        {"pointset.validate.basic", "pointset.validate.subset",
         "pointset.validate.outliers_removed"}},
       {"validator_parameter_bindings",
        {{"pointset.validate.subset",
          {{"neighbors", "neighbors"},
           {"threshold_percent", "threshold_percent"},
           {"threshold_distance", "threshold_distance"}}},
         {"pointset.validate.outliers_removed",
          {{"neighbors", "neighbors"},
           {"threshold_percent", "threshold_percent"},
           {"threshold_distance", "threshold_distance"}}}}},
       {"numeric_scale_contract",
        {{"minimum_span", kMinimumProcessingSpan},
         {"maximum_absolute_coordinate", kMaximumProcessingCoordinate},
         {"maximum_translation_to_span_ratio",
          kMaximumTranslationToSpanRatio}}}});
}

OperationDefinition grid_simplify_operation() {
  return make_definition(
      "pointset.simplify.grid", {"PointSet3"}, "PointSet3", "transform",
      run_grid_simplify,
      {{"source_header", "CGAL/grid_simplify_point_set.h"},
       {"input_format", "xyz"},
       {"output_format", "xyz"},
       {"required_parameters", {"cell_size", "min_points_per_cell"}},
       {"validators",
        {"pointset.validate.basic", "pointset.validate.subset"}},
       {"validator_parameter_bindings",
        {{"pointset.validate.subset",
          {{"cell_size", "cell_size"},
           {"min_points_per_cell", "min_points_per_cell"}}}}},
       {"numeric_scale_contract",
        {{"minimum_span", kMinimumProcessingSpan},
         {"maximum_absolute_coordinate", kMaximumProcessingCoordinate},
         {"maximum_translation_to_span_ratio",
          kMaximumTranslationToSpanRatio},
         {"finite_coordinate_to_cell_ratio", true}}}});
}

OperationDefinition random_simplify_operation() {
  return make_definition(
      "pointset.simplify.random", {"PointSet3"}, "PointSet3", "transform",
      run_random_simplify,
      {{"source_header", "CGAL/random_simplify_point_set.h"},
       {"input_format", "xyz"},
       {"output_format", "xyz"},
       {"required_parameters", {"removed_percentage", "seed"}},
       {"seed_type", "uint32"},
       {"reproducible_random_seed", true},
       {"validators",
        {"pointset.validate.basic", "pointset.validate.subset"}},
       {"validator_parameter_bindings",
        {{"pointset.validate.subset",
          {{"removed_percentage", "removed_percentage"},
           {"seed", "seed"}}}}}});
}

OperationDefinition hierarchy_simplify_operation() {
  return make_definition(
      "pointset.simplify.hierarchy", {"PointSet3"}, "PointSet3",
      "transform", run_hierarchy_simplify,
      {{"source_header", "CGAL/hierarchy_simplify_point_set.h"},
       {"input_format", "xyz"},
       {"output_format", "xyz"},
       {"required_parameters", {"cluster_size", "maximum_variation"}},
       {"validators",
        {"pointset.validate.basic", "pointset.validate.subset"}},
       {"validator_parameter_bindings",
        {{"pointset.validate.subset",
          {{"cluster_size", "cluster_size"},
           {"maximum_variation", "maximum_variation"}}}}},
       {"numeric_scale_contract",
        {{"minimum_span", kMinimumProcessingSpan},
         {"maximum_absolute_coordinate", kMaximumProcessingCoordinate},
         {"maximum_translation_to_span_ratio",
          kMaximumTranslationToSpanRatio}}}});
}

OperationDefinition jet_smooth_operation() {
  return make_definition(
      "pointset.smooth.jet", {"PointSet3"}, "PointSet3", "transform",
      run_jet_smooth,
      {{"source_header", "CGAL/jet_smooth_point_set.h"},
       {"input_format", "xyz"},
       {"output_format", "xyz"},
       {"required_parameters",
        {"neighbors", "degree_fitting", "degree_monge"}},
       {"validators",
        {"pointset.validate.basic", "pointset.validate.smoothed"}},
       {"validator_parameter_bindings",
        {{"pointset.validate.smoothed",
          {{"neighbors", "neighbors"},
           {"degree_fitting", "degree_fitting"},
           {"degree_monge", "degree_monge"}}}}},
       {"numeric_scale_contract",
        {{"minimum_span", kMinimumProcessingSpan},
         {"maximum_absolute_coordinate", kMaximumProcessingCoordinate},
         {"maximum_translation_to_span_ratio",
          kMaximumTranslationToSpanRatio}}},
       {"local_neighborhood_contract",
        {{"minimum_affine_rank", 2}, {"neighbor_parameter", "neighbors"}}}});
}

OperationDefinition estimate_normals_operation() {
  return make_definition(
      "pointset.normals.estimate", {"PointSet3"}, "PointSet3Normals",
      "transform", run_estimate_normals,
      {{"source_headers",
        {"CGAL/pca_estimate_normals.h", "CGAL/jet_estimate_normals.h"}},
       {"input_format", "xyz"},
       {"output_format", "ascii_ply_with_x_y_z_nx_ny_nz"},
       {"methods", {"pca", "jet"}},
       {"validators",
        {"pointset.validate.basic",
         "pointset.validate.normals_estimated"}},
       {"validator_parameter_bindings",
        {{"pointset.validate.normals_estimated",
          {{"method", "method"},
           {"neighbors", "neighbors"},
           {"degree_fitting", "degree_fitting"}}}}},
       {"numeric_scale_contract",
        {{"minimum_span", kMinimumProcessingSpan},
         {"maximum_absolute_coordinate", kMaximumProcessingCoordinate},
         {"maximum_translation_to_span_ratio",
          kMaximumTranslationToSpanRatio}}},
       {"local_neighborhood_contract",
        {{"minimum_affine_rank", 2}, {"neighbor_parameter", "neighbors"}}}});
}

OperationDefinition orient_normals_mst_operation() {
  return make_definition(
      "pointset.normals.orient_mst", {"PointSet3Normals"},
      "PointSet3Normals", "transform", run_orient_normals_mst,
      {{"source_header", "CGAL/mst_orient_normals.h"},
       {"input_format", "ascii_ply_with_x_y_z_nx_ny_nz"},
       {"output_format", "ascii_ply_with_x_y_z_nx_ny_nz"},
       {"required_parameters", {"neighbors", "drop_unoriented"}},
       {"validators",
        {"pointset.validate.basic",
         "pointset.validate.normals_oriented"}},
       {"validator_parameter_bindings",
        {{"pointset.validate.normals_oriented",
          {{"neighbors", "neighbors"},
           {"drop_unoriented", "drop_unoriented"}}}}},
       {"numeric_scale_contract",
        {{"minimum_span", kMinimumProcessingSpan},
         {"maximum_absolute_coordinate", kMaximumProcessingCoordinate},
         {"maximum_translation_to_span_ratio",
          kMaximumTranslationToSpanRatio}}}});
}

OperationDefinition pointset_basic_validator_operation() {
  return make_definition(
      "pointset.validate.basic", {"PointSet3", "PointSet3Normals"},
      "ValidationReport", "validator", run_pointset_validator,
      {{"input_slots", {"points"}},
       {"accepted_formats",
        {"PointSet3/xyz", "PointSet3Normals/ascii_ply"}},
       {"output_slot", "validation"},
       {"checks",
        {"finite_coordinates", "point_count", "affine_rank",
         "normal_vectors_nonzero", "normal_vectors_unit"}}});
}

OperationDefinition pointset_subset_validator_operation() {
  return make_definition(
      "pointset.validate.subset", {"PointSet3", "PointSet3"},
      "ValidationReport", "validator", run_subset_validator,
      {{"input_slots", {"candidate", "source"}},
       {"input_formats", {"xyz", "xyz"}},
       {"output_slot", "validation"},
       {"optional_parameters",
        {"neighbors", "threshold_percent", "threshold_distance", "cell_size",
         "min_points_per_cell", "removed_percentage", "seed", "cluster_size",
         "maximum_variation"}},
       {"bound_parameters",
        {"neighbors", "threshold_percent", "threshold_distance", "cell_size",
         "min_points_per_cell", "removed_percentage", "seed", "cluster_size",
         "maximum_variation"}},
       {"checks",
        {"finite_coordinates", "candidate_is_source_subset",
         "count_not_increased", "affine_rank",
         "cgal_reference_match", "random_sample_count_matches"}}});
}

OperationDefinition pointset_smoothed_validator_operation() {
  return make_definition(
      "pointset.validate.smoothed", {"PointSet3", "PointSet3"},
      "ValidationReport", "validator", run_smoothed_validator,
      {{"input_slots", {"candidate", "source"}},
       {"input_formats", {"xyz", "xyz"}},
       {"output_slot", "validation"},
       {"required_parameters",
        {"neighbors", "degree_fitting", "degree_monge"}},
       {"bound_parameters",
        {"neighbors", "degree_fitting", "degree_monge"}},
       {"checks",
        {"finite_coordinates", "point_count_preserved", "affine_rank",
         "cgal_reference_match", "coordinates_modified"}}});
}

OperationDefinition pointset_normals_estimated_validator_operation() {
  return make_definition(
      "pointset.validate.normals_estimated",
      {"PointSet3Normals", "PointSet3"}, "ValidationReport", "validator",
      run_normals_estimated_validator,
      {{"input_slots", {"candidate", "source"}},
       {"input_formats", {"ply", "xyz"}},
       {"output_slot", "validation"},
       {"required_parameters", {"method", "neighbors"}},
       {"optional_parameters", {"degree_fitting"}},
       {"bound_parameters", {"method", "neighbors", "degree_fitting"}},
       {"checks",
        {"finite_coordinates", "point_count_preserved",
         "positions_preserved", "normal_vectors_nonzero",
         "normal_vectors_unit", "local_surface_neighborhoods_valid",
         "cgal_reference_direction_match", "affine_rank"}}});
}

OperationDefinition pointset_normals_oriented_validator_operation() {
  return make_definition(
      "pointset.validate.normals_oriented",
      {"PointSet3Normals", "PointSet3Normals"}, "ValidationReport",
      "validator", run_normals_oriented_validator,
      {{"input_slots", {"candidate", "source"}},
       {"input_formats", {"ply", "ply"}},
       {"output_slot", "validation"},
       {"required_parameters", {"neighbors", "drop_unoriented"}},
       {"bound_parameters", {"neighbors", "drop_unoriented"}},
       {"checks",
        {"finite_coordinates", "positions_preserved_or_subset",
         "normal_directions_preserved_up_to_sign",
         "normal_vectors_nonzero", "normal_vectors_unit",
         "drop_policy_honored", "cgal_mst_reference_match",
         "affine_rank"}}});
}

}  // namespace cgal_master::wave_b
