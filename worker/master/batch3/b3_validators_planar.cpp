// Independent validators for the planar operations of batch 3: Minkowski sums (7.12.07), arrangements
// and zones (7.12.02) and face overlays (7.12.03). No CGAL header is included. Everything is derived
// with GMP rationals from the raw binary64 input:
//   * the arrangement of a segment set is rebuilt by splitting every segment at all intersection
//     points, its faces are traced with an exact angular order (next halfedge = first clockwise
//     neighbour) and component boundaries are nested by exact point-in-cycle tests;
//   * a zone is recomputed by splitting the query segment at all arrangement vertices and edge
//     crossings and locating every piece in the traced faces;
//   * an overlay is the arrangement of both polygon boundaries; every bounded face is labelled with
//     the number of polygons containing an interior witness point (exact point-in-polygon);
//   * the Minkowski sum boundary is a subset of the translated edges (edge of P + vertex of Q and
//     vice versa); every piece obtained by splitting them is kept exactly when point membership
//     in P + Q (exists a in P with q - a in Q, exact region intersection) differs on its two sides.

#include "b3_common.h"

#include "../wave_c/wave_c_common.h"

#include <algorithm>
#include <functional>
#include <map>
#include <set>

namespace cgal_master::batch3 {
namespace {

using batch2::concluded;
using batch2::require_member;
using batch2::vinfo;
using query_ops::exact_of;
using query_ops::read_polygon;
using query_ops::read_report;
using query_ops::reported_rational;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::validation_failure;

struct P2 {
  Q x, y;
};
bool operator==(const P2& a, const P2& b) { return a.x == b.x && a.y == b.y; }
bool operator!=(const P2& a, const P2& b) { return !(a == b); }
bool operator<(const P2& a, const P2& b) { return a.x != b.x ? a.x < b.x : a.y < b.y; }
P2 sub(const P2& a, const P2& b) { return {a.x - b.x, a.y - b.y}; }
P2 add(const P2& a, const P2& b) { return {a.x + b.x, a.y + b.y}; }
Q cross2(const P2& a, const P2& b) { return a.x * b.y - a.y * b.x; }
Q dot2(const P2& a, const P2& b) { return a.x * b.x + a.y * b.y; }
int sign_of(const Q& v) { return v > 0 ? 1 : (v < 0 ? -1 : 0); }

bool on_segment(const P2& p, const P2& a, const P2& b) {
  if (cross2(sub(b, a), sub(p, a)) != 0) return false;
  const Q s = dot2(sub(p, a), sub(b, a));
  return s >= 0 && s <= dot2(sub(b, a), sub(b, a));
}

bool segments_touch(const P2& a, const P2& b, const P2& c, const P2& d) {
  const int o1 = sign_of(cross2(sub(b, a), sub(c, a))), o2 = sign_of(cross2(sub(b, a), sub(d, a)));
  const int o3 = sign_of(cross2(sub(d, c), sub(a, c))), o4 = sign_of(cross2(sub(d, c), sub(b, c)));
  if (o1 != o2 && o3 != o4 && o1 * o2 <= 0 && o3 * o4 <= 0) return true;
  return (o1 == 0 && on_segment(c, a, b)) || (o2 == 0 && on_segment(d, a, b)) ||
         (o3 == 0 && on_segment(a, c, d)) || (o4 == 0 && on_segment(b, c, d));
}

using Ring = std::vector<P2>;

Q twice_area(const Ring& ring) {
  Q total = 0;
  for (std::size_t i = 0; i < ring.size(); ++i) total += cross2(ring[i], ring[(i + 1) % ring.size()]);
  return total;
}

// Ray-casting parity; the caller guarantees that p is not on the boundary.
bool parity_inside(const Ring& ring, const P2& p) {
  bool inside = false;
  const std::size_t n = ring.size();
  for (std::size_t i = 0; i < n; ++i) {
    const P2 &a = ring[i], &b = ring[(i + 1) % n];
    if ((a.y > p.y) != (b.y > p.y)) {
      const Q x = a.x + (p.y - a.y) * (b.x - a.x) / (b.y - a.y);
      if (p.x < x) inside = !inside;
    }
  }
  return inside;
}

bool inside_closed(const Ring& ring, const P2& p) {
  const std::size_t n = ring.size();
  for (std::size_t i = 0; i < n; ++i) {
    if (on_segment(p, ring[i], ring[(i + 1) % n])) return true;
  }
  return parity_inside(ring, p);
}

Ring read_simple_polygon(const ArtifactInput& input, const std::string& context) {
  const auto raw = read_polygon(input);
  if (raw.size() < 3 || raw.size() > kMaximumMinkowskiVertices) {
    validation_failure("POLYGON_SIZE", context + " must have 3..16 vertices");
  }
  Ring ring;
  for (const auto& v : raw) ring.push_back({exact_of(v[0]), exact_of(v[1])});
  const std::size_t n = ring.size();
  for (std::size_t i = 0; i < n; ++i) {
    if (ring[i] == ring[(i + 1) % n]) validation_failure("POLYGON_REPEATED_VERTEX", context + " repeats a vertex");
  }
  for (std::size_t i = 0; i < n; ++i) {
    for (std::size_t j = i + 1; j < n; ++j) {
      const bool adjacent = j == i + 1 || (i == 0 && j == n - 1);
      const P2 &a = ring[i], &b = ring[(i + 1) % n], &c = ring[j], &d = ring[(j + 1) % n];
      if (adjacent) {
        const P2& shared = (j == i + 1) ? b : a;
        const P2 &p = (j == i + 1) ? a : b, &q = (j == i + 1) ? d : c;
        if (cross2(sub(p, shared), sub(q, shared)) == 0 && dot2(sub(p, shared), sub(q, shared)) > 0) {
          validation_failure("POLYGON_NOT_SIMPLE", context + " has overlapping adjacent edges");
        }
      } else if (segments_touch(a, b, c, d)) {
        validation_failure("POLYGON_NOT_SIMPLE", context + " is not simple");
      }
    }
  }
  if (twice_area(ring) == 0) validation_failure("POLYGON_ZERO_AREA", context + " has zero area");
  if (twice_area(ring) < 0) std::reverse(ring.begin(), ring.end());
  return ring;
}

P2 reported_point(const Json& value, const std::string& context) {
  if (!value.is_array() || value.size() != 2) validation_failure("REPORT_VALUE_INVALID", context + " must be [x,y]");
  return {reported_rational(value[0], context), reported_rational(value[1], context)};
}

Ring reported_ring(const Json& value, const std::string& context) {
  if (!value.is_array() || value.size() < 3 || value.size() > 4096) {
    validation_failure("REPORT_VALUE_INVALID", context + " must be a ring of at least three points");
  }
  Ring ring;
  for (const auto& item : value) ring.push_back(reported_point(item, context));
  return ring;
}

// ---- segment splitting ---------------------------------------------------------------------------

struct Seg {
  P2 a, b;
};
bool operator<(const Seg& l, const Seg& r) { return l.a != r.a ? l.a < r.a : l.b < r.b; }
bool operator==(const Seg& l, const Seg& r) { return l.a == r.a && l.b == r.b; }

Seg normalized(const P2& a, const P2& b) { return b < a ? Seg{b, a} : Seg{a, b}; }

// Splits every segment at all points where another segment meets it; returns the unit pieces
// (normalised, de-duplicated). Zero-length segments are ignored.
std::set<Seg> split_all(const std::vector<Seg>& segments) {
  std::set<Seg> result;
  for (std::size_t i = 0; i < segments.size(); ++i) {
    const P2 &a = segments[i].a, &b = segments[i].b;
    const P2 e = sub(b, a);
    if (e.x == 0 && e.y == 0) continue;
    std::vector<Q> params{Q(0), Q(1)};
    for (std::size_t j = 0; j < segments.size(); ++j) {
      if (j == i) continue;
      const P2 &c = segments[j].a, &d = segments[j].b;
      const P2 f = sub(d, c);
      if (f.x == 0 && f.y == 0) continue;
      const Q denominator = cross2(e, f);
      if (denominator != 0) {
        const Q t = cross2(sub(c, a), f) / denominator;
        const Q u = cross2(sub(c, a), e) / denominator;
        if (t >= 0 && t <= 1 && u >= 0 && u <= 1) params.push_back(t);
      } else if (cross2(sub(c, a), e) == 0) {
        for (const P2* q : {&c, &d}) {
          const Q t = dot2(sub(*q, a), e) / dot2(e, e);
          if (t >= 0 && t <= 1) params.push_back(t);
        }
      }
    }
    std::sort(params.begin(), params.end());
    params.erase(std::unique(params.begin(), params.end()), params.end());
    for (std::size_t k = 0; k + 1 < params.size(); ++k) {
      result.insert(normalized({a.x + params[k] * e.x, a.y + params[k] * e.y},
                               {a.x + params[k + 1] * e.x, a.y + params[k + 1] * e.y}));
    }
  }
  return result;
}

Q squared_distance_to_segment(const P2& p, const Seg& s) {
  const P2 e = sub(s.b, s.a);
  Q t = dot2(sub(p, s.a), e) / dot2(e, e);
  if (t < 0) t = 0;
  if (t > 1) t = 1;
  const P2 d = sub(p, {s.a.x + t * e.x, s.a.y + t * e.y});
  return dot2(d, d);
}

// An offset t such that the closed segment [m, m + t n] meets no piece other than `self`.
Q safe_offset(const P2& m, const P2& n, const Seg& self, const std::set<Seg>& pieces) {
  bool first = true;
  Q best = 0;
  for (const auto& piece : pieces) {
    if (piece == self) continue;
    const Q d = squared_distance_to_segment(m, piece);
    if (first || d < best) best = d;
    first = false;
  }
  Q t = 1;
  const Q norm = dot2(n, n);
  while (!first && 4 * t * t * norm >= best) t /= 2;
  return t;
}

// ---- planar graph, faces ---------------------------------------------------------------------------

struct Cycle {
  std::vector<std::size_t> ring;
  Q area2;
  std::size_t component;
};

struct Planar {
  std::vector<P2> verts;
  std::map<P2, std::size_t> id;
  std::set<std::pair<std::size_t, std::size_t>> edges;
  std::vector<Cycle> cycles;
  // Per face: outer cycle (-1 for the unbounded face) and hole cycles.
  std::vector<std::pair<long long, std::vector<std::size_t>>> faces;
};

int half_of(const P2& d) { return (d.y > 0 || (d.y == 0 && d.x > 0)) ? 0 : 1; }
bool angle_less(const P2& l, const P2& r) {
  const int hl = half_of(l), hr = half_of(r);
  if (hl != hr) return hl < hr;
  return cross2(l, r) > 0;
}

Planar build_planar(const std::vector<Seg>& segments) {
  Planar g;
  const auto pieces = split_all(segments);
  std::set<P2> points;
  for (const auto& s : pieces) {
    points.insert(s.a);
    points.insert(s.b);
  }
  for (const auto& p : points) {
    g.id[p] = g.verts.size();
    g.verts.push_back(p);
  }
  for (const auto& s : pieces) {
    const auto a = g.id[s.a], b = g.id[s.b];
    g.edges.insert({std::min(a, b), std::max(a, b)});
  }
  const std::size_t n = g.verts.size();
  std::vector<std::vector<std::size_t>> around(n);
  for (const auto& e : g.edges) {
    around[e.first].push_back(e.second);
    around[e.second].push_back(e.first);
  }
  for (std::size_t v = 0; v < n; ++v) {
    std::sort(around[v].begin(), around[v].end(), [&](std::size_t l, std::size_t r) {
      return angle_less(sub(g.verts[l], g.verts[v]), sub(g.verts[r], g.verts[v]));
    });
  }
  // Components.
  std::vector<std::size_t> parent(n);
  for (std::size_t i = 0; i < n; ++i) parent[i] = i;
  std::function<std::size_t(std::size_t)> find = [&](std::size_t x) { return parent[x] == x ? x : parent[x] = find(parent[x]); };
  for (const auto& e : g.edges) parent[find(e.first)] = find(e.second);
  // Cycles: next(u->v) = neighbour of v that precedes u in counter-clockwise order.
  std::set<std::pair<std::size_t, std::size_t>> visited;
  for (std::size_t u = 0; u < n; ++u) {
    for (const auto v0 : around[u]) {
      if (visited.count({u, v0})) continue;
      Cycle cycle;
      std::size_t a = u, b = v0;
      while (!visited.count({a, b})) {
        visited.insert({a, b});
        cycle.ring.push_back(a);
        const auto& ring = around[b];
        const std::size_t position = std::find(ring.begin(), ring.end(), a) - ring.begin();
        const std::size_t next = ring[(position + ring.size() - 1) % ring.size()];
        a = b;
        b = next;
      }
      Ring polygon;
      for (const auto v : cycle.ring) polygon.push_back(g.verts[v]);
      cycle.area2 = twice_area(polygon);
      cycle.component = find(cycle.ring.front());
      g.cycles.push_back(std::move(cycle));
    }
  }
  std::vector<std::size_t> positives;
  for (std::size_t c = 0; c < g.cycles.size(); ++c) {
    if (g.cycles[c].area2 > 0) {
      positives.push_back(c);
      g.faces.push_back({static_cast<long long>(c), {}});
    }
  }
  g.faces.push_back({-1, {}});
  auto polygon_of = [&](const Cycle& c) {
    Ring polygon;
    for (const auto v : c.ring) polygon.push_back(g.verts[v]);
    return polygon;
  };
  for (std::size_t c = 0; c < g.cycles.size(); ++c) {
    if (g.cycles[c].area2 > 0) continue;
    const P2& witness = g.verts[g.cycles[c].ring.front()];
    long long best = -1;
    for (std::size_t f = 0; f + 1 < g.faces.size(); ++f) {
      const Cycle& outer = g.cycles[static_cast<std::size_t>(g.faces[f].first)];
      if (outer.component == g.cycles[c].component) continue;
      if (!parity_inside(polygon_of(outer), witness)) continue;
      if (best < 0 || outer.area2 < g.cycles[static_cast<std::size_t>(g.faces[static_cast<std::size_t>(best)].first)].area2) {
        best = static_cast<long long>(f);
      }
    }
    g.faces[best < 0 ? g.faces.size() - 1 : static_cast<std::size_t>(best)].second.push_back(c);
  }
  return g;
}

Json rotated_ring(std::vector<std::size_t> ring) {
  std::vector<std::size_t> best = ring;
  for (std::size_t k = 1; k < ring.size(); ++k) {
    std::rotate(ring.begin(), ring.begin() + 1, ring.end());
    if (ring < best) best = ring;
  }
  Json result = Json::array();
  for (const auto id : best) result.push_back(id);
  return result;
}

Json face_record(const Planar& g, std::size_t face) {
  Json holes = Json::array();
  std::vector<std::string> dumps;
  for (const auto h : g.faces[face].second) dumps.push_back(rotated_ring(g.cycles[h].ring).dump());
  std::sort(dumps.begin(), dumps.end());
  for (const auto& d : dumps) holes.push_back(Json::parse(d));
  return Json{{"outer", g.faces[face].first < 0 ? Json(nullptr)
                                                 : rotated_ring(g.cycles[static_cast<std::size_t>(g.faces[face].first)].ring)},
              {"holes", holes}};
}

std::vector<std::string> sorted_dumps(const Json& faces, const std::string& context) {
  if (!faces.is_array()) validation_failure("REPORT_VALUE_INVALID", context + " must be an array");
  std::vector<std::string> result;
  for (const auto& f : faces) result.push_back(f.dump());
  std::sort(result.begin(), result.end());
  return result;
}

Json vertex_json(const Planar& g) {
  Json result = Json::array();
  for (const auto& p : g.verts) result.push_back(Json::array({query_ops::q_text(p.x), query_ops::q_text(p.y)}));
  return result;
}

Json edge_json(const Planar& g) {
  Json result = Json::array();
  for (const auto& e : g.edges) result.push_back(Json::array({e.first, e.second}));
  return result;
}

void compare_planar(const Planar& g, const Json& results, std::vector<Json> expected_faces, Json& checks) {
  if (require_member(results, "vertices", "results") != vertex_json(g)) {
    validation_failure("ARRANGEMENT_VERTICES_MISMATCH", "The reported vertices differ from the exact arrangement vertices");
  }
  checks["vertices_equal_exact_arrangement"] = true;
  if (require_member(results, "edges", "results") != edge_json(g)) {
    validation_failure("ARRANGEMENT_EDGES_MISMATCH", "The reported edges differ from the exact arrangement edges");
  }
  checks["edges_equal_exact_arrangement"] = true;
  std::vector<std::string> expected;
  for (const auto& f : expected_faces) expected.push_back(f.dump());
  std::sort(expected.begin(), expected.end());
  if (sorted_dumps(require_member(results, "faces", "results"), "faces") != expected) {
    validation_failure("ARRANGEMENT_FACES_MISMATCH", "The reported faces differ from the exact traced faces");
  }
  checks["faces_equal_exact_traced_faces"] = true;
}

std::vector<Seg> read_segments(const ArtifactInput& input, const std::string& context, std::size_t maximum) {
  const auto graph = wave_c::read_segment_graph2(input);
  if (graph.segments.empty() || graph.segments.size() > maximum) {
    validation_failure("SEGMENT_COUNT", context + " has an unsupported segment count");
  }
  std::vector<Seg> result;
  for (const auto& s : graph.segments) {
    const P2 a{exact_of(graph.points.at(s[0])[0]), exact_of(graph.points.at(s[0])[1])};
    const P2 b{exact_of(graph.points.at(s[1])[0]), exact_of(graph.points.at(s[1])[1])};
    if (a == b) validation_failure("ZERO_LENGTH_SEGMENT", context + " has a zero-length segment");
    result.push_back({a, b});
  }
  return result;
}

Json run_arrangement_validator(const Request& request) {
  const std::string validator = "arrangement.validate.build";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "arrangement_2");
  const auto segments = read_segments(request.inputs[1], "segments", kMaximumArrangementSegments);
  Json checks;
  const auto results = batch2::check_report_frame(report, "arrangement.build", Json::object(),
                                                  {{"segments_sha256", &request.inputs[1]}}, checks);
  const Planar g = build_planar(segments);
  std::vector<Json> faces;
  for (std::size_t f = 0; f < g.faces.size(); ++f) faces.push_back(face_record(g, f));
  compare_planar(g, results, faces, checks);
  return concluded(request, validator, checks,
                   {{"vertex_count", g.verts.size()}, {"edge_count", g.edges.size()}, {"face_count", g.faces.size()},
                    {"independence", "exact segment splitting, angular half-edge face tracing and cycle nesting in GMP rationals; no CGAL header"}});
}

Json run_zone_validator(const Request& request) {
  const std::string validator = "arrangement.validate.zone";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "arrangement_zone");
  const auto segments = read_segments(request.inputs[1], "segments", kMaximumArrangementSegments);
  const auto curve = read_segments(request.inputs[2], "curve", 1);
  if (curve.size() != 1) validation_failure("QUERY_NOT_ONE_SEGMENT", "The query graph must contain one segment");
  Json checks;
  const auto results = batch2::check_report_frame(
      report, "arrangement.zone", Json::object(),
      {{"segments_sha256", &request.inputs[1]}, {"curve_sha256", &request.inputs[2]}}, checks);
  const Planar g = build_planar(segments);
  if (require_member(results, "arrangement_vertices", "results") != vertex_json(g)) {
    validation_failure("ARRANGEMENT_VERTICES_MISMATCH", "The reported arrangement vertices differ from the exact ones");
  }
  checks["arrangement_vertices_equal_exact"] = true;
  const P2 &a = curve[0].a, &b = curve[0].b;
  const P2 e = sub(b, a);
  // Split points on the query: its ends, arrangement vertices on it and crossings with edges.
  std::vector<Q> params{Q(0), Q(1)};
  for (const auto& v : g.verts) {
    if (on_segment(v, a, b)) params.push_back(dot2(sub(v, a), e) / dot2(e, e));
  }
  std::vector<Seg> edge_segments;
  for (const auto& edge : g.edges) edge_segments.push_back({g.verts[edge.first], g.verts[edge.second]});
  for (const auto& s : edge_segments) {
    const P2 f = sub(s.b, s.a);
    const Q denominator = cross2(e, f);
    if (denominator != 0) {
      const Q t = cross2(sub(s.a, a), f) / denominator;
      const Q u = cross2(sub(s.a, a), e) / denominator;
      if (t >= 0 && t <= 1 && u >= 0 && u <= 1) params.push_back(t);
    } else if (cross2(sub(s.a, a), e) == 0) {
      for (const P2* q : {&s.a, &s.b}) {
        const Q t = dot2(sub(*q, a), e) / dot2(e, e);
        if (t >= 0 && t <= 1) params.push_back(t);
      }
    }
  }
  std::sort(params.begin(), params.end());
  params.erase(std::unique(params.begin(), params.end()), params.end());
  const auto point_at = [&](const Q& t) { return P2{a.x + t * e.x, a.y + t * e.y}; };
  std::set<std::size_t> vertices;
  std::set<std::pair<std::size_t, std::size_t>> edges;
  std::set<std::string> faces;
  const auto edge_of = [&](const P2& p) -> std::pair<long long, long long> {
    for (const auto& edge : g.edges) {
      if (on_segment(p, g.verts[edge.first], g.verts[edge.second])) {
        return {static_cast<long long>(edge.first), static_cast<long long>(edge.second)};
      }
    }
    return {-1, -1};
  };
  for (const auto& t : params) {
    const P2 p = point_at(t);
    const auto found = g.id.find(p);
    if (found != g.id.end()) {
      vertices.insert(found->second);
    } else {
      const auto edge = edge_of(p);
      if (edge.first >= 0) edges.insert({static_cast<std::size_t>(edge.first), static_cast<std::size_t>(edge.second)});
    }
  }
  for (std::size_t k = 0; k + 1 < params.size(); ++k) {
    const P2 mid = point_at((params[k] + params[k + 1]) / 2);
    const auto edge = edge_of(mid);
    if (edge.first >= 0) {
      edges.insert({static_cast<std::size_t>(edge.first), static_cast<std::size_t>(edge.second)});
      continue;
    }
    long long best = -1;
    for (std::size_t f = 0; f + 1 < g.faces.size(); ++f) {
      const Cycle& outer = g.cycles[static_cast<std::size_t>(g.faces[f].first)];
      Ring polygon;
      for (const auto v : outer.ring) polygon.push_back(g.verts[v]);
      if (!parity_inside(polygon, mid)) continue;
      if (best < 0 || outer.area2 < g.cycles[static_cast<std::size_t>(g.faces[static_cast<std::size_t>(best)].first)].area2) {
        best = static_cast<long long>(f);
      }
    }
    faces.insert(face_record(g, best < 0 ? g.faces.size() - 1 : static_cast<std::size_t>(best)).dump());
  }
  Json expected_vertices = Json::array(), expected_edges = Json::array();
  for (const auto v : vertices) expected_vertices.push_back(v);
  for (const auto& edge : edges) expected_edges.push_back(Json::array({edge.first, edge.second}));
  if (require_member(results, "vertices", "results") != expected_vertices) {
    validation_failure("ZONE_VERTICES_MISMATCH", "The reported zone vertices differ from the exact ones");
  }
  checks["zone_vertices_equal_exact"] = true;
  if (require_member(results, "edges", "results") != expected_edges) {
    validation_failure("ZONE_EDGES_MISMATCH", "The reported zone edges differ from the exact ones");
  }
  checks["zone_edges_equal_exact"] = true;
  const auto reported_faces = sorted_dumps(require_member(results, "faces", "results"), "faces");
  if (reported_faces != std::vector<std::string>(faces.begin(), faces.end())) {
    validation_failure("ZONE_FACES_MISMATCH", "The reported zone faces differ from the exact ones");
  }
  checks["zone_faces_equal_exact"] = true;
  return concluded(request, validator, checks,
                   {{"zone_vertex_count", vertices.size()}, {"zone_edge_count", edges.size()},
                    {"zone_face_count", faces.size()},
                    {"independence", "exact splitting of the query at arrangement vertices and edges and exact face location; no CGAL header"}});
}

Json run_overlay_validator(const Request& request) {
  const std::string validator = "arrangement.validate.overlay";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "arrangement_overlay");
  const Ring first = read_simple_polygon(request.inputs[1], "first polygon");
  const Ring second = read_simple_polygon(request.inputs[2], "second polygon");
  Json checks = Json::object();
  const auto results = batch2::check_report_frame(
      report, "arrangement.overlay", Json::object(),
      {{"first_sha256", &request.inputs[1]}, {"second_sha256", &request.inputs[2]}}, checks);
  checks["operands_simple_nonzero_area"] = true;
  std::vector<Seg> segments;
  for (const Ring* ring : {&first, &second}) {
    for (std::size_t i = 0; i < ring->size(); ++i) segments.push_back({(*ring)[i], (*ring)[(i + 1) % ring->size()]});
  }
  const Planar g = build_planar(segments);
  const auto pieces = split_all(segments);
  std::vector<Json> faces;
  for (std::size_t f = 0; f < g.faces.size(); ++f) {
    Json record = face_record(g, f);
    int label = 0;
    if (g.faces[f].first >= 0) {
      const Cycle& outer = g.cycles[static_cast<std::size_t>(g.faces[f].first)];
      // Interior witness: just left of the first outer edge.
      const P2 &u = g.verts[outer.ring[0]], &v = g.verts[outer.ring[1 % outer.ring.size()]];
      const P2 direction = sub(v, u);
      const P2 midpoint{(u.x + v.x) / 2, (u.y + v.y) / 2};
      const P2 normal{-direction.y, direction.x};
      const Q t = safe_offset(midpoint, normal, normalized(u, v), pieces);
      const P2 witness = add(midpoint, {t * normal.x, t * normal.y});
      label = (parity_inside(first, witness) ? 1 : 0) + (parity_inside(second, witness) ? 1 : 0);
    }
    record["label"] = label;
    faces.push_back(std::move(record));
  }
  compare_planar(g, results, faces, checks);
  return concluded(request, validator, checks,
                   {{"vertex_count", g.verts.size()}, {"edge_count", g.edges.size()}, {"face_count", g.faces.size()},
                    {"independence", "arrangement of both boundaries traced in GMP rationals; face labels from exact point-in-polygon witnesses; no CGAL header"}});
}

// ---- Minkowski ------------------------------------------------------------------------------------

bool region_intersects(const Ring& p, const Ring& r) {
  for (std::size_t i = 0; i < p.size(); ++i)
    for (std::size_t j = 0; j < r.size(); ++j)
      if (segments_touch(p[i], p[(i + 1) % p.size()], r[j], r[(j + 1) % r.size()])) return true;
  return inside_closed(p, r[0]) || inside_closed(r, p[0]);
}

bool in_sum(const Ring& a, const Ring& b, const P2& q) {
  Ring reflected;
  for (const auto& v : b) reflected.push_back(sub(q, v));
  return region_intersects(a, reflected);
}

Json run_minkowski_validator(const Request& request) {
  const std::string validator = "polygon.validate.minkowski_sum";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "minkowski_sum_2");
  const std::string operation = report.value("operation", std::string());
  if (operation != "polygon.minkowski_sum" && operation != "polygon.minkowski_sum_reduced_convolution") {
    validation_failure("PARAMETER_MISMATCH", "The report is not a Minkowski sum report");
  }
  const Ring a = read_simple_polygon(request.inputs[1], "first polygon");
  const Ring b = read_simple_polygon(request.inputs[2], "second polygon");
  Json checks = Json::object();
  const auto results = batch2::check_report_frame(
      report, operation, Json::object(), {{"first_sha256", &request.inputs[1]}, {"second_sha256", &request.inputs[2]}}, checks);
  checks["operands_simple_nonzero_area"] = true;

  // Candidate boundary: edges of one summand translated by the vertices of the other.
  std::vector<Seg> candidates;
  for (std::size_t i = 0; i < a.size(); ++i)
    for (const auto& v : b) candidates.push_back({add(a[i], v), add(a[(i + 1) % a.size()], v)});
  for (std::size_t j = 0; j < b.size(); ++j)
    for (const auto& v : a) candidates.push_back({add(b[j], v), add(b[(j + 1) % b.size()], v)});
  const auto pieces = split_all(candidates);
  std::vector<Seg> expected;  // directed with the sum on the left
  for (const auto& piece : pieces) {
    const P2 direction = sub(piece.b, piece.a);
    const P2 midpoint{(piece.a.x + piece.b.x) / 2, (piece.a.y + piece.b.y) / 2};
    const P2 normal{-direction.y, direction.x};
    const Q t = safe_offset(midpoint, normal, piece, pieces);
    const bool left = in_sum(a, b, add(midpoint, {t * normal.x, t * normal.y}));
    const bool right = in_sum(a, b, sub(midpoint, {t * normal.x, t * normal.y}));
    if (left == right) continue;
    expected.push_back(left ? piece : Seg{piece.b, piece.a});
  }

  const Ring outer = reported_ring(require_member(results, "outer", "results"), "outer");
  if (twice_area(outer) <= 0) validation_failure("RING_ORIENTATION", "The outer boundary is not counter-clockwise");
  std::vector<Seg> reported;
  for (std::size_t i = 0; i < outer.size(); ++i) reported.push_back({outer[i], outer[(i + 1) % outer.size()]});
  const auto& holes = require_member(results, "holes", "results");
  if (!holes.is_array()) validation_failure("REPORT_VALUE_INVALID", "holes must be an array");
  for (const auto& hole_json : holes) {
    const Ring hole = reported_ring(hole_json, "hole");
    if (twice_area(hole) >= 0) validation_failure("RING_ORIENTATION", "A hole is not clockwise");
    for (std::size_t i = 0; i < hole.size(); ++i) reported.push_back({hole[i], hole[(i + 1) % hole.size()]});
  }
  checks["rings_oriented_outer_ccw_hole_cw"] = true;

  std::set<P2> points;
  for (const auto& s : expected) {
    points.insert(s.a);
    points.insert(s.b);
  }
  for (const auto& s : reported) {
    points.insert(s.a);
    points.insert(s.b);
  }
  auto unit_segments = [&](const std::vector<Seg>& chain) {
    std::map<std::pair<P2, P2>, int> result;
    for (const auto& s : chain) {
      std::vector<std::pair<Q, P2>> on;
      const P2 d = sub(s.b, s.a);
      for (const auto& p : points) {
        if (on_segment(p, s.a, s.b)) on.emplace_back(dot2(sub(p, s.a), d), p);
      }
      std::sort(on.begin(), on.end(), [](const auto& l, const auto& r) { return l.first < r.first; });
      for (std::size_t i = 0; i + 1 < on.size(); ++i) ++result[{on[i].second, on[i + 1].second}];
    }
    return result;
  };
  const auto expected_units = unit_segments(expected);
  const auto reported_units = unit_segments(reported);
  if (expected_units != reported_units) {
    validation_failure("BOUNDARY_CHAIN_MISMATCH", "The reported polygon does not have the exact boundary of the Minkowski sum");
  }
  for (const auto& [segment, count] : reported_units) {
    if (count != 1) validation_failure("BOUNDARY_CHAIN_MISMATCH", "A boundary segment is reported more than once");
  }
  checks["boundary_chain_equals_exact_minkowski_sum"] = true;
  return concluded(request, validator, checks,
                   {{"expected_boundary_segment_count", expected_units.size()}, {"candidate_piece_count", pieces.size()},
                    {"independence", "convolution-segment splitting with exact set-membership on both sides of every piece; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> planar_validators() {
  using query_ops::query_definition;
  const std::string gmp = "exact:GMP";
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "arrangement.validate.build", {"GeometryQueryReport", "SegmentGraph2"}, "ValidationReport", "validator",
      run_arrangement_validator, {"Arrangement_on_surface_2"}, gmp,
      vinfo({"parameters_match", "source_matches", "vertices_equal_exact_arrangement", "edges_equal_exact_arrangement",
             "faces_equal_exact_traced_faces"},
            {"candidate", "segments"},
            "exact segment splitting, angular half-edge face tracing and cycle nesting in GMP rationals; no CGAL header")));
  result.push_back(query_definition(
      "arrangement.validate.zone", {"GeometryQueryReport", "SegmentGraph2", "SegmentGraph2"}, "ValidationReport",
      "validator", run_zone_validator, {"Arrangement_on_surface_2"}, gmp,
      vinfo({"parameters_match", "source_matches", "arrangement_vertices_equal_exact", "zone_vertices_equal_exact",
             "zone_edges_equal_exact", "zone_faces_equal_exact"},
            {"candidate", "segments", "curve"},
            "exact splitting of the query at arrangement vertices and edges and exact face location; no CGAL header")));
  result.push_back(query_definition(
      "arrangement.validate.overlay", {"GeometryQueryReport", "Polygon2", "Polygon2"}, "ValidationReport", "validator",
      run_overlay_validator, {"Arrangement_on_surface_2"}, gmp,
      vinfo({"parameters_match", "source_matches", "operands_simple_nonzero_area", "vertices_equal_exact_arrangement",
             "edges_equal_exact_arrangement", "faces_equal_exact_traced_faces"},
            {"candidate", "first", "second"},
            "arrangement of both boundaries traced in GMP rationals; face labels from exact point-in-polygon witnesses; no CGAL header")));
  result.push_back(query_definition(
      "polygon.validate.minkowski_sum", {"GeometryQueryReport", "Polygon2", "Polygon2"}, "ValidationReport", "validator",
      run_minkowski_validator, {"Minkowski_sum_2"}, gmp,
      vinfo({"parameters_match", "source_matches", "operands_simple_nonzero_area", "rings_oriented_outer_ccw_hole_cw",
             "boundary_chain_equals_exact_minkowski_sum"},
            {"candidate", "first", "second"},
            "convolution-segment splitting with exact set-membership on both sides of every piece; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch3
