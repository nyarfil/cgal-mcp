// Independent validators for the point-set operations of batch 2: average spacing and
// outlier removal (7.9.02, 7.9.06) and minimum bounding circle / sphere (7.13.04). No CGAL
// header is included. Spacing and outlier measures need square roots, so they are
// recomputed by brute force in long double and compared with an explicit relative
// tolerance; decisions that sit inside the tolerance band are rejected instead of guessed.
// The bounding circle / sphere is an exact rational enumeration of every support set.

#include "b2_geometry.h"

#include <algorithm>
#include <cmath>
#include <functional>
#include <numeric>
#include <optional>

namespace cgal_master::batch2 {
namespace {

using query_ops::exact_of;
using query_ops::integer_parameter;
using query_ops::read_points2;
using query_ops::read_points3;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::signed_length_parameter;
using query_ops::validation_failure;

constexpr std::size_t kMaximumPoints3 = 400;
constexpr double kRelativeTolerance = 1e-9;

// Squared distances from point i to all points, ascending (long double).
std::vector<long double> sorted_squared_distances(const std::vector<V3>& points, std::size_t i) {
  std::vector<long double> result;
  result.reserve(points.size());
  for (const auto& p : points) {
    const long double dx = static_cast<long double>(p[0]) - points[i][0];
    const long double dy = static_cast<long double>(p[1]) - points[i][1];
    const long double dz = static_cast<long double>(p[2]) - points[i][2];
    result.push_back(dx * dx + dy * dy + dz * dz);
  }
  std::sort(result.begin(), result.end());
  return result;
}

std::size_t neighbors_parameter(const Request& request, std::size_t point_count) {
  const auto neighbors = integer_parameter(request, "neighbors", 2, 1000);
  if (neighbors >= point_count) {
    validation_failure("NEIGHBORHOOD_TOO_LARGE", "neighbors must be smaller than the point count");
  }
  return neighbors;
}

void require_point_limit(const std::vector<V3>& points, const std::string& context) {
  if (points.empty()) validation_failure("POINT_SET_EMPTY", context + " has no points");
  if (points.size() > kMaximumPoints3) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", context + " exceeds the point limit");
  }
}

// ---- 7.9 average spacing --------------------------------------------------------------------

Json run_spacing_validator(const Request& request) {
  const std::string validator = "pointset.validate.average_spacing";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"neighbors"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "average_spacing");
  const auto points = read_points3(request.inputs[1]);
  require_point_limit(points, "points");
  const auto neighbors = neighbors_parameter(request, points.size());
  Json checks;
  const auto results = check_report_frame(report, "pointset.spacing.average", Json{{"neighbors", neighbors}},
                                          {{"points_sha256", &request.inputs[1]}}, checks);
  long double sum = 0;
  for (std::size_t i = 0; i < points.size(); ++i) {
    const auto distances = sorted_squared_distances(points, i);
    long double per_point = 0;
    for (std::size_t j = 0; j < neighbors + 1; ++j) per_point += std::sqrt(distances[j]);
    sum += per_point / static_cast<long double>(neighbors + 1);
  }
  const long double expected = sum / static_cast<long double>(points.size());
  const auto value = require_member(results, "average_spacing", "results");
  if (!value.is_object() || !value.contains("value") || !value.at("value").is_number() ||
      value.value("unit", std::string()) != request.inputs[1].unit) {
    validation_failure("REPORT_VALUE_INVALID", "average_spacing must be a TypedLength in the artifact unit");
  }
  const long double reported = value.at("value").get<double>();
  if (!(std::fabs(static_cast<double>(reported - expected)) <= kRelativeTolerance * static_cast<double>(std::max<long double>(expected, 1e-300L)))) {
    validation_failure("AVERAGE_SPACING_MISMATCH", "Reported average spacing differs from the brute-force value");
  }
  checks["average_spacing_matches_bruteforce"] = true;
  return concluded(request, validator, checks,
                   {{"neighbors", neighbors}, {"point_count", points.size()},
                    {"expected_average_spacing", static_cast<double>(expected)},
                    {"relative_tolerance", kRelativeTolerance},
                    {"independence", "brute-force k+1 nearest distances in long double (self included, as the CGAL neighbour query); no CGAL header"}});
}

// ---- 7.9 outlier removal ----------------------------------------------------------------------

Json run_outliers_validator(const Request& request) {
  const std::string validator = "pointset.validate.outliers_removed";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"neighbors", "threshold_percent", "threshold_distance"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto candidate = read_points3(request.inputs[0]);
  const auto source = read_points3(request.inputs[1]);
  require_point_limit(source, "source");
  const auto neighbors = neighbors_parameter(request, source.size());
  const auto& percent_value = request.parameters.at("threshold_percent");
  if (!percent_value.is_number() || percent_value.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "threshold_percent must be a number");
  }
  const double percent = percent_value.get<double>();
  if (!std::isfinite(percent) || percent < 0 || percent > 100) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "threshold_percent must be in [0,100]");
  }
  const double distance = signed_length_parameter(request, "threshold_distance", request.inputs[1].unit);
  if (distance < 0) throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "threshold_distance must be >= 0");

  const std::size_t n = source.size();
  std::vector<long double> measure(n);
  for (std::size_t i = 0; i < n; ++i) {
    const auto distances = sorted_squared_distances(source, i);
    long double total = 0;
    for (std::size_t j = 0; j < neighbors + 1; ++j) total += distances[j];
    measure[i] = total / static_cast<long double>(neighbors + 1);
  }
  const long double squared_threshold = static_cast<long double>(distance) * static_cast<long double>(distance);
  std::size_t good = 0;
  if (distance != 0) {
    for (const auto m : measure) {
      if (std::fabs(static_cast<double>(m - squared_threshold)) <=
          kRelativeTolerance * static_cast<double>(std::max(m, squared_threshold))) {
        validation_failure("AMBIGUOUS_THRESHOLD",
                           "A point measure lies within the relative tolerance of the threshold distance");
      }
      if (m < squared_threshold) ++good;
    }
  }
  const std::size_t first_index = static_cast<std::size_t>(static_cast<double>(n) * ((100.0 - percent) / 100.0));
  const std::size_t kept = std::min(n, std::max(good, first_index));
  if (candidate.size() != kept) {
    validation_failure("KEPT_COUNT_MISMATCH", "The candidate keeps a different number of points than the thresholds imply");
  }

  // Multiset subset by exact coordinate; kept points must be the lowest measures.
  std::map<std::array<double, 3>, std::vector<long double>> by_coordinate;
  for (std::size_t i = 0; i < n; ++i) by_coordinate[{source[i][0], source[i][1], source[i][2]}].push_back(measure[i]);
  long double kept_maximum = -1;
  for (const auto& p : candidate) {
    auto it = by_coordinate.find({p[0], p[1], p[2]});
    if (it == by_coordinate.end() || it->second.empty()) {
      validation_failure("CANDIDATE_NOT_SUBSET", "A candidate point is not a (remaining) source point");
    }
    kept_maximum = std::max(kept_maximum, it->second.back());
    it->second.pop_back();
  }
  long double removed_minimum = -1;
  bool any_removed = false;
  for (const auto& [coordinate, remaining] : by_coordinate) {
    for (const auto m : remaining) {
      removed_minimum = any_removed ? std::min(removed_minimum, m) : m;
      any_removed = true;
    }
  }
  if (any_removed && kept_maximum > removed_minimum &&
      std::fabs(static_cast<double>(kept_maximum - removed_minimum)) > kRelativeTolerance * static_cast<double>(kept_maximum)) {
    validation_failure("REMOVED_POINT_LESS_OUTLYING", "A removed point has a lower outlier measure than a kept point");
  }
  Json checks = json_checks({"candidate_is_source_multiset_subset", "kept_count_matches_thresholds",
                             "kept_points_have_lowest_measures"});
  return concluded(request, validator, checks,
                   {{"neighbors", neighbors}, {"source_point_count", n}, {"kept_point_count", kept},
                    {"removed_point_count", n - kept}, {"points_below_threshold_distance", good},
                    {"percent_keep_index", first_index}, {"relative_tolerance", kRelativeTolerance},
                    {"independence", "brute-force average squared distance to the k+1 nearest points (self included) in long double; no CGAL header"}});
}

// ---- 7.13.04 minimum bounding circle / sphere ---------------------------------------------------

// Solves G lambda = b exactly; returns false for a singular system.
bool solve_exact(std::vector<std::vector<Q>> g, std::vector<Q> b, std::vector<Q>& lambda) {
  const std::size_t k = b.size();
  for (std::size_t col = 0; col < k; ++col) {
    std::size_t pivot = col;
    while (pivot < k && g[pivot][col] == 0) ++pivot;
    if (pivot == k) return false;
    std::swap(g[pivot], g[col]);
    std::swap(b[pivot], b[col]);
    for (std::size_t row = 0; row < k; ++row) {
      if (row == col || g[row][col] == 0) continue;
      const Q factor = g[row][col] / g[col][col];
      for (std::size_t c = col; c < k; ++c) g[row][c] -= factor * g[col][c];
      b[row] -= factor * b[col];
    }
  }
  lambda.assign(k, 0);
  for (std::size_t i = 0; i < k; ++i) lambda[i] = b[i] / g[i][i];
  return true;
}

struct Ball {
  Vec center;
  Q squared_radius;
};

std::optional<Ball> support_ball(const std::vector<Vec>& support) {
  const Vec& p0 = support[0];
  const std::size_t k = support.size() - 1;
  if (k == 0) return Ball{p0, 0};
  std::vector<Vec> u;
  for (std::size_t i = 1; i <= k; ++i) u.push_back(support[i] - p0);
  std::vector<std::vector<Q>> g(k, std::vector<Q>(k));
  std::vector<Q> b(k);
  for (std::size_t i = 0; i < k; ++i) {
    for (std::size_t j = 0; j < k; ++j) g[i][j] = dot(u[i], u[j]);
    b[i] = dot(u[i], u[i]) / 2;
  }
  std::vector<Q> lambda;
  if (!solve_exact(g, b, lambda)) return std::nullopt;
  Vec offset{0, 0, 0};
  for (std::size_t i = 0; i < k; ++i) offset = offset + lambda[i] * u[i];
  return Ball{p0 + offset, dot(offset, offset)};
}

// Exact minimum enclosing ball of the points (support sets of 1..dimension+1 points).
Ball exact_minimum_ball(const std::vector<Vec>& points, std::size_t dimension) {
  std::optional<Ball> best;
  std::vector<Vec> support;
  std::function<void(std::size_t)> recurse = [&](std::size_t start) {
    if (!support.empty()) {
      if (const auto ball = support_ball(support)) {
        bool encloses = true;
        for (const auto& p : points) {
          const Vec d = p - ball->center;
          if (dot(d, d) > ball->squared_radius) {
            encloses = false;
            break;
          }
        }
        if (encloses && (!best || ball->squared_radius < best->squared_radius)) best = *ball;
      }
    }
    if (support.size() == dimension + 1) return;
    for (std::size_t i = start; i < points.size(); ++i) {
      support.push_back(points[i]);
      recurse(i + 1);
      support.pop_back();
    }
  };
  recurse(0);
  if (!best) validation_failure("NO_ENCLOSING_BALL", "No support set encloses the points (internal error)");
  return *best;
}

Json run_bounding_validator(const Request& request, bool circle) {
  const std::string validator = circle ? "shape.validate.min_circle" : "shape.validate.min_sphere";
  require_inputs(request, 2, validator);
  std::vector<Vec> points;
  double radius = 0;
  Json expected_parameters = Json::object();
  if (circle) {
    require_parameter_names(request, {});
    for (const auto& p : read_points2(request.inputs[1])) points.push_back(Vec{exact_of(p[0]), exact_of(p[1]), 0});
    if (points.size() > 64) throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "At most 64 points");
  } else {
    require_parameter_names(request, {"radius"});
    radius = signed_length_parameter(request, "radius", request.inputs[1].unit);
    if (radius < 0) throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "radius must be >= 0");
    for (const auto& p : read_points3(request.inputs[1])) points.push_back(vec(p));
    if (points.size() > 32) throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "At most 32 points");
    expected_parameters = Json{{"radius", {{"value", radius}, {"unit", request.inputs[1].unit}}}};
  }
  if (points.empty()) validation_failure("POINT_SET_EMPTY", "The point set is empty");
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "minimum_bounding_ball");
  Json checks;
  const auto results = check_report_frame(report, circle ? "shape.bounding.circle" : "shape.bounding.sphere",
                                          expected_parameters, {{"points_sha256", &request.inputs[1]}}, checks);
  const Ball exact = exact_minimum_ball(points, circle ? 2 : 3);
  const long double root = std::sqrt(static_cast<long double>(exact.squared_radius.get_d()));
  const long double expected_radius = root + radius;
  const auto center = require_member(results, "center", "results");
  const std::size_t dimension = circle ? 2 : 3;
  if (!center.is_array() || center.size() != dimension) {
    validation_failure("REPORT_VALUE_INVALID", "center has the wrong dimension");
  }
  const std::array<Q, 3> exact_center{exact.center.x, exact.center.y, exact.center.z};
  long double scale = 1;
  for (std::size_t i = 0; i < dimension; ++i) scale = std::max(scale, std::fabs(static_cast<long double>(exact_center[i].get_d())));
  scale = std::max(scale, expected_radius);
  for (std::size_t i = 0; i < dimension; ++i) {
    if (!center[i].is_number()) validation_failure("REPORT_VALUE_INVALID", "center must be numeric");
    if (std::fabs(static_cast<long double>(center[i].get<double>()) - static_cast<long double>(exact_center[i].get_d())) >
        kRelativeTolerance * scale) {
      validation_failure("CENTER_MISMATCH", "The reported center differs from the exact minimum ball center");
    }
  }
  checks["center_matches_exact_minimum"] = true;
  const auto reported_radius = require_member(results, "radius", "results");
  if (!reported_radius.is_object() || !reported_radius.at("value").is_number() ||
      reported_radius.value("unit", std::string()) != request.inputs[1].unit) {
    validation_failure("REPORT_VALUE_INVALID", "radius must be a TypedLength in the artifact unit");
  }
  if (std::fabs(static_cast<long double>(reported_radius.at("value").get<double>()) - expected_radius) >
      kRelativeTolerance * scale) {
    validation_failure("RADIUS_MISMATCH", "The reported radius differs from the exact minimum ball radius");
  }
  checks["radius_matches_exact_minimum"] = true;
  // Enclosure of every (common-radius) ball by the reported ball, exactly up to the same tolerance.
  const long double reported = reported_radius.at("value").get<double>();
  for (const auto& p : points) {
    long double squared = 0;
    for (std::size_t i = 0; i < dimension; ++i) {
      const std::array<Q, 3> coordinate{p.x, p.y, p.z};
      const long double delta = static_cast<long double>(coordinate[i].get_d()) - static_cast<long double>(center[i].get<double>());
      squared += delta * delta;
    }
    if (std::sqrt(squared) + radius > reported + kRelativeTolerance * scale) {
      validation_failure("BALL_NOT_ENCLOSED", "A ball of the input is not enclosed by the reported ball");
    }
  }
  checks["all_balls_enclosed"] = true;
  return concluded(request, validator, checks,
                   {{"point_count", points.size()}, {"dimension", dimension}, {"common_ball_radius", radius},
                    {"exact_squared_radius_of_points", query_ops::q_text(exact.squared_radius)},
                    {"relative_tolerance", kRelativeTolerance},
                    {"independence", "exact rational enumeration of every support set of 1..d+1 points (center in the affine hull); no CGAL header"}});
}

Json run_circle_validator(const Request& request) { return run_bounding_validator(request, true); }
Json run_sphere_validator(const Request& request) { return run_bounding_validator(request, false); }

}  // namespace

std::vector<OperationDefinition> points_validator_operations() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "pointset.validate.average_spacing", {"GeometryQueryReport", "PointSet3"}, "ValidationReport", "validator",
      run_spacing_validator, {"Point_set_processing_3"}, "float:long_double",
      vinfo({"parameters_match", "source_matches", "average_spacing_matches_bruteforce"}, {"candidate", "points"},
            "brute-force k+1 nearest distances in long double (self included, as the CGAL neighbour query); no CGAL header")));
  result.push_back(query_definition(
      "pointset.validate.outliers_removed", {"PointSet3", "PointSet3"}, "ValidationReport", "validator",
      run_outliers_validator, {"Point_set_processing_3"}, "float:long_double",
      vinfo({"candidate_is_source_multiset_subset", "kept_count_matches_thresholds", "kept_points_have_lowest_measures"},
            {"candidate", "source"},
            "brute-force average squared distance to the k+1 nearest points (self included) in long double; no CGAL header")));
  result.push_back(query_definition(
      "shape.validate.min_circle", {"GeometryQueryReport", "PointSet2"}, "ValidationReport", "validator",
      run_circle_validator, {"Bounding_volumes"}, "exact:GMP",
      vinfo({"parameters_match", "source_matches", "center_matches_exact_minimum", "radius_matches_exact_minimum",
             "all_balls_enclosed"},
            {"candidate", "points"}, "exact rational enumeration of every support set of 1..d+1 points (center in the affine hull); no CGAL header")));
  result.push_back(query_definition(
      "shape.validate.min_sphere", {"GeometryQueryReport", "PointSet3"}, "ValidationReport", "validator",
      run_sphere_validator, {"Bounding_volumes"}, "exact:GMP",
      vinfo({"parameters_match", "source_matches", "center_matches_exact_minimum", "radius_matches_exact_minimum",
             "all_balls_enclosed"},
            {"candidate", "points"}, "exact rational enumeration of every support set of 1..d+1 points (center in the affine hull); no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch2
