// Wave E (family 7.14) Mesh_2: refine_Delaunay_mesh_2 over a strictly checked
// polygon-with-holes domain, and an independent exact validator that recomputes
// constraint preservation, domain coverage, shape/size criteria and the
// constrained Delaunay property from the raw domain without calling Mesh_2.
#include "wave_e_operations.h"

#include "../wave_c/wave_c_common.h"

#include <CGAL/Constrained_Delaunay_triangulation_2.h>
#include <CGAL/Delaunay_mesh_face_base_2.h>
#include <CGAL/Delaunay_mesh_size_criteria_2.h>
#include <CGAL/Delaunay_mesher_2.h>
#include <CGAL/Polygon_2_algorithms.h>
#include <CGAL/Triangulation_data_structure_2.h>
#include <CGAL/Triangulation_vertex_base_2.h>
#include <CGAL/enum.h>

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace cgal_master::wave_e {
namespace {

using namespace cgal_master::wave_c;

using P2 = Epick::Point_2;
using S2 = Epick::Segment_2;
using FT = Epeck::FT;

using Vb = CGAL::Triangulation_vertex_base_2<Epick>;
using Fb = CGAL::Delaunay_mesh_face_base_2<Epick>;
using Tds = CGAL::Triangulation_data_structure_2<Vb, Fb>;
using CDT = CGAL::Constrained_Delaunay_triangulation_2<Epick, Tds>;
using Criteria = CGAL::Delaunay_mesh_size_criteria_2<CDT>;

// Producers refuse domains / outputs whose mandatory validation would exceed
// the validator budget, so no candidate is produced that cannot be validated.
constexpr std::size_t kMaximumDomainVertices = 1000;
constexpr std::size_t kMaximumMeshTriangles = 30000;
constexpr std::size_t kValidatorTriangleLimit = 60000;
constexpr double kMaximumAspectBound = 0.125;  // Mesh_2 termination guarantee (about 20.7 degrees)
constexpr double kGeometryTolerance = 1e-9;    // relative to the domain bbox diagonal

P2 p2(const XY& point) { return P2(point[0], point[1]); }

int turn(const XY& a, const XY& b, const XY& c) {
  return static_cast<int>(CGAL::orientation(p2(a), p2(b), p2(c)));
}

FT twice_area(const XY& a, const XY& b, const XY& c) {
  return (FT(b[0]) - FT(a[0])) * (FT(c[1]) - FT(a[1])) -
         (FT(b[1]) - FT(a[1])) * (FT(c[0]) - FT(a[0]));
}

FT sq_length(const XY& a, const XY& b) {
  const FT dx = FT(b[0]) - FT(a[0]);
  const FT dy = FT(b[1]) - FT(a[1]);
  return dx * dx + dy * dy;
}

struct Defect {
  std::string code;
  std::string message;
};

std::vector<const std::vector<XY>*> rings_of(const PolygonWithHolesData& domain) {
  std::vector<const std::vector<XY>*> rings{&domain.outer};
  for (const auto& hole : domain.holes) rings.push_back(&hole);
  return rings;
}

bool strictly_inside(const std::vector<XY>& ring, const XY& point) {
  std::vector<P2> points;
  points.reserve(ring.size());
  for (const auto& vertex : ring) points.push_back(p2(vertex));
  return CGAL::bounded_side_2(points.begin(), points.end(), p2(point), Epick()) ==
         CGAL::ON_BOUNDED_SIDE;
}

// Exact structural check: pairwise distinct vertices, simple non-degenerate
// rings, rings pairwise disjoint, every hole strictly inside the outer ring and
// outside every other hole.
std::optional<Defect> domain_defect(const PolygonWithHolesData& domain) {
  const auto rings = rings_of(domain);
  std::size_t total = 0;
  std::set<XY> seen;
  for (const auto* ring : rings) {
    total += ring->size();
    for (const auto& vertex : *ring) {
      if (!seen.insert(vertex).second) {
        return Defect{"REPEATED_DOMAIN_VERTEX", "A domain vertex is repeated"};
      }
    }
  }
  if (total > kMaximumDomainVertices) {
    return Defect{"DOMAIN_VERTEX_LIMIT", "Domain exceeds the Mesh_2 vertex limit"};
  }
  struct Edge {
    XY a, b;
    std::size_t ring, index, size;
  };
  std::vector<Edge> edges;
  for (std::size_t r = 0; r < rings.size(); ++r) {
    const auto& ring = *rings[r];
    for (std::size_t i = 0; i < ring.size(); ++i) {
      edges.push_back({ring[i], ring[(i + 1) % ring.size()], r, i, ring.size()});
    }
  }
  for (std::size_t i = 0; i < edges.size(); ++i) {
    for (std::size_t j = i + 1; j < edges.size(); ++j) {
      const auto& e = edges[i];
      const auto& f = edges[j];
      const bool same_ring = e.ring == f.ring;
      const bool next = same_ring && f.index == (e.index + 1) % e.size;
      const bool previous = same_ring && e.index == (f.index + 1) % f.size;
      if (next || previous) {
        // Adjacent edges share exactly one endpoint; they must not fold back.
        const XY& shared = next ? e.b : e.a;
        const XY& far_e = next ? e.a : e.b;
        const XY& far_f = next ? f.b : f.a;
        if (turn(far_e, shared, far_f) == 0 &&
            !CGAL::collinear_are_ordered_along_line(p2(far_e), p2(shared), p2(far_f))) {
          return Defect{"SELF_INTERSECTING_DOMAIN", "Adjacent domain edges overlap"};
        }
        continue;
      }
      if (CGAL::do_intersect(S2(p2(e.a), p2(e.b)), S2(p2(f.a), p2(f.b)))) {
        return Defect{"SELF_INTERSECTING_DOMAIN",
                      same_ring ? "A domain ring intersects itself"
                                : "Two domain rings intersect or touch"};
      }
    }
  }
  // Rings are simple here, so a zero signed area means all vertices are collinear.
  for (const auto* ring : rings) {
    FT twice(0);
    for (std::size_t i = 1; i + 1 < ring->size(); ++i) twice += twice_area((*ring)[0], (*ring)[i], (*ring)[i + 1]);
    if (twice == FT(0)) return Defect{"DEGENERATE_RING", "A domain ring has zero area"};
  }
  for (std::size_t h = 1; h < rings.size(); ++h) {
    if (!strictly_inside(domain.outer, (*rings[h])[0])) {
      return Defect{"HOLE_OUTSIDE_DOMAIN", "A hole is not strictly inside the outer ring"};
    }
    for (std::size_t k = 1; k < rings.size(); ++k) {
      if (k != h && strictly_inside(*rings[k], (*rings[h])[0])) {
        return Defect{"NESTED_HOLE", "A hole lies inside another hole"};
      }
    }
  }
  return std::nullopt;
}

FT domain_twice_area(const PolygonWithHolesData& domain) {
  const auto rings = rings_of(domain);
  FT result(0);
  for (std::size_t r = 0; r < rings.size(); ++r) {
    const auto& ring = *rings[r];
    FT twice(0);
    for (std::size_t i = 1; i + 1 < ring.size(); ++i) twice += twice_area(ring[0], ring[i], ring[i + 1]);
    if (twice < FT(0)) twice = -twice;
    if (r == 0) result += twice; else result -= twice;
  }
  return result;
}

double bbox_diagonal(const PolygonWithHolesData& domain) {
  double lo_x = std::numeric_limits<double>::infinity(), lo_y = lo_x;
  double hi_x = -lo_x, hi_y = -lo_x;
  for (const auto& vertex : domain.outer) {
    lo_x = std::min(lo_x, vertex[0]); hi_x = std::max(hi_x, vertex[0]);
    lo_y = std::min(lo_y, vertex[1]); hi_y = std::max(hi_y, vertex[1]);
  }
  return std::hypot(hi_x - lo_x, hi_y - lo_y);
}

double point_segment_distance(const XY& p, const XY& a, const XY& b) {
  const double dx = b[0] - a[0], dy = b[1] - a[1];
  const double length2 = dx * dx + dy * dy;
  double t = length2 > 0 ? ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2 : 0.0;
  t = std::clamp(t, 0.0, 1.0);
  return std::hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

double number_parameter(const Request& request, const char* name, double exclusive_minimum,
                        double maximum) {
  const auto& value = request.parameters.at(name);
  if (!value.is_number() || value.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be a number");
  }
  const double result = value.get<double>();
  if (!std::isfinite(result) || !(result > exclusive_minimum) || result > maximum) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " is outside its supported range");
  }
  return result;
}

double positive_length(const Request& request, const char* name, const std::string& unit) {
  const double value = typed_length_parameter(request, name, unit);
  if (!(value > 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be positive");
  }
  return value;
}

// ---------------------------------------------------------------------------
// mesh2.refine.delaunay
// ---------------------------------------------------------------------------

// A point strictly inside a simple ring: the centroid of a triangle of the
// ring's own constrained triangulation that lies in the ring (checked exactly).
P2 interior_point(const std::vector<XY>& ring) {
  CDT local;
  std::vector<P2> points;
  for (const auto& vertex : ring) points.push_back(p2(vertex));
  local.insert_constraint(points.begin(), points.end(), true);
  for (auto face = local.finite_faces_begin(); face != local.finite_faces_end(); ++face) {
    const XY centroid{(face->vertex(0)->point().x() + face->vertex(1)->point().x() +
                       face->vertex(2)->point().x()) / 3.0,
                      (face->vertex(0)->point().y() + face->vertex(1)->point().y() +
                       face->vertex(2)->point().y()) / 3.0};
    if (strictly_inside(ring, centroid)) return p2(centroid);
  }
  throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_DOMAIN", "A hole has no interior point");
}

Index3 canonical_triangle(std::size_t a, std::size_t b, std::size_t c) {
  if (b < a && b < c) return {b, c, a};
  if (c < a && c < b) return {c, a, b};
  return {a, b, c};
}

Json run_refine(const Request& request) {
  require_input_count(request, 1, "mesh2.refine.delaunay");
  require_parameters(request, {"aspect_bound", "size_bound"});
  const auto& source = request.inputs[0];
  const double aspect_bound = number_parameter(request, "aspect_bound", 0.0, kMaximumAspectBound);
  const double size_bound = positive_length(request, "size_bound", source.unit);
  const auto domain = read_polygon_with_holes2(source);
  if (const auto defect = domain_defect(domain)) {
    throw WorkerError("PRECONDITION_FAILED", defect->code, defect->message);
  }
  // Bound the work: estimate the triangle count from the size criterion and the
  // smallest local feature (vertex pairs, vertex-to-edge distances).
  const auto rings = rings_of(domain);
  std::vector<std::pair<XY, XY>> segments;
  std::vector<XY> vertices;
  for (const auto* ring : rings) {
    for (std::size_t i = 0; i < ring->size(); ++i) {
      segments.push_back({(*ring)[i], (*ring)[(i + 1) % ring->size()]});
      vertices.push_back((*ring)[i]);
    }
  }
  double feature = std::numeric_limits<double>::infinity();
  for (std::size_t i = 0; i < vertices.size(); ++i) {
    for (std::size_t j = i + 1; j < vertices.size(); ++j) {
      feature = std::min(feature, std::hypot(vertices[i][0] - vertices[j][0],
                                             vertices[i][1] - vertices[j][1]));
    }
    for (const auto& segment : segments) {
      if (segment.first == vertices[i] || segment.second == vertices[i]) continue;
      feature = std::min(feature, point_segment_distance(vertices[i], segment.first, segment.second));
    }
  }
  const double area = CGAL::to_double(domain_twice_area(domain)) / 2.0;
  const double length = std::min(size_bound, feature);
  if (!(2.0 * area / (0.4330127 * length * length) <= static_cast<double>(kMaximumMeshTriangles))) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "size_bound is too small relative to the domain for bounded validation");
  }
  CDT cdt;
  for (const auto* ring : rings) {
    std::vector<P2> points;
    for (const auto& vertex : *ring) points.push_back(p2(vertex));
    cdt.insert_constraint(points.begin(), points.end(), true);
  }
  if (cdt.dimension() != 2) {
    throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_DOMAIN", "Domain triangulation is not 2D");
  }
  const std::size_t input_vertices = vertices.size();
  // Without seeds every bounded component would be meshed, holes included.
  // One strictly interior point per hole marks that component as not in domain.
  std::vector<P2> hole_seeds;
  for (const auto& hole : domain.holes) hole_seeds.push_back(interior_point(hole));
  CGAL::refine_Delaunay_mesh_2(cdt, hole_seeds.begin(), hole_seeds.end(),
                               Criteria(aspect_bound, size_bound), false);
  if (!cdt.is_valid()) {
    throw WorkerError("INTERNAL", "INVALID_TRIANGULATION", "CGAL produced an invalid triangulation");
  }
  std::set<XY> used;
  for (auto face = cdt.finite_faces_begin(); face != cdt.finite_faces_end(); ++face) {
    if (!face->is_in_domain()) continue;
    for (int k = 0; k < 3; ++k) used.insert({face->vertex(k)->point().x(), face->vertex(k)->point().y()});
  }
  std::vector<XY> output_vertices(used.begin(), used.end());
  std::map<XY, std::size_t> index;
  for (std::size_t i = 0; i < output_vertices.size(); ++i) index[output_vertices[i]] = i;
  std::vector<Index3> triangles;
  for (auto face = cdt.finite_faces_begin(); face != cdt.finite_faces_end(); ++face) {
    if (!face->is_in_domain()) continue;
    auto at = [&](int k) {
      return index.at({face->vertex(k)->point().x(), face->vertex(k)->point().y()});
    };
    triangles.push_back(canonical_triangle(at(0), at(1), at(2)));
  }
  if (triangles.size() > kMaximumMeshTriangles) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "Mesh_2 output exceeds the bounded validation budget");
  }
  std::vector<Index2> constrained;
  for (auto edge = cdt.finite_edges_begin(); edge != cdt.finite_edges_end(); ++edge) {
    if (!cdt.is_constrained(*edge)) continue;
    const auto face = edge->first;
    const int i = edge->second;
    if (!face->is_in_domain() && !face->neighbor(i)->is_in_domain()) continue;
    const auto& a = face->vertex(cdt.cw(i))->point();
    const auto& b = face->vertex(cdt.ccw(i))->point();
    auto ia = index.at({a.x(), a.y()});
    auto ib = index.at({b.x(), b.y()});
    if (ib < ia) std::swap(ia, ib);
    constrained.push_back({ia, ib});
  }
  std::sort(triangles.begin(), triangles.end());
  std::sort(constrained.begin(), constrained.end());
  Json vertex_array = Json::array();
  for (const auto& vertex : output_vertices) vertex_array.push_back(xy_json(vertex));
  Json triangle_array = Json::array();
  for (const auto& t : triangles) triangle_array.push_back(Json::array({t[0], t[1], t[2]}));
  Json edge_array = Json::array();
  for (const auto& e : constrained) edge_array.push_back(Json::array({e[0], e[1]}));
  const auto triangle_count = triangles.size();
  const auto constrained_count = constrained.size();
  auto output = write_json_output(
      request, "mesh", "Triangulation2", source.unit,
      Json{{"vertices", vertex_array}, {"triangles", triangle_array},
           {"constrained_edges", edge_array}});
  Json metrics = {{"algorithm", "CGAL::refine_Delaunay_mesh_2"},
                  {"criteria", "CGAL::Delaunay_mesh_size_criteria_2"},
                  {"input_vertex_count", input_vertices},
                  {"ring_count", rings.size()},
                  {"vertex_count", output_vertices.size()},
                  {"steiner_vertex_count", output_vertices.size() - input_vertices},
                  {"triangle_count", triangle_count},
                  {"constrained_edge_count", constrained_count},
                  {"aspect_bound", aspect_bound},
                  {"size_bound", size_bound},
                  {"effective_kernel", kEpick}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---------------------------------------------------------------------------
// mesh.validate.delaunay_refinement_2 (independent)
// ---------------------------------------------------------------------------

Json run_refine_validator(const Request& request) {
  require_input_count(request, 2, "mesh.validate.delaunay_refinement_2");
  require_parameters(request, {"aspect_bound", "size_bound"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const double aspect_bound = number_parameter(request, "aspect_bound", 0.0, 1.0);
  const double size_bound = positive_length(request, "size_bound", request.inputs[0].unit);
  const auto candidate = read_triangulation2(request.inputs[0]);
  const auto domain = read_polygon_with_holes2(request.inputs[1]);
  if (const auto defect = domain_defect(domain)) {
    fail_validation("SOURCE_DOMAIN_INVALID", defect->message);
  }
  if (candidate.triangles.size() > kValidatorTriangleLimit) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "Candidate exceeds the Mesh_2 validation budget");
  }
  const auto& vertices = candidate.vertices;
  const std::size_t n = vertices.size();
  const auto rings = rings_of(domain);
  const double diagonal = bbox_diagonal(domain);
  const double tolerance = kGeometryTolerance * diagonal;

  std::set<XY> vertex_set(vertices.begin(), vertices.end());
  if (vertex_set.size() != n) fail_validation("REPEATED_VERTEX", "Candidate repeats a vertex");
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
  }
  for (std::size_t i = 0; i < n; ++i) {
    if (!used[i]) fail_validation("UNUSED_VERTEX", "A candidate vertex is in no triangle");
  }
  std::set<std::pair<std::size_t, std::size_t>> boundary;
  std::size_t undirected = 0;
  for (const auto& [edge, opposite] : directed) {
    if (directed.find({edge.second, edge.first}) == directed.end()) {
      boundary.insert(std::minmax(edge.first, edge.second));
      ++undirected;
    } else if (edge.first < edge.second) {
      ++undirected;
    }
  }
  const long long euler = static_cast<long long>(n) - static_cast<long long>(undirected) +
                          static_cast<long long>(candidate.triangles.size());
  if (euler != 1 - static_cast<long long>(domain.holes.size())) {
    fail_validation("EULER_CHARACTERISTIC_MISMATCH",
                    "V - E + F differs from 1 - number of holes");
  }
  // Constraint preservation: every domain segment is a chain of boundary edges
  // whose vertices lie on the segment, from the exact source endpoints.
  std::map<XY, std::size_t> position;
  for (std::size_t i = 0; i < n; ++i) position[vertices[i]] = i;
  std::set<std::pair<std::size_t, std::size_t>> chain;
  double maximum_deviation = 0;
  for (const auto* ring : rings) {
    for (std::size_t i = 0; i < ring->size(); ++i) {
      const XY& a = (*ring)[i];
      const XY& b = (*ring)[(i + 1) % ring->size()];
      const auto first = position.find(a);
      const auto last = position.find(b);
      if (first == position.end() || last == position.end()) {
        fail_validation("DOMAIN_VERTEX_MISSING", "A domain vertex is not a candidate vertex");
      }
      const double dx = b[0] - a[0], dy = b[1] - a[1];
      const double length2 = dx * dx + dy * dy;
      std::vector<std::pair<double, std::size_t>> on;
      for (std::size_t v = 0; v < n; ++v) {
        const double distance = point_segment_distance(vertices[v], a, b);
        if (distance > tolerance) continue;
        maximum_deviation = std::max(maximum_deviation, distance);
        on.push_back({((vertices[v][0] - a[0]) * dx + (vertices[v][1] - a[1]) * dy) / length2, v});
      }
      std::sort(on.begin(), on.end());
      if (on.size() < 2 || on.front().second != first->second || on.back().second != last->second) {
        fail_validation("CONSTRAINT_NOT_PRESERVED", "A domain segment is not a chain from its endpoints");
      }
      for (std::size_t k = 0; k + 1 < on.size(); ++k) {
        const auto key = std::minmax(on[k].second, on[k + 1].second);
        if (boundary.find(key) == boundary.end()) {
          fail_validation("CONSTRAINT_NOT_PRESERVED", "A domain segment piece is not a boundary edge");
        }
        chain.insert(key);
      }
    }
  }
  if (chain != boundary) {
    fail_validation("BOUNDARY_NOT_DOMAIN_BOUNDARY",
                    "The candidate boundary contains edges outside the domain boundary");
  }
  std::set<std::pair<std::size_t, std::size_t>> declared;
  for (const auto& e : candidate.constrained_edges) {
    if (e[0] == e[1] || !declared.insert(std::minmax(e[0], e[1])).second) {
      fail_validation("INVALID_CONSTRAINED_EDGE", "Constrained edge list is invalid");
    }
  }
  if (declared != chain) {
    fail_validation("CONSTRAINT_NOT_PRESERVED",
                    "Declared constrained edges differ from the domain boundary chains");
  }
  // Coverage: all triangles are positive and the surface is edge-manifold with
  // exactly the domain boundary, so equal total area means every domain point
  // is covered once. Centroids are an independent point-location cross-check.
  const double domain_area = CGAL::to_double(domain_twice_area(domain)) / 2.0;
  const double mesh_area = CGAL::to_double(total) / 2.0;
  const double area_error = std::abs(mesh_area - domain_area) / domain_area;
  if (!(area_error <= kGeometryTolerance)) {
    fail_validation("AREA_COVERAGE_MISMATCH", "Triangle areas do not sum to the domain area");
  }
  for (const auto& t : candidate.triangles) {
    const XY centroid{(vertices[t[0]][0] + vertices[t[1]][0] + vertices[t[2]][0]) / 3.0,
                      (vertices[t[0]][1] + vertices[t[1]][1] + vertices[t[2]][1]) / 3.0};
    bool inside = strictly_inside(domain.outer, centroid);
    for (const auto& hole : domain.holes) inside = inside && !strictly_inside(hole, centroid);
    if (!inside) fail_validation("TRIANGLE_OUTSIDE_DOMAIN", "A triangle centroid lies outside the domain");
  }
  // Shape and size criteria, exact in the candidate coordinates.
  const FT bound(aspect_bound);
  const FT size_squared = FT(size_bound) * FT(size_bound) * FT(1.0 + 1e-12);
  const FT shape_slack = FT(1.0 - 1e-9);
  double minimum_sine_squared = 1.0, maximum_edge_squared = 0.0;
  for (const auto& t : candidate.triangles) {
    FT a = sq_length(vertices[t[1]], vertices[t[2]]);
    FT b = sq_length(vertices[t[2]], vertices[t[0]]);
    FT c = sq_length(vertices[t[0]], vertices[t[1]]);
    FT longest = a, second = b;
    if (longest < second) std::swap(longest, second);
    if (longest < c) { second = longest; longest = c; }
    else if (second < c) { second = c; }
    if (longest > size_squared) {
      fail_validation("SIZE_CRITERION_VIOLATED", "A triangle edge exceeds size_bound");
    }
    const FT twice = twice_area(vertices[t[0]], vertices[t[1]], vertices[t[2]]);
    const FT lhs = twice * twice;
    if (lhs < bound * shape_slack * longest * second) {
      fail_validation("SHAPE_CRITERION_VIOLATED", "A triangle violates the aspect bound");
    }
    minimum_sine_squared = std::min(minimum_sine_squared,
                                    CGAL::to_double(lhs) / (CGAL::to_double(longest) * CGAL::to_double(second)));
    maximum_edge_squared = std::max(maximum_edge_squared, CGAL::to_double(longest));
  }
  // Constrained Delaunay property across every unconstrained interior edge.
  std::size_t delaunay_edges = 0;
  for (const auto& [edge, opposite] : directed) {
    if (edge.first > edge.second) continue;
    const auto twin = directed.find({edge.second, edge.first});
    if (twin == directed.end()) continue;
    if (chain.count(std::minmax(edge.first, edge.second)) != 0) continue;
    if (CGAL::side_of_bounded_circle(p2(vertices[edge.first]), p2(vertices[edge.second]),
                                     p2(vertices[opposite]), p2(vertices[twin->second])) ==
        CGAL::ON_BOUNDED_SIDE) {
      fail_validation("NOT_LOCALLY_DELAUNAY",
                      "An unconstrained interior edge violates the empty-circle property");
    }
    ++delaunay_edges;
  }
  Json report = {
      {"checks",
       {{"input_domain_valid", true},
        {"triangles_counterclockwise", true},
        {"edge_manifold", true},
        {"euler_characteristic", true},
        {"constraints_preserved", true},
        {"boundary_equals_domain_boundary", true},
        {"area_covers_domain", true},
        {"triangles_inside_domain", true},
        {"shape_criterion_satisfied", true},
        {"size_criterion_satisfied", true},
        {"constrained_delaunay", true}}},
      {"vertex_count", n},
      {"triangle_count", candidate.triangles.size()},
      {"boundary_edge_count", boundary.size()},
      {"hole_count", domain.holes.size()},
      {"locally_delaunay_edge_count", delaunay_edges},
      {"minimum_angle_degrees",
       std::asin(std::sqrt(minimum_sine_squared)) * 180.0 / 3.14159265358979323846},
      {"maximum_edge_length", std::sqrt(maximum_edge_squared)},
      {"boundary_maximum_deviation", maximum_deviation},
      {"area", {{"exact", exact_string(total / FT(2))}, {"unit", request.inputs[0].unit + "^2"}}},
      {"relative_area_error", area_error},
      {"independence",
       "exact orientation/in-circle predicates, edge maps and own point location on the raw "
       "domain; CGAL Mesh_2 classes and refine_Delaunay_mesh_2 are not used"}};
  return finish_validation(request, "mesh.validate.delaunay_refinement_2", std::move(report));
}

}  // namespace

std::vector<OperationDefinition> operations() {
  std::vector<OperationDefinition> result;
  result.push_back(make_definition(
      "mesh2.refine.delaunay", {"PolygonWithHoles2"}, "Triangulation2", "transform", run_refine,
      {"Mesh_2", "Triangulation_2"},
      {{"source_header", "CGAL/Delaunay_mesher_2.h"},
       {"symbols", {"refine_Delaunay_mesh_2", "Delaunay_mesh_size_criteria_2"}},
       {"input_format", "json"},
       {"output_format", "json"},
       {"required_parameters", {"aspect_bound", "size_bound"}},
       {"validators", {"mesh.validate.delaunay_refinement_2"}},
       {"validator_parameter_bindings",
        {{"mesh.validate.delaunay_refinement_2",
          {{"aspect_bound", "aspect_bound"}, {"size_bound", "size_bound"}}}}},
       {"maximum_domain_vertices", kMaximumDomainVertices},
       {"maximum_output_triangles", kMaximumMeshTriangles}}));
  result.push_back(make_definition(
      "mesh.validate.delaunay_refinement_2", {"Triangulation2", "PolygonWithHoles2"},
      "ValidationReport", "validator", run_refine_validator, {"Mesh_2", "Triangulation_2"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"bound_parameters", {"aspect_bound", "size_bound"}},
       {"checks",
        {"input_domain_valid", "triangles_counterclockwise", "edge_manifold",
         "euler_characteristic", "constraints_preserved", "boundary_equals_domain_boundary",
         "area_covers_domain", "triangles_inside_domain", "shape_criterion_satisfied",
         "size_criterion_satisfied", "constrained_delaunay"}}}));
  for (auto& definition : surface_mesh_operations()) result.push_back(std::move(definition));
  return result;
}

}  // namespace cgal_master::wave_e
