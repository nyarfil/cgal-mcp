#include "wave_a_boolean_operations.h"

#include "boolean_common.h"

#include "../artifact_io.h"

#include <string>

namespace cgal_master::wave_a_boolean {
namespace {

Json execute_boolean(const Request& request, BooleanKind kind) {
  require_boolean_request(request, kind, false);
  const auto source_a = read_boolean_source(request.inputs[0], "Boolean source A");
  const auto source_b = read_boolean_source(request.inputs[1], "Boolean source B");
  const auto result = compute_boolean(source_a, source_b, kind);
  const auto path = write_boolean_mesh(request, result.mesh);
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
       {"output_vertices", result.mesh.number_of_vertices()},
       {"output_faces", result.mesh.number_of_faces()},
       {"exact_volume", exact_number(result.volume)},
       {"volume_unit", request.inputs[0].unit + "^3"},
       {"effective_kernel",
        "CGAL::Exact_predicates_exact_constructions_kernel"},
       {"output_coordinate_storage", "IEEE-754 binary64 exact-only"}});
}

OperationDefinition definition(BooleanKind kind) {
  const auto id = operation_id(kind);
  const auto validation = validator_id(kind);
  OperationDefinition result{
      id,
      1,
      {"TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "TriangleSurfaceMesh",
      "transform",
      [kind](const Request& request) { return execute_boolean(request, kind); }};
  result.supported_kernels = {"exact_constructions", "package_recommended"};
  result.effective_kernel =
      "CGAL::Exact_predicates_exact_constructions_kernel";
  result.dependencies = {"Polygon_mesh_processing", "Surface_mesh", "AABB_tree"};
  result.info = {
      {"boolean_operation", operation_name(kind)},
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
      {"source_sha256",
       "16db532539a0fa937ef8ee41409785fa6d97ee7cfaec856aaa424a09981654c5"},
      {"source_kind", "official_release"},
      {"source_version", "6.2.1"},
      {"license_expression", "GPL-3.0-or-later OR LicenseRef-Commercial"},
      {"validators", {validation}},
      {"validator_artifact_bindings",
       {{validation,
         {{"candidate", {{"output", "geometry"}}},
          {"source_a", {{"input", "source_a"}}},
          {"source_b", {{"input", "source_b"}}}}}}},
      {"validator_parameter_bindings",
       {{validation, {{"operation", "operation"}}}}},
      {"precision_contract",
       {{"internal_kernel", "EPECK"},
        {"input_coordinate_storage",
         "IEEE-754 binary64 converted to exact binary-rational coordinates"},
        {"output_coordinate_storage", "IEEE-754 binary64 ASCII OFF"},
        {"unrepresentable_policy",
         "NUMERIC_FAILURE/OUTPUT_BINARY64_LOSS; no silent rounding"}}}};
  return result;
}

}  // namespace

OperationDefinition boolean_union_operation() {
  return definition(BooleanKind::kUnion);
}

OperationDefinition boolean_intersection_operation() {
  return definition(BooleanKind::kIntersection);
}

OperationDefinition boolean_difference_operation() {
  return definition(BooleanKind::kDifference);
}

}  // namespace cgal_master::wave_a_boolean
