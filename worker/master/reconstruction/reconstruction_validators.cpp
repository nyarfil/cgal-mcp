// Independent validators for the surface reconstruction family (7.10).
//
// They never call Poisson_surface_reconstruction_3, Advancing_front_surface_
// reconstruction, Scale_space_reconstruction_3, Alpha_wrap_3 or any other CGAL
// code: the candidate OFF and the source points are parsed here, combinatorics
// (manifoldness, orientation, Euler characteristic, components) are derived
// from the raw index lists, and every geometric acceptance bound is decided in
// exact rational arithmetic (GMP mpq) on the binary64 input values:
//  * source -> surface: for every source point an exact squared point-triangle
//    distance <= bound^2 is exhibited (double only selects candidates);
//  * surface -> source: per triangle, every point x satisfies
//    d(x, P) <= min(circumradius, longest edge) + max_v d(v, P), with every
//    term an exact rational square and sqrt(a) + sqrt(b) <= B decided exactly;
//  * orientation: exact signed volume; enclosure: exact axis-ray parity.

#include "reconstruction_common.h"

#include <gmpxx.h>

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace cgal_master::reconstruction_ops {
namespace {

using Q = mpq_class;
using E3 = std::array<Q, 3>;

E3 exact3(const V3& v) {
  E3 result;
  for (int k = 0; k < 3; ++k) mpq_set_d(result[k].get_mpq_t(), v[k]);
  return result;
}

E3 sub(const E3& a, const E3& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
Q dot(const E3& a, const E3& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
E3 cross(const E3& a, const E3& b) {
  return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}

V3 dsub(const V3& a, const V3& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
double ddot(const V3& a, const V3& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
V3 dcross(const V3& a, const V3& b) {
  return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}

// Closest point on triangle (Ericson, Real-Time Collision Detection 5.1.5);
// templated so the same region logic runs in double (filter) and mpq (decision).
template <typename T, typename P>
T squared_distance_point_triangle(const P& p, const P& a, const P& b, const P& c) {
  const auto s = [](const P& u, const P& v) { return P{u[0] - v[0], u[1] - v[1], u[2] - v[2]}; };
  const auto d = [](const P& u, const P& v) { return T(u[0] * v[0] + u[1] * v[1] + u[2] * v[2]); };
  const auto len2 = [&](const P& u) { return d(u, u); };
  const P ab = s(b, a), ac = s(c, a), ap = s(p, a);
  const T d1 = d(ab, ap), d2 = d(ac, ap);
  if (d1 <= 0 && d2 <= 0) return len2(ap);
  const P bp = s(p, b);
  const T d3 = d(ab, bp), d4 = d(ac, bp);
  if (d3 >= 0 && d4 <= d3) return len2(bp);
  const T vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) {
    const T v = d1 / (d1 - d3);
    const P q{a[0] + v * ab[0], a[1] + v * ab[1], a[2] + v * ab[2]};
    return len2(s(p, q));
  }
  const P cp = s(p, c);
  const T d5 = d(ab, cp), d6 = d(ac, cp);
  if (d6 >= 0 && d5 <= d6) return len2(cp);
  const T vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) {
    const T w = d2 / (d2 - d6);
    const P q{a[0] + w * ac[0], a[1] + w * ac[1], a[2] + w * ac[2]};
    return len2(s(p, q));
  }
  const T va = d3 * d6 - d5 * d4;
  if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
    const T w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
    const P bc = s(c, b);
    const P q{b[0] + w * bc[0], b[1] + w * bc[1], b[2] + w * bc[2]};
    return len2(s(p, q));
  }
  const T denominator = T(1) / (va + vb + vc);
  const T v = vb * denominator, w = vc * denominator;
  const P q{a[0] + ab[0] * v + ac[0] * w, a[1] + ab[1] * v + ac[1] * w, a[2] + ab[2] * v + ac[2] * w};
  return len2(s(p, q));
}

// sqrt(a) + sqrt(b) <= B, all exact (a, b >= 0, B >= 0).
bool sum_of_roots_at_most(const Q& a, const Q& b, const Q& bound) {
  const Q rest = bound * bound - a - b;
  if (rest < 0) return false;
  return 4 * a * b <= rest * rest;
}

double approx_sqrt(const Q& value) { return std::sqrt(value.get_d()); }

struct ExactMesh {
  std::vector<E3> vertices;
};

void require_basic_mesh(const RawMesh& mesh, const ExactMesh& exact, const Topology& topology, Json& checks) {
  if (topology.repeated_index_face_count != 0) {
    validation_failure("DEGENERATE_TRIANGLE", "A candidate face repeats a vertex index");
  }
  {
    std::set<V3> seen(mesh.vertices.begin(), mesh.vertices.end());
    if (seen.size() != mesh.vertices.size()) validation_failure("REPEATED_VERTEX", "Candidate repeats a vertex position");
  }
  for (const auto& face : mesh.faces) {
    const E3 n = cross(sub(exact.vertices[face[1]], exact.vertices[face[0]]),
                       sub(exact.vertices[face[2]], exact.vertices[face[0]]));
    if (n[0] == 0 && n[1] == 0 && n[2] == 0) {
      validation_failure("DEGENERATE_TRIANGLE", "A candidate triangle has zero area (exact)");
    }
  }
  checks["triangle_mesh"] = true;
  checks["nondegenerate_triangles_exact"] = true;
  if (topology.unreferenced_vertex_count != 0) validation_failure("UNUSED_VERTEX", "A candidate vertex is in no triangle");
  checks["no_unreferenced_vertices"] = true;
  if (!topology.edge_manifold) validation_failure("NON_MANIFOLD_EDGE", "An edge is used by more than two triangles");
  checks["edge_manifold"] = true;
  if (!topology.vertex_manifold) validation_failure("NON_MANIFOLD_VERTEX", "A vertex star is not a single fan");
  checks["vertex_manifold"] = true;
  if (!topology.consistently_oriented) {
    validation_failure("INCONSISTENT_ORIENTATION", "Adjacent triangles are not consistently oriented");
  }
  checks["consistent_orientation"] = true;
}

Q signed_volume_times_six(const ExactMesh& exact, const RawMesh& mesh) {
  Q total = 0;
  for (const auto& face : mesh.faces) {
    total += dot(exact.vertices[face[0]], cross(exact.vertices[face[1]], exact.vertices[face[2]]));
  }
  return total;
}

void require_closed_outward(const RawMesh& mesh, const ExactMesh& exact, const Topology& topology,
                            Json& checks, Json& details) {
  if (!topology.closed) validation_failure("SURFACE_NOT_CLOSED", "Candidate has boundary edges");
  checks["closed_surface"] = true;
  const Q volume6 = signed_volume_times_six(exact, mesh);
  if (volume6 <= 0) validation_failure("ORIENTATION_NOT_OUTWARD", "Exact signed volume is not positive");
  checks["outward_orientation_exact_volume"] = true;
  details["signed_volume_approx"] = volume6.get_d() / 6.0;
}

Json topology_json(const Topology& t) {
  Json result{{"vertex_count", t.vertex_count},
              {"facet_count", t.face_count},
              {"edge_count", t.edge_count},
              {"boundary_edge_count", t.boundary_edge_count},
              {"component_count", t.component_count},
              {"euler_characteristic", t.euler_characteristic}};
  if (t.closed && t.component_count == 1) result["genus"] = (2 - t.euler_characteristic) / 2;
  return result;
}

// Index of the (double-)nearest source point; ties keep the lowest index.
std::size_t nearest_point(const std::vector<V3>& points, const V3& v) {
  std::size_t best = 0;
  double best_distance = std::numeric_limits<double>::infinity();
  for (std::size_t i = 0; i < points.size(); ++i) {
    const V3 d = dsub(points[i], v);
    const double value = ddot(d, d);
    if (value < best_distance) {
      best_distance = value;
      best = i;
    }
  }
  return best;
}

struct SourceDistance {
  double maximum = 0;          // approx of the largest exhibited exact distance
  Q maximum_squared = 0;       // exact
};

// Every source point is within `bound` of the candidate surface (exact).
SourceDistance source_to_surface(const std::vector<V3>& points, const RawMesh& mesh, const ExactMesh& exact,
                                 const Q& bound, double bound_value, const std::vector<bool>& skip,
                                 std::vector<bool>* uncovered = nullptr) {
  SourceDistance result;
  const Q bound2 = bound * bound;
  std::vector<std::pair<double, std::size_t>> order(mesh.faces.size());
  for (std::size_t i = 0; i < points.size(); ++i) {
    if (skip[i]) continue;
    for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
      const auto& face = mesh.faces[f];
      order[f] = {squared_distance_point_triangle<double>(points[i], mesh.vertices[face[0]],
                                                          mesh.vertices[face[1]], mesh.vertices[face[2]]),
                  f};
    }
    std::sort(order.begin(), order.end());
    const E3 p = exact3(points[i]);
    bool found = false;
    const double limit = (bound_value * (1 + 1e-6)) * (bound_value * (1 + 1e-6)) + 1e-300;
    for (const auto& [approx, f] : order) {
      if (approx > limit) break;
      const auto& face = mesh.faces[f];
      const Q d2 = squared_distance_point_triangle<Q>(p, exact.vertices[face[0]], exact.vertices[face[1]],
                                                      exact.vertices[face[2]]);
      if (d2 <= bound2) {
        if (d2 > result.maximum_squared) result.maximum_squared = d2;
        found = true;
        break;
      }
    }
    if (!found && uncovered != nullptr) {
      (*uncovered)[i] = true;
      continue;
    }
    if (!found) {
      validation_failure("SOURCE_TO_SURFACE_BOUND_EXCEEDED",
                         "Source point " + std::to_string(i) + " is farther than the bound from the surface");
    }
  }
  result.maximum = approx_sqrt(result.maximum_squared);
  return result;
}

struct SurfaceBound {
  Q maximum_vertex_squared = 0;  // largest exact d(v, P)^2 (upper bound)
  Q minimum_vertex_squared = 0;
  double maximum_certified = 0;  // approx of the largest per-triangle certified bound
};

// Every point of every triangle is within `bound` of the source (certified, exact).
SurfaceBound surface_to_source(const std::vector<V3>& points, const RawMesh& mesh, const ExactMesh& exact,
                               const Q& bound) {
  SurfaceBound result;
  std::vector<E3> source;
  source.reserve(points.size());
  for (const auto& p : points) source.push_back(exact3(p));
  std::vector<Q> vertex_squared(mesh.vertices.size());
  bool first = true;
  for (std::size_t v = 0; v < mesh.vertices.size(); ++v) {
    const auto nearest = nearest_point(points, mesh.vertices[v]);
    const E3 d = sub(exact.vertices[v], source[nearest]);
    vertex_squared[v] = dot(d, d);
    if (first || vertex_squared[v] > result.maximum_vertex_squared) result.maximum_vertex_squared = vertex_squared[v];
    if (first || vertex_squared[v] < result.minimum_vertex_squared) result.minimum_vertex_squared = vertex_squared[v];
    first = false;
  }
  for (const auto& face : mesh.faces) {
    const E3& a = exact.vertices[face[0]];
    const E3& b = exact.vertices[face[1]];
    const E3& c = exact.vertices[face[2]];
    const Q ab2 = dot(sub(b, a), sub(b, a)), bc2 = dot(sub(c, b), sub(c, b)), ca2 = dot(sub(a, c), sub(a, c));
    const E3 n = cross(sub(b, a), sub(c, a));
    const Q circumradius2 = ab2 * bc2 * ca2 / (4 * dot(n, n));
    const Q longest2 = std::max({ab2, bc2, ca2});
    const Q cover2 = std::min(circumradius2, longest2);
    const Q vertex2 = std::max({vertex_squared[face[0]], vertex_squared[face[1]], vertex_squared[face[2]]});
    if (!sum_of_roots_at_most(cover2, vertex2, bound)) {
      validation_failure("SURFACE_TO_SOURCE_BOUND_EXCEEDED",
                         "A candidate triangle is not certified within the bound of the source points");
    }
    result.maximum_certified = std::max(result.maximum_certified, approx_sqrt(cover2) + approx_sqrt(vertex2));
  }
  return result;
}

Json squared_metric(const Q& value, const std::string& unit) {
  return Json{{"value", value.get_d()}, {"unit", unit + "2"}, {"squared_length", true}};
}

Json length_metric(double value, const std::string& unit) { return Json{{"value", value}, {"unit", unit}}; }

Q exact_length(double value) {
  Q result;
  mpq_set_d(result.get_mpq_t(), value);
  return result;
}

// ---- reconstruction.validate.poisson -----------------------------------------

// Orientation against the source normals: the nearest candidate triangle of every source point faces
// the same side as the oriented input normal. Returns the number of disagreeing source points.
std::size_t normal_disagreements(const PointCloud& source, const RawMesh& mesh,
                                 const std::vector<bool>* skip = nullptr) {
  std::size_t disagreements = 0;
  for (std::size_t i = 0; i < source.points.size(); ++i) {
    if (skip != nullptr && (*skip)[i]) continue;
    double best = std::numeric_limits<double>::infinity();
    std::size_t best_face = 0;
    for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
      const auto& face = mesh.faces[f];
      const double d = squared_distance_point_triangle<double>(source.points[i], mesh.vertices[face[0]],
                                                               mesh.vertices[face[1]], mesh.vertices[face[2]]);
      if (d < best) {
        best = d;
        best_face = f;
      }
    }
    const auto& face = mesh.faces[best_face];
    const V3 n = dcross(dsub(mesh.vertices[face[1]], mesh.vertices[face[0]]),
                        dsub(mesh.vertices[face[2]], mesh.vertices[face[0]]));
    if (!(ddot(n, source.normals[i]) > 0)) ++disagreements;
  }
  return disagreements;
}


Json validate_poisson(const Request& request) {
  require_inputs(request, 2, "reconstruction.validate.poisson");
  require_parameter_names(request, {"max_deviation"}, {"sm_angle", "sm_radius", "sm_distance"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const std::string& unit = request.inputs[0].unit;
  const double bound_value = length_parameter(request, "max_deviation", unit);
  const auto source = read_points_with_normals(request.inputs[1]);
  if (source.points.empty()) validation_failure("EMPTY_SOURCE", "Source point set is empty");
  const auto mesh = read_candidate_mesh(request.inputs[0]);
  ExactMesh exact;
  for (const auto& v : mesh.vertices) exact.vertices.push_back(exact3(v));
  const auto topology = analyze_topology(mesh);
  Json checks{{"source_points_valid", true}};
  Json details;
  require_basic_mesh(mesh, exact, topology, checks);
  require_closed_outward(mesh, exact, topology, checks, details);
  const std::size_t disagreements = normal_disagreements(source, mesh);
  if (disagreements != 0) {
    validation_failure("NORMAL_ORIENTATION_MISMATCH",
                       std::to_string(disagreements) + " source normals oppose their nearest candidate facet");
  }
  checks["source_normals_agree_with_orientation"] = true;
  const Q bound = exact_length(bound_value);
  const auto forward = source_to_surface(source.points, mesh, exact, bound, bound_value,
                                         std::vector<bool>(source.points.size(), false));
  checks["source_to_surface_within_bound_exact"] = true;
  const auto backward = surface_to_source(source.points, mesh, exact, bound);
  checks["surface_to_source_within_bound_certified"] = true;
  Json report{{"checks", checks},
              {"topology", topology_json(topology)},
              {"max_deviation", length_metric(bound_value, unit)},
              {"max_source_to_surface_distance", length_metric(forward.maximum, unit)},
              {"max_source_to_surface_squared_distance", squared_metric(forward.maximum_squared, unit)},
              {"max_vertex_to_source_squared_distance", squared_metric(backward.maximum_vertex_squared, unit)},
              {"max_certified_surface_to_source_distance", length_metric(backward.maximum_certified, unit)},
              {"signed_volume", Json{{"value", details["signed_volume_approx"]}, {"unit", unit + "3"}}},
              {"independence",
               "own OFF/PLY parsers and combinatorics; exact GMP rational point-triangle distances, signed "
               "volume and certified triangle cover bounds; CGAL Poisson_surface_reconstruction_3, Mesh_3 and "
               "Point_set_processing_3 are not used"}};
  return finish_reconstruction_validation(request, "reconstruction.validate.poisson", std::move(report));
}

// ---- reconstruction.validate.poisson_boundary ---------------------------------
// poisson_surface_reconstruction_delaunay always requests the Mesh_3 manifold_with_boundary option, so the
// candidate may legitimately have boundary edges. Accepted: edge- and vertex-manifold, consistently
// oriented (with boundary), facets agreeing with the oriented source normals, every source point within
// max_deviation of the surface, every candidate triangle certified within max_deviation of the source
// and with an exact circumradius of at most max_circumradius. A closed candidate must in addition be
// outward oriented. The boundary edge count is reported, never hidden, and closedness is never claimed.

Json validate_poisson_boundary(const Request& request) {
  require_inputs(request, 2, "reconstruction.validate.poisson_boundary");
  require_parameter_names(request, {"max_deviation", "max_circumradius", "min_coverage"},
                          {"sm_angle", "sm_radius", "sm_distance"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const std::string& unit = request.inputs[0].unit;
  const double bound_value = length_parameter(request, "max_deviation", unit);
  const double radius_value = length_parameter(request, "max_circumradius", unit);
  const double minimum_coverage = number_parameter(request, "min_coverage", 0.0, 1.0);
  const auto source = read_points_with_normals(request.inputs[1]);
  if (source.points.empty()) validation_failure("EMPTY_SOURCE", "Source point set is empty");
  const auto mesh = read_candidate_mesh(request.inputs[0]);
  ExactMesh exact;
  for (const auto& v : mesh.vertices) exact.vertices.push_back(exact3(v));
  const auto topology = analyze_topology(mesh);
  Json checks{{"source_points_valid", true}};
  Json details;
  require_basic_mesh(mesh, exact, topology, checks);
  if (topology.closed) require_closed_outward(mesh, exact, topology, checks, details);
  checks["manifold_with_boundary_consistently_oriented"] = true;
  const Q bound = exact_length(bound_value);
  // One-sided coverage: the holes the manifold_with_boundary option leaves are disclosed, not hidden. Source
  // points farther than the bound from the surface are counted as uncovered; their fraction is limited by
  // min_coverage, and the orientation test applies to the covered points.
  std::vector<bool> uncovered(source.points.size(), false);
  const auto forward = source_to_surface(source.points, mesh, exact, bound, bound_value,
                                         std::vector<bool>(source.points.size(), false), &uncovered);
  std::size_t uncovered_count = 0;
  for (const bool flag : uncovered) uncovered_count += flag ? 1 : 0;
  const double coverage =
      1.0 - static_cast<double>(uncovered_count) / static_cast<double>(source.points.size());
  if (coverage < minimum_coverage) {
    validation_failure("SOURCE_COVERAGE_BELOW_MINIMUM",
                       std::to_string(uncovered_count) + " source points are farther than max_deviation from the surface");
  }
  checks["source_coverage_at_least_minimum_exact"] = true;
  const std::size_t disagreements = normal_disagreements(source, mesh, &uncovered);
  if (disagreements != 0) {
    validation_failure("NORMAL_ORIENTATION_MISMATCH",
                       std::to_string(disagreements) + " covered source normals oppose their nearest candidate facet");
  }
  checks["source_normals_agree_with_orientation"] = true;
  const auto backward = surface_to_source(source.points, mesh, exact, bound);
  checks["surface_to_source_within_bound_certified"] = true;
  const Q radius = exact_length(radius_value);
  Q largest_circumradius2 = 0;
  for (const auto& face : mesh.faces) {
    const E3& a = exact.vertices[face[0]];
    const E3& b = exact.vertices[face[1]];
    const E3& c = exact.vertices[face[2]];
    const Q ab2 = dot(sub(b, a), sub(b, a)), bc2 = dot(sub(c, b), sub(c, b)), ca2 = dot(sub(a, c), sub(a, c));
    const E3 n = cross(sub(b, a), sub(c, a));
    const Q circumradius2 = ab2 * bc2 * ca2 / (4 * dot(n, n));
    if (circumradius2 > largest_circumradius2) largest_circumradius2 = circumradius2;
  }
  if (largest_circumradius2 > radius * radius) {
    validation_failure("FACET_RADIUS_BOUND_EXCEEDED", "A candidate triangle has a circumradius above max_circumradius");
  }
  checks["facet_circumradius_within_bound_exact"] = true;
  Json report{{"checks", checks},
              {"topology", topology_json(topology)},
              {"closed", topology.closed},
              {"boundary_edge_count", topology.boundary_edge_count},
              {"max_deviation", length_metric(bound_value, unit)},
              {"max_circumradius_bound", length_metric(radius_value, unit)},
              {"max_circumradius", length_metric(approx_sqrt(largest_circumradius2), unit)},
              {"source_point_count", source.points.size()},
              {"uncovered_source_point_count", uncovered_count},
              {"source_coverage_fraction", coverage},
              {"min_coverage", minimum_coverage},
              {"max_covered_source_to_surface_distance", length_metric(forward.maximum, unit)},
              {"max_covered_source_to_surface_squared_distance", squared_metric(forward.maximum_squared, unit)},
              {"max_certified_surface_to_source_distance", length_metric(backward.maximum_certified, unit)},
              {"closedness_claimed", false},
              {"independence",
               "own OFF/PLY parsers and combinatorics; exact GMP rational point-triangle distances, circumradii "
               "and certified triangle cover bounds; manifold-with-boundary topology from raw index lists; CGAL "
               "Poisson_surface_reconstruction_3, Mesh_3 and Point_set_processing_3 are not used"}};
  if (details.contains("signed_volume_approx")) {
    report["signed_volume"] = Json{{"value", details["signed_volume_approx"]}, {"unit", unit + "3"}};
  }
  return finish_reconstruction_validation(request, "reconstruction.validate.poisson_boundary", std::move(report));
}

// ---- reconstruction.validate.interpolating -----------------------------------

Json validate_interpolating(const Request& request) {
  require_inputs(request, 2, "reconstruction.validate.interpolating");
  require_parameter_names(request, {"max_deviation"},
                          {"radius_ratio_bound", "beta", "iterations", "neighbors", "maximum_facet_length"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const std::string& unit = request.inputs[0].unit;
  const double bound_value = length_parameter(request, "max_deviation", unit);
  const auto source = read_points(request.inputs[1]);
  if (source.points.empty()) validation_failure("EMPTY_SOURCE", "Source point set is empty");
  const auto mesh = read_candidate_mesh(request.inputs[0]);
  ExactMesh exact;
  for (const auto& v : mesh.vertices) exact.vertices.push_back(exact3(v));
  const auto topology = analyze_topology(mesh);
  Json checks{{"source_points_valid", true}};
  Json details;
  require_basic_mesh(mesh, exact, topology, checks);
  // Interpolation: every candidate vertex is bitwise one of the source points.
  std::map<V3, std::size_t> index;
  for (std::size_t i = 0; i < source.points.size(); ++i) index.emplace(source.points[i], i);
  std::vector<bool> used(source.points.size(), false);
  for (const auto& v : mesh.vertices) {
    const auto it = index.find(v);
    if (it == index.end()) validation_failure("VERTEX_NOT_SOURCE_POINT", "A candidate vertex is not a source point");
    used[it->second] = true;
  }
  checks["vertices_are_source_points"] = true;
  // Open reconstructions are legitimate (reported as closed=false); a closed
  // one must enclose a positive volume.
  if (topology.closed) require_closed_outward(mesh, exact, topology, checks, details);
  const Q bound = exact_length(bound_value);
  const auto forward = source_to_surface(source.points, mesh, exact, bound, bound_value, used);
  checks["source_to_surface_within_bound_exact"] = true;
  const auto backward = surface_to_source(source.points, mesh, exact, bound);
  if (backward.maximum_vertex_squared != 0) {
    validation_failure("VERTEX_NOT_SOURCE_POINT", "A candidate vertex is not a source point");
  }
  checks["surface_to_source_within_bound_certified"] = true;
  std::size_t unused = 0;
  for (const bool flag : used) unused += flag ? 0 : 1;
  Json report{{"checks", checks},
              {"topology", topology_json(topology)},
              {"closed", topology.closed},
              {"used_source_point_count", source.points.size() - unused},
              {"unused_source_point_count", unused},
              {"max_deviation", length_metric(bound_value, unit)},
              {"max_unused_point_to_surface_distance", length_metric(forward.maximum, unit)},
              {"max_unused_point_to_surface_squared_distance", squared_metric(forward.maximum_squared, unit)},
              {"max_certified_surface_to_source_distance", length_metric(backward.maximum_certified, unit)},
              {"independence",
               "own OFF/XYZ parsers and combinatorics; exact vertex identity with the source, exact GMP rational "
               "point-triangle distances and certified triangle cover bounds; CGAL "
               "Advancing_front_surface_reconstruction and Scale_space_reconstruction_3 are not used"}};
  if (details.contains("signed_volume_approx")) {
    report["signed_volume"] = Json{{"value", details["signed_volume_approx"]}, {"unit", unit + "3"}};
  }
  return finish_reconstruction_validation(request, "reconstruction.validate.interpolating", std::move(report));
}

// ---- reconstruction.validate.alpha_wrap --------------------------------------

// Exact parity of crossings of the ray p + t e_axis (t > 0) with the surface.
// Returns -1 when the ray is degenerate (touches an edge/vertex in projection)
// and -2 when p lies on the surface.
int ray_parity(const RawMesh& mesh, const ExactMesh& exact, const V3& p, const E3& pe, int axis) {
  const int u = (axis + 1) % 3, w = (axis + 2) % 3;
  int crossings = 0;
  for (const auto& face : mesh.faces) {
    const V3& a = mesh.vertices[face[0]];
    const V3& b = mesh.vertices[face[1]];
    const V3& c = mesh.vertices[face[2]];
    if (std::max({a[axis], b[axis], c[axis]}) < p[axis]) continue;
    if (std::min({a[u], b[u], c[u]}) > p[u] || std::max({a[u], b[u], c[u]}) < p[u]) continue;
    if (std::min({a[w], b[w], c[w]}) > p[w] || std::max({a[w], b[w], c[w]}) < p[w]) continue;
    const E3& ea = exact.vertices[face[0]];
    const E3& eb = exact.vertices[face[1]];
    const E3& ec = exact.vertices[face[2]];
    const auto orient = [&](const E3& s, const E3& t) {
      const Q value = (t[u] - s[u]) * (pe[w] - s[w]) - (t[w] - s[w]) * (pe[u] - s[u]);
      return sgn(value);
    };
    const int o1 = orient(ea, eb), o2 = orient(eb, ec), o3 = orient(ec, ea);
    if ((o1 > 0 || o2 > 0 || o3 > 0) && (o1 < 0 || o2 < 0 || o3 < 0)) continue;  // outside projection
    if (o1 == 0 || o2 == 0 || o3 == 0) {
      // On a projected edge/vertex: the ray is degenerate unless the triangle is entirely behind p.
      return -1;
    }
    const E3 n = cross(sub(eb, ea), sub(ec, ea));
    const Q along = dot(n, sub(ea, pe));
    const int s_along = sgn(along), s_normal = sgn(n[axis]);
    if (s_along == 0) return -2;
    if (s_along == s_normal) ++crossings;
  }
  return crossings % 2;
}

Json validate_alpha_wrap(const Request& request) {
  require_inputs(request, 2, "reconstruction.validate.alpha_wrap");
  require_parameter_names(request, {"alpha", "offset"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const std::string& unit = request.inputs[0].unit;
  const double alpha = length_parameter(request, "alpha", unit);
  const double offset = length_parameter(request, "offset", unit);
  const auto source = read_points(request.inputs[1]);
  if (source.points.empty()) validation_failure("EMPTY_SOURCE", "Source point set is empty");
  const auto mesh = read_candidate_mesh(request.inputs[0]);
  ExactMesh exact;
  for (const auto& v : mesh.vertices) exact.vertices.push_back(exact3(v));
  const auto topology = analyze_topology(mesh);
  Json checks{{"source_points_valid", true}};
  Json details;
  require_basic_mesh(mesh, exact, topology, checks);
  require_closed_outward(mesh, exact, topology, checks, details);
  // Strict enclosure: every source point is strictly inside the closed surface.
  for (std::size_t i = 0; i < source.points.size(); ++i) {
    const E3 pe = exact3(source.points[i]);
    int parity = -1;
    for (int axis = 0; axis < 3 && parity == -1; ++axis) parity = ray_parity(mesh, exact, source.points[i], pe, axis);
    if (parity == -2) validation_failure("SOURCE_ON_SURFACE", "Source point " + std::to_string(i) + " lies on the wrap");
    if (parity == -1) {
      validation_failure("ENCLOSURE_UNDECIDABLE", "Every axis ray of source point " + std::to_string(i) +
                                                      " is degenerate; enclosure is not certified");
    }
    if (parity != 1) {
      validation_failure("SOURCE_NOT_ENCLOSED", "Source point " + std::to_string(i) + " is outside the wrap");
    }
  }
  checks["source_strictly_enclosed_exact"] = true;
  // Envelope: every wrap point is within alpha + offset of the source
  // (certified per triangle), and every wrap vertex lies in the offset band
  // [(1 - b) offset, (1 + b) offset] around the source. Alpha_wrap_3 constructs
  // its Steiner points on the offset surface; a few vertices are measured up to
  // about 1% off it (CGAL documents no exact vertex placement), hence b = 5%.
  const Q offset_q = exact_length(offset);
  const Q alpha_q = exact_length(alpha);
  const auto backward = surface_to_source(source.points, mesh, exact, alpha_q + offset_q);
  checks["surface_within_alpha_plus_offset_certified"] = true;
  constexpr double kOffsetBandRelative = 0.05;
  const Q upper = offset_q * exact_length(1.0 + kOffsetBandRelative);
  const Q lower = offset_q * exact_length(1.0 - kOffsetBandRelative);
  if (backward.maximum_vertex_squared > upper * upper) {
    validation_failure("VERTEX_BEYOND_OFFSET_BAND", "A wrap vertex is farther than the offset band from the source");
  }
  const Q lower2 = lower * lower;
  const double lower_filter = lower.get_d() * lower.get_d() * (1 + 1e-6);
  for (std::size_t v = 0; v < mesh.vertices.size(); ++v) {
    for (std::size_t i = 0; i < source.points.size(); ++i) {
      const V3 d = dsub(mesh.vertices[v], source.points[i]);
      if (ddot(d, d) > lower_filter) continue;
      const E3 e = sub(exact.vertices[v], exact3(source.points[i]));
      const Q d2 = dot(e, e);
      if (d2 < lower2) {
        validation_failure("VERTEX_INSIDE_OFFSET_BAND", "A wrap vertex is closer than the offset band to the source");
      }
    }
  }
  checks["vertices_in_offset_band_exact"] = true;
  const double vertex_max = approx_sqrt(backward.maximum_vertex_squared);
  const double vertex_min = approx_sqrt(backward.minimum_vertex_squared);
  Json report{{"checks", checks},
              {"topology", topology_json(topology)},
              {"alpha", length_metric(alpha, unit)},
              {"offset", length_metric(offset, unit)},
              {"max_vertex_to_source_distance", length_metric(vertex_max, unit)},
              {"min_vertex_to_source_distance", length_metric(vertex_min, unit)},
              {"max_vertex_to_source_squared_distance", squared_metric(backward.maximum_vertex_squared, unit)},
              {"max_certified_surface_to_source_distance", length_metric(backward.maximum_certified, unit)},
              {"offset_band_relative", kOffsetBandRelative},
              {"signed_volume", Json{{"value", details["signed_volume_approx"]}, {"unit", unit + "3"}}},
              {"independence",
               "own OFF/XYZ parsers and combinatorics; exact GMP rational signed volume, axis-ray parity, "
               "vertex-to-source distances and certified triangle cover bounds; CGAL Alpha_wrap_3 is not used"}};
  return finish_reconstruction_validation(request, "reconstruction.validate.alpha_wrap", std::move(report));
}

}  // namespace

std::vector<OperationDefinition> validator_operations() {
  std::vector<OperationDefinition> result;
  result.push_back(reconstruction_definition(
      "reconstruction.validate.poisson", {"TriangleSurfaceMesh", "PointSet3Normals"}, "ValidationReport",
      "validator", validate_poisson, {"Poisson_surface_reconstruction_3"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"bound_parameters", {"max_deviation"}},
       {"checks",
        {"source_points_valid", "triangle_mesh", "nondegenerate_triangles_exact", "no_unreferenced_vertices",
         "edge_manifold", "vertex_manifold", "consistent_orientation", "closed_surface",
         "outward_orientation_exact_volume", "source_normals_agree_with_orientation",
         "source_to_surface_within_bound_exact", "surface_to_source_within_bound_certified"}}}));
  result.push_back(reconstruction_definition(
      "reconstruction.validate.poisson_boundary", {"TriangleSurfaceMesh", "PointSet3Normals"}, "ValidationReport",
      "validator", validate_poisson_boundary, {"Poisson_surface_reconstruction_3"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"bound_parameters", {"max_deviation", "max_circumradius", "min_coverage"}},
       {"checks",
        {"source_points_valid", "triangle_mesh", "nondegenerate_triangles_exact", "no_unreferenced_vertices",
         "edge_manifold", "vertex_manifold", "consistent_orientation", "manifold_with_boundary_consistently_oriented",
         "source_normals_agree_with_orientation", "source_coverage_at_least_minimum_exact",
         "surface_to_source_within_bound_certified", "facet_circumradius_within_bound_exact"}}}));
  result.push_back(reconstruction_definition(
      "reconstruction.validate.interpolating", {"TriangleSurfaceMesh", "PointSet3"}, "ValidationReport",
      "validator", validate_interpolating,
      {"Advancing_front_surface_reconstruction", "Scale_space_reconstruction_3"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"bound_parameters", {"max_deviation"}},
       {"checks",
        {"source_points_valid", "triangle_mesh", "nondegenerate_triangles_exact", "no_unreferenced_vertices",
         "edge_manifold", "vertex_manifold", "consistent_orientation", "vertices_are_source_points",
         "source_to_surface_within_bound_exact", "surface_to_source_within_bound_certified"}}}));
  result.push_back(reconstruction_definition(
      "reconstruction.validate.alpha_wrap", {"TriangleSurfaceMesh", "PointSet3"}, "ValidationReport", "validator",
      validate_alpha_wrap, {"Alpha_wrap_3"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"bound_parameters", {"alpha", "offset"}},
       {"checks",
        {"source_points_valid", "triangle_mesh", "nondegenerate_triangles_exact", "no_unreferenced_vertices",
         "edge_manifold", "vertex_manifold", "consistent_orientation", "closed_surface",
         "outward_orientation_exact_volume", "source_strictly_enclosed_exact",
         "surface_within_alpha_plus_offset_certified", "vertices_in_offset_band_exact"}}}));
  return result;
}

}  // namespace cgal_master::reconstruction_ops
