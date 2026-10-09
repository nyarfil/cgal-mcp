// Independent validators for the OpenGR registration operations (7.9.05). No CGAL header is included.
// The recovered motion is applied in exact rationals (GMP) to the raw binary64 input; the residual
// to the reference set is the exact nearest-neighbour squared distance, so RMS and inlier decisions
// are exact comparisons of squares. Super4PCS is a global registration with an accuracy parameter,
// so the tolerances (max_rms, inlier_distance, min_inlier_fraction) are explicit typed parameters.

#include "b6_common.h"

#include <algorithm>
#include <cmath>

namespace cgal_master::batch6 {
namespace {

using batch2::concluded;
using batch2::dot;
using batch2::require_member;
using batch2::vec;
using batch2::vinfo;
using query_ops::exact_of;
using query_ops::read_points3;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::signed_length_parameter;
using query_ops::validation_failure;

struct Tolerances {
  double max_rms = 0;
  double inlier_distance = 0;
  double min_inlier_fraction = 0;
};

std::vector<V3> read_set(const ArtifactInput& input, const std::string& context) {
  auto points = read_points3(input);
  if (points.size() < reconstruction_ops::kMinimumPoints) validation_failure("POINT_SET_TOO_SMALL", context + " has fewer than ten points");
  if (points.size() > kMaximumRegistrationPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", context + " exceeds the registration point limit");
  }
  return points;
}

Tolerances read_tolerances(const Request& request, const std::string& unit) {
  Tolerances t;
  t.max_rms = signed_length_parameter(request, "max_rms", unit);
  t.inlier_distance = signed_length_parameter(request, "inlier_distance", unit);
  const auto& fraction = request.parameters.at("min_inlier_fraction");
  if (!fraction.is_number() || fraction.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "min_inlier_fraction must be a number");
  }
  t.min_inlier_fraction = fraction.get<double>();
  if (!(t.max_rms > 0) || !(t.inlier_distance > 0) || !(t.min_inlier_fraction > 0) || !(t.min_inlier_fraction <= 1)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "max_rms and inlier_distance must be positive; min_inlier_fraction must lie in (0,1]");
  }
  return t;
}

struct Residual {
  Q mean_squared;
  Q maximum_squared;
  std::size_t inliers = 0;
  std::size_t count = 0;
};

Q squared_distance(const Vec& a, const Vec& b) {
  const Vec d = a - b;
  return dot(d, d);
}

Residual residual_to(const std::vector<Vec>& moved, const std::vector<Vec>& reference, const Q& inlier_squared) {
  Residual r;
  r.count = moved.size();
  Q total = 0;
  for (const auto& p : moved) {
    Q best = squared_distance(p, reference[0]);
    for (std::size_t j = 1; j < reference.size(); ++j) {
      const Q d = squared_distance(p, reference[j]);
      if (d < best) best = d;
    }
    total += best;
    if (best > r.maximum_squared) r.maximum_squared = best;
    if (best <= inlier_squared) ++r.inliers;
  }
  r.mean_squared = total / Q(static_cast<unsigned long>(moved.size()));
  return r;
}

void require_alignment(const Residual& r, const Tolerances& t, Json& checks) {
  const Q rms_bound = exact_of(t.max_rms) * exact_of(t.max_rms);
  if (r.mean_squared > rms_bound) {
    validation_failure("RESIDUAL_RMS_EXCEEDED", "The exact RMS nearest-neighbour residual exceeds max_rms");
  }
  checks["residual_rms_within_bound_exact"] = true;
  const Q inlier_squared = exact_of(t.inlier_distance) * exact_of(t.inlier_distance);
  (void)inlier_squared;
  const double fraction = static_cast<double>(r.inliers) / static_cast<double>(r.count);
  if (fraction < t.min_inlier_fraction) {
    validation_failure("INLIER_FRACTION_TOO_LOW", "Too few moved points lie within inlier_distance of the reference");
  }
  checks["inlier_fraction_within_bound_exact"] = true;
}

Json alignment_details(const Residual& r, const Tolerances& t) {
  return Json{{"point_count", r.count},
              {"inlier_count", r.inliers},
              {"inlier_fraction", static_cast<double>(r.inliers) / static_cast<double>(r.count)},
              {"mean_squared_residual", query_ops::q_text(r.mean_squared)},
              {"residual_rms", std::sqrt(r.mean_squared.get_d())},
              {"maximum_residual", std::sqrt(r.maximum_squared.get_d())},
              {"max_rms", t.max_rms},
              {"inlier_distance", t.inlier_distance},
              {"min_inlier_fraction", t.min_inlier_fraction}};
}

Q determinant3(const Vec& a, const Vec& b, const Vec& c) {
  return a.x * (b.y * c.z - b.z * c.y) - a.y * (b.x * c.z - b.z * c.x) + a.z * (b.x * c.y - b.y * c.x);
}

// ---- transformation report ---------------------------------------------------------------------

Json run_transformation_validator(const Request& request) {
  const std::string validator = "pointset.validate.registration_transformation";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {"max_rms", "inlier_distance", "min_inlier_fraction"});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "registration_transformation");
  const auto reference = read_set(request.inputs[1], "reference");
  const auto moving = read_set(request.inputs[2], "moving");
  const auto tolerances = read_tolerances(request, request.inputs[1].unit);
  Json checks = Json::object();
  if (report.value("operation", std::string()) != "pointset.registration.compute_transformation") {
    validation_failure("PARAMETER_MISMATCH", "Report is not a registration transformation report");
  }
  const auto source = require_member(report, "source", "report");
  if (!source.is_object() || source.value("reference_sha256", std::string()) != request.inputs[1].sha256 ||
      source.value("moving_sha256", std::string()) != request.inputs[2].sha256) {
    validation_failure("SOURCE_MISMATCH", "Report does not describe the validated point sets");
  }
  checks["source_matches"] = true;
  const auto parameters = require_member(report, "parameters", "report");
  for (const char* name : {"max_rms", "inlier_distance", "min_inlier_fraction"}) {
    if (!parameters.is_object() || !parameters.contains(name) || parameters.at(name) != request.parameters.at(name)) {
      validation_failure("PARAMETER_MISMATCH", "Report tolerances differ from the validated request");
    }
  }
  checks["parameters_match"] = true;
  const auto results = require_member(report, "results", "report");
  const auto matrix = require_member(results, "transformation_row_major_3x4", "results");
  if (!matrix.is_array() || matrix.size() != 12) validation_failure("REPORT_SCHEMA_MISMATCH", "The transformation must hold 12 numbers");
  Q m[3][4];
  for (int row = 0; row < 3; ++row) {
    for (int column = 0; column < 4; ++column) {
      const auto& item = matrix.at(static_cast<std::size_t>(row * 4 + column));
      if (!item.is_number() || item.is_boolean() || !std::isfinite(item.get<double>())) {
        validation_failure("REPORT_SCHEMA_MISMATCH", "Transformation entries must be finite numbers");
      }
      m[row][column] = exact_of(item.get<double>());
    }
  }
  // Rotation block: R R^T = I and det R = +1 within 1e-9 (declared rigidity tolerance).
  const Q rigid_tolerance = exact_of(1e-9);
  for (int i = 0; i < 3; ++i) {
    for (int j = 0; j < 3; ++j) {
      Q sum = 0;
      for (int k = 0; k < 3; ++k) sum += m[i][k] * m[j][k];
      if (i == j) sum -= 1;
      if (abs(sum) > rigid_tolerance) validation_failure("TRANSFORMATION_NOT_RIGID", "The rotation block is not orthonormal");
    }
  }
  const Q determinant = determinant3({m[0][0], m[0][1], m[0][2]}, {m[1][0], m[1][1], m[1][2]}, {m[2][0], m[2][1], m[2][2]});
  if (abs(determinant - 1) > rigid_tolerance) {
    validation_failure("TRANSFORMATION_NOT_PROPER_ROTATION", "The rotation block does not have determinant +1");
  }
  checks["transformation_is_rigid_motion"] = true;
  std::vector<Vec> moved, ref;
  for (const auto& p : moving) {
    const Vec v = vec(p);
    moved.push_back(Vec{m[0][0] * v.x + m[0][1] * v.y + m[0][2] * v.z + m[0][3],
                        m[1][0] * v.x + m[1][1] * v.y + m[1][2] * v.z + m[1][3],
                        m[2][0] * v.x + m[2][1] * v.y + m[2][2] * v.z + m[2][3]});
  }
  for (const auto& p : reference) ref.push_back(vec(p));
  const Q inlier_squared = exact_of(tolerances.inlier_distance) * exact_of(tolerances.inlier_distance);
  const auto residual = residual_to(moved, ref, inlier_squared);
  require_alignment(residual, tolerances, checks);
  auto details = alignment_details(residual, tolerances);
  details["independence"] =
      "transformation applied to the raw binary64 moving points in exact GMP rationals; exact nearest-neighbour squared distances to the reference; no CGAL header";
  return concluded(request, validator, checks, details);
}

// ---- registered point set --------------------------------------------------------------------

Json run_registered_validator(const Request& request) {
  const std::string validator = "pointset.validate.registered_points";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {"max_rms", "inlier_distance", "min_inlier_fraction"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto candidate = read_set(request.inputs[0], "candidate");
  const auto reference = read_set(request.inputs[1], "reference");
  const auto moving = read_set(request.inputs[2], "moving");
  const auto tolerances = read_tolerances(request, request.inputs[1].unit);
  if (candidate.size() != moving.size()) {
    validation_failure("POINT_COUNT_MISMATCH", "The registered set must keep the point count of the moving set");
  }
  Json checks = Json::object();
  checks["point_count_preserved"] = true;
  std::vector<Vec> c, mv, ref;
  for (const auto& p : candidate) c.push_back(vec(p));
  for (const auto& p : moving) mv.push_back(vec(p));
  for (const auto& p : reference) ref.push_back(vec(p));
  // Rigid image: every pairwise squared distance is preserved within 2e-9 * (bounding diagonal)^2,
  // the rounding band of one binary64 transformation of the whole set.
  V3 low = moving[0], high = moving[0];
  for (const auto& p : moving) {
    for (int k = 0; k < 3; ++k) {
      low[k] = std::min(low[k], p[k]);
      high[k] = std::max(high[k], p[k]);
    }
  }
  const Vec diagonal = vec(high) - vec(low);
  const Q pair_tolerance = exact_of(2e-9) * dot(diagonal, diagonal);
  for (std::size_t i = 0; i < c.size(); ++i) {
    for (std::size_t j = i + 1; j < c.size(); ++j) {
      if (abs(squared_distance(c[i], c[j]) - squared_distance(mv[i], mv[j])) > pair_tolerance) {
        validation_failure("NOT_A_RIGID_IMAGE", "The registered set does not preserve the pairwise distances of the moving set");
      }
    }
  }
  checks["pairwise_distances_preserved"] = true;
  // Chirality: a reflection preserves distances. Find an exactly non-degenerate moving tetrahedron.
  bool oriented = false;
  for (std::size_t a = 1; a < mv.size() && !oriented; ++a) {
    for (std::size_t b = a + 1; b < mv.size() && !oriented; ++b) {
      for (std::size_t d = b + 1; d < mv.size() && !oriented; ++d) {
        const Q before = determinant3(mv[a] - mv[0], mv[b] - mv[0], mv[d] - mv[0]);
        if (before == 0) continue;
        const Q after = determinant3(c[a] - c[0], c[b] - c[0], c[d] - c[0]);
        if ((before > 0) != (after > 0) || after == 0) {
          validation_failure("ORIENTATION_REVERSED", "The registered set is a reflection of the moving set");
        }
        oriented = true;
      }
    }
  }
  if (!oriented) validation_failure("DEGENERATE_POINT_SET", "The moving set has no non-degenerate tetrahedron");
  checks["orientation_preserved_exact"] = true;
  const Q inlier_squared = exact_of(tolerances.inlier_distance) * exact_of(tolerances.inlier_distance);
  const auto residual = residual_to(c, ref, inlier_squared);
  require_alignment(residual, tolerances, checks);
  auto details = alignment_details(residual, tolerances);
  details["independence"] =
      "exact rational pairwise-distance and tetrahedron-orientation comparison with the moving set, then exact nearest-neighbour squared distances to the reference; no CGAL header";
  return concluded(request, validator, checks, details);
}

}  // namespace

std::vector<OperationDefinition> registration_validators() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "pointset.validate.registration_transformation", {"GeometryQueryReport", "PointSet3", "PointSet3"},
      "ValidationReport", "validator", run_transformation_validator, {"Point_set_processing_3"}, "exact:GMP",
      vinfo({"source_matches", "parameters_match", "transformation_is_rigid_motion", "residual_rms_within_bound_exact",
             "inlier_fraction_within_bound_exact"},
            {"candidate", "reference", "moving"},
            "transformation applied to the raw binary64 moving points in exact GMP rationals; exact nearest-neighbour squared distances to the reference; no CGAL header")));
  result.push_back(query_ops::query_definition(
      "pointset.validate.registered_points", {"PointSet3", "PointSet3", "PointSet3"}, "ValidationReport", "validator",
      run_registered_validator, {"Point_set_processing_3"}, "exact:GMP",
      vinfo({"point_count_preserved", "pairwise_distances_preserved", "orientation_preserved_exact",
             "residual_rms_within_bound_exact", "inlier_fraction_within_bound_exact"},
            {"candidate", "reference", "moving"},
            "exact rational pairwise-distance and tetrahedron-orientation comparison with the moving set, then exact nearest-neighbour squared distances to the reference; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch6
