#include "wave_c_common.h"
#include "wave_c_operations.h"

#include "../artifact_io.h"

#include <CGAL/boost/graph/iterator.h>
#include <CGAL/number_utils.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <set>
#include <sstream>
#include <system_error>

namespace cgal_master::wave_c {
namespace {

constexpr double kMaximumExactInteger = 9007199254740992.0;  // 2^53

[[noreturn]] void input_error(const std::string& code, const std::string& message) {
  throw WorkerError("INPUT_ERROR", code, message);
}

void require_json_shape(const ArtifactInput& input, const std::string& type,
                        bool length_unit) {
  if (input.type != type) {
    throw WorkerError("TYPE_ERROR", "INPUT_TYPE_MISMATCH",
                      "Expected input type " + type + ", received " + input.type);
  }
  if (input.format != "json") {
    throw WorkerError("TYPE_ERROR", "INPUT_FORMAT_MISMATCH",
                      "Expected input format json, received " + input.format);
  }
  const bool valid_unit = length_unit
                              ? (input.unit == "mm" || input.unit == "cm" || input.unit == "m")
                              : input.unit == "none";
  if (!valid_unit) {
    throw WorkerError("TYPE_ERROR", "UNSUPPORTED_UNIT",
                      length_unit ? "Geometry unit must be one of: mm, cm, m"
                                  : "Report unit must be none");
  }
}

Json parse_object(const ArtifactInput& input, const std::string& type, bool length_unit,
                  std::initializer_list<const char*> keys) {
  require_json_shape(input, type, length_unit);
  const auto bytes = read_verified_input_bytes(input);
  Json value;
  try {
    value = Json::parse(bytes);
  } catch (const nlohmann::json::exception&) {
    input_error("MALFORMED_JSON", type + " must be valid JSON");
  }
  if (!value.is_object()) input_error("MALFORMED_JSON", type + " must be a JSON object");
  if (keys.size() != 0) {
    std::set<std::string> expected;
    for (const char* key : keys) expected.insert(key);
    std::set<std::string> actual;
    for (const auto& item : value.items()) actual.insert(item.key());
    if (actual != expected) {
      input_error("SCHEMA_MISMATCH", type + " has missing or unexpected top-level keys");
    }
  }
  return value;
}

double number_of(const Json& value, const std::string& context) {
  if (value.is_number_float()) {
    const double result = value.get<double>();
    if (!std::isfinite(result)) input_error("NONFINITE_COORDINATE", context + " is not finite");
    return result;
  }
  if (value.is_number_integer()) {
    const double result = value.is_number_unsigned()
                              ? static_cast<double>(value.get<std::uint64_t>())
                              : static_cast<double>(value.get<std::int64_t>());
    if (std::fabs(result) > kMaximumExactInteger) {
      input_error("INEXACT_INTEGER", context + " exceeds the exactly representable range");
    }
    return result;
  }
  input_error("SCHEMA_MISMATCH", context + " must be a number");
}

std::size_t index_of(const Json& value, std::size_t bound, const std::string& context) {
  if (!value.is_number_integer() || (value.is_number_integer() && !value.is_number_unsigned() &&
                                      value.get<std::int64_t>() < 0)) {
    input_error("SCHEMA_MISMATCH", context + " must be a non-negative integer index");
  }
  const auto index = value.get<std::uint64_t>();
  if (index >= bound) input_error("INDEX_OUT_OF_RANGE", context + " is out of range");
  return static_cast<std::size_t>(index);
}

template <std::size_t N>
std::array<double, N> coordinates(const Json& value, const std::string& context) {
  if (!value.is_array() || value.size() != N) {
    input_error("SCHEMA_MISMATCH",
                context + " must contain exactly " + std::to_string(N) + " numbers");
  }
  std::array<double, N> result{};
  for (std::size_t axis = 0; axis < N; ++axis) result[axis] = number_of(value[axis], context);
  return result;
}

template <std::size_t N>
std::vector<std::array<double, N>> coordinate_list(const Json& value, const std::string& context,
                                                   std::size_t minimum, std::size_t maximum) {
  if (!value.is_array()) input_error("SCHEMA_MISMATCH", context + " must be an array");
  if (value.size() < minimum) {
    input_error("INSUFFICIENT_ELEMENTS",
                context + " requires at least " + std::to_string(minimum) + " points");
  }
  if (value.size() > maximum) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED",
                      context + " exceeds the Wave C size limit");
  }
  std::vector<std::array<double, N>> result;
  result.reserve(value.size());
  for (const auto& item : value) result.push_back(coordinates<N>(item, context));
  return result;
}

template <std::size_t N>
std::vector<std::array<std::size_t, N>> index_list(const Json& value, std::size_t bound,
                                                   const std::string& context) {
  if (!value.is_array()) input_error("SCHEMA_MISMATCH", context + " must be an array");
  std::vector<std::array<std::size_t, N>> result;
  result.reserve(value.size());
  for (const auto& item : value) {
    if (!item.is_array() || item.size() != N) {
      input_error("SCHEMA_MISMATCH",
                  context + " entries must contain exactly " + std::to_string(N) + " indices");
    }
    std::array<std::size_t, N> entry{};
    for (std::size_t position = 0; position < N; ++position) {
      entry[position] = index_of(item[position], bound, context);
    }
    result.push_back(entry);
  }
  return result;
}

std::vector<XY> ring_of(const Json& value, const std::string& context) {
  auto ring = coordinate_list<2>(value, context, 3, kMaximumPolygonVertices);
  return ring;
}

}  // namespace

void require_input_count(const Request& request, std::size_t count,
                         const std::string& operation) {
  if (request.inputs.size() != count) {
    throw WorkerError("TYPE_ERROR", "INPUT_COUNT_MISMATCH",
                      operation + " requires exactly " + std::to_string(count) + " inputs");
  }
}

void require_parameters(const Request& request, std::initializer_list<const char*> required,
                        std::initializer_list<const char*> optional) {
  if (!request.parameters.is_object()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETERS", "parameters must be an object");
  }
  std::set<std::string> allowed;
  for (const char* name : required) {
    allowed.insert(name);
    if (!request.parameters.contains(name)) {
      throw WorkerError("INVALID_REQUEST", "MISSING_PARAMETER",
                        std::string("Missing required parameter ") + name);
    }
  }
  for (const char* name : optional) allowed.insert(name);
  for (const auto& item : request.parameters.items()) {
    if (allowed.find(item.key()) == allowed.end()) {
      throw WorkerError("INVALID_REQUEST", "UNSUPPORTED_PARAMETER",
                        "Unsupported parameter " + item.key());
    }
  }
}

std::size_t integer_parameter(const Request& request, const char* name, std::size_t minimum,
                              std::size_t maximum) {
  const auto& value = request.parameters.at(name);
  if (!value.is_number_integer() ||
      (!value.is_number_unsigned() && value.get<std::int64_t>() < 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " must be a non-negative integer");
  }
  const auto result = value.get<std::uint64_t>();
  if (result < minimum || result > maximum) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " is outside its supported range");
  }
  return static_cast<std::size_t>(result);
}

bool boolean_parameter(const Request& request, const char* name) {
  const auto& value = request.parameters.at(name);
  if (!value.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " must be a boolean");
  }
  return value.get<bool>();
}

std::string enum_parameter(const Request& request, const char* name,
                           std::initializer_list<const char*> allowed) {
  const auto& value = request.parameters.at(name);
  if (value.is_string()) {
    const auto text = value.get<std::string>();
    for (const char* option : allowed) {
      if (text == option) return text;
    }
  }
  throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                    std::string(name) + " is not one of the supported values");
}

double typed_length_parameter(const Request& request, const char* name,
                              const std::string& artifact_unit) {
  const auto& value = request.parameters.at(name);
  if (!value.is_object() || value.size() != 2 || !value.contains("value") ||
      !value.contains("unit") || !value.at("unit").is_string() ||
      !value.at("value").is_number()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " must be a TypedLength {value, unit}");
  }
  if (value.at("unit").get<std::string>() != artifact_unit) {
    throw WorkerError("TYPE_ERROR", "UNIT_MISMATCH",
                      std::string(name) + " must be normalized to the artifact unit");
  }
  const double result = value.at("value").get<double>();
  if (!std::isfinite(result) || result < 0) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " must be finite and non-negative");
  }
  return result;
}

void require_same_unit(const ArtifactInput& first, const ArtifactInput& second) {
  if (first.unit != second.unit) {
    throw WorkerError("TYPE_ERROR", "UNIT_MISMATCH", "Input artifact units must match");
  }
}

std::vector<XY> read_point_set2(const ArtifactInput& input) {
  const auto value = parse_object(input, "PointSet2", true, {"points"});
  return coordinate_list<2>(value.at("points"), "PointSet2 point", 1, kMaximumPlanarPoints);
}

std::vector<XY> read_polygon2(const ArtifactInput& input) {
  const auto value = parse_object(input, "Polygon2", true, {"points"});
  return ring_of(value.at("points"), "Polygon2 vertex");
}

PolygonWithHolesData read_polygon_with_holes2(const ArtifactInput& input) {
  const auto value = parse_object(input, "PolygonWithHoles2", true, {"outer", "holes"});
  PolygonWithHolesData result;
  result.outer = ring_of(value.at("outer"), "PolygonWithHoles2 outer vertex");
  const auto& holes = value.at("holes");
  if (!holes.is_array()) input_error("SCHEMA_MISMATCH", "PolygonWithHoles2 holes must be an array");
  std::size_t total = result.outer.size();
  for (const auto& hole : holes) {
    result.holes.push_back(ring_of(hole, "PolygonWithHoles2 hole vertex"));
    total += result.holes.back().size();
    if (total > kMaximumPolygonVertices) {
      throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED",
                        "PolygonWithHoles2 exceeds the Wave C vertex limit");
    }
  }
  return result;
}

SegmentGraphData read_segment_graph2(const ArtifactInput& input) {
  const auto value = parse_object(input, "SegmentGraph2", true, {"points", "segments"});
  SegmentGraphData result;
  result.points = coordinate_list<2>(value.at("points"), "SegmentGraph2 point", 1,
                                     kMaximumPlanarPoints);
  result.segments = index_list<2>(value.at("segments"), result.points.size(),
                                  "SegmentGraph2 segment");
  if (result.segments.size() > kMaximumConstraintSegments) {
    throw WorkerError("RESOURCE_LIMIT", "SEGMENT_LIMIT_EXCEEDED",
                      "SegmentGraph2 exceeds the Wave C segment limit");
  }
  return result;
}

Triangulation2Data read_triangulation2(const ArtifactInput& input) {
  const auto value =
      parse_object(input, "Triangulation2", true, {"vertices", "triangles", "constrained_edges"});
  Triangulation2Data result;
  result.vertices = coordinate_list<2>(value.at("vertices"), "Triangulation2 vertex", 3,
                                       kMaximumPlanarPoints);
  result.triangles = index_list<3>(value.at("triangles"), result.vertices.size(),
                                   "Triangulation2 triangle");
  result.constrained_edges = index_list<2>(value.at("constrained_edges"),
                                           result.vertices.size(),
                                           "Triangulation2 constrained edge");
  return result;
}

Triangulation3Data read_triangulation3(const ArtifactInput& input) {
  const auto value = parse_object(input, "Triangulation3", true, {"vertices", "tetrahedra"});
  Triangulation3Data result;
  result.vertices = coordinate_list<3>(value.at("vertices"), "Triangulation3 vertex", 4,
                                       kMaximumPlanarPoints);
  result.tetrahedra = index_list<4>(value.at("tetrahedra"), result.vertices.size(),
                                    "Triangulation3 tetrahedron");
  return result;
}

std::vector<XYZ> read_point_set3(const ArtifactInput& input) {
  const auto points = read_xyz_points(input);
  if (points.size() > kMaximumSpatialPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED",
                      "PointSet3 exceeds the Wave C size limit");
  }
  std::vector<XYZ> result;
  result.reserve(points.size());
  for (const auto& point : points) {
    result.push_back({CGAL::to_double(point.x()), CGAL::to_double(point.y()),
                      CGAL::to_double(point.z())});
  }
  return result;
}

std::vector<RayData> read_ray_batch3(const ArtifactInput& input) {
  const auto value = parse_object(input, "RayBatch3", true, {"rays"});
  const auto& rays = value.at("rays");
  if (!rays.is_array() || rays.empty()) {
    input_error("SCHEMA_MISMATCH", "RayBatch3 rays must be a nonempty array");
  }
  if (rays.size() > kMaximumQueryCount) {
    throw WorkerError("RESOURCE_LIMIT", "QUERY_LIMIT_EXCEEDED",
                      "RayBatch3 exceeds the Wave C query limit");
  }
  std::vector<RayData> result;
  for (const auto& ray : rays) {
    if (!ray.is_object() || ray.size() != 2 || !ray.contains("origin") ||
        !ray.contains("direction")) {
      input_error("SCHEMA_MISMATCH", "Each RayBatch3 ray needs exactly origin and direction");
    }
    RayData item{coordinates<3>(ray.at("origin"), "RayBatch3 origin"),
                 coordinates<3>(ray.at("direction"), "RayBatch3 direction")};
    if (item.direction[0] == 0 && item.direction[1] == 0 && item.direction[2] == 0) {
      input_error("DEGENERATE_RAY", "RayBatch3 direction must be nonzero");
    }
    result.push_back(item);
  }
  return result;
}

TriangleMeshData read_triangle_mesh(const ArtifactInput& input) {
  const auto mesh = read_off_mesh(input);
  TriangleMeshData result;
  if (mesh.number_of_vertices() > kMaximumSpatialPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED",
                      "TriangleSurfaceMesh exceeds the Wave C size limit");
  }
  for (const auto vertex : mesh.vertices()) {
    if (static_cast<std::size_t>(vertex.idx()) != result.vertices.size()) {
      throw WorkerError("INTERNAL", "MESH_INDEX_GAP", "Mesh vertex indices are not contiguous");
    }
    const auto& point = mesh.point(vertex);
    result.vertices.push_back({CGAL::to_double(point.x()), CGAL::to_double(point.y()),
                               CGAL::to_double(point.z())});
  }
  for (const auto face : mesh.faces()) {
    if (static_cast<std::size_t>(face.idx()) != result.faces.size()) {
      throw WorkerError("INTERNAL", "MESH_INDEX_GAP", "Mesh face indices are not contiguous");
    }
    Index3 entry{};
    std::size_t position = 0;
    for (const auto vertex : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      if (position >= 3) {
        throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED",
                          "TriangleSurfaceMesh must be triangulated");
      }
      entry[position++] = static_cast<std::size_t>(vertex.idx());
    }
    if (position != 3) {
      throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED",
                        "TriangleSurfaceMesh must be triangulated");
    }
    result.faces.push_back(entry);
  }
  return result;
}

Json read_report(const ArtifactInput& input, const std::string& type, const std::string& kind_key,
                 const std::string& kind) {
  const auto value = parse_object(input, type, false, {});
  if (!value.contains("schema_version") || value.at("schema_version") != 1 ||
      !value.contains("report_type") || value.at("report_type") != type ||
      !value.contains(kind_key) || value.at(kind_key) != kind || !value.contains("results")) {
    throw WorkerError("VALIDATION_FAILED", "REPORT_SCHEMA_MISMATCH",
                      type + " candidate does not declare the expected schema/kind");
  }
  return value;
}

Json write_json_output(const Request& request, const std::string& slot, const std::string& type,
                       const std::string& unit, const Json& value) {
  const auto directory = checked_output_dir(request);
  const auto destination = output_path(directory, slot + ".json");
  const auto temporary =
      directory / ("." + slot + "." + staging_filename_token(request.request_id) + ".tmp.json");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("OUTPUT_ERROR", "TEMPORARY_OUTPUT_EXISTS",
                      "Temporary output path is not clean");
  }
  {
    std::ofstream output(temporary, std::ios::binary);
    output << value.dump() << '\n';
    output.close();
    if (!output) {
      std::filesystem::remove(temporary);
      throw WorkerError("OUTPUT_ERROR", "OUTPUT_WRITE_FAILED", "Unable to write JSON output");
    }
  }
  commit_output(temporary, destination);
  return Json{{"slot", slot},
              {"type", type},
              {"unit", unit},
              {"format", "json"},
              {"path", portable_path(destination)}};
}

Json finish_validation(const Request& request, const std::string& validator, Json report) {
  report["status"] = "pass";
  report["passed"] = true;
  report["validator"] = validator;
  auto output = write_json_output(request, "validation", "ValidationReport", "none", report);
  return success_result(request, Json::array({std::move(output)}), std::move(report));
}

void fail_validation(const std::string& code, const std::string& message) {
  throw WorkerError("VALIDATION_FAILED", code, message);
}

std::string exact_string(const Epeck::FT& value) {
  std::ostringstream stream;
  stream << CGAL::exact(value);
  return stream.str();
}

Json exact_metric(const Epeck::FT& value, const std::string& unit) {
  return Json{{"exact", exact_string(value)},
              {"approximate", CGAL::to_double(value)},
              {"unit", unit}};
}

Json xy_json(const XY& point) { return Json::array({point[0], point[1]}); }

Json xyz_json(const XYZ& point) { return Json::array({point[0], point[1], point[2]}); }

bool same_double(double first, double second) { return first == second; }

OperationDefinition make_definition(std::string id, std::vector<std::string> inputs,
                                    std::string output, std::string role,
                                    std::function<Json(const Request&)> execute,
                                    std::vector<std::string> dependencies, Json info) {
  OperationDefinition definition{std::move(id),   1, std::move(inputs), std::move(output),
                                 std::move(role), std::move(execute)};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel = kEpick;
  definition.dependencies = std::move(dependencies);
  definition.info = std::move(info);
  return definition;
}

std::vector<OperationDefinition> operations() {
  std::vector<OperationDefinition> result;
  for (auto& item : planar_operations()) result.push_back(std::move(item));
  for (auto& item : triangulation_operations()) result.push_back(std::move(item));
  for (auto& item : spatial_operations()) result.push_back(std::move(item));
  return result;
}

}  // namespace cgal_master::wave_c
