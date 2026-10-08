// Wave D producers: official CGAL 6.2.1 Polygon_mesh_processing meshing and
// remeshing functions over a strictly checked input surface mesh.
#include "wave_d_common.h"

#include "../wave_c/wave_c_common.h"

#include <CGAL/Polygon_mesh_processing/Adaptive_sizing_field.h>
#include <CGAL/Polygon_mesh_processing/measure.h>
#include <CGAL/Polygon_mesh_processing/refine.h>
#include <CGAL/Polygon_mesh_processing/remesh.h>
#include <CGAL/Polygon_mesh_processing/smooth_shape.h>
#include <CGAL/Polygon_mesh_processing/tangential_relaxation.h>
#include <CGAL/Polygon_mesh_processing/triangulate_faces.h>

#include <algorithm>
#include <cmath>
#include <vector>

namespace cgal_master::wave_d {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;
using wave_c::enum_parameter;
using wave_c::integer_parameter;
using wave_c::boolean_parameter;
using wave_c::require_input_count;
using wave_c::require_parameters;
using wave_c::typed_length_parameter;

using Face = SurfaceMesh::Face_index;
using Edge = SurfaceMesh::Edge_index;
using Vertex = SurfaceMesh::Vertex_index;

double positive_length(const Request& request, const char* name, const std::string& unit) {
  const double value = typed_length_parameter(request, name, unit);
  if (!(value > 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be positive");
  }
  return value;
}

double total_area(const SurfaceMesh& mesh) { return CGAL::to_double(PMP::area(mesh)); }

// Refuse candidates whose two-sided deviation sampling would exceed the
// validator budget (mirrors the validator's lattice plan).
void require_sampling_budget(const SurfaceMesh& first, const SurfaceMesh& second,
                             double max_deviation) {
  const double resolution = max_deviation;
  std::size_t planned = 0;
  for (const SurfaceMesh* mesh : {&first, &second}) {
    std::size_t one_side = 0;
    for (const auto face : mesh->faces()) {
      std::vector<Point3> corners;
      for (const auto vertex : CGAL::vertices_around_face(mesh->halfedge(face), *mesh)) {
        corners.push_back(mesh->point(vertex));
      }
      for (std::size_t corner = 1; corner + 1 < corners.size(); ++corner) {
        const double longest = std::sqrt(std::max(
            {CGAL::squared_distance(corners[0], corners[corner]),
             CGAL::squared_distance(corners[corner], corners[corner + 1]),
             CGAL::squared_distance(corners[corner + 1], corners[0])}));
        const auto k = static_cast<std::size_t>(
            std::clamp(std::ceil(longest / resolution), 1.0, 4096.0));
        one_side += (k + 1) * (k + 2) / 2;
      }
    }
    planned = std::max(planned, one_side);
  }
  if (planned > kMaximumSamples) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED",
                      "max_deviation is too small relative to the mesh for bounded validation");
  }
}

void require_estimated_faces(double estimate, const std::string& operation) {
  if (!(estimate <= static_cast<double>(kMaximumOutputFaces))) {
    throw WorkerError("RESOURCE_LIMIT", "OUTPUT_FACE_LIMIT_EXCEEDED",
                      operation + " would exceed the Wave D output face budget");
  }
}

Json counts(const SurfaceMesh& mesh) {
  return Json{{"vertices", mesh.number_of_vertices()},
              {"faces", mesh.number_of_faces()},
              {"edges", mesh.number_of_edges()}};
}

Json finish(const Request& request, SurfaceMesh& mesh, const ArtifactInput& source,
            Json metrics) {
  metrics["effective_kernel"] = kEpick;
  metrics["output"] = counts(mesh);
  auto output = write_mesh_candidate(request, mesh, source.unit);
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json run_triangulate(const Request& request) {
  require_kernel(request);
  require_input_count(request, 1, "mesh.triangulate.faces");
  require_parameters(request, {"method"});
  const auto method = enum_parameter(request, "method", {"triangulate_faces", "triangulate_face"});
  const auto& source = request.inputs[0];
  auto mesh = read_producer_mesh(source, {"PolygonSoup3"}, false);
  const Json input = counts(mesh);
  std::size_t polygon_faces = 0;
  for (const auto face : mesh.faces()) polygon_faces += CGAL::is_triangle(mesh.halfedge(face), mesh) ? 0 : 1;
  bool succeeded = true;
  if (method == "triangulate_faces") {
    succeeded = PMP::triangulate_faces(mesh);
  } else {
    std::vector<Face> faces(mesh.faces().begin(), mesh.faces().end());
    for (const auto face : faces) {
      if (!CGAL::is_triangle(mesh.halfedge(face), mesh)) {
        succeeded = PMP::triangulate_face(face, mesh) && succeeded;
      }
    }
  }
  if (!succeeded || !CGAL::is_triangle_mesh(mesh)) {
    throw WorkerError("OPERATION_FAILED", "TRIANGULATION_FAILED",
                      "CGAL could not triangulate every face");
  }
  require_output_budget(mesh, "mesh.triangulate.faces");
  return finish(request, mesh, source,
                Json{{"algorithm", method == "triangulate_faces"
                                       ? "CGAL::Polygon_mesh_processing::triangulate_faces"
                                       : "CGAL::Polygon_mesh_processing::triangulate_face"},
                     {"method", method},
                     {"input", input},
                     {"triangulated_polygon_faces", polygon_faces}});
}

Json run_refine(const Request& request) {
  require_kernel(request);
  require_input_count(request, 1, "mesh.refine.local");
  require_parameters(request, {"density_control_factor", "max_deviation"});
  const auto& source = request.inputs[0];
  const double density = number_parameter(request, "density_control_factor", 0.0, 10.0);
  const double max_deviation = positive_length(request, "max_deviation", source.unit);
  auto mesh = read_producer_mesh(source, {"TriangleSurfaceMesh"}, true);
  const SurfaceMesh original = mesh;
  const Json input = counts(mesh);
  std::vector<Face> faces(mesh.faces().begin(), mesh.faces().end());
  std::vector<Face> new_faces;
  std::vector<Vertex> new_vertices;
  PMP::refine(mesh, faces, std::back_inserter(new_faces), std::back_inserter(new_vertices),
              CGAL::parameters::density_control_factor(density));
  require_output_budget(mesh, "mesh.refine.local");
  require_sampling_budget(original, mesh, max_deviation);
  return finish(request, mesh, source,
                Json{{"algorithm", "CGAL::Polygon_mesh_processing::refine"},
                     {"density_control_factor", density},
                     {"input", input},
                     {"inserted_vertices", new_vertices.size()},
                     {"new_faces", new_faces.size()}});
}

Json run_isotropic(const Request& request) {
  require_kernel(request);
  require_input_count(request, 1, "mesh.remesh.isotropic");
  require_parameters(request, {"target_edge_length", "number_of_iterations",
                               "number_of_relaxation_steps", "max_deviation"});
  const auto& source = request.inputs[0];
  const double target = positive_length(request, "target_edge_length", source.unit);
  const double max_deviation = positive_length(request, "max_deviation", source.unit);
  const auto iterations = integer_parameter(request, "number_of_iterations", 1, kMaximumIterations);
  const auto relaxation = integer_parameter(request, "number_of_relaxation_steps", 0, 10);
  auto mesh = read_producer_mesh(source, {"TriangleSurfaceMesh"}, true);
  const SurfaceMesh original = mesh;
  const double minimum_edge = 0.8 * target;
  require_estimated_faces(2.0 * total_area(mesh) / (std::sqrt(3.0) / 4 * minimum_edge * minimum_edge),
                          "mesh.remesh.isotropic");
  const Json input = counts(mesh);
  PMP::isotropic_remeshing(mesh.faces(), target, mesh,
                           CGAL::parameters::number_of_iterations(static_cast<unsigned int>(iterations))
                               .number_of_relaxation_steps(static_cast<unsigned int>(relaxation)));
  if (mesh.has_garbage()) mesh.collect_garbage();
  require_output_budget(mesh, "mesh.remesh.isotropic");
  require_sampling_budget(original, mesh, max_deviation);
  return finish(request, mesh, source,
                Json{{"algorithm", "CGAL::Polygon_mesh_processing::isotropic_remeshing"},
                     {"sizing", "uniform"},
                     {"target_edge_length", target},
                     {"number_of_iterations", iterations},
                     {"number_of_relaxation_steps", relaxation},
                     {"input", input}});
}

Json run_split_long_edges(const Request& request) {
  require_kernel(request);
  require_input_count(request, 1, "mesh.remesh.split_long_edges");
  require_parameters(request, {"max_length"});
  const auto& source = request.inputs[0];
  const double max_length = positive_length(request, "max_length", source.unit);
  auto mesh = read_producer_mesh(source, {"TriangleSurfaceMesh"}, true);
  double estimate = static_cast<double>(mesh.number_of_faces());
  for (const auto edge : mesh.edges()) {
    estimate += 2.0 * std::ceil(std::sqrt(CGAL::to_double(CGAL::squared_distance(
                                    mesh.point(mesh.vertex(edge, 0)), mesh.point(mesh.vertex(edge, 1))))) /
                                max_length);
  }
  require_estimated_faces(estimate, "mesh.remesh.split_long_edges");
  const Json input = counts(mesh);
  std::vector<Edge> edges(mesh.edges().begin(), mesh.edges().end());
  PMP::split_long_edges(edges, max_length, mesh);
  require_output_budget(mesh, "mesh.remesh.split_long_edges");
  return finish(request, mesh, source,
                Json{{"algorithm", "CGAL::Polygon_mesh_processing::split_long_edges"},
                     {"max_length", max_length},
                     {"input", input}});
}

Json run_tangential_relaxation(const Request& request) {
  require_kernel(request);
  require_input_count(request, 1, "mesh.smooth.tangential_relaxation");
  require_parameters(request, {"number_of_iterations", "max_deviation"});
  const auto& source = request.inputs[0];
  const auto iterations = integer_parameter(request, "number_of_iterations", 1, kMaximumIterations);
  const double max_deviation = positive_length(request, "max_deviation", source.unit);
  auto mesh = read_producer_mesh(source, {"TriangleSurfaceMesh"}, true);
  const SurfaceMesh original = mesh;
  require_sampling_budget(original, mesh, max_deviation);
  PMP::tangential_relaxation(mesh.vertices(), mesh,
                             CGAL::parameters::number_of_iterations(static_cast<unsigned int>(iterations)));
  return finish(request, mesh, source,
                Json{{"algorithm", "CGAL::Polygon_mesh_processing::tangential_relaxation"},
                     {"number_of_iterations", iterations},
                     {"boundary_vertices", "fixed (relax_constraints=false)"}});
}

Json run_smooth_shape(const Request& request) {
  require_kernel(request);
  require_input_count(request, 1, "mesh.smooth.shape");
  require_parameters(request, {"time_step", "number_of_iterations", "preserve_volume", "max_deviation"});
  const auto& source = request.inputs[0];
  const double time_step = number_parameter(request, "time_step", 0.0, 1e6);
  const auto iterations = integer_parameter(request, "number_of_iterations", 1, kMaximumIterations);
  const bool preserve_volume = boolean_parameter(request, "preserve_volume");
  const double max_deviation = positive_length(request, "max_deviation", source.unit);
  auto mesh = read_producer_mesh(source, {"TriangleSurfaceMesh"}, true);
  const bool closed = CGAL::is_closed(mesh);
  if (preserve_volume && !closed) {
    throw WorkerError("PRECONDITION_FAILED", "VOLUME_REQUIRES_CLOSED_MESH",
                      "preserve_volume requires a closed mesh");
  }
  const SurfaceMesh original = mesh;
  require_sampling_budget(original, mesh, max_deviation);
  auto constrained = mesh.add_property_map<Vertex, bool>("v:wave_d_constrained", false).first;
  std::size_t constrained_count = 0;
  for (const auto vertex : mesh.vertices()) {
    if (mesh.is_border(vertex)) {
      constrained[vertex] = true;
      ++constrained_count;
    }
  }
  PMP::smooth_shape(mesh, time_step,
                    CGAL::parameters::number_of_iterations(static_cast<unsigned int>(iterations))
                        .vertex_is_constrained_map(constrained)
                        .do_scale(preserve_volume));
  mesh.remove_property_map(constrained);
  return finish(request, mesh, source,
                Json{{"algorithm", "CGAL::Polygon_mesh_processing::smooth_shape"},
                     {"time_step", time_step},
                     {"time_step_unit", source.unit + "^2"},
                     {"number_of_iterations", iterations},
                     {"preserve_volume", preserve_volume},
                     {"constrained_boundary_vertices", constrained_count}});
}

Json run_adaptive(const Request& request) {
  require_kernel(request);
  require_input_count(request, 1, "mesh.remesh.adaptive");
  require_parameters(request, {"tolerance", "min_edge_length", "max_edge_length", "mode",
                               "number_of_iterations", "max_deviation"});
  const auto& source = request.inputs[0];
  const double tolerance = positive_length(request, "tolerance", source.unit);
  const double minimum = positive_length(request, "min_edge_length", source.unit);
  const double maximum = positive_length(request, "max_edge_length", source.unit);
  const double max_deviation = positive_length(request, "max_deviation", source.unit);
  const auto mode = enum_parameter(request, "mode", {"isotropic_remeshing", "split_long_edges"});
  const auto iterations = integer_parameter(request, "number_of_iterations", 1, kMaximumIterations);
  if (!(minimum < maximum)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "min_edge_length must be smaller than max_edge_length");
  }
  auto mesh = read_producer_mesh(source, {"TriangleSurfaceMesh"}, true);
  const SurfaceMesh original = mesh;
  const double smallest = mode == "isotropic_remeshing" ? 0.8 * minimum : minimum / 2;
  require_estimated_faces(2.0 * total_area(mesh) / (std::sqrt(3.0) / 4 * smallest * smallest) +
                              static_cast<double>(mesh.number_of_faces()),
                          "mesh.remesh.adaptive");
  const Json input = counts(mesh);
  PMP::Adaptive_sizing_field<SurfaceMesh> sizing(tolerance, std::make_pair(minimum, maximum),
                                                 mesh.faces(), mesh);
  if (mode == "isotropic_remeshing") {
    PMP::isotropic_remeshing(mesh.faces(), sizing, mesh,
                             CGAL::parameters::number_of_iterations(static_cast<unsigned int>(iterations))
                                 .number_of_relaxation_steps(3));
  } else {
    std::vector<Edge> edges(mesh.edges().begin(), mesh.edges().end());
    PMP::split_long_edges(edges, sizing, mesh);
  }
  if (mesh.has_garbage()) mesh.collect_garbage();
  require_output_budget(mesh, "mesh.remesh.adaptive");
  require_sampling_budget(original, mesh, max_deviation);
  return finish(request, mesh, source,
                Json{{"algorithm", mode == "isotropic_remeshing"
                                       ? "CGAL::Polygon_mesh_processing::isotropic_remeshing"
                                       : "CGAL::Polygon_mesh_processing::split_long_edges"},
                     {"sizing", "CGAL::Polygon_mesh_processing::Adaptive_sizing_field"},
                     {"mode", mode},
                     {"tolerance", tolerance},
                     {"edge_length_range", {minimum, maximum}},
                     {"number_of_iterations", iterations},
                     {"input", input}});
}

}  // namespace

std::vector<OperationDefinition> remesh_operations() {
  std::vector<OperationDefinition> result;
  result.push_back(make_definition(
      "mesh.triangulate.faces", {"PolygonSoup3"}, "TriangleSurfaceMesh", "transform",
      run_triangulate, {"PMP_Remeshing"},
      {{"source_header", "CGAL/Polygon_mesh_processing/triangulate_faces.h"},
       {"symbols", {"triangulate_faces", "triangulate_face"}},
       {"input_slots", {"source"}},
       {"required_parameters", {"method"}},
       {"validators", {"mesh.validate.triangulated_faces"}},
       {"maximum_input_faces", kMaximumInputFaces}}));
  result.push_back(make_definition(
      "mesh.refine.local", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform", run_refine,
      {"PMP_Remeshing"},
      {{"source_header", "CGAL/Polygon_mesh_processing/refine.h"},
       {"symbols", {"refine"}},
       {"input_slots", {"source"}},
       {"required_parameters", {"density_control_factor", "max_deviation"}},
       {"validators", {"mesh.validate.refinement"}},
       {"validator_parameter_bindings",
        {{"mesh.validate.refinement", {{"max_deviation", "max_deviation"}}}}},
       {"maximum_input_faces", kMaximumInputFaces}}));
  result.push_back(make_definition(
      "mesh.remesh.isotropic", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform",
      run_isotropic, {"PMP_Remeshing"},
      {{"source_header", "CGAL/Polygon_mesh_processing/remesh.h"},
       {"symbols", {"isotropic_remeshing"}},
       {"input_slots", {"source"}},
       {"required_parameters",
        {"target_edge_length", "number_of_iterations", "number_of_relaxation_steps", "max_deviation"}},
       {"validators", {"mesh.validate.isotropic_remesh"}},
       {"validator_parameter_bindings",
        {{"mesh.validate.isotropic_remesh",
          {{"target_edge_length", "target_edge_length"}, {"max_deviation", "max_deviation"}}}}},
       {"maximum_input_faces", kMaximumInputFaces},
       {"maximum_output_faces", kMaximumOutputFaces}}));
  result.push_back(make_definition(
      "mesh.remesh.split_long_edges", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform",
      run_split_long_edges, {"PMP_Remeshing"},
      {{"source_header", "CGAL/Polygon_mesh_processing/remesh.h"},
       {"symbols", {"split_long_edges"}},
       {"input_slots", {"source"}},
       {"required_parameters", {"max_length"}},
       {"validators", {"mesh.validate.split_long_edges"}},
       {"validator_parameter_bindings",
        {{"mesh.validate.split_long_edges", {{"max_length", "max_length"}}}}},
       {"maximum_input_faces", kMaximumInputFaces},
       {"maximum_output_faces", kMaximumOutputFaces}}));
  result.push_back(make_definition(
      "mesh.smooth.tangential_relaxation", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh",
      "transform", run_tangential_relaxation, {"PMP_Remeshing"},
      {{"source_header", "CGAL/Polygon_mesh_processing/tangential_relaxation.h"},
       {"symbols", {"tangential_relaxation"}},
       {"input_slots", {"source"}},
       {"required_parameters", {"number_of_iterations", "max_deviation"}},
       {"validators", {"mesh.validate.tangential_relaxation"}},
       {"validator_parameter_bindings",
        {{"mesh.validate.tangential_relaxation", {{"max_deviation", "max_deviation"}}}}},
       {"maximum_input_faces", kMaximumInputFaces}}));
  result.push_back(make_definition(
      "mesh.smooth.shape", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform",
      run_smooth_shape, {"PMP_Remeshing", "Eigen"},
      {{"source_header", "CGAL/Polygon_mesh_processing/smooth_shape.h"},
       {"symbols", {"smooth_shape"}},
       {"input_slots", {"source"}},
       {"required_parameters", {"time_step", "number_of_iterations", "preserve_volume", "max_deviation"}},
       {"time_step_dimension", "squared artifact length unit"},
       {"boundary_policy", "boundary vertices constrained"},
       {"validators", {"mesh.validate.shape_smoothing"}},
       {"validator_parameter_bindings",
        {{"mesh.validate.shape_smoothing",
          {{"max_deviation", "max_deviation"}, {"preserve_volume", "preserve_volume"}}}}},
       {"maximum_input_faces", kMaximumInputFaces}}));
  result.push_back(make_definition(
      "mesh.remesh.adaptive", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform",
      run_adaptive, {"PMP_Remeshing"},
      {{"source_header", "CGAL/Polygon_mesh_processing/Adaptive_sizing_field.h"},
       {"symbols", {"Adaptive_sizing_field", "isotropic_remeshing", "split_long_edges"}},
       {"input_slots", {"source"}},
       {"required_parameters",
        {"tolerance", "min_edge_length", "max_edge_length", "mode", "number_of_iterations",
         "max_deviation"}},
       {"validators", {"mesh.validate.adaptive_remesh"}},
       {"validator_parameter_bindings",
        {{"mesh.validate.adaptive_remesh",
          {{"tolerance", "tolerance"},
           {"min_edge_length", "min_edge_length"},
           {"max_edge_length", "max_edge_length"},
           {"mode", "mode"},
           {"max_deviation", "max_deviation"}}}}},
       {"maximum_input_faces", kMaximumInputFaces},
       {"maximum_output_faces", kMaximumOutputFaces}}));
  return result;
}

}  // namespace cgal_master::wave_d
