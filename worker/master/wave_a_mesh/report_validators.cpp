#include "wave_a_mesh_operations.h"

#include "../artifact_io.h"
#include "../sha256.h"

#include <algorithm>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <functional>
#include <set>
#include <string>
#include <utility>

namespace cgal_master::wave_a_mesh {
namespace {

constexpr std::uintmax_t kMaxReportBytes = 16ULL * 1024ULL * 1024ULL;

struct ValidatorProfile {
  std::string id;
  std::string analysis_operation;
  std::string analysis_kind;
  bool binds_angle = false;
  bool package_recommended_only = false;
  bool accepts_polygon_soup = false;
};

bool has_exact_keys(const Json& value,
                    std::initializer_list<const char*> required) {
  if (!value.is_object() || value.size() != required.size()) return false;
  return std::all_of(required.begin(), required.end(),
                     [&](const char* key) { return value.contains(key); });
}

bool string_array(const Json& value) {
  return value.is_array() &&
         std::all_of(value.begin(), value.end(),
                     [](const Json& item) { return item.is_string(); });
}

bool common_report_schema_valid(const Json& candidate) {
  if (!has_exact_keys(candidate,
                      {"schema_version", "analysis_kind", "source",
                       "mesh_summary", "results", "validation"}) ||
      !candidate.at("schema_version").is_number_integer() ||
      candidate.at("schema_version") != Json(1) ||
      !candidate.at("analysis_kind").is_string() ||
      !has_exact_keys(candidate.at("source"),
                      {"artifact_id", "type", "format", "unit", "sha256"}) ||
      !candidate.at("mesh_summary").is_object() ||
      !candidate.at("results").is_object() ||
      !has_exact_keys(candidate.at("validation"),
                      {"validator_id", "authoritative", "passed", "checks"}))
    return false;
  const auto& source = candidate.at("source");
  for (const auto* key : {"artifact_id", "type", "format", "unit", "sha256"})
    if (!source.at(key).is_string()) return false;
  const auto& validation = candidate.at("validation");
  return validation.at("validator_id").is_string() &&
         validation.at("authoritative").is_boolean() &&
         validation.at("passed").is_boolean() &&
         string_array(validation.at("checks"));
}

std::string verified_report_bytes(const ArtifactInput& candidate) {
  std::error_code error;
  const auto canonical = std::filesystem::canonical(candidate.path, error);
  if (error || !std::filesystem::is_regular_file(canonical, error) || error) {
    throw WorkerError("INVALID_INPUT", "INPUT_NOT_REGULAR_FILE",
                      "Candidate analysis report must be a regular file");
  }
  const auto size = std::filesystem::file_size(canonical, error);
  if (error) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Cannot stat candidate analysis report");
  }
  if (size > kMaxReportBytes) {
    throw WorkerError("RESOURCE_LIMIT", "REPORT_SIZE_LIMIT_EXCEEDED",
                      "Candidate analysis report exceeds 16 MiB");
  }
  std::ifstream stream(canonical, std::ios::binary);
  if (!stream) {
    throw WorkerError("INVALID_INPUT", "INPUT_OPEN_FAILED",
                      "Cannot open candidate analysis report");
  }
  std::string bytes((std::istreambuf_iterator<char>(stream)),
                    std::istreambuf_iterator<char>());
  if (!stream.eof() && stream.fail()) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Cannot read candidate analysis report");
  }
  if (sha256_bytes(bytes) != candidate.sha256) {
    throw WorkerError("INVALID_INPUT", "DIGEST_MISMATCH",
                      "Candidate report sha256 does not match parsed bytes");
  }
  return bytes;
}

bool recursively_finite(const Json& value) {
  if (value.is_number_float()) return std::isfinite(value.get<double>());
  if (value.is_array())
    return std::all_of(value.begin(), value.end(), recursively_finite);
  if (value.is_object())
    return std::all_of(value.begin(), value.end(),
                       [](const auto& item) {
                         return recursively_finite(item);
                       });
  return true;
}

Json read_candidate(const ArtifactInput& input) {
  if (input.type != "GeometryAnalysisReport" || input.format != "json" ||
      input.unit != "none") {
    throw WorkerError(
        "INVALID_INPUT", "INPUT_TYPE_OR_FORMAT_MISMATCH",
        "Validator candidate must be GeometryAnalysisReport/json/none");
  }
  Json report;
  try {
    report = Json::parse(verified_report_bytes(input));
  } catch (const Json::exception&) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_ANALYSIS_REPORT",
                      "Candidate analysis report is not strict JSON");
  }
  if (!recursively_finite(report)) {
    throw WorkerError("INVALID_INPUT", "NONFINITE_ANALYSIS_REPORT",
                      "Candidate analysis report contains nonfinite numbers");
  }
  return report;
}

void require_validator_request(const Request& request,
                               const ValidatorProfile& profile) {
  if (profile.package_recommended_only &&
      request.kernel != "package_recommended") {
    throw WorkerError(
        "UNSUPPORTED", "OUTPUT_PRECISION_PROFILE_UNSUPPORTED",
        "This validator replays an approximate-output analysis and supports "
        "only package_recommended");
  }
  if (request.inputs.size() != 2) {
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "Analysis validator requires candidate then source mesh");
  }
  const auto& source = request.inputs[1];
  const bool source_type_supported =
      source.type == "TriangleSurfaceMesh" ||
      (profile.accepts_polygon_soup && source.type == "PolygonSoup3");
  if (!source_type_supported || source.format != "off" ||
      (source.unit != "mm" && source.unit != "cm" && source.unit != "m")) {
    throw WorkerError("INVALID_INPUT", "INPUT_TYPE_OR_FORMAT_MISMATCH",
                      profile.accepts_polygon_soup
                          ? "Inspection validator source must be "
                            "TriangleSurfaceMesh or PolygonSoup3 in OFF format"
                          : "Validator source must be TriangleSurfaceMesh/OFF");
  }
  if (!profile.binds_angle && !request.parameters.empty()) {
    throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PARAMETER",
                      "This analysis validator accepts no parameters");
  }
  if (profile.binds_angle &&
      (!request.parameters.is_object() ||
       !request.parameters.contains("angle") ||
       request.parameters.size() != 1)) {
    throw WorkerError("INVALID_INPUT", "MISSING_OR_INVALID_PARAMETER",
                      "Sharp-feature validator requires bound angle");
  }
}

bool dimensions_valid(const Json& candidate, const ValidatorProfile& profile,
                      const std::string& unit) {
  try {
    const auto& results = candidate.at("results");
    if (profile.analysis_kind == "measures") {
      const auto typed = [&](const char* name, const std::string& expected) {
        const auto& value = results.at(name);
        if (!value.is_object() || value.value("unit", "") != expected ||
            !value.contains("available") || !value.at("available").is_boolean())
          return false;
        if (value.at("available").get<bool>())
          return value.contains("value");
        return value.contains("reason") && value.at("reason").is_string() &&
               !value.at("reason").get<std::string>().empty();
      };
      return typed("surface_area", unit + "^2") &&
             typed("signed_volume", unit + "^3") &&
             typed("absolute_volume", unit + "^3") &&
             typed("volume_centroid", unit);
    }
    if (profile.analysis_kind == "normals") {
      for (const auto* field : {"face_normals", "vertex_normals",
                                "corner_normals"}) {
        if (!results.at(field).is_array()) return false;
        for (const auto& item : results.at(field)) {
          const auto& normal = item.at("normal");
          if (!normal.is_object() || normal.value("unit", "") != "none" ||
              !normal.contains("is_unit") || !normal.contains("zero"))
            return false;
        }
      }
    }
    if (profile.analysis_kind == "sharp_features")
      return results.at("angle").is_object() &&
             results.at("angle").value("unit", "") == "deg" &&
             results.value("count_unit", "") == "count";
    if (profile.analysis_kind == "pmp_inspection" ||
        profile.analysis_kind == "connected_components" ||
        profile.analysis_kind == "normals" ||
        profile.analysis_kind == "self_intersections")
      return results.value("count_unit", "") == "count";
    return true;
  } catch (const Json::exception&) {
    return false;
  }
}

Json write_validation(const Request& request, const ValidatorProfile& profile,
                      const Json& checks) {
  Json validation = {
      {"schema_version", 1},
      {"validator_id", profile.id},
      {"candidate_sha256", request.inputs[0].sha256},
      {"source_sha256", request.inputs[1].sha256},
      {"status", "pass"},
      {"passed", true},
      {"checks", checks}};
  const auto destination =
      output_path(checked_output_dir(request), "validation.json");
  const auto temporary = destination.parent_path() /
                         (".validation.json." +
                          staging_filename_token(request.request_id) + ".tmp");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("IO_FAILURE", "TEMPORARY_OUTPUT_EXISTS",
                      "Temporary validation report path is not clean");
  }
  std::ofstream output(temporary, std::ios::binary);
  output << validation.dump() << '\n';
  output.close();
  if (!output) {
    std::filesystem::remove(temporary);
    throw WorkerError("IO_FAILURE", "OUTPUT_WRITE_FAILED",
                      "Cannot write validation report");
  }
  commit_output(temporary, destination);
  return success_result(
      request,
      Json::array({{{"slot", "validation"},
                    {"type", "ValidationReport"},
                    {"unit", "none"},
                    {"format", "json"},
                    {"path", portable_path(destination)}}}),
      {{"validator_id", profile.id},
       {"candidate_sha256", request.inputs[0].sha256},
       {"source_sha256", request.inputs[1].sha256}});
}

Json validate_report(const Request& request, const ValidatorProfile& profile) {
  require_validator_request(request, profile);
  const auto candidate = read_candidate(request.inputs[0]);
  const auto& source = request.inputs[1];
  const bool schema_valid = common_report_schema_valid(candidate);
  if (!schema_valid) {
    throw WorkerError("VALIDATION_FAILED", "REPORT_SCHEMA_MISMATCH",
                      "Candidate does not satisfy GeometryAnalysisReport/v1");
  }
  const Json expected_source = {
      {"artifact_id", source.artifact_id}, {"type", source.type},
      {"format", source.format},           {"unit", source.unit},
      {"sha256", source.sha256}};
  const bool source_identity_matches = candidate.at("source") == expected_source;
  const bool analysis_kind_matches =
      candidate.value("analysis_kind", "") == profile.analysis_kind;
  if (!source_identity_matches || !analysis_kind_matches) {
    throw WorkerError("VALIDATION_FAILED", "REPORT_IDENTITY_MISMATCH",
                      "Candidate report identity does not match source and operation");
  }
  Request replay = request;
  replay.operation = profile.analysis_operation;
  replay.inputs = {source};
  const auto reference =
      analysis_reference_report(profile.analysis_operation, replay);
  const bool dimensions = dimensions_valid(candidate, profile, source.unit);
  const bool producer_diagnostic_matches =
      candidate.at("validation") == reference.at("validation");
  const bool semantics =
      candidate.at("mesh_summary") == reference.at("mesh_summary") &&
      candidate.at("results") == reference.at("results");
  if (!dimensions) {
    throw WorkerError("VALIDATION_FAILED", "REPORT_DIMENSION_MISMATCH",
                      "Candidate report contains invalid dimensional units");
  }
  if (!semantics) {
    throw WorkerError("VALIDATION_FAILED", "REPORT_SEMANTICS_MISMATCH",
                      "Candidate results differ from official CGAL replay");
  }
  if (!producer_diagnostic_matches) {
    throw WorkerError(
        "VALIDATION_FAILED", "REPORT_PRODUCER_DIAGNOSTIC_MISMATCH",
        "Candidate producer diagnostic differs from the replayed report");
  }
  Json checks = {{"schema_valid", true},
                 {"source_identity_matches", true},
                 {"analysis_kind_matches", true},
                 {"dimension_units_valid", true},
                 {"result_semantics_valid", true},
                 {"producer_diagnostic_matches", true},
                 {"official_cgal_reference_match", true}};
  return write_validation(request, profile, checks);
}

OperationDefinition validator_definition(ValidatorProfile profile,
                                         Json extra_info = Json::object()) {
  const auto id = profile.id;
  const auto package_recommended_only = profile.package_recommended_only;
  Json info = {
      {"validates", profile.analysis_operation},
      {"report_schema", "ValidationReport/v1"},
      {"candidate_report_schema", "GeometryAnalysisReport/v1"},
      {"max_candidate_report_bytes", kMaxReportBytes},
      {"artifact_bindings",
       {{"candidate", {{"output", "analysis"}}},
        {"source", {{"input", "mesh"}}}}},
      {"required_checks",
       {"schema_valid", "source_identity_matches", "analysis_kind_matches",
        "dimension_units_valid", "result_semantics_valid",
        "producer_diagnostic_matches",
        "official_cgal_reference_match"}},
      {"required_report_checks",
       {{"schema_version", 1},
        {"validator_id", profile.id},
        {"status", "pass"},
        {"passed", true},
        {"checks.schema_valid", true},
        {"checks.source_identity_matches", true},
        {"checks.analysis_kind_matches", true},
        {"checks.dimension_units_valid", true},
         {"checks.result_semantics_valid", true},
         {"checks.producer_diagnostic_matches", true},
         {"checks.official_cgal_reference_match", true}}}};
  info.update(extra_info);
  std::vector<std::string> input_types = {"GeometryAnalysisReport",
                                           "TriangleSurfaceMesh"};
  if (profile.accepts_polygon_soup) input_types.push_back("PolygonSoup3");
  OperationDefinition definition{
      id,
      1,
      std::move(input_types),
      "ValidationReport",
      "validator",
      [profile = std::move(profile)](const Request& request) {
        return validate_report(request, profile);
      }};
  definition.supported_kernels = {"exact_constructions", "package_recommended"};
  if (package_recommended_only)
    definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel =
      "CGAL::Exact_predicates_exact_constructions_kernel";
  definition.dependencies = {"Polygon_mesh_processing", "Surface_mesh"};
  definition.info = std::move(info);
  return definition;
}

}  // namespace

OperationDefinition validate_pmp_inspection_report_operation() {
  return validator_definition({"mesh.validate.pmp_inspection_report",
                               "mesh.inspect.pmp", "pmp_inspection", false,
                               false, true});
}

OperationDefinition validate_connected_components_report_operation() {
  return validator_definition({"mesh.validate.connected_components_report",
                               "mesh.analysis.connected_components",
                               "connected_components"});
}

OperationDefinition validate_normals_report_operation() {
  return validator_definition({"mesh.validate.normals_report",
                               "mesh.analysis.normals", "normals", false,
                               true},
                              {{"independent_fixture_contract",
                                "analytic face-normal direction"}});
}

OperationDefinition validate_measures_report_operation() {
  return validator_definition({"mesh.validate.measures_report",
                               "mesh.analysis.measures", "measures", false,
                               true},
                              {{"independent_fixture_contract",
                                "analytic tetra area-volume-centroid"}});
}

OperationDefinition validate_sharp_features_report_operation() {
  return validator_definition(
      {"mesh.validate.sharp_features_report",
       "mesh.analysis.sharp_features", "sharp_features", true, true},
      {{"parameter_bindings", {{"angle", {{"parameter", "angle"}}}}}});
}

OperationDefinition validate_self_intersections_report_operation() {
  return validator_definition({"mesh.validate.self_intersections_report",
                               "mesh.analysis.self_intersections",
                               "self_intersections"});
}

}  // namespace cgal_master::wave_a_mesh
