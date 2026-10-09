// Independent validators for weighted (regular) triangulations (7.11.03) and Voronoi diagrams (7.11.05).
// No CGAL header is included. Everything is evaluated with GMP rationals on the raw binary64 input:
//   * regular triangulations: lifting p -> (p, |p|^2 - w); a reported simplex must be a lower-hull
//     face (every other visible vertex above or on its lifted hyperplane), the simplices must tile the
//     convex hull of the visible vertices (shared faces matched with opposite orientation, boundary
//     faces supporting the visible points, exact volume equal to the hull volume) and every hidden
//     weighted point must lie strictly above the lifted triangulation;
//   * Voronoi diagram: every Voronoi edge of every site pair is recomputed as the exact parameter
//     interval of the bisector on which no third site is closer.

#include "b3_common.h"

#include <algorithm>
#include <map>
#include <set>
#include <tuple>

namespace cgal_master::batch3 {
namespace {

using batch2::concluded;
using batch2::index_of;
using batch2::require_member;
using batch2::vinfo;
using query_ops::exact_of;
using query_ops::read_points2;
using query_ops::read_points3;
using query_ops::read_report;
using query_ops::reported_rational;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;

std::vector<Q> exact_weights(const Request& request, std::size_t count) {
  std::vector<Q> result;
  for (const double w : weights_parameter(request, count)) result.push_back(exact_of(w));
  return result;
}

std::vector<std::size_t> index_list(const Json& value, std::size_t bound, const std::string& context) {
  if (!value.is_array()) validation_failure("REPORT_VALUE_INVALID", context + " must be an array");
  std::vector<std::size_t> result;
  for (const auto& item : value) result.push_back(index_of(item, bound, context));
  return result;
}

// ---- 2D ------------------------------------------------------------------------------------------

struct P2 {
  Q x, y;
};
Q orient2(const P2& a, const P2& b, const P2& c) { return (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x); }

Q hull_twice_area(std::vector<P2> p) {
  std::sort(p.begin(), p.end(), [](const P2& a, const P2& b) { return a.x != b.x ? a.x < b.x : a.y < b.y; });
  std::vector<P2> h(2 * p.size());
  std::size_t k = 0;
  for (std::size_t i = 0; i < p.size(); ++i) {
    while (k >= 2 && orient2(h[k - 2], h[k - 1], p[i]) <= 0) --k;
    h[k++] = p[i];
  }
  for (std::size_t i = p.size() - 1, t = k + 1; i > 0; --i) {
    while (k >= t && orient2(h[k - 2], h[k - 1], p[i - 1]) <= 0) --k;
    h[k++] = p[i - 1];
  }
  h.resize(k - 1);
  Q total = 0;
  for (std::size_t i = 0; i < h.size(); ++i) {
    const P2 &a = h[i], &b = h[(i + 1) % h.size()];
    total += a.x * b.y - a.y * b.x;
  }
  return total;
}

// det > 0: d lies above the lifted plane of the counter-clockwise triangle (a,b,c); det < 0: conflict.
Q power_det_2(const P2& a, const P2& b, const P2& c, const P2& d, const Q& wa, const Q& wb, const Q& wc,
              const Q& wd) {
  const Q la = a.x * a.x + a.y * a.y - wa;
  auto row = [&](const P2& p, const Q& w) {
    return std::vector<Q>{p.x - a.x, p.y - a.y, p.x * p.x + p.y * p.y - w - la};
  };
  return determinant({row(b, wb), row(c, wc), row(d, wd)});
}

Json run_regular_2_validator(const Request& request) {
  const std::string validator = "triangulation.validate.regular_2";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"weights"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "regular_triangulation_2");
  const auto raw = read_points2(request.inputs[1]);
  const std::size_t n = raw.size();
  if (n < 3 || n > kMaximumWeightedPoints) validation_failure("POINT_COUNT", "Between 3 and 400 points are supported");
  const auto w = exact_weights(request, n);
  std::vector<P2> p;
  for (const auto& v : raw) p.push_back({exact_of(v[0]), exact_of(v[1])});
  for (std::size_t i = 0; i < n; ++i)
    for (std::size_t j = i + 1; j < n; ++j)
      if (p[i].x == p[j].x && p[i].y == p[j].y) validation_failure("DUPLICATE_POINT", "Source points must be distinct");
  Json checks;
  const auto results = batch2::check_report_frame(report, "triangulation.regular_2", Json{{"weights", request.parameters.at("weights")}},
                                                  {{"points_sha256", &request.inputs[1]}}, checks);
  const auto vertices = index_list(require_member(results, "vertices", "results"), n, "vertices");
  const auto hidden = index_list(require_member(results, "hidden", "results"), n, "hidden");
  std::set<std::size_t> visible(vertices.begin(), vertices.end());
  std::set<std::size_t> hidden_set(hidden.begin(), hidden.end());
  if (visible.size() != vertices.size() || hidden_set.size() != hidden.size() || visible.size() + hidden_set.size() != n) {
    validation_failure("VERTEX_PARTITION_MISMATCH", "Vertices and hidden points must partition the input");
  }
  for (const auto i : visible) {
    if (hidden_set.count(i)) validation_failure("VERTEX_PARTITION_MISMATCH", "A point is both vertex and hidden");
  }
  checks["vertices_and_hidden_partition_input"] = true;

  const auto& triangle_json = require_member(results, "triangles", "results");
  if (!triangle_json.is_array() || triangle_json.empty()) validation_failure("REPORT_VALUE_INVALID", "triangles must be a nonempty array");
  std::vector<std::array<std::size_t, 3>> triangles;
  std::map<std::pair<std::size_t, std::size_t>, int> directed;
  std::set<std::array<std::size_t, 3>> seen;
  Q area2 = 0;
  std::set<std::size_t> used;
  for (const auto& item : triangle_json) {
    const auto ids = index_list(item, n, "triangle");
    if (ids.size() != 3) validation_failure("REPORT_VALUE_INVALID", "A triangle needs three vertices");
    std::array<std::size_t, 3> t{ids[0], ids[1], ids[2]};
    for (const auto v : t) {
      if (!visible.count(v)) validation_failure("TRIANGLE_VERTEX_HIDDEN", "A triangle uses a hidden or unknown vertex");
      used.insert(v);
    }
    std::array<std::size_t, 3> key = t;
    std::sort(key.begin(), key.end());
    if (key[0] == key[1] || key[1] == key[2] || !seen.insert(key).second) {
      validation_failure("TRIANGLE_DUPLICATE", "A triangle repeats a vertex or occurs twice");
    }
    const Q o = orient2(p[t[0]], p[t[1]], p[t[2]]);
    if (o <= 0) validation_failure("TRIANGLE_NOT_COUNTER_CLOCKWISE", "A triangle is degenerate or clockwise");
    area2 += o;
    for (int e = 0; e < 3; ++e) {
      if (++directed[{t[e], t[(e + 1) % 3]}] > 1) validation_failure("TRIANGLES_OVERLAP", "A directed edge is used twice");
    }
    triangles.push_back(t);
  }
  if (used != visible) validation_failure("VERTEX_NOT_USED", "A reported vertex belongs to no triangle");
  checks["triangles_counter_clockwise_distinct"] = true;

  // Regularity: no visible vertex lies below the lifted plane of any triangle.
  for (const auto& t : triangles) {
    for (const auto v : visible) {
      if (v == t[0] || v == t[1] || v == t[2]) continue;
      if (power_det_2(p[t[0]], p[t[1]], p[t[2]], p[v], w[t[0]], w[t[1]], w[t[2]], w[v]) < 0) {
        validation_failure("NOT_REGULAR", "A vertex lies inside the weighted circle of a triangle");
      }
    }
  }
  checks["every_triangle_is_regular"] = true;

  // Tiling: interior edges are shared with the opposite direction, boundary edges form the hull,
  // and the exact area equals the area of the convex hull of the visible vertices.
  std::vector<P2> visible_points;
  for (const auto v : visible) visible_points.push_back(p[v]);
  if (area2 != hull_twice_area(visible_points)) {
    validation_failure("TRIANGLES_DO_NOT_TILE_HULL", "The triangle areas differ from the hull area of the vertices");
  }
  for (const auto& [edge, count] : directed) {
    const auto reverse = directed.find({edge.second, edge.first});
    if (reverse == directed.end()) {
      for (const auto v : visible) {
        if (v != edge.first && v != edge.second && orient2(p[edge.first], p[edge.second], p[v]) < 0) {
          validation_failure("BOUNDARY_EDGE_NOT_HULL_EDGE", "A boundary edge does not support all vertices");
        }
      }
    }
  }
  checks["triangles_tile_convex_hull_of_vertices"] = true;

  // Hidden points: inside a triangle and strictly above its lifted plane.
  for (const auto h : hidden_set) {
    bool dominated = false;
    for (const auto& t : triangles) {
      if (orient2(p[t[0]], p[t[1]], p[h]) >= 0 && orient2(p[t[1]], p[t[2]], p[h]) >= 0 &&
          orient2(p[t[2]], p[t[0]], p[h]) >= 0 &&
          power_det_2(p[t[0]], p[t[1]], p[t[2]], p[h], w[t[0]], w[t[1]], w[t[2]], w[h]) > 0) {
        dominated = true;
        break;
      }
    }
    if (!dominated) validation_failure("HIDDEN_POINT_NOT_DOMINATED", "A hidden point is not strictly above the regular triangulation");
  }
  checks["hidden_points_are_dominated"] = true;
  return concluded(request, validator, checks,
                   {{"vertex_count", visible.size()}, {"hidden_count", hidden_set.size()},
                    {"triangle_count", triangles.size()},
                    {"independence", "exact rational lifting, orientation and hull-area tiling; no CGAL header"}});
}

// ---- 3D ------------------------------------------------------------------------------------------

struct P3 {
  Q x, y, z;
};
Q orient3(const P3& a, const P3& b, const P3& c, const P3& d) {
  return determinant({{b.x - a.x, b.y - a.y, b.z - a.z}, {c.x - a.x, c.y - a.y, c.z - a.z},
                      {d.x - a.x, d.y - a.y, d.z - a.z}});
}
Q power_det_3(const std::array<const P3*, 4>& s, const std::array<const Q*, 4>& ws, const P3& e, const Q& we) {
  const P3& a = *s[0];
  auto lift = [](const P3& q, const Q& weight) -> Q { return q.x * q.x + q.y * q.y + q.z * q.z - weight; };
  const Q la = lift(a, *ws[0]);
  std::vector<std::vector<Q>> m;
  for (int k = 1; k < 4; ++k) {
    m.push_back({s[k]->x - a.x, s[k]->y - a.y, s[k]->z - a.z, lift(*s[k], *ws[k]) - la});
  }
  m.push_back({e.x - a.x, e.y - a.y, e.z - a.z, lift(e, we) - la});
  return determinant(m);
}

using Face3 = std::array<std::size_t, 3>;
Face3 canon(Face3 f) {
  std::rotate(f.begin(), std::min_element(f.begin(), f.end()), f.end());
  return f;
}

Json run_regular_3_validator(const Request& request) {
  const std::string validator = "triangulation.validate.regular_3";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"weights"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "regular_triangulation_3");
  const auto raw = read_points3(request.inputs[1]);
  const std::size_t n = raw.size();
  if (n < 4 || n > kMaximumWeightedPoints) validation_failure("POINT_COUNT", "Between 4 and 400 points are supported");
  const auto w = exact_weights(request, n);
  std::vector<P3> p;
  for (const auto& v : raw) p.push_back({exact_of(v[0]), exact_of(v[1]), exact_of(v[2])});
  for (std::size_t i = 0; i < n; ++i)
    for (std::size_t j = i + 1; j < n; ++j)
      if (p[i].x == p[j].x && p[i].y == p[j].y && p[i].z == p[j].z) {
        validation_failure("DUPLICATE_POINT", "Source points must be distinct");
      }
  Json checks;
  const auto results = batch2::check_report_frame(report, "triangulation.regular_3", Json{{"weights", request.parameters.at("weights")}},
                                                  {{"points_sha256", &request.inputs[1]}}, checks);
  const auto vertices = index_list(require_member(results, "vertices", "results"), n, "vertices");
  const auto hidden = index_list(require_member(results, "hidden", "results"), n, "hidden");
  std::set<std::size_t> visible(vertices.begin(), vertices.end());
  std::set<std::size_t> hidden_set(hidden.begin(), hidden.end());
  if (visible.size() != vertices.size() || hidden_set.size() != hidden.size() || visible.size() + hidden_set.size() != n) {
    validation_failure("VERTEX_PARTITION_MISMATCH", "Vertices and hidden points must partition the input");
  }
  for (const auto i : visible) {
    if (hidden_set.count(i)) validation_failure("VERTEX_PARTITION_MISMATCH", "A point is both vertex and hidden");
  }
  checks["vertices_and_hidden_partition_input"] = true;

  const auto& cell_json = require_member(results, "tetrahedra", "results");
  if (!cell_json.is_array() || cell_json.empty()) validation_failure("REPORT_VALUE_INVALID", "tetrahedra must be a nonempty array");
  std::vector<std::array<std::size_t, 4>> cells;
  std::set<std::array<std::size_t, 4>> seen;
  std::set<std::size_t> used;
  std::map<Face3, int> directed;  // outward-oriented faces
  Q volume6 = 0;
  for (const auto& item : cell_json) {
    const auto ids = index_list(item, n, "tetrahedron");
    if (ids.size() != 4) validation_failure("REPORT_VALUE_INVALID", "A tetrahedron needs four vertices");
    std::array<std::size_t, 4> t{ids[0], ids[1], ids[2], ids[3]};
    for (const auto v : t) {
      if (!visible.count(v)) validation_failure("CELL_VERTEX_HIDDEN", "A tetrahedron uses a hidden or unknown vertex");
      used.insert(v);
    }
    auto key = t;
    std::sort(key.begin(), key.end());
    if (key[0] == key[1] || key[1] == key[2] || key[2] == key[3] || !seen.insert(key).second) {
      validation_failure("CELL_DUPLICATE", "A tetrahedron repeats a vertex or occurs twice");
    }
    const Q o = orient3(p[t[0]], p[t[1]], p[t[2]], p[t[3]]);
    if (o <= 0) validation_failure("CELL_NOT_POSITIVE", "A tetrahedron is degenerate or negatively oriented");
    volume6 += o;
    const Face3 faces[4] = {{t[1], t[2], t[3]}, {t[0], t[2], t[1]}, {t[0], t[1], t[3]}, {t[0], t[3], t[2]}};
    for (const auto& f : faces) {
      if (++directed[canon(f)] > 1) validation_failure("CELLS_OVERLAP", "An oriented face is used by two tetrahedra");
    }
    cells.push_back(t);
  }
  if (used != visible) validation_failure("VERTEX_NOT_USED", "A reported vertex belongs to no tetrahedron");
  checks["tetrahedra_positive_distinct"] = true;

  for (const auto& t : cells) {
    const std::array<const P3*, 4> s{&p[t[0]], &p[t[1]], &p[t[2]], &p[t[3]]};
    const std::array<const Q*, 4> ws{&w[t[0]], &w[t[1]], &w[t[2]], &w[t[3]]};
    for (const auto v : visible) {
      if (v == t[0] || v == t[1] || v == t[2] || v == t[3]) continue;
      if (power_det_3(s, ws, p[v], w[v]) < 0) {
        validation_failure("NOT_REGULAR", "A vertex lies inside the weighted sphere of a tetrahedron");
      }
    }
  }
  checks["every_tetrahedron_is_regular"] = true;

  // Boundary faces (no opposite partner) must support all visible vertices, close up, and enclose
  // exactly the summed tetrahedron volume.
  Q boundary6 = 0;
  std::map<std::pair<std::size_t, std::size_t>, int> boundary_edges;
  for (const auto& [face, count] : directed) {
    if (directed.count(canon({face[0], face[2], face[1]}))) continue;
    for (const auto v : visible) {
      if (v == face[0] || v == face[1] || v == face[2]) continue;
      if (orient3(p[face[0]], p[face[1]], p[face[2]], p[v]) > 0) {
        validation_failure("BOUNDARY_FACE_NOT_HULL_FACE", "A boundary face does not support all vertices");
      }
    }
    const P3 &a = p[face[0]], &b = p[face[1]], &c = p[face[2]];
    boundary6 += a.x * (b.y * c.z - b.z * c.y) - a.y * (b.x * c.z - b.z * c.x) + a.z * (b.x * c.y - b.y * c.x);
    for (int e = 0; e < 3; ++e) ++boundary_edges[{face[e], face[(e + 1) % 3]}];
  }
  for (const auto& [edge, count] : boundary_edges) {
    const auto reverse = boundary_edges.find({edge.second, edge.first});
    if (count != 1 || reverse == boundary_edges.end() || reverse->second != 1) {
      validation_failure("BOUNDARY_NOT_CLOSED", "The boundary faces do not form a closed oriented surface");
    }
  }
  if (boundary6 != volume6) {
    validation_failure("CELLS_DO_NOT_FILL_HULL", "The tetrahedron volumes differ from the volume bounded by the hull faces");
  }
  checks["tetrahedra_tile_convex_hull_of_vertices"] = true;

  for (const auto h : hidden_set) {
    bool dominated = false;
    for (const auto& t : cells) {
      const P3 &a = p[t[0]], &b = p[t[1]], &c = p[t[2]], &d = p[t[3]];
      if (orient3(p[h], b, c, d) >= 0 && orient3(a, p[h], c, d) >= 0 && orient3(a, b, p[h], d) >= 0 &&
          orient3(a, b, c, p[h]) >= 0) {
        const std::array<const P3*, 4> s{&a, &b, &c, &d};
        const std::array<const Q*, 4> ws{&w[t[0]], &w[t[1]], &w[t[2]], &w[t[3]]};
        if (power_det_3(s, ws, p[h], w[h]) > 0) {
          dominated = true;
          break;
        }
      }
    }
    if (!dominated) validation_failure("HIDDEN_POINT_NOT_DOMINATED", "A hidden point is not strictly above the regular triangulation");
  }
  checks["hidden_points_are_dominated"] = true;
  return concluded(request, validator, checks,
                   {{"vertex_count", visible.size()}, {"hidden_count", hidden_set.size()},
                    {"tetrahedron_count", cells.size()},
                    {"independence", "exact rational lifting, orientation, boundary-surface volume tiling; no CGAL header"}});
}

// ---- Voronoi -------------------------------------------------------------------------------------

using VertexKey = std::pair<Q, Q>;
using EdgeKey = std::tuple<std::size_t, std::size_t, int, Q, Q, int, Q, Q>;

Json run_voronoi_validator(const Request& request) {
  const std::string validator = "triangulation.validate.voronoi_dual";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "voronoi_diagram_2");
  const auto raw = read_points2(request.inputs[1]);
  const std::size_t n = raw.size();
  if (n < 3 || n > kMaximumWeightedPoints) validation_failure("POINT_COUNT", "Between 3 and 400 sites are supported");
  std::vector<P2> p;
  for (const auto& v : raw) p.push_back({exact_of(v[0]), exact_of(v[1])});
  for (std::size_t i = 0; i < n; ++i)
    for (std::size_t j = i + 1; j < n; ++j)
      if (p[i].x == p[j].x && p[i].y == p[j].y) validation_failure("DUPLICATE_POINT", "Sites must be distinct");
  bool rank_two = false;
  for (std::size_t i = 2; i < n; ++i) rank_two = rank_two || orient2(p[0], p[1], p[i]) != 0;
  if (!rank_two) validation_failure("ALL_COLLINEAR", "The sites must not all be collinear");
  Json checks;
  const auto results = batch2::check_report_frame(report, "triangulation.voronoi_dual", Json::object(),
                                                  {{"sites_sha256", &request.inputs[1]}}, checks);

  // Exact expectation: for every site pair, the bisector interval where no third site is closer.
  std::set<EdgeKey> expected;
  std::set<VertexKey> expected_vertices;
  std::set<std::size_t> expected_unbounded;
  for (std::size_t i = 0; i < n; ++i) {
    for (std::size_t j = i + 1; j < n; ++j) {
      const P2 m{(p[i].x + p[j].x) / 2, (p[i].y + p[j].y) / 2};
      const P2 d{-(p[j].y - p[i].y), p[j].x - p[i].x};
      bool has_lo = false, has_hi = false, empty = false;
      Q lo = 0, hi = 0;
      for (std::size_t u = 0; u < n && !empty; ++u) {
        if (u == i || u == j) continue;
        const P2 delta{p[u].x - p[i].x, p[u].y - p[i].y};
        const Q a = 2 * (d.x * delta.x + d.y * delta.y);
        const Q b = (p[u].x * p[u].x + p[u].y * p[u].y) - (p[i].x * p[i].x + p[i].y * p[i].y) -
                    2 * (m.x * delta.x + m.y * delta.y);
        if (a == 0) {
          if (b < 0) empty = true;
        } else if (a > 0) {
          const Q bound = b / a;  // tau <= bound
          if (!has_hi || bound < hi) hi = bound;
          has_hi = true;
        } else {
          const Q bound = b / a;  // tau >= bound
          if (!has_lo || bound > lo) lo = bound;
          has_lo = true;
        }
      }
      if (empty || (has_lo && has_hi && !(lo < hi))) continue;
      const auto at = [&](const Q& tau) { return VertexKey{m.x + tau * d.x, m.y + tau * d.y}; };
      const VertexKey lo_point = has_lo ? at(lo) : VertexKey{0, 0};
      const VertexKey hi_point = has_hi ? at(hi) : VertexKey{0, 0};
      if (has_lo) expected_vertices.insert(lo_point);
      if (has_hi) expected_vertices.insert(hi_point);
      if (!has_lo || !has_hi) {
        expected_unbounded.insert(i);
        expected_unbounded.insert(j);
      }
      expected.insert({i, j, has_lo ? 1 : 0, lo_point.first, lo_point.second, has_hi ? 1 : 0, hi_point.first,
                       hi_point.second});
    }
  }

  const auto& vertex_json = require_member(results, "vertices", "results");
  if (!vertex_json.is_array()) validation_failure("REPORT_VALUE_INVALID", "vertices must be an array");
  std::vector<VertexKey> vertices;
  for (const auto& item : vertex_json) {
    if (!item.is_array() || item.size() != 2) validation_failure("REPORT_VALUE_INVALID", "A vertex must be [x,y]");
    vertices.push_back({reported_rational(item[0], "vertex"), reported_rational(item[1], "vertex")});
  }
  if (!std::is_sorted(vertices.begin(), vertices.end()) ||
      std::adjacent_find(vertices.begin(), vertices.end()) != vertices.end()) {
    validation_failure("VERTEX_ORDER", "Voronoi vertices must be strictly increasing in (x,y)");
  }
  if (std::set<VertexKey>(vertices.begin(), vertices.end()) != expected_vertices) {
    validation_failure("VORONOI_VERTICES_MISMATCH", "The reported Voronoi vertices differ from the exact vertices");
  }
  checks["voronoi_vertices_equal_exact_bisector_endpoints"] = true;

  const auto& edge_json = require_member(results, "edges", "results");
  if (!edge_json.is_array()) validation_failure("REPORT_VALUE_INVALID", "edges must be an array");
  std::set<EdgeKey> reported;
  for (const auto& item : edge_json) {
    const auto sites = index_list(require_member(item, "sites", "edge"), n, "edge sites");
    if (sites.size() != 2 || sites[0] >= sites[1]) validation_failure("REPORT_VALUE_INVALID", "edge sites must be [i,j] with i<j");
    auto end = [&](const char* key, int& flag, Q& x, Q& y) {
      const auto& value = require_member(item, key, "edge");
      flag = 0;
      x = 0;
      y = 0;
      if (value.is_null()) return;
      const std::size_t id = index_of(value, vertices.size(), key);
      flag = 1;
      x = vertices[id].first;
      y = vertices[id].second;
    };
    int lo_flag, hi_flag;
    Q lx, ly, hx, hy;
    end("lo", lo_flag, lx, ly);
    end("hi", hi_flag, hx, hy);
    if (!reported.insert({sites[0], sites[1], lo_flag, lx, ly, hi_flag, hx, hy}).second) {
      validation_failure("EDGE_DUPLICATE", "A Voronoi edge is reported twice");
    }
  }
  if (reported != expected) {
    validation_failure("VORONOI_EDGES_MISMATCH", "The reported Voronoi edges differ from the exact bisector intervals");
  }
  checks["voronoi_edges_equal_exact_bisector_intervals"] = true;

  const auto cell_count = require_member(results, "cell_count", "results");
  const auto unbounded_count = require_member(results, "unbounded_cell_count", "results");
  if (!cell_count.is_number_integer() || cell_count.get<long long>() != static_cast<long long>(n)) {
    validation_failure("CELL_COUNT_MISMATCH", "There must be one Voronoi cell per site");
  }
  if (!unbounded_count.is_number_integer() ||
      unbounded_count.get<long long>() != static_cast<long long>(expected_unbounded.size())) {
    validation_failure("UNBOUNDED_CELL_COUNT_MISMATCH", "The unbounded cell count differs from the exact one");
  }
  checks["cell_counts_match_exact_edges"] = true;
  return concluded(request, validator, checks,
                   {{"site_count", n}, {"edge_count", expected.size()}, {"vertex_count", expected_vertices.size()},
                    {"unbounded_cell_count", expected_unbounded.size()},
                    {"independence", "exact bisector intervals against all other sites in GMP rationals; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> triangulation_validators() {
  using query_ops::query_definition;
  const std::string gmp = "exact:GMP";
  const std::string note2 = "exact rational lifting, orientation and hull-area tiling; no CGAL header";
  const std::string note3 = "exact rational lifting, orientation, boundary-surface volume tiling; no CGAL header";
  const std::string noteV = "exact bisector intervals against all other sites in GMP rationals; no CGAL header";
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "triangulation.validate.regular_2", {"GeometryQueryReport", "PointSet2"}, "ValidationReport", "validator",
      run_regular_2_validator, {"Triangulation_2"}, gmp,
      vinfo({"parameters_match", "source_matches", "vertices_and_hidden_partition_input",
             "triangles_counter_clockwise_distinct", "every_triangle_is_regular",
             "triangles_tile_convex_hull_of_vertices", "hidden_points_are_dominated"},
            {"candidate", "points"}, note2)));
  result.push_back(query_definition(
      "triangulation.validate.regular_3", {"GeometryQueryReport", "PointSet3"}, "ValidationReport", "validator",
      run_regular_3_validator, {"Triangulation_3"}, gmp,
      vinfo({"parameters_match", "source_matches", "vertices_and_hidden_partition_input",
             "tetrahedra_positive_distinct", "every_tetrahedron_is_regular",
             "tetrahedra_tile_convex_hull_of_vertices", "hidden_points_are_dominated"},
            {"candidate", "points"}, note3)));
  result.push_back(query_definition(
      "triangulation.validate.voronoi_dual", {"GeometryQueryReport", "PointSet2"}, "ValidationReport", "validator",
      run_voronoi_validator, {"Voronoi_diagram_2", "Triangulation_2"}, gmp,
      vinfo({"parameters_match", "source_matches", "voronoi_vertices_equal_exact_bisector_endpoints",
             "voronoi_edges_equal_exact_bisector_intervals", "cell_counts_match_exact_edges"},
            {"candidate", "sites"}, noteV)));
  return result;
}

}  // namespace cgal_master::batch3
