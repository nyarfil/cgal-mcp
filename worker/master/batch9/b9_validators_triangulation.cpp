// Independent validators for the periodic and on-sphere Delaunay triangulations (7.11.04). No CGAL header is
// included; every predicate is evaluated exactly with GMP rationals on the raw binary64 input coordinates.
//
// Periodic (flat torus of period L): every reported simplex is a list of (point index, integer lattice offset);
// its vertices are p_i + L * offset. The validator requires positive orientation of every simplex, that every
// oriented facet (edge in 2D) occurs exactly once with each orientation modulo lattice translation (a closed
// pseudomanifold on the torus), total area/volume exactly L^2 / L^3 (the simplices tile one fundamental domain, so
// the covering degree is one), the torus Euler relation V - E + F (- T) = 0, and the empty-circle / empty-sphere
// property against every translate of every input point that can reach the circumscribed ball.
// On the sphere: faces are triples of input points oriented counter-clockwise seen from outside; the empty-circle
// property of the triangulation on the sphere is exactly orientation_3(p, q, r, s) <= 0 for every face (p, q, r)
// and point s (no point strictly beyond the plane of a face, on the cap side), the faces form a closed oriented
// 2-manifold with V - E + F = 2, and every vertex lies on the declared sphere within a declared relative tolerance.

#include "b9_common.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>

namespace cgal_master::batch9 {
namespace {

using batch2::concluded;
using batch2::require_member;
using batch2::vinfo;
using query_ops::read_points2;
using query_ops::read_points3;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;

constexpr double kSphereRadiusTolerance = 1e-9;

struct PVertex {
  std::size_t index;
  std::array<long long, 3> offset;  // unused trailing entries are zero in 2D
};

std::vector<std::vector<PVertex>> read_simplices(const Json& value, std::size_t arity, std::size_t dimension,
                                                 std::size_t points) {
  if (!value.is_array() || value.empty()) validation_failure("REPORT_VALUE_INVALID", "No simplices are reported");
  std::vector<std::vector<PVertex>> result;
  for (const auto& simplex : value) {
    if (!simplex.is_array() || simplex.size() != arity) {
      validation_failure("REPORT_VALUE_INVALID", "A simplex has the wrong number of vertices");
    }
    std::vector<PVertex> row;
    std::set<std::size_t> indices;
    for (const auto& vertex : simplex) {
      if (!vertex.is_array() || vertex.size() != dimension + 1) {
        validation_failure("REPORT_VALUE_INVALID", "A periodic vertex must be [index, offsets...]");
      }
      PVertex v{batch2::index_of(vertex[0], points, "periodic vertex index"), {0, 0, 0}};
      for (std::size_t k = 0; k < dimension; ++k) {
        if (!vertex[k + 1].is_number_integer() || std::llabs(vertex[k + 1].get<long long>()) > kMaximumReportedOffset) {
          validation_failure("REPORT_VALUE_INVALID", "A lattice offset must be a small integer");
        }
        v.offset[k] = vertex[k + 1].get<long long>();
      }
      if (!indices.insert(v.index).second) {
        validation_failure("SIMPLEX_REPEATS_VERTEX", "A simplex uses the same point twice (not a 1-sheeted complex)");
      }
      row.push_back(v);
    }
    result.push_back(std::move(row));
  }
  return result;
}

struct Domain {
  std::vector<Q> minimum;
  Q period;
  double period_d = 0;
  std::vector<double> minimum_d;
};

Domain read_domain(const Request& request, std::size_t dimension) {
  Domain d;
  d.minimum_d = domain_min_parameter(request.parameters, dimension);
  d.period_d = positive_length(request.parameters, "period", request.inputs[1].unit);
  for (const double m : d.minimum_d) d.minimum.push_back(query_ops::exact_of(m));
  d.period = query_ops::exact_of(d.period_d);
  return d;
}

template <typename Array>
void check_points_in_domain(const std::vector<Array>& points, const Domain& d, std::size_t dimension) {
  std::set<Array> seen;
  for (const auto& p : points) {
    if (!seen.insert(p).second) validation_failure("DUPLICATE_POINT", "Input points must be pairwise distinct");
    for (std::size_t k = 0; k < dimension; ++k) {
      const Q x = query_ops::exact_of(p[k]);
      if (x < d.minimum[k] || x >= d.minimum[k] + d.period) {
        validation_failure("POINT_OUTSIDE_DOMAIN", "A point lies outside the half-open periodic domain");
      }
    }
  }
}

// Canonical key of an oriented sub-simplex modulo lattice translation: rotate (even permutation for the
// orientation-preserving rotations of a triangle; for an edge the order is the orientation) so that the smallest
// index comes first and express the offsets relative to it.
using Key = std::vector<long long>;

Key relative_key(const std::vector<PVertex>& vertices) {
  Key key;
  const auto& base = vertices.front().offset;
  for (const auto& v : vertices) {
    key.push_back(static_cast<long long>(v.index));
    for (int k = 0; k < 3; ++k) key.push_back(v.offset[k] - base[k]);
  }
  return key;
}

Key oriented_triangle_key(std::vector<PVertex> t) {
  const auto it = std::min_element(t.begin(), t.end(), [](const PVertex& a, const PVertex& b) { return a.index < b.index; });
  std::rotate(t.begin(), it, t.end());
  return relative_key(t);
}

Key undirected_edge_key(PVertex a, PVertex b) {
  if (b.index < a.index) std::swap(a, b);
  return relative_key({a, b});
}

std::vector<Q> position(const std::vector<std::vector<double>>& points, const PVertex& v, const Domain& d,
                        std::size_t dimension) {
  std::vector<Q> p;
  for (std::size_t k = 0; k < dimension; ++k) p.push_back(query_ops::exact_of(points[v.index][k]) + d.period * Q(static_cast<long>(v.offset[k])));
  return p;
}

// Circumcentre of dimension+1 affinely independent points (Cramer's rule on 2 (p_k - p_0) . x = |p_k|^2 - |p_0|^2).
std::vector<Q> circumcentre(const std::vector<std::vector<Q>>& p) {
  const std::size_t n = p.size() - 1;
  std::vector<std::vector<Q>> a(n, std::vector<Q>(n));
  std::vector<Q> rhs(n);
  for (std::size_t r = 0; r < n; ++r) {
    Q s0 = 0, s1 = 0;
    for (std::size_t k = 0; k < n; ++k) {
      a[r][k] = 2 * (p[r + 1][k] - p[0][k]);
      s1 += p[r + 1][k] * p[r + 1][k];
      s0 += p[0][k] * p[0][k];
    }
    rhs[r] = s1 - s0;
  }
  auto det = [&](const std::vector<std::vector<Q>>& m) -> Q {
    if (n == 2) return m[0][0] * m[1][1] - m[0][1] * m[1][0];
    return m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
           m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
  };
  const Q full = det(a);
  std::vector<Q> x(n);
  for (std::size_t col = 0; col < n; ++col) {
    auto m = a;
    for (std::size_t r = 0; r < n; ++r) m[r][col] = rhs[r];
    x[col] = det(m) / full;
  }
  return x;
}

Q signed_measure(const std::vector<std::vector<Q>>& p) {  // 2x area (2D) or 6x volume (3D)
  if (p.size() == 3) {
    return (p[1][0] - p[0][0]) * (p[2][1] - p[0][1]) - (p[1][1] - p[0][1]) * (p[2][0] - p[0][0]);
  }
  Vec a{p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]};
  Vec b{p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2]};
  Vec c{p[3][0] - p[0][0], p[3][1] - p[0][1], p[3][2] - p[0][2]};
  return batch2::dot(batch2::cross(a, b), c);
}

Json validate_periodic(const Request& request, std::size_t dimension) {
  const std::string validator =
      dimension == 2 ? "triangulation.validate.periodic_delaunay_2" : "triangulation.validate.periodic_delaunay_3";
  const std::string producer = dimension == 2 ? "triangulation.periodic_delaunay_2" : "triangulation.periodic_delaunay_3";
  require_parameter_names(request, {"domain_min", "period"});
  require_inputs(request, 2, validator);
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind",
                                  dimension == 2 ? "periodic_delaunay_triangulation_2" : "periodic_delaunay_triangulation_3");
  const Domain d = read_domain(request, dimension);
  std::vector<std::vector<double>> points;
  if (dimension == 2) {
    const auto raw = read_points2(request.inputs[1]);
    check_points_in_domain(raw, d, 2);
    for (const auto& p : raw) points.push_back({p[0], p[1]});
  } else {
    const auto raw = read_points3(request.inputs[1]);
    check_points_in_domain(raw, d, 3);
    for (const auto& p : raw) points.push_back({p[0], p[1], p[2]});
  }
  if (points.empty() || points.size() > kMaximumPeriodicPoints) {
    validation_failure("POINT_COUNT", "Unsupported number of input points");
  }
  Json checks = Json::object();
  checks["points_in_domain"] = true;
  const auto results = batch2::check_report_frame(report, producer, request.parameters,
                                                  {{"points_sha256", &request.inputs[1]}}, checks);
  if (require_member(results, "distance_unit", "results") != request.inputs[1].unit) {
    validation_failure("UNIT_MISMATCH", "The report distance unit differs from the point unit");
  }
  checks["distance_unit_matches_points"] = true;
  const auto simplices = read_simplices(require_member(results, dimension == 2 ? "triangles" : "tetrahedra", "results"),
                                        dimension + 1, dimension, points.size());
  std::set<std::size_t> used;
  for (const auto& s : simplices) {
    for (const auto& v : s) used.insert(v.index);
  }
  if (used.size() != points.size()) {
    validation_failure("VERTEX_SET_MISMATCH", "Every input point must be a vertex of the periodic triangulation");
  }
  checks["vertex_set_matches_source"] = true;

  // Orientation and measure.
  Q total = 0;
  std::vector<std::vector<std::vector<Q>>> positions;
  for (const auto& s : simplices) {
    std::vector<std::vector<Q>> p;
    for (const auto& v : s) p.push_back(position(points, v, d, dimension));
    const Q m = signed_measure(p);
    if (m <= 0) validation_failure("SIMPLEX_NOT_POSITIVE", "A simplex is degenerate or negatively oriented");
    total += m;
    positions.push_back(std::move(p));
  }
  checks["simplices_positively_oriented"] = true;
  Q expected = d.period * d.period * (dimension == 2 ? 2 : 6);
  if (dimension == 3) expected *= d.period;
  if (total != expected) {
    validation_failure("DOMAIN_NOT_COVERED_ONCE", "The simplices do not tile exactly one fundamental domain");
  }
  checks["covers_fundamental_domain_once"] = true;

  // Oriented facets (edges in 2D) modulo translation, each exactly once per orientation.
  std::map<Key, int> oriented;
  std::set<Key> edges;
  for (const auto& s : simplices) {
    if (dimension == 2) {
      for (int k = 0; k < 3; ++k) {
        ++oriented[relative_key({s[k], s[(k + 1) % 3]})];
      }
    } else {
      const auto &a = s[0], &b = s[1], &c = s[2], &e = s[3];
      for (const auto& facet : {std::vector<PVertex>{b, c, e}, std::vector<PVertex>{a, e, c},
                                std::vector<PVertex>{a, b, e}, std::vector<PVertex>{a, c, b}}) {
        ++oriented[oriented_triangle_key(facet)];
      }
    }
    for (std::size_t i = 0; i < s.size(); ++i) {
      for (std::size_t j = i + 1; j < s.size(); ++j) edges.insert(undirected_edge_key(s[i], s[j]));
    }
  }
  for (const auto& [key, count] : oriented) {
    Key reverse;
    if (dimension == 2) {
      // (i, 0, j, o) reversed is (j, 0, i, -o)
      reverse = {key[4], 0, 0, 0, key[0], -key[5], -key[6], -key[7]};
    } else {
      std::vector<PVertex> facet;
      for (int k = 0; k < 3; ++k) {
        facet.push_back({static_cast<std::size_t>(key[4 * k]), {key[4 * k + 1], key[4 * k + 2], key[4 * k + 3]}});
      }
      std::swap(facet[1], facet[2]);
      reverse = oriented_triangle_key(facet);
    }
    const auto other = oriented.find(reverse);
    if (count != 1 || other == oriented.end() || other->second != 1) {
      validation_failure("NOT_CLOSED_ON_TORUS", "A facet is not shared by exactly two oppositely oriented simplices");
    }
  }
  checks["closed_pseudomanifold_on_torus"] = true;
  const long long v = static_cast<long long>(points.size());
  const long long e = static_cast<long long>(edges.size());
  const long long f = static_cast<long long>(dimension == 2 ? simplices.size() : oriented.size() / 2);
  const long long t = static_cast<long long>(simplices.size());
  const long long euler = dimension == 2 ? v - e + f : v - e + f - t;
  if (euler != 0) validation_failure("EULER_MISMATCH", "The torus Euler characteristic must be 0");
  checks["torus_euler_characteristic"] = true;

  // Empty circumscribed balls against every lattice translate that can reach them.
  for (std::size_t s = 0; s < simplices.size(); ++s) {
    const auto& p = positions[s];
    const auto centre = circumcentre(p);
    Q r2 = 0;
    for (std::size_t k = 0; k < dimension; ++k) r2 += (p[0][k] - centre[k]) * (p[0][k] - centre[k]);
    // Candidate translates: a binary64 bounding-box filter with a generous margin (1e-6 relative plus 1e-9 periods)
    // selects the lattice offsets and points that can reach the ball; the decisive comparison is exact.
    const double r2_d = r2.get_d();
    const double r = std::sqrt(r2_d) * (1 + 1e-6) + 1e-9 * d.period_d;
    std::vector<double> centre_d;
    for (std::size_t k = 0; k < dimension; ++k) centre_d.push_back(centre[k].get_d());
    for (std::size_t j = 0; j < points.size(); ++j) {
      std::array<long long, 3> lo{0, 0, 0}, hi{0, 0, 0};
      for (std::size_t k = 0; k < dimension; ++k) {
        lo[k] = static_cast<long long>(std::floor((centre_d[k] - r - points[j][k]) / d.period_d));
        hi[k] = static_cast<long long>(std::ceil((centre_d[k] + r - points[j][k]) / d.period_d));
      }
      for (long long ox = lo[0]; ox <= hi[0]; ++ox) {
        for (long long oy = lo[1]; oy <= hi[1]; ++oy) {
          for (long long oz = lo[2]; oz <= hi[2]; ++oz) {
            const long long o[3] = {ox, oy, oz};
            double dd = 0;
            for (std::size_t k = 0; k < dimension; ++k) {
              const double x = points[j][k] + static_cast<double>(o[k]) * d.period_d - centre_d[k];
              dd += x * x;
            }
            if (dd > r * r) continue;
            const auto q = position(points, PVertex{j, {ox, oy, oz}}, d, dimension);
            Q dist = 0;
            for (std::size_t k = 0; k < dimension; ++k) dist += (q[k] - centre[k]) * (q[k] - centre[k]);
            if (dist < r2) {
              validation_failure("NOT_DELAUNAY", "A periodic copy of an input point lies strictly inside a circumscribed "
                                                 "ball");
            }
          }
        }
      }
    }
  }
  checks["empty_circumscribed_balls"] = true;
  return concluded(request, validator, checks,
                   {{"vertex_count", v}, {"edge_count", e}, {"facet_count", f}, {"simplex_count", t},
                    {"euler_characteristic", euler},
                    {"tolerances", "none: every predicate is exact (GMP rationals on the binary64 input)"},
                    {"independence", "exact GMP rational orientation, measure, combinatorics and circumscribed-ball "
                                     "tests over lattice translates; no CGAL header"}});
}

Json validate_periodic_2(const Request& request) { return validate_periodic(request, 2); }
Json validate_periodic_3(const Request& request) { return validate_periodic(request, 3); }

Json validate_on_sphere(const Request& request) {
  const std::string validator = "triangulation.validate.delaunay_on_sphere_2";
  require_parameter_names(request, {"center", "radius"});
  require_inputs(request, 2, validator);
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind",
                                  "delaunay_triangulation_on_sphere_2");
  const V3 centre_d = query_ops::vector_parameter(request, "center");
  const double radius = positive_length(request.parameters, "radius", request.inputs[1].unit);
  const auto points = read_points3(request.inputs[1]);
  if (points.size() < 4 || points.size() > kMaximumSpherePoints) {
    validation_failure("POINT_COUNT", "Unsupported number of input points");
  }
  Json checks = Json::object();
  const auto results = batch2::check_report_frame(report, "triangulation.delaunay_on_sphere_2", request.parameters,
                                                  {{"points_sha256", &request.inputs[1]}}, checks);
  if (require_member(results, "distance_unit", "results") != request.inputs[1].unit) {
    validation_failure("UNIT_MISMATCH", "The report distance unit differs from the point unit");
  }
  checks["distance_unit_matches_points"] = true;
  const Vec centre = batch2::vec(centre_d);
  std::vector<Vec> p;
  const Q r2 = query_ops::exact_of(radius) * query_ops::exact_of(radius);
  double worst = 0;
  std::set<V3> seen;
  for (const auto& raw : points) {
    if (!seen.insert(raw).second) validation_failure("DUPLICATE_POINT", "Input points must be pairwise distinct");
    p.push_back(batch2::vec(raw));
    const Vec d = p.back() - centre;
    const Q deviation = (batch2::dot(d, d) - r2) / r2;
    const double relative = std::fabs(deviation.get_d());
    worst = std::max(worst, relative);
    if (relative > kSphereRadiusTolerance) {
      validation_failure("POINT_NOT_ON_SPHERE", "A point is farther than the declared tolerance from the sphere");
    }
  }
  checks["points_on_declared_sphere"] = true;
  const auto& rows = require_member(results, "triangles", "results");
  if (!rows.is_array() || rows.empty()) validation_failure("REPORT_VALUE_INVALID", "No triangles are reported");
  std::vector<std::array<std::size_t, 3>> faces;
  std::set<std::size_t> used;
  for (const auto& row : rows) {
    if (!row.is_array() || row.size() != 3) validation_failure("REPORT_VALUE_INVALID", "A triangle must have 3 indices");
    std::array<std::size_t, 3> t{};
    for (int k = 0; k < 3; ++k) {
      t[k] = batch2::index_of(row[k], points.size(), "triangle vertex");
      used.insert(t[k]);
    }
    if (t[0] == t[1] || t[1] == t[2] || t[0] == t[2]) validation_failure("REPORT_VALUE_INVALID", "A triangle repeats a vertex");
    faces.push_back(t);
  }
  if (used.size() != points.size()) {
    validation_failure("VERTEX_SET_MISMATCH", "Every input point must be a vertex of the triangulation");
  }
  checks["vertex_set_matches_source"] = true;
  for (const auto& t : faces) {
    if (batch2::dot(batch2::cross(p[t[1]] - p[t[0]], p[t[2]] - p[t[0]]), centre - p[t[0]]) >= 0) {
      validation_failure("FACE_NOT_OUTWARD", "A face is not counter-clockwise seen from outside the sphere");
    }
  }
  checks["faces_oriented_outward"] = true;
  std::map<std::pair<std::size_t, std::size_t>, int> directed;
  for (const auto& t : faces) {
    for (int k = 0; k < 3; ++k) ++directed[{t[k], t[(k + 1) % 3]}];
  }
  for (const auto& [edge, count] : directed) {
    const auto other = directed.find({edge.second, edge.first});
    if (count != 1 || other == directed.end() || other->second != 1) {
      validation_failure("NOT_CLOSED_SURFACE", "An edge is not shared by exactly two oppositely oriented faces");
    }
  }
  checks["closed_oriented_surface"] = true;
  const long long v = static_cast<long long>(points.size());
  const long long e = static_cast<long long>(directed.size() / 2);
  const long long f = static_cast<long long>(faces.size());
  if (v - e + f != 2) validation_failure("EULER_MISMATCH", "The sphere Euler characteristic must be 2");
  checks["sphere_euler_characteristic"] = true;
  for (const auto& t : faces) {
    const Vec n = batch2::cross(p[t[1]] - p[t[0]], p[t[2]] - p[t[0]]);
    for (std::size_t s = 0; s < p.size(); ++s) {
      if (batch2::dot(n, p[s] - p[t[0]]) > 0) {
        validation_failure("NOT_DELAUNAY", "A point lies strictly inside the circumcircle (on the cap) of a face");
      }
    }
  }
  checks["empty_circles_on_sphere"] = true;
  return concluded(request, validator, checks,
                   {{"vertex_count", v}, {"edge_count", e}, {"triangle_count", f}, {"euler_characteristic", v - e + f},
                    {"maximum_relative_squared_radius_deviation", worst},
                    {"tolerances", "|(|p - c|^2 - R^2) / R^2| <= 1e-9 for every point; every other predicate is exact"},
                    {"independence", "exact GMP rational orientation_3 against the declared centre and every point; "
                                     "no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> triangulation_validators() {
  using query_ops::query_definition;
  const std::string independence =
      "exact GMP rational orientation, measure, combinatorics and circumscribed-ball tests; no CGAL header";
  const std::vector<std::string> periodic_checks{
      "points_in_domain", "parameters_match", "source_matches", "distance_unit_matches_points",
      "vertex_set_matches_source", "simplices_positively_oriented", "covers_fundamental_domain_once",
      "closed_pseudomanifold_on_torus", "torus_euler_characteristic", "empty_circumscribed_balls"};
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "triangulation.validate.periodic_delaunay_2", {"GeometryQueryReport", "PointSet2"}, "ValidationReport",
      "validator", validate_periodic_2, {"Periodic_2_triangulation_2"}, "GMP rationals (no CGAL header)",
      vinfo(periodic_checks, {"candidate", "points"}, independence)));
  result.push_back(query_definition(
      "triangulation.validate.periodic_delaunay_3", {"GeometryQueryReport", "PointSet3"}, "ValidationReport",
      "validator", validate_periodic_3, {"Periodic_3_triangulation_3"}, "GMP rationals (no CGAL header)",
      vinfo(periodic_checks, {"candidate", "points"}, independence)));
  result.push_back(query_definition(
      "triangulation.validate.delaunay_on_sphere_2", {"GeometryQueryReport", "PointSet3"}, "ValidationReport",
      "validator", validate_on_sphere, {"Triangulation_on_sphere_2"}, "GMP rationals (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "distance_unit_matches_points", "points_on_declared_sphere",
             "vertex_set_matches_source", "faces_oriented_outward", "closed_oriented_surface",
             "sphere_euler_characteristic", "empty_circles_on_sphere"},
            {"candidate", "points"}, independence)));
  return result;
}

}  // namespace cgal_master::batch9
