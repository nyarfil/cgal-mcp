// Producers for the query / mesh-processing family additions, wrapping official CGAL
// 6.2.1 APIs: Barycentric_coordinates_2 (7.13.05), AABB_tree intersection queries
// (7.2.04), PMP connected components (7.3.02), PMP locate (7.3.08), Polygon_mesh_slicer
// (7.5.05) and Subdivision_method_3 (7.8.06). Every report/mesh is checked by an
// independent validator in query_validators.cpp that includes no CGAL header.

#include "query_common.h"

#include "../wave_c/wave_c_common.h"

#include <CGAL/AABB_face_graph_triangle_primitive.h>
#include <CGAL/AABB_traits_3.h>
#include <CGAL/AABB_tree.h>
#include <CGAL/Barycentric_coordinates_2/Wachspress_coordinates_2.h>
#include <CGAL/Barycentric_coordinates_2/Mean_value_coordinates_2.h>
#include <CGAL/Barycentric_coordinates_2/Discrete_harmonic_coordinates_2.h>
#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygon_2.h>
#include <CGAL/Polygon_mesh_processing/connected_components.h>
#include <CGAL/Polygon_mesh_processing/locate.h>
#include <CGAL/Polygon_mesh_slicer.h>
#include <CGAL/Subdivision_method_3/subdivision_methods_3.h>
#include <CGAL/Surface_mesh.h>

#include <algorithm>
#include <cmath>
#include <iterator>
#include <map>
#include <set>
#include <sstream>

namespace cgal_master::query_ops {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;
namespace BC = CGAL::Barycentric_coordinates;
using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using Epeck = CGAL::Exact_predicates_exact_constructions_kernel;
using EpickMesh = CGAL::Surface_mesh<Epick::Point_3>;
using EpeckMesh = CGAL::Surface_mesh<Epeck::Point_3>;

constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";
constexpr const char* kEpeckName = "CGAL::Exact_predicates_exact_constructions_kernel";

std::string epeck_text(const Epeck::FT& value) { return wave_c::exact_string(value); }

Json epeck_point(const Epeck::Point_3& p) {
  return Json::array({epeck_text(p.x()), epeck_text(p.y()), epeck_text(p.z())});
}

void require_triangles(const RawMesh& raw) {
  if (raw.faces.size() > kMaximumQueryFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "Input mesh exceeds the face limit");
  }
  for (const auto& face : raw.faces) {
    if (face.size() != 3) {
      throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED", "Input mesh must be triangulated");
    }
  }
}

template <typename Mesh, typename Point>
Mesh build_mesh(const RawMesh& raw, Point (*make)(const V3&)) {
  Mesh mesh;
  std::vector<typename Mesh::Vertex_index> handles;
  for (const auto& vertex : raw.vertices) handles.push_back(mesh.add_vertex(make(vertex)));
  std::size_t expected = 0;
  for (const auto& face : raw.faces) {
    std::vector<typename Mesh::Vertex_index> cycle;
    std::set<std::size_t> distinct(face.begin(), face.end());
    if (distinct.size() != face.size()) {
      throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_FACE", "Input face repeats a vertex");
    }
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

Epick::Point_3 epick_point(const V3& v) { return Epick::Point_3(v[0], v[1], v[2]); }
Epeck::Point_3 epeck_point_of(const V3& v) { return Epeck::Point_3(v[0], v[1], v[2]); }

EpickMesh epick_mesh(const RawMesh& raw) { return build_mesh<EpickMesh, Epick::Point_3>(raw, epick_point); }
EpeckMesh epeck_mesh(const RawMesh& raw) { return build_mesh<EpeckMesh, Epeck::Point_3>(raw, epeck_point_of); }

Json geometry_report(const Request& request, const std::string& kind, Json parameters, Json source,
                     Json summary, Json results) {
  return Json{{"schema_version", 1},
              {"report_type", "GeometryQueryReport"},
              {"report_kind", kind},
              {"operation", request.operation},
              {"length_unit", request.inputs[0].unit},
              {"parameters", std::move(parameters)},
              {"source", std::move(source)},
              {"summary", std::move(summary)},
              {"results", std::move(results)}};
}

// ---- 7.13.05 Barycentric_coordinates_2 ------------------------------------------

Json compute_barycentric(const Request& request) {
  require_inputs(request, 2, "shape.barycentric");
  require_parameter_names(request, {"method"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto method = enum_parameter(request, "method", {"wachspress", "mean_value", "discrete_harmonic"});
  const auto polygon = read_polygon(request.inputs[0]);
  const auto queries = read_points2(request.inputs[1]);
  if (polygon.size() > kMaximumPolygonVertices || queries.size() > kMaximumQueries) {
    throw WorkerError("RESOURCE_LIMIT", "SIZE_LIMIT_EXCEEDED", "Polygon or query set exceeds the limit");
  }
  CGAL::Polygon_2<Epeck> exact_polygon;
  std::vector<Epick::Point_2> points;
  for (const auto& v : polygon) {
    exact_polygon.push_back(Epeck::Point_2(v[0], v[1]));
    points.emplace_back(v[0], v[1]);
  }
  if (!exact_polygon.is_simple()) precondition("POLYGON_NOT_SIMPLE", "The polygon must be simple");
  if (!exact_polygon.is_counterclockwise_oriented()) {
    precondition("POLYGON_NOT_COUNTERCLOCKWISE", "The polygon must be counterclockwise oriented");
  }
  if (method != "mean_value") {
    const auto n = polygon.size();
    for (std::size_t i = 0; i < n; ++i) {
      if (CGAL::orientation(exact_polygon[i], exact_polygon[(i + 1) % n], exact_polygon[(i + 2) % n]) !=
          CGAL::LEFT_TURN) {
        precondition("POLYGON_NOT_STRICTLY_CONVEX", method + " coordinates require a strictly convex polygon");
      }
    }
  }
  Json results = Json::array();
  for (std::size_t q = 0; q < queries.size(); ++q) {
    if (exact_polygon.bounded_side(Epeck::Point_2(queries[q][0], queries[q][1])) != CGAL::ON_BOUNDED_SIDE) {
      precondition("QUERY_NOT_STRICTLY_INSIDE", "Every query point must lie strictly inside the polygon");
    }
    const Epick::Point_2 query(queries[q][0], queries[q][1]);
    std::vector<double> coordinates;
    coordinates.reserve(points.size());
    if (method == "wachspress") {
      BC::wachspress_coordinates_2(points, query, std::back_inserter(coordinates));
    } else if (method == "mean_value") {
      BC::mean_value_coordinates_2(points, query, std::back_inserter(coordinates));
    } else {
      BC::discrete_harmonic_coordinates_2(points, query, std::back_inserter(coordinates));
    }
    if (coordinates.size() != polygon.size()) {
      throw WorkerError("INTERNAL_ERROR", "COORDINATE_COUNT", "CGAL returned a wrong coordinate count");
    }
    for (const double c : coordinates) {
      if (!std::isfinite(c)) throw WorkerError("OPERATION_FAILED", "NONFINITE_COORDINATE", "Coordinate is not finite");
    }
    results.push_back({{"query_index", q}, {"point", Json::array({queries[q][0], queries[q][1]})},
                       {"coordinates", coordinates}});
  }
  Json report = geometry_report(
      request, "barycentric_coordinates", {{"method", method}},
      {{"polygon_sha256", request.inputs[0].sha256}, {"queries_sha256", request.inputs[1].sha256}},
      {{"vertex_count", polygon.size()}, {"query_count", queries.size()}}, results);
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"vertex_count", polygon.size()},
               {"query_count", queries.size()},
               {"method", method},
               {"algorithm", method == "wachspress"    ? "CGAL::Barycentric_coordinates::wachspress_coordinates_2"
                             : method == "mean_value" ? "CGAL::Barycentric_coordinates::mean_value_coordinates_2"
                                                      : "CGAL::Barycentric_coordinates::discrete_harmonic_coordinates_2"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.2.04 AABB_tree intersection queries ---------------------------------------

Json aabb_intersections(const Request& request) {
  require_inputs(request, 2, "spatial.aabb.intersections");
  require_parameter_names(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto raw = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  require_triangles(raw);
  const auto rays = read_rays(request.inputs[1]);
  if (rays.size() > kMaximumQueries) {
    throw WorkerError("RESOURCE_LIMIT", "QUERY_LIMIT_EXCEEDED", "Ray batch exceeds the query limit");
  }
  const auto mesh = epick_mesh(raw);
  using Primitive = CGAL::AABB_face_graph_triangle_primitive<EpickMesh>;
  using Tree = CGAL::AABB_tree<CGAL::AABB_traits_3<Epick, Primitive>>;
  Tree tree(faces(mesh).first, faces(mesh).second, mesh);
  tree.build();
  Json results = Json::array();
  std::size_t intersecting = 0;
  for (std::size_t r = 0; r < rays.size(); ++r) {
    const Epick::Ray_3 ray(epick_point(rays[r].origin),
                           Epick::Vector_3(rays[r].direction[0], rays[r].direction[1], rays[r].direction[2]));
    const bool any_hit = tree.do_intersect(ray);
    const auto any = tree.any_intersected_primitive(ray);
    std::vector<EpickMesh::Face_index> all;
    tree.all_intersected_primitives(ray, std::back_inserter(all));
    std::vector<std::size_t> ids;
    for (const auto face : all) ids.push_back(static_cast<std::size_t>(face.idx()));
    std::sort(ids.begin(), ids.end());
    intersecting += any_hit ? 1 : 0;
    Json entry{{"ray_index", r}, {"do_intersect", any_hit}, {"faces", ids}};
    entry["any_face"] = any ? Json(static_cast<std::size_t>(any->idx())) : Json(nullptr);
    results.push_back(std::move(entry));
  }
  Json report{{"schema_version", 1},
              {"report_type", "SpatialQueryReport"},
              {"query_kind", "aabb_ray_intersections"},
              {"operation", request.operation},
              {"length_unit", request.inputs[0].unit},
              {"source", {{"mesh_sha256", request.inputs[0].sha256}, {"rays_sha256", request.inputs[1].sha256}}},
              {"parameters", Json::object()},
              {"summary", {{"ray_count", rays.size()}, {"intersecting_ray_count", intersecting},
                           {"face_count", raw.faces.size()}}},
              {"results", results}};
  auto output = write_report(request, "SpatialQueryReport", report);
  Json metrics{{"ray_count", rays.size()}, {"intersecting_ray_count", intersecting},
               {"face_count", raw.faces.size()},
               {"algorithm", "CGAL::AABB_tree::do_intersect / any_intersected_primitive / all_intersected_primitives"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.3.02 PMP connected components ----------------------------------------------

Json component_label(const Request& request) {
  require_inputs(request, 1, "mesh.components.label");
  require_parameter_names(request, {});
  const auto raw = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  require_triangles(raw);
  auto mesh = epick_mesh(raw);
  auto map = mesh.add_property_map<EpickMesh::Face_index, std::size_t>("f:component", 0).first;
  const auto count = PMP::connected_components(mesh, map);
  std::vector<std::size_t> labels(raw.faces.size()), sizes(count, 0);
  for (const auto face : mesh.faces()) {
    labels[static_cast<std::size_t>(face.idx())] = map[face];
    ++sizes[map[face]];
  }
  Json report = geometry_report(request, "connected_components", Json::object(),
                                {{"mesh_sha256", request.inputs[0].sha256}},
                                {{"face_count", raw.faces.size()}, {"component_count", count}},
                                {{"component_count", count}, {"face_labels", labels}, {"component_sizes", sizes}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"face_count", raw.faces.size()}, {"component_count", count},
               {"algorithm", "CGAL::Polygon_mesh_processing::connected_components"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// Output mesh holding exactly the given faces (vertex cycles preserved).
Json emit_selected_faces(const Request& request, const EpickMesh& mesh,
                         const std::vector<EpickMesh::Face_index>& selected, Json metrics,
                         const std::string& algorithm) {
  std::map<std::size_t, std::size_t> renumber;
  std::vector<V3> vertices;
  std::vector<std::vector<std::size_t>> faces;
  for (const auto face : selected) {
    std::vector<std::size_t> cycle;
    for (const auto vertex : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      const auto key = static_cast<std::size_t>(vertex.idx());
      auto found = renumber.find(key);
      if (found == renumber.end()) {
        found = renumber.emplace(key, vertices.size()).first;
        const auto& p = mesh.point(vertex);
        vertices.push_back({p.x(), p.y(), p.z()});
      }
      cycle.push_back(found->second);
    }
    faces.push_back(std::move(cycle));
  }
  if (faces.empty()) throw WorkerError("OPERATION_FAILED", "EMPTY_OUTPUT", "Operation produced an empty mesh");
  metrics["output_face_count"] = faces.size();
  metrics["output_vertex_count"] = vertices.size();
  metrics["algorithm"] = algorithm;
  auto output = write_off_output(request, vertices, faces, "TriangleSurfaceMesh", request.inputs[0].unit);
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json component_of_face(const Request& request) {
  require_inputs(request, 1, "mesh.components.component");
  require_parameter_names(request, {"face"});
  const auto raw = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  require_triangles(raw);
  const auto face_index = integer_parameter(request, "face", 0, raw.faces.size() - 1);
  auto mesh = epick_mesh(raw);
  std::vector<EpickMesh::Face_index> selected;
  PMP::connected_component(EpickMesh::Face_index(static_cast<std::uint32_t>(face_index)), mesh,
                           std::back_inserter(selected));
  std::sort(selected.begin(), selected.end());
  return emit_selected_faces(request, mesh, selected, {{"input_face_count", raw.faces.size()}, {"seed_face", face_index}},
                             "CGAL::Polygon_mesh_processing::connected_component");
}

Json keep_largest(const Request& request) {
  require_inputs(request, 1, "mesh.components.keep_largest");
  require_parameter_names(request, {"count"});
  const auto raw = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  require_triangles(raw);
  const auto keep = integer_parameter(request, "count", 1, 1000);
  auto mesh = epick_mesh(raw);
  {
    auto map = mesh.add_property_map<EpickMesh::Face_index, std::size_t>("f:probe", 0).first;
    const auto total = PMP::connected_components(mesh, map);
    std::vector<std::size_t> sizes(total, 0);
    for (const auto face : mesh.faces()) ++sizes[map[face]];
    std::sort(sizes.rbegin(), sizes.rend());
    if (keep < total && sizes[keep - 1] == sizes[keep]) {
      precondition("AMBIGUOUS_COMPONENT_TIE",
                   "The kept set is not unique: the smallest kept component ties with the largest removed one");
    }
  }
  const auto input_faces = raw.faces.size();
  const auto removed = PMP::keep_largest_connected_components(mesh, keep);
  mesh.collect_garbage();
  std::vector<EpickMesh::Face_index> selected(mesh.faces().begin(), mesh.faces().end());
  return emit_selected_faces(request, mesh, selected,
                             {{"input_face_count", input_faces}, {"components_requested", keep},
                              {"components_removed", removed}},
                             "CGAL::Polygon_mesh_processing::keep_largest_connected_components");
}

// ---- 7.3.08 PMP locate --------------------------------------------------------------

Json locate_points(const Request& request) {
  require_inputs(request, 2, "mesh.location.locate");
  require_parameter_names(request, {"strategy"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto strategy = enum_parameter(request, "strategy", {"locate", "locate_with_AABB_tree"});
  const auto raw = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  require_triangles(raw);
  const auto queries = read_points3(request.inputs[1]);
  if (queries.size() > kMaximumQueries || queries.size() * raw.faces.size() > 400000) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED",
                      "Mesh and query counts exceed the mandatory validation budget");
  }
  const auto mesh = epeck_mesh(raw);
  for (const auto face : mesh.faces()) {
    auto h = mesh.halfedge(face);
    if (CGAL::collinear(mesh.point(mesh.source(h)), mesh.point(mesh.target(h)),
                        mesh.point(mesh.target(mesh.next(h))))) {
      precondition("DEGENERATE_FACE", "Mesh contains a zero-area face");
    }
  }
  using Primitive = CGAL::AABB_face_graph_triangle_primitive<EpeckMesh>;
  using Tree = CGAL::AABB_tree<CGAL::AABB_traits_3<Epeck, Primitive>>;
  Tree tree;
  if (strategy == "locate_with_AABB_tree") PMP::build_AABB_tree(mesh, tree);
  Json results = Json::array();
  for (std::size_t q = 0; q < queries.size(); ++q) {
    const Epeck::Point_3 query(queries[q][0], queries[q][1], queries[q][2]);
    const auto location = strategy == "locate" ? PMP::locate(query, mesh)
                                               : PMP::locate_with_AABB_tree(query, tree, mesh);
    const auto point = PMP::construct_point(location, mesh);
    const auto squared = CGAL::squared_distance(query, point);
    // CGAL orders the coordinates by the face halfedge; report them in the face's
    // input (file) vertex order so the result is independent of halfedge bookkeeping.
    const auto face_index = static_cast<std::size_t>(location.first.idx());
    std::vector<std::pair<std::size_t, std::string>> by_vertex;
    // PMP::locate documents the order as source(h), target(h), target(next(h)) for h = halfedge(f).
    const auto h0 = mesh.halfedge(location.first);
    const std::array<typename EpeckMesh::Vertex_index, 3> order{mesh.source(h0), mesh.target(h0),
                                                               mesh.target(mesh.next(h0))};
    for (std::size_t position = 0; position < 3; ++position) {
      by_vertex.emplace_back(static_cast<std::size_t>(order[position].idx()), epeck_text(location.second[position]));
    }
    Json ordered = Json::array();
    for (const auto corner : raw.faces[face_index]) {
      for (const auto& entry : by_vertex) {
        if (entry.first == corner) ordered.push_back(entry.second);
      }
    }
    results.push_back({{"query_index", q},
                       {"face", face_index},
                       {"barycentric", ordered},
                       {"point", epeck_point(point)},
                       {"squared_distance", epeck_text(squared)}});
  }
  Json report = geometry_report(request, "mesh_location", {{"strategy", strategy}},
                                {{"mesh_sha256", request.inputs[0].sha256}, {"queries_sha256", request.inputs[1].sha256}},
                                {{"face_count", raw.faces.size()}, {"query_count", queries.size()},
                                 {"squared_distance_unit", request.inputs[0].unit + "2"}},
                                results);
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"face_count", raw.faces.size()}, {"query_count", queries.size()}, {"strategy", strategy},
               {"algorithm", strategy == "locate" ? "CGAL::Polygon_mesh_processing::locate"
                                                  : "CGAL::Polygon_mesh_processing::locate_with_AABB_tree"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.5.05 Polygon_mesh_slicer ---------------------------------------------------

Json slice_mesh(const Request& request) {
  require_inputs(request, 1, "mesh.slice.compute");
  require_parameter_names(request, {"normal", "offset"});
  const auto raw = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  require_triangles(raw);
  const auto normal = vector_parameter(request, "normal");
  const double offset = signed_length_parameter(request, "offset", request.inputs[0].unit);
  if (normal[0] == 0 && normal[1] == 0 && normal[2] == 0) {
    precondition("ZERO_NORMAL", "The slicing plane normal must be nonzero");
  }
  const auto mesh = epeck_mesh(raw);
  const Epeck::Plane_3 plane(normal[0], normal[1], normal[2], -offset);
  for (const auto face : mesh.faces()) {
    bool coplanar = true;
    for (const auto vertex : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      coplanar = coplanar && plane.oriented_side(mesh.point(vertex)) == CGAL::ON_ORIENTED_BOUNDARY;
    }
    if (coplanar) {
      precondition("COPLANAR_FACE", "The slicing plane contains a mesh face; the slice is not a curve");
    }
  }
  CGAL::Polygon_mesh_slicer<EpeckMesh, Epeck> slicer(mesh);
  std::vector<std::vector<Epeck::Point_3>> polylines;
  slicer(plane, std::back_inserter(polylines));
  Json items = Json::array();
  std::size_t closed_count = 0;
  for (const auto& polyline : polylines) {
    const bool closed = polyline.size() > 2 && polyline.front() == polyline.back();
    closed_count += closed ? 1 : 0;
    Json points = Json::array();
    for (const auto& p : polyline) points.push_back(epeck_point(p));
    items.push_back({{"closed", closed}, {"points", points}});
  }
  Json report = geometry_report(
      request, "mesh_slice",
      {{"normal", Json::array({normal[0], normal[1], normal[2]})},
       {"offset", {{"value", offset}, {"unit", request.inputs[0].unit}}}},
      {{"mesh_sha256", request.inputs[0].sha256}},
      {{"face_count", raw.faces.size()}, {"polyline_count", polylines.size()}, {"closed_polyline_count", closed_count}},
      {{"polylines", items}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"face_count", raw.faces.size()}, {"polyline_count", polylines.size()},
               {"closed_polyline_count", closed_count},
               {"algorithm", "CGAL::Polygon_mesh_slicer"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.8.06 Subdivision_method_3 ---------------------------------------------------

Json subdivide(const Request& request, bool catmull_clark) {
  const std::string name = catmull_clark ? "mesh.subdivide.catmull_clark" : "mesh.subdivide.loop";
  require_inputs(request, 1, name);
  require_parameter_names(request, {"steps"});
  const auto steps = integer_parameter(request, "steps", 1, kMaximumSubdivisionSteps);
  const auto raw = read_raw_mesh(request.inputs[0],
                                 catmull_clark ? std::initializer_list<const char*>{"TriangleSurfaceMesh", "PolygonSoup3"}
                                               : std::initializer_list<const char*>{"TriangleSurfaceMesh"});
  if (raw.faces.size() > kMaximumSubdivisionInputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "Input mesh exceeds the subdivision face limit");
  }
  for (const auto& face : raw.faces) {
    if (!catmull_clark && face.size() != 3) {
      throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED", "Loop subdivision needs a triangle mesh");
    }
  }
  // Loop: every step quadruples the faces. Catmull-Clark: the first step makes one quad per
  // corner, every later step quadruples the quads.
  std::size_t estimate = 0;
  if (catmull_clark) {
    for (const auto& face : raw.faces) estimate += face.size();
    for (std::size_t s = 1; s < steps; ++s) estimate *= 4;
  } else {
    estimate = raw.faces.size();
    for (std::size_t s = 0; s < steps; ++s) estimate *= 4;
  }
  if (estimate > kMaximumSubdivisionOutputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "OUTPUT_FACE_LIMIT_EXCEEDED", "Subdivision would exceed the output face budget");
  }
  auto mesh = epick_mesh(raw);
  if (catmull_clark) {
    CGAL::Subdivision_method_3::CatmullClark_subdivision(mesh, CGAL::parameters::number_of_iterations(steps));
  } else {
    CGAL::Subdivision_method_3::Loop_subdivision(mesh, CGAL::parameters::number_of_iterations(steps));
  }
  mesh.collect_garbage();
  std::vector<V3> vertices;
  std::map<std::size_t, std::size_t> renumber;
  for (const auto vertex : mesh.vertices()) {
    renumber[static_cast<std::size_t>(vertex.idx())] = vertices.size();
    const auto& p = mesh.point(vertex);
    vertices.push_back({p.x(), p.y(), p.z()});
  }
  std::vector<std::vector<std::size_t>> faces;
  for (const auto face : mesh.faces()) {
    std::vector<std::size_t> cycle;
    for (const auto vertex : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      cycle.push_back(renumber.at(static_cast<std::size_t>(vertex.idx())));
    }
    faces.push_back(std::move(cycle));
  }
  Json metrics{{"input_face_count", raw.faces.size()}, {"output_face_count", faces.size()},
               {"output_vertex_count", vertices.size()}, {"steps", steps},
               {"algorithm", catmull_clark ? "CGAL::Subdivision_method_3::CatmullClark_subdivision"
                                           : "CGAL::Subdivision_method_3::Loop_subdivision"}};
  auto output = write_off_output(request, vertices, faces, catmull_clark ? "PolygonSoup3" : "TriangleSurfaceMesh",
                                 request.inputs[0].unit);
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json catmull_clark(const Request& request) { return subdivide(request, true); }
Json loop(const Request& request) { return subdivide(request, false); }

Json info(const std::string& validator, const std::vector<std::string>& parameters,
          std::vector<std::string> slots, Json extra) {
  Json bindings = Json::object();
  for (const auto& name : parameters) bindings[name] = name;
  Json result{{"input_slots", slots},
              {"validators", Json::array({validator})},
              {"validator_parameter_bindings", {{validator, bindings}}}};
  if (parameters.empty()) result.erase("validator_parameter_bindings");
  for (auto& item : extra.items()) result[item.key()] = item.value();
  return result;
}

}  // namespace

std::vector<OperationDefinition> producer_operations() {
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "shape.barycentric", {"Polygon2", "PointSet2"}, "GeometryQueryReport", "analysis", compute_barycentric,
      {"Barycentric_coordinates_2"}, kEpickName,
      info("shape.validate.barycentric", {"method"}, {"polygon", "queries"},
           {{"source_header", "CGAL/Barycentric_coordinates_2/Wachspress_coordinates_2.h"},
            {"maximum_polygon_vertices", kMaximumPolygonVertices}})));
  result.push_back(query_definition(
      "spatial.aabb.intersections", {"TriangleSurfaceMesh", "RayBatch3"}, "SpatialQueryReport", "analysis",
      aabb_intersections, {"AABB_tree"}, kEpickName,
      info("spatial.validate.aabb_intersections", {}, {"mesh", "rays"},
           {{"source_header", "CGAL/AABB_tree.h"}, {"maximum_queries", kMaximumQueries}})));
  result.push_back(query_definition(
      "mesh.components.label", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", component_label,
      {"Polygon_mesh_processing"}, kEpickName,
      info("mesh.validate.components_label", {}, {"mesh"},
           {{"source_header", "CGAL/Polygon_mesh_processing/connected_components.h"},
            {"maximum_input_faces", kMaximumQueryFaces}})));
  result.push_back(query_definition(
      "mesh.components.component", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform", component_of_face,
      {"Polygon_mesh_processing"}, kEpickName,
      info("mesh.validate.components_component", {"face"}, {"source"},
           {{"source_header", "CGAL/Polygon_mesh_processing/connected_components.h"},
            {"maximum_input_faces", kMaximumQueryFaces}})));
  result.push_back(query_definition(
      "mesh.components.keep_largest", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform", keep_largest,
      {"Polygon_mesh_processing"}, kEpickName,
      info("mesh.validate.components_keep_largest", {"count"}, {"source"},
           {{"source_header", "CGAL/Polygon_mesh_processing/connected_components.h"},
            {"maximum_input_faces", kMaximumQueryFaces}})));
  result.push_back(query_definition(
      "mesh.location.locate", {"TriangleSurfaceMesh", "PointSet3"}, "GeometryQueryReport", "analysis", locate_points,
      {"Polygon_mesh_processing"}, kEpeckName,
      info("mesh.validate.location", {"strategy"}, {"mesh", "queries"},
           {{"source_header", "CGAL/Polygon_mesh_processing/locate.h"},
            {"maximum_input_faces", kMaximumQueryFaces}, {"maximum_queries", kMaximumQueries}})));
  result.push_back(query_definition(
      "mesh.slice.compute", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", slice_mesh,
      {"PMP_Boolean_operations"}, kEpeckName,
      info("mesh.validate.slice", {"normal", "offset"}, {"mesh"},
           {{"source_header", "CGAL/Polygon_mesh_slicer.h"}, {"maximum_input_faces", kMaximumQueryFaces}})));
  result.push_back(query_definition(
      "mesh.subdivide.catmull_clark", {"TriangleSurfaceMesh", "PolygonSoup3"}, "PolygonSoup3", "transform",
      catmull_clark, {"Subdivision_method_3"}, kEpickName,
      info("mesh.validate.catmull_clark", {"steps"}, {"source"},
           {{"source_header", "CGAL/Subdivision_method_3/subdivision_methods_3.h"},
            {"maximum_input_faces", kMaximumSubdivisionInputFaces},
            {"maximum_output_faces", kMaximumSubdivisionOutputFaces}})));
  result.push_back(query_definition(
      "mesh.subdivide.loop", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform", loop,
      {"Subdivision_method_3"}, kEpickName,
      info("mesh.validate.loop", {"steps"}, {"source"},
           {{"source_header", "CGAL/Subdivision_method_3/subdivision_methods_3.h"},
            {"maximum_input_faces", kMaximumSubdivisionInputFaces},
            {"maximum_output_faces", kMaximumSubdivisionOutputFaces}})));
  return result;
}

}  // namespace cgal_master::query_ops
