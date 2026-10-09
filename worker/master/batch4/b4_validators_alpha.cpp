// Independent validators for alpha shapes (7.13.02). No CGAL header is included.
//
// With GMP rationals on the raw binary64 input, every full-dimensional Delaunay simplex is found by
// brute force (its open circumscribed ball contains no input point; a point exactly on the sphere is
// a degenerate input and is rejected), its squared circumradius is computed exactly and compared
// with alpha. A full-dimensional Delaunay simplex is interior when its squared circumradius is at
// most alpha; a Delaunay edge (2D) or facet (3D) is regular when exactly one incident simplex is
// interior. The reported sets must equal the recomputed sets exactly.

#include "b4_common.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>

namespace cgal_master::batch4 {
namespace {

using batch2::concluded;
using batch2::index_of;
using batch2::require_member;
using batch2::vinfo;
using query_ops::exact_of;
using query_ops::read_points2;
using query_ops::read_points3;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;

using Tuple = std::vector<std::size_t>;

Q alpha_of(const Request& request) {
  const auto& value = request.parameters.at("alpha");
  if (!value.is_number() || value.is_boolean() || !std::isfinite(value.get<double>()) || value.get<double>() < 0) {
    validation_failure("INVALID_ALPHA", "alpha must be a finite non-negative number");
  }
  return exact_of(value.get<double>());
}

std::set<Tuple> tuple_set(const Json& value, std::size_t arity, std::size_t bound, const std::string& context) {
  if (!value.is_array()) validation_failure("REPORT_VALUE_INVALID", context + " must be an array");
  std::set<Tuple> result;
  for (const auto& item : value) {
    if (!item.is_array() || item.size() != arity) {
      validation_failure("REPORT_VALUE_INVALID", context + " entries have the wrong size");
    }
    Tuple t;
    for (const auto& index : item) t.push_back(index_of(index, bound, context));
    if (!std::is_sorted(t.begin(), t.end()) || std::adjacent_find(t.begin(), t.end()) != t.end()) {
      validation_failure("REPORT_VALUE_INVALID", context + " entries must be strictly increasing index lists");
    }
    if (!result.insert(t).second) validation_failure("REPORT_VALUE_INVALID", context + " lists an entry twice");
  }
  return result;
}

Q det3(const Q a[3][3]) {
  return a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1]) - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0]) +
         a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]);
}

template <std::size_t D>
struct Pt {
  Q c[D];
};

// A Delaunay simplex of full dimension with its exact squared circumradius.
struct Simplex {
  Tuple vertices;
  Q r2;
};

// Regular faces: faces (one dimension lower) with exactly one interior incident simplex.
std::set<Tuple> regular_faces(const std::vector<Simplex>& simplices, const Q& alpha, std::set<Tuple>& interior) {
  std::map<Tuple, int> sides;
  for (const auto& s : simplices) {
    const bool is_interior = s.r2 <= alpha;
    if (is_interior) interior.insert(s.vertices);
    for (std::size_t omit = 0; omit < s.vertices.size(); ++omit) {
      Tuple face;
      for (std::size_t c = 0; c < s.vertices.size(); ++c) if (c != omit) face.push_back(s.vertices[c]);
      sides[face] += is_interior ? 1 : 0;
    }
  }
  std::set<Tuple> regular;
  for (const auto& [face, count] : sides) if (count == 1) regular.insert(face);
  return regular;
}

// ---- 2D ------------------------------------------------------------------------------------------

std::vector<Simplex> delaunay_2(const std::vector<Pt<2>>& p) {
  std::vector<Simplex> result;
  const std::size_t n = p.size();
  for (std::size_t i = 0; i < n; ++i)
    for (std::size_t j = i + 1; j < n; ++j)
      for (std::size_t k = j + 1; k < n; ++k) {
        const Q ax = p[j].c[0] - p[i].c[0], ay = p[j].c[1] - p[i].c[1];
        const Q bx = p[k].c[0] - p[i].c[0], by = p[k].c[1] - p[i].c[1];
        const Q d = 2 * (ax * by - ay * bx);
        if (d == 0) continue;
        const Q a2 = ax * ax + ay * ay, b2 = bx * bx + by * by;
        const Q ux = (by * a2 - ay * b2) / d, uy = (ax * b2 - bx * a2) / d;  // circumcentre - p[i]
        const Q r2 = ux * ux + uy * uy;
        bool empty = true, on_circle = false;
        for (std::size_t m = 0; m < n && empty; ++m) {
          if (m == i || m == j || m == k) continue;
          const Q dx = p[m].c[0] - p[i].c[0] - ux, dy = p[m].c[1] - p[i].c[1] - uy;
          const Q s = dx * dx + dy * dy;
          if (s == r2) on_circle = true;
          if (s < r2) empty = false;
        }
        if (!empty) continue;
        if (on_circle) {
          validation_failure("DEGENERATE_COCIRCULAR",
                             "Four input points lie on one empty circle: the Delaunay triangulation is not unique");
        }
        result.push_back({{i, j, k}, r2});
      }
  return result;
}

Json run_alpha_2(const Request& request) {
  const std::string validator = "shape.validate.alpha_shape_2";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"alpha"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "alpha_shape_2");
  const auto raw = read_points2(request.inputs[1]);
  const std::size_t n = raw.size();
  if (n < 3 || n > kMaximumAlpha2Points) validation_failure("POINT_COUNT", "Between 3 and 60 points are supported");
  const Q alpha = alpha_of(request);
  std::vector<Pt<2>> p(n);
  for (std::size_t i = 0; i < n; ++i) {
    p[i].c[0] = exact_of(raw[i][0]);
    p[i].c[1] = exact_of(raw[i][1]);
    for (std::size_t j = 0; j < i; ++j) {
      if (p[i].c[0] == p[j].c[0] && p[i].c[1] == p[j].c[1]) {
        validation_failure("DUPLICATE_POINT", "Input points must be pairwise distinct");
      }
    }
  }
  Json checks;
  const auto results = batch2::check_report_frame(report, "shape.alpha_shape_2", {{"alpha", request.parameters.at("alpha")}},
                                                  {{"points_sha256", &request.inputs[1]}}, checks);
  if (require_member(results, "alpha_unit", "results") != request.inputs[1].unit + "^2") {
    validation_failure("UNIT_MISMATCH", "alpha_unit must be the squared artifact unit");
  }
  checks["alpha_unit_is_squared_artifact_unit"] = true;
  const auto triangles = delaunay_2(p);
  if (triangles.empty()) validation_failure("ALL_COLLINEAR", "The points are collinear");
  std::set<Tuple> interior;
  const auto regular = regular_faces(triangles, alpha, interior);
  if (tuple_set(require_member(results, "interior_triangles", "results"), 3, n, "interior_triangles") != interior) {
    validation_failure("INTERIOR_MISMATCH", "The interior triangles differ from the exact alpha complex");
  }
  checks["interior_triangles_equal_exact_delaunay_triangles_within_alpha"] = true;
  if (tuple_set(require_member(results, "regular_edges", "results"), 2, n, "regular_edges") != regular) {
    validation_failure("REGULAR_EDGE_MISMATCH", "The regular edges differ from the exact boundary of the alpha complex");
  }
  checks["regular_edges_equal_exact_boundary_of_interior_triangles"] = true;
  return concluded(request, validator, checks,
                   {{"delaunay_triangle_count", triangles.size()}, {"interior_triangle_count", interior.size()},
                    {"regular_edge_count", regular.size()},
                    {"independence", "exact rational empty-circle search and circumradius; no CGAL header"}});
}

// ---- 3D ------------------------------------------------------------------------------------------

std::vector<Simplex> delaunay_3(const std::vector<Pt<3>>& p) {
  std::vector<Simplex> result;
  const std::size_t n = p.size();
  for (std::size_t i = 0; i < n; ++i)
    for (std::size_t j = i + 1; j < n; ++j)
      for (std::size_t k = j + 1; k < n; ++k)
        for (std::size_t l = k + 1; l < n; ++l) {
          Q m[3][3];
          Q rhs[3];
          const std::size_t q[3] = {j, k, l};
          for (int r = 0; r < 3; ++r) {
            Q norm = 0;
            for (int c = 0; c < 3; ++c) {
              m[r][c] = 2 * (p[q[r]].c[c] - p[i].c[c]);
              norm += (p[q[r]].c[c] - p[i].c[c]) * (p[q[r]].c[c] - p[i].c[c]);
            }
            rhs[r] = norm;
          }
          const Q d = det3(m);
          if (d == 0) continue;
          Q u[3];
          for (int c = 0; c < 3; ++c) {
            Q t[3][3];
            for (int r = 0; r < 3; ++r)
              for (int cc = 0; cc < 3; ++cc) t[r][cc] = cc == c ? rhs[r] : m[r][cc];
            u[c] = det3(t) / d;  // circumcentre - p[i]
          }
          const Q r2 = u[0] * u[0] + u[1] * u[1] + u[2] * u[2];
          bool empty = true, on_sphere = false;
          for (std::size_t s = 0; s < n && empty; ++s) {
            if (s == i || s == j || s == k || s == l) continue;
            Q dist = 0;
            for (int c = 0; c < 3; ++c) dist += (p[s].c[c] - p[i].c[c] - u[c]) * (p[s].c[c] - p[i].c[c] - u[c]);
            if (dist == r2) on_sphere = true;
            if (dist < r2) empty = false;
          }
          if (!empty) continue;
          if (on_sphere) {
            validation_failure("DEGENERATE_COSPHERICAL",
                               "Five input points lie on one empty sphere: the Delaunay triangulation is not unique");
          }
          result.push_back({{i, j, k, l}, r2});
        }
  return result;
}

Json run_alpha_3(const Request& request) {
  const std::string validator = "shape.validate.alpha_shape_3";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"alpha"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "alpha_shape_3");
  const auto raw = read_points3(request.inputs[1]);
  const std::size_t n = raw.size();
  if (n < 4 || n > kMaximumAlpha3Points) validation_failure("POINT_COUNT", "Between 4 and 24 points are supported");
  const Q alpha = alpha_of(request);
  std::vector<Pt<3>> p(n);
  for (std::size_t i = 0; i < n; ++i) {
    for (int k = 0; k < 3; ++k) p[i].c[k] = exact_of(raw[i][k]);
    for (std::size_t j = 0; j < i; ++j) {
      if (p[i].c[0] == p[j].c[0] && p[i].c[1] == p[j].c[1] && p[i].c[2] == p[j].c[2]) {
        validation_failure("DUPLICATE_POINT", "Input points must be pairwise distinct");
      }
    }
  }
  const std::string operation = report.value("operation", std::string());
  if (operation != "shape.alpha_shape_3" && operation != "shape.fixed_alpha_shape_3") {
    validation_failure("PARAMETER_MISMATCH", "Report is not a 3D alpha shape report");
  }
  Json checks;
  const auto results = batch2::check_report_frame(report, operation, {{"alpha", request.parameters.at("alpha")}},
                                                  {{"points_sha256", &request.inputs[1]}}, checks);
  if (require_member(results, "alpha_unit", "results") != request.inputs[1].unit + "^2") {
    validation_failure("UNIT_MISMATCH", "alpha_unit must be the squared artifact unit");
  }
  checks["alpha_unit_is_squared_artifact_unit"] = true;
  const auto cells = delaunay_3(p);
  if (cells.empty()) validation_failure("ALL_COPLANAR", "The points are coplanar");
  std::set<Tuple> interior;
  const auto regular = regular_faces(cells, alpha, interior);
  if (tuple_set(require_member(results, "interior_cells", "results"), 4, n, "interior_cells") != interior) {
    validation_failure("INTERIOR_MISMATCH", "The interior cells differ from the exact alpha complex");
  }
  checks["interior_cells_equal_exact_delaunay_cells_within_alpha"] = true;
  if (tuple_set(require_member(results, "regular_facets", "results"), 3, n, "regular_facets") != regular) {
    validation_failure("REGULAR_FACET_MISMATCH", "The regular facets differ from the exact boundary of the alpha complex");
  }
  checks["regular_facets_equal_exact_boundary_of_interior_cells"] = true;
  return concluded(request, validator, checks,
                   {{"delaunay_cell_count", cells.size()}, {"interior_cell_count", interior.size()},
                    {"regular_facet_count", regular.size()},
                    {"independence", "exact rational empty-sphere search and circumradius; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> alpha_validators() {
  using query_ops::query_definition;
  const std::string gmp = "exact:GMP";
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "shape.validate.alpha_shape_2", {"GeometryQueryReport", "PointSet2"}, "ValidationReport", "validator", run_alpha_2,
      {"Alpha_shapes_2"}, gmp,
      vinfo({"parameters_match", "source_matches", "alpha_unit_is_squared_artifact_unit",
             "interior_triangles_equal_exact_delaunay_triangles_within_alpha",
             "regular_edges_equal_exact_boundary_of_interior_triangles"},
            {"candidate", "points"}, "exact rational empty-circle search and circumradius; no CGAL header")));
  result.push_back(query_definition(
      "shape.validate.alpha_shape_3", {"GeometryQueryReport", "PointSet3"}, "ValidationReport", "validator", run_alpha_3,
      {"Alpha_shapes_3"}, gmp,
      vinfo({"parameters_match", "source_matches", "alpha_unit_is_squared_artifact_unit",
             "interior_cells_equal_exact_delaunay_cells_within_alpha",
             "regular_facets_equal_exact_boundary_of_interior_cells"},
            {"candidate", "points"}, "exact rational empty-sphere search and circumradius; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch4
