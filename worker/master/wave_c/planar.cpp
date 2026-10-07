// Wave C planar adapters: 2D convex hull and polygon(-with-holes) operations,
// each with an independent exact validator.
#include "wave_c_common.h"

#include <CGAL/Polygon_2.h>
#include <CGAL/Polygon_with_holes_2.h>
#include <CGAL/convex_hull_2.h>

#include <algorithm>
#include <cmath>
#include <iterator>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace cgal_master::wave_c {
namespace {

using EP2 = Epeck::Point_2;
using ES2 = Epeck::Segment_2;
using Polygon = CGAL::Polygon_2<Epeck>;
using PolygonWithHoles = CGAL::Polygon_with_holes_2<Epeck>;
using FT = Epeck::FT;

EP2 exact_point(const XY& point) { return EP2(point[0], point[1]); }

std::string area_unit(const std::string& unit) { return unit + "^2"; }

// ---------------------------------------------------------------------------
// Independent exact primitives used only by validators (no CGAL algorithms).
// ---------------------------------------------------------------------------

int sign_of(const FT& value) {
  if (value > FT(0)) return 1;
  if (value < FT(0)) return -1;
  return 0;
}

// Exact (filtered) orientation predicate on the binary64 input coordinates.
int turn(const XY& a, const XY& b, const XY& c) {
  return static_cast<int>(CGAL::orientation(Epick::Point_2(a[0], a[1]),
                                            Epick::Point_2(b[0], b[1]),
                                            Epick::Point_2(c[0], c[1])));
}

bool between_on_line(const XY& a, const XY& b, const XY& p) {
  return std::min(a[0], b[0]) <= p[0] && p[0] <= std::max(a[0], b[0]) &&
         std::min(a[1], b[1]) <= p[1] && p[1] <= std::max(a[1], b[1]);
}

bool on_segment(const XY& a, const XY& b, const XY& p) {
  return turn(a, b, p) == 0 && between_on_line(a, b, p);
}

bool segments_touch(const XY& a, const XY& b, const XY& c, const XY& d) {
  const int d1 = turn(a, b, c), d2 = turn(a, b, d), d3 = turn(c, d, a), d4 = turn(c, d, b);
  if (d1 * d2 < 0 && d3 * d4 < 0) return true;
  return (d1 == 0 && between_on_line(a, b, c)) || (d2 == 0 && between_on_line(a, b, d)) ||
         (d3 == 0 && between_on_line(c, d, a)) || (d4 == 0 && between_on_line(c, d, b));
}

// Simple: no repeated vertices, non-adjacent edges disjoint, adjacent edges
// share only their common endpoint.
bool independent_simple(const std::vector<XY>& ring) {
  const std::size_t n = ring.size();
  if (n < 3) return false;
  std::set<XY> distinct(ring.begin(), ring.end());
  if (distinct.size() != n) return false;
  for (std::size_t i = 0; i < n; ++i) {
    const XY& a = ring[i];
    const XY& b = ring[(i + 1) % n];
    for (std::size_t j = i + 1; j < n; ++j) {
      const XY& c = ring[j];
      const XY& d = ring[(j + 1) % n];
      const bool adjacent = (j == i + 1) || (i == 0 && j == n - 1);
      if (!adjacent) {
        if (segments_touch(a, b, c, d)) return false;
        continue;
      }
      // Adjacent edges: the far endpoint of one must not lie on the other.
      if (j == i + 1) {
        if (turn(a, b, d) == 0 && (on_segment(a, b, d) || on_segment(c, d, a))) return false;
      } else {
        if (turn(c, d, b) == 0 && (on_segment(c, d, b) || on_segment(a, b, c))) return false;
      }
    }
  }
  return true;
}

FT independent_twice_area(const std::vector<XY>& ring) {
  // Fan from the first vertex (the producer uses CGAL's area()).
  FT total(0);
  const FT ox(ring[0][0]), oy(ring[0][1]);
  for (std::size_t i = 1; i + 1 < ring.size(); ++i) {
    const FT ax = FT(ring[i][0]) - ox, ay = FT(ring[i][1]) - oy;
    const FT bx = FT(ring[i + 1][0]) - ox, by = FT(ring[i + 1][1]) - oy;
    total += ax * by - ay * bx;
  }
  return total;
}

bool independent_convex(const std::vector<XY>& ring, int orientation) {
  const std::size_t n = ring.size();
  for (std::size_t i = 0; i < n; ++i) {
    const int t = turn(ring[i], ring[(i + 1) % n], ring[(i + 2) % n]);
    if (t != 0 && t != orientation) return false;
  }
  return true;
}

// Even-odd point location against all rings; boundary first.
std::string independent_location(const PolygonWithHolesData& polygon, const XY& p) {
  std::vector<const std::vector<XY>*> rings = {&polygon.outer};
  for (const auto& hole : polygon.holes) rings.push_back(&hole);
  bool inside = false;
  for (const auto* ring : rings) {
    const std::size_t n = ring->size();
    for (std::size_t i = 0; i < n; ++i) {
      const XY& a = (*ring)[i];
      const XY& b = (*ring)[(i + 1) % n];
      if (on_segment(a, b, p)) return "boundary";
      // Half-open rule on y for the upward ray crossing test.
      const bool a_above = a[1] > p[1];
      const bool b_above = b[1] > p[1];
      if (a_above != b_above) {
        // Edge crosses the horizontal line through p; does it cross to the right of p?
        const int side = turn(a, b, p);
        if ((b[1] > a[1] && side > 0) || (b[1] < a[1] && side < 0)) inside = !inside;
      }
    }
  }
  return inside ? "inside" : "outside";
}

// ---------------------------------------------------------------------------
// Producer-side helpers (CGAL Polygon package).
// ---------------------------------------------------------------------------

Polygon make_polygon(const std::vector<XY>& ring) {
  Polygon polygon;
  for (const auto& point : ring) polygon.push_back(exact_point(point));
  return polygon;
}

struct PolygonAnalysis {
  std::vector<Polygon> rings;
  std::vector<bool> simple;
  bool valid = true;
  std::vector<std::string> reasons;
};

PolygonAnalysis analyse(const PolygonWithHolesData& data) {
  PolygonAnalysis analysis;
  analysis.rings.push_back(make_polygon(data.outer));
  for (const auto& hole : data.holes) analysis.rings.push_back(make_polygon(hole));
  for (std::size_t r = 0; r < analysis.rings.size(); ++r) {
    const bool simple = analysis.rings[r].is_simple();
    analysis.simple.push_back(simple);
    if (!simple) {
      analysis.valid = false;
      analysis.reasons.push_back((r == 0 ? std::string("outer") : "hole " + std::to_string(r - 1)) +
                                 " ring is not simple");
    }
  }
  if (!analysis.valid) return analysis;
  for (std::size_t r = 0; r < analysis.rings.size(); ++r) {
    for (std::size_t s = r + 1; s < analysis.rings.size(); ++s) {
      bool touch = false;
      for (auto e = analysis.rings[r].edges_begin(); e != analysis.rings[r].edges_end() && !touch;
           ++e) {
        for (auto f = analysis.rings[s].edges_begin(); f != analysis.rings[s].edges_end(); ++f) {
          if (CGAL::do_intersect(*e, *f)) {
            touch = true;
            break;
          }
        }
      }
      if (touch) {
        analysis.valid = false;
        analysis.reasons.push_back("rings " + std::to_string(r) + " and " + std::to_string(s) +
                                   " intersect or touch");
      }
    }
  }
  if (!analysis.valid) return analysis;
  for (std::size_t h = 1; h < analysis.rings.size(); ++h) {
    if (analysis.rings[0].bounded_side(analysis.rings[h].vertex(0)) != CGAL::ON_BOUNDED_SIDE) {
      analysis.valid = false;
      analysis.reasons.push_back("hole " + std::to_string(h - 1) + " is not inside the outer ring");
    }
    for (std::size_t g = 1; g < analysis.rings.size(); ++g) {
      if (g != h &&
          analysis.rings[g].bounded_side(analysis.rings[h].vertex(0)) != CGAL::ON_UNBOUNDED_SIDE) {
        analysis.valid = false;
        analysis.reasons.push_back("hole " + std::to_string(h - 1) + " is nested in hole " +
                                   std::to_string(g - 1));
      }
    }
  }
  return analysis;
}

void require_planar_budget(std::size_t first, std::size_t second, const char* what) {
  if (first != 0 && second > kMaximumBruteForcePairs / first) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED",
                      std::string(what) + " exceeds the mandatory validation budget");
  }
}

Json bbox_json(const std::vector<XY>& points) {
  XY low = points.front(), high = points.front();
  for (const auto& point : points) {
    for (int axis = 0; axis < 2; ++axis) {
      low[axis] = std::min(low[axis], point[axis]);
      high[axis] = std::max(high[axis], point[axis]);
    }
  }
  return Json{{"min", xy_json(low)}, {"max", xy_json(high)}};
}

// ---------------------------------------------------------------------------
// hull.convex_2
// ---------------------------------------------------------------------------

void require_affine_rank_2(const std::vector<XY>& points) {
  const XY& first = points.front();
  auto second = std::find_if(points.begin() + 1, points.end(),
                             [&](const XY& point) { return point != first; });
  if (second == points.end()) {
    throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_2", "Point set has affine rank 0");
  }
  const auto third = std::find_if(second + 1, points.end(), [&](const XY& point) {
    return CGAL::orientation(Epick::Point_2(first[0], first[1]),
                             Epick::Point_2((*second)[0], (*second)[1]),
                             Epick::Point_2(point[0], point[1])) != CGAL::COLLINEAR;
  });
  if (third == points.end()) {
    throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_2",
                      "Point set has affine rank at most 1");
  }
}

Json run_convex_hull_2(const Request& request) {
  require_input_count(request, 1, "hull.convex_2");
  require_parameters(request, {});
  const auto points = read_point_set2(request.inputs[0]);
  if (points.size() < 3) {
    throw WorkerError("PRECONDITION_FAILED", "INSUFFICIENT_POINTS",
                      "At least three points are required for a 2D convex hull");
  }
  require_affine_rank_2(points);
  std::vector<Epick::Point_2> input;
  input.reserve(points.size());
  for (const auto& point : points) input.emplace_back(point[0], point[1]);
  std::vector<Epick::Point_2> hull;
  CGAL::convex_hull_2(input.begin(), input.end(), std::back_inserter(hull));
  if (hull.size() < 3) {
    throw WorkerError("INTERNAL", "INVALID_HULL_GENERATED", "CGAL produced a degenerate 2D hull");
  }
  Json ring = Json::array();
  std::vector<XY> hull_xy;
  for (const auto& point : hull) {
    hull_xy.push_back({point.x(), point.y()});
    ring.push_back(xy_json(hull_xy.back()));
  }
  const auto area = make_polygon(hull_xy).area();
  const auto& unit = request.inputs[0].unit;
  auto output = write_json_output(request, "polygon", "Polygon2", unit, Json{{"points", ring}});
  Json metrics = {{"input_point_count", points.size()},
                  {"hull_vertex_count", hull.size()},
                  {"orientation", "counterclockwise"},
                  {"area", exact_metric(area, area_unit(unit))},
                  {"algorithm", "CGAL::convex_hull_2"},
                  {"effective_kernel", kEpick}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json run_convex_enclosure_2_validator(const Request& request) {
  require_input_count(request, 2, "hull.validate.convex_enclosure_2");
  require_parameters(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto ring = read_polygon2(request.inputs[0]);
  const auto points = read_point_set2(request.inputs[1]);
  const std::size_t h = ring.size();
  std::set<XY> source(points.begin(), points.end());
  std::set<XY> vertices(ring.begin(), ring.end());
  if (vertices.size() != h) fail_validation("HULL_REPEATED_VERTEX", "Hull repeats a vertex");
  for (const auto& vertex : ring) {
    if (source.find(vertex) == source.end()) {
      fail_validation("HULL_VERTEX_NOT_IN_SOURCE", "A hull vertex is not a source point");
    }
  }
  for (std::size_t i = 0; i < h; ++i) {
    if (turn(ring[i], ring[(i + 1) % h], ring[(i + 2) % h]) <= 0) {
      fail_validation("HULL_NOT_STRICTLY_CONVEX_CCW",
                      "Hull has a non-left turn (not strictly convex counterclockwise)");
    }
  }
  int order_changes = 0;
  auto less = [](const XY& a, const XY& b) { return a < b; };
  bool order = less(ring[0], ring[1]);
  for (std::size_t i = 1; i <= h; ++i) {
    const bool next = less(ring[i % h], ring[(i + 1) % h]);
    if (next != order) ++order_changes;
    order = next;
  }
  if (order_changes != 2) {
    fail_validation("HULL_NOT_SIMPLE", "Hull ring winds more than once");
  }
  require_planar_budget(points.size(), h, "Hull enclosure check");
  std::size_t boundary = 0;
  for (const auto& point : points) {
    bool on_boundary = false;
    for (std::size_t i = 0; i < h; ++i) {
      const int side = turn(ring[i], ring[(i + 1) % h], point);
      if (side < 0) fail_validation("POINT_OUTSIDE_HULL", "A source point lies outside the hull");
      if (side == 0) on_boundary = true;
    }
    if (on_boundary) ++boundary;
  }
  const FT twice_area = independent_twice_area(ring);
  Json report = {
      {"checks",
       {{"vertices_are_source_points", true},
        {"strictly_convex_counterclockwise", true},
        {"simple_ring", true},
        {"all_source_points_enclosed", true},
        {"minimal_convex_enclosure", true}}},
      {"source_point_count", points.size()},
      {"distinct_source_point_count", source.size()},
      {"hull_vertex_count", h},
      {"boundary_point_count", boundary},
      {"area", exact_metric(twice_area / FT(2), area_unit(request.inputs[0].unit))},
      {"independence",
       "exact orientation predicates and order-change test; CGAL::convex_hull_2 is not called"}};
  return finish_validation(request, "hull.validate.convex_enclosure_2", std::move(report));
}

// ---------------------------------------------------------------------------
// polygon.analysis.properties
// ---------------------------------------------------------------------------

Json run_polygon_properties(const Request& request) {
  require_input_count(request, 1, "polygon.analysis.properties");
  require_parameters(request, {});
  const auto data = read_polygon_with_holes2(request.inputs[0]);
  const auto& unit = request.inputs[0].unit;
  const auto analysis = analyse(data);
  Json rings = Json::array();
  FT area(0), moment_x(0), moment_y(0);
  bool canonical = true;
  for (std::size_t r = 0; r < analysis.rings.size(); ++r) {
    const auto& polygon = analysis.rings[r];
    const bool simple = analysis.simple[r];
    const FT signed_area = polygon.area();
    std::string orientation = "unavailable";
    if (simple) {
      const auto value = polygon.orientation();
      orientation = value == CGAL::COUNTERCLOCKWISE ? "counterclockwise"
                    : value == CGAL::CLOCKWISE      ? "clockwise"
                                                    : "collinear";
    }
    if ((r == 0 && orientation != "counterclockwise") || (r > 0 && orientation != "clockwise")) {
      canonical = false;
    }
    double perimeter = 0;
    for (auto edge = polygon.edges_begin(); edge != polygon.edges_end(); ++edge) {
      perimeter += std::sqrt(CGAL::to_double(edge->squared_length()));
    }
    rings.push_back({{"role", r == 0 ? "outer" : "hole"},
                     {"ring_index", r},
                     {"vertex_count", polygon.size()},
                     {"simple", simple},
                     {"orientation", orientation},
                     {"convex", simple ? polygon.is_convex() : false},
                     {"signed_area", exact_metric(signed_area, area_unit(unit))},
                     {"perimeter", {{"approximate", perimeter}, {"unit", unit}}}});
    // Signed moments from CGAL's vertex circulation (shoelace on edges).
    FT ring_mx(0), ring_my(0);
    for (auto edge = polygon.edges_begin(); edge != polygon.edges_end(); ++edge) {
      const auto& a = edge->source();
      const auto& b = edge->target();
      const FT cross = a.x() * b.y() - b.x() * a.y();
      ring_mx += (a.x() + b.x()) * cross;
      ring_my += (a.y() + b.y()) * cross;
    }
    const int ring_sign = signed_area > FT(0) ? 1 : -1;
    const int weight = (r == 0 ? 1 : -1) * ring_sign;
    area += FT(weight) * signed_area;
    moment_x += FT(weight) * ring_mx / FT(6);
    moment_y += FT(weight) * ring_my / FT(6);
  }
  Json results = {{"rings", rings},
                  {"hole_count", data.holes.size()},
                  {"valid_polygon_with_holes", analysis.valid},
                  {"validity_reasons", analysis.reasons},
                  {"canonical_orientation", analysis.valid && canonical}};
  std::vector<XY> all = data.outer;
  for (const auto& hole : data.holes) all.insert(all.end(), hole.begin(), hole.end());
  results["bbox"] = bbox_json(all);
  if (analysis.valid && area > FT(0)) {
    // Polygon_with_holes_2 is the canonical container for the validated result.
    PolygonWithHoles container(analysis.rings[0],
                               std::next(analysis.rings.begin()), analysis.rings.end());
    results["area"] = exact_metric(area, area_unit(unit));
    results["area"]["available"] = true;
    const FT cx = moment_x / area, cy = moment_y / area;
    results["centroid"] = {{"available", true},
                           {"exact", Json::array({exact_string(cx), exact_string(cy)})},
                           {"approximate", Json::array({CGAL::to_double(cx), CGAL::to_double(cy)})},
                           {"unit", unit}};
    results["container_hole_count"] = container.number_of_holes();
  } else {
    results["area"] = {{"available", false},
                       {"reason", "area and centroid require a valid polygon with holes"}};
    results["centroid"] = {{"available", false},
                           {"reason", "area and centroid require a valid polygon with holes"}};
  }
  Json report = {{"schema_version", 1},
                 {"report_type", "Polygon2AnalysisReport"},
                 {"analysis_kind", "polygon_properties"},
                 {"operation", "polygon.analysis.properties"},
                 {"length_unit", unit},
                 {"source", {{"sha256", request.inputs[0].sha256}, {"type", "PolygonWithHoles2"}}},
                 {"results", results}};
  auto output = write_json_output(request, "analysis", "Polygon2AnalysisReport", "none", report);
  Json metrics = {{"valid_polygon_with_holes", analysis.valid},
                  {"hole_count", data.holes.size()},
                  {"canonical_orientation", analysis.valid && canonical},
                  {"effective_kernel", "CGAL::Exact_predicates_exact_constructions_kernel"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json run_polygon_properties_validator(const Request& request) {
  require_input_count(request, 2, "polygon.validate.properties_report");
  require_parameters(request, {});
  const auto report = read_report(request.inputs[0], "Polygon2AnalysisReport", "analysis_kind",
                                  "polygon_properties");
  const auto data = read_polygon_with_holes2(request.inputs[1]);
  const auto& unit = request.inputs[1].unit;
  if (report.value("length_unit", "") != unit ||
      report.value("/source/sha256"_json_pointer, "") != request.inputs[1].sha256) {
    fail_validation("REPORT_SOURCE_MISMATCH", "Report does not describe this polygon source");
  }
  const auto& results = report.at("results");
  std::vector<const std::vector<XY>*> rings = {&data.outer};
  for (const auto& hole : data.holes) rings.push_back(&hole);
  if (!results.contains("rings") || results.at("rings").size() != rings.size()) {
    fail_validation("RING_COUNT_MISMATCH", "Report ring count differs from the source");
  }
  bool all_simple = true, canonical = true;
  FT area(0), moment_x(0), moment_y(0);
  for (std::size_t r = 0; r < rings.size(); ++r) {
    const auto& ring = *rings[r];
    const auto& entry = results.at("rings")[r];
    const bool simple = independent_simple(ring);
    all_simple = all_simple && simple;
    const FT twice = independent_twice_area(ring);
    const int orientation_sign = sign_of(twice);
    const std::string orientation = !simple ? "unavailable"
                                    : orientation_sign > 0 ? "counterclockwise"
                                    : orientation_sign < 0 ? "clockwise"
                                                           : "collinear";
    if ((r == 0 && orientation != "counterclockwise") || (r > 0 && orientation != "clockwise")) {
      canonical = false;
    }
    const bool convex = simple && independent_convex(ring, orientation_sign);
    double perimeter = 0;
    for (std::size_t i = 0; i < ring.size(); ++i) {
      const auto& a = ring[i];
      const auto& b = ring[(i + 1) % ring.size()];
      perimeter += std::hypot(b[0] - a[0], b[1] - a[1]);
    }
    if (entry.value("simple", !simple) != simple ||
        entry.value("orientation", std::string()) != orientation ||
        entry.value("convex", !convex) != convex ||
        entry.value("vertex_count", std::size_t(0)) != ring.size() ||
        entry.value("/signed_area/exact"_json_pointer, std::string()) !=
            exact_string(twice / FT(2))) {
      fail_validation("RING_PROPERTY_MISMATCH",
                      "Ring " + std::to_string(r) + " properties differ from exact recomputation");
    }
    const double reported = entry.value("/perimeter/approximate"_json_pointer, -1.0);
    if (!(std::fabs(reported - perimeter) <= 1e-12 * std::max(1.0, perimeter))) {
      fail_validation("PERIMETER_MISMATCH", "Ring perimeter differs from recomputation");
    }
    // Moments by triangle fan from the first vertex (different decomposition).
    FT mx(0), my(0);
    const FT ox(ring[0][0]), oy(ring[0][1]);
    for (std::size_t i = 1; i + 1 < ring.size(); ++i) {
      const FT ax(ring[i][0]), ay(ring[i][1]), bx(ring[i + 1][0]), by(ring[i + 1][1]);
      const FT t = (ax - ox) * (by - oy) - (ay - oy) * (bx - ox);
      mx += t * (ox + ax + bx);
      my += t * (oy + ay + by);
    }
    const int weight = (r == 0 ? 1 : -1) * (orientation_sign > 0 ? 1 : -1);
    area += FT(weight) * twice / FT(2);
    moment_x += FT(weight) * mx / FT(6);
    moment_y += FT(weight) * my / FT(6);
  }
  bool valid = all_simple;
  for (std::size_t r = 0; valid && r < rings.size(); ++r) {
    for (std::size_t s = r + 1; valid && s < rings.size(); ++s) {
      const auto& a = *rings[r];
      const auto& b = *rings[s];
      for (std::size_t i = 0; valid && i < a.size(); ++i) {
        for (std::size_t j = 0; j < b.size(); ++j) {
          if (segments_touch(a[i], a[(i + 1) % a.size()], b[j], b[(j + 1) % b.size()])) {
            valid = false;
            break;
          }
        }
      }
    }
  }
  if (valid) {
    PolygonWithHolesData outer_only{data.outer, {}};
    for (std::size_t h = 0; valid && h < data.holes.size(); ++h) {
      if (independent_location(outer_only, data.holes[h][0]) != "inside") valid = false;
      for (std::size_t g = 0; valid && g < data.holes.size(); ++g) {
        PolygonWithHolesData other{data.holes[g], {}};
        if (g != h && independent_location(other, data.holes[h][0]) != "outside") valid = false;
      }
    }
  }
  if (results.value("valid_polygon_with_holes", !valid) != valid ||
      results.value("canonical_orientation", !(valid && canonical)) != (valid && canonical)) {
    fail_validation("VALIDITY_MISMATCH", "Polygon validity differs from exact recomputation");
  }
  if (valid != (results.value("validity_reasons", Json::array()).empty())) {
    fail_validation("VALIDITY_REASON_MISMATCH", "Validity reasons are inconsistent");
  }
  std::vector<XY> all = data.outer;
  for (const auto& hole : data.holes) all.insert(all.end(), hole.begin(), hole.end());
  if (results.value("bbox", Json()) != bbox_json(all)) {
    fail_validation("BBOX_MISMATCH", "Polygon bounding box differs");
  }
  Json area_value = nullptr, centroid_value = nullptr;
  if (valid) {
    if (results.value("/area/exact"_json_pointer, std::string()) != exact_string(area)) {
      fail_validation("AREA_MISMATCH", "Polygon area differs from exact recomputation");
    }
    const FT cx = moment_x / area, cy = moment_y / area;
    const Json centroid = Json::array({exact_string(cx), exact_string(cy)});
    if (results.value("/centroid/exact"_json_pointer, Json()) != centroid) {
      fail_validation("CENTROID_MISMATCH", "Polygon centroid differs from exact recomputation");
    }
    area_value = exact_string(area);
    centroid_value = centroid;
  } else if (results.value("/area/available"_json_pointer, true) != false ||
             results.value("/centroid/available"_json_pointer, true) != false) {
    fail_validation("UNAVAILABLE_RESULT_PUBLISHED",
                    "Area/centroid must be unavailable for an invalid polygon");
  }
  Json report_out = {{"checks",
                      {{"ring_properties_match", true},
                       {"validity_matches", true},
                       {"area_matches", true},
                       {"centroid_matches", true},
                       {"bbox_matches", true}}},
                     {"ring_count", rings.size()},
                     {"valid_polygon_with_holes", valid},
                     {"exact_area", area_value},
                     {"exact_centroid", centroid_value},
                     {"independence",
                      "exact rational fan decomposition and pairwise edge tests; CGAL Polygon_2 "
                      "algorithms are not called"}};
  return finish_validation(request, "polygon.validate.properties_report", std::move(report_out));
}

// ---------------------------------------------------------------------------
// polygon.query.containment
// ---------------------------------------------------------------------------

Json run_polygon_containment(const Request& request) {
  require_input_count(request, 2, "polygon.query.containment");
  require_parameters(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto data = read_polygon_with_holes2(request.inputs[0]);
  const auto queries = read_point_set2(request.inputs[1]);
  if (queries.size() > kMaximumQueryCount) {
    throw WorkerError("RESOURCE_LIMIT", "QUERY_LIMIT_EXCEEDED", "Too many containment queries");
  }
  std::size_t vertices = data.outer.size();
  for (const auto& hole : data.holes) vertices += hole.size();
  require_planar_budget(queries.size(), vertices, "Containment query");
  const auto analysis = analyse(data);
  if (!analysis.valid) {
    throw WorkerError("PRECONDITION_FAILED", "INVALID_POLYGON_WITH_HOLES",
                      "Containment requires a valid polygon with holes: " +
                          analysis.reasons.front());
  }
  PolygonWithHoles container(analysis.rings[0], std::next(analysis.rings.begin()),
                             analysis.rings.end());
  Json results = Json::array();
  std::map<std::string, std::size_t> counts = {{"inside", 0}, {"boundary", 0}, {"outside", 0}};
  for (std::size_t i = 0; i < queries.size(); ++i) {
    const EP2 point = exact_point(queries[i]);
    std::string location;
    const auto outer_side = container.outer_boundary().bounded_side(point);
    if (outer_side == CGAL::ON_BOUNDARY) {
      location = "boundary";
    } else if (outer_side == CGAL::ON_UNBOUNDED_SIDE) {
      location = "outside";
    } else {
      location = "inside";
      for (auto hole = container.holes_begin(); hole != container.holes_end(); ++hole) {
        const auto side = hole->bounded_side(point);
        if (side == CGAL::ON_BOUNDARY) {
          location = "boundary";
          break;
        }
        if (side == CGAL::ON_BOUNDED_SIDE) {
          location = "outside";
          break;
        }
      }
    }
    ++counts[location];
    results.push_back({{"query_index", i}, {"location", location}});
  }
  Json report = {{"schema_version", 1},
                 {"report_type", "Polygon2AnalysisReport"},
                 {"analysis_kind", "point_containment"},
                 {"operation", "polygon.query.containment"},
                 {"length_unit", request.inputs[0].unit},
                 {"source",
                  {{"sha256", request.inputs[0].sha256},
                   {"type", "PolygonWithHoles2"},
                   {"query_sha256", request.inputs[1].sha256}}},
                 {"summary", counts},
                 {"results", results}};
  auto output = write_json_output(request, "analysis", "Polygon2AnalysisReport", "none", report);
  Json metrics = {{"query_count", queries.size()},
                  {"inside_count", counts["inside"]},
                  {"boundary_count", counts["boundary"]},
                  {"outside_count", counts["outside"]},
                  {"effective_kernel", "CGAL::Exact_predicates_exact_constructions_kernel"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json run_polygon_containment_validator(const Request& request) {
  require_input_count(request, 3, "polygon.validate.containment_report");
  require_parameters(request, {});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto report = read_report(request.inputs[0], "Polygon2AnalysisReport", "analysis_kind",
                                  "point_containment");
  const auto data = read_polygon_with_holes2(request.inputs[1]);
  const auto queries = read_point_set2(request.inputs[2]);
  if (report.value("/source/sha256"_json_pointer, "") != request.inputs[1].sha256 ||
      report.value("/source/query_sha256"_json_pointer, "") != request.inputs[2].sha256 ||
      report.value("length_unit", "") != request.inputs[1].unit) {
    fail_validation("REPORT_SOURCE_MISMATCH", "Report does not describe these inputs");
  }
  std::size_t vertices = data.outer.size();
  for (const auto& hole : data.holes) vertices += hole.size();
  require_planar_budget(queries.size(), vertices, "Containment validation");
  const auto& results = report.at("results");
  if (!results.is_array() || results.size() != queries.size()) {
    fail_validation("RESULT_COUNT_MISMATCH", "Report must classify every query exactly once");
  }
  std::map<std::string, std::size_t> counts = {{"inside", 0}, {"boundary", 0}, {"outside", 0}};
  for (std::size_t i = 0; i < queries.size(); ++i) {
    const auto expected = independent_location(data, queries[i]);
    if (results[i].value("query_index", std::size_t(-1)) != i ||
        results[i].value("location", std::string()) != expected) {
      fail_validation("LOCATION_MISMATCH",
                      "Query " + std::to_string(i) + " location differs from exact crossing test");
    }
    ++counts[expected];
  }
  if (report.value("summary", Json()) != Json(counts)) {
    fail_validation("SUMMARY_MISMATCH", "Containment summary differs");
  }
  Json out = {{"checks", {{"every_query_classified", true}, {"locations_match", true}}},
              {"query_count", queries.size()},
              {"inside_count", counts["inside"]},
              {"boundary_count", counts["boundary"]},
              {"outside_count", counts["outside"]},
              {"independence", "exact even-odd crossing test; CGAL bounded_side is not called"}};
  return finish_validation(request, "polygon.validate.containment_report", std::move(out));
}

}  // namespace

std::vector<OperationDefinition> planar_operations() {
  std::vector<OperationDefinition> result;
  result.push_back(make_definition(
      "hull.convex_2", {"PointSet2"}, "Polygon2", "transform", run_convex_hull_2,
      {"Convex_hull_2"},
      {{"source_header", "CGAL/convex_hull_2.h"},
       {"input_format", "json"},
       {"output_format", "json"},
       {"validators", {"hull.validate.convex_enclosure_2"}},
       {"maximum_points", kMaximumPlanarPoints}}));
  result.push_back(make_definition(
      "hull.validate.convex_enclosure_2", {"Polygon2", "PointSet2"}, "ValidationReport",
      "validator", run_convex_enclosure_2_validator, {"Convex_hull_2"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"checks",
        {"vertices_are_source_points", "strictly_convex_counterclockwise", "simple_ring",
         "all_source_points_enclosed", "minimal_convex_enclosure"}},
       {"maximum_brute_force_pairs", kMaximumBruteForcePairs}}));
  result.push_back(make_definition(
      "polygon.analysis.properties", {"PolygonWithHoles2"}, "Polygon2AnalysisReport", "analysis",
      run_polygon_properties, {"Polygon"},
      {{"source_header", "CGAL/Polygon_with_holes_2.h"},
       {"input_format", "json"},
       {"output_format", "json"},
       {"validators", {"polygon.validate.properties_report"}},
       {"maximum_vertices", kMaximumPolygonVertices}}));
  result.push_back(make_definition(
      "polygon.validate.properties_report", {"Polygon2AnalysisReport", "PolygonWithHoles2"},
      "ValidationReport", "validator", run_polygon_properties_validator, {"Polygon"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"checks",
        {"ring_properties_match", "validity_matches", "area_matches", "centroid_matches",
         "bbox_matches"}}}));
  result.push_back(make_definition(
      "polygon.query.containment", {"PolygonWithHoles2", "PointSet2"}, "Polygon2AnalysisReport",
      "analysis", run_polygon_containment, {"Polygon"},
      {{"source_header", "CGAL/Polygon_2.h"},
       {"input_format", "json"},
       {"output_format", "json"},
       {"validators", {"polygon.validate.containment_report"}},
       {"maximum_queries", kMaximumQueryCount},
       {"maximum_brute_force_pairs", kMaximumBruteForcePairs}}));
  result.push_back(make_definition(
      "polygon.validate.containment_report",
      {"Polygon2AnalysisReport", "PolygonWithHoles2", "PointSet2"}, "ValidationReport",
      "validator", run_polygon_containment_validator, {"Polygon"},
      {{"input_slots", {"candidate", "polygon", "queries"}},
       {"output_slot", "validation"},
       {"checks", {"every_query_classified", "locations_match"}}}));
  return result;
}

}  // namespace cgal_master::wave_c
