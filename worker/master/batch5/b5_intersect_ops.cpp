// Producers wrapping CGAL 6.2.1 PMP::do_intersect and PMP::intersection_polylines (7.3.07, the
// two-mesh half of "intersections / self-intersection"; the self half stays in
// mesh.analysis.self_intersections). intersection_polylines is the 6.2 name of the deprecated
// surface_intersection. Results are checked by b5_intersect_validators.cpp (no CGAL header).

#include "b5_common.h"

#include "../batch2/b2_broadphase.h"
#include "../batch2/b2_registry.h"
#include "../wave_c/wave_c_common.h"

#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygon_mesh_processing/intersection.h>
#include <CGAL/Polygon_mesh_processing/intersection_polylines.h>
#include <CGAL/Surface_mesh.h>

#include <iterator>
#include <set>

namespace cgal_master::batch5 {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;
using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using Epeck = CGAL::Exact_predicates_exact_constructions_kernel;
using EpickMesh = CGAL::Surface_mesh<Epick::Point_3>;
using EpeckMesh = CGAL::Surface_mesh<Epeck::Point_3>;
constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";
constexpr const char* kEpeckName = "CGAL::Exact_predicates_exact_constructions_kernel";

using batch2::geometry_frame;
using batch2::pinfo;
using query_ops::precondition;
using query_ops::RawMesh;
using query_ops::read_raw_mesh;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::write_report;

RawMesh load(const ArtifactInput& input) {
  auto raw = read_raw_mesh(input, {"TriangleSurfaceMesh"}, kMaximumIntersectionFaces);
  if (raw.faces.empty() || raw.faces.size() > kMaximumIntersectionFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "Each mesh needs between 1 and " + std::to_string(kMaximumIntersectionFaces) + " triangles");
  }
  for (const auto& face : raw.faces) {
    if (face.size() != 3) precondition("MESH_NOT_TRIANGULATED", "Input meshes must be triangulated");
  }
  return raw;
}

template <typename Mesh, typename Point>
Mesh build(const RawMesh& raw) {
  Mesh mesh;
  std::vector<typename Mesh::Vertex_index> handles;
  for (const auto& v : raw.vertices) handles.push_back(mesh.add_vertex(Point(v[0], v[1], v[2])));
  std::size_t expected = 0;
  for (const auto& face : raw.faces) {
    std::set<std::size_t> distinct(face.begin(), face.end());
    if (distinct.size() != 3) precondition("DEGENERATE_FACE", "A face repeats a vertex");
    const auto added = mesh.add_face(handles[face[0]], handles[face[1]], handles[face[2]]);
    if (added == Mesh::null_face() || static_cast<std::size_t>(added.idx()) != expected) {
      precondition("INVALID_POLYGON_MESH", "Faces are not a manifold, consistently oriented mesh indexable in file order");
    }
    ++expected;
  }
  for (const auto f : mesh.faces()) {
    auto h = mesh.halfedge(f);
    if (CGAL::collinear(mesh.point(mesh.source(h)), mesh.point(mesh.target(h)), mesh.point(mesh.target(mesh.next(h))))) {
      precondition("DEGENERATE_FACE", "A face has zero area");
    }
  }
  return mesh;
}

Json do_intersect_op(const Request& request) {
  require_inputs(request, 2, "mesh.intersections.do_intersect");
  require_parameter_names(request, {"overlap_test"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto& flag = request.parameters.at("overlap_test");
  if (!flag.is_boolean()) throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "overlap_test must be boolean");
  const bool overlap = flag.get<bool>();
  const auto first = load(request.inputs[0]);
  const auto second = load(request.inputs[1]);
  auto a = build<EpickMesh, Epick::Point_3>(first);
  auto b = build<EpickMesh, Epick::Point_3>(second);
  if (overlap && (!CGAL::is_closed(a) || !CGAL::is_closed(b))) {
    precondition("MESH_NOT_CLOSED", "The bounded-side overlap test needs two closed meshes");
  }
  const bool result = PMP::do_intersect(a, b, CGAL::parameters::do_overlap_test_of_bounded_sides(overlap));
  Json report = geometry_frame(
      request, "mesh_do_intersect", {{"overlap_test", overlap}},
      {{"first_sha256", request.inputs[0].sha256}, {"second_sha256", request.inputs[1].sha256}},
      {{"first_face_count", first.faces.size()}, {"second_face_count", second.faces.size()}},
      {{"intersect", result}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"intersect", result}, {"overlap_test", overlap}, {"algorithm", "CGAL::Polygon_mesh_processing::do_intersect"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json polylines_op(const Request& request) {
  require_inputs(request, 2, "mesh.intersections.polylines");
  require_parameter_names(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto first = load(request.inputs[0]);
  const auto second = load(request.inputs[1]);
  auto a = build<EpeckMesh, Epeck::Point_3>(first);
  auto b = build<EpeckMesh, Epeck::Point_3>(second);
  // Coplanar overlapping triangles make the intersection two-dimensional; the report format and the
  // independent validator describe one-dimensional intersection curves only.
  // Only face pairs whose closed binary64 boxes meet can intersect (b2_broadphase.h); faces are
  // indexed in file order, so the raw coordinates are those of the mesh faces.
  const auto triangle_of = [](const RawMesh& raw, std::size_t face) {
    std::array<Epeck::Point_3, 3> points;
    for (std::size_t k = 0; k < 3; ++k) {
      const auto& v = raw.vertices[raw.faces[face][k]];
      points[k] = Epeck::Point_3(v[0], v[1], v[2]);
    }
    return points;
  };
  const auto box_of_face = [](const RawMesh& raw, std::size_t face) {
    batch2::Box box = batch2::empty_box();
    for (std::size_t k = 0; k < 3; ++k) {
      const auto& v = raw.vertices[raw.faces[face][k]];
      for (int axis = 0; axis < 3; ++axis) {
        box.lo[axis] = std::min(box.lo[axis], v[axis]);
        box.hi[axis] = std::max(box.hi[axis], v[axis]);
      }
    }
    return box;
  };
  std::vector<batch2::Box> second_boxes;
  second_boxes.reserve(second.faces.size());
  for (std::size_t j = 0; j < second.faces.size(); ++j) second_boxes.push_back(box_of_face(second, j));
  const batch2::BoxTree second_tree(std::move(second_boxes));
  for (std::size_t i = 0; i < first.faces.size(); ++i) {
    const auto pa = triangle_of(first, i);
    second_tree.query(box_of_face(first, i), [&](std::size_t j) {
      const auto pb = triangle_of(second, j);
      if (CGAL::coplanar(pa[0], pa[1], pa[2], pb[0]) && CGAL::coplanar(pa[0], pa[1], pa[2], pb[1]) &&
          CGAL::coplanar(pa[0], pa[1], pa[2], pb[2]) &&
          CGAL::do_intersect(Epeck::Triangle_3(pa[0], pa[1], pa[2]), Epeck::Triangle_3(pb[0], pb[1], pb[2]))) {
        precondition("COPLANAR_TRIANGLES", "Two coplanar triangles of the meshes intersect; the intersection is not a curve");
      }
    });
  }
  std::vector<std::vector<Epeck::Point_3>> polylines;
  PMP::intersection_polylines(a, b, std::back_inserter(polylines));
  Json lines = Json::array();
  std::size_t segments = 0;
  for (const auto& line : polylines) {
    Json points = Json::array();
    for (const auto& p : line) {
      points.push_back(Json::array({wave_c::exact_string(p.x()), wave_c::exact_string(p.y()), wave_c::exact_string(p.z())}));
    }
    if (line.size() > 1) segments += line.size() - 1;
    lines.push_back({{"points", std::move(points)}});
  }
  Json report = geometry_frame(
      request, "mesh_intersection_polylines", Json::object(),
      {{"first_sha256", request.inputs[0].sha256}, {"second_sha256", request.inputs[1].sha256}},
      {{"polyline_count", polylines.size()}, {"segment_count", segments}},
      {{"polylines", lines}, {"coordinate_encoding", "exact rationals p/q"}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"polyline_count", polylines.size()}, {"segment_count", segments},
               {"algorithm", "CGAL::Polygon_mesh_processing::intersection_polylines"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> intersection_producers() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.intersections.do_intersect", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "GeometryQueryReport",
      "analysis", do_intersect_op, {"Polygon_mesh_processing", "Surface_mesh"}, kEpickName,
      pinfo("mesh.validate.do_intersect", {"overlap_test"}, {"first", "second"},
            {{"source_header", "CGAL/Polygon_mesh_processing/intersection.h"},
             {"maximum_input_faces", kMaximumIntersectionFaces}})));
  result.push_back(query_definition(
      "mesh.intersections.polylines", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "GeometryQueryReport",
      "analysis", polylines_op, {"Polygon_mesh_processing", "Surface_mesh"}, kEpeckName,
      pinfo("mesh.validate.intersection_polylines", {}, {"first", "second"},
            {{"source_header", "CGAL/Polygon_mesh_processing/intersection_polylines.h"},
             {"maximum_input_faces", kMaximumIntersectionFaces}})));
  return result;
}

}  // namespace cgal_master::batch5
