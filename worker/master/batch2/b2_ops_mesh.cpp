// Producers wrapping official CGAL 6.2.1 Polygon_mesh_processing APIs: detect_sharp_edges /
// sharp_edges_segmentation (7.3.05), self_intersections / does_self_intersect (7.3.07),
// clip (7.5.03), split and corefine (7.5.04). Every result is checked by an independent
// validator in b2_validators_mesh.cpp that includes no CGAL header. Output meshes are OFF
// files of binary64 coordinates, so a result is accepted only when every Epeck output
// coordinate is exactly representable as a double.

#include "b2_geometry.h"
#include "b2_registry.h"

#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygon_mesh_processing/clip.h>
#include <CGAL/Polygon_mesh_processing/corefinement.h>
#include <CGAL/Polygon_mesh_processing/detect_features.h>
#include <CGAL/Polygon_mesh_processing/intersection.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Surface_mesh.h>

#include <boost/container/flat_set.hpp>

#include <algorithm>
#include <cmath>
#include <iterator>
#include <map>
#include <set>

namespace cgal_master::batch2 {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;
using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using Epeck = CGAL::Exact_predicates_exact_constructions_kernel;
using EpickMesh = CGAL::Surface_mesh<Epick::Point_3>;
using EpeckMesh = CGAL::Surface_mesh<Epeck::Point_3>;
constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";
constexpr const char* kEpeckName = "CGAL::Exact_predicates_exact_constructions_kernel";

using query_ops::precondition;
using query_ops::read_raw_mesh;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::signed_length_parameter;
using query_ops::vector_parameter;
using query_ops::write_off_output;
using query_ops::write_report;

RawMesh load_input(const ArtifactInput& input) {
  auto raw = read_raw_mesh(input, {"TriangleSurfaceMesh"});
  if (raw.faces.size() > kMaximumFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "Input mesh exceeds the face limit");
  }
  for (const auto& face : raw.faces) {
    if (face.size() != 3) {
      throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED", "Input mesh must be triangulated");
    }
  }
  return raw;
}

template <typename Mesh, typename Point>
Mesh build_mesh(const RawMesh& raw) {
  Mesh mesh;
  std::vector<typename Mesh::Vertex_index> handles;
  for (const auto& v : raw.vertices) handles.push_back(mesh.add_vertex(Point(v[0], v[1], v[2])));
  std::size_t expected = 0;
  for (const auto& face : raw.faces) {
    std::set<std::size_t> distinct(face.begin(), face.end());
    if (distinct.size() != face.size()) {
      throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_FACE", "Input face repeats a vertex");
    }
    std::vector<typename Mesh::Vertex_index> cycle;
    for (const auto index : face) cycle.push_back(handles[index]);
    const auto added = mesh.add_face(cycle);
    if (added == Mesh::null_face() || static_cast<std::size_t>(added.idx()) != expected) {
      throw WorkerError("PRECONDITION_FAILED", "INVALID_POLYGON_MESH",
                        "Faces are not a manifold, consistently oriented mesh indexable in file order");
    }
    ++expected;
  }
  return mesh;
}

double exact_double(const Epeck::FT& value) {
  const double d = CGAL::to_double(value);
  if (!std::isfinite(d) || Epeck::FT(d) != value) {
    precondition("OUTPUT_NOT_REPRESENTABLE",
                 "An exact output coordinate is not representable as a binary64 value");
  }
  return d;
}

Json write_epeck_mesh(const Request& request, const EpeckMesh& mesh, const std::string& type, const std::string& unit) {
  if (mesh.number_of_faces() == 0) precondition("EMPTY_RESULT", "The operation produced no faces");
  if (mesh.number_of_faces() > kMaximumOutputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "Output mesh exceeds the face limit");
  }
  std::vector<V3> vertices;
  std::map<EpeckMesh::Vertex_index, std::size_t> ids;
  std::vector<std::vector<std::size_t>> faces;
  for (const auto face : mesh.faces()) {
    std::vector<std::size_t> cycle;
    for (const auto v : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      auto it = ids.find(v);
      if (it == ids.end()) {
        const auto& p = mesh.point(v);
        vertices.push_back({exact_double(p.x()), exact_double(p.y()), exact_double(p.z())});
        it = ids.emplace(v, vertices.size() - 1).first;
      }
      cycle.push_back(it->second);
    }
    faces.push_back(std::move(cycle));
  }
  return write_off_output(request, vertices, faces, type, unit);
}

Epeck::Plane_3 plane_parameters(const Request& request, V3& normal, double& offset) {
  normal = vector_parameter(request, "normal");
  offset = signed_length_parameter(request, "offset", request.inputs[0].unit);
  if (normal[0] == 0 && normal[1] == 0 && normal[2] == 0) {
    precondition("ZERO_NORMAL", "The plane normal must be nonzero");
  }
  return Epeck::Plane_3(normal[0], normal[1], normal[2], -offset);
}

void reject_coplanar_faces(const EpeckMesh& mesh, const Epeck::Plane_3& plane) {
  for (const auto face : mesh.faces()) {
    bool coplanar = true;
    for (const auto v : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      coplanar = coplanar && plane.oriented_side(mesh.point(v)) == CGAL::ON_ORIENTED_BOUNDARY;
    }
    if (coplanar) precondition("COPLANAR_FACE", "The plane contains a mesh face");
  }
}

Json plane_parameter_json(const V3& normal, double offset, const std::string& unit) {
  return {{"normal", Json::array({normal[0], normal[1], normal[2]})}, {"offset", {{"value", offset}, {"unit", unit}}}};
}

// ---- 7.3.05 -----------------------------------------------------------------------------

Json edge_list_json(const std::set<std::pair<std::size_t, std::size_t>>& edges) {
  Json result = Json::array();
  for (const auto& [a, b] : edges) result.push_back(Json::array({a, b}));
  return result;
}

Json detect_features(const Request& request) {
  require_inputs(request, 1, "mesh.features.detect");
  require_parameter_names(request, {"angle_degrees"});
  const auto raw = load_input(request.inputs[0]);
  const auto& angle_value = request.parameters.at("angle_degrees");
  if (!angle_value.is_number() || angle_value.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "angle_degrees must be a number");
  }
  const double angle = angle_value.get<double>();
  if (!std::isfinite(angle) || angle < 0 || angle > 180) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "angle_degrees must be in [0,180]");
  }
  auto mesh = build_mesh<EpickMesh, Epick::Point_3>(raw);
  auto edge_feature = mesh.add_property_map<EpickMesh::Edge_index, bool>("e:feature", false).first;
  auto patch_id = mesh.add_property_map<EpickMesh::Face_index, std::size_t>("f:patch", 0).first;
  auto feature_degree = mesh.add_property_map<EpickMesh::Vertex_index, std::size_t>("v:degree", 0).first;
  auto incident_patches =
      mesh.add_property_map<EpickMesh::Vertex_index, boost::container::flat_set<std::size_t>>("v:patches").first;

  auto collect = [&]() {
    std::set<std::pair<std::size_t, std::size_t>> edges;
    for (const auto e : mesh.edges()) {
      if (!get(edge_feature, e)) continue;
      const std::size_t a = mesh.source(mesh.halfedge(e)).idx(), b = mesh.target(mesh.halfedge(e)).idx();
      edges.insert({std::min(a, b), std::max(a, b)});
    }
    return edges;
  };
  PMP::detect_sharp_edges(mesh, angle, edge_feature);
  const auto sharp = collect();
  for (const auto e : mesh.edges()) put(edge_feature, e, false);
  const std::size_t patch_count = PMP::sharp_edges_segmentation(
      mesh, angle, edge_feature, patch_id,
      CGAL::parameters::vertex_incident_patches_map(incident_patches).vertex_feature_degree_map(feature_degree));
  const auto segmentation_sharp = collect();
  if (sharp != segmentation_sharp) {
    throw WorkerError("INTERNAL_ERROR", "FEATURE_SETS_DIFFER", "detect_sharp_edges and sharp_edges_segmentation disagree");
  }
  Json degrees = Json::array(), ids = Json::array(), patches = Json::array();
  for (const auto v : mesh.vertices()) {
    degrees.push_back(get(feature_degree, v));
    Json list = Json::array();
    for (const auto id : get(incident_patches, v)) list.push_back(id);
    patches.push_back(std::move(list));
  }
  for (const auto f : mesh.faces()) ids.push_back(get(patch_id, f));
  Json report = geometry_frame(
      request, "mesh_features", {{"angle_degrees", angle}}, {{"mesh_sha256", request.inputs[0].sha256}},
      {{"face_count", raw.faces.size()}, {"sharp_edge_count", sharp.size()}, {"patch_count", patch_count}},
      {{"sharp_edges", edge_list_json(sharp)},
       {"vertex_feature_degree", degrees},
       {"segmentation", {{"sharp_edges", edge_list_json(segmentation_sharp)},
                         {"patch_count", patch_count},
                         {"patch_ids", ids},
                         {"vertex_incident_patches", patches}}}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"face_count", raw.faces.size()}, {"sharp_edge_count", sharp.size()}, {"patch_count", patch_count},
               {"algorithm", "CGAL::Polygon_mesh_processing::sharp_edges_segmentation"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.3.07 -----------------------------------------------------------------------------

Json self_intersections(const Request& request) {
  require_inputs(request, 1, "mesh.intersections.self");
  require_parameter_names(request, {});
  const auto raw = load_input(request.inputs[0]);
  auto mesh = build_mesh<EpickMesh, Epick::Point_3>(raw);
  std::vector<std::pair<EpickMesh::Face_index, EpickMesh::Face_index>> pairs;
  PMP::self_intersections(mesh, std::back_inserter(pairs));
  const bool flag = PMP::does_self_intersect(mesh);
  std::set<std::pair<std::size_t, std::size_t>> sorted;
  for (const auto& [f, g] : pairs) {
    const std::size_t a = f.idx(), b = g.idx();
    sorted.insert({std::min(a, b), std::max(a, b)});
  }
  if (flag != !pairs.empty()) {
    throw WorkerError("INTERNAL_ERROR", "SELF_INTERSECTION_INCONSISTENT",
                      "does_self_intersect disagrees with self_intersections");
  }
  Json report = geometry_frame(
      request, "self_intersections", Json::object(), {{"mesh_sha256", request.inputs[0].sha256}},
      {{"face_count", raw.faces.size()}, {"intersecting_pair_count", sorted.size()}},
      {{"intersecting_face_pairs", edge_list_json(sorted)}, {"does_self_intersect", flag}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"face_count", raw.faces.size()}, {"intersecting_pair_count", sorted.size()},
               {"does_self_intersect", flag},
               {"algorithm", "CGAL::Polygon_mesh_processing::self_intersections"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.5.03 / 7.5.04 --------------------------------------------------------------------

Json clip_plane(const Request& request) {
  require_inputs(request, 1, "mesh.clip.plane");
  require_parameter_names(request, {"normal", "offset", "clip_volume"});
  const auto raw = load_input(request.inputs[0]);
  V3 normal{};
  double offset = 0;
  const auto plane = plane_parameters(request, normal, offset);
  const auto& flag = request.parameters.at("clip_volume");
  if (!flag.is_boolean()) throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "clip_volume must be boolean");
  const bool clip_volume = flag.get<bool>();
  auto mesh = build_mesh<EpeckMesh, Epeck::Point_3>(raw);
  reject_coplanar_faces(mesh, plane);
  PMP::clip(mesh, plane, CGAL::parameters::clip_volume(clip_volume));
  mesh.collect_garbage();
  auto output = write_epeck_mesh(request, mesh, "TriangleSurfaceMesh", request.inputs[0].unit);
  Json metrics{{"input_face_count", raw.faces.size()}, {"output_face_count", mesh.number_of_faces()},
               {"clip_volume", clip_volume}, {"algorithm", "CGAL::Polygon_mesh_processing::clip"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json split_plane(const Request& request) {
  require_inputs(request, 1, "mesh.split.plane");
  require_parameter_names(request, {"normal", "offset"});
  const auto raw = load_input(request.inputs[0]);
  V3 normal{};
  double offset = 0;
  const auto plane = plane_parameters(request, normal, offset);
  auto mesh = build_mesh<EpeckMesh, Epeck::Point_3>(raw);
  reject_coplanar_faces(mesh, plane);
  PMP::split(mesh, plane);
  mesh.collect_garbage();
  auto output = write_epeck_mesh(request, mesh, "PolygonSoup3", request.inputs[0].unit);
  Json metrics{{"input_face_count", raw.faces.size()}, {"output_face_count", mesh.number_of_faces()},
               {"algorithm", "CGAL::Polygon_mesh_processing::split"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json corefine_meshes(const Request& request) {
  require_inputs(request, 2, "mesh.corefine");
  require_parameter_names(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto first = load_input(request.inputs[0]);
  const auto second = load_input(request.inputs[1]);
  auto mesh = build_mesh<EpeckMesh, Epeck::Point_3>(first);
  auto other = build_mesh<EpeckMesh, Epeck::Point_3>(second);
  PMP::corefine(mesh, other, CGAL::parameters::default_values(), CGAL::parameters::do_not_modify(true));
  mesh.collect_garbage();
  auto output = write_epeck_mesh(request, mesh, "TriangleSurfaceMesh", request.inputs[0].unit);
  Json metrics{{"input_face_count", first.faces.size()}, {"other_face_count", second.faces.size()},
               {"output_face_count", mesh.number_of_faces()},
               {"algorithm", "CGAL::Polygon_mesh_processing::corefine"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> mesh_producer_operations() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.features.detect", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", detect_features,
      {"Polygon_mesh_processing"}, kEpickName,
      pinfo("mesh.validate.features", {"angle_degrees"}, {"mesh"},
            {{"source_header", "CGAL/Polygon_mesh_processing/detect_features.h"}, {"maximum_input_faces", kMaximumFaces}})));
  result.push_back(query_definition(
      "mesh.intersections.self", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", self_intersections,
      {"Polygon_mesh_processing"}, kEpickName,
      pinfo("mesh.validate.self_intersections", {}, {"mesh"},
            {{"source_header", "CGAL/Polygon_mesh_processing/self_intersections.h"}, {"maximum_input_faces", kMaximumFaces}})));
  result.push_back(query_definition(
      "mesh.clip.plane", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform", clip_plane,
      {"PMP_Boolean_operations"}, kEpeckName,
      pinfo("mesh.validate.clip", {"normal", "offset", "clip_volume"}, {"source"},
            {{"source_header", "CGAL/Polygon_mesh_processing/clip.h"}, {"maximum_input_faces", kMaximumFaces},
             {"maximum_output_faces", kMaximumOutputFaces}})));
  result.push_back(query_definition(
      "mesh.split.plane", {"TriangleSurfaceMesh"}, "PolygonSoup3", "transform", split_plane,
      {"PMP_Boolean_operations"}, kEpeckName,
      pinfo("mesh.validate.split", {"normal", "offset"}, {"source"},
            {{"source_header", "CGAL/Polygon_mesh_processing/clip.h"}, {"maximum_input_faces", kMaximumFaces},
             {"maximum_output_faces", kMaximumOutputFaces}})));
  result.push_back(query_definition(
      "mesh.corefine", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform",
      corefine_meshes, {"PMP_Boolean_operations"}, kEpeckName,
      pinfo("mesh.validate.corefine", {}, {"source", "other"},
            {{"source_header", "CGAL/Polygon_mesh_processing/corefinement.h"}, {"maximum_input_faces", kMaximumFaces},
             {"maximum_output_faces", kMaximumOutputFaces}})));
  return result;
}

}  // namespace cgal_master::batch2
