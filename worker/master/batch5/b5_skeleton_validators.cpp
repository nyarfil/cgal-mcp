// Independent validators for the 7.12.05 straight skeletons and 7.12.06 polygon offsets. No CGAL algorithm
// header is used (only the shared input parser).
//
// Skeleton: the reported contour must equal the source polygon exactly (plus the axis-aligned frame of the
// exterior construction); there must be one face per contour edge; every node must lie strictly inside the
// region (exact rational point-in-ring on the reported binary64 coordinates); the node time must equal the
// distance to the line of every face edge it touches and the node must be clear of the whole boundary at that
// time (the mitered wavefront never gets closer to the boundary than its time); the exact face areas must sum
// to the region area. Offset: every output edge must lie on the source edge line shifted by d to the correct
// side; output vertices must be clear of the source boundary; empty output is accepted only when the source is
// convex and the shifted half-planes have empty intersection, or when the inradius bound proves the true
// offset region empty. Square roots force the declared tolerance (1e-9 relative to the region diagonal).

#include "b5_common.h"

#include "../wave_c/wave_c_common.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <queue>
#include <set>

namespace cgal_master::batch5 {
namespace {

using batch2::concluded;
using batch2::require_member;
using batch2::vinfo;
using query_ops::exact_of;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;

using LD = long double;
using Pt = std::array<Q, 2>;
constexpr LD kTolerance = 1e-9L;
constexpr std::size_t kNodeBudget = 2000000;

struct P {
  LD x, y;
};
P operator-(const P& a, const P& b) { return {a.x - b.x, a.y - b.y}; }
LD cross(const P& a, const P& b) { return a.x * b.y - a.y * b.x; }
LD dot(const P& a, const P& b) { return a.x * b.x + a.y * b.y; }
LD norm(const P& a) { return std::sqrt(dot(a, a)); }
P to_p(const V2& v) { return {v[0], v[1]}; }
Pt to_exact(const V2& v) { return {exact_of(v[0]), exact_of(v[1])}; }

// Signed distance of p to the directed line a->b (positive on the left).
LD line_distance(const P& p, const P& a, const P& b) { return cross(b - a, p - a) / norm(b - a); }
LD segment_distance(const P& p, const P& a, const P& b) {
  const P ab = b - a;
  const LD t = std::max<LD>(0, std::min<LD>(1, dot(p - a, ab) / dot(ab, ab)));
  return norm(p - P{a.x + t * ab.x, a.y + t * ab.y});
}

double number(const Json& value, const std::string& context) {
  if (!value.is_number()) validation_failure("REPORT_SCHEMA_MISMATCH", context + " must be a number");
  const double result = value.get<double>();
  if (!std::isfinite(result)) validation_failure("REPORT_SCHEMA_MISMATCH", context + " must be finite");
  return result;
}

std::size_t index_of(const Json& value, std::size_t limit, const std::string& context) {
  if (!value.is_number_unsigned()) validation_failure("REPORT_SCHEMA_MISMATCH", context + " must be a non-negative integer");
  const std::size_t result = value.get<std::size_t>();
  if (result >= limit) validation_failure("REPORT_SCHEMA_MISMATCH", context + " is out of range");
  return result;
}

Json array_member(const Json& object, const char* key, const std::string& context) {
  const Json& value = require_member(object, key, context);
  if (!value.is_array()) validation_failure("REPORT_SCHEMA_MISMATCH", context + "." + key + " must be an array");
  return value;
}

// Source polygon: rings[0] is the outer ring (counter-clockwise), the other rings are holes (clockwise).
struct Source {
  std::vector<std::vector<V2>> rings;
};

Ring exact_ring(const std::vector<V2>& points) { return ring_from_doubles(points); }

Source load_source(const ArtifactInput& input, bool allow_holes) {
  const auto data = wave_c::read_polygon_with_holes2(input);
  std::size_t total = data.outer.size();
  for (const auto& hole : data.holes) total += hole.size();
  if (total > kMaximumSkeletonVertices) validation_failure("POINT_LIMIT_EXCEEDED", "At most 64 polygon vertices are supported");
  if (!allow_holes && !data.holes.empty()) validation_failure("HOLES_NOT_SUPPORTED", "The exterior construction takes a polygon without holes");
  Source source;
  source.rings.emplace_back(data.outer.begin(), data.outer.end());
  for (const auto& hole : data.holes) source.rings.emplace_back(hole.begin(), hole.end());
  std::vector<Ring> rings;
  for (const auto& ring : source.rings) rings.push_back(exact_ring(ring));
  check_polygon_with_holes(rings[0], std::vector<Ring>(rings.begin() + 1, rings.end()), true);
  for (std::size_t i = 0; i < rings.size(); ++i) {
    const bool counter_clockwise = ring_signed_area(rings[i]) > 0;
    if (counter_clockwise != (i == 0)) std::reverse(source.rings[i].begin(), source.rings[i].end());
  }
  return source;
}

Q exact_area(const std::vector<V2>& ring) {
  Q twice = 0;
  for (std::size_t i = 0; i < ring.size(); ++i) {
    const auto& a = ring[i];
    const auto& b = ring[(i + 1) % ring.size()];
    twice += exact_of(a[0]) * exact_of(b[1]) - exact_of(b[0]) * exact_of(a[1]);
  }
  return twice / 2;
}

LD diagonal_of(const Source& source) {
  LD low[2] = {1e300L, 1e300L}, high[2] = {-1e300L, -1e300L};
  for (const auto& v : source.rings[0]) {
    for (int a = 0; a < 2; ++a) {
      low[a] = std::min<LD>(low[a], v[a]);
      high[a] = std::max<LD>(high[a], v[a]);
    }
  }
  return std::sqrt((high[0] - low[0]) * (high[0] - low[0]) + (high[1] - low[1]) * (high[1] - low[1]));
}

// ---------------------------------------------------------------------------------------------------------
// Straight skeleton validator
// ---------------------------------------------------------------------------------------------------------

struct SkeletonVertex {
  double x, y, time;
  bool contour;
};

Json run_skeleton(const Request& request) {
  const std::string validator = "polygon.validate.straight_skeleton";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {}, {"max_offset"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "straight_skeleton");
  const std::string operation = report.value("operation", std::string());
  bool exterior = false;
  if (operation == "polygon.straight_skeleton.exterior") {
    exterior = true;
  } else if (operation != "polygon.straight_skeleton.interior") {
    validation_failure("PARAMETER_MISMATCH", "Report is not a straight skeleton report");
  }
  if (exterior != request.parameters.contains("max_offset")) {
    validation_failure("PARAMETER_MISMATCH", "max_offset is required exactly for the exterior skeleton");
  }
  const std::string unit = request.inputs[1].unit;
  double max_offset = 0;
  if (exterior) max_offset = positive_length(request.parameters.at("max_offset"), "max_offset", unit);
  Json checks;
  const auto results = batch2::check_report_frame(report, operation, request.parameters,
                                                  {{"polygon_sha256", &request.inputs[1]}}, checks);
  const Source source = load_source(request.inputs[1], !exterior);
  if (report.value("length_unit", std::string()) != unit || results.value("length_unit", std::string()) != unit ||
      results.value("area_unit", std::string()) != unit + "^2") {
    validation_failure("UNIT_MISMATCH", "The report units differ from the polygon units");
  }
  if (results.value("skeleton_kind", std::string()) != (exterior ? "exterior" : "interior") ||
      results.value("includes_outer_frame", !exterior) != exterior) {
    validation_failure("PARAMETER_MISMATCH", "The skeleton kind differs from the operation");
  }
  const Json jv = array_member(results, "vertices", "results");
  const Json jf = array_member(results, "faces", "results");
  const Json jb = array_member(results, "bisectors", "results");
  if (jv.size() > 5000 || jf.size() > 1000) validation_failure("REPORT_SCHEMA_MISMATCH", "The skeleton report is too large");
  std::vector<SkeletonVertex> vs;
  for (std::size_t i = 0; i < jv.size(); ++i) {
    const Json& item = jv[i];
    if (!item.is_object()) validation_failure("REPORT_SCHEMA_MISMATCH", "A skeleton vertex must be an object");
    if (index_of(require_member(item, "id", "vertex"), jv.size(), "vertex id") != i) {
      validation_failure("REPORT_SCHEMA_MISMATCH", "Vertex ids must be consecutive");
    }
    const Json& contour = require_member(item, "contour", "vertex");
    if (!contour.is_boolean()) validation_failure("REPORT_SCHEMA_MISMATCH", "vertex contour must be a boolean");
    vs.push_back({number(require_member(item, "x", "vertex"), "vertex x"), number(require_member(item, "y", "vertex"), "vertex y"),
                  number(require_member(item, "time", "vertex"), "vertex time"), contour.get<bool>()});
  }
  struct Face {
    std::size_t s, t;
    std::vector<std::size_t> ring;
  };
  std::vector<Face> faces;
  for (const Json& item : jf) {
    if (!item.is_object()) validation_failure("REPORT_SCHEMA_MISMATCH", "A skeleton face must be an object");
    const Json edge = array_member(item, "edge", "face");
    const Json ring = array_member(item, "vertices", "face");
    if (edge.size() != 2 || ring.size() < 3 || ring.size() > 400) validation_failure("REPORT_SCHEMA_MISMATCH", "A face needs an edge pair and 3 or more vertices");
    Face face{index_of(edge[0], vs.size(), "face edge"), index_of(edge[1], vs.size(), "face edge"), {}};
    for (const Json& id : ring) face.ring.push_back(index_of(id, vs.size(), "face vertex"));
    faces.push_back(std::move(face));
  }
  std::set<std::pair<std::size_t, std::size_t>> bisectors;
  for (const Json& item : jb) {
    if (!item.is_array() || item.size() != 2) validation_failure("REPORT_SCHEMA_MISMATCH", "A bisector must be a vertex pair");
    const std::size_t a = index_of(item[0], vs.size(), "bisector vertex"), b = index_of(item[1], vs.size(), "bisector vertex");
    if (a >= b || !bisectors.insert({a, b}).second) validation_failure("BISECTOR_INVALID", "Bisectors must be unique pairs with a < b");
  }
  const Json& summary = require_member(report, "summary", "report");
  if (summary.value("vertex_count", std::size_t(-1)) != vs.size() || summary.value("face_count", std::size_t(-1)) != faces.size() ||
      summary.value("bisector_count", std::size_t(-1)) != bisectors.size()) {
    validation_failure("REPORT_SCHEMA_MISMATCH", "The summary counts differ from the listed vertices, faces or bisectors");
  }
  checks["report_schema_and_units_valid"] = true;

  // Contour = source polygon (+ frame): exact coordinates, time zero.
  std::map<std::pair<double, double>, std::size_t> contour_at;
  for (std::size_t i = 0; i < vs.size(); ++i) {
    if (!vs[i].contour) continue;
    if (vs[i].time != 0) validation_failure("CONTOUR_MISMATCH", "A contour vertex must have time zero");
    if (!contour_at.emplace(std::make_pair(vs[i].x, vs[i].y), i).second) validation_failure("CONTOUR_MISMATCH", "Two contour vertices coincide");
  }
  std::vector<std::vector<V2>> contour_rings = source.rings;
  if (exterior) std::reverse(contour_rings[0].begin(), contour_rings[0].end());
  std::vector<std::vector<std::size_t>> contour_ids;
  std::set<std::size_t> used;
  for (const auto& ring : contour_rings) {
    contour_ids.emplace_back();
    for (const auto& v : ring) {
      const auto found = contour_at.find({v[0], v[1]});
      if (found == contour_at.end()) validation_failure("CONTOUR_MISMATCH", "A source vertex is missing from the skeleton contour");
      contour_ids.back().push_back(found->second);
      used.insert(found->second);
    }
  }
  double frame[4] = {0, 0, 0, 0};  // xl, xh, yl, yh
  if (exterior) {
    std::vector<std::size_t> extra;
    for (const auto& [key, id] : contour_at) {
      if (!used.count(id)) extra.push_back(id);
    }
    if (extra.size() != 4) validation_failure("CONTOUR_MISMATCH", "The exterior contour needs exactly four frame vertices");
    std::set<double> xs, ys;
    for (std::size_t id : extra) {
      xs.insert(vs[id].x);
      ys.insert(vs[id].y);
    }
    if (xs.size() != 2 || ys.size() != 2) validation_failure("CONTOUR_MISMATCH", "The frame is not an axis-aligned rectangle");
    frame[0] = *xs.begin();
    frame[1] = *xs.rbegin();
    frame[2] = *ys.begin();
    frame[3] = *ys.rbegin();
    std::vector<std::size_t> ring;
    const double corners[4][2] = {{frame[0], frame[2]}, {frame[1], frame[2]}, {frame[1], frame[3]}, {frame[0], frame[3]}};
    for (const auto& c : corners) {
      const auto found = contour_at.find({c[0], c[1]});
      if (found == contour_at.end() || used.count(found->second)) validation_failure("CONTOUR_MISMATCH", "The frame corners are not all present");
      ring.push_back(found->second);
    }
    contour_ids.push_back(ring);
    for (const auto& v : source.rings[0]) {
      if (!(frame[0] < v[0] && v[0] < frame[1] && frame[2] < v[1] && v[1] < frame[3])) {
        validation_failure("CONTOUR_MISMATCH", "The frame does not strictly contain the polygon");
      }
    }
    LD gap = std::numeric_limits<LD>::infinity();
    for (const auto& v : source.rings[0]) {
      gap = std::min({gap, static_cast<LD>(v[0]) - frame[0], static_cast<LD>(frame[1]) - v[0], static_cast<LD>(v[1]) - frame[2], static_cast<LD>(frame[3]) - v[1]});
    }
    if (gap < max_offset * (1 - kTolerance)) validation_failure("CONTOUR_MISMATCH", "The frame margin is smaller than max_offset");
  } else if (used.size() != contour_at.size()) {
    validation_failure("CONTOUR_MISMATCH", "The contour holds vertices that are not source vertices");
  }
  checks["contour_matches_source_polygon"] = true;

  // Boundary segments (source rings, reversed outer for exterior, plus the frame) and region data.
  std::vector<std::pair<std::size_t, std::size_t>> expected_edges;
  for (const auto& ring : contour_ids) {
    for (std::size_t i = 0; i < ring.size(); ++i) expected_edges.push_back({ring[i], ring[(i + 1) % ring.size()]});
  }
  LD diagonal = diagonal_of(source);
  if (exterior) {
    diagonal = std::sqrt((static_cast<LD>(frame[1]) - frame[0]) * (frame[1] - frame[0]) + (static_cast<LD>(frame[3]) - frame[2]) * (frame[3] - frame[2]));
  }
  const LD tol = kTolerance * (1 + diagonal);

  // One face per contour edge.
  std::set<std::pair<std::size_t, std::size_t>> face_edges;
  for (const Face& face : faces) face_edges.insert({face.s, face.t});
  if (faces.size() != expected_edges.size() || face_edges.size() != faces.size() ||
      face_edges != std::set<std::pair<std::size_t, std::size_t>>(expected_edges.begin(), expected_edges.end())) {
    validation_failure("FACE_EDGE_MISMATCH", "The faces are not exactly one per directed contour edge");
  }
  checks["one_face_per_contour_edge"] = true;

  // Nodes strictly inside the region.
  std::vector<Ring> source_exact;
  for (const auto& ring : source.rings) source_exact.push_back(exact_ring(ring));
  std::vector<std::size_t> face_count(vs.size(), 0);
  for (const Face& face : faces) {
    std::set<std::size_t> distinct(face.ring.begin(), face.ring.end());
    if (distinct.size() != face.ring.size()) validation_failure("FACE_INVALID", "A face repeats a vertex");
    for (std::size_t id : face.ring) ++face_count[id];
  }
  std::size_t node_count = 0;
  for (std::size_t i = 0; i < vs.size(); ++i) {
    if (vs[i].contour) continue;
    ++node_count;
    const Pt p = {exact_of(vs[i].x), exact_of(vs[i].y)};
    bool inside;
    if (exterior) {
      inside = frame[0] < vs[i].x && vs[i].x < frame[1] && frame[2] < vs[i].y && vs[i].y < frame[3] &&
               point_in_ring(p, source_exact[0]) == -1;
    } else {
      inside = point_in_ring(p, source_exact[0]) == 1;
      for (std::size_t h = 1; h < source_exact.size() && inside; ++h) inside = point_in_ring(p, source_exact[h]) == -1;
    }
    if (!inside) validation_failure("NODE_OUTSIDE_REGION", "A skeleton node does not lie strictly inside the region");
    if (!(vs[i].time > 0)) validation_failure("NODE_TIME_INVALID", "A skeleton node must have positive time");
    if (face_count[i] < 3) validation_failure("NODE_DEGREE", "A skeleton node must touch at least three faces");
  }
  checks["nodes_strictly_inside_region"] = true;

  // Node time = distance to the line of each touching face edge; node clear of the boundary.
  auto vp = [&](std::size_t id) { return P{vs[id].x, vs[id].y}; };
  for (const Face& face : faces) {
    for (std::size_t id : face.ring) {
      if (vs[id].contour) continue;
      const LD d = line_distance(vp(id), vp(face.s), vp(face.t));
      if (std::fabs(d - vs[id].time) > tol) {
        validation_failure("NODE_TIME_MISMATCH", "A node time differs from its distance to the line of a touching face edge");
      }
    }
  }
  checks["node_time_equals_distance_to_defining_edge_lines"] = true;
  for (std::size_t i = 0; i < vs.size(); ++i) {
    if (vs[i].contour) continue;
    LD nearest = std::numeric_limits<LD>::infinity();
    for (const auto& [a, b] : expected_edges) nearest = std::min(nearest, segment_distance(vp(i), vp(a), vp(b)));
    if (nearest < vs[i].time - tol) validation_failure("NODE_TOO_CLOSE_TO_BOUNDARY", "A node is closer to the boundary than its time");
  }
  checks["node_clear_of_boundary_at_node_time"] = true;

  // Faces: positive exact area, vertices on the interior side of the face edge.
  Q area_sum = 0;
  for (const Face& face : faces) {
    Q twice = 0;
    for (std::size_t i = 0; i < face.ring.size(); ++i) {
      const std::size_t a = face.ring[i], b = face.ring[(i + 1) % face.ring.size()];
      twice += exact_of(vs[a].x) * exact_of(vs[b].y) - exact_of(vs[b].x) * exact_of(vs[a].y);
      if (line_distance(vp(a), vp(face.s), vp(face.t)) < -tol) {
        validation_failure("FACE_NOT_ON_INTERIOR_SIDE", "A face vertex lies on the wrong side of the face edge");
      }
    }
    if (twice <= 0) validation_failure("FACE_AREA_NOT_POSITIVE", "A face has non-positive area or is clockwise");
    area_sum += twice / 2;
  }
  checks["faces_positive_area_on_interior_side_of_edge"] = true;

  // Face rings: every ring step is the face edge or a reported bisector shared by exactly two faces.
  std::map<std::pair<std::size_t, std::size_t>, int> shared;
  for (const Face& face : faces) {
    bool has_edge = false;
    for (std::size_t i = 0; i < face.ring.size(); ++i) {
      const std::size_t a = face.ring[i], b = face.ring[(i + 1) % face.ring.size()];
      if (a == face.s && b == face.t) {
        has_edge = true;
        continue;
      }
      const auto key = std::make_pair(std::min(a, b), std::max(a, b));
      if (!bisectors.count(key)) validation_failure("FACE_BOUNDARY_INVALID", "A face side is neither its contour edge nor a reported bisector");
      ++shared[key];
    }
    if (!has_edge) validation_failure("FACE_BOUNDARY_INVALID", "A face does not contain its contour edge");
  }
  for (const auto& key : bisectors) {
    if (shared[key] != 2) validation_failure("FACE_BOUNDARY_INVALID", "A bisector is not shared by exactly two faces");
  }
  checks["face_boundaries_are_edges_or_shared_bisectors"] = true;

  // Face areas sum to the region area (exact).
  Q region = exact_area(source.rings[0]);
  for (std::size_t h = 1; h < source.rings.size(); ++h) region += exact_area(source.rings[h]);  // holes are clockwise: negative
  if (exterior) {
    region = Q(exact_of(frame[1]) - exact_of(frame[0])) * Q(exact_of(frame[3]) - exact_of(frame[2])) - region;
  }
  const LD sum = static_cast<LD>(area_sum.get_d()), want = static_cast<LD>(region.get_d());
  if (std::fabs(sum - want) > kTolerance * (1 + want)) validation_failure("AREA_MISMATCH", "The face areas do not sum to the region area");
  checks["face_areas_sum_to_region_area"] = true;
  return concluded(request, validator, checks,
                   {{"node_count", node_count}, {"face_count", faces.size()}, {"region_area", region.get_d()},
                    {"face_area_sum", area_sum.get_d()}, {"length_tolerance_relative_to_diagonal", static_cast<double>(kTolerance)},
                    {"independence", "exact rational point-in-ring, face areas and contour comparison on the reported binary64 values; long double line and segment distances; no CGAL header"}});
}

// ---------------------------------------------------------------------------------------------------------
// Offset validator
// ---------------------------------------------------------------------------------------------------------

bool is_convex(const std::vector<V2>& ring) {
  const std::size_t n = ring.size();
  for (std::size_t i = 0; i < n; ++i) {
    const Pt a = to_exact(ring[i]), b = to_exact(ring[(i + 1) % n]), c = to_exact(ring[(i + 2) % n]);
    if ((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0]) < 0) return false;
  }
  return true;
}

std::vector<P> clip(const std::vector<P>& polygon, const P& a, const P& b, LD c) {
  std::vector<P> result;
  const std::size_t n = polygon.size();
  for (std::size_t i = 0; i < n; ++i) {
    const P& p = polygon[i];
    const P& q = polygon[(i + 1) % n];
    const LD sp = line_distance(p, a, b) - c, sq = line_distance(q, a, b) - c;
    if (sp >= 0) result.push_back(p);
    if ((sp >= 0) != (sq >= 0)) {
      const LD t = sp / (sp - sq);
      result.push_back({p.x + t * (q.x - p.x), p.y + t * (q.y - p.y)});
    }
  }
  return result;
}

LD polygon_area(const std::vector<P>& polygon) {
  LD twice = 0;
  for (std::size_t i = 0; i < polygon.size(); ++i) twice += cross(polygon[i], polygon[(i + 1) % polygon.size()]);
  return twice / 2;
}

// Upper bound proof that the true offset region is empty: sup of the distance to the boundary over the polygon.
bool inradius_below(const Source& source, LD d, LD tol, LD diagonal) {
  auto inside = [&](const P& p) {
    int crossings = 0;
    for (const auto& ring : source.rings) {
      for (std::size_t i = 0; i < ring.size(); ++i) {
        const P a = to_p(ring[i]), b = to_p(ring[(i + 1) % ring.size()]);
        if ((a.y > p.y) != (b.y > p.y) && p.x < a.x + (p.y - a.y) * (b.x - a.x) / (b.y - a.y)) ++crossings;
      }
    }
    return crossings % 2 == 1;
  };
  auto g = [&](const P& p) {
    if (!inside(p)) return LD(0);
    LD best = std::numeric_limits<LD>::infinity();
    for (const auto& ring : source.rings) {
      for (std::size_t i = 0; i < ring.size(); ++i) best = std::min(best, segment_distance(p, to_p(ring[i]), to_p(ring[(i + 1) % ring.size()])));
    }
    return best;
  };
  LD low[2] = {1e300L, 1e300L}, high[2] = {-1e300L, -1e300L};
  for (const auto& v : source.rings[0]) {
    for (int a = 0; a < 2; ++a) {
      low[a] = std::min<LD>(low[a], v[a]);
      high[a] = std::max<LD>(high[a], v[a]);
    }
  }
  struct Cell {
    LD cx, cy, half, ub;
    bool operator<(const Cell& other) const { return ub < other.ub; }
  };
  const LD side = std::max(high[0] - low[0], high[1] - low[1]) / 2;
  std::priority_queue<Cell> queue;
  auto push = [&](LD cx, LD cy, LD half) { queue.push({cx, cy, half, g({cx, cy}) + half * std::sqrt(LD(2))}); };
  push((low[0] + high[0]) / 2, (low[1] + high[1]) / 2, side);
  (void)diagonal;
  std::size_t nodes = 0;
  while (!queue.empty()) {
    const Cell cell = queue.top();
    queue.pop();
    if (cell.ub <= d + tol) return true;
    if (g({cell.cx, cell.cy}) > d + tol || ++nodes > kNodeBudget) return false;
    const LD h = cell.half / 2;
    for (int sx = -1; sx <= 1; sx += 2) {
      for (int sy = -1; sy <= 1; sy += 2) push(cell.cx + sx * h, cell.cy + sy * h, h);
    }
  }
  return true;
}

Json run_offset(const Request& request) {
  const std::string validator = "polygon.validate.offset";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"offset"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "polygon_offset");
  const std::string operation = report.value("operation", std::string());
  bool exterior = false;
  if (operation == "polygon.offset.exterior") {
    exterior = true;
  } else if (operation != "polygon.offset.interior") {
    validation_failure("PARAMETER_MISMATCH", "Report is not a polygon offset report");
  }
  const std::string unit = request.inputs[1].unit;
  const double offset = positive_length(request.parameters.at("offset"), "offset", unit);
  Json checks;
  const auto results = batch2::check_report_frame(report, operation, request.parameters,
                                                  {{"polygon_sha256", &request.inputs[1]}}, checks);
  const Source source = load_source(request.inputs[1], !exterior);
  if (report.value("length_unit", std::string()) != unit || results.value("length_unit", std::string()) != unit ||
      results.value("area_unit", std::string()) != unit + "^2") {
    validation_failure("UNIT_MISMATCH", "The report units differ from the polygon units");
  }
  if (results.value("offset_kind", std::string()) != (exterior ? "exterior" : "interior") ||
      number(require_member(results, "offset", "results"), "offset") != offset) {
    validation_failure("PARAMETER_MISMATCH", "The reported offset kind or distance differs from the request");
  }
  const Json jr = array_member(results, "rings", "results");
  if (jr.size() > 64) validation_failure("REPORT_SCHEMA_MISMATCH", "Too many offset rings");
  std::vector<std::vector<V2>> rings;
  for (const Json& item : jr) {
    if (!item.is_object()) validation_failure("REPORT_SCHEMA_MISMATCH", "An offset ring must be an object");
    const Json points = array_member(item, "points", "ring");
    if (points.size() < 3 || points.size() > 400) validation_failure("REPORT_SCHEMA_MISMATCH", "An offset ring needs 3 to 400 points");
    rings.emplace_back();
    for (const Json& point : points) {
      if (!point.is_array() || point.size() != 2) validation_failure("REPORT_SCHEMA_MISMATCH", "An offset point must be a pair");
      rings.back().push_back({number(point[0], "offset point"), number(point[1], "offset point")});
    }
  }
  if (require_member(require_member(report, "summary", "report"), "ring_count", "summary") != rings.size()) {
    validation_failure("REPORT_SCHEMA_MISMATCH", "The summary ring count differs from the listed rings");
  }
  checks["report_schema_and_units_valid"] = true;

  const LD d = offset;
  const LD diagonal = diagonal_of(source);
  const LD tol = kTolerance * (1 + diagonal + d);
  // Source edges (oriented: interior on the left).
  struct Edge {
    P a, b;
  };
  std::vector<Edge> edges;
  for (const auto& ring : source.rings) {
    for (std::size_t i = 0; i < ring.size(); ++i) edges.push_back({to_p(ring[i]), to_p(ring[(i + 1) % ring.size()])});
  }
  std::vector<Ring> source_exact;
  for (const auto& ring : source.rings) source_exact.push_back(exact_ring(ring));
  const LD side = exterior ? -d : d;
  for (const auto& ring : rings) {
    check_polygon_with_holes(exact_ring(ring), {}, true);
    for (std::size_t i = 0; i < ring.size(); ++i) {
      const P p = to_p(ring[i]), q = to_p(ring[(i + 1) % ring.size()]);
      bool matched = false;
      for (const Edge& e : edges) {
        const LD length = norm(q - p);
        if (std::fabs(cross(e.b - e.a, q - p)) / (norm(e.b - e.a) * length) > kTolerance) continue;
        if (std::fabs(line_distance(p, e.a, e.b) - side) <= tol && std::fabs(line_distance(q, e.a, e.b) - side) <= tol) {
          matched = true;
          break;
        }
      }
      if (!matched) validation_failure("OFFSET_EDGE_MISMATCH", "An offset edge is not parallel to a source edge at the offset distance");
    }
  }
  checks["offset_edges_parallel_at_offset_distance"] = true;
  for (const auto& ring : rings) {
    for (const auto& v : ring) {
      LD nearest = std::numeric_limits<LD>::infinity();
      for (const Edge& e : edges) nearest = std::min(nearest, segment_distance(to_p(v), e.a, e.b));
      if (nearest < d - tol) validation_failure("OFFSET_TOO_CLOSE", "An offset vertex is closer to the source boundary than the offset");
    }
  }
  checks["offset_vertices_clear_of_source_boundary"] = true;
  for (const auto& ring : rings) {
    for (const auto& v : ring) {
      const int where = point_in_ring(to_exact(v), source_exact[0]);
      bool ok;
      if (exterior) {
        ok = where == -1;
      } else {
        ok = where == 1;
        for (std::size_t h = 1; h < source_exact.size() && ok; ++h) ok = point_in_ring(to_exact(v), source_exact[h]) == -1;
      }
      if (!ok) validation_failure("OFFSET_WRONG_SIDE", "An offset vertex lies on the wrong side of the source polygon");
    }
  }
  checks["offset_vertices_on_correct_side"] = true;

  // Extent: independent construction.
  std::string certification;
  const bool convex = source.rings.size() == 1 && is_convex(source.rings[0]);
  LD ring_area_sum = 0;
  for (const auto& ring : rings) {
    std::vector<P> polygon;
    for (const auto& v : ring) polygon.push_back(to_p(v));
    ring_area_sum += std::fabs(polygon_area(polygon));
  }
  if (exterior && rings.empty()) validation_failure("OFFSET_EMPTY_INVALID", "An exterior offset is never empty");
  if (convex) {
    // Intersection of the shifted half-planes (the mitered offset of a convex polygon).
    LD low[2] = {1e300L, 1e300L}, high[2] = {-1e300L, -1e300L};
    for (const auto& v : source.rings[0]) {
      for (int a = 0; a < 2; ++a) {
        low[a] = std::min<LD>(low[a], v[a]);
        high[a] = std::max<LD>(high[a], v[a]);
      }
    }
    const LD margin = 1e4L * (d + diagonal);
    std::vector<P> region = {{low[0] - margin, low[1] - margin}, {high[0] + margin, low[1] - margin},
                             {high[0] + margin, high[1] + margin}, {low[0] - margin, high[1] + margin}};
    for (const Edge& e : edges) region = clip(region, e.a, e.b, side);
    for (const P& p : region) {
      if (p.x <= low[0] - margin * 0.999L || p.x >= high[0] + margin * 0.999L || p.y <= low[1] - margin * 0.999L || p.y >= high[1] + margin * 0.999L) {
        validation_failure("OFFSET_EXTENT_UNCERTIFIED", "The independent construction is unbounded for this polygon");
      }
    }
    const LD expected = region.size() < 3 ? 0 : std::fabs(polygon_area(region));
    const LD area_tol = kTolerance * (1 + expected + diagonal * diagonal);
    if (expected <= area_tol) {
      if (!rings.empty() && ring_area_sum > area_tol) validation_failure("OFFSET_EXTENT_MISMATCH", "The offset is not empty although the shifted half-planes do not overlap");
      certification = "convex_half_plane_intersection_empty";
    } else {
      if (rings.size() != 1) validation_failure("OFFSET_EXTENT_MISMATCH", "A convex polygon offset must be exactly one ring");
      if (std::fabs(ring_area_sum - expected) > area_tol) validation_failure("OFFSET_AREA_MISMATCH", "The offset area differs from the half-plane intersection area");
      certification = "convex_half_plane_intersection";
    }
    // Axis-aligned rectangle: exact rational (w -/+ 2d)(h -/+ 2d).
    const auto& r = source.rings[0];
    if (r.size() == 4) {
      bool axis = true;
      for (std::size_t i = 0; i < 4; ++i) axis = axis && (r[i][0] == r[(i + 1) % 4][0] || r[i][1] == r[(i + 1) % 4][1]);
      if (axis) {
        Q lo_x = exact_of(r[0][0]), hi_x = lo_x, lo_y = exact_of(r[0][1]), hi_y = lo_y;
        for (const auto& v : r) {
          lo_x = std::min(lo_x, exact_of(v[0]));
          hi_x = std::max(hi_x, exact_of(v[0]));
          lo_y = std::min(lo_y, exact_of(v[1]));
          hi_y = std::max(hi_y, exact_of(v[1]));
        }
        const Q w = hi_x - lo_x, h = hi_y - lo_y;
        const Q shift = Q(2) * exact_of(offset) * (exterior ? 1 : -1);
        const Q rw = w + shift, rh = h + shift;
        const bool empty = rw <= 0 || rh <= 0;
        const LD exact_expected = empty ? 0 : static_cast<LD>(Q(rw * rh).get_d());
        if (empty != rings.empty() && !(empty && ring_area_sum <= area_tol)) {
          validation_failure("OFFSET_AREA_MISMATCH", "The rectangle offset emptiness differs from the exact formula");
        }
        if (std::fabs(ring_area_sum - exact_expected) > area_tol) {
          validation_failure("OFFSET_AREA_MISMATCH", "The rectangle offset area differs from the exact formula (w -/+ 2d)(h -/+ 2d)");
        }
        certification = "axis_aligned_rectangle_exact_formula";
      }
    }
  } else if (rings.empty()) {
    if (!inradius_below(source, d, tol, diagonal)) {
      validation_failure("OFFSET_EMPTY_NOT_JUSTIFIED", "The empty offset is not justified: the offset does not exceed the inradius bound");
    }
    certification = "empty_certified_by_inradius_bound";
  } else {
    certification = "not_certified_nonconvex_completeness";
  }
  checks["offset_extent_verified_as_declared"] = true;
  return concluded(request, validator, checks,
                   {{"ring_count", rings.size()}, {"extent_certification", certification},
                    {"offset_area_sum", static_cast<double>(ring_area_sum)},
                    {"length_tolerance_relative_to_diagonal", static_cast<double>(kTolerance)},
                    {"independence", "long double parallel-line and segment distances, exact rational point-in-ring, half-plane intersection for convex sources, exact rational rectangle formula; completeness of non-empty offsets of non-convex sources is not certified; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> skeleton_validators() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "polygon.validate.straight_skeleton", {"GeometryQueryReport", "PolygonWithHoles2"}, "ValidationReport", "validator",
      run_skeleton, {"Straight_skeleton_2"}, "GMP rationals and long double (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "report_schema_and_units_valid", "contour_matches_source_polygon",
             "one_face_per_contour_edge", "nodes_strictly_inside_region", "node_time_equals_distance_to_defining_edge_lines",
             "node_clear_of_boundary_at_node_time", "faces_positive_area_on_interior_side_of_edge",
             "face_boundaries_are_edges_or_shared_bisectors", "face_areas_sum_to_region_area"},
            {"candidate", "polygon"},
            "exact rational point-in-ring, face areas and contour comparison on the reported binary64 values; long double line and segment distances; no CGAL header")));
  result.push_back(query_definition(
      "polygon.validate.offset", {"GeometryQueryReport", "PolygonWithHoles2"}, "ValidationReport", "validator", run_offset,
      {"Straight_skeleton_2"}, "GMP rationals and long double (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "report_schema_and_units_valid", "offset_edges_parallel_at_offset_distance",
             "offset_vertices_clear_of_source_boundary", "offset_vertices_on_correct_side", "offset_extent_verified_as_declared"},
            {"candidate", "polygon"},
            "long double parallel-line and segment distances, exact rational point-in-ring, half-plane intersection for convex sources, exact rational rectangle formula; completeness of non-empty offsets of non-convex sources is not certified; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch5
