// Independent validators for the surface parameterizations (7.8.05): mesh.parameterize (ARAP through
// CGAL::Surface_mesh_parameterization::parameterize) and mesh.parameterize.discrete_conformal_map.
// No CGAL header is included. Bijectivity is certified exactly (signed uv areas and the simplicity of the
// boundary polygon are evaluated with GMP rationals on the raw binary64 uv values); the harmonic residual and
// the isometric distortion need square roots and cotangents and use long double with declared tolerances.

#include "b8_common.h"

#include <algorithm>
#include <cmath>
#include <map>

namespace cgal_master::batch8 {
namespace {

using batch2::concluded;
using batch2::require_member;
using batch2::vinfo;
using query_ops::read_raw_mesh;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;

using LD = long double;
constexpr LD kHarmonicResidualTolerance = 1e-9L;
constexpr LD kBorderTolerance = 1e-9L;
constexpr const char* kHarmonicTolerance =
    "relative harmonic residual |sum_j w_ij (uv_j - uv_i)| / (sum_j |w_ij|) <= 1e-9 for every interior vertex "
    "(w_ij = cot a + cot b from the 3D triangles, long double); border position error <= 1e-9";

struct Uv {
  Q u, v;
  double ud, vd;
};

struct Common {
  RawMesh mesh;
  Topology topology;
  std::vector<Uv> uv;
  int orientation = 0;  // +1: every uv triangle is counter-clockwise, -1: every one is clockwise
  std::vector<std::size_t> border;
  Json checks;
};

Q cross_uv(const Uv& o, const Uv& a, const Uv& b) { return (a.u - o.u) * (b.v - o.v) - (a.v - o.v) * (b.u - o.u); }

int sign_of(const Q& q) { return q < 0 ? -1 : (q > 0 ? 1 : 0); }

bool on_segment(const Uv& a, const Uv& b, const Uv& p) {  // p collinear with a-b
  return std::min(a.u, b.u) <= p.u && p.u <= std::max(a.u, b.u) && std::min(a.v, b.v) <= p.v && p.v <= std::max(a.v, b.v);
}

bool segments_touch(const Uv& a, const Uv& b, const Uv& c, const Uv& d) {
  const int o1 = sign_of(cross_uv(a, b, c)), o2 = sign_of(cross_uv(a, b, d));
  const int o3 = sign_of(cross_uv(c, d, a)), o4 = sign_of(cross_uv(c, d, b));
  if (o1 != o2 && o3 != o4) return true;
  if (o1 == 0 && on_segment(a, b, c)) return true;
  if (o2 == 0 && on_segment(a, b, d)) return true;
  if (o3 == 0 && on_segment(c, d, a)) return true;
  if (o4 == 0 && on_segment(c, d, b)) return true;
  return false;
}

// Shared parsing and the exact bijectivity certificate.
Common load(const Request& request, const std::string& operation, const std::string& validator) {
  require_inputs(request, 2, validator);
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "surface_parameterization");
  Common c;
  c.mesh = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  batch2::require_triangle_faces(c.mesh, "The mesh", kMaximumParameterizationFaces);
  c.topology = analyze_topology(c.mesh);
  if (c.topology.unreferenced_vertex || !c.topology.oriented_manifold || c.topology.components != 1 ||
      c.topology.boundary_loops.size() != 1 || c.topology.euler() != 1) {
    validation_failure("MESH_NOT_DISC", "The mesh must be a connected oriented disc with one boundary loop");
  }
  c.border = c.topology.boundary_loops.front();
  const auto results = batch2::check_report_frame(report, operation, request.parameters,
                                                  {{"mesh_sha256", &request.inputs[1]}}, c.checks);
  if (require_member(results, "distance_unit", "results") != request.inputs[1].unit) {
    validation_failure("UNIT_MISMATCH", "The report distance unit differs from the mesh unit");
  }
  c.checks["distance_unit_matches_mesh"] = true;
  const auto& rows = require_member(results, "uv", "results");
  if (!rows.is_array() || rows.size() != c.mesh.vertices.size()) {
    validation_failure("UV_COUNT_MISMATCH", "There must be one uv pair per mesh vertex");
  }
  for (const auto& row : rows) {
    if (!row.is_array() || row.size() != 2 || !row[0].is_number() || !row[1].is_number() ||
        !std::isfinite(row[0].get<double>()) || !std::isfinite(row[1].get<double>())) {
      validation_failure("REPORT_VALUE_INVALID", "A uv entry must be two finite numbers");
    }
    const double u = row[0].get<double>(), v = row[1].get<double>();
    c.uv.push_back({query_ops::exact_of(u), query_ops::exact_of(v), u, v});
  }
  c.checks["uv_complete_and_finite"] = true;

  // Exact signed areas: one common orientation, none degenerate.
  for (const auto& face : c.mesh.faces) {
    const int s = sign_of(cross_uv(c.uv[face[0]], c.uv[face[1]], c.uv[face[2]]));
    if (s == 0) validation_failure("DEGENERATE_UV_TRIANGLE", "A triangle has zero area in the parameter domain");
    if (c.orientation == 0) c.orientation = s;
    else if (s != c.orientation) validation_failure("FLIPPED_TRIANGLE", "The parameterization flips a triangle");
  }
  c.checks["no_flipped_or_degenerate_triangles"] = true;

  // The image of the boundary loop is a simple closed polygon.
  const std::size_t b = c.border.size();
  if (b < 3) validation_failure("MESH_NOT_DISC", "The boundary loop is too short");
  for (std::size_t i = 0; i < b; ++i) {
    for (std::size_t j = i + 1; j < b; ++j) {
      const bool adjacent = (j == i + 1) || (i == 0 && j == b - 1);
      const auto& a0 = c.uv[c.border[i]];
      const auto& a1 = c.uv[c.border[(i + 1) % b]];
      const auto& b0 = c.uv[c.border[j]];
      const auto& b1 = c.uv[c.border[(j + 1) % b]];
      if (adjacent) {
        // Neighbouring boundary edges may only share their common endpoint (no fold-back along a line).
        const bool forward = (j == i + 1);
        const Uv& shared = forward ? a1 : a0;
        const Uv& other1 = forward ? a0 : a1;
        const Uv& other2 = forward ? b1 : b0;
        if (cross_uv(shared, other1, other2) == 0 &&
            (other1.u - shared.u) * (other2.u - shared.u) + (other1.v - shared.v) * (other2.v - shared.v) > 0) {
          validation_failure("BORDER_NOT_SIMPLE", "The boundary polygon folds back on itself");
        }
        continue;
      }
      if (segments_touch(a0, a1, b0, b1)) validation_failure("BORDER_NOT_SIMPLE", "The boundary polygon crosses itself");
    }
  }
  c.checks["boundary_image_is_simple_polygon"] = true;
  return c;
}

struct V3d {
  LD x, y, z;
};
V3d sub(const V3d& a, const V3d& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
LD dot3(const V3d& a, const V3d& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
V3d cross3(const V3d& a, const V3d& b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
LD norm3(const V3d& a) { return std::sqrt(dot3(a, a)); }
V3d point_of(const RawMesh& m, std::size_t i) { return {m.vertices[i][0], m.vertices[i][1], m.vertices[i][2]}; }

// ---- DCM: harmonic map with cotangent weights onto an arc-length circle --------------------------------
Json validate_harmonic(const Request& request) {
  const std::string validator = "mesh.validate.parameterization_harmonic";
  require_parameter_names(request, {});
  auto c = load(request, "mesh.parameterize.discrete_conformal_map", validator);
  const std::size_t n = c.mesh.vertices.size();
  const std::size_t b = c.border.size();

  // Border: on the circle of radius 1/2 about (1/2, 1/2), spaced proportionally to the 3D arc length.
  std::vector<LD> length(b);
  LD total = 0;
  for (std::size_t i = 0; i < b; ++i) {
    length[i] = norm3(sub(point_of(c.mesh, c.border[(i + 1) % b]), point_of(c.mesh, c.border[i])));
    total += length[i];
  }
  const LD pi = std::acos(static_cast<LD>(-1));
  LD worst_border = 0;
  std::vector<LD> angle(b);
  for (std::size_t i = 0; i < b; ++i) {
    const LD x = static_cast<LD>(c.uv[c.border[i]].ud) - 0.5L, y = static_cast<LD>(c.uv[c.border[i]].vd) - 0.5L;
    worst_border = std::max(worst_border, std::fabs(std::sqrt(x * x + y * y) - 0.5L));
    angle[i] = std::atan2(y, x);
  }
  std::vector<LD> steps(b);
  LD turning = 0;
  for (std::size_t i = 0; i < b; ++i) {
    LD step = angle[(i + 1) % b] - angle[i];
    while (step > pi) step -= 2 * pi;
    while (step <= -pi) step += 2 * pi;
    steps[i] = step;
    turning += step;
  }
  const LD direction = turning >= 0 ? 1 : -1;
  for (std::size_t i = 0; i < b; ++i) {
    worst_border = std::max(worst_border, std::fabs(steps[i] - direction * 2 * pi * length[i] / total));
  }
  if (worst_border > kBorderTolerance) {
    validation_failure("BORDER_NOT_ARC_LENGTH_CIRCLE", "The boundary is not mapped onto the arc-length circle");
  }
  c.checks["boundary_on_arc_length_circle"] = true;

  // Harmonic condition with cotangent weights at every interior vertex.
  std::vector<bool> on_border(n, false);
  for (const auto v : c.border) on_border[v] = true;
  std::vector<std::map<std::size_t, LD>> weight(n);
  for (const auto& face : c.mesh.faces) {
    for (std::size_t k = 0; k < 3; ++k) {
      const std::size_t i = face[k], j = face[(k + 1) % 3], o = face[(k + 2) % 3];
      const V3d a = sub(point_of(c.mesh, i), point_of(c.mesh, o)), bb = sub(point_of(c.mesh, j), point_of(c.mesh, o));
      const LD cot = dot3(a, bb) / norm3(cross3(a, bb));  // cotangent of the angle at o, opposite the edge i-j
      weight[i][j] += cot;
      weight[j][i] += cot;
    }
  }
  LD worst = 0;
  LD minimum_weight = 1e300L;
  std::size_t interior = 0;
  for (std::size_t i = 0; i < n; ++i) {
    if (on_border[i]) continue;
    ++interior;
    LD rx = 0, ry = 0, scale = 0;
    for (const auto& [j, w] : weight[i]) {
      rx += w * (static_cast<LD>(c.uv[j].ud) - static_cast<LD>(c.uv[i].ud));
      ry += w * (static_cast<LD>(c.uv[j].vd) - static_cast<LD>(c.uv[i].vd));
      scale += std::fabs(w);
      minimum_weight = std::min(minimum_weight, w);
    }
    worst = std::max(worst, std::sqrt(rx * rx + ry * ry) / scale);
  }
  if (interior == 0) validation_failure("NO_INTERIOR_VERTEX", "The mesh has no interior vertex");
  if (worst > kHarmonicResidualTolerance) {
    validation_failure("HARMONIC_RESIDUAL_TOO_LARGE", "The uv map violates the cotangent harmonic condition");
  }
  c.checks["cotangent_harmonic_condition_holds"] = true;
  return concluded(request, validator, c.checks,
                   {{"orientation", c.orientation}, {"interior_vertex_count", interior}, {"border_vertex_count", b},
                    {"maximum_relative_harmonic_residual", static_cast<double>(worst)},
                    {"maximum_border_error", static_cast<double>(worst_border)},
                    {"minimum_cotangent_weight", static_cast<double>(minimum_weight)},
                    {"tolerances", kHarmonicTolerance},
                    {"independence", "exact GMP rational signed areas and boundary-polygon simplicity; long double "
                                     "cotangent weights; no CGAL header"}});
}

// ---- ARAP: bounded isometric distortion ----------------------------------------------------------------
Json validate_isometric(const Request& request) {
  const std::string validator = "mesh.validate.parameterization_isometric";
  require_parameter_names(request, {"lambda", "iterations", "maximum_distortion"});
  const auto bound_json = request.parameters.at("maximum_distortion");
  if (!bound_json.is_number() || bound_json.get<double>() < 1.0) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "maximum_distortion must be a number >= 1");
  }
  const LD bound = bound_json.get<double>();
  auto c = load(request, "mesh.parameterize", validator);
  LD area_uv = 0, area_3d = 0;
  struct Jacobian {
    LD sigma_large, sigma_small;
  };
  std::vector<Jacobian> jacobians;
  for (const auto& face : c.mesh.faces) {
    const V3d p0 = point_of(c.mesh, face[0]), p1 = point_of(c.mesh, face[1]), p2 = point_of(c.mesh, face[2]);
    const V3d e1 = sub(p1, p0), e2 = sub(p2, p0);
    const LD l1 = norm3(e1);
    const LD x2 = dot3(e1, e2) / l1;
    const LD y2 = norm3(cross3(e1, e2)) / l1;
    const LD u1 = static_cast<LD>(c.uv[face[1]].ud) - static_cast<LD>(c.uv[face[0]].ud);
    const LD v1 = static_cast<LD>(c.uv[face[1]].vd) - static_cast<LD>(c.uv[face[0]].vd);
    const LD u2 = static_cast<LD>(c.uv[face[2]].ud) - static_cast<LD>(c.uv[face[0]].ud);
    const LD v2 = static_cast<LD>(c.uv[face[2]].vd) - static_cast<LD>(c.uv[face[0]].vd);
    // J maps the local edges (l1,0) and (x2,y2) to (u1,v1) and (u2,v2).
    const LD a = u1 / l1, c0 = v1 / l1;
    const LD b = (u2 - a * x2) / y2, d = (v2 - c0 * x2) / y2;
    const LD s1 = a * a + b * b + c0 * c0 + d * d;
    const LD s2 = std::sqrt((a * a + b * b - c0 * c0 - d * d) * (a * a + b * b - c0 * c0 - d * d) +
                            4 * (a * c0 + b * d) * (a * c0 + b * d));
    jacobians.push_back({std::sqrt((s1 + s2) / 2), std::sqrt(std::max<LD>(0, (s1 - s2) / 2))});
    area_3d += norm3(cross3(e1, e2)) / 2;
    area_uv += std::fabs(u1 * v2 - u2 * v1) / 2;
  }
  const LD scale = std::sqrt(area_uv / area_3d);
  LD worst = 1, sum = 0;
  for (const auto& j : jacobians) {
    if (j.sigma_small <= 0) validation_failure("DEGENERATE_UV_TRIANGLE", "A triangle collapses in the parameter domain");
    const LD distortion = std::max(j.sigma_large / scale, scale / j.sigma_small);
    worst = std::max(worst, distortion);
    sum += distortion;
  }
  if (worst > bound) {
    validation_failure("ISOMETRIC_DISTORTION_EXCEEDS_BOUND", "A triangle's stretch exceeds maximum_distortion");
  }
  c.checks["isometric_distortion_within_bound"] = true;
  return concluded(request, validator, c.checks,
                   {{"orientation", c.orientation}, {"maximum_isometric_distortion", static_cast<double>(worst)},
                    {"mean_isometric_distortion", static_cast<double>(sum / jacobians.size())},
                    {"uniform_scale", static_cast<double>(scale)}, {"distortion_bound", static_cast<double>(bound)},
                    {"tolerances", "distortion = max(sigma_1 / s, s / sigma_2) per triangle, s = sqrt(uv area / 3D area), "
                                   "long double; the bound is the declared parameter"},
                    {"independence", "exact GMP rational signed areas and boundary-polygon simplicity; long double "
                                     "singular values of the per-triangle Jacobian; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> parameterization_validators() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.validate.parameterization_harmonic", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport",
      "validator", validate_harmonic, {"Surface_mesh_parameterization"}, "GMP rationals and long double (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "distance_unit_matches_mesh", "uv_complete_and_finite",
             "no_flipped_or_degenerate_triangles", "boundary_image_is_simple_polygon", "boundary_on_arc_length_circle",
             "cotangent_harmonic_condition_holds"},
            {"candidate", "mesh"},
            "exact GMP rational signed areas and boundary-polygon simplicity; long double cotangent weights; no CGAL "
            "header")));
  result.push_back(query_definition(
      "mesh.validate.parameterization_isometric", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport",
      "validator", validate_isometric, {"Surface_mesh_parameterization"}, "GMP rationals and long double (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "distance_unit_matches_mesh", "uv_complete_and_finite",
             "no_flipped_or_degenerate_triangles", "boundary_image_is_simple_polygon", "isometric_distortion_within_bound"},
            {"candidate", "mesh"},
            "exact GMP rational signed areas and boundary-polygon simplicity; long double singular values of the "
            "per-triangle Jacobian; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch8
