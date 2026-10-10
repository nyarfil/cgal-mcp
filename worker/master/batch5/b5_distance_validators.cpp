// Independent validators for the 7.3.06 distance operations. No CGAL header.
//
// Point-to-triangle distances are brute force over all triangles: exact GMP rationals for point sets
// (squared distances) and for the vertex lower bounds, long double for the subdivision bracket of a
// supremum. The Hausdorff distance sup_{p in A} dist(p, B) is bracketed by a best-first subdivision of
// the triangles of A using the 1-Lipschitz bound dist(p) <= dist(c) + |p - c|; the bracket width is
// kBracketWidth times the diagonal of A. Square roots force the declared tolerance kRelativeTolerance.

#include "b5_common.h"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <queue>

namespace cgal_master::batch5 {
namespace {

using batch2::concluded;
using batch2::require_member;
using batch2::vec;
using batch2::vinfo;
using query_ops::RawMesh;
using query_ops::read_points3;
using query_ops::read_raw_mesh;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;

using LD = long double;
constexpr LD kRelativeTolerance = 1e-9L;
constexpr LD kBracketWidth = 5e-3L;
constexpr std::size_t kNodeBudget = 3000000;

struct P3 {
  LD x, y, z;
};
P3 operator-(const P3& a, const P3& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
P3 operator+(const P3& a, const P3& b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
P3 operator*(LD s, const P3& a) { return {s * a.x, s * a.y, s * a.z}; }
LD dot3(const P3& a, const P3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
LD length3(const P3& a) { return std::sqrt(dot3(a, a)); }
P3 midpoint(const P3& a, const P3& b) { return {(a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2}; }

struct Tri {
  P3 a, b, c;
};

P3 to_p3(const V3& v) { return {v[0], v[1], v[2]}; }

LD distance_to_triangle(const P3& p, const Tri& t) {
  const P3 ab = t.b - t.a, ac = t.c - t.a, ap = p - t.a;
  const LD d1 = dot3(ab, ap), d2 = dot3(ac, ap);
  if (d1 <= 0 && d2 <= 0) return length3(ap);
  const P3 bp = p - t.b;
  const LD d3 = dot3(ab, bp), d4 = dot3(ac, bp);
  if (d3 >= 0 && d4 <= d3) return length3(bp);
  const LD vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) return length3(ap - (d1 / (d1 - d3)) * ab);
  const P3 cp = p - t.c;
  const LD d5 = dot3(ab, cp), d6 = dot3(ac, cp);
  if (d6 >= 0 && d5 <= d6) return length3(cp);
  const LD vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) return length3(ap - (d2 / (d2 - d6)) * ac);
  const LD va = d3 * d6 - d5 * d4;
  if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
    const LD w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
    return length3(bp - w * (t.c - t.b));
  }
  const LD denominator = va + vb + vc;
  return length3(ap - (vb / denominator) * ab - (vc / denominator) * ac);
}

std::vector<Tri> triangles_of(const RawMesh& raw, const std::string& context) {
  batch2::require_triangle_faces(raw, context, kMaximumDistanceFaces);
  std::vector<Tri> result;
  for (const auto& face : raw.faces) {
    const auto exact = batch2::make_tri(raw, face);
    if (batch2::tri_degenerate(exact)) validation_failure("DEGENERATE_FACE", context + " has a zero-area face");
    result.push_back({to_p3(raw.vertices[face[0]]), to_p3(raw.vertices[face[1]]), to_p3(raw.vertices[face[2]])});
  }
  return result;
}

LD diagonal_of(const RawMesh& raw) {
  LD low[3], high[3];
  for (int a = 0; a < 3; ++a) low[a] = high[a] = raw.vertices.at(0)[a];
  for (const auto& v : raw.vertices) {
    for (int a = 0; a < 3; ++a) {
      low[a] = std::min<LD>(low[a], v[a]);
      high[a] = std::max<LD>(high[a], v[a]);
    }
  }
  return std::sqrt((high[0] - low[0]) * (high[0] - low[0]) + (high[1] - low[1]) * (high[1] - low[1]) +
                   (high[2] - low[2]) * (high[2] - low[2]));
}

LD distance_to_mesh(const P3& p, const std::vector<Tri>& mesh) {
  LD best = std::numeric_limits<LD>::infinity();
  for (const Tri& t : mesh) best = std::min(best, distance_to_triangle(p, t));
  return best;
}

// Exact squared distance of a point to a mesh / to a point set (GMP rationals).
Q exact_squared_to_mesh(const V3& p, const RawMesh& raw) {
  const auto point = vec(p);
  bool first = true;
  Q best = 0;
  for (const auto& face : raw.faces) {
    const Q d = squared_distance_point_triangle(point, vec(raw.vertices[face[0]]), vec(raw.vertices[face[1]]),
                                                vec(raw.vertices[face[2]]));
    if (first || d < best) best = d;
    first = false;
  }
  return best;
}

LD sqrt_of(const Q& value) { return std::sqrt(static_cast<LD>(value.get_d())); }

// Brackets sup over the triangles of `region` of the 1-Lipschitz function `distance`.
void bracket(const std::vector<Tri>& region, const std::function<LD(const P3&)>& distance, LD width, LD& lower,
             LD& upper) {
  struct Node {
    Tri t;
    LD ub;
    bool operator<(const Node& other) const { return ub < other.ub; }
  };
  lower = 0;
  std::priority_queue<Node> queue;
  auto push = [&](const Tri& t) {
    const LD da = distance(t.a), db = distance(t.b), dc = distance(t.c);
    const P3 centroid = {(t.a.x + t.b.x + t.c.x) / 3, (t.a.y + t.b.y + t.c.y) / 3, (t.a.z + t.b.z + t.c.z) / 3};
    const LD dm = distance(centroid);
    lower = std::max({lower, da, db, dc, dm});
    const LD rc = std::max({length3(t.a - centroid), length3(t.b - centroid), length3(t.c - centroid)});
    const LD ab = length3(t.a - t.b), bc = length3(t.b - t.c), ca = length3(t.c - t.a);
    LD ub = dm + rc;
    ub = std::min(ub, da + std::max(ab, ca));
    ub = std::min(ub, db + std::max(ab, bc));
    ub = std::min(ub, dc + std::max(bc, ca));
    queue.push({t, ub});
  };
  for (const Tri& t : region) push(t);
  std::size_t nodes = 0;
  upper = lower;
  while (!queue.empty()) {
    const Node top = queue.top();
    if (top.ub <= lower + width) {
      upper = std::max(lower, top.ub);
      return;
    }
    queue.pop();
    if (++nodes > kNodeBudget) {
      validation_failure("BRACKET_NOT_CONVERGED", "The exact distance bracket did not converge within the node budget");
    }
    const P3 ab = midpoint(top.t.a, top.t.b), bc = midpoint(top.t.b, top.t.c), ca = midpoint(top.t.c, top.t.a);
    push({top.t.a, ab, ca});
    push({ab, top.t.b, bc});
    push({ca, bc, top.t.c});
    push({ab, bc, ca});
  }
  upper = lower;
}

Json distance_value(const Json& results, const std::string& unit) {
  if (require_member(results, "distance_unit", "results") != unit) {
    validation_failure("UNIT_MISMATCH", "The report distance unit differs from the mesh unit");
  }
  const auto& value = require_member(results, "distance", "results");
  if (!value.is_number() || value.is_boolean() || !std::isfinite(value.get<double>()) || value.get<double>() < 0) {
    validation_failure("REPORT_VALUE_INVALID", "distance must be a finite non-negative number");
  }
  return value;
}

// ---- hausdorff_approximate, hausdorff_approximate_symmetric, hausdorff_bounded --------------------------

struct OneSided {
  LD vertex_lower;  // exact max over vertices of A of dist(v, B)
  LD lower, upper;  // bracket of the exact one-sided Hausdorff distance
};

OneSided one_sided(const RawMesh& a, const RawMesh& b, const std::vector<Tri>& ta, const std::vector<Tri>& tb) {
  OneSided result{};
  Q best = 0;
  for (const auto& v : a.vertices) best = std::max(best, exact_squared_to_mesh(v, b));
  result.vertex_lower = sqrt_of(best);
  bracket(ta, [&](const P3& p) { return distance_to_mesh(p, tb); }, kBracketWidth * diagonal_of(a), result.lower,
          result.upper);
  result.lower = std::max(result.lower, result.vertex_lower);
  result.upper = std::max(result.upper, result.lower);
  return result;
}

Json run_hausdorff(const Request& request) {
  const std::string validator = "mesh.validate.hausdorff_report";
  require_inputs(request, 3, validator);
  Json report;
  {
    bool found = false;
    for (const char* kind : {"hausdorff_approximate", "hausdorff_approximate_symmetric", "hausdorff_bounded"}) {
      try {
        report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", kind);
        found = true;
        break;
      } catch (const WorkerError&) {
      }
    }
    if (!found) validation_failure("REPORT_SCHEMA_MISMATCH", "The report is not a Hausdorff distance report");
  }
  const std::string operation = report.value("operation", std::string());
  const auto first = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  const auto second = read_raw_mesh(request.inputs[2], {"TriangleSurfaceMesh"});
  const auto ta = triangles_of(first, "The first mesh");
  const auto tb = triangles_of(second, "The second mesh");
  if (request.inputs[1].unit != request.inputs[2].unit) validation_failure("UNIT_MISMATCH", "The meshes use different units");
  const bool bounded = operation == "mesh.distance.hausdorff_bounded";
  const bool symmetric = operation == "mesh.distance.hausdorff_approximate_symmetric";
  if (!bounded && !symmetric && operation != "mesh.distance.hausdorff_approximate") {
    validation_failure("PARAMETER_MISMATCH", "The report is not a Hausdorff distance report");
  }
  require_parameter_names(request, {bounded ? "error_bound" : "sampling"});
  Json checks;
  const auto results = batch2::check_report_frame(
      report, operation, request.parameters,
      {{"first_sha256", &request.inputs[1]}, {"second_sha256", &request.inputs[2]}}, checks);
  const double reported = distance_value(results, request.inputs[1].unit).get<double>();
  checks["distance_unit_matches_mesh"] = true;
  const LD diagonal = std::max(diagonal_of(first), diagonal_of(second));
  const LD eps = kRelativeTolerance * (1 + diagonal);

  const auto forward = one_sided(first, second, ta, tb);
  OneSided backward{};
  if (symmetric) backward = one_sided(second, first, tb, ta);
  const LD upper = symmetric ? std::max(forward.upper, backward.upper) : forward.upper;
  const LD lower = symmetric ? std::max(forward.lower, backward.lower) : forward.lower;
  const LD vertex_lower = symmetric ? std::max(forward.vertex_lower, backward.vertex_lower) : forward.vertex_lower;

  if (bounded) {
    const LD bound = request.parameters.at("error_bound").at("value").get<double>();
    if (reported < lower - bound - eps || reported > upper + bound + eps) {
      validation_failure("DISTANCE_OUT_OF_BRACKET",
                         "The reported distance is farther than the error bound from the exact Hausdorff bracket");
    }
    checks["distance_within_error_bound_of_exact_bracket"] = true;
  } else {
    const auto sampling = parse_sampling(request.parameters.at("sampling"), request.inputs[1].unit);
    // Samples are points of the first mesh (both meshes when symmetric), so the estimate never exceeds
    // the exact distance; with the vertices sampled it is at least the largest vertex distance.
    if (reported > upper + eps) {
      validation_failure("DISTANCE_ABOVE_EXACT", "The sampled distance exceeds the exact Hausdorff upper bound");
    }
    checks["distance_not_above_exact_hausdorff_bound"] = true;
    if (sampling.include_vertices && reported < vertex_lower - eps) {
      validation_failure("DISTANCE_BELOW_VERTEX_BOUND", "The sampled distance is below the exact vertex-sample distance");
    }
    checks["distance_not_below_vertex_sample_distance"] = true;
  }
  checks["distance_consistent_with_exact_hausdorff_bracket"] = true;
  return concluded(request, validator, checks,
                   {{"operation", operation},
                    {"recomputed_vertex_lower_bound", static_cast<double>(vertex_lower)},
                    {"recomputed_bracket_lower", static_cast<double>(lower)},
                    {"recomputed_bracket_upper", static_cast<double>(upper)},
                    {"bracket_width_relative_to_diagonal", static_cast<double>(kBracketWidth)},
                    {"length_tolerance_relative_to_diagonal", static_cast<double>(kRelativeTolerance)},
                    {"independence", "exact rational vertex distances plus best-first Lipschitz subdivision bracket over brute-force point-triangle distances; no CGAL header"}});
}

// ---- bounded_error_symmetric_Hausdorff_distance (report of mesh.distance.symmetric_hausdorff) ------------

LD length_scale(const std::string& unit) {
  if (unit == "mm") return 1e-3L;
  if (unit == "cm") return 1e-2L;
  if (unit == "m") return 1;
  validation_failure("UNIT_MISMATCH", "Unsupported length unit " + unit);
  return 0;
}

// TypedLength parameter converted to the mesh unit.
LD typed_in_unit(const Json& value, const std::string& name, const std::string& unit, bool strictly_positive) {
  if (!value.is_object() || value.size() != 2 || !value.contains("value") || !value.contains("unit") ||
      !value.at("unit").is_string() || !value.at("value").is_number() || value.at("value").is_boolean()) {
    validation_failure("PARAMETER_MISMATCH", name + " must be a TypedLength {value, unit}");
  }
  const LD amount = value.at("value").get<double>();
  const LD converted = amount * length_scale(value.at("unit").get<std::string>()) / length_scale(unit);
  if (!std::isfinite(converted) || converted < 0 || (strictly_positive && converted <= 0)) {
    validation_failure("PARAMETER_MISMATCH",
                       name + " must be finite and " + (strictly_positive ? "positive" : "non-negative"));
  }
  return converted;
}

// {value, unit} member of the report, required to be in the mesh unit.
LD report_length(const Json& report, const char* key, const std::string& unit) {
  const auto item = require_member(report, key, "report");
  if (!item.is_object() || item.size() != 2 || !item.contains("value") || !item.at("value").is_number() ||
      item.at("value").is_boolean() || !item.contains("unit") || item.at("unit") != unit ||
      !std::isfinite(item.at("value").get<double>())) {
    validation_failure("REPORT_VALUE_INVALID", std::string(key) + " must be a finite {value, unit} in the mesh unit");
  }
  return item.at("value").get<double>();
}

bool close_to(LD a, LD b) { return std::fabs(a - b) <= 1e-12L * (1 + std::fabs(b)); }

Json run_symmetric_hausdorff_report(const Request& request) {
  const std::string validator = "mesh.validate.hausdorff_symmetric_report";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {"tolerance", "error_bound"});
  const auto report = read_report(request.inputs[0], "ValidationReport", "report_kind", "hausdorff_bounded_symmetric");
  const auto reference = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  const auto candidate = read_raw_mesh(request.inputs[2], {"TriangleSurfaceMesh"});
  const auto tr = triangles_of(reference, "The reference mesh");
  const auto tc = triangles_of(candidate, "The candidate mesh");
  const std::string unit = request.inputs[1].unit;
  if (unit != request.inputs[2].unit) validation_failure("UNIT_MISMATCH", "The meshes use different units");
  Json checks;
  const auto results = batch2::check_report_frame(
      report, "mesh.distance.symmetric_hausdorff", request.parameters,
      {{"reference_sha256", &request.inputs[1]}, {"candidate_sha256", &request.inputs[2]}}, checks);
  const double reported = distance_value(results, unit).get<double>();
  checks["distance_unit_matches_mesh"] = true;
  const LD tolerance = typed_in_unit(request.parameters.at("tolerance"), "tolerance", unit, false);
  const LD error_bound = typed_in_unit(request.parameters.at("error_bound"), "error_bound", unit, true);

  // The report frame must be self-consistent with the declared bounds and verdict.
  const LD reported_lower = std::max<LD>(0, reported - error_bound);
  const LD reported_upper = reported + error_bound;
  if (!close_to(report_length(report, "distance_estimate", unit), reported) ||
      !close_to(report_length(report, "tolerance", unit), tolerance) ||
      !close_to(report_length(report, "error_bound", unit), error_bound) ||
      !close_to(report_length(report, "lower_bound", unit), reported_lower) ||
      !close_to(report_length(report, "upper_bound", unit), reported_upper)) {
    validation_failure("REPORT_BOUNDS_INCONSISTENT",
                       "The reported estimate, bounds, tolerance or error bound disagree with the parameters");
  }
  const std::string expected_verdict =
      reported_upper <= tolerance ? "pass" : (reported_lower > tolerance ? "fail" : "indeterminate");
  const auto verdict = require_member(report, "verdict", "report");
  const auto status = require_member(report, "status", "report");
  const auto valid = require_member(report, "valid", "report");
  if (!verdict.is_string() || verdict.get<std::string>() != expected_verdict || !status.is_string() ||
      status.get<std::string>() != (expected_verdict == "pass" ? "pass" : "fail") || !valid.is_boolean() ||
      valid.get<bool>() != (expected_verdict == "pass") ||
      require_member(report, "method", "report") != "bounded_error_symmetric") {
    validation_failure("VERDICT_MISMATCH", "The reported verdict does not follow from the estimate, bound and tolerance");
  }
  checks["verdict_follows_bounds_and_tolerance"] = true;

  const LD diagonal = std::max(diagonal_of(reference), diagonal_of(candidate));
  const LD eps = kRelativeTolerance * (1 + diagonal);
  const auto forward = one_sided(reference, candidate, tr, tc);
  const auto backward = one_sided(candidate, reference, tc, tr);
  const LD upper = std::max(forward.upper, backward.upper);
  const LD lower = std::max(forward.lower, backward.lower);
  if (reported < lower - error_bound - eps || reported > upper + error_bound + eps) {
    validation_failure("DISTANCE_OUT_OF_BRACKET",
                       "The reported distance is farther than the error bound from the exact symmetric Hausdorff bracket");
  }
  checks["distance_within_error_bound_of_exact_symmetric_bracket"] = true;
  return concluded(request, validator, checks,
                   {{"verdict", expected_verdict},
                    {"recomputed_bracket_lower", static_cast<double>(lower)},
                    {"recomputed_bracket_upper", static_cast<double>(upper)},
                    {"recomputed_forward_vertex_lower_bound", static_cast<double>(forward.vertex_lower)},
                    {"recomputed_backward_vertex_lower_bound", static_cast<double>(backward.vertex_lower)},
                    {"bracket_width_relative_to_diagonal", static_cast<double>(kBracketWidth)},
                    {"length_tolerance_relative_to_diagonal", static_cast<double>(kRelativeTolerance)},
                    {"independence", "exact rational vertex distances plus best-first Lipschitz subdivision bracket over brute-force point-triangle distances in both directions; no CGAL header"}});
}

// ---- max_distance_to_triangle_mesh --------------------------------------------------------------------

Json run_max_to_mesh(const Request& request) {
  const std::string validator = "mesh.validate.max_distance_to_mesh";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "max_distance_to_mesh");
  const auto points = read_points3(request.inputs[1]);
  const auto raw = read_raw_mesh(request.inputs[2], {"TriangleSurfaceMesh"});
  triangles_of(raw, "The mesh");
  if (points.empty() || points.size() > kMaximumDistancePoints) validation_failure("POINT_COUNT", "Between 1 and 2000 points are supported");
  if (request.inputs[1].unit != request.inputs[2].unit) validation_failure("UNIT_MISMATCH", "Points and mesh use different units");
  Json checks;
  const auto results = batch2::check_report_frame(
      report, "mesh.distance.max_to_mesh", request.parameters,
      {{"points_sha256", &request.inputs[1]}, {"mesh_sha256", &request.inputs[2]}}, checks);
  const double reported = distance_value(results, request.inputs[2].unit).get<double>();
  checks["distance_unit_matches_mesh"] = true;
  Q best = 0;
  for (const auto& p : points) best = std::max(best, exact_squared_to_mesh(p, raw));
  const LD exact = sqrt_of(best);
  if (std::fabs(static_cast<LD>(reported) - exact) > kRelativeTolerance * (1 + exact)) {
    validation_failure("DISTANCE_MISMATCH", "The reported maximum distance differs from the exact brute-force result");
  }
  checks["distance_equals_exact_brute_force_maximum"] = true;
  return concluded(request, validator, checks,
                   {{"recomputed_distance", static_cast<double>(exact)}, {"recomputed_squared_distance", query_ops::q_text(best)},
                    {"length_tolerance_relative", static_cast<double>(kRelativeTolerance)},
                    {"independence", "exact rational squared point-triangle distances over all points and triangles; no CGAL header"}});
}

// ---- approximate_max_distance_to_point_set -----------------------------------------------------------

Json run_max_to_points(const Request& request) {
  const std::string validator = "mesh.validate.max_distance_to_points";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {"precision"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "max_distance_to_points");
  const auto raw = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  const auto tris = triangles_of(raw, "The mesh");
  const auto points = read_points3(request.inputs[2]);
  if (points.empty() || points.size() > kMaximumDistancePoints) validation_failure("POINT_COUNT", "Between 1 and 2000 points are supported");
  if (request.inputs[1].unit != request.inputs[2].unit) validation_failure("UNIT_MISMATCH", "Points and mesh use different units");
  Json checks;
  const auto results = batch2::check_report_frame(
      report, "mesh.distance.max_to_points", request.parameters,
      {{"mesh_sha256", &request.inputs[1]}, {"points_sha256", &request.inputs[2]}}, checks);
  const double reported = distance_value(results, request.inputs[1].unit).get<double>();
  checks["distance_unit_matches_mesh"] = true;
  const LD precision = positive_length(request.parameters.at("precision"), "precision", request.inputs[1].unit);
  std::vector<P3> targets;
  for (const auto& p : points) targets.push_back(to_p3(p));
  auto nearest = [&](const P3& p) {
    LD best = std::numeric_limits<LD>::infinity();
    for (const P3& q : targets) best = std::min(best, length3(p - q));
    return best;
  };
  LD lower = 0, upper = 0;
  bracket(tris, nearest, kBracketWidth * diagonal_of(raw), lower, upper);
  const LD eps = kRelativeTolerance * (1 + diagonal_of(raw));
  if (reported < lower - precision - eps || reported > upper + precision + eps) {
    validation_failure("DISTANCE_OUT_OF_BRACKET", "The reported distance is farther than the precision from the exact bracket");
  }
  checks["distance_within_precision_of_exact_bracket"] = true;
  return concluded(request, validator, checks,
                   {{"recomputed_bracket_lower", static_cast<double>(lower)}, {"recomputed_bracket_upper", static_cast<double>(upper)},
                    {"bracket_width_relative_to_diagonal", static_cast<double>(kBracketWidth)},
                    {"length_tolerance_relative_to_diagonal", static_cast<double>(kRelativeTolerance)},
                    {"independence", "best-first Lipschitz subdivision bracket over brute-force point distances; no CGAL header"}});
}

// ---- sample_triangle_mesh ------------------------------------------------------------------------------

LD distance_to_segment(const P3& p, const P3& a, const P3& b) {
  const P3 ab = b - a;
  const LD denominator = dot3(ab, ab);
  LD t = denominator > 0 ? dot3(p - a, ab) / denominator : 0;
  t = std::max<LD>(0, std::min<LD>(1, t));
  return length3(p - (a + t * ab));
}

Json run_samples(const Request& request) {
  const std::string validator = "mesh.validate.distance_samples";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"sampling"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "mesh_samples");
  const auto raw = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  const auto tris = triangles_of(raw, "The mesh");
  const auto spec = parse_sampling(request.parameters.at("sampling"), request.inputs[1].unit);
  Json checks;
  const auto results = batch2::check_report_frame(report, "mesh.distance.sample_points", request.parameters,
                                                  {{"mesh_sha256", &request.inputs[1]}}, checks);
  const auto& list = require_member(results, "points", "results");
  if (!list.is_array() || list.empty() || list.size() > kMaximumSamplePoints) {
    validation_failure("REPORT_VALUE_INVALID", "points must be a non-empty array of at most 20000 points");
  }
  if (require_member(results, "length_unit", "results") != request.inputs[1].unit) {
    validation_failure("UNIT_MISMATCH", "The report length unit differs from the mesh unit");
  }
  checks["length_unit_matches_mesh"] = true;
  std::vector<P3> points;
  std::vector<V3> raw_points;
  for (const auto& item : list) {
    if (!item.is_array() || item.size() != 3) validation_failure("REPORT_VALUE_INVALID", "A sample must be [x,y,z]");
    V3 v{};
    for (int k = 0; k < 3; ++k) {
      if (!item[k].is_number() || item[k].is_boolean() || !std::isfinite(item[k].get<double>())) {
        validation_failure("REPORT_VALUE_INVALID", "Sample coordinates must be finite numbers");
      }
      v[k] = item[k].get<double>();
    }
    raw_points.push_back(v);
    points.push_back(to_p3(v));
  }
  const LD eps = kRelativeTolerance * (1 + diagonal_of(raw));
  for (const P3& p : points) {
    if (distance_to_mesh(p, tris) > eps) validation_failure("SAMPLE_OFF_SURFACE", "A sample does not lie on the mesh surface");
  }
  checks["samples_lie_on_mesh_surface"] = true;
  const std::size_t vertex_count = spec.include_vertices ? raw.vertices.size() : 0;
  if (spec.include_vertices) {
    if (points.size() < raw.vertices.size()) validation_failure("VERTICES_MISSING", "The mesh vertices are not part of the sample");
    for (std::size_t i = 0; i < raw.vertices.size(); ++i) {
      if (raw_points[i] != raw.vertices[i]) validation_failure("VERTICES_MISSING", "The mesh vertices are not the first samples");
    }
  }
  checks["vertices_sampled_as_requested"] = true;
  // Samples that are not mesh vertices.
  std::size_t edge_samples = 0;
  std::vector<bool> face_covered(tris.size(), false);
  for (std::size_t i = vertex_count; i < points.size(); ++i) {
    bool on_edge = false;
    for (std::size_t f = 0; f < tris.size(); ++f) {
      const Tri& t = tris[f];
      if (distance_to_triangle(points[i], t) <= eps) face_covered[f] = true;
      if (distance_to_segment(points[i], t.a, t.b) <= eps || distance_to_segment(points[i], t.b, t.c) <= eps ||
          distance_to_segment(points[i], t.c, t.a) <= eps) {
        on_edge = true;
      }
    }
    if (on_edge) ++edge_samples;
  }
  if (spec.grid) {
    for (std::size_t f = 0; f < tris.size(); ++f) {
      if (!face_covered[f]) validation_failure("FACE_NOT_SAMPLED", "A triangle carries no sample");
    }
    checks["every_triangle_carries_a_sample"] = true;
  } else {
    if (points.size() != vertex_count + spec.points_on_faces + spec.points_on_edges) {
      validation_failure("SAMPLE_COUNT_MISMATCH", "The sample count differs from vertices + points_on_faces + points_on_edges");
    }
    checks["sample_count_matches_request"] = true;
    if (edge_samples < spec.points_on_edges) {
      validation_failure("EDGE_SAMPLES_MISSING", "Fewer samples lie on mesh edges than points_on_edges");
    }
    checks["edge_samples_lie_on_mesh_edges"] = true;
  }
  return concluded(request, validator, checks,
                   {{"sample_count", points.size()}, {"edge_sample_count", edge_samples},
                    {"length_tolerance_relative_to_diagonal", static_cast<double>(kRelativeTolerance)},
                    {"independence", "brute-force point-triangle and point-edge distances over all samples; sample positions of a seeded random stream are not re-derived; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> distance_validators() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.validate.distance_samples", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      run_samples, {"Polygon_mesh_processing"}, "long double (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "length_unit_matches_mesh", "samples_lie_on_mesh_surface",
             "vertices_sampled_as_requested"},
            {"candidate", "mesh"}, "brute-force point-triangle and point-edge distances over all samples; sample positions of a seeded random stream are not re-derived; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.max_distance_to_mesh", {"GeometryQueryReport", "PointSet3", "TriangleSurfaceMesh"}, "ValidationReport",
      "validator", run_max_to_mesh, {"Polygon_mesh_processing"}, "GMP rationals (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "distance_unit_matches_mesh", "distance_equals_exact_brute_force_maximum"},
            {"candidate", "points", "mesh"}, "exact rational squared point-triangle distances over all points and triangles; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.max_distance_to_points", {"GeometryQueryReport", "TriangleSurfaceMesh", "PointSet3"}, "ValidationReport",
      "validator", run_max_to_points, {"Polygon_mesh_processing"}, "long double (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "distance_unit_matches_mesh", "distance_within_precision_of_exact_bracket"},
            {"candidate", "mesh", "points"}, "best-first Lipschitz subdivision bracket over brute-force point distances; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.hausdorff_report", {"GeometryQueryReport", "TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "ValidationReport",
      "validator", run_hausdorff, {"Polygon_mesh_processing"}, "long double (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "distance_unit_matches_mesh", "distance_consistent_with_exact_hausdorff_bracket"}, {"candidate", "first", "second"},
            "exact rational vertex distances plus best-first Lipschitz subdivision bracket over brute-force point-triangle distances; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.hausdorff_symmetric_report", {"ValidationReport", "TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "ValidationReport", "validator", run_symmetric_hausdorff_report, {"Polygon_mesh_processing"},
      "long double (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "distance_unit_matches_mesh", "verdict_follows_bounds_and_tolerance",
             "distance_within_error_bound_of_exact_symmetric_bracket"},
            {"report", "reference", "candidate"},
            "exact rational vertex distances plus best-first Lipschitz subdivision bracket over brute-force point-triangle distances in both directions; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch5
