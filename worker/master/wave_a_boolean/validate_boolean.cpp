#include "wave_a_boolean_operations.h"

#include "boolean_common.h"

#include "../artifact_io.h"

namespace cgal_master::wave_a_boolean {
namespace {

Json execute_validator(const Request& request, BooleanKind kind) {
  require_boolean_request(request, kind, true);
  Mesh candidate;
  try {
    candidate = read_boolean_candidate(request.inputs[0]);
  } catch (const WorkerError& error) {
    if (error.error_class == "PRECONDITION_FAILED") {
      throw WorkerError("VALIDATION_FAILED",
                        "BOOLEAN_CANDIDATE_" + error.code,
                        std::string("Candidate topology failed validation: ") +
                            error.what());
    }
    throw;
  }
  const auto source_a = read_boolean_source(request.inputs[1], "Boolean source A");
  const auto source_b = read_boolean_source(request.inputs[2], "Boolean source B");
  const auto reference = compute_boolean(source_a, source_b, kind);
  const auto checks =
      validate_boolean_semantics(source_a, source_b, candidate, kind, reference);
  const Json report = {
      {"schema_version", 1},
      {"schema", "ValidationReport/v1"},
      {"status", "pass"},
      {"validator_id", validator_id(kind)},
      {"validates", operation_id(kind)},
      {"passed", true},
      {"operation", operation_name(kind)},
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
      {{"validator_id", validator_id(kind)},
       {"passed", true},
       {"result_status", checks.at("result_status")},
       {"candidate_sha256", request.inputs[0].sha256},
       {"source_a_sha256", request.inputs[1].sha256},
       {"source_b_sha256", request.inputs[2].sha256}});
}

OperationDefinition definition(BooleanKind kind) {
  OperationDefinition result{
      validator_id(kind),
      1,
      {"TriangleSurfaceMesh", "TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "ValidationReport",
      "validator",
      [kind](const Request& request) { return execute_validator(request, kind); }};
  result.supported_kernels = {"exact_constructions", "package_recommended"};
  result.effective_kernel =
      "CGAL::Exact_predicates_exact_constructions_kernel";
  result.dependencies = {"Polygon_mesh_processing", "Surface_mesh", "AABB_tree"};
  result.info = {
      {"validates", operation_id(kind)},
      {"boolean_operation", operation_name(kind)},
      {"artifact_bindings",
       {{"candidate", {{"output", "geometry"}}},
        {"source_a", {{"input", "source_a"}}},
        {"source_b", {{"input", "source_b"}}}}},
      {"parameter_bindings", {{"operation", {{"parameter", "operation"}}}}},
      {"required_checks",
       {"topology_valid", "closed_or_canonical_empty",
        "volume_boundary_orientation_valid", "self_intersection_free",
        "operation_parameter_bound", "result_status_matches_reference",
        "exact_volume_matches_reference", "mutual_exact_difference_empty",
        "operation_classification_matches"}},
      {"report_schema", "ValidationReport/v1"},
      {"required_report_checks",
       {{"schema_version", 1},
        {"schema", "ValidationReport/v1"},
        {"status", "pass"},
        {"validator_id", validator_id(kind)},
        {"validates", operation_id(kind)},
        {"passed", true},
        {"operation", operation_name(kind)},
        {"bindings.operation_parameter", operation_name(kind)},
        {"checks.topology_valid", true},
        {"checks.closed_or_canonical_empty", true},
        {"checks.volume_boundary_orientation_valid", true},
        {"checks.self_intersection_free", true},
        {"checks.operation_parameter_bound", true},
        {"checks.result_status_matches_reference", true},
        {"checks.exact_volume_matches_reference", true},
        {"checks.mutual_exact_difference_empty", true},
        {"checks.operation_classification_matches", true}}},
      {"precision_contract",
       {{"internal_kernel", "EPECK"},
        {"input_coordinate_storage",
         "IEEE-754 binary64 converted to exact binary-rational coordinates"},
        {"reference_comparison",
         "exact EPECK Boolean replay, exact signed volume, and mutual exact set difference"},
        {"report_numeric_storage",
         "booleans and exact rational strings; no approximate tolerance"}}},
      {"source_headers",
       {"CGAL/Polygon_mesh_processing/corefinement.h",
        "CGAL/Side_of_triangle_mesh.h"}},
      {"source_sha256",
       {{"CGAL/Polygon_mesh_processing/corefinement.h",
         "16db532539a0fa937ef8ee41409785fa6d97ee7cfaec856aaa424a09981654c5"},
        {"CGAL/Side_of_triangle_mesh.h",
         "3c0b35fa40276bfa70c20a710b7321ba935b228e3e4f657181233e936fbe77a4"}}},
      {"source_kind", "official_release"},
      {"source_version", "6.2.1"},
      {"license_expression", "GPL-3.0-or-later OR LicenseRef-Commercial"}};
  return result;
}

}  // namespace

OperationDefinition validate_boolean_union_operation() {
  return definition(BooleanKind::kUnion);
}

OperationDefinition validate_boolean_intersection_operation() {
  return definition(BooleanKind::kIntersection);
}

OperationDefinition validate_boolean_difference_operation() {
  return definition(BooleanKind::kDifference);
}

}  // namespace cgal_master::wave_a_boolean
