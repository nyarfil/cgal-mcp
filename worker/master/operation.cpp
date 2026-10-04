#include "operation.h"
#include "wave_a/wave_a_operations.h"
#include "wave_b/wave_b_operations.h"
#include "wave_a_mesh/wave_a_mesh_operations.h"
#include "wave_a_boolean/wave_a_boolean_operations.h"

#include <CGAL/version.h>

#ifndef CGAL_MASTER_SOURCE_KIND
#define CGAL_MASTER_SOURCE_KIND "unspecified"
#endif

#ifndef CGAL_MASTER_SOURCE_SHA256
#define CGAL_MASTER_SOURCE_SHA256 ""
#endif

#define CGAL_MASTER_STRINGIFY_DETAIL(value) #value
#define CGAL_MASTER_STRINGIFY(value) CGAL_MASTER_STRINGIFY_DETAIL(value)

namespace cgal_master {
namespace {

Json compiler_manifest() {
#if defined(_MSC_VER)
  return Json{{"family", "msvc"},
              {"version", _MSC_VER},
              {"full_version", _MSC_FULL_VER}};
#elif defined(__clang__)
  return Json{{"family", "clang"}, {"version", __clang_version__}};
#elif defined(__GNUC__)
  return Json{{"family", "gcc"}, {"version", __VERSION__}};
#else
  return Json{{"family", "unknown"}, {"version", "unknown"}};
#endif
}

}  // namespace

const std::vector<OperationDefinition>& operation_registry() {
  static const std::vector<OperationDefinition> registry = {
      convex_hull_operation(),
      convex_enclosure_validator_operation(),
      wave_a::simplify_edge_collapse_operation(),
      wave_a::simplification_integrity_validator_operation(),
      wave_a::symmetric_hausdorff_operation(),
      wave_b::remove_outliers_operation(),
      wave_b::grid_simplify_operation(),
      wave_b::random_simplify_operation(),
      wave_b::hierarchy_simplify_operation(),
      wave_b::jet_smooth_operation(),
      wave_b::estimate_normals_operation(),
      wave_b::orient_normals_mst_operation(),
      wave_b::pointset_basic_validator_operation(),
      wave_b::pointset_subset_validator_operation(),
      wave_b::pointset_smoothed_validator_operation(),
      wave_b::pointset_normals_estimated_validator_operation(),
      wave_b::pointset_normals_oriented_validator_operation(),
      wave_a_mesh::inspect_pmp_operation(),
      wave_a_mesh::connected_components_operation(),
      wave_a_mesh::normals_operation(),
      wave_a_mesh::measures_operation(),
      wave_a_mesh::sharp_features_operation(),
      wave_a_mesh::self_intersections_operation(),
      wave_a_mesh::validate_pmp_inspection_report_operation(),
      wave_a_mesh::validate_connected_components_report_operation(),
      wave_a_mesh::validate_normals_report_operation(),
      wave_a_mesh::validate_measures_report_operation(),
      wave_a_mesh::validate_sharp_features_report_operation(),
      wave_a_mesh::validate_self_intersections_report_operation(),
      wave_a_boolean::boolean_union_operation(),
      wave_a_boolean::boolean_intersection_operation(),
      wave_a_boolean::boolean_difference_operation(),
      wave_a_boolean::validate_boolean_union_operation(),
      wave_a_boolean::validate_boolean_intersection_operation(),
      wave_a_boolean::validate_boolean_difference_operation()};
  return registry;
}

Json dispatch(const Request& request) {
  for (const auto& operation : operation_registry()) {
    if (operation.id == request.operation) return operation.execute(request);
  }
  throw WorkerError("UNSUPPORTED", "UNKNOWN_OPERATION",
                    "Operation is not registered: " + request.operation);
}

Json manifest() {
  Json operations = Json::array();
  for (const auto& operation : operation_registry()) {
    operations.push_back(
        {{"id", operation.id},
         {"revision", operation.revision},
         {"input_types", operation.input_types},
         {"output_type", operation.output_type},
         {"role", operation.role},
         {"supported_kernels", operation.supported_kernels},
         {"effective_kernel", operation.effective_kernel},
         {"dependencies", operation.dependencies},
         {"info", operation.info}});
  }
  const std::string actual_version = CGAL_MASTER_STRINGIFY(CGAL_VERSION);
  const std::string source_kind = CGAL_MASTER_SOURCE_KIND;
  Json build = {{"cgal_version", actual_version},
                {"cgal_version_nr", CGAL_VERSION_NR},
                {"cgal_release_date", CGAL_RELEASE_DATE},
                {"compiler", compiler_manifest()},
                {"source_kind", source_kind},
                {"source_sha256", CGAL_MASTER_SOURCE_SHA256},
                {"source_attestation",
                 source_kind == "official_release"
                     ? "configured_pinned_official_archive"
                     : "configured_unverified"}};
  return Json{{"protocol", 1},
              {"worker", "cgal-master-worker"},
              {"actual_cgal_version", actual_version},
              {"request_model", "one_json_line_per_process"},
              {"resource_enforcement", "parent_supervisor"},
              {"supported_kernels",
               Json::array({"exact_constructions", "package_recommended"})},
              {"build", std::move(build)},
              {"operations", std::move(operations)}};
}

}  // namespace cgal_master
