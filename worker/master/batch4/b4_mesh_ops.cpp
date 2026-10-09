// Producers wrapping CGAL 6.2.1 Surface_mesh_shortest_path (7.8.04). Results are checked by the
// CGAL-free validators in b4_validators_mesh.cpp.

#include "b4_common.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/Surface_mesh_shortest_path.h>

#include <algorithm>
#include <cmath>
#include <iterator>

namespace cgal_master::batch4 {
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
using PathTraits = CGAL::Surface_mesh_shortest_path_traits<Epick, SurfaceMesh>;
using ShortestPaths = CGAL::Surface_mesh_shortest_path<PathTraits>;

// Receives the locations of a shortest path (query first, source last) as 3D points.
struct PathCollector {
  const ShortestPaths& paths;
  const SurfaceMesh& mesh;
  std::vector<V3>& points;
  void operator()(SurfaceMesh::Face_index face, ShortestPaths::Barycentric_coordinates coordinates) {
    const auto p = paths.point(face, coordinates);
    points.push_back({p.x(), p.y(), p.z()});
  }
  void operator()(SurfaceMesh::Vertex_index vertex) {
    const auto& p = mesh.point(vertex);
    points.push_back({p.x(), p.y(), p.z()});
  }
  void operator()(SurfaceMesh::Halfedge_index halfedge, double alpha) {
    const auto& p = mesh.point(mesh.source(halfedge));
    const auto& q = mesh.point(mesh.target(halfedge));
    points.push_back({(1 - alpha) * p.x() + alpha * q.x(), (1 - alpha) * p.y() + alpha * q.y(),
                      (1 - alpha) * p.z() + alpha * q.z()});
  }
};

Json shortest_path(const Request& request) {
  require_inputs(request, 1, "mesh.path.shortest");
  require_parameter_names(request, {"sources", "targets"});
  const auto raw = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  if (raw.faces.empty() || raw.faces.size() > kMaximumShortestPathFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_COUNT", "Between 1 and 64 triangles are supported");
  }
  for (const auto& face : raw.faces) {
    if (face.size() != 3) precondition("NOT_TRIANGULATED", "Every face must be a triangle");
  }
  const auto sources = parse_location_list(request, "sources", kMaximumShortestPathSources, raw);
  const auto targets = parse_location_list(request, "targets", kMaximumShortestPathTargets, raw);

  SurfaceMesh mesh;
  std::vector<SurfaceMesh::Vertex_index> vertices;
  for (const auto& v : raw.vertices) vertices.push_back(mesh.add_vertex(Epick::Point_3(v[0], v[1], v[2])));
  std::vector<SurfaceMesh::Face_index> faces;
  for (const auto& face : raw.faces) {
    const auto id = mesh.add_face(vertices.at(face[0]), vertices.at(face[1]), vertices.at(face[2]));
    if (id == SurfaceMesh::null_face()) {
      precondition("MESH_NOT_ORIENTED_MANIFOLD", "The triangles must form an orientable 2-manifold");
    }
    faces.push_back(id);
  }
  // Index maps below rely on insertion order being preserved.
  for (std::size_t i = 0; i < faces.size(); ++i) {
    if (static_cast<std::size_t>(faces[i]) != i) precondition("FACE_ORDER", "Face indices were reordered");
  }

  ShortestPaths paths(mesh);
  // CGAL orders a face's barycentric coordinates by the face halfedge cycle, which can be a rotation
  // of the OFF corner order; permute the caller's coordinates (given in OFF corner order) to match.
  auto coordinates = [&](const SurfaceLocation& l) {
    ShortestPaths::Barycentric_coordinates result{{0, 0, 0}};
    // Documented order: source(h), target(h), target(next(h)) for the face halfedge h.
    const auto h = mesh.halfedge(faces.at(l.face));
    const SurfaceMesh::Vertex_index order[3] = {mesh.source(h), mesh.target(h), mesh.target(mesh.next(h))};
    for (std::size_t slot = 0; slot < 3; ++slot) {
      for (std::size_t corner = 0; corner < 3; ++corner) {
        if (vertices.at(raw.faces[l.face][corner]) == order[slot]) result[slot] = l.barycentric[corner];
      }
    }
    return result;
  };
  for (const auto& s : sources) {
    if (s.is_vertex) paths.add_source_point(vertices.at(s.vertex));
    else paths.add_source_point(faces.at(s.face), coordinates(s));
  }
  paths.build_sequence_tree();

  Json rows = Json::array();
  double longest = 0;
  for (const auto& t : targets) {
    std::vector<V3> points;
    PathCollector collector{paths, mesh, points};
    ShortestPaths::Shortest_path_result result =
        t.is_vertex ? paths.shortest_path_sequence_to_source_points(vertices.at(t.vertex), collector)
                    : paths.shortest_path_sequence_to_source_points(faces.at(t.face), coordinates(t), collector);
    if (result.second == paths.source_points_end()) {
      precondition("TARGET_UNREACHABLE", "A target cannot be reached from any source point");
    }
    // CGAL reports the path from the query back to the source; the report runs source to target.
    std::reverse(points.begin(), points.end());
    Json path = Json::array();
    for (const auto& p : points) path.push_back(Json::array({p[0], p[1], p[2]}));
    std::size_t source_index = 0;
    for (auto it = paths.source_points_begin(); it != result.second; ++it) ++source_index;
    longest = std::max(longest, result.first);
    rows.push_back({{"distance", result.first}, {"source_index", source_index}, {"path", std::move(path)}});
  }
  Json report = geometry_frame(request, "shortest_paths", {{"sources", request.parameters.at("sources")}, {"targets", request.parameters.at("targets")}},
                               {{"mesh_sha256", request.inputs[0].sha256}},
                               {{"source_count", sources.size()}, {"target_count", targets.size()}},
                               {{"targets", rows}, {"distance_unit", request.inputs[0].unit}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"source_count", sources.size()}, {"target_count", targets.size()},
               {"face_count", raw.faces.size()}, {"longest_distance", longest},
               {"algorithm", "CGAL::Surface_mesh_shortest_path"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> mesh_producers() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.path.shortest", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", shortest_path,
      {"Surface_mesh_shortest_path"}, "CGAL::Exact_predicates_inexact_constructions_kernel",
      pinfo("mesh.validate.shortest_path", {"sources", "targets"}, {"mesh"},
            {{"source_header", "CGAL/Surface_mesh_shortest_path.h"},
             {"maximum_input_faces", kMaximumShortestPathFaces}})));
  return result;
}

}  // namespace cgal_master::batch4
