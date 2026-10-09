// Independent validators for mesh.intersections.do_intersect and mesh.intersections.polylines
// (7.3.07). No CGAL header: a brute-force exact (GMP rational) triangle-triangle test over all face
// pairs decides the intersection predicate, the intersection curve is rebuilt as the union of the
// exact triangle-pair intersection segments and compared with the candidate polylines.

#include "b5_common.h"

#include <algorithm>
#include <map>

namespace cgal_master::batch5 {
namespace {

using batch2::boxes_overlap;
using batch2::concluded;
using batch2::cross;
using batch2::dot;
using batch2::is_zero;
using batch2::intersection_points;
using batch2::make_tri;
using batch2::point_in_triangle;
using batch2::require_member;
using batch2::require_triangle_faces;
using batch2::Tri;
using batch2::tri_degenerate;
using batch2::tri_normal;
using batch2::vinfo;
using query_ops::RawMesh;
using query_ops::read_raw_mesh;
using query_ops::read_report;
using query_ops::reported_rational;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;

std::vector<Tri> triangles_of(const RawMesh& raw, const std::string& context) {
  require_triangle_faces(raw, context, kMaximumIntersectionFaces);
  std::vector<Tri> result;
  for (const auto& face : raw.faces) {
    result.push_back(make_tri(raw, face));
    if (tri_degenerate(result.back())) validation_failure("DEGENERATE_FACE", context + " has a zero-area face");
  }
  return result;
}

bool closed_mesh(const RawMesh& raw) {
  std::map<std::pair<std::size_t, std::size_t>, int> directed;
  for (const auto& face : raw.faces) {
    for (std::size_t k = 0; k < 3; ++k) ++directed[{face[k], face[(k + 1) % 3]}];
  }
  for (const auto& [edge, count] : directed) {
    if (count != 1) return false;
    const auto opposite = directed.find({edge.second, edge.first});
    if (opposite == directed.end() || opposite->second != 1) return false;
  }
  return !directed.empty();
}

// Strict inside test against a closed mesh by exact ray parity; a ray touching an edge or a vertex of a
// triangle is discarded and the next direction is tried.
bool inside_closed_mesh(const Vec& p, const std::vector<Tri>& tris) {
  const Vec directions[] = {{Q(1), Q(3) / 7, Q(5) / 11}, {Q(2), Q(-1) / 13, Q(3) / 17}, {Q(-1), Q(5) / 19, Q(7) / 23},
                            {Q(3) / 5, Q(-7) / 29, Q(-1)}};
  for (const Vec& d : directions) {
    int parity = 0;
    bool degenerate = false;
    for (const Tri& t : tris) {
      const Vec n = tri_normal(t);
      const Q denominator = dot(n, d);
      if (denominator == 0) continue;
      const Q s = dot(n, t.v[0] - p) / denominator;
      if (s <= 0) continue;
      const Vec h = p + s * d;
      bool outside = false, boundary = false;
      for (int i = 0; i < 3; ++i) {
        const Q side = dot(n, cross(t.v[(i + 1) % 3] - t.v[i], h - t.v[i]));
        if (side < 0) outside = true;
        else if (side == 0) boundary = true;
      }
      if (outside) continue;
      if (boundary) {
        degenerate = true;
        break;
      }
      ++parity;
    }
    if (!degenerate) return parity % 2 == 1;
  }
  validation_failure("RAY_DEGENERATE", "No generic ray direction was found for the containment test");
}

Json run_do_intersect(const Request& request) {
  const std::string validator = "mesh.validate.do_intersect";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {"overlap_test"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "mesh_do_intersect");
  const auto first_raw = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  const auto second_raw = read_raw_mesh(request.inputs[2], {"TriangleSurfaceMesh"});
  const auto first = triangles_of(first_raw, "The first mesh");
  const auto second = triangles_of(second_raw, "The second mesh");
  if (request.inputs[1].unit != request.inputs[2].unit) validation_failure("UNIT_MISMATCH", "The meshes use different units");
  Json checks;
  const auto results = batch2::check_report_frame(
      report, "mesh.intersections.do_intersect", {{"overlap_test", request.parameters.at("overlap_test")}},
      {{"first_sha256", &request.inputs[1]}, {"second_sha256", &request.inputs[2]}}, checks);
  const auto& reported = require_member(results, "intersect", "results");
  if (!reported.is_boolean()) validation_failure("REPORT_VALUE_INVALID", "intersect must be boolean");
  const bool overlap = request.parameters.at("overlap_test").get<bool>();
  bool surfaces = false;
  for (const Tri& a : first) {
    for (const Tri& b : second) {
      if (boxes_overlap(a, b) && !intersection_points(a, b).empty()) surfaces = true;
    }
  }
  bool expected = surfaces;
  bool contained = false;
  if (overlap) {
    if (!closed_mesh(first_raw) || !closed_mesh(second_raw)) {
      validation_failure("MESH_NOT_CLOSED", "The bounded-side overlap test needs two closed meshes");
    }
    if (!surfaces) {
      contained = inside_closed_mesh(first[0].v[0], second) || inside_closed_mesh(second[0].v[0], first);
      expected = contained;
    }
  }
  if (reported.get<bool>() != expected) {
    validation_failure("INTERSECTION_MISMATCH", "The reported intersection result differs from the exact brute-force result");
  }
  checks["intersect_equals_exact_brute_force"] = true;
  return concluded(request, validator, checks,
                   {{"recomputed_surfaces_intersect", surfaces}, {"recomputed_bounded_sides_overlap", contained},
                    {"recomputed_intersect", expected},
                    {"independence", "exact rational triangle-pair intersection over all face pairs and exact ray parity; no CGAL header"}});
}

struct Segment {
  Vec a, b;
};

// True when [0,1] along (p,q) is covered by the union of the collinear parts of `others`.
bool covered(const Vec& p, const Vec& q, const std::vector<Segment>& others) {
  const Vec d = q - p;
  const Q length2 = dot(d, d);
  std::vector<std::pair<Q, Q>> intervals;
  for (const Segment& s : others) {
    if (!is_zero(cross(d, s.a - p)) || !is_zero(cross(d, s.b - p))) continue;
    Q lo = dot(s.a - p, d) / length2, hi = dot(s.b - p, d) / length2;
    if (lo > hi) std::swap(lo, hi);
    if (hi < 0 || lo > 1) continue;
    intervals.push_back({std::max(lo, Q(0)), std::min(hi, Q(1))});
  }
  std::sort(intervals.begin(), intervals.end());
  Q reach = 0;
  for (const auto& [lo, hi] : intervals) {
    if (lo > reach) return false;
    reach = std::max(reach, hi);
  }
  return reach >= 1;
}

Vec parse_point(const Json& item) {
  if (!item.is_array() || item.size() != 3) validation_failure("REPORT_VALUE_INVALID", "A polyline point must be three rationals");
  return {reported_rational(item[0], "polyline x"), reported_rational(item[1], "polyline y"),
          reported_rational(item[2], "polyline z")};
}

Json run_polylines(const Request& request) {
  const std::string validator = "mesh.validate.intersection_polylines";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "mesh_intersection_polylines");
  const auto first_raw = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  const auto second_raw = read_raw_mesh(request.inputs[2], {"TriangleSurfaceMesh"});
  const auto first = triangles_of(first_raw, "The first mesh");
  const auto second = triangles_of(second_raw, "The second mesh");
  if (request.inputs[1].unit != request.inputs[2].unit) validation_failure("UNIT_MISMATCH", "The meshes use different units");
  Json checks;
  const auto results = batch2::check_report_frame(
      report, "mesh.intersections.polylines", Json::object(),
      {{"first_sha256", &request.inputs[1]}, {"second_sha256", &request.inputs[2]}}, checks);
  const auto& lines = require_member(results, "polylines", "results");
  if (!lines.is_array()) validation_failure("REPORT_VALUE_INVALID", "polylines must be an array");

  std::vector<Segment> reference;
  for (const Tri& a : first) {
    for (const Tri& b : second) {
      if (!boxes_overlap(a, b)) continue;
      const auto points = intersection_points(a, b);
      if (points.empty()) continue;
      const Vec n = tri_normal(a);
      if (is_zero(cross(n, tri_normal(b))) && dot(n, b.v[0] - a.v[0]) == 0) {
        validation_failure("COPLANAR_TRIANGLES", "Two coplanar triangles intersect; the intersection is not a curve");
      }
      if (points.front() != points.back()) reference.push_back({points.front(), points.back()});
    }
  }

  std::vector<Segment> candidate;
  std::size_t point_count = 0;
  for (const auto& line : lines) {
    const auto& points = require_member(line, "points", "polyline");
    if (!points.is_array() || points.size() < 2) validation_failure("REPORT_VALUE_INVALID", "A polyline needs at least two points");
    std::vector<Vec> parsed;
    for (const auto& item : points) parsed.push_back(parse_point(item));
    for (const Vec& p : parsed) {
      ++point_count;
      bool on_first = false, on_second = false;
      for (const Tri& t : first) on_first = on_first || point_in_triangle(t, p);
      for (const Tri& t : second) on_second = on_second || point_in_triangle(t, p);
      if (!on_first || !on_second) {
        validation_failure("POINT_NOT_ON_BOTH_MESHES", "A polyline point does not lie on both mesh surfaces");
      }
    }
    for (std::size_t i = 0; i + 1 < parsed.size(); ++i) {
      if (parsed[i] != parsed[i + 1]) candidate.push_back({parsed[i], parsed[i + 1]});
    }
  }
  checks["points_lie_on_both_meshes"] = true;
  for (const Segment& s : candidate) {
    if (!covered(s.a, s.b, reference)) {
      validation_failure("SEGMENT_NOT_ON_INTERSECTION", "A polyline segment is not part of the exact intersection of the meshes");
    }
  }
  checks["candidate_covered_by_exact_intersection"] = true;
  for (const Segment& s : reference) {
    if (!covered(s.a, s.b, candidate)) {
      validation_failure("INTERSECTION_MISSING", "A part of the exact intersection of the meshes is missing from the polylines");
    }
  }
  checks["exact_intersection_covered_by_candidate"] = true;
  return concluded(request, validator, checks,
                   {{"exact_segment_count", reference.size()}, {"candidate_segment_count", candidate.size()},
                    {"candidate_point_count", point_count},
                    {"independence", "exact rational triangle-pair intersection segments over all face pairs; isolated touching points are not curves and are not required; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> intersection_validators() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.validate.do_intersect", {"GeometryQueryReport", "TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "ValidationReport", "validator", run_do_intersect, {"Polygon_mesh_processing"}, "GMP rationals (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "intersect_equals_exact_brute_force"},
            {"candidate", "first", "second"}, "exact rational triangle-pair intersection over all face pairs and exact ray parity; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.intersection_polylines", {"GeometryQueryReport", "TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "ValidationReport", "validator", run_polylines, {"Polygon_mesh_processing"}, "GMP rationals (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "points_lie_on_both_meshes", "candidate_covered_by_exact_intersection",
             "exact_intersection_covered_by_candidate"},
            {"candidate", "first", "second"}, "exact rational triangle-pair intersection segments over all face pairs; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch5
