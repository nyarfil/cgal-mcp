// mesh.boolean.rounded and mesh.validate.boolean_rounded.
//
// The exact Boolean handlers publish a result only when every exact coordinate is a binary64
// value, which holds for axis-aligned dyadic inputs and almost never for general meshes. This
// pair covers general inputs: the producer computes the same exact EPECK corefinement, replaces
// each coordinate by a neighbouring binary64 value and refuses the result if rounding broke the
// mesh. The validator replays the exact Boolean and accepts the candidate only within a stated
// absolute tolerance (see boolean_common.h); it certifies closeness, not exact set equality.

#include "wave_a_boolean_operations.h"

#include "boolean_common.h"

#include "../artifact_io.h"

#include <string>

namespace cgal_master::wave_a_boolean {
namespace {

constexpr const char* kOperationId = "mesh.boolean.rounded";
constexpr const char* kValidatorId = "mesh.validate.boolean_rounded";

BooleanKind require_rounded_request(const Request& request, bool validator) {
  if (request.kernel != "exact_constructions" && request.kernel != "package_recommended") {
    throw WorkerError("UNSUPPORTED_ADAPTER", "UNSUPPORTED_KERNEL",
                      "Rounded PMP Boolean supports exact_constructions and package_recommended, both mapped to EPECK");
  }
  const std::size_t expected = validator ? 3 : 2;
  if (request.inputs.size() != expected) {
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH", "Rounded Boolean request has the wrong input count");
  }
  const auto& unit = request.inputs.front().unit;
  for (const auto& input : request.inputs) {
    if (input.unit != unit) {
      throw WorkerError("INVALID_INPUT", "UNIT_MISMATCH", "Both Boolean sources and candidate must use one unit");
    }
  }
  if (request.parameters.size() != 1 || !request.parameters.contains("operation") ||
      !request.parameters.at("operation").is_string()) {
    throw WorkerError("INVALID_INPUT", "BOOLEAN_OPERATION_BINDING_MISMATCH",
                      "The only parameter is operation: union, intersection or difference");
  }
  const auto name = request.parameters.at("operation").get<std::string>();
  if (name == "union") return BooleanKind::kUnion;
  if (name == "intersection") return BooleanKind::kIntersection;
  if (name == "difference") return BooleanKind::kDifference;
  throw WorkerError("INVALID_INPUT", "BOOLEAN_OPERATION_BINDING_MISMATCH",
                    "operation must be union, intersection or difference");
}

Json execute_rounded(const Request& request) {
  const auto kind = require_rounded_request(request, false);
  const auto source_a = read_boolean_source(request.inputs[0], "Boolean source A");
  const auto source_b = read_boolean_source(request.inputs[1], "Boolean source B");
  const auto result = compute_boolean(source_a, source_b, kind);
  const auto rounded = round_boolean_mesh(result.mesh);
  const auto path = write_boolean_mesh(request, rounded);
  return success_result(
      request,
      Json::array({{{"slot", "geometry"},
                    {"type", "TriangleSurfaceMesh"},
                    {"unit", request.inputs[0].unit},
                    {"format", "off"},
                    {"path", portable_path(path)}}}),
      {{"operation", operation_name(kind)},
       {"result_status", result.empty ? "empty" : "volume"},
       {"empty_reason", result.empty ? result.empty_reason : ""},
       {"surfaces_contact", result.surfaces_contact},
       {"output_vertices", rounded.number_of_vertices()},
       {"output_faces", rounded.number_of_faces()},
       {"exact_volume_before_rounding", exact_number(result.volume)},
       {"rounded_volume", exact_number(mesh_volume(rounded))},
       {"volume_unit", request.inputs[0].unit + "^3"},
       {"tolerance", rounded_tolerance(source_a, source_b)},
       {"effective_kernel", "CGAL::Exact_predicates_exact_constructions_kernel"},
       {"output_coordinate_storage", "IEEE-754 binary64, rounded from exact coordinates"}});
}

Json execute_rounded_validator(const Request& request) {
  const auto kind = require_rounded_request(request, true);
  Mesh candidate;
  try {
    candidate = read_boolean_candidate(request.inputs[0]);
  } catch (const WorkerError& error) {
    if (error.error_class == "PRECONDITION_FAILED") {
      throw WorkerError("VALIDATION_FAILED", "BOOLEAN_CANDIDATE_" + error.code,
                        std::string("Candidate topology failed validation: ") + error.what());
    }
    throw;
  }
  const auto source_a = read_boolean_source(request.inputs[1], "Boolean source A");
  const auto source_b = read_boolean_source(request.inputs[2], "Boolean source B");
  const auto reference = compute_boolean(source_a, source_b, kind);
  const auto checks = validate_boolean_rounded(source_a, source_b, candidate, kind, reference);
  const Json report = {{"schema_version", 1},
                       {"schema", "ValidationReport/v1"},
                       {"status", "pass"},
                       {"validator_id", kValidatorId},
                       {"validates", kOperationId},
                       {"passed", true},
                       {"operation", operation_name(kind)},
                       {"comparison", "tolerance"},
                       {"bindings",
                        {{"candidate_sha256", request.inputs[0].sha256},
                         {"source_a_sha256", request.inputs[1].sha256},
                         {"source_b_sha256", request.inputs[2].sha256},
                         {"unit", request.inputs[0].unit},
                         {"operation_parameter", request.parameters.at("operation")}}},
                       {"checks", checks}};
  const auto path = write_boolean_validation(request, report);
  return success_result(
      request,
      Json::array({{{"slot", "validation"},
                    {"type", "ValidationReport"},
                    {"unit", "none"},
                    {"format", "json"},
                    {"path", portable_path(path)}}}),
      {{"validator_id", kValidatorId},
       {"passed", true},
       {"result_status", checks.at("result_status")},
       {"tolerance", checks.at("tolerance")},
       {"candidate_sha256", request.inputs[0].sha256},
       {"source_a_sha256", request.inputs[1].sha256},
       {"source_b_sha256", request.inputs[2].sha256}});
}

Json precision_contract() {
  return {{"internal_kernel", "EPECK"},
          {"input_coordinate_storage", "IEEE-754 binary64 converted to exact binary-rational coordinates"},
          {"output_coordinate_storage", "IEEE-754 binary64 ASCII OFF, rounded from the exact result"},
          {"rounding_policy",
           "each exact coordinate is replaced by a neighbouring binary64 value; a rounded mesh that is not a healthy volume boundary is refused (NUMERIC_FAILURE/ROUNDING_INVALIDATED_RESULT)"},
          {"tolerance_rule", "2^-40 times the power of two above the largest absolute source coordinate"}};
}

}  // namespace

OperationDefinition boolean_rounded_operation() {
  OperationDefinition result{kOperationId, 1, {"TriangleSurfaceMesh", "TriangleSurfaceMesh"},
                             "TriangleSurfaceMesh", "transform", execute_rounded};
  result.supported_kernels = {"exact_constructions", "package_recommended"};
  result.effective_kernel = "CGAL::Exact_predicates_exact_constructions_kernel";
  result.dependencies = {"Polygon_mesh_processing", "Surface_mesh", "AABB_tree"};
  result.info = {
      {"boolean_operations", {"union", "intersection", "difference"}},
      {"input_format", "off"},
      {"input_slots", {"source_a", "source_b"}},
      {"input_units", {"mm", "cm", "m"}},
      {"output_format", "off"},
      {"output_slot", "geometry"},
      {"output_unit_from", "source_a"},
      {"same_unit_inputs", true},
      {"empty_output", "canonical ASCII OFF with zero vertices and faces"},
      {"source_mutation", false},
      {"source_header", "CGAL/Polygon_mesh_processing/corefinement.h"},
      {"source_sha256", "16db532539a0fa937ef8ee41409785fa6d97ee7cfaec856aaa424a09981654c5"},
      {"source_kind", "official_release"},
      {"source_version", "6.2.1"},
      {"license_expression", "GPL-3.0-or-later OR LicenseRef-Commercial"},
      {"validators", {kValidatorId}},
      {"validator_artifact_bindings",
       {{kValidatorId,
         {{"candidate", {{"output", "geometry"}}},
          {"source_a", {{"input", "source_a"}}},
          {"source_b", {{"input", "source_b"}}}}}}},
      {"validator_parameter_bindings", {{kValidatorId, {{"operation", "operation"}}}}},
      {"precision_contract", precision_contract()}};
  return result;
}

OperationDefinition validate_boolean_rounded_operation() {
  OperationDefinition result{kValidatorId, 1,
                             {"TriangleSurfaceMesh", "TriangleSurfaceMesh", "TriangleSurfaceMesh"},
                             "ValidationReport", "validator", execute_rounded_validator};
  result.supported_kernels = {"exact_constructions", "package_recommended"};
  result.effective_kernel = "CGAL::Exact_predicates_exact_constructions_kernel";
  result.dependencies = {"Polygon_mesh_processing", "Surface_mesh", "AABB_tree"};
  result.info = {
      {"validates", kOperationId},
      {"artifact_bindings",
       {{"candidate", {{"output", "geometry"}}},
        {"source_a", {{"input", "source_a"}}},
        {"source_b", {{"input", "source_b"}}}}},
      {"parameter_bindings", {{"operation", {{"parameter", "operation"}}}}},
      {"required_checks",
       {"topology_valid", "closed_or_canonical_empty", "volume_boundary_orientation_valid",
        "self_intersection_free", "operation_parameter_bound", "result_status_matches_reference",
        "element_counts_match_reference", "volume_within_tolerance_of_reference",
        "candidate_vertices_within_tolerance_of_reference_surface",
        "reference_vertices_within_tolerance_of_candidate_surface"}},
      {"report_schema", "ValidationReport/v1"},
      {"independence",
       "exact EPECK replay of the same CGAL corefinement; the candidate is compared by exact volume and exact vertex-to-witness-triangle distances against a stated tolerance. This is a replay check, not a CGAL-free oracle, and it does not prove exact set equality"},
      {"precision_contract", precision_contract()},
      {"source_headers", {"CGAL/Polygon_mesh_processing/corefinement.h", "CGAL/AABB_tree.h"}},
      {"source_kind", "official_release"},
      {"source_version", "6.2.1"},
      {"license_expression", "GPL-3.0-or-later OR LicenseRef-Commercial"}};
  return result;
}

}  // namespace cgal_master::wave_a_boolean
