// Producers wrapping CGAL 6.2.1 mesh decomposition, skeletonization and parameterization (7.8.02,
// 7.8.03, 7.8.05). Results are checked by the CGAL-free validators in the b8_validators_*.cpp files.

#include "b8_common.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Mean_curvature_flow_skeletonization.h>
#include <CGAL/Polygon_mesh_processing/measure.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/Surface_mesh_parameterization/ARAP_parameterizer_3.h>
#include <CGAL/Surface_mesh_parameterization/Discrete_conformal_map_parameterizer_3.h>
#include <CGAL/Surface_mesh_parameterization/Error_code.h>
#include <CGAL/Surface_mesh_parameterization/parameterize.h>
#include <CGAL/approximate_convex_decomposition.h>
#include <CGAL/extract_mean_curvature_flow_skeleton.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <iterator>

namespace cgal_master::batch8 {
namespace {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using batch2::geometry_frame;
using batch2::pinfo;
using query_ops::precondition;
using query_ops::read_raw_mesh;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::write_report;

using SurfaceMesh = CGAL::Surface_mesh<Epick::Point_3>;
namespace SMP = CGAL::Surface_mesh_parameterization;

double number_parameter(const Request& request, const char* name, double minimum, double maximum,
                        bool minimum_exclusive) {
  const auto& value = request.parameters.at(name);
  if (!value.is_number() || value.is_boolean() || !std::isfinite(value.get<double>())) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be a finite number");
  }
  const double number = value.get<double>();
  if (number > maximum || number < minimum || (minimum_exclusive && number <= minimum)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " is out of range");
  }
  return number;
}

bool bool_parameter(const Request& request, const char* name) {
  const auto& value = request.parameters.at(name);
  if (!value.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be a boolean");
  }
  return value.get<bool>();
}

RawMesh read_triangle_mesh(const Request& request, std::size_t maximum_faces) {
  auto raw = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  if (raw.faces.empty() || raw.faces.size() > maximum_faces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_COUNT",
                      "Between 1 and " + std::to_string(maximum_faces) + " triangles are supported");
  }
  for (const auto& face : raw.faces) {
    if (face.size() != 3) precondition("NOT_TRIANGULATED", "Every face must be a triangle");
  }
  return raw;
}

void require_closed_outward(const RawMesh& raw) {
  const auto topology = analyze_topology(raw);
  if (topology.unreferenced_vertex) precondition("UNREFERENCED_VERTEX", "Every vertex must belong to a face");
  if (!topology.oriented_manifold) {
    precondition("MESH_NOT_ORIENTED_MANIFOLD", "The triangles must form an oriented 2-manifold");
  }
  if (!topology.closed) precondition("MESH_NOT_CLOSED", "The mesh must be closed");
  if (signed_volume(raw) <= 0) precondition("MESH_NOT_OUTWARD", "The faces must be oriented outward");
}

SurfaceMesh build_surface_mesh(const RawMesh& raw, std::vector<SurfaceMesh::Vertex_index>& vertices) {
  SurfaceMesh mesh;
  for (const auto& v : raw.vertices) vertices.push_back(mesh.add_vertex(Epick::Point_3(v[0], v[1], v[2])));
  for (const auto& face : raw.faces) {
    const auto id = mesh.add_face(vertices.at(face[0]), vertices.at(face[1]), vertices.at(face[2]));
    if (id == SurfaceMesh::null_face()) {
      precondition("MESH_NOT_ORIENTED_MANIFOLD", "The triangles must form an orientable 2-manifold");
    }
  }
  return mesh;
}

double part_volume(const std::vector<Epick::Point_3>& points, const std::vector<std::array<unsigned int, 3>>& faces) {
  double six = 0;
  for (const auto& f : faces) {
    const auto& a = points.at(f[0]);
    const auto& b = points.at(f[1]);
    const auto& c = points.at(f[2]);
    six += a.x() * (b.y() * c.z() - b.z() * c.y()) + a.y() * (b.z() * c.x() - b.x() * c.z()) +
           a.z() * (b.x() * c.y() - b.y() * c.x());
  }
  return six / 6.0;
}

// ---- 7.8.02 -------------------------------------------------------------------------------------
Json approx_convex(const Request& request) {
  require_inputs(request, 1, "mesh.decompose.approx_convex");
  require_parameter_names(request, {"maximum_number_of_convex_volumes", "maximum_number_of_voxels", "maximum_depth",
                                    "volume_error", "refitting", "split_at_concavity"});
  const auto volumes_limit = query_ops::integer_parameter(request, "maximum_number_of_convex_volumes", 1, 64);
  const auto voxels = query_ops::integer_parameter(request, "maximum_number_of_voxels", 4096, 1000000);
  const auto depth = query_ops::integer_parameter(request, "maximum_depth", 1, 12);
  const double volume_error = number_parameter(request, "volume_error", 0.0, 1.0, true);
  const bool refitting = bool_parameter(request, "refitting");
  const bool split_at_concavity = bool_parameter(request, "split_at_concavity");
  const auto raw = read_triangle_mesh(request, kMaximumDecompositionFaces);
  require_closed_outward(raw);
  std::vector<SurfaceMesh::Vertex_index> vertices;
  const SurfaceMesh mesh = build_surface_mesh(raw, vertices);

  using Volume = std::pair<std::vector<Epick::Point_3>, std::vector<std::array<unsigned int, 3>>>;
  std::vector<Volume> volumes;
  CGAL::approximate_convex_decomposition(
      mesh, std::back_inserter(volumes),
      CGAL::parameters::maximum_number_of_voxels(static_cast<unsigned int>(voxels))
          .maximum_depth(static_cast<unsigned int>(depth))
          .refitting(refitting)
          .maximum_number_of_convex_volumes(static_cast<unsigned int>(volumes_limit))
          .volume_error(volume_error)
          .split_at_concavity(split_at_concavity)
          .concurrency_tag(CGAL::Sequential_tag()));

  Json parts = Json::array();
  double total = 0;
  for (const auto& volume : volumes) {
    Json vertex_rows = Json::array();
    for (const auto& p : volume.first) vertex_rows.push_back(Json::array({p.x(), p.y(), p.z()}));
    Json face_rows = Json::array();
    for (const auto& f : volume.second) face_rows.push_back(Json::array({f[0], f[1], f[2]}));
    total += part_volume(volume.first, volume.second);
    parts.push_back({{"vertices", std::move(vertex_rows)}, {"faces", std::move(face_rows)}});
  }
  double mesh_volume = 0;
  {
    std::vector<Epick::Point_3> points;
    std::vector<std::array<unsigned int, 3>> faces;
    for (const auto& v : raw.vertices) points.emplace_back(v[0], v[1], v[2]);
    for (const auto& f : raw.faces) {
      faces.push_back({static_cast<unsigned int>(f[0]), static_cast<unsigned int>(f[1]),
                       static_cast<unsigned int>(f[2])});
    }
    mesh_volume = part_volume(points, faces);
  }
  Json report = geometry_frame(request, "approximate_convex_decomposition", request.parameters,
                               {{"mesh_sha256", request.inputs[0].sha256}},
                               {{"part_count", volumes.size()}},
                               {{"parts", std::move(parts)}, {"distance_unit", request.inputs[0].unit}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"part_count", volumes.size()}, {"face_count", raw.faces.size()},
               {"mesh_volume", mesh_volume}, {"total_part_volume", total},
               {"algorithm", "CGAL::approximate_convex_decomposition"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.8.03 -------------------------------------------------------------------------------------
using Mcf = CGAL::Mean_curvature_flow_skeletonization<SurfaceMesh>;

Json skeleton_report(const Request& request, const Mcf::Skeleton& skeleton, const RawMesh& raw,
                     const char* algorithm) {
  Json vertex_rows = Json::array();
  for (const auto v : CGAL::make_range(boost::vertices(skeleton))) {
    const auto& info = skeleton[v];
    std::vector<std::size_t> surface;
    for (const auto s : info.vertices) surface.push_back(static_cast<std::size_t>(s));
    std::sort(surface.begin(), surface.end());
    Json ids = Json::array();
    for (const auto id : surface) ids.push_back(id);
    vertex_rows.push_back({{"point", Json::array({info.point.x(), info.point.y(), info.point.z()})},
                           {"surface_vertices", std::move(ids)}});
  }
  std::vector<std::pair<std::size_t, std::size_t>> edge_list;
  for (const auto e : CGAL::make_range(boost::edges(skeleton))) {
    const auto a = static_cast<std::size_t>(boost::source(e, skeleton));
    const auto b = static_cast<std::size_t>(boost::target(e, skeleton));
    edge_list.push_back({std::min(a, b), std::max(a, b)});
  }
  std::sort(edge_list.begin(), edge_list.end());
  Json edge_rows = Json::array();
  for (const auto& e : edge_list) edge_rows.push_back(Json::array({e.first, e.second}));
  Json report = geometry_frame(request, "mean_curvature_flow_skeleton", request.parameters,
                               {{"mesh_sha256", request.inputs[0].sha256}},
                               {{"skeleton_vertex_count", boost::num_vertices(skeleton)},
                                {"skeleton_edge_count", edge_list.size()}},
                               {{"vertices", std::move(vertex_rows)}, {"edges", std::move(edge_rows)},
                                {"distance_unit", request.inputs[0].unit}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"skeleton_vertex_count", boost::num_vertices(skeleton)}, {"skeleton_edge_count", edge_list.size()},
               {"face_count", raw.faces.size()}, {"algorithm", algorithm}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json skeleton_function(const Request& request) {
  require_inputs(request, 1, "mesh.skeletonize.mean_curvature");
  require_parameter_names(request, {});
  const auto raw = read_triangle_mesh(request, kMaximumSkeletonFaces);
  require_closed_outward(raw);
  std::vector<SurfaceMesh::Vertex_index> vertices;
  const SurfaceMesh mesh = build_surface_mesh(raw, vertices);
  Mcf::Skeleton skeleton;
  CGAL::extract_mean_curvature_flow_skeleton(mesh, skeleton);
  return skeleton_report(request, skeleton, raw, "CGAL::extract_mean_curvature_flow_skeleton");
}

Json skeleton_class(const Request& request) {
  require_inputs(request, 1, "mesh.skeletonize.mean_curvature_flow");
  require_parameter_names(request, {"quality_speed_tradeoff", "medially_centered_speed_tradeoff",
                                    "is_medially_centered", "max_iterations"});
  const double quality = number_parameter(request, "quality_speed_tradeoff", 0.0, 100.0, true);
  const double medial = number_parameter(request, "medially_centered_speed_tradeoff", 0.0, 100.0, true);
  const bool is_medial = bool_parameter(request, "is_medially_centered");
  const auto iterations = query_ops::integer_parameter(request, "max_iterations", 1, 2000);
  const auto raw = read_triangle_mesh(request, kMaximumSkeletonFaces);
  require_closed_outward(raw);
  std::vector<SurfaceMesh::Vertex_index> vertices;
  const SurfaceMesh mesh = build_surface_mesh(raw, vertices);
  Mcf mcf(mesh);
  mcf.set_quality_speed_tradeoff(quality);
  mcf.set_medially_centered_speed_tradeoff(medial);
  mcf.set_is_medially_centered(is_medial);
  mcf.set_max_iterations(iterations);
  mcf.contract_until_convergence();
  Mcf::Skeleton skeleton;
  mcf.convert_to_skeleton(skeleton);
  return skeleton_report(request, skeleton, raw, "CGAL::Mean_curvature_flow_skeletonization");
}

// ---- 7.8.05 -------------------------------------------------------------------------------------
using UvMap = SurfaceMesh::Property_map<SurfaceMesh::Vertex_index, Epick::Point_2>;

SurfaceMesh build_disc(const Request& request, const RawMesh& raw, std::vector<SurfaceMesh::Vertex_index>& vertices) {
  const auto topology = analyze_topology(raw);
  if (topology.unreferenced_vertex) precondition("UNREFERENCED_VERTEX", "Every vertex must belong to a face");
  if (!topology.oriented_manifold) {
    precondition("MESH_NOT_ORIENTED_MANIFOLD", "The triangles must form an oriented 2-manifold");
  }
  if (topology.components != 1 || topology.boundary_loops.size() != 1 || topology.euler() != 1) {
    precondition("MESH_NOT_DISC", "The mesh must be a connected topological disc with one boundary loop");
  }
  (void)request;
  return build_surface_mesh(raw, vertices);
}

Json parameterization_report(const Request& request, const SurfaceMesh& mesh,
                             const std::vector<SurfaceMesh::Vertex_index>& vertices, const UvMap& uv,
                             const RawMesh& raw, const char* algorithm) {
  Json rows = Json::array();
  for (const auto v : vertices) {
    const auto& p = uv[v];
    rows.push_back(Json::array({p.x(), p.y()}));
  }
  (void)mesh;
  Json report = geometry_frame(request, "surface_parameterization", request.parameters,
                               {{"mesh_sha256", request.inputs[0].sha256}},
                               {{"vertex_count", vertices.size()}, {"face_count", raw.faces.size()}},
                               {{"uv", std::move(rows)}, {"distance_unit", request.inputs[0].unit}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"vertex_count", vertices.size()}, {"face_count", raw.faces.size()}, {"algorithm", algorithm}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json parameterize_arap(const Request& request) {
  require_inputs(request, 1, "mesh.parameterize");
  require_parameter_names(request, {"lambda", "iterations", "maximum_distortion"});
  const double lambda = number_parameter(request, "lambda", 0.0, 1.0e6, false);
  const auto iterations = query_ops::integer_parameter(request, "iterations", 1, 500);
  (void)number_parameter(request, "maximum_distortion", 1.0, 1.0e6, false);
  const auto raw = read_triangle_mesh(request, kMaximumParameterizationFaces);
  std::vector<SurfaceMesh::Vertex_index> vertices;
  SurfaceMesh mesh = build_disc(request, raw, vertices);
  const auto border = CGAL::Polygon_mesh_processing::longest_border(mesh).first;
  UvMap uv = mesh.add_property_map<SurfaceMesh::Vertex_index, Epick::Point_2>("v:uv").first;
  SMP::ARAP_parameterizer_3<SurfaceMesh> parameterizer(
      SMP::ARAP_parameterizer_3<SurfaceMesh>::Border_parameterizer(),
      SMP::ARAP_parameterizer_3<SurfaceMesh>::Solver_traits(), lambda, static_cast<unsigned int>(iterations), 1e-6);
  const auto error = SMP::parameterize(mesh, parameterizer, border, uv);
  if (error != SMP::OK) precondition("PARAMETERIZATION_FAILED", SMP::get_error_message(error));
  return parameterization_report(request, mesh, vertices, uv, raw, "CGAL::Surface_mesh_parameterization::parameterize");
}

Json parameterize_dcm(const Request& request) {
  require_inputs(request, 1, "mesh.parameterize.discrete_conformal_map");
  require_parameter_names(request, {});
  const auto raw = read_triangle_mesh(request, kMaximumParameterizationFaces);
  std::vector<SurfaceMesh::Vertex_index> vertices;
  SurfaceMesh mesh = build_disc(request, raw, vertices);
  const auto border = CGAL::Polygon_mesh_processing::longest_border(mesh).first;
  UvMap uv = mesh.add_property_map<SurfaceMesh::Vertex_index, Epick::Point_2>("v:uv").first;
  SMP::Discrete_conformal_map_parameterizer_3<SurfaceMesh> parameterizer;
  auto parameterized = mesh.add_property_map<SurfaceMesh::Vertex_index, bool>("v:parameterized", false).first;
  const auto error = parameterizer.parameterize(mesh, border, uv, get(boost::vertex_index, mesh), parameterized);
  if (error != SMP::OK) precondition("PARAMETERIZATION_FAILED", SMP::get_error_message(error));
  return parameterization_report(request, mesh, vertices, uv, raw,
                                 "CGAL::Surface_mesh_parameterization::Discrete_conformal_map_parameterizer_3");
}

}  // namespace

std::vector<OperationDefinition> producer_operations() {
  using query_ops::query_definition;
  const std::string kernel = "CGAL::Exact_predicates_inexact_constructions_kernel";
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.decompose.approx_convex", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", approx_convex,
      {"Convex_decomposition_3"}, kernel,
      pinfo("mesh.validate.approx_convex",
            {"maximum_number_of_convex_volumes", "maximum_number_of_voxels", "maximum_depth", "volume_error",
             "refitting", "split_at_concavity"},
            {"mesh"},
            {{"source_header", "CGAL/approximate_convex_decomposition.h"},
             {"maximum_input_faces", kMaximumDecompositionFaces}})));
  result.push_back(query_definition(
      "mesh.skeletonize.mean_curvature", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis",
      skeleton_function, {"Surface_mesh_skeletonization"}, kernel,
      pinfo("mesh.validate.skeleton", {}, {"mesh"},
            {{"source_header", "CGAL/extract_mean_curvature_flow_skeleton.h"},
             {"maximum_input_faces", kMaximumSkeletonFaces}})));
  result.push_back(query_definition(
      "mesh.skeletonize.mean_curvature_flow", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis",
      skeleton_class, {"Surface_mesh_skeletonization"}, kernel,
      pinfo("mesh.validate.skeleton",
            {"quality_speed_tradeoff", "medially_centered_speed_tradeoff", "is_medially_centered", "max_iterations"},
            {"mesh"},
            {{"source_header", "CGAL/Mean_curvature_flow_skeletonization.h"},
             {"maximum_input_faces", kMaximumSkeletonFaces}})));
  result.push_back(query_definition(
      "mesh.parameterize", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", parameterize_arap,
      {"Surface_mesh_parameterization"}, kernel,
      pinfo("mesh.validate.parameterization_isometric", {"lambda", "iterations", "maximum_distortion"}, {"mesh"},
            {{"source_header", "CGAL/Surface_mesh_parameterization/ARAP_parameterizer_3.h"},
             {"maximum_input_faces", kMaximumParameterizationFaces}})));
  result.push_back(query_definition(
      "mesh.parameterize.discrete_conformal_map", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis",
      parameterize_dcm, {"Surface_mesh_parameterization"}, kernel,
      pinfo("mesh.validate.parameterization_harmonic", {}, {"mesh"},
            {{"source_header", "CGAL/Surface_mesh_parameterization/Discrete_conformal_map_parameterizer_3.h"},
             {"maximum_input_faces", kMaximumParameterizationFaces}})));
  return result;
}

}  // namespace cgal_master::batch8
