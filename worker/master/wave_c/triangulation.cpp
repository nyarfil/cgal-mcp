// Wave C triangulation adapters: 2D Delaunay, 2D constrained (Delaunay)
// triangulation and 3D Delaunay, each with an independent exact validator.
#include "wave_c_common.h"

#include "../geometry.h"

#include <CGAL/Constrained_Delaunay_triangulation_2.h>
#include <CGAL/Constrained_triangulation_2.h>
#include <CGAL/Constrained_triangulation_face_base_2.h>
#include <CGAL/Delaunay_triangulation_2.h>
#include <CGAL/Delaunay_triangulation_3.h>
#include <CGAL/Delaunay_triangulation_cell_base_3.h>
#include <CGAL/Polygon_mesh_processing/measure.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/Triangulation_data_structure_2.h>
#include <CGAL/Triangulation_data_structure_3.h>
#include <CGAL/Triangulation_vertex_base_with_info_2.h>
#include <CGAL/Triangulation_vertex_base_with_info_3.h>
#include <CGAL/convex_hull_3.h>

#include <algorithm>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace cgal_master::wave_c {
namespace {

using P2 = Epick::Point_2;
using P3 = Epick::Point_3;
using FT = Epeck::FT;

using Vb2 = CGAL::Triangulation_vertex_base_with_info_2<std::size_t, Epick>;
using DTds2 = CGAL::Triangulation_data_structure_2<Vb2, CGAL::Triangulation_face_base_2<Epick>>;
using DT2 = CGAL::Delaunay_triangulation_2<Epick, DTds2>;
using CFb2 = CGAL::Constrained_triangulation_face_base_2<Epick>;
using CTds2 = CGAL::Triangulation_data_structure_2<Vb2, CFb2>;
using Itag = CGAL::No_constraint_intersection_requiring_constructions_tag;
using CDT2 = CGAL::Constrained_Delaunay_triangulation_2<Epick, CTds2, Itag>;
using CT2 = CGAL::Constrained_triangulation_2<Epick, CTds2, Itag>;
using Vb3 = CGAL::Triangulation_vertex_base_with_info_3<std::size_t, Epick>;
using Tds3 =
    CGAL::Triangulation_data_structure_3<Vb3, CGAL::Delaunay_triangulation_cell_base_3<Epick>>;
using DT3 = CGAL::Delaunay_triangulation_3<Epick, Tds3>;

P2 p2(const XY& point) { return P2(point[0], point[1]); }
P3 p3(const XYZ& point) { return P3(point[0], point[1], point[2]); }

int turn(const XY& a, const XY& b, const XY& c) {
  return static_cast<int>(CGAL::orientation(p2(a), p2(b), p2(c)));
}

bool on_segment(const XY& a, const XY& b, const XY& p) {
  return turn(a, b, p) == 0 && std::min(a[0], b[0]) <= p[0] && p[0] <= std::max(a[0], b[0]) &&
         std::min(a[1], b[1]) <= p[1] && p[1] <= std::max(a[1], b[1]);
}

void require_budget(std::size_t first, std::size_t second, const char* what) {
  if (first != 0 && second > kMaximumBruteForcePairs / first) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED",
                      std::string(what) + " exceeds the mandatory validation budget");
  }
}

// Distinct points in first-occurrence order and the source -> unique map.
template <class Point>
std::pair<std::vector<Point>, std::vector<std::size_t>> deduplicate(
    const std::vector<Point>& points) {
  std::map<Point, std::size_t> index;
  std::vector<Point> unique;
  std::vector<std::size_t> mapping;
  mapping.reserve(points.size());
  for (const auto& point : points) {
    const auto inserted = index.emplace(point, unique.size());
    if (inserted.second) unique.push_back(point);
    mapping.push_back(inserted.first->second);
  }
  return {std::move(unique), std::move(mapping)};
}

void require_rank_2(const std::vector<XY>& unique) {
  if (unique.size() < 3) {
    throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_2",
                      "At least three distinct points are required");
  }
  for (std::size_t i = 2; i < unique.size(); ++i) {
    if (turn(unique[0], unique[1], unique[i]) != 0) return;
  }
  throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_2", "Points are collinear");
}

Index3 canonical_triangle(std::size_t a, std::size_t b, std::size_t c) {
  if (b < a && b < c) return {b, c, a};
  if (c < a && c < b) return {c, a, b};
  return {a, b, c};
}

Json triangulation2_json(const std::vector<XY>& vertices, std::vector<Index3> triangles,
                         std::vector<Index2> constrained) {
  std::sort(triangles.begin(), triangles.end());
  std::sort(constrained.begin(), constrained.end());
  Json vertex_array = Json::array();
  for (const auto& vertex : vertices) vertex_array.push_back(xy_json(vertex));
  Json triangle_array = Json::array();
  for (const auto& triangle : triangles) {
    triangle_array.push_back(Json::array({triangle[0], triangle[1], triangle[2]}));
  }
  Json edge_array = Json::array();
  for (const auto& edge : constrained) edge_array.push_back(Json::array({edge[0], edge[1]}));
  return Json{{"vertices", vertex_array},
              {"triangles", triangle_array},
              {"constrained_edges", edge_array}};
}

template <class Triangulation>
std::vector<Index3> finite_triangles(const Triangulation& triangulation) {
  std::vector<Index3> triangles;
  for (auto face = triangulation.finite_faces_begin(); face != triangulation.finite_faces_end();
       ++face) {
    triangles.push_back(canonical_triangle(face->vertex(0)->info(), face->vertex(1)->info(),
                                           face->vertex(2)->info()));
  }
  return triangles;
}

// ---------------------------------------------------------------------------
// triangulation.delaunay_2
// ---------------------------------------------------------------------------

Json run_delaunay_2(const Request& request) {
  require_input_count(request, 1, "triangulation.delaunay_2");
  require_parameters(request, {});
  const auto points = read_point_set2(request.inputs[0]);
  auto [unique, mapping] = deduplicate(points);
  require_rank_2(unique);
  std::vector<std::pair<P2, std::size_t>> input;
  for (std::size_t i = 0; i < unique.size(); ++i) input.emplace_back(p2(unique[i]), i);
  DT2 triangulation;
  triangulation.insert(input.begin(), input.end());
  if (triangulation.dimension() != 2 || triangulation.number_of_vertices() != unique.size() ||
      !triangulation.is_valid()) {
    throw WorkerError("INTERNAL", "INVALID_TRIANGULATION", "CGAL produced an invalid triangulation");
  }
  auto triangles = finite_triangles(triangulation);
  const auto triangle_count = triangles.size();
  auto output = write_json_output(request, "triangulation", "Triangulation2",
                                  request.inputs[0].unit,
                                  triangulation2_json(unique, std::move(triangles), {}));
  Json metrics = {{"input_point_count", points.size()},
                  {"vertex_count", unique.size()},
                  {"duplicate_points_merged", points.size() - unique.size()},
                  {"triangle_count", triangle_count},
                  {"algorithm", "CGAL::Delaunay_triangulation_2"},
                  {"effective_kernel", kEpick}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---------------------------------------------------------------------------
// triangulation.constrained_2
// ---------------------------------------------------------------------------

template <class Triangulation>
std::vector<Index2> constrained_edges(const Triangulation& triangulation) {
  std::vector<Index2> edges;
  for (auto edge = triangulation.finite_edges_begin(); edge != triangulation.finite_edges_end();
       ++edge) {
    if (!triangulation.is_constrained(*edge)) continue;
    const auto face = edge->first;
    const int i = edge->second;
    auto a = face->vertex(Triangulation::cw(i))->info();
    auto b = face->vertex(Triangulation::ccw(i))->info();
    if (b < a) std::swap(a, b);
    edges.push_back({a, b});
  }
  return edges;
}

template <class Triangulation>
std::pair<std::vector<Index3>, std::vector<Index2>> build_constrained(
    const std::vector<XY>& unique, const std::vector<Index2>& segments) {
  Triangulation triangulation;
  std::vector<typename Triangulation::Vertex_handle> handles;
  handles.reserve(unique.size());
  for (std::size_t i = 0; i < unique.size(); ++i) {
    auto handle = triangulation.insert(p2(unique[i]));
    handle->info() = i;
    handles.push_back(handle);
  }
  try {
    for (const auto& segment : segments) {
      triangulation.insert_constraint(handles[segment[0]], handles[segment[1]]);
    }
  } catch (const std::exception&) {
    throw WorkerError("PRECONDITION_FAILED", "CONSTRAINTS_INTERSECT",
                      "Constraint segments intersect in a way that needs new vertices");
  }
  if (triangulation.dimension() != 2 || triangulation.number_of_vertices() != unique.size() ||
      !triangulation.is_valid()) {
    throw WorkerError("INTERNAL", "INVALID_TRIANGULATION",
                      "CGAL produced an invalid constrained triangulation");
  }
  return {finite_triangles(triangulation), constrained_edges(triangulation)};
}

Json run_constrained_2(const Request& request) {
  require_input_count(request, 1, "triangulation.constrained_2");
  require_parameters(request, {"delaunay"});
  const bool delaunay = boolean_parameter(request, "delaunay");
  const auto graph = read_segment_graph2(request.inputs[0]);
  auto [unique, mapping] = deduplicate(graph.points);
  require_rank_2(unique);
  require_budget(graph.segments.size(), unique.size(), "Constraint coverage check");
  std::vector<Index2> segments;
  for (const auto& segment : graph.segments) {
    const auto a = mapping[segment[0]];
    const auto b = mapping[segment[1]];
    if (a == b) {
      throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_CONSTRAINT",
                        "A constraint segment has coincident endpoints");
    }
    segments.push_back({a, b});
  }
  // Proper interior crossings require constructed vertices; refuse them so the
  // output vertex set stays exactly the input point set.
  for (std::size_t i = 0; i < segments.size(); ++i) {
    for (std::size_t j = i + 1; j < segments.size(); ++j) {
      const auto& a = unique[segments[i][0]];
      const auto& b = unique[segments[i][1]];
      const auto& c = unique[segments[j][0]];
      const auto& d = unique[segments[j][1]];
      if (turn(a, b, c) * turn(a, b, d) < 0 && turn(c, d, a) * turn(c, d, b) < 0) {
        throw WorkerError("PRECONDITION_FAILED", "CONSTRAINTS_INTERSECT",
                          "Constraint segments " + std::to_string(i) + " and " +
                              std::to_string(j) + " cross in their interiors");
      }
    }
  }
  auto built = delaunay ? build_constrained<CDT2>(unique, segments)
                        : build_constrained<CT2>(unique, segments);
  const auto triangle_count = built.first.size();
  const auto constrained_count = built.second.size();
  auto output = write_json_output(
      request, "triangulation", "Triangulation2", request.inputs[0].unit,
      triangulation2_json(unique, std::move(built.first), std::move(built.second)));
  Json metrics = {{"input_point_count", graph.points.size()},
                  {"vertex_count", unique.size()},
                  {"input_segment_count", graph.segments.size()},
                  {"constrained_edge_count", constrained_count},
                  {"triangle_count", triangle_count},
                  {"delaunay", delaunay},
                  {"algorithm", delaunay ? "CGAL::Constrained_Delaunay_triangulation_2"
                                         : "CGAL::Constrained_triangulation_2"},
                  {"effective_kernel", kEpick}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---------------------------------------------------------------------------
// Independent 2D triangulation validator.
// ---------------------------------------------------------------------------

std::vector<XY> monotone_chain_hull(std::vector<XY> points) {
  std::sort(points.begin(), points.end());
  points.erase(std::unique(points.begin(), points.end()), points.end());
  std::vector<XY> hull(2 * points.size());
  std::size_t k = 0;
  for (std::size_t i = 0; i < points.size(); ++i) {
    while (k >= 2 && turn(hull[k - 2], hull[k - 1], points[i]) <= 0) --k;
    hull[k++] = points[i];
  }
  for (std::size_t i = points.size() - 1, t = k + 1; i > 0; --i) {
    while (k >= t && turn(hull[k - 2], hull[k - 1], points[i - 1]) <= 0) --k;
    hull[k++] = points[i - 1];
  }
  hull.resize(k - 1);
  return hull;
}

FT twice_area(const XY& a, const XY& b, const XY& c) {
  return (FT(b[0]) - FT(a[0])) * (FT(c[1]) - FT(a[1])) -
         (FT(b[1]) - FT(a[1])) * (FT(c[0]) - FT(a[0]));
}

struct Validation2 {
  std::size_t vertex_count = 0;
  std::size_t triangle_count = 0;
  std::size_t boundary_vertex_count = 0;
  std::size_t interior_edge_count = 0;
  std::size_t constrained_edge_count = 0;
  std::size_t locally_delaunay_edges = 0;
  std::string area_exact;
};

Validation2 validate_triangulation_2(const Triangulation2Data& candidate,
                                     const std::vector<XY>& source_points,
                                     const std::vector<Index2>* source_segments,
                                     bool require_delaunay) {
  Validation2 result;
  const auto& vertices = candidate.vertices;
  const std::size_t n = vertices.size();
  std::set<XY> vertex_set(vertices.begin(), vertices.end());
  if (vertex_set.size() != n) fail_validation("REPEATED_VERTEX", "Triangulation repeats a vertex");
  std::set<XY> source_set(source_points.begin(), source_points.end());
  if (vertex_set != source_set) {
    fail_validation("VERTEX_SET_MISMATCH", "Triangulation vertices differ from the source points");
  }
  // Directed edges -> opposite vertex.
  std::map<std::pair<std::size_t, std::size_t>, std::size_t> directed;
  std::vector<bool> used(n, false);
  FT total(0);
  for (const auto& t : candidate.triangles) {
    if (t[0] == t[1] || t[1] == t[2] || t[0] == t[2]) {
      fail_validation("DEGENERATE_TRIANGLE", "Triangle repeats a vertex index");
    }
    if (turn(vertices[t[0]], vertices[t[1]], vertices[t[2]]) <= 0) {
      fail_validation("TRIANGLE_NOT_CCW", "Triangle is not strictly counterclockwise");
    }
    for (int k = 0; k < 3; ++k) {
      used[t[k]] = true;
      if (!directed.emplace(std::make_pair(t[k], t[(k + 1) % 3]), t[(k + 2) % 3]).second) {
        fail_validation("NON_MANIFOLD_EDGE", "A directed edge is used by two triangles");
      }
    }
    total += twice_area(vertices[t[0]], vertices[t[1]], vertices[t[2]]);
    CGAL::exact(total);  // collapse the lazy DAG: a deep sum chain overflows the stack
  }
  for (std::size_t i = 0; i < n; ++i) {
    if (!used[i]) fail_validation("UNUSED_VERTEX", "A source point is not a triangle vertex");
  }
  std::vector<std::pair<std::size_t, std::size_t>> boundary;
  std::set<std::size_t> boundary_vertices;
  for (const auto& [edge, opposite] : directed) {
    if (directed.find({edge.second, edge.first}) == directed.end()) {
      boundary.push_back(edge);
      boundary_vertices.insert(edge.first);
      boundary_vertices.insert(edge.second);
    } else if (edge.first < edge.second) {
      ++result.interior_edge_count;
    }
  }
  require_budget(boundary.size(), n, "Boundary supporting-line check");
  for (const auto& edge : boundary) {
    for (const auto& vertex : vertices) {
      if (turn(vertices[edge.first], vertices[edge.second], vertex) < 0) {
        fail_validation("BOUNDARY_NOT_CONVEX_HULL", "A boundary edge is not a convex-hull edge");
      }
    }
  }
  const auto hull = monotone_chain_hull(vertices);
  FT hull_twice(0);
  for (std::size_t i = 1; i + 1 < hull.size(); ++i) hull_twice += twice_area(hull[0], hull[i], hull[i + 1]);
  if (total != hull_twice) {
    fail_validation("AREA_COVERAGE_MISMATCH",
                    "Triangle areas do not sum exactly to the convex-hull area");
  }
  const std::size_t b = boundary_vertices.size();
  if (candidate.triangles.size() + b + 2 != 2 * n) {
    fail_validation("EULER_COUNT_MISMATCH", "Triangle count violates T = 2n - b - 2");
  }
  // Constraints.
  std::set<std::pair<std::size_t, std::size_t>> constrained;
  for (const auto& edge : candidate.constrained_edges) {
    const auto key = std::minmax(edge[0], edge[1]);
    if (edge[0] == edge[1] || !constrained.insert(key).second) {
      fail_validation("INVALID_CONSTRAINED_EDGE", "Constrained edge list is invalid");
    }
    if (directed.find({edge[0], edge[1]}) == directed.end() &&
        directed.find({edge[1], edge[0]}) == directed.end()) {
      fail_validation("CONSTRAINED_EDGE_MISSING", "A constrained edge is not a triangulation edge");
    }
  }
  if (source_segments == nullptr) {
    if (!constrained.empty()) {
      fail_validation("UNEXPECTED_CONSTRAINTS", "Unconstrained Delaunay output marks constraints");
    }
  } else {
    std::map<XY, std::size_t> position;
    for (std::size_t i = 0; i < n; ++i) position[vertices[i]] = i;
    require_budget(source_segments->size(), n, "Constraint coverage check");
    std::set<std::pair<std::size_t, std::size_t>> covered;
    for (const auto& segment : *source_segments) {
      const XY& a = source_points[segment[0]];
      const XY& b2 = source_points[segment[1]];
      std::vector<XY> on;
      for (const auto& vertex : vertices) {
        if (on_segment(a, b2, vertex)) on.push_back(vertex);
      }
      std::sort(on.begin(), on.end());
      for (std::size_t i = 0; i + 1 < on.size(); ++i) {
        const auto key = std::minmax(position[on[i]], position[on[i + 1]]);
        if (constrained.find(key) == constrained.end()) {
          fail_validation("CONSTRAINT_NOT_PRESERVED",
                          "An input constraint is not a chain of constrained edges");
        }
        covered.insert(key);
      }
    }
    if (covered != constrained) {
      fail_validation("SPURIOUS_CONSTRAINT", "A constrained edge lies on no input segment");
    }
  }
  result.constrained_edge_count = constrained.size();
  if (require_delaunay) {
    for (const auto& [edge, opposite] : directed) {
      if (edge.first > edge.second) continue;
      const auto twin = directed.find({edge.second, edge.first});
      if (twin == directed.end()) continue;
      if (constrained.count(std::minmax(edge.first, edge.second)) != 0) continue;
      const auto side = CGAL::side_of_bounded_circle(
          p2(vertices[edge.first]), p2(vertices[edge.second]), p2(vertices[opposite]),
          p2(vertices[twin->second]));
      if (side == CGAL::ON_BOUNDED_SIDE) {
        fail_validation("NOT_LOCALLY_DELAUNAY",
                        "An unconstrained interior edge violates the empty-circle property");
      }
      ++result.locally_delaunay_edges;
    }
  }
  result.vertex_count = n;
  result.triangle_count = candidate.triangles.size();
  result.boundary_vertex_count = b;
  result.area_exact = exact_string(total / FT(2));
  return result;
}

Json validation2_report(const Validation2& value, bool delaunay, bool constrained,
                        const std::string& unit) {
  Json checks = {{"vertex_set_matches_source", true},
                 {"triangles_counterclockwise", true},
                 {"edge_manifold", true},
                 {"boundary_is_convex_hull", true},
                 {"area_covers_convex_hull", true},
                 {"euler_count", true}};
  if (constrained) checks["constraints_preserved"] = true;
  if (delaunay) checks[constrained ? "constrained_delaunay" : "delaunay"] = true;
  return Json{{"checks", checks},
              {"vertex_count", value.vertex_count},
              {"triangle_count", value.triangle_count},
              {"boundary_vertex_count", value.boundary_vertex_count},
              {"interior_edge_count", value.interior_edge_count},
              {"constrained_edge_count", value.constrained_edge_count},
              {"locally_delaunay_edge_count", value.locally_delaunay_edges},
              {"area", {{"exact", value.area_exact}, {"unit", unit + "^2"}}},
              {"independence",
               "exact orientation/in-circle predicates, monotone-chain hull and edge maps; "
               "CGAL triangulation classes are not used"}};
}

Json run_delaunay_2_validator(const Request& request) {
  require_input_count(request, 2, "triangulation.validate.delaunay_2");
  require_parameters(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto candidate = read_triangulation2(request.inputs[0]);
  const auto source = read_point_set2(request.inputs[1]);
  const auto value = validate_triangulation_2(candidate, source, nullptr, true);
  return finish_validation(request, "triangulation.validate.delaunay_2",
                           validation2_report(value, true, false, request.inputs[0].unit));
}

Json run_constrained_2_validator(const Request& request) {
  require_input_count(request, 2, "triangulation.validate.constrained_2");
  require_parameters(request, {"delaunay"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const bool delaunay = boolean_parameter(request, "delaunay");
  const auto candidate = read_triangulation2(request.inputs[0]);
  const auto graph = read_segment_graph2(request.inputs[1]);
  const auto value = validate_triangulation_2(candidate, graph.points, &graph.segments, delaunay);
  auto report = validation2_report(value, delaunay, true, request.inputs[0].unit);
  report["delaunay"] = delaunay;
  return finish_validation(request, "triangulation.validate.constrained_2", std::move(report));
}

// ---------------------------------------------------------------------------
// triangulation.delaunay_3
// ---------------------------------------------------------------------------

Index4 canonical_tetrahedron(Index4 t) {
  // Even permutations only (orientation preserving).
  const auto smallest = std::min_element(t.begin(), t.end()) - t.begin();
  if (smallest == 1) t = {t[1], t[0], t[3], t[2]};
  if (smallest == 2) t = {t[2], t[3], t[0], t[1]};
  if (smallest == 3) t = {t[3], t[2], t[1], t[0]};
  // Rotate the last three (a 3-cycle is even) so the second entry is smallest.
  while (!(t[1] < t[2] && t[1] < t[3])) t = {t[0], t[2], t[3], t[1]};
  return t;
}

Json run_delaunay_3(const Request& request) {
  require_input_count(request, 1, "triangulation.delaunay_3");
  require_parameters(request, {});
  const auto points = read_point_set3(request.inputs[0]);
  auto [unique, mapping] = deduplicate(points);
  if (unique.size() > kMaximumPlanarPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED",
                      "Delaunay 3D input exceeds the Wave C size limit");
  }
  std::vector<std::pair<P3, std::size_t>> input;
  for (std::size_t i = 0; i < unique.size(); ++i) input.emplace_back(p3(unique[i]), i);
  DT3 triangulation;
  triangulation.insert(input.begin(), input.end());
  if (triangulation.dimension() != 3) {
    throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_3",
                      "3D Delaunay triangulation requires affinely independent points");
  }
  if (triangulation.number_of_vertices() != unique.size() || !triangulation.is_valid()) {
    throw WorkerError("INTERNAL", "INVALID_TRIANGULATION", "CGAL produced an invalid triangulation");
  }
  std::vector<Index4> tetrahedra;
  for (auto cell = triangulation.finite_cells_begin(); cell != triangulation.finite_cells_end();
       ++cell) {
    tetrahedra.push_back(canonical_tetrahedron({cell->vertex(0)->info(), cell->vertex(1)->info(),
                                                cell->vertex(2)->info(), cell->vertex(3)->info()}));
  }
  std::sort(tetrahedra.begin(), tetrahedra.end());
  Json vertex_array = Json::array();
  for (const auto& vertex : unique) vertex_array.push_back(xyz_json(vertex));
  Json cell_array = Json::array();
  for (const auto& t : tetrahedra) cell_array.push_back(Json::array({t[0], t[1], t[2], t[3]}));
  auto output = write_json_output(request, "triangulation", "Triangulation3",
                                  request.inputs[0].unit,
                                  Json{{"vertices", vertex_array}, {"tetrahedra", cell_array}});
  Json metrics = {{"input_point_count", points.size()},
                  {"vertex_count", unique.size()},
                  {"duplicate_points_merged", points.size() - unique.size()},
                  {"tetrahedron_count", tetrahedra.size()},
                  {"algorithm", "CGAL::Delaunay_triangulation_3"},
                  {"effective_kernel", kEpick}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

FT six_volume(const XYZ& a, const XYZ& b, const XYZ& c, const XYZ& d) {
  const FT bx = FT(b[0]) - FT(a[0]), by = FT(b[1]) - FT(a[1]), bz = FT(b[2]) - FT(a[2]);
  const FT cx = FT(c[0]) - FT(a[0]), cy = FT(c[1]) - FT(a[1]), cz = FT(c[2]) - FT(a[2]);
  const FT dx = FT(d[0]) - FT(a[0]), dy = FT(d[1]) - FT(a[1]), dz = FT(d[2]) - FT(a[2]);
  return bx * (cy * dz - cz * dy) - by * (cx * dz - cz * dx) + bz * (cx * dy - cy * dx);
}

Json run_delaunay_3_validator(const Request& request) {
  require_input_count(request, 2, "triangulation.validate.delaunay_3");
  require_parameters(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto candidate = read_triangulation3(request.inputs[0]);
  const auto source = read_point_set3(request.inputs[1]);
  const auto& vertices = candidate.vertices;
  const std::size_t n = vertices.size();
  std::set<XYZ> vertex_set(vertices.begin(), vertices.end());
  if (vertex_set.size() != n) fail_validation("REPEATED_VERTEX", "Triangulation repeats a vertex");
  if (vertex_set != std::set<XYZ>(source.begin(), source.end())) {
    fail_validation("VERTEX_SET_MISMATCH", "Triangulation vertices differ from the source points");
  }
  // Facet (sorted triple) -> list of (tetrahedron, opposite vertex).
  std::map<Index3, std::vector<std::pair<std::size_t, std::size_t>>> facets;
  std::vector<bool> used(n, false);
  FT total(0);
  for (std::size_t c = 0; c < candidate.tetrahedra.size(); ++c) {
    const auto& t = candidate.tetrahedra[c];
    if (std::set<std::size_t>(t.begin(), t.end()).size() != 4) {
      fail_validation("DEGENERATE_TETRAHEDRON", "Tetrahedron repeats a vertex index");
    }
    if (CGAL::orientation(p3(vertices[t[0]]), p3(vertices[t[1]]), p3(vertices[t[2]]),
                          p3(vertices[t[3]])) != CGAL::POSITIVE) {
      fail_validation("TETRAHEDRON_NOT_POSITIVE", "Tetrahedron is not positively oriented");
    }
    total += six_volume(vertices[t[0]], vertices[t[1]], vertices[t[2]], vertices[t[3]]);
    CGAL::exact(total);  // collapse the lazy DAG: a deep sum chain overflows the stack
    for (int k = 0; k < 4; ++k) {
      used[t[k]] = true;
      Index3 facet{t[(k + 1) % 4], t[(k + 2) % 4], t[(k + 3) % 4]};
      std::sort(facet.begin(), facet.end());
      facets[facet].push_back({c, t[k]});
    }
  }
  for (std::size_t i = 0; i < n; ++i) {
    if (!used[i]) fail_validation("UNUSED_VERTEX", "A source point is not a tetrahedron vertex");
  }
  std::size_t boundary_facets = 0, interior_facets = 0, delaunay_facets = 0;
  std::vector<std::pair<Index3, std::size_t>> boundary;
  for (const auto& [facet, incident] : facets) {
    const P3 a = p3(vertices[facet[0]]), b = p3(vertices[facet[1]]), c = p3(vertices[facet[2]]);
    if (incident.size() > 2) fail_validation("NON_MANIFOLD_FACET", "A facet has three cells");
    if (incident.size() == 1) {
      ++boundary_facets;
      boundary.push_back({facet, incident[0].second});
      continue;
    }
    ++interior_facets;
    const auto first = CGAL::orientation(a, b, c, p3(vertices[incident[0].second]));
    const auto second = CGAL::orientation(a, b, c, p3(vertices[incident[1].second]));
    if (first == CGAL::COPLANAR || second == CGAL::COPLANAR || first == second) {
      fail_validation("OVERLAPPING_CELLS", "Cells sharing a facet are not on opposite sides");
    }
    const auto& t = candidate.tetrahedra[incident[0].first];
    const auto side = CGAL::side_of_bounded_sphere(p3(vertices[t[0]]), p3(vertices[t[1]]),
                                                   p3(vertices[t[2]]), p3(vertices[t[3]]),
                                                   p3(vertices[incident[1].second]));
    if (side == CGAL::ON_BOUNDED_SIDE) {
      fail_validation("NOT_LOCALLY_DELAUNAY", "An interior facet violates the empty-sphere property");
    }
    ++delaunay_facets;
  }
  require_budget(boundary.size(), n, "Boundary supporting-plane check");
  for (const auto& [facet, opposite] : boundary) {
    const P3 a = p3(vertices[facet[0]]), b = p3(vertices[facet[1]]), c = p3(vertices[facet[2]]);
    const auto inner = CGAL::orientation(a, b, c, p3(vertices[opposite]));
    for (const auto& vertex : vertices) {
      const auto side = CGAL::orientation(a, b, c, p3(vertex));
      if (side != CGAL::COPLANAR && side != inner) {
        fail_validation("BOUNDARY_NOT_CONVEX_HULL", "A boundary facet is not a convex-hull facet");
      }
    }
  }
  // Volume coverage against an independent package (Convex_hull_3).
  std::vector<Point> exact_points;
  for (const auto& vertex : vertices) exact_points.emplace_back(vertex[0], vertex[1], vertex[2]);
  Mesh hull;
  CGAL::convex_hull_3(exact_points.begin(), exact_points.end(), hull);
  const auto hull_volume = CGAL::Polygon_mesh_processing::volume(hull);
  if (total / FT(6) != hull_volume) {
    fail_validation("VOLUME_COVERAGE_MISMATCH",
                    "Tetrahedra volumes do not sum exactly to the convex-hull volume");
  }
  Json report = {{"checks",
                  {{"vertex_set_matches_source", true},
                   {"tetrahedra_positive", true},
                   {"facet_manifold", true},
                   {"boundary_is_convex_hull", true},
                   {"volume_covers_convex_hull", true},
                   {"delaunay", true}}},
                 {"vertex_count", n},
                 {"tetrahedron_count", candidate.tetrahedra.size()},
                 {"boundary_facet_count", boundary_facets},
                 {"interior_facet_count", interior_facets},
                 {"locally_delaunay_facet_count", delaunay_facets},
                 {"volume", {{"exact", exact_string(total / FT(6))},
                             {"unit", request.inputs[0].unit + "^3"}}},
                 {"independence",
                  "exact orientation/in-sphere predicates, facet maps and a Convex_hull_3 volume; "
                  "CGAL Triangulation_3 classes are not used"}};
  return finish_validation(request, "triangulation.validate.delaunay_3", std::move(report));
}

}  // namespace

std::vector<OperationDefinition> triangulation_operations() {
  std::vector<OperationDefinition> result;
  result.push_back(make_definition(
      "triangulation.delaunay_2", {"PointSet2"}, "Triangulation2", "transform", run_delaunay_2,
      {"Triangulation_2"},
      {{"source_header", "CGAL/Delaunay_triangulation_2.h"},
       {"input_format", "json"},
       {"output_format", "json"},
       {"validators", {"triangulation.validate.delaunay_2"}},
       {"maximum_points", kMaximumPlanarPoints}}));
  result.push_back(make_definition(
      "triangulation.validate.delaunay_2", {"Triangulation2", "PointSet2"}, "ValidationReport",
      "validator", run_delaunay_2_validator, {"Triangulation_2"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"checks",
        {"vertex_set_matches_source", "triangles_counterclockwise", "edge_manifold",
         "boundary_is_convex_hull", "area_covers_convex_hull", "euler_count", "delaunay"}}}));
  result.push_back(make_definition(
      "triangulation.constrained_2", {"SegmentGraph2"}, "Triangulation2", "transform",
      run_constrained_2, {"Triangulation_2"},
      {{"source_header", "CGAL/Constrained_Delaunay_triangulation_2.h"},
       {"input_format", "json"},
       {"output_format", "json"},
       {"required_parameters", {"delaunay"}},
       {"intersection_tag", "CGAL::No_constraint_intersection_requiring_constructions_tag"},
       {"validators", {"triangulation.validate.constrained_2"}},
       {"validator_parameter_bindings",
        {{"triangulation.validate.constrained_2", {{"delaunay", "delaunay"}}}}},
       {"maximum_segments", kMaximumConstraintSegments}}));
  result.push_back(make_definition(
      "triangulation.validate.constrained_2", {"Triangulation2", "SegmentGraph2"},
      "ValidationReport", "validator", run_constrained_2_validator, {"Triangulation_2"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"bound_parameters", {"delaunay"}},
       {"checks",
        {"vertex_set_matches_source", "triangles_counterclockwise", "edge_manifold",
         "boundary_is_convex_hull", "area_covers_convex_hull", "euler_count",
         "constraints_preserved", "constrained_delaunay"}}}));
  result.push_back(make_definition(
      "triangulation.delaunay_3", {"PointSet3"}, "Triangulation3", "transform", run_delaunay_3,
      {"Triangulation_3"},
      {{"source_header", "CGAL/Delaunay_triangulation_3.h"},
       {"input_format", "xyz"},
       {"output_format", "json"},
       {"validators", {"triangulation.validate.delaunay_3"}},
       {"maximum_points", kMaximumPlanarPoints}}));
  result.push_back(make_definition(
      "triangulation.validate.delaunay_3", {"Triangulation3", "PointSet3"}, "ValidationReport",
      "validator", run_delaunay_3_validator, {"Triangulation_3", "Convex_hull_3"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"checks",
        {"vertex_set_matches_source", "tetrahedra_positive", "facet_manifold",
         "boundary_is_convex_hull", "volume_covers_convex_hull", "delaunay"}}}));
  return result;
}

}  // namespace cgal_master::wave_c
