#include "spatial_operations.h"

#include "../artifact_io.h"
#include "../sha256.h"
#include "../wave_a/mesh_io.h"

#include <CGAL/AABB_face_graph_triangle_primitive.h>
#include <CGAL/AABB_traits_3.h>
#include <CGAL/AABB_tree.h>
#include <CGAL/Polygon_mesh_processing/shape_predicates.h>
#include <CGAL/boost/graph/helpers.h>
#include <CGAL/number_utils.h>

#include <cmath>
#include <filesystem>
#include <fstream>
#include <limits>
#include <set>
#include <string>
#include <vector>

namespace cgal_master::spatial {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;
using Kernel = wave_a::Kernel;
using Point = Kernel::Point_3;
using Mesh = wave_a::Mesh;
using Primitive = CGAL::AABB_face_graph_triangle_primitive<Mesh>;
using Traits = CGAL::AABB_traits_3<Kernel, Primitive>;
using Tree = CGAL::AABB_tree<Traits>;

constexpr std::size_t kMaxReportBytes = 1024ULL * 1024ULL;
const std::set<std::string> kLengthUnits = {"mm", "cm", "m"};

double unit_in_metres(const std::string& unit) {
  if (unit == "mm") return 0.001;
  if (unit == "cm") return 0.01;
  if (unit == "m") return 1.0;
  throw WorkerError("INVALID_INPUT", "UNSUPPORTED_UNIT",
                    "AABB query unit must be mm, cm, or m");
}

void require_parameters(const Json& parameters) {
  if (!parameters.is_object() || parameters.size() != 1 ||
      !parameters.contains("query") || !parameters.at("query").is_object()) {
    throw WorkerError(
        "INVALID_INPUT", "INVALID_AABB_QUERY",
        "AABB closest-point requires only query={value:[x,y,z],unit}");
  }
  const auto& query = parameters.at("query");
  if (query.size() != 2 || !query.contains("value") ||
      !query.contains("unit") || !query.at("value").is_array() ||
      query.at("value").size() != 3 || !query.at("unit").is_string()) {
    throw WorkerError(
        "INVALID_INPUT", "INVALID_AABB_QUERY",
        "query must contain exactly value:[x,y,z] and unit");
  }
  for (const auto& coordinate : query.at("value")) {
    if (!coordinate.is_number() ||
        !std::isfinite(coordinate.get<double>())) {
      throw WorkerError("INVALID_INPUT", "INVALID_AABB_QUERY",
                        "query coordinates must be finite numbers");
    }
  }
  if (kLengthUnits.count(query.at("unit").get<std::string>()) == 0) {
    throw WorkerError("INVALID_INPUT", "UNSUPPORTED_UNIT",
                      "query unit must be mm, cm, or m");
  }
}

Point query_point(const Request& request, const std::string& mesh_unit) {
  require_parameters(request.parameters);
  const auto& query = request.parameters.at("query");
  const auto unit = query.at("unit").get<std::string>();
  const auto scale = unit_in_metres(unit) / unit_in_metres(mesh_unit);
  const auto& values = query.at("value");
  const double x = values.at(0).get<double>() * scale;
  const double y = values.at(1).get<double>() * scale;
  const double z = values.at(2).get<double>() * scale;
  if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
    throw WorkerError("INVALID_INPUT", "AABB_QUERY_CONVERSION_OVERFLOW",
                      "query is not representable in the mesh unit");
  }
  return Point(x, y, z);
}

void require_request(const Request& request, bool validator) {
  if (request.kernel != "package_recommended") {
    throw WorkerError(
        "UNSUPPORTED", "UNSUPPORTED_KERNEL",
        "AABB closest-point uses the package_recommended EPICK profile");
  }
  const std::size_t expected_inputs = validator ? 2 : 1;
  if (request.inputs.size() != expected_inputs) {
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "AABB closest-point input count is invalid");
  }
  require_parameters(request.parameters);
}

Mesh source_mesh(const ArtifactInput& input) {
  auto mesh = wave_a::read_triangle_off(input);
  if (mesh.number_of_faces() == 0) {
    throw WorkerError("PRECONDITION_FAILED", "EMPTY_MESH",
                      "AABB Tree requires at least one triangle");
  }
  for (const auto face : mesh.faces()) {
    if (PMP::is_degenerate_triangle_face(face, mesh)) {
      throw WorkerError(
          "PRECONDITION_FAILED", "DEGENERATE_AABB_PRIMITIVE",
          "AABB Tree input contains a degenerate triangle primitive");
    }
  }
  return mesh;
}

Json source_descriptor(const ArtifactInput& input) {
  return {{"artifact_id", input.artifact_id},
          {"type", input.type},
          {"format", input.format},
          {"unit", input.unit},
          {"sha256", input.sha256}};
}

Json point_json(const Point& point, const std::string& unit) {
  const double x = CGAL::to_double(point.x());
  const double y = CGAL::to_double(point.y());
  const double z = CGAL::to_double(point.z());
  if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
    throw WorkerError("NUMERIC_FAILURE", "AABB_RESULT_NOT_BINARY64",
                      "closest point is not representable in binary64");
  }
  return {{"value", {x, y, z}}, {"unit", unit}};
}

Json canonical_query_json(const Point& point, const std::string& unit) {
  return point_json(point, unit);
}

Json compute_report(const Request& request, const ArtifactInput& source) {
  auto mesh = source_mesh(source);
  const auto query = query_point(request, source.unit);

  Tree tree(faces(mesh).first, faces(mesh).second, mesh);
  tree.accelerate_distance_queries();

  const auto closest = tree.closest_point_and_primitive(query);
  const auto squared = tree.squared_distance(query);
  const double squared_value = CGAL::to_double(squared);
  if (!std::isfinite(squared_value) || squared_value < 0) {
    throw WorkerError("NUMERIC_FAILURE", "AABB_DISTANCE_NOT_BINARY64",
                      "squared distance is not representable in binary64");
  }
  const double distance = std::sqrt(squared_value);
  if (!std::isfinite(distance)) {
    throw WorkerError("NUMERIC_FAILURE", "AABB_DISTANCE_NOT_BINARY64",
                      "distance is not representable in binary64");
  }

  return {
      {"schema_version", 1},
      {"analysis_kind", "aabb_closest_point"},
      {"source", source_descriptor(source)},
      {"query", canonical_query_json(query, source.unit)},
      {"results",
       {{"closest_point", point_json(closest.first, source.unit)},
        {"squared_distance",
         {{"value", squared_value}, {"unit", source.unit + "^2"}}},
        {"distance", {{"value", distance}, {"unit", source.unit}}},
        {"closest_face_index", closest.second.idx()},
        {"primitive_count", mesh.number_of_faces()},
        {"distance_acceleration", true}}},
      {"validation",
       {{"validator_id", "spatial.producer_check.aabb_closest_point"},
        {"authoritative", false},
        {"passed", true}}}};
}

std::filesystem::path write_json(const Request& request,
                                 const std::string& filename,
                                 const Json& report) {
  const auto directory = checked_output_dir(request);
  const auto destination = output_path(directory, filename);
  const auto temporary =
      directory / ("." + staging_filename_token(request.request_id) +
                   "." + filename + ".tmp");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("IO_FAILURE", "TEMPORARY_OUTPUT_EXISTS",
                      "AABB report temporary path is not clean");
  }
  const auto bytes = report.dump();
  if (bytes.size() + 1 > kMaxReportBytes) {
    throw WorkerError("RESOURCE_LIMIT", "REPORT_SIZE_LIMIT_EXCEEDED",
                      "AABB report exceeds the 1 MiB limit");
  }
  {
    std::ofstream output(temporary, std::ios::binary);
    output << bytes << '\n';
    if (!output) {
      output.close();
      std::filesystem::remove(temporary);
      throw WorkerError("IO_FAILURE", "OUTPUT_WRITE_FAILED",
                        "Unable to write AABB report");
    }
  }
  commit_output(temporary, destination);
  return destination;
}

std::string verified_report_bytes(const ArtifactInput& input) {
  if (input.type != "GeometryAnalysisReport" || input.format != "json" ||
      input.unit != "none") {
    throw WorkerError("INVALID_INPUT", "INPUT_TYPE_OR_FORMAT_MISMATCH",
                      "AABB validator candidate must be GeometryAnalysisReport/json");
  }
  std::error_code error;
  const auto canonical = std::filesystem::canonical(input.path, error);
  if (error || !std::filesystem::is_regular_file(canonical, error) || error) {
    throw WorkerError("INVALID_INPUT", "INPUT_NOT_REGULAR_FILE",
                      "AABB validator candidate must be a regular file");
  }
  const auto size = std::filesystem::file_size(canonical, error);
  if (error || size > kMaxReportBytes) {
    throw WorkerError("RESOURCE_LIMIT", "REPORT_SIZE_LIMIT_EXCEEDED",
                      "AABB candidate report exceeds the 1 MiB limit");
  }
  std::ifstream stream(canonical, std::ios::binary);
  std::string bytes((std::istreambuf_iterator<char>(stream)),
                    std::istreambuf_iterator<char>());
  if (!stream.eof() && stream.fail()) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Unable to read AABB candidate report");
  }
  if (sha256_bytes(bytes) != input.sha256) {
    throw WorkerError("INVALID_INPUT", "DIGEST_MISMATCH",
                      "AABB candidate sha256 does not match request");
  }
  return bytes;
}

Json read_candidate(const ArtifactInput& input) {
  try {
    return Json::parse(verified_report_bytes(input));
  } catch (const Json::exception&) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_JSON",
                      "AABB candidate report is not valid JSON");
  }
}

Json run_analysis(const Request& request) {
  require_request(request, false);
  const auto report = compute_report(request, request.inputs.front());
  const auto path = write_json(request, "analysis.json", report);
  return success_result(
      request,
      Json::array({{{"slot", "analysis"},
                    {"type", "GeometryAnalysisReport"},
                    {"unit", "none"},
                    {"format", "json"},
                    {"path", portable_path(path)}}}),
      {{"analysis_kind", "aabb_closest_point"},
       {"source_sha256", request.inputs.front().sha256},
       {"primitive_count", report.at("results").at("primitive_count")},
       {"distance_acceleration", true}});
}

Json run_validator(const Request& request) {
  require_request(request, true);
  const auto& candidate_input = request.inputs.at(0);
  const auto& source = request.inputs.at(1);
  const auto candidate = read_candidate(candidate_input);
  const auto reference = compute_report(request, source);

  Json checks = {
      {"schema_valid",
       candidate.value("schema_version", 0) == 1 &&
           candidate.value("analysis_kind", "") == "aabb_closest_point" &&
           candidate.contains("source") && candidate.contains("query") &&
           candidate.contains("results")},
      {"source_identity_matches",
       candidate.contains("source") &&
           candidate.at("source").value("sha256", "") == source.sha256 &&
           candidate.at("source").value("unit", "") == source.unit},
      {"query_matches_reference",
       candidate.contains("query") &&
           candidate.at("query") == reference.at("query")},
      {"closest_point_matches_reference",
       candidate.contains("results") &&
           candidate.at("results").contains("closest_point") &&
           candidate.at("results").at("closest_point") ==
               reference.at("results").at("closest_point")},
      {"distance_matches_reference",
       candidate.contains("results") &&
           candidate.at("results").contains("distance") &&
           candidate.at("results").contains("squared_distance") &&
           candidate.at("results").at("distance") ==
               reference.at("results").at("distance") &&
           candidate.at("results").at("squared_distance") ==
               reference.at("results").at("squared_distance")},
      {"primitive_matches_reference",
       candidate.contains("results") &&
           candidate.at("results").contains("closest_face_index") &&
           candidate.at("results").at("closest_face_index") ==
               reference.at("results").at("closest_face_index")},
  };
  bool passed = true;
  for (auto it = checks.begin(); it != checks.end(); ++it)
    passed = passed && it.value().is_boolean() && it.value().get<bool>();
  if (!passed) {
    throw WorkerError("VALIDATION_FAILED", "AABB_REPORT_MISMATCH",
                      "AABB closest-point report does not match official CGAL replay");
  }

  Json report = {
      {"schema_version", 1},
      {"schema", "ValidationReport/v1"},
      {"status", "pass"},
      {"validator_id", "spatial.validate.aabb_closest_point"},
      {"validates", "spatial.aabb.closest_point"},
      {"passed", true},
      {"candidate_sha256", candidate_input.sha256},
      {"source_sha256", source.sha256},
      {"checks", checks}};
  const auto path = write_json(request, "validation.json", report);
  return success_result(
      request,
      Json::array({{{"slot", "validation"},
                    {"type", "ValidationReport"},
                    {"unit", "none"},
                    {"format", "json"},
                    {"path", portable_path(path)}}}),
      {{"validator_id", "spatial.validate.aabb_closest_point"},
       {"source_sha256", source.sha256}});
}

Json analysis_info() {
  return {
      {"analysis_kind", "aabb_closest_point"},
      {"input_format", "off"},
      {"input_slot", "mesh"},
      {"input_units", {"mm", "cm", "m"}},
      {"output_format", "json"},
      {"output_slot", "analysis"},
      {"output_unit", "none"},
      {"geometry_mutation", false},
      {"source_header", "CGAL/AABB_tree.h"},
      {"source_version", "6.2.1"},
      {"source_kind", "official_release"},
      {"distance_acceleration", "AABB_tree::accelerate_distance_queries"},
      {"degenerate_primitive_policy", "reject"},
      {"validators", {"spatial.validate.aabb_closest_point"}},
      {"validator_parameter_bindings",
       {{"spatial.validate.aabb_closest_point", {{"query", "query"}}}}},
      {"precision_contract",
       {{"internal_kernel", "EPICK"},
        {"input_coordinates", "IEEE-754 binary64"},
        {"reported_values", "IEEE-754 binary64"},
        {"exact_constructions", false}}}};
}

Json validator_info() {
  return {
      {"validates", "spatial.aabb.closest_point"},
      {"report_schema", "ValidationReport/v1"},
      {"artifact_bindings",
       {{"candidate", {{"output", "analysis"}}},
        {"source", {{"input", "mesh"}}}}},
      {"parameter_bindings", {{"query", {{"parameter", "query"}}}}},
      {"required_checks",
       {"schema_valid", "source_identity_matches", "query_matches_reference",
        "closest_point_matches_reference", "distance_matches_reference",
        "primitive_matches_reference"}},
      {"reference", "fresh official CGAL AABB_tree replay"}};
}

}  // namespace

OperationDefinition aabb_closest_point_operation() {
  OperationDefinition definition{
      "spatial.aabb.closest_point",
      1,
      {"TriangleSurfaceMesh"},
      "GeometryAnalysisReport",
      "analysis",
      [](const Request& request) { return run_analysis(request); }};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel =
      "CGAL::Exact_predicates_inexact_constructions_kernel";
  definition.dependencies = {"AABB_tree", "Surface_mesh"};
  definition.info = analysis_info();
  return definition;
}

OperationDefinition validate_aabb_closest_point_operation() {
  OperationDefinition definition{
      "spatial.validate.aabb_closest_point",
      1,
      {"GeometryAnalysisReport", "TriangleSurfaceMesh"},
      "ValidationReport",
      "validator",
      [](const Request& request) { return run_validator(request); }};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel =
      "CGAL::Exact_predicates_inexact_constructions_kernel";
  definition.dependencies = {"AABB_tree", "Surface_mesh"};
  definition.info = validator_info();
  return definition;
}

}  // namespace cgal_master::spatial
