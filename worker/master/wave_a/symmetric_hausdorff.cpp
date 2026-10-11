#include "mesh_io.h"
#include "wave_a_operations.h"
#include "../session_cache.h"

#include <CGAL/Polygon_mesh_processing/distance.h>

#include <algorithm>
#include <cmath>
#include <set>
#include <string>

namespace cgal_master::wave_a {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;

void require_allowed_parameters(const Json& parameters) {
  static const std::set<std::string> allowed = {"tolerance", "error_bound"};
  if (parameters.size() != allowed.size()) {
    throw WorkerError(
        "INVALID_REQUEST", "MISSING_OR_UNSUPPORTED_PARAMETER",
        "symmetric Hausdorff requires only tolerance and error_bound");
  }
  for (auto iterator = parameters.begin(); iterator != parameters.end();
       ++iterator) {
    if (allowed.find(iterator.key()) == allowed.end()) {
      throw WorkerError("INVALID_REQUEST", "UNSUPPORTED_PARAMETER",
                        "Unsupported symmetric Hausdorff parameter: " +
                            iterator.key());
    }
  }
}

Json run_symmetric_hausdorff(const Request& request) {
  require_wave_a_kernel(request);
  if (request.inputs.size() != 2) {
    throw WorkerError(
        "TYPE_ERROR", "INPUT_COUNT_MISMATCH",
        "mesh.distance.symmetric_hausdorff requires reference then candidate");
  }
  require_allowed_parameters(request.parameters);
  require_same_unit(request.inputs[0], request.inputs[1]);
  // Parsed + health-checked meshes are reused across requests in a persistent worker only when
  // the session cache is enabled; the Hausdorff computation itself (its internal AABB trees,
  // which CGAL does not let callers supply) always runs.
  struct Parsed : SessionCacheEntry {
    Mesh mesh;
  };
  auto load = [&](const ArtifactInput& input, const char* label) {
    auto& cache = SessionCache::instance();
    const auto key = SessionCache::key("mesh.distance.parsed_off", "Epick/Surface_mesh", input);
    auto cached = cache.find<Parsed>(key, input);
    if (cached) return cached;
    return cache.build<Parsed>(key, [&] {
      auto parsed = std::make_shared<Parsed>();
      parsed->mesh = read_triangle_off(input);
      require_healthy_triangle_mesh(parsed->mesh, label);
      parsed->bytes = parsed->mesh.number_of_faces() * 400 + parsed->mesh.number_of_vertices() * 150 + 4096;
      return parsed;
    });
  };
  const auto reference_entry = load(request.inputs[0], "Hausdorff reference");
  const auto candidate_entry = load(request.inputs[1], "Hausdorff candidate");
  const Mesh& reference = reference_entry->mesh;
  const Mesh& candidate = candidate_entry->mesh;

  const auto& unit = request.inputs[0].unit;
  const double tolerance =
      typed_length(request.parameters.at("tolerance"), unit, "tolerance");
  const double error_bound = typed_length(
      request.parameters.at("error_bound"), unit, "error_bound", true);

  const double distance =
      PMP::bounded_error_symmetric_Hausdorff_distance<CGAL::Sequential_tag>(
          reference, candidate, error_bound);
  if (!std::isfinite(distance) || distance < 0) {
    throw WorkerError("INTERNAL", "NONFINITE_DISTANCE",
                      "CGAL returned an invalid Hausdorff distance");
  }
  const double lower = std::max(0.0, distance - error_bound);
  const double upper = distance + error_bound;
  const std::string verdict = upper <= tolerance
                                  ? "pass"
                                  : (lower > tolerance ? "fail"
                                                       : "indeterminate");

  // ValidationReport has a binary status for the parent publication gate.
  // The verdict retains the bounded-error indeterminate state explicitly.
  Json report = {
      {"status", verdict == "pass" ? "pass" : "fail"},
      {"valid", verdict == "pass"},
      {"verdict", verdict},
      {"method", "bounded_error_symmetric"},
      // Self-describing frame so the independent mesh.validate.hausdorff_symmetric_report validator can
      // bind the report to its input artifacts and parameters.
      {"schema_version", 1},
      {"report_type", "ValidationReport"},
      {"report_kind", "hausdorff_bounded_symmetric"},
      {"operation", request.operation},
      {"parameters", request.parameters},
      {"source",
       {{"reference_sha256", request.inputs[0].sha256},
        {"candidate_sha256", request.inputs[1].sha256}}},
      {"results", {{"distance", distance}, {"distance_unit", unit}}},
      {"distance_estimate", { {"value", distance}, {"unit", unit} }},
      {"lower_bound", { {"value", lower}, {"unit", unit} }},
      {"upper_bound", { {"value", upper}, {"unit", unit} }},
      {"tolerance", { {"value", tolerance}, {"unit", unit} }},
      {"error_bound", { {"value", error_bound}, {"unit", unit} }},
      {"effective_concurrency", "sequential"},
      {"effective_kernel",
       "CGAL::Exact_predicates_inexact_constructions_kernel"}};
  const auto path = write_validation_output(request, report);
  return success_result(request,
                        Json::array({validation_output(path)}), report);
}

}  // namespace

OperationDefinition symmetric_hausdorff_operation() {
  OperationDefinition definition{
      "mesh.distance.symmetric_hausdorff", 1,
      {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "ValidationReport",
      "validator", run_symmetric_hausdorff};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel =
      "CGAL::Exact_predicates_inexact_constructions_kernel";
  definition.dependencies = {"Polygon_mesh_processing"};
  definition.info = {
      {"input_slots", Json::array({"reference", "candidate"})},
      {"input_format", "off"},
      {"output_slot", "validation"},
      {"output_format", "json"},
      {"method", "bounded_error_symmetric_Hausdorff_distance"},
      {"effective_concurrency", "sequential"},
      {"bound_parameters", Json::array({"tolerance", "error_bound"})},
      {"verdicts", Json::array({"pass", "fail", "indeterminate"})},
      {"validators", Json::array({"mesh.validate.hausdorff_symmetric_report"})},
      {"validator_parameter_bindings",
       {{"mesh.validate.hausdorff_symmetric_report",
         {{"tolerance", "tolerance"}, {"error_bound", "error_bound"}}}}}};
  return definition;
}

}  // namespace cgal_master::wave_a
