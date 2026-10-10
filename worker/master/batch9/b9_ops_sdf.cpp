// Producers wrapping CGAL 6.2.1 Surface_mesh_segmentation (7.8.01): CGAL::sdf_values and
// CGAL::segmentation_from_sdf_values. Results are checked by the CGAL-free validators in
// b9_validators_sdf.cpp.

#include "b9_common.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/mesh_segmentation.h>

#include <algorithm>
#include <cmath>

namespace cgal_master::batch9 {
namespace {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using SurfaceMesh = CGAL::Surface_mesh<Epick::Point_3>;
using Face = SurfaceMesh::Face_index;
using batch2::geometry_frame;
using batch2::pinfo;
using query_ops::precondition;
using query_ops::read_raw_mesh;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::write_report;

RawMesh read_closed_mesh(const Request& request) {
  auto raw = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  if (raw.faces.empty() || raw.faces.size() > kMaximumSegmentationFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_COUNT",
                      "Between 1 and " + std::to_string(kMaximumSegmentationFaces) + " triangles are supported");
  }
  for (const auto& face : raw.faces) {
    if (face.size() != 3) precondition("NOT_TRIANGULATED", "Every face must be a triangle");
  }
  const auto topology = batch8::analyze_topology(raw);
  if (topology.unreferenced_vertex) precondition("UNREFERENCED_VERTEX", "Every vertex must belong to a face");
  if (!topology.oriented_manifold) {
    precondition("MESH_NOT_ORIENTED_MANIFOLD", "The triangles must form an oriented 2-manifold");
  }
  if (!topology.closed) precondition("MESH_NOT_CLOSED", "The mesh must be closed");
  if (batch8::signed_volume(raw) <= 0) precondition("MESH_NOT_OUTWARD", "The faces must be oriented outward");
  return raw;
}

SurfaceMesh build_mesh(const RawMesh& raw) {
  SurfaceMesh mesh;
  std::vector<SurfaceMesh::Vertex_index> vertices;
  for (const auto& v : raw.vertices) vertices.push_back(mesh.add_vertex(Epick::Point_3(v[0], v[1], v[2])));
  for (const auto& face : raw.faces) {
    if (mesh.add_face(vertices.at(face[0]), vertices.at(face[1]), vertices.at(face[2])) == SurfaceMesh::null_face()) {
      precondition("MESH_NOT_ORIENTED_MANIFOLD", "The triangles must form an orientable 2-manifold");
    }
  }
  return mesh;
}

struct SdfParameters {
  double cone_angle;
  std::size_t rays;
};

SdfParameters sdf_parameters(const Request& request) {
  SdfParameters p{};
  p.cone_angle = finite_number(request.parameters, "cone_angle", 0.0, 3.0, true);
  p.rays = query_ops::integer_parameter(request, "number_of_rays", 1, 100);
  (void)finite_number(request.parameters, "thickness_tolerance", 0.0, 0.5, false);
  return p;
}

Json values_of(const SurfaceMesh& mesh, const SurfaceMesh::Property_map<Face, double>& map) {
  Json rows = Json::array();
  for (const auto f : mesh.faces()) rows.push_back(map[f]);
  return rows;
}

void raw_statistics(const SurfaceMesh& mesh, const SurfaceMesh::Property_map<Face, double>& map, std::size_t& missing,
                    double& minimum, double& maximum) {
  missing = 0;
  minimum = INFINITY;
  maximum = -INFINITY;
  for (const auto f : mesh.faces()) {
    const double v = map[f];
    if (v == -1.0) {
      ++missing;
      continue;
    }
    minimum = std::min(minimum, v);
    maximum = std::max(maximum, v);
  }
  if (missing == mesh.number_of_faces()) minimum = maximum = -1.0;
}

// ---- 7.8.01 sdf_values -------------------------------------------------------------------------
Json sdf_values_operation(const Request& request) {
  require_inputs(request, 1, "mesh.segment.sdf_values");
  require_parameter_names(request, {"cone_angle", "number_of_rays", "thickness_tolerance"});
  const auto p = sdf_parameters(request);
  const auto raw = read_closed_mesh(request);
  SurfaceMesh mesh = build_mesh(raw);
  auto sdf = mesh.add_property_map<Face, double>("f:sdf", 0.0).first;
  CGAL::sdf_values(mesh, sdf, p.cone_angle, p.rays, false);
  std::size_t missing = 0;
  double minimum = 0, maximum = 0;
  raw_statistics(mesh, sdf, missing, minimum, maximum);
  Json report = geometry_frame(request, "sdf_values", request.parameters, {{"mesh_sha256", request.inputs[0].sha256}},
                               {{"face_count", raw.faces.size()}, {"missing_count", missing}},
                               {{"raw_sdf", values_of(mesh, sdf)}, {"distance_unit", request.inputs[0].unit}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"face_count", raw.faces.size()}, {"missing_count", missing}, {"minimum_raw_sdf", minimum},
               {"maximum_raw_sdf", maximum}, {"algorithm", "CGAL::sdf_values"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.8.01 segmentation_from_sdf_values -------------------------------------------------------
Json segmentation_operation(const Request& request) {
  require_inputs(request, 1, "mesh.segment.sdf");
  require_parameter_names(request, {"cone_angle", "number_of_rays", "number_of_clusters", "smoothing_lambda",
                                    "thickness_tolerance"});
  const auto p = sdf_parameters(request);
  const auto clusters = query_ops::integer_parameter(request, "number_of_clusters", 1, 16);
  const double lambda = finite_number(request.parameters, "smoothing_lambda", 0.0, 1.0, false);
  const auto raw = read_closed_mesh(request);
  SurfaceMesh mesh = build_mesh(raw);
  auto raw_sdf = mesh.add_property_map<Face, double>("f:raw_sdf", 0.0).first;
  CGAL::sdf_values(mesh, raw_sdf, p.cone_angle, p.rays, false);
  auto sdf = mesh.add_property_map<Face, double>("f:sdf", 0.0).first;
  const auto range = CGAL::sdf_values(mesh, sdf, p.cone_angle, p.rays, true);
  auto cluster_ids = mesh.add_property_map<Face, std::size_t>("f:cluster", 0).first;
  CGAL::segmentation_from_sdf_values(mesh, sdf, cluster_ids, clusters, lambda, true);
  auto segment_ids = mesh.add_property_map<Face, std::size_t>("f:segment", 0).first;
  const std::size_t segments = CGAL::segmentation_from_sdf_values(mesh, sdf, segment_ids, clusters, lambda, false);
  Json cluster_rows = Json::array(), segment_rows = Json::array();
  std::size_t used_clusters = 0;
  for (const auto f : mesh.faces()) {
    cluster_rows.push_back(cluster_ids[f]);
    segment_rows.push_back(segment_ids[f]);
    used_clusters = std::max(used_clusters, cluster_ids[f] + 1);
  }
  std::size_t missing = 0;
  double minimum = 0, maximum = 0;
  raw_statistics(mesh, raw_sdf, missing, minimum, maximum);
  Json report = geometry_frame(
      request, "sdf_segmentation", request.parameters, {{"mesh_sha256", request.inputs[0].sha256}},
      {{"face_count", raw.faces.size()}, {"segment_count", segments}, {"missing_count", missing}},
      {{"raw_sdf", values_of(mesh, raw_sdf)}, {"sdf", values_of(mesh, sdf)},
       {"postprocessed_range", Json::array({range.first, range.second})}, {"cluster_ids", std::move(cluster_rows)},
       {"segment_ids", std::move(segment_rows)}, {"distance_unit", request.inputs[0].unit}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"face_count", raw.faces.size()}, {"segment_count", segments}, {"cluster_upper_bound", used_clusters},
               {"missing_count", missing}, {"minimum_raw_sdf", minimum}, {"maximum_raw_sdf", maximum},
               {"algorithm", "CGAL::segmentation_from_sdf_values"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> sdf_producers() {
  using query_ops::query_definition;
  const std::string kernel = "CGAL::Exact_predicates_inexact_constructions_kernel";
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.segment.sdf_values", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", sdf_values_operation,
      {"Surface_mesh_segmentation"}, kernel,
      pinfo("mesh.validate.sdf_values", {"cone_angle", "number_of_rays", "thickness_tolerance"}, {"mesh"},
            {{"source_header", "CGAL/mesh_segmentation.h"}, {"maximum_input_faces", kMaximumSegmentationFaces}})));
  result.push_back(query_definition(
      "mesh.segment.sdf", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", segmentation_operation,
      {"Surface_mesh_segmentation"}, kernel,
      pinfo("mesh.validate.sdf_segmentation",
            {"cone_angle", "number_of_rays", "number_of_clusters", "smoothing_lambda", "thickness_tolerance"}, {"mesh"},
            {{"source_header", "CGAL/mesh_segmentation.h"}, {"maximum_input_faces", kMaximumSegmentationFaces}})));
  return result;
}

}  // namespace cgal_master::batch9
