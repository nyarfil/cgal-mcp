#include "repair_common.h"

#include "../artifact_io.h"

#include <array>
#include <map>

namespace cgal_master::wave_a_repair {
namespace {

const std::array<RepairKind, 6> kKinds = {
    RepairKind::kOrient, RepairKind::kStitchBorders,
    RepairKind::kRemoveDegenerate, RepairKind::kFillHoles,
    RepairKind::kPolygonSoup, RepairKind::kManifoldPreprocess};

std::vector<std::string> source_types(RepairKind kind) {
  if (kind == RepairKind::kOrient || kind == RepairKind::kPolygonSoup)
    return {"PolygonSoup3"};
  if (kind == RepairKind::kRemoveDegenerate)
    return {"PolygonSoup3", "TriangleSurfaceMesh"};
  return {"TriangleSurfaceMesh"};
}

std::string output_type(RepairKind kind) {
  return kind == RepairKind::kPolygonSoup ? "PolygonSoup3" : "TriangleSurfaceMesh";
}

Json source_record(RepairKind kind) {
  switch (kind) {
    case RepairKind::kOrient:
      return {{"header", "CGAL/Polygon_mesh_processing/orient_polygon_soup.h"},
              {"sha256", "ce58927a46f32174b69d693f55995a55b7e0cffbc322299fd2924d75305887fb"},
              {"identifiers", {"orient_polygon_soup", "orient_to_bound_a_volume"}}};
    case RepairKind::kStitchBorders:
      return {{"header", "CGAL/Polygon_mesh_processing/stitch_borders.h"},
              {"sha256", "cd09f6b1127eeb1926768405189459cfde11efc29f695f4ffd0666f747aa1644"},
              {"identifiers", {"stitch_borders"}}};
    case RepairKind::kRemoveDegenerate:
      return {{"header", "CGAL/Polygon_mesh_processing/repair_degeneracies.h"},
              {"sha256", "89278c2446e0efd977145ee2edc2b39ac40e9304e4b25caeaf4d2708984eae3a"},
              {"identifiers", {"remove_degenerate_faces", "remove_degenerate_edges"}}};
    case RepairKind::kFillHoles:
      return {{"header", "CGAL/Polygon_mesh_processing/triangulate_hole.h"},
              {"sha256", "b1a20a8eac2144e612df15b78a4ef045d6d7540b3ab13bb12044f40d94cb8118"},
              {"identifiers", {"triangulate_hole"}}};
    case RepairKind::kPolygonSoup:
      return {{"header", "CGAL/Polygon_mesh_processing/repair_polygon_soup.h"},
              {"sha256", "068e1c62d7a0dce7cf861876be21cfbddf8c15989c730e2e4f507df0cc67f9ef"},
              {"identifiers", {"repair_polygon_soup"}}};
    case RepairKind::kManifoldPreprocess:
      return {{"header", "CGAL/Polygon_mesh_processing/manifoldness.h"},
              {"sha256", "b7089cd3b24ca28b030da574086e27e051f8092e3b02be8e581828583127a91f"},
              {"identifiers", {"duplicate_non_manifold_vertices", "is_non_manifold_vertex"}}};
  }
  throw std::logic_error("Unknown repair kind");
}

Json parameter_schema(RepairKind kind) {
  if (kind == RepairKind::kFillHoles) {
    return {{"type", "object"},
            {"required", {"max_hole_edges"}},
            {"additionalProperties", false},
            {"properties", {{"max_hole_edges", {{"type", "integer"}, {"minimum", 3}, {"maximum", 100000}}}}}};
  }
  if (kind == RepairKind::kPolygonSoup) {
    return {{"type", "object"},
            {"required", {"duplicate_polygon_policy", "require_same_orientation"}},
            {"additionalProperties", false},
            {"properties",
             {{"duplicate_polygon_policy", {{"type", "string"}, {"enum", {"keep_one", "erase_all", "keep_one_if_odd"}}}},
              {"require_same_orientation", {{"type", "boolean"}}}}}};
  }
  return {{"type", "object"}, {"maxProperties", 0}, {"additionalProperties", false}};
}

Json parameter_bindings(RepairKind kind) {
  if (kind == RepairKind::kFillHoles)
    return {{validator_id(kind), {{"max_hole_edges", "max_hole_edges"}}}};
  if (kind == RepairKind::kPolygonSoup)
    return {{validator_id(kind),
             {{"duplicate_polygon_policy", "duplicate_polygon_policy"},
              {"require_same_orientation", "require_same_orientation"}}}};
  return {{validator_id(kind), Json::object()}};
}

}  // namespace

Json operation_metadata(RepairKind kind, bool validator) {
  const auto transform = operation_id(kind);
  const auto validation = validator_id(kind);
  Json common = {
      {"source_kind", "official_release"},
      {"source_version", "6.2.1"},
      {"source", source_record(kind)},
      {"package_ids", {"PMP_Mesh_repair"}},
      {"license_expression", "GPL-3.0-or-later OR LicenseRef-Commercial"},
      {"license_evidence",
       {{"path", "include/CGAL/license/gpl_package_list.txt"},
        {"sha256", "efb290ee3ef3d8b7675896bc037f1c9359f583543ca9e38bcb425fe34a8995db"},
        {"license_path", "LICENSE.GPL"},
        {"license_sha256", "416213203479e27015c32d9e8b30f80a287962a46750441b2223706cdd392116"}}},
      {"input_format", "off"},
      {"input_units", {"mm", "cm", "m"}},
      {"output_format", validator ? "json" : "off"},
      {"source_mutation", false},
      {"numeric_scale_contract",
       {{"minimum_span", 1e-100},
        {"maximum_absolute_coordinate", 1e100},
        {"maximum_translation_to_span_ratio", 1e6}}},
      {"precision_contract",
       {{"effective_kernel", "CGAL::Exact_predicates_inexact_constructions_kernel"},
        {"supported_request_kernel", "package_recommended"},
        {"exact_constructions", "unsupported_fail_closed"},
        {"coordinate_storage", "IEEE-754 binary64"}}}};
  if (!validator) {
    common["output_slot"] = "geometry";
    common["output_unit_from"] = "source";
    common["parameter_schema"] = parameter_schema(kind);
    common["validators"] = {validation};
    common["validator_artifact_bindings"] =
        {{validation,
          {{"candidate", {{"output", "geometry"}}},
           {"source", {{"input", "source"}}}}}};
    common["validator_parameter_bindings"] = parameter_bindings(kind);
    common["bounded_profile"] = "triangle ASCII OFF; one explicit CGAL repair family per operation";
  } else {
    common["output_slot"] = "validation";
    common["output_unit"] = "none";
    common["validators"] = Json::array();
    common["terminal_validator"] = true;
    common["validates"] = transform;
    common["parameter_schema"] = parameter_schema(kind);
    common["required_report_checks"] = {
        {"schema_version", 1}, {"status", "pass"}, {"passed", true},
        {"validator_id", validation}, {"validates", transform},
        {"checks.source_identity_matches", true},
        {"checks.candidate_matches_official_cgal_replay", true},
        {"checks.candidate_unit_matches_source", true},
        {"checks.repair_invariant_valid", true},
        {"checks.numeric_profile_valid", true},
        {"checks.source_geometry_preserved_as_required", true}};
  }
  return common;
}

namespace {

Json execute_repair(const Request& request, RepairKind kind) {
  require_request(request, kind, false);
  const auto source = read_soup(request.inputs[0], source_types(kind));
  const auto result = compute_repair(kind, source, request.parameters);
  const auto path = write_soup_output(request, result.soup, "geometry.off");
  auto metrics = result.metrics;
  metrics["operation"] = operation_id(kind);
  metrics["source_sha256"] = request.inputs[0].sha256;
  metrics["effective_kernel"] = "CGAL::Exact_predicates_inexact_constructions_kernel";
  return success_result(
      request,
      Json::array({{{"slot", "geometry"}, {"type", output_type(kind)},
                    {"unit", request.inputs[0].unit}, {"format", "off"},
                    {"path", portable_path(path)}}}),
      std::move(metrics));
}

OperationDefinition definition(RepairKind kind) {
  OperationDefinition operation{
      operation_id(kind), 1, source_types(kind), output_type(kind), "transform",
      [kind](const Request& request) { return execute_repair(request, kind); }};
  operation.supported_kernels = {"package_recommended"};
  operation.effective_kernel = "CGAL::Exact_predicates_inexact_constructions_kernel";
  operation.dependencies = {"Polygon_mesh_processing", "Surface_mesh"};
  operation.info = operation_metadata(kind, false);
  return operation;
}

}  // namespace

std::vector<OperationDefinition> repair_operations() {
  std::vector<OperationDefinition> result;
  for (const auto kind : kKinds) result.push_back(definition(kind));
  return result;
}

}  // namespace cgal_master::wave_a_repair
