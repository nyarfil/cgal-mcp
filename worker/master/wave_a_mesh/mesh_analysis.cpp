#include "wave_a_mesh_operations.h"

#include "../artifact_io.h"
#include "../sha256.h"

#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Polygon_mesh_processing/compute_normal.h>
#include <CGAL/Polygon_mesh_processing/connected_components.h>
#include <CGAL/Polygon_mesh_processing/detect_features.h>
#include <CGAL/Polygon_mesh_processing/manifoldness.h>
#include <CGAL/Polygon_mesh_processing/measure.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Polygon_mesh_processing/shape_predicates.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/boost/graph/helpers.h>
#include <CGAL/number_utils.h>

#include <boost/iterator/function_output_iterator.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <limits>
#include <locale>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace cgal_master::wave_a_mesh {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;
using Kernel = CGAL::Exact_predicates_exact_constructions_kernel;
using Point = Kernel::Point_3;
using Vector = Kernel::Vector_3;
using Mesh = CGAL::Surface_mesh<Point>;
using Face = Mesh::Face_index;
using Vertex = Mesh::Vertex_index;
using Edge = Mesh::Edge_index;
using Halfedge = Mesh::Halfedge_index;

constexpr std::size_t kMaxArtifactBytes = 256ULL * 1024ULL * 1024ULL;
constexpr std::size_t kMaxVertices = 200000;
constexpr std::size_t kMaxFaces = 200000;
constexpr std::size_t kMaxFaceDegree = 100000;
constexpr std::size_t kMaxIntersectionPairs = 10000;
constexpr std::size_t kMaxReportBytes = 16ULL * 1024ULL * 1024ULL;
constexpr double kPi = 3.141592653589793238462643383279502884;
const std::set<std::string> kLengthUnits = {"mm", "cm", "m"};

struct RawOff {
  std::vector<Point> points;
  std::vector<std::vector<std::size_t>> faces;
  bool finite = true;
  bool indices_valid = true;
  bool triangulated = true;
  std::vector<std::string> issues;
};

struct MeshInput {
  RawOff raw;
  Mesh mesh;
  bool constructible = false;
  std::string construction_reason;
};

void require_kernel(const Request& request) {
  if (request.kernel != "exact_constructions" &&
      request.kernel != "package_recommended") {
    throw WorkerError(
        "UNSUPPORTED_ADAPTER", "UNSUPPORTED_KERNEL",
        "Wave A mesh analysis supports exact_constructions and "
        "package_recommended, both mapped to EPECK");
  }
}

void require_approximate_output_profile(const Request& request,
                                        const char* operation) {
  if (request.kernel != "package_recommended") {
    throw WorkerError(
        "UNSUPPORTED", "OUTPUT_PRECISION_PROFILE_UNSUPPORTED",
        std::string(operation) +
            " emits explicitly approximate binary64 values and supports only "
            "the package_recommended policy");
  }
}

void require_parameters(const Json& parameters,
                        const std::set<std::string>& allowed) {
  for (auto it = parameters.begin(); it != parameters.end(); ++it) {
    if (allowed.count(it.key()) == 0) {
      throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PARAMETER",
                        "Unsupported mesh-analysis parameter: " + it.key());
    }
  }
}

void require_input(const Request& request, bool accepts_polygon_soup = false) {
  require_kernel(request);
  if (request.inputs.size() != 1) {
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "Mesh analysis requires one mesh input");
  }
  const auto& input = request.inputs.front();
  const bool type_supported =
      input.type == "TriangleSurfaceMesh" ||
      (accepts_polygon_soup && input.type == "PolygonSoup3");
  if (!type_supported || input.format != "off") {
    throw WorkerError("INVALID_INPUT", "INPUT_TYPE_OR_FORMAT_MISMATCH",
                      accepts_polygon_soup
                          ? "PMP inspection requires TriangleSurfaceMesh or "
                            "PolygonSoup3 in OFF format"
                          : "Mesh analysis requires TriangleSurfaceMesh/OFF");
  }
  if (kLengthUnits.count(input.unit) == 0) {
    throw WorkerError("INVALID_INPUT", "UNSUPPORTED_UNIT",
                      "Mesh length unit must be mm, cm, or m");
  }
}

std::string verified_bytes(const ArtifactInput& input) {
  std::error_code error;
  const auto canonical = std::filesystem::canonical(input.path, error);
  if (error || !std::filesystem::is_regular_file(canonical, error) || error) {
    throw WorkerError("INVALID_INPUT", "INPUT_NOT_REGULAR_FILE",
                      "Mesh input must resolve to a regular file");
  }
  const auto size = std::filesystem::file_size(canonical, error);
  if (error) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Cannot stat mesh input");
  }
  if (size > kMaxArtifactBytes) {
    throw WorkerError("RESOURCE_LIMIT", "ARTIFACT_SIZE_LIMIT_EXCEEDED",
                      "Mesh input exceeds the analysis byte limit");
  }
  std::ifstream stream(canonical, std::ios::binary);
  if (!stream) {
    throw WorkerError("INVALID_INPUT", "INPUT_OPEN_FAILED",
                      "Cannot open mesh input");
  }
  std::string bytes((std::istreambuf_iterator<char>(stream)),
                    std::istreambuf_iterator<char>());
  if (!stream.eof() && stream.fail()) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Cannot read mesh input");
  }
  if (sha256_bytes(bytes) != input.sha256) {
    throw WorkerError("INVALID_INPUT", "DIGEST_MISMATCH",
                      "Mesh input sha256 does not match parsed bytes");
  }
  return bytes;
}

std::vector<std::string> off_tokens(const std::string& bytes) {
  std::istringstream source(bytes);
  source.imbue(std::locale::classic());
  std::vector<std::string> result;
  std::string line;
  while (std::getline(source, line)) {
    const auto comment = line.find('#');
    if (comment != std::string::npos) line.erase(comment);
    std::istringstream fields(line);
    fields.imbue(std::locale::classic());
    std::string token;
    while (fields >> token) result.push_back(token);
  }
  return result;
}

std::uint64_t unsigned_token(const std::string& token, const char* name) {
  std::size_t consumed = 0;
  try {
    if (!token.empty() && token.front() == '-') throw std::invalid_argument(name);
    const auto value = std::stoull(token, &consumed);
    if (consumed != token.size()) throw std::invalid_argument(name);
    return value;
  } catch (const std::exception&) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      std::string("Invalid OFF ") + name);
  }
}

double numeric_token(const std::string& token, bool& finite) {
  std::size_t consumed = 0;
  double value = 0;
  try {
    value = std::stod(token, &consumed);
    if (consumed != token.size()) throw std::invalid_argument("coordinate");
  } catch (const std::exception&) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      "Invalid OFF coordinate");
  }
  if (!std::isfinite(value)) finite = false;
  return value;
}

RawOff parse_off(const ArtifactInput& input) {
  const auto tokens = off_tokens(verified_bytes(input));
  std::size_t cursor = 0;
  const auto next = [&]() -> const std::string& {
    if (cursor >= tokens.size()) {
      throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                        "OFF ended before declared data");
    }
    return tokens[cursor++];
  };
  if (next() != "OFF") {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      "OFF header is required");
  }
  const auto vertex_count = unsigned_token(next(), "vertex count");
  const auto face_count = unsigned_token(next(), "face count");
  (void)unsigned_token(next(), "edge count");
  if (vertex_count > kMaxVertices || face_count > kMaxFaces) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_ELEMENT_LIMIT_EXCEEDED",
                      "Mesh exceeds the bounded analysis element limit");
  }
  RawOff raw;
  raw.points.reserve(static_cast<std::size_t>(vertex_count));
  for (std::size_t index = 0; index < vertex_count; ++index) {
    bool finite = true;
    const auto x = numeric_token(next(), finite);
    const auto y = numeric_token(next(), finite);
    const auto z = numeric_token(next(), finite);
    if (!finite) {
      raw.finite = false;
      raw.issues.push_back("NONFINITE_COORDINATE");
      raw.points.emplace_back(0, 0, 0);
    } else {
      raw.points.emplace_back(x, y, z);
    }
  }
  raw.faces.reserve(static_cast<std::size_t>(face_count));
  for (std::size_t face_index = 0; face_index < face_count; ++face_index) {
    const auto degree = unsigned_token(next(), "face degree");
    if (degree > kMaxFaceDegree) {
      throw WorkerError("RESOURCE_LIMIT", "FACE_DEGREE_LIMIT_EXCEEDED",
                        "OFF face degree exceeds the bounded analysis limit");
    }
    if (degree != 3) raw.triangulated = false;
    if (degree < 3) raw.issues.push_back("FACE_DEGREE_LT_3");
    std::vector<std::size_t> face;
    face.reserve(static_cast<std::size_t>(degree));
    for (std::size_t corner = 0; corner < degree; ++corner) {
      const auto vertex = unsigned_token(next(), "face index");
      if (vertex >= vertex_count) {
        raw.indices_valid = false;
        raw.issues.push_back("FACE_INDEX_OUT_OF_RANGE");
      }
      face.push_back(static_cast<std::size_t>(vertex));
    }
    raw.faces.push_back(std::move(face));
  }
  if (cursor != tokens.size()) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      "Unsupported trailing OFF data");
  }
  std::sort(raw.issues.begin(), raw.issues.end());
  raw.issues.erase(std::unique(raw.issues.begin(), raw.issues.end()),
                   raw.issues.end());
  return raw;
}

MeshInput load_mesh(const Request& request,
                    bool accepts_polygon_soup = false) {
  require_input(request, accepts_polygon_soup);
  MeshInput result;
  result.raw = parse_off(request.inputs.front());
  if (!result.raw.finite) {
    result.construction_reason = "NONFINITE_COORDINATE";
    return result;
  }
  if (!result.raw.indices_valid) {
    result.construction_reason = "FACE_INDEX_OUT_OF_RANGE";
    return result;
  }
  std::vector<Vertex> vertices;
  vertices.reserve(result.raw.points.size());
  for (const auto& point : result.raw.points)
    vertices.push_back(result.mesh.add_vertex(point));
  for (const auto& face : result.raw.faces) {
    std::vector<Vertex> polygon;
    polygon.reserve(face.size());
    for (const auto index : face) polygon.push_back(vertices[index]);
    if (result.mesh.add_face(polygon) == Mesh::null_face()) {
      result.construction_reason = "SURFACE_MESH_FACE_INSERTION_FAILED";
      return result;
    }
  }
  result.constructible = true;
  return result;
}

void require_pmp_mesh(const MeshInput& input, const char* operation,
                      bool require_triangles = true) {
  if (!input.constructible) {
    throw WorkerError(
        "PRECONDITION_FAILED", "MESH_GRAPH_NOT_CONSTRUCTIBLE",
        std::string(operation) + " requires a constructible surface mesh");
  }
  if (!CGAL::is_valid_polygon_mesh(input.mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "INVALID_POLYGON_MESH",
                      std::string(operation) + " requires a valid polygon mesh");
  }
  if (require_triangles && !CGAL::is_triangle_mesh(input.mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED",
                      std::string(operation) + " requires triangular faces");
  }
  if (input.mesh.number_of_faces() == 0) {
    throw WorkerError("PRECONDITION_FAILED", "EMPTY_MESH",
                      std::string(operation) + " requires at least one face");
  }
}

std::size_t degenerate_face_count(const Mesh& mesh) {
  std::vector<Face> faces;
  PMP::degenerate_faces(mesh, std::back_inserter(faces));
  return faces.size();
}

Mesh normalized_local_frame(const Mesh& source, double span, Point& origin) {
  Mesh local = source;
  const auto first = *local.vertices().begin();
  origin = local.point(first);
  const auto scale = Kernel::FT(span > 0 && std::isfinite(span) ? span : 1.0);
  for (const auto vertex : local.vertices())
    local.point(vertex) =
        CGAL::ORIGIN + (local.point(vertex) - origin) / scale;
  return local;
}

Json source_descriptor(const Request& request) {
  const auto& input = request.inputs.front();
  return {{"artifact_id", input.artifact_id},
          {"type", input.type},
          {"format", input.format},
          {"unit", input.unit},
          {"sha256", input.sha256}};
}

Json mesh_summary(const MeshInput& input) {
  Json summary = {{"raw_vertex_count", input.raw.points.size()},
                  {"raw_face_count", input.raw.faces.size()},
                  {"finite_coordinates", input.raw.finite},
                  {"indices_valid", input.raw.indices_valid},
                  {"triangulated", input.raw.triangulated},
                  {"surface_mesh_constructible", input.constructible}};
  if (!input.constructible) {
    summary["construction_reason"] = input.construction_reason;
    summary["vertex_count"] = nullptr;
    summary["face_count"] = nullptr;
    summary["edge_count"] = nullptr;
    summary["closed"] = nullptr;
  } else {
    summary["vertex_count"] = input.mesh.number_of_vertices();
    summary["face_count"] = input.mesh.number_of_faces();
    summary["edge_count"] = input.mesh.number_of_edges();
    summary["closed"] = CGAL::is_closed(input.mesh);
  }
  return summary;
}

Json base_report(const Request& request, const MeshInput& input,
                 const std::string& kind) {
  return {{"schema_version", 1},
          {"analysis_kind", kind},
          {"source", source_descriptor(request)},
          {"mesh_summary", mesh_summary(input)},
          {"results", Json::object()},
          {"validation", {{"validator_id", "mesh.producer_check." + kind},
                          {"authoritative", false},
                          {"passed", false}}}};
}

void fail_report(const std::string& message) {
  throw WorkerError("VALIDATION_FAILED", "ANALYSIS_REPORT_INVALID", message);
}

void validate_common_report(const Json& report, const std::string& kind,
                            const Request& request) {
  if (report.value("schema_version", 0) != 1 ||
      report.value("analysis_kind", "") != kind ||
      !report.contains("source") || !report.contains("mesh_summary") ||
      !report.contains("results") || !report.at("results").is_object() ||
      report.at("source").value("sha256", "") !=
          request.inputs.front().sha256) {
    fail_report("Analysis report common contract failed");
  }
}

std::filesystem::path report_destination(const Request& request) {
  return output_path(checked_output_dir(request), "analysis.json");
}

Json finish_report(const Request& request, Json report,
                   const std::string& kind, Json metrics) {
  validate_common_report(report, kind, request);
  if (!report.at("validation").value("passed", false)) {
    fail_report("Dedicated analysis validator did not pass");
  }
  const auto destination = report_destination(request);
  const auto temporary = destination.parent_path() /
                         (".analysis.json." +
                          staging_filename_token(request.request_id) + ".tmp");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("IO_FAILURE", "TEMPORARY_OUTPUT_EXISTS",
                      "Temporary analysis report path is not clean");
  }
  auto bytes = report.dump();
  if (bytes.size() + 1 > kMaxReportBytes) {
    throw WorkerError("RESOURCE_LIMIT", "REPORT_SIZE_LIMIT_EXCEEDED",
                      "Geometry analysis report exceeds 16 MiB");
  }
  std::ofstream output(temporary, std::ios::binary);
  output << bytes << '\n';
  output.close();
  if (!output) {
    std::filesystem::remove(temporary);
    throw WorkerError("IO_FAILURE", "OUTPUT_WRITE_FAILED",
                      "Cannot write analysis report");
  }
  commit_output(temporary, destination);
  metrics["analysis_kind"] = kind;
  metrics["source_sha256"] = request.inputs.front().sha256;
  metrics["effective_kernel"] =
      "CGAL::Exact_predicates_exact_constructions_kernel";
  return success_result(
      request,
      Json::array({{{"slot", "analysis"},
                    {"type", "GeometryAnalysisReport"},
                    {"unit", "none"},
                    {"format", "json"},
                    {"path", portable_path(destination)}}}),
      std::move(metrics));
}

Json vector_json(const Vector& vector) {
  const auto x = CGAL::to_double(vector.x());
  const auto y = CGAL::to_double(vector.y());
  const auto z = CGAL::to_double(vector.z());
  if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
    throw WorkerError("NUMERIC_FAILURE", "NONFINITE_NORMAL",
                      "Computed normal is not representable in binary64");
  }
  const auto length = std::hypot(x, y, z);
  return {{"value", {x, y, z}},
          {"zero", length == 0},
          {"is_unit", length != 0 && std::abs(length - 1.0) <= 1e-6},
          {"unit", "none"}};
}

Json scalar_measure(const Kernel::FT& value, const std::string& unit,
                    bool require_nonzero_representability = true,
                    bool geometrically_known_nonzero = false) {
  const auto approximate = CGAL::to_double(value);
  if (!std::isfinite(approximate) ||
      (require_nonzero_representability && value != Kernel::FT(0) &&
       approximate == 0) ||
      (require_nonzero_representability && geometrically_known_nonzero &&
       approximate == 0)) {
    return {{"available", false},
            {"reason", "BINARY64_RESULT_NOT_REPRESENTABLE"},
            {"unit", unit}};
  }
  return {{"available", true}, {"value", approximate}, {"unit", unit}};
}

Json point_measure(const Point& point, const std::string& unit) {
  const auto x = CGAL::to_double(point.x());
  const auto y = CGAL::to_double(point.y());
  const auto z = CGAL::to_double(point.z());
  if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
    return {{"available", false},
            {"reason", "BINARY64_RESULT_NOT_REPRESENTABLE"},
            {"unit", unit}};
  }
  return {{"available", true}, {"value", {x, y, z}}, {"unit", unit}};
}

double maximum_coordinate_span(const RawOff& raw) {
  std::array<double, 3> low = {
      std::numeric_limits<double>::infinity(),
      std::numeric_limits<double>::infinity(),
      std::numeric_limits<double>::infinity()};
  std::array<double, 3> high = {
      -std::numeric_limits<double>::infinity(),
      -std::numeric_limits<double>::infinity(),
      -std::numeric_limits<double>::infinity()};
  for (const auto& point : raw.points) {
    const std::array<double, 3> coordinate = {
        CGAL::to_double(point.x()), CGAL::to_double(point.y()),
        CGAL::to_double(point.z())};
    for (std::size_t axis = 0; axis != 3; ++axis) {
      low[axis] = std::min(low[axis], coordinate[axis]);
      high[axis] = std::max(high[axis], coordinate[axis]);
    }
  }
  double span = 0;
  for (std::size_t axis = 0; axis != 3; ++axis) {
    const auto scale = std::max(std::abs(low[axis]), std::abs(high[axis]));
    if (scale == 0) continue;
    const auto normalized = high[axis] / scale - low[axis] / scale;
    const auto axis_span = scale * normalized;
    if (!std::isfinite(axis_span))
      return std::numeric_limits<double>::infinity();
    span = std::max(span, axis_span);
  }
  return span;
}

Json unavailable_measure(const std::string& unit,
                         const std::string& reason) {
  return {{"available", false}, {"reason", reason}, {"unit", unit}};
}

double typed_angle_degrees(const Json& parameters) {
  require_parameters(parameters, {"angle"});
  if (!parameters.contains("angle") || !parameters.at("angle").is_object()) {
    throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                      "angle must be a typed angle object");
  }
  const auto& angle = parameters.at("angle");
  if (angle.size() != 2 || !angle.contains("value") ||
      !angle.contains("unit") || !angle.at("value").is_number() ||
      !angle.at("unit").is_string()) {
    throw WorkerError("INVALID_INPUT", "INVALID_TYPED_ANGLE",
                      "angle must be {value,unit} with deg or rad");
  }
  const auto value = angle.at("value").get<double>();
  const auto unit = angle.at("unit").get<std::string>();
  if (!std::isfinite(value) || (unit != "deg" && unit != "rad")) {
    throw WorkerError("INVALID_INPUT", "INVALID_TYPED_ANGLE",
                      "angle must use a finite deg or rad value");
  }
  const auto degrees = unit == "deg" ? value : value * 180.0 / kPi;
  if (!std::isfinite(degrees) || degrees < 0 || degrees > 180) {
    throw WorkerError("INVALID_INPUT", "INVALID_TYPED_ANGLE",
                      "sharp-feature angle must be within [0,180] degrees");
  }
  return degrees;
}

Json run_inspect(const Request& request, bool publish) {
  require_parameters(request.parameters, {});
  auto input = load_mesh(request, true);
  auto report = base_report(request, input, "pmp_inspection");
  auto& results = report["results"];
  results["count_unit"] = "count";
  results["parse_issues"] = input.raw.issues;
  results["polygon_mesh_valid"] =
      input.constructible ? Json(CGAL::is_valid_polygon_mesh(input.mesh))
                          : Json(nullptr);
  results["closed"] =
      input.constructible ? Json(CGAL::is_closed(input.mesh)) : Json(nullptr);
  if (input.constructible && CGAL::is_triangle_mesh(input.mesh)) {
    std::vector<Face> degenerate;
    PMP::degenerate_faces(input.mesh, std::back_inserter(degenerate));
    // CGAL reports one representative halfedge per non-manifold vertex.
    std::vector<Halfedge> non_manifold;
    PMP::non_manifold_vertices(input.mesh, std::back_inserter(non_manifold));
    std::size_t isolated = 0;
    for (const auto vertex : input.mesh.vertices())
      if (input.mesh.halfedge(vertex) == Mesh::null_halfedge()) ++isolated;
    results["degenerate_face_count"] = degenerate.size();
    results["non_manifold_vertex_count"] = non_manifold.size();
    results["isolated_vertex_count"] = isolated;
  } else {
    results["degenerate_face_count"] = nullptr;
    results["non_manifold_vertex_count"] = nullptr;
    results["isolated_vertex_count"] = nullptr;
  }
  if (!results.contains("parse_issues") ||
      !results.contains("polygon_mesh_valid") ||
      report["mesh_summary"].value("raw_vertex_count", 0) !=
          input.raw.points.size()) {
    fail_report("PMP inspection report contract failed");
  }
  report["validation"]["passed"] = true;
  report["validation"]["checks"] =
      {"raw_counts_present", "graph_state_explicit", "findings_not_repair"};
  if (!publish) return report;
  return finish_report(request, std::move(report), "pmp_inspection",
                       {{"raw_vertex_count", input.raw.points.size()},
                        {"raw_face_count", input.raw.faces.size()},
                        {"surface_mesh_constructible", input.constructible}});
}

Json run_connected_components(const Request& request, bool publish) {
  require_parameters(request.parameters, {});
  auto input = load_mesh(request);
  require_pmp_mesh(input, "connected-components analysis");
  auto property = input.mesh.add_property_map<Face, std::size_t>("f:cc", 0).first;
  const auto count = PMP::connected_components(input.mesh, property);
  std::vector<std::vector<std::size_t>> members(count);
  for (const auto face : input.mesh.faces()) members[property[face]].push_back(face.idx());
  Json components = Json::array();
  std::size_t total = 0;
  for (std::size_t id = 0; id < members.size(); ++id) {
    total += members[id].size();
    components.push_back({{"id", id},
                          {"face_count", members[id].size()},
                          {"face_indices", members[id]}});
  }
  auto report = base_report(request, input, "connected_components");
  report["results"] = {{"component_count", count},
                       {"count_unit", "count"},
                       {"components", std::move(components)}};
  if (total != input.mesh.number_of_faces() ||
      report["results"]["components"].size() != count) {
    fail_report("Connected-components partition contract failed");
  }
  report["validation"]["passed"] = true;
  report["validation"]["checks"] =
      {"component_ids_contiguous", "all_faces_partitioned_once"};
  if (!publish) return report;
  return finish_report(request, std::move(report), "connected_components",
                       {{"component_count", count}, {"face_count", total}});
}

Json run_normals(const Request& request, bool publish) {
  require_parameters(request.parameters, {});
  require_approximate_output_profile(request, "Normal analysis");
  auto input = load_mesh(request);
  require_pmp_mesh(input, "normal analysis");
  const auto span = maximum_coordinate_span(input.raw);
  if (!std::isfinite(span)) {
    throw WorkerError("PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
                      "Normal analysis cannot normalize this coordinate span");
  }
  Point local_origin;
  auto analysis_mesh = normalized_local_frame(input.mesh, span, local_origin);
  auto face_normals =
      analysis_mesh.add_property_map<Face, Vector>("f:normal", CGAL::NULL_VECTOR)
          .first;
  auto vertex_normals =
      analysis_mesh.add_property_map<Vertex, Vector>("v:normal", CGAL::NULL_VECTOR)
          .first;
  PMP::compute_normals(analysis_mesh, vertex_normals, face_normals);
  Json faces_json = Json::array();
  Json vertices_json = Json::array();
  Json corners_json = Json::array();
  std::size_t zero_faces = 0;
  std::size_t zero_vertices = 0;
  for (const auto face : analysis_mesh.faces()) {
    const auto normal = vector_json(face_normals[face]);
    if (normal.at("zero").get<bool>()) ++zero_faces;
    faces_json.push_back({{"face", face.idx()}, {"normal", normal}});
    std::size_t corner = 0;
    for (const auto vertex : CGAL::vertices_around_face(
             analysis_mesh.halfedge(face), analysis_mesh)) {
      corners_json.push_back({{"face", face.idx()},
                              {"corner", corner++},
                              {"vertex", vertex.idx()},
                              {"normal", normal},
                              {"mode", "flat_face_normal"}});
    }
  }
  for (const auto vertex : analysis_mesh.vertices()) {
    const auto normal = vector_json(vertex_normals[vertex]);
    if (normal.at("zero").get<bool>()) ++zero_vertices;
    vertices_json.push_back({{"vertex", vertex.idx()}, {"normal", normal}});
  }
  const auto degenerates = degenerate_face_count(analysis_mesh);
  auto report = base_report(request, input, "normals");
  report["results"] = {{"face_normals", std::move(faces_json)},
                       {"vertex_normals", std::move(vertices_json)},
                       {"corner_normals", std::move(corners_json)},
                       {"corner_normal_mode", "flat_face_normal"},
                       {"count_unit", "count"},
                       {"degenerate_face_count", degenerates},
                       {"zero_face_normal_count", zero_faces},
                       {"zero_vertex_normal_count", zero_vertices}};
  if (report["results"]["face_normals"].size() !=
          input.mesh.number_of_faces() ||
      report["results"]["vertex_normals"].size() !=
          input.mesh.number_of_vertices() ||
      report["results"]["corner_normals"].size() !=
          3 * input.mesh.number_of_faces() || zero_faces != degenerates) {
    fail_report("Normal report cardinality contract failed");
  }
  const auto normals_are_unit_or_explicit_zero = [](const Json& values) {
    return std::all_of(values.begin(), values.end(), [](const Json& item) {
      const auto& normal = item.at("normal");
      return normal.value("zero", false) || normal.value("is_unit", false);
    });
  };
  if (!normals_are_unit_or_explicit_zero(report["results"]["face_normals"]) ||
      !normals_are_unit_or_explicit_zero(
          report["results"]["vertex_normals"]) ||
      !normals_are_unit_or_explicit_zero(
          report["results"]["corner_normals"])) {
    fail_report("Normal report contains a non-unit, nonzero vector");
  }
  report["validation"]["passed"] = true;
  report["validation"]["checks"] =
      {"face_normal_count", "vertex_normal_count", "corner_normal_count",
       "finite_vectors", "zero_normals_explicit"};
  if (!publish) return report;
  return finish_report(
      request, std::move(report), "normals",
      {{"face_normal_count", input.mesh.number_of_faces()},
       {"vertex_normal_count", input.mesh.number_of_vertices()},
       {"corner_normal_count", 3 * input.mesh.number_of_faces()},
       {"degenerate_face_count", degenerates},
       {"zero_face_normal_count", zero_faces},
       {"zero_vertex_normal_count", zero_vertices}});
}

Json run_measures(const Request& request, bool publish) {
  require_parameters(request.parameters, {});
  require_approximate_output_profile(request, "Measure analysis");
  auto input = load_mesh(request);
  require_pmp_mesh(input, "measure analysis");
  const auto& unit = request.inputs.front().unit;
  const auto span = maximum_coordinate_span(input.raw);
  Point local_origin;
  auto analysis_mesh = normalized_local_frame(input.mesh, span, local_origin);
  const auto scale = Kernel::FT(span > 0 && std::isfinite(span) ? span : 1.0);
  const auto degenerates = degenerate_face_count(analysis_mesh);
  auto report = base_report(request, input, "measures");
  auto& results = report["results"];
  if (!std::isfinite(span)) {
    results["surface_area"] = unavailable_measure(
        unit + "^2", "BINARY64_RESULT_NOT_REPRESENTABLE");
  } else {
    const auto area = PMP::area(analysis_mesh) * scale * scale;
    results["surface_area"] = scalar_measure(
        area, unit + "^2", true,
        degenerates < input.mesh.number_of_faces());
  }
  const bool closed = CGAL::is_closed(analysis_mesh);
  if (!closed) {
    results["signed_volume"] = {{"available", false},
                                 {"reason", "MESH_NOT_CLOSED"},
                                 {"unit", unit + "^3"}};
    results["absolute_volume"] = results["signed_volume"];
    results["volume_centroid"] = {{"available", false},
                                   {"reason", "MESH_NOT_CLOSED"},
                                   {"unit", unit}};
  } else if (!std::isfinite(span)) {
    results["signed_volume"] = unavailable_measure(
        unit + "^3", "BINARY64_RESULT_NOT_REPRESENTABLE");
    results["absolute_volume"] = results["signed_volume"];
    results["volume_centroid"] = unavailable_measure(
        unit, "BINARY64_RESULT_NOT_REPRESENTABLE");
  } else if (degenerates != 0) {
    results["signed_volume"] = unavailable_measure(
        unit + "^3", "DEGENERATE_FACES");
    results["absolute_volume"] = results["signed_volume"];
    results["volume_centroid"] = unavailable_measure(
        unit, "DEGENERATE_FACES");
  } else if (PMP::does_self_intersect(analysis_mesh)) {
    // PMP::does_bound_a_volume() has undefined behavior on self-intersecting
    // meshes. Keep surface area available, but never call the volume APIs for
    // this input.
    results["signed_volume"] = unavailable_measure(
        unit + "^3", "SELF_INTERSECTING_MESH");
    results["absolute_volume"] = results["signed_volume"];
    results["volume_centroid"] = unavailable_measure(
        unit, "SELF_INTERSECTING_MESH");
  } else if (!PMP::does_bound_a_volume(analysis_mesh)) {
    results["signed_volume"] = {{"available", false},
                                 {"reason", "MESH_DOES_NOT_BOUND_A_VOLUME"},
                                 {"unit", unit + "^3"}};
    results["absolute_volume"] = results["signed_volume"];
    results["volume_centroid"] = {{"available", false},
                                   {"reason", "MESH_DOES_NOT_BOUND_A_VOLUME"},
                                   {"unit", unit}};
  } else {
    const auto signed_volume =
        PMP::volume(analysis_mesh) * scale * scale * scale;
    if (signed_volume <= Kernel::FT(0)) {
      results["signed_volume"] = {{"available", false},
                                   {"reason", "NONPOSITIVE_ORIENTATION"},
                                   {"unit", unit + "^3"}};
      results["absolute_volume"] = results["signed_volume"];
      results["volume_centroid"] = {{"available", false},
                                     {"reason", "NONPOSITIVE_ORIENTATION"},
                                     {"unit", unit}};
    } else {
      results["signed_volume"] = scalar_measure(signed_volume, unit + "^3");
      results["absolute_volume"] = results["signed_volume"];
      results["volume_centroid"] = point_measure(
          local_origin + (PMP::centroid(analysis_mesh) - CGAL::ORIGIN) * scale,
          unit);
    }
  }
  if (!results["surface_area"].contains("available") ||
      !results["signed_volume"].contains("available") ||
      !results["volume_centroid"].contains("available")) {
    fail_report("Measure availability contract failed");
  }
  report["validation"]["passed"] = true;
  report["validation"]["checks"] =
      {"surface_area_dimension", "volume_preconditions_explicit",
       "volume_dimension", "centroid_dimension", "binary64_precision_gate"};
  if (!publish) return report;
  return finish_report(
      request, std::move(report), "measures",
      {{"surface_area_available", results["surface_area"].value("available", false)},
       {"volume_available", results["signed_volume"].value("available", false)},
       {"centroid_available", results["volume_centroid"].value("available", false)}});
}

Json run_sharp_features(const Request& request, bool publish) {
  require_approximate_output_profile(request, "Sharp-feature analysis");
  const auto degrees = typed_angle_degrees(request.parameters);
  auto input = load_mesh(request);
  require_pmp_mesh(input, "sharp-feature analysis");
  const auto span = maximum_coordinate_span(input.raw);
  if (!std::isfinite(span)) {
    throw WorkerError(
        "PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
        "Sharp-feature analysis cannot normalize this coordinate span");
  }
  Point local_origin;
  auto analysis_mesh = normalized_local_frame(input.mesh, span, local_origin);
  auto report = base_report(request, input, "sharp_features");
  auto& results = report["results"];
  results["angle"] = {{"value", degrees}, {"unit", "deg"}};
  results["count_unit"] = "count";
  const auto degenerates = degenerate_face_count(analysis_mesh);
  if (degenerates != 0) {
    results["features"] = {{"available", false},
                            {"reason", "DEGENERATE_FACES"}};
    results["degenerate_face_count"] = degenerates;
  } else {
    auto feature =
        analysis_mesh.add_property_map<Edge, bool>("e:feature", false).first;
    PMP::detect_sharp_edges(analysis_mesh, Kernel::FT(degrees), feature);
    Json edges_json = Json::array();
    std::size_t border_count = 0;
    for (const auto edge : analysis_mesh.edges()) {
      if (!feature[edge]) continue;
      const auto halfedge = analysis_mesh.halfedge(edge);
      const bool border = analysis_mesh.is_border(edge);
      if (border) ++border_count;
      edges_json.push_back({{"edge", edge.idx()},
                            {"vertices",
                             {analysis_mesh.source(halfedge).idx(),
                              analysis_mesh.target(halfedge).idx()}},
                            {"border", border}});
    }
    results["features"] = {{"available", true},
                            {"feature_edge_count", edges_json.size()},
                            {"border_feature_edge_count", border_count},
                            {"edges", std::move(edges_json)}};
  }
  if (!results["angle"].contains("unit") ||
      !results["features"].contains("available")) {
    fail_report("Sharp-feature report contract failed");
  }
  report["validation"]["passed"] = true;
  report["validation"]["checks"] =
      {"canonical_angle_degrees", "feature_edges_belong_to_source",
       "degenerate_unavailability_explicit"};
  if (!publish) return report;
  return finish_report(
      request, std::move(report), "sharp_features",
      {{"angle_degrees", degrees},
       {"features_available", results["features"].value("available", false)}});
}

struct PairLimitReached {};

Json run_self_intersections(const Request& request, bool publish) {
  require_parameters(request.parameters, {});
  auto input = load_mesh(request);
  require_pmp_mesh(input, "self-intersection analysis");
  const auto span = maximum_coordinate_span(input.raw);
  if (!std::isfinite(span)) {
    throw WorkerError(
        "PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
        "Self-intersection analysis cannot normalize this coordinate span");
  }
  Point local_origin;
  auto analysis_mesh = normalized_local_frame(input.mesh, span, local_origin);
  auto report = base_report(request, input, "self_intersections");
  auto& results = report["results"];
  const auto degenerates = degenerate_face_count(analysis_mesh);
  if (degenerates != 0) {
    results = {{"available", false},
               {"count_unit", "count"},
               {"reason", "DEGENERATE_FACES"},
               {"degenerate_face_count", degenerates}};
  } else {
    Json pairs = Json::array();
    bool truncated = false;
    try {
      auto sink = boost::make_function_output_iterator(
          [&](const std::pair<Face, Face>& pair) {
            if (pairs.size() >= kMaxIntersectionPairs) throw PairLimitReached{};
            pairs.push_back({pair.first.idx(), pair.second.idx()});
          });
      PMP::self_intersections<CGAL::Sequential_tag>(analysis_mesh, sink);
    } catch (const PairLimitReached&) {
      truncated = true;
    }
    results = {{"available", !truncated},
               {"count_unit", "count"},
               {"does_self_intersect", !pairs.empty()},
               {"intersection_pair_count",
                truncated ? Json(nullptr) : Json(pairs.size())},
               {"pair_limit", kMaxIntersectionPairs},
               {"pairs", std::move(pairs)}};
    if (truncated) results["reason"] = "INTERSECTION_PAIR_LIMIT_EXCEEDED";
  }
  if (!results.contains("available"))
    fail_report("Self-intersection availability contract failed");
  if (results.value("available", false) &&
      results.at("intersection_pair_count") != results.at("pairs").size())
    fail_report("Self-intersection pair count contract failed");
  report["validation"]["passed"] = true;
  report["validation"]["checks"] =
      {"source_face_pairs", "pair_count_consistent",
       "bounded_pair_collection", "degenerate_unavailability_explicit"};
  if (!publish) return report;
  return finish_report(
      request, std::move(report), "self_intersections",
      {{"available", results.value("available", false)},
       {"does_self_intersect", results.value("does_self_intersect", false)}});
}

OperationDefinition make_definition(std::string id,
                                    std::function<Json(const Request&)> execute,
                                    Json info,
                                    std::vector<std::string> input_types =
                                        {"TriangleSurfaceMesh"}) {
  OperationDefinition definition{std::move(id),
                                 1,
                                 std::move(input_types),
                                 "GeometryAnalysisReport",
                                 "analysis",
                                 std::move(execute)};
  definition.supported_kernels = {"exact_constructions", "package_recommended"};
  definition.effective_kernel =
      "CGAL::Exact_predicates_exact_constructions_kernel";
  definition.dependencies = {"Polygon_mesh_processing", "Surface_mesh"};
  definition.info = std::move(info);
  return definition;
}

Json common_info(const std::string& kind, const std::string& header,
                 const std::string& validator) {
  const std::map<std::string, std::string> source_hashes = {
      {"CGAL/boost/graph/helpers.h",
       "a9e73905b62e1426775fe77d90aea0a803b50a18a735923062baf7c0beca2767"},
      {"CGAL/Polygon_mesh_processing/connected_components.h",
       "3f980c0349166a44c80e990fdf83a91086bee637e4850c44c1ff295fda594e70"},
      {"CGAL/Polygon_mesh_processing/compute_normal.h",
       "bc53b2e20f93dddaa467bd59d344ff3f7396b41dd280835961159b77711abc40"},
      {"CGAL/Polygon_mesh_processing/measure.h",
       "ba707292f05045a0c6eea3d73c3b21435673f440f4461b5ac5cf19542f6c540b"},
      {"CGAL/Polygon_mesh_processing/detect_features.h",
       "0fda63d13f171d8a107a1cb96db9545fa19802eacae419df0498c9838669724c"},
      {"CGAL/Polygon_mesh_processing/self_intersections.h",
       "d459c0e6480a9e1c2cbef291340ae61a0bf4e79ceb182365c1b922dd7e38ae8f"}};
  return {{"analysis_kind", kind},
          {"input_format", "off"},
          {"input_slot", "mesh"},
          {"input_units", {"mm", "cm", "m"}},
          {"output_format", "json"},
          {"output_slot", "analysis"},
          {"output_unit", "none"},
          {"geometry_mutation", false},
          {"source_header", header},
          {"source_sha256", source_hashes.at(header)},
          {"source_kind", "official_release"},
          {"source_version", "6.2.1"},
          {"license_expression",
           "GPL-3.0-or-later OR LicenseRef-Commercial"},
          {"producer_diagnostic_id", "mesh.producer_check." + kind},
          {"validators", {validator}},
          {"validator_artifact_bindings",
           {{validator,
             {{"candidate", {{"output", "analysis"}}},
              {"source", {{"input", "mesh"}}}}}}},
          {"report_schema", "GeometryAnalysisReport/v1"},
          {"report_schema_version", 1},
          {"max_report_bytes", kMaxReportBytes},
          {"result_enumeration",
           {{"policy", "atomic_report_or_resource_limit"},
            {"max_report_bytes", kMaxReportBytes}}}};
}

}  // namespace

Json analysis_reference_report(const std::string& operation_id,
                               const Request& source_request) {
  if (operation_id == "mesh.inspect.pmp")
    return run_inspect(source_request, false);
  if (operation_id == "mesh.analysis.connected_components")
    return run_connected_components(source_request, false);
  if (operation_id == "mesh.analysis.normals")
    return run_normals(source_request, false);
  if (operation_id == "mesh.analysis.measures")
    return run_measures(source_request, false);
  if (operation_id == "mesh.analysis.sharp_features")
    return run_sharp_features(source_request, false);
  if (operation_id == "mesh.analysis.self_intersections")
    return run_self_intersections(source_request, false);
  throw WorkerError("UNSUPPORTED_ADAPTER", "UNKNOWN_ANALYSIS_REFERENCE",
                    "No Wave A mesh reference implementation is registered");
}

OperationDefinition inspect_pmp_operation() {
  auto info = common_info("pmp_inspection", "CGAL/boost/graph/helpers.h",
                          "mesh.validate.pmp_inspection_report");
  info["tolerates_unconstructible_graph"] = true;
  info["accepted_geometry_types"] = {"TriangleSurfaceMesh", "PolygonSoup3"};
  info["checks"] = {"finite_coordinates", "indices_valid", "triangulated",
                    "polygon_mesh_valid", "closed", "degenerate_faces",
                    "non_manifold_vertices", "isolated_vertices"};
  return make_definition(
      "mesh.inspect.pmp",
      [](const Request& request) { return run_inspect(request, true); },
      std::move(info), {"TriangleSurfaceMesh", "PolygonSoup3"});
}

OperationDefinition connected_components_operation() {
  auto info = common_info(
      "connected_components",
      "CGAL/Polygon_mesh_processing/connected_components.h",
      "mesh.validate.connected_components_report");
  info["checks"] = {"component_ids_contiguous", "all_faces_partitioned_once"};
  return make_definition("mesh.analysis.connected_components",
                         [](const Request& request) {
                           return run_connected_components(request, true);
                         },
                         std::move(info));
}

OperationDefinition normals_operation() {
  auto info = common_info("normals",
                          "CGAL/Polygon_mesh_processing/compute_normal.h",
                          "mesh.validate.normals_report");
  info["normal_modes"] = {"face", "vertex", "corner_flat"};
  info["checks"] = {"normal_cardinality", "finite_vectors",
                    "unit_or_explicit_zero", "face_degeneracy_consistent"};
  info["precision_contract"] =
      {{"internal_kernel", "EPECK"},
       {"reported_values", "normalized IEEE-754 binary64 vectors"},
       {"exact_irrational_output", false}};
  auto definition = make_definition(
      "mesh.analysis.normals",
      [](const Request& request) { return run_normals(request, true); },
      std::move(info));
  definition.supported_kernels = {"package_recommended"};
  return definition;
}

OperationDefinition measures_operation() {
  auto info = common_info("measures",
                          "CGAL/Polygon_mesh_processing/measure.h",
                          "mesh.validate.measures_report");
  info["measure_dimensions"] = {{"surface_area", "length^2"},
                                 {"signed_volume", "length^3"},
                                 {"absolute_volume", "length^3"},
                                 {"volume_centroid", "length"}};
  info["volume_preconditions"] = {"closed", "non_degenerate",
                                   "non_self_intersecting", "bounds_volume",
                                   "positive_orientation"};
  info["checks"] = {"typed_dimensions", "availability_reasons",
                    "self_intersection_gate_before_volume",
                    "binary64_precision_gate"};
  info["additional_source_headers"] =
      {{{"header", "CGAL/Polygon_mesh_processing/self_intersections.h"},
        {"sha256",
         "d459c0e6480a9e1c2cbef291340ae61a0bf4e79ceb182365c1b922dd7e38ae8f"}}};
  info["precision_contract"] =
      {{"internal_kernel", "EPECK"},
       {"surface_area", "approximate square root then binary64"},
       {"signed_volume", "exact internal rational then binary64"},
       {"volume_centroid", "exact internal rational then binary64"},
       {"unrepresentable", "explicit unavailable reason"}};
  auto definition = make_definition(
      "mesh.analysis.measures",
      [](const Request& request) { return run_measures(request, true); },
      std::move(info));
  definition.supported_kernels = {"package_recommended"};
  return definition;
}

OperationDefinition sharp_features_operation() {
  auto info = common_info("sharp_features",
                          "CGAL/Polygon_mesh_processing/detect_features.h",
                          "mesh.validate.sharp_features_report");
  info["required_parameters"] = {"angle"};
  info["angle_units"] = {"deg", "rad"};
  info["validator_parameter_bindings"] =
      {{"mesh.validate.sharp_features_report", {{"angle", "angle"}}}};
  info["checks"] = {"canonical_angle_degrees",
                    "feature_edges_belong_to_source"};
  info["precision_contract"] =
      {{"internal_kernel", "EPECK"},
       {"angle_threshold", "IEEE-754 binary64 degrees"},
       {"threshold_decision", "CGAL approximate trigonometric comparison"}};
  auto definition = make_definition(
      "mesh.analysis.sharp_features",
      [](const Request& request) { return run_sharp_features(request, true); },
      std::move(info));
  definition.supported_kernels = {"package_recommended"};
  return definition;
}

OperationDefinition self_intersections_operation() {
  auto info = common_info(
      "self_intersections",
      "CGAL/Polygon_mesh_processing/self_intersections.h",
      "mesh.validate.self_intersections_report");
  info["pair_limit"] = kMaxIntersectionPairs;
  info["checks"] = {"source_face_pairs", "pair_count_consistent",
                    "bounded_pair_collection"};
  return make_definition("mesh.analysis.self_intersections",
                         [](const Request& request) {
                           return run_self_intersections(request, true);
                         },
                         std::move(info));
}

}  // namespace cgal_master::wave_a_mesh
