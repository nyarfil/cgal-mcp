// Independent validator for Boolean polygon set operations (7.12.04). No CGAL header is
// included. The expected boundary of A op B is derived with exact GMP rational arithmetic:
// every edge of each operand is split at all points where the other operand's boundary
// meets it, each piece is classified (inside / outside / on the boundary with the same or
// the opposite direction) and kept according to the set-operation rule. The resulting
// directed boundary chain is compared with the reported polygons-with-holes after both
// are normalised into unit segments between all collected points.

#include "b2_geometry.h"

#include <algorithm>

namespace cgal_master::batch2 {
namespace {

using query_ops::enum_parameter;
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
Q cross2(const P2& a, const P2& b) { return a.x * b.y - a.y * b.x; }
Q dot2(const P2& a, const P2& b) { return a.x * b.x + a.y * b.y; }

using Ring = std::vector<P2>;
struct Segment {
  P2 from, to;
  bool operator==(const Segment& other) const { return from == other.from && to == other.to; }
  bool operator<(const Segment& other) const {
    return from != other.from ? from < other.from : to < other.to;
  }
};

constexpr std::size_t kMaximumVertices = 200;

Q signed_area2(const Ring& ring) {  // twice the signed area
  Q total = 0;
  for (std::size_t i = 0; i < ring.size(); ++i) total += cross2(ring[i], ring[(i + 1) % ring.size()]);
  return total;
}

bool point_on_segment2(const P2& p, const P2& a, const P2& b) {
  if (cross2(sub(b, a), sub(p, a)) != 0) return false;
  const Q s = dot2(sub(p, a), sub(b, a));
  return s >= 0 && s <= dot2(sub(b, a), sub(b, a));
}

int sign_of(const Q& v) { return v > 0 ? 1 : (v < 0 ? -1 : 0); }

bool segments_touch(const P2& a, const P2& b, const P2& c, const P2& d) {
  const int o1 = sign_of(cross2(sub(b, a), sub(c, a))), o2 = sign_of(cross2(sub(b, a), sub(d, a)));
  const int o3 = sign_of(cross2(sub(d, c), sub(a, c))), o4 = sign_of(cross2(sub(d, c), sub(b, c)));
  if (o1 != o2 && o3 != o4 && o1 * o2 <= 0 && o3 * o4 <= 0) return true;
  return (o1 == 0 && point_on_segment2(c, a, b)) || (o2 == 0 && point_on_segment2(d, a, b)) ||
         (o3 == 0 && point_on_segment2(a, c, d)) || (o4 == 0 && point_on_segment2(b, c, d));
}

Ring read_operand(const ArtifactInput& input, const std::string& context) {
  const auto raw = read_polygon(input);
  if (raw.size() < 3 || raw.size() > kMaximumVertices) {
    validation_failure("POLYGON_SIZE", context + " must have 3.." + std::to_string(kMaximumVertices) + " vertices");
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
        // Shared vertex only: no fold-back along the same line.
        const P2 &shared = (j == i + 1) ? b : a;
        const P2 &p = (j == i + 1) ? a : b, &q = (j == i + 1) ? d : c;
        if (cross2(sub(p, shared), sub(q, shared)) == 0 && dot2(sub(p, shared), sub(q, shared)) > 0) {
          validation_failure("POLYGON_NOT_SIMPLE", context + " has overlapping adjacent edges");
        }
      } else if (segments_touch(a, b, c, d)) {
        validation_failure("POLYGON_NOT_SIMPLE", context + " is not simple");
      }
    }
  }
  if (signed_area2(ring) == 0) validation_failure("POLYGON_ZERO_AREA", context + " has zero area");
  if (signed_area2(ring) < 0) std::reverse(ring.begin(), ring.end());
  return ring;
}

enum class Place { Inside, Outside, OnSame, OnOpposite };

Place classify(const P2& midpoint, const Segment& piece, const Ring& other) {
  const std::size_t n = other.size();
  for (std::size_t i = 0; i < n; ++i) {
    const P2 &a = other[i], &b = other[(i + 1) % n];
    if (point_on_segment2(midpoint, a, b)) {
      return dot2(sub(piece.to, piece.from), sub(b, a)) > 0 ? Place::OnSame : Place::OnOpposite;
    }
  }
  bool inside = false;
  for (std::size_t i = 0; i < n; ++i) {
    const P2 &a = other[i], &b = other[(i + 1) % n];
    if ((a.y > midpoint.y) != (b.y > midpoint.y)) {
      const Q x = a.x + (midpoint.y - a.y) * (b.x - a.x) / (b.y - a.y);
      if (midpoint.x < x) inside = !inside;
    }
  }
  return inside ? Place::Inside : Place::Outside;
}

// Splits each edge of `ring` at all points where `other` meets it and classifies the pieces.
std::vector<std::pair<Segment, Place>> classified_pieces(const Ring& ring, const Ring& other) {
  std::vector<std::pair<Segment, Place>> result;
  const std::size_t n = ring.size(), m = other.size();
  for (std::size_t i = 0; i < n; ++i) {
    const P2 &a = ring[i], &b = ring[(i + 1) % n];
    const P2 e = sub(b, a);
    std::vector<Q> params{Q(0), Q(1)};
    for (std::size_t j = 0; j < m; ++j) {
      const P2 &c = other[j], &d = other[(j + 1) % m];
      const P2 f = sub(d, c);
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
      const P2 from{a.x + params[k] * e.x, a.y + params[k] * e.y};
      const P2 to{a.x + params[k + 1] * e.x, a.y + params[k + 1] * e.y};
      const P2 mid{(from.x + to.x) / 2, (from.y + to.y) / 2};
      const Segment piece{from, to};
      result.emplace_back(piece, classify(mid, piece, other));
    }
  }
  return result;
}

P2 reported_point(const Json& value, const std::string& context) {
  if (!value.is_array() || value.size() != 2) validation_failure("REPORT_VALUE_INVALID", context + " must be [x,y]");
  return {reported_rational(value[0], context), reported_rational(value[1], context)};
}

Ring reported_ring(const Json& value, const std::string& context) {
  if (!value.is_array() || value.size() < 3 || value.size() > 4 * kMaximumVertices) {
    validation_failure("REPORT_VALUE_INVALID", context + " must be a ring of at least three points");
  }
  Ring ring;
  for (const auto& item : value) ring.push_back(reported_point(item, context));
  return ring;
}

Json run_polygon_boolean_validator(const Request& request) {
  const std::string validator = "polygon.validate.boolean";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {"operation"});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto operation = enum_parameter(request, "operation", {"join", "intersection", "difference"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "polygon_boolean");
  const Ring a = read_operand(request.inputs[1], "first operand");
  const Ring b = read_operand(request.inputs[2], "second operand");
  Json checks;
  const auto results = check_report_frame(report, "polygon.boolean", Json{{"operation", operation}},
                                          {{"first_sha256", &request.inputs[1]}, {"second_sha256", &request.inputs[2]}},
                                          checks);
  checks["operands_simple_nonzero_area"] = true;

  // Expected boundary chain.
  std::vector<Segment> expected;
  for (const auto& [piece, place] : classified_pieces(a, b)) {
    bool keep = false;
    if (operation == "join") keep = place == Place::Outside || place == Place::OnSame;
    else if (operation == "intersection") keep = place == Place::Inside || place == Place::OnSame;
    else keep = place == Place::Outside || place == Place::OnOpposite;
    if (keep) expected.push_back(piece);
  }
  for (const auto& [piece, place] : classified_pieces(b, a)) {
    if (operation == "join" && place == Place::Outside) expected.push_back(piece);
    else if (operation == "intersection" && place == Place::Inside) expected.push_back(piece);
    else if (operation == "difference" && place == Place::Inside) expected.push_back({piece.to, piece.from});
  }

  // Reported chain: outer rings counter-clockwise, holes clockwise.
  const auto polygons = require_member(results, "polygons", "results");
  if (!polygons.is_array()) validation_failure("REPORT_VALUE_INVALID", "polygons must be an array");
  std::vector<Segment> reported;
  for (const auto& polygon : polygons) {
    const Ring outer = reported_ring(require_member(polygon, "outer", "polygon"), "outer");
    if (signed_area2(outer) <= 0) validation_failure("RING_ORIENTATION", "An outer boundary is not counter-clockwise");
    for (std::size_t i = 0; i < outer.size(); ++i) reported.push_back({outer[i], outer[(i + 1) % outer.size()]});
    const auto holes = require_member(polygon, "holes", "polygon");
    if (!holes.is_array()) validation_failure("REPORT_VALUE_INVALID", "holes must be an array");
    for (const auto& hole_json : holes) {
      const Ring hole = reported_ring(hole_json, "hole");
      if (signed_area2(hole) >= 0) validation_failure("RING_ORIENTATION", "A hole is not clockwise");
      for (std::size_t i = 0; i < hole.size(); ++i) reported.push_back({hole[i], hole[(i + 1) % hole.size()]});
    }
  }
  checks["rings_oriented_outer_ccw_hole_cw"] = true;

  // Normalise both chains into unit segments between all collected points.
  std::set<P2> points;
  for (const auto& s : expected) {
    points.insert(s.from);
    points.insert(s.to);
  }
  for (const auto& s : reported) {
    points.insert(s.from);
    points.insert(s.to);
  }
  auto unit_segments = [&](const std::vector<Segment>& chain) {
    std::map<Segment, int> result;
    for (const auto& s : chain) {
      std::vector<std::pair<Q, P2>> on;
      const P2 e = sub(s.to, s.from);
      for (const auto& p : points) {
        if (point_on_segment2(p, s.from, s.to)) on.emplace_back(dot2(sub(p, s.from), e), p);
      }
      std::sort(on.begin(), on.end(), [](const auto& l, const auto& r) { return l.first < r.first; });
      for (std::size_t i = 0; i + 1 < on.size(); ++i) ++result[Segment{on[i].second, on[i + 1].second}];
    }
    return result;
  };
  const auto expected_units = unit_segments(expected);
  const auto reported_units = unit_segments(reported);
  if (expected_units != reported_units) {
    validation_failure("BOUNDARY_CHAIN_MISMATCH",
                       "The reported polygons do not have the exact boundary of the set operation");
  }
  for (const auto& [segment, count] : reported_units) {
    if (count != 1) validation_failure("BOUNDARY_CHAIN_MISMATCH", "A boundary segment is reported more than once");
  }
  checks["boundary_chain_equals_exact_set_operation"] = true;
  return concluded(request, validator, checks,
                   {{"operation", operation}, {"expected_boundary_segment_count", expected_units.size()},
                    {"reported_polygon_count", polygons.size()},
                    {"independence", "exact rational edge splitting, point classification and unit-segment boundary chain comparison; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> polygon_validator_operations() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "polygon.validate.boolean", {"GeometryQueryReport", "Polygon2", "Polygon2"}, "ValidationReport", "validator",
      run_polygon_boolean_validator, {"Boolean_set_operations_2"}, "exact:GMP",
      vinfo({"parameters_match", "source_matches", "operands_simple_nonzero_area", "rings_oriented_outer_ccw_hole_cw",
             "boundary_chain_equals_exact_set_operation"},
            {"candidate", "first", "second"},
            "exact rational edge splitting, point classification and unit-segment boundary chain comparison; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch2
