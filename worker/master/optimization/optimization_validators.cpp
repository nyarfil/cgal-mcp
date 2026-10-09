// Independent validators for the optimization / numerical-geometry family (7.15).
//
// This translation unit includes no CGAL header. Policy:
//   * QP_solver reports are accepted only with a checked proof: exact GMP
//     primal feasibility plus the optimality (KKT), infeasibility (Farkas) or
//     unboundedness certificate of the CGAL QP_solver manual (Lemmas 1-3),
//     an exact LDL^T semidefiniteness test of D and the exact objective value;
//   * natural-neighbour coordinates are re-derived as exact Voronoi areas by
//     rational half-plane clipping (Sibson's definition); linear interpolation
//     must match exactly, Sibson C1 within 1e-9 relative to the data scale;
//   * the interval p-center is re-solved by exhaustive exact candidate
//     enumeration and an independent greedy feasibility test;
//   * mesh approximation partitions, L21 proxies and errors are recomputed in
//     long double from the source mesh, together with brute-force
//     point-to-triangle deviations.

#include "optimization_common.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <queue>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace cgal_master::optimization_ops {
namespace {

void require_result_keys(const Json& value, std::initializer_list<const char*> keys, const std::string& context) {
  if (!value.is_object()) validation_failure("REPORT_SCHEMA_MISMATCH", context + " must be an object");
  std::set<std::string> expected(keys.begin(), keys.end());
  std::set<std::string> actual;
  for (const auto& item : value.items()) actual.insert(item.key());
  if (actual != expected) validation_failure("REPORT_SCHEMA_MISMATCH", context + " has missing or unexpected keys");
}

std::vector<Q> rational_list(const Json& value, std::size_t size, const std::string& context) {
  if (!value.is_array() || value.size() != size) {
    validation_failure("REPORT_SCHEMA_MISMATCH", context + " must have " + std::to_string(size) + " entries");
  }
  std::vector<Q> result;
  for (std::size_t i = 0; i < size; ++i) result.push_back(reported_rational(value[i], context));
  return result;
}

std::size_t count_value(const Json& value, const std::string& context) {
  if (!value.is_number_unsigned()) validation_failure("REPORT_SCHEMA_MISMATCH", context + " must be a count");
  return value.get<std::size_t>();
}

double finite_number(const Json& value, const std::string& context) {
  if (!value.is_number()) validation_failure("REPORT_VALUE_INVALID", context + " must be a number");
  const double result = value.get<double>();
  if (!std::isfinite(result)) validation_failure("REPORT_VALUE_INVALID", context + " must be finite");
  return result;
}

Json validator_report(const std::string& validates, Json checks, Json details) {
  Json report{{"schema_version", 1}, {"validates", validates}, {"checks", std::move(checks)},
              {"independence", "no CGAL header is used by this validator translation unit"}};
  for (auto& item : details.items()) report[item.key()] = item.value();
  return report;
}

// ---- 7.15.01 QP certificates ---------------------------------------------------------

// Exact LDL^T test: a symmetric matrix is PSD iff elimination never meets a negative
// pivot and every zero pivot has a zero row.
bool ldl_semidefinite(std::vector<std::vector<Q>> m) {
  const std::size_t n = m.size();
  for (std::size_t k = 0; k < n; ++k) {
    if (m[k][k] < 0) return false;
    if (m[k][k] == 0) {
      for (std::size_t j = k; j < n; ++j) {
        if (m[k][j] != 0) return false;
      }
      continue;
    }
    for (std::size_t i = k + 1; i < n; ++i) {
      if (m[i][k] == 0) continue;
      const Q factor = m[i][k] / m[k][k];
      for (std::size_t j = k; j < n; ++j) m[i][j] -= factor * m[k][j];
    }
  }
  return true;
}

Q row_value(const Constraint& row, const std::vector<Q>& x) {
  Q sum = 0;
  for (std::size_t j = 0; j < x.size(); ++j) sum += row.coefficients[j] * x[j];
  return sum;
}

void require_primal_feasible(const QuadraticProgramData& data, const std::vector<Q>& x) {
  for (std::size_t i = 0; i < data.constraints.size(); ++i) {
    const auto& row = data.constraints[i];
    const Q slack = row_value(row, x) - row.rhs;
    const bool ok = row.relation == Relation::kLess ? slack <= 0
                    : row.relation == Relation::kEqual ? slack == 0 : slack >= 0;
    if (!ok) validation_failure("INFEASIBLE_POINT", "Reported point violates constraint " + std::to_string(i));
  }
  for (std::size_t j = 0; j < x.size(); ++j) {
    if ((data.lower[j].finite && x[j] < data.lower[j].value) || (data.upper[j].finite && x[j] > data.upper[j].value)) {
      validation_failure("INFEASIBLE_POINT", "Reported point violates the bounds of variable " + std::to_string(j));
    }
  }
}

void require_multiplier_signs(const QuadraticProgramData& data, const std::vector<Q>& lambda) {
  for (std::size_t i = 0; i < lambda.size(); ++i) {
    const auto relation = data.constraints[i].relation;
    if ((relation == Relation::kLess && lambda[i] < 0) || (relation == Relation::kGreater && lambda[i] > 0)) {
      validation_failure("CERTIFICATE_INVALID", "Multiplier " + std::to_string(i) + " has the wrong sign");
    }
  }
}

std::vector<Q> twice_dx(const QuadraticProgramData& data, const std::vector<Q>& x) {
  std::vector<Q> result(x.size());
  for (std::size_t j = 0; j < x.size(); ++j) {
    for (std::size_t k = 0; k < x.size(); ++k) result[j] += 2 * data.d[j][k] * x[k];
  }
  return result;
}

Json validate_quadratic_program(const Request& request) {
  require_inputs(request, 2, "optimization.validate.quadratic_program");
  require_parameter_names(request, {"solver"});
  const auto solver = enum_parameter(request, "solver", {"linear", "quadratic"});
  const auto report = read_optimization_report(request.inputs[0], "quadratic_program");
  const auto data = read_quadratic_program(request.inputs[1]);
  Json checks = Json::object();
  const auto results = check_report_frame(request, report, "optimization.quadratic_program",
                                          {{"solver", solver}}, checks);
  require_result_keys(results, {"variables", "constraints", "status", "variable_values", "objective_value",
                                "certificate"},
                      "results");
  const std::size_t n = data.variables, m = data.constraints.size();
  if (count_value(results.at("variables"), "variables") != n ||
      count_value(results.at("constraints"), "constraints") != m) {
    validation_failure("RESULT_SET_INCOMPLETE", "Report program dimensions differ from the source");
  }
  if (solver == "linear" ? !data.d_is_zero : !ldl_semidefinite(data.d)) {
    validation_failure("NOT_POSITIVE_SEMIDEFINITE", "Objective matrix is not admissible for the solver");
  }
  checks["objective_convex"] = true;
  const auto& certificate = results.at("certificate");
  require_result_keys(certificate, {"kind", "values"}, "certificate");
  const auto status = results.at("status");
  if (status == "optimal") {
    if (certificate.at("kind") != "optimality") validation_failure("CERTIFICATE_INVALID", "Optimal needs an optimality certificate");
    const auto x = rational_list(results.at("variable_values"), n, "variable_values");
    const auto lambda = rational_list(certificate.at("values"), m, "optimality certificate");
    require_primal_feasible(data, x);
    require_multiplier_signs(data, lambda);
    for (std::size_t i = 0; i < m; ++i) {
      if (lambda[i] * (row_value(data.constraints[i], x) - data.constraints[i].rhs) != 0) {
        validation_failure("CERTIFICATE_INVALID", "Complementary slackness fails for constraint " + std::to_string(i));
      }
    }
    const auto dx = twice_dx(data, x);
    for (std::size_t j = 0; j < n; ++j) {
      Q tau = data.c[j] + dx[j];
      for (std::size_t i = 0; i < m; ++i) tau += lambda[i] * data.constraints[i].coefficients[j];
      const bool at_lower = data.lower[j].finite && x[j] == data.lower[j].value;
      const bool at_upper = data.upper[j].finite && x[j] == data.upper[j].value;
      const bool ok = (at_lower && at_upper) || (at_lower ? tau >= 0 : (at_upper ? tau <= 0 : tau == 0));
      if (!ok) validation_failure("CERTIFICATE_INVALID", "Reduced cost condition fails for variable " + std::to_string(j));
    }
    Q objective = data.c0;
    for (std::size_t j = 0; j < n; ++j) objective += data.c[j] * x[j] + x[j] * dx[j] / 2;
    if (reported_rational(results.at("objective_value"), "objective_value") != objective) {
      validation_failure("OBJECTIVE_MISMATCH", "Reported objective value differs from c^T x + x^T D x + c0");
    }
    checks["primal_feasible"] = true;
    checks["certificate_valid"] = true;
    checks["objective_matches"] = true;
  } else if (status == "infeasible") {
    if (certificate.at("kind") != "infeasibility" || !results.at("variable_values").is_null() ||
        !results.at("objective_value").is_null()) {
      validation_failure("CERTIFICATE_INVALID", "Infeasible needs only an infeasibility certificate");
    }
    const auto lambda = rational_list(certificate.at("values"), m, "infeasibility certificate");
    require_multiplier_signs(data, lambda);
    Q lambda_b = 0, bound_sum = 0;
    for (std::size_t i = 0; i < m; ++i) lambda_b += lambda[i] * data.constraints[i].rhs;
    for (std::size_t j = 0; j < n; ++j) {
      Q s = 0;
      for (std::size_t i = 0; i < m; ++i) s += lambda[i] * data.constraints[i].coefficients[j];
      if ((!data.upper[j].finite && s < 0) || (!data.lower[j].finite && s > 0)) {
        validation_failure("CERTIFICATE_INVALID", "Farkas column condition fails for variable " + std::to_string(j));
      }
      if (s < 0) bound_sum += s * data.upper[j].value;
      if (s > 0) bound_sum += s * data.lower[j].value;
    }
    if (!(lambda_b < bound_sum)) validation_failure("CERTIFICATE_INVALID", "Farkas inequality lambda^T b < bound sum fails");
    checks["primal_feasible"] = true;  // vacuous: infeasibility is proven
    checks["certificate_valid"] = true;
    checks["objective_matches"] = true;  // no objective for an infeasible program
  } else if (status == "unbounded") {
    if (certificate.at("kind") != "unboundedness" || !results.at("objective_value").is_null()) {
      validation_failure("CERTIFICATE_INVALID", "Unbounded needs an unboundedness certificate");
    }
    const auto x = rational_list(results.at("variable_values"), n, "variable_values");
    const auto w = rational_list(certificate.at("values"), n, "unboundedness certificate");
    require_primal_feasible(data, x);
    for (std::size_t i = 0; i < m; ++i) {
      const Q aw = row_value(data.constraints[i], w);
      const auto relation = data.constraints[i].relation;
      if ((relation == Relation::kLess && aw > 0) || (relation == Relation::kGreater && aw < 0) ||
          (relation == Relation::kEqual && aw != 0)) {
        validation_failure("CERTIFICATE_INVALID", "Direction leaves constraint " + std::to_string(i));
      }
    }
    for (std::size_t j = 0; j < n; ++j) {
      if ((data.lower[j].finite && w[j] < 0) || (data.upper[j].finite && w[j] > 0)) {
        validation_failure("CERTIFICATE_INVALID", "Direction leaves the bounds of variable " + std::to_string(j));
      }
    }
    const auto dw = twice_dx(data, w);
    const auto dx = twice_dx(data, x);
    Q wdw = 0, slope = 0;
    for (std::size_t j = 0; j < n; ++j) {
      wdw += w[j] * dw[j];
      slope += (data.c[j] + dx[j]) * w[j];
    }
    if (wdw != 0 || !(slope < 0)) validation_failure("CERTIFICATE_INVALID", "Direction is not an unbounded descent ray");
    checks["primal_feasible"] = true;
    checks["certificate_valid"] = true;
    checks["objective_matches"] = true;  // the objective is unbounded below
  } else {
    validation_failure("REPORT_VALUE_INVALID", "status must be optimal, infeasible or unbounded");
  }
  checks["result_set_complete"] = true;
  return finish_optimization_validation(
      request, "optimization.validate.quadratic_program",
      validator_report("optimization.quadratic_program", checks,
                       {{"status", status}, {"solver", solver},
                        {"proof", "QP_solver manual Lemma 1/2/3 certificate rechecked in exact GMP rationals"}}));
}

// ---- 7.15.02 natural-neighbour coordinates by exact Voronoi clipping ---------------------

using P2 = std::array<Q, 2>;
using Polygon = std::vector<P2>;

// Keep {y : a . y <= b}.
Polygon clip(const Polygon& polygon, const P2& a, const Q& b) {
  Polygon result;
  const std::size_t n = polygon.size();
  for (std::size_t i = 0; i < n; ++i) {
    const auto& p = polygon[i];
    const auto& q = polygon[(i + 1) % n];
    const Q fp = a[0] * p[0] + a[1] * p[1] - b;
    const Q fq = a[0] * q[0] + a[1] * q[1] - b;
    if (fp <= 0) result.push_back(p);
    if ((fp < 0 && fq > 0) || (fp > 0 && fq < 0)) {
      const Q t = fp / (fp - fq);
      result.push_back({p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])});
    }
  }
  return result;
}

Q area(const Polygon& polygon) {
  Q twice = 0;
  for (std::size_t i = 0; i < polygon.size(); ++i) {
    const auto& p = polygon[i];
    const auto& q = polygon[(i + 1) % polygon.size()];
    twice += p[0] * q[1] - p[1] * q[0];
  }
  return twice / 2;
}

// Keep the points at least as close to `near` as to `far`.
Polygon clip_closer(const Polygon& polygon, const P2& near, const P2& far) {
  const P2 a{2 * (far[0] - near[0]), 2 * (far[1] - near[1])};
  const Q b = far[0] * far[0] + far[1] * far[1] - near[0] * near[0] - near[1] * near[1];
  return clip(polygon, a, b);
}

int half(const P2& v) { return (v[1] < 0 || (v[1] == 0 && v[0] < 0)) ? 1 : 0; }

// Strictly interior to the convex hull of `sites` iff the distinct directions
// from x to the sites leave no angular gap of pi or more.
bool strictly_inside_hull(const std::vector<P2>& sites, const P2& x) {
  std::vector<P2> directions;
  for (const auto& s : sites) directions.push_back({s[0] - x[0], s[1] - x[1]});
  auto cross = [](const P2& a, const P2& b) { return Q(a[0] * b[1] - a[1] * b[0]); };
  std::sort(directions.begin(), directions.end(), [&](const P2& a, const P2& b) {
    if (half(a) != half(b)) return half(a) < half(b);
    return cross(a, b) > 0;
  });
  std::vector<P2> distinct;
  for (const auto& d : directions) {
    if (distinct.empty() || cross(distinct.back(), d) != 0 ||
        distinct.back()[0] * d[0] + distinct.back()[1] * d[1] < 0) {
      distinct.push_back(d);
    }
  }
  if (distinct.size() >= 2 && cross(distinct.back(), distinct.front()) == 0 &&
      distinct.back()[0] * distinct.front()[0] + distinct.back()[1] * distinct.front()[1] > 0) {
    distinct.pop_back();
  }
  if (distinct.size() < 3) return false;
  for (std::size_t i = 0; i < distinct.size(); ++i) {
    if (!(cross(distinct[i], distinct[(i + 1) % distinct.size()]) > 0)) return false;
  }
  return true;
}

// Unnormalized Sibson coordinates: area of the region the new cell of x takes
// from each site's Voronoi cell.
std::map<std::size_t, Q> natural_neighbor_areas(const std::vector<P2>& sites, const P2& x) {
  for (std::size_t i = 0; i < sites.size(); ++i) {
    if (sites[i] == x) return {{i, Q(1)}};
  }
  if (!strictly_inside_hull(sites, x)) {
    validation_failure("QUERY_NOT_INTERIOR", "A query is not strictly inside the convex hull of the sites");
  }
  Q extent = 1;
  for (const auto& s : sites) extent = std::max({extent, Q(abs(s[0] - x[0])), Q(abs(s[1] - x[1]))});
  for (int attempt = 0; attempt < 64; ++attempt, extent *= 16) {
    const Q big = extent * 4;
    Polygon cell{{x[0] - big, x[1] - big}, {x[0] + big, x[1] - big}, {x[0] + big, x[1] + big}, {x[0] - big, x[1] + big}};
    for (const auto& s : sites) cell = clip_closer(cell, x, s);
    bool touches = false;
    for (const auto& v : cell) {
      if (abs(v[0] - x[0]) == big || abs(v[1] - x[1]) == big) touches = true;
    }
    if (touches) continue;
    std::map<std::size_t, Q> result;
    for (std::size_t i = 0; i < sites.size(); ++i) {
      Polygon region = cell;
      for (std::size_t j = 0; j < sites.size() && region.size() >= 3; ++j) {
        if (j != i) region = clip_closer(region, sites[i], sites[j]);
      }
      if (region.size() >= 3) {
        const Q a = area(region);
        if (a > 0) result[i] = a;
      }
    }
    return result;
  }
  validation_failure("QUERY_NOT_INTERIOR", "The Voronoi cell of a query could not be bounded");
}

Json validate_interpolation(const Request& request) {
  require_inputs(request, 2, "optimization.validate.interpolation");
  require_parameter_names(request, {"method"});
  const auto method = enum_parameter(request, "method", {"linear", "sibson_c1"});
  const bool sibson = method == "sibson_c1";
  const auto report = read_optimization_report(request.inputs[0], "natural_neighbor_interpolation");
  const auto data = read_interpolation_data(request.inputs[1]);
  Json checks = Json::object();
  const auto results = check_report_frame(request, report, "optimization.interpolate", {{"method", method}}, checks);
  require_result_keys(results, {"kernel", "input_representation", "site_count", "queries"}, "results");
  if (results.at("kernel") != (sibson ? "CGAL::Exact_predicates_inexact_constructions_kernel"
                                      : "CGAL::Exact_predicates_exact_constructions_kernel") ||
      results.at("input_representation") != (sibson ? "binary64_round_to_nearest" : "exact_rational")) {
    validation_failure("KERNEL_MISMATCH", "Report kernel declaration differs from the method's kernel");
  }
  checks["kernel_matches"] = true;
  // The kernel received binary64-rounded inputs for sibson_c1 and exact rationals for linear.
  auto represent = [&](const Q& v) { return sibson ? exact_of_double(nearest_double(v)) : v; };
  std::vector<P2> sites;
  std::vector<Q> values;
  std::vector<P2> gradients;
  Q scale = 1;
  for (const auto& s : data.sites) {
    sites.push_back({represent(s.point[0]), represent(s.point[1])});
    values.push_back(represent(s.value));
    gradients.push_back({represent(s.gradient[0]), represent(s.gradient[1])});
    scale = std::max({scale, Q(abs(values.back())), Q(abs(gradients.back()[0])), Q(abs(gradients.back()[1]))});
  }
  const auto& queries = results.at("queries");
  if (count_value(results.at("site_count"), "site_count") != sites.size() || !queries.is_array() ||
      queries.size() != data.queries.size()) {
    validation_failure("RESULT_SET_INCOMPLETE", "Report queries differ from the source");
  }
  long double max_coordinate_error = 0, max_value_error = 0;
  for (std::size_t q = 0; q < queries.size(); ++q) {
    const std::string w = "query " + std::to_string(q);
    const auto& entry = queries[q];
    require_result_keys(entry, {"index", "neighbors", "norm", "value"}, w);
    if (count_value(entry.at("index"), w + " index") != q || !entry.at("neighbors").is_array()) {
      validation_failure("RESULT_SET_INCOMPLETE", w + " differs from the source");
    }
    const P2 x{represent(data.queries[q][0]), represent(data.queries[q][1])};
    const auto expected = natural_neighbor_areas(sites, x);
    Q expected_norm = 0;
    for (const auto& item : expected) expected_norm += item.second;
    std::map<std::size_t, Q> reported;
    for (const auto& neighbor : entry.at("neighbors")) {
      require_result_keys(neighbor, {"site", "coordinate"}, w + " neighbor");
      const auto site = count_value(neighbor.at("site"), w + " neighbor site");
      if (site >= sites.size() || reported.count(site)) validation_failure("REPORT_VALUE_INVALID", w + " neighbor site is invalid");
      reported[site] = reported_rational(neighbor.at("coordinate"), w + " coordinate");
    }
    const Q norm = reported_rational(entry.at("norm"), w + " norm");
    if (!(norm > 0)) validation_failure("COORDINATE_MISMATCH", w + " norm must be positive");
    Q reported_sum = 0;
    for (const auto& item : reported) reported_sum += item.second;
    std::set<std::size_t> all;
    for (const auto& item : expected) all.insert(item.first);
    for (const auto& item : reported) all.insert(item.first);
    std::map<std::size_t, Q> lambda;  // expected normalized coordinates
    for (const auto site : all) {
      const Q e = expected.count(site) ? Q(expected.at(site) / expected_norm) : Q(0);
      const Q r = reported.count(site) ? Q(reported.at(site) / norm) : Q(0);
      lambda[site] = e;
      if (!sibson) {
        if (e != r) validation_failure("COORDINATE_MISMATCH", w + " natural-neighbour coordinate differs");
      } else {
        const long double error = std::fabs(static_cast<long double>(Q(e - r).get_d()));
        max_coordinate_error = std::max(max_coordinate_error, error);
        if (error > 1e-9L) validation_failure("COORDINATE_MISMATCH", w + " natural-neighbour coordinate differs");
      }
    }
    if (!sibson && reported_sum != norm) validation_failure("COORDINATE_MISMATCH", w + " norm is not the coordinate sum");
    const Q value = reported_rational(entry.at("value"), w + " value");
    if (!sibson) {
      Q linear = 0;
      for (const auto& item : lambda) linear += item.second * values[item.first];
      if (linear != value) validation_failure("INTERPOLATION_MISMATCH", w + " linear interpolation differs");
    } else {
      // Sibson's C1 interpolant (Farin's form used by the Interpolation manual):
      // zeta = sum (l_i/r_i)(f_i + g_i.(x - p_i)) / sum(l_i/r_i),
      // value = (term4 * sum l_i f_i + sum(l_i r_i^2) * zeta) / (term4 + sum l_i r_i^2),
      // term4 = sum(l_i r_i) / sum(l_i/r_i).
      long double expected_value;
      if (expected.size() == 1 && sites[expected.begin()->first] == x) {
        expected_value = static_cast<long double>(values[expected.begin()->first].get_d());
      } else {
        long double t1 = 0, t2 = 0, t3 = 0, linear = 0, gradient = 0;
        const long double qx = x[0].get_d(), qy = x[1].get_d();
        for (const auto& item : lambda) {
          if (item.second == 0) continue;
          const long double l = item.second.get_d();
          const long double dx = qx - sites[item.first][0].get_d(), dy = qy - sites[item.first][1].get_d();
          const long double r2 = dx * dx + dy * dy, r = std::sqrt(r2);
          t1 += l / r;
          t2 += l * r2;
          t3 += l * r;
          linear += l * values[item.first].get_d();
          gradient += (l / r) * (values[item.first].get_d() + gradients[item.first][0].get_d() * dx +
                                 gradients[item.first][1].get_d() * dy);
        }
        const long double t4 = t3 / t1;
        expected_value = (t4 * linear + t2 * (gradient / t1)) / (t4 + t2);
      }
      const long double error = std::fabs(expected_value - static_cast<long double>(value.get_d()));
      max_value_error = std::max(max_value_error, error);
      if (error > 1e-9L * static_cast<long double>(scale.get_d())) {
        validation_failure("INTERPOLATION_MISMATCH", w + " Sibson C1 value differs");
      }
    }
  }
  checks["coordinates_match"] = true;
  checks["interpolated_values_match"] = true;
  checks["result_set_complete"] = true;
  return finish_optimization_validation(
      request, "optimization.validate.interpolation",
      validator_report("optimization.interpolate", checks,
                       {{"method", method},
                        {"comparison_policy", sibson ? "exact Voronoi-area coordinates of the binary64 inputs; "
                                                       "coordinates within 1e-9, values within 1e-9*scale"
                                                     : "exact equality of coordinates and values"},
                        {"max_coordinate_error", static_cast<double>(max_coordinate_error)},
                        {"max_value_error", static_cast<double>(max_value_error)}}));
}

// ---- 7.15.03 mesh approximation -------------------------------------------------------------

using V3 = std::array<long double, 3>;
V3 sub(const V3& a, const V3& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
V3 add(const V3& a, const V3& b) { return {a[0] + b[0], a[1] + b[1], a[2] + b[2]}; }
V3 mul(long double s, const V3& a) { return {s * a[0], s * a[1], s * a[2]}; }
long double dot(const V3& a, const V3& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
V3 cross(const V3& a, const V3& b) {
  return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
V3 to_v3(const std::array<double, 3>& p) { return {p[0], p[1], p[2]}; }

// Closest point on triangle (Ericson, Real-Time Collision Detection 5.1.5).
long double point_triangle_squared(const V3& p, const V3& a, const V3& b, const V3& c) {
  const V3 ab = sub(b, a), ac = sub(c, a), ap = sub(p, a);
  const long double d1 = dot(ab, ap), d2 = dot(ac, ap);
  auto sq = [&](const V3& q) { const V3 d = sub(p, q); return dot(d, d); };
  if (d1 <= 0 && d2 <= 0) return sq(a);
  const V3 bp = sub(p, b);
  const long double d3 = dot(ab, bp), d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return sq(b);
  const long double vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) return sq(add(a, mul(d1 / (d1 - d3), ab)));
  const V3 cp = sub(p, c);
  const long double d5 = dot(ab, cp), d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return sq(c);
  const long double vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) return sq(add(a, mul(d2 / (d2 - d6), ac)));
  const long double va = d3 * d6 - d5 * d4;
  if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
    return sq(add(b, mul((d4 - d3) / ((d4 - d3) + (d5 - d6)), sub(c, b))));
  }
  const long double denominator = 1 / (va + vb + vc);
  return sq(add(a, add(mul(vb * denominator, ab), mul(vc * denominator, ac))));
}

Json validate_mesh_approximation(const Request& request) {
  require_inputs(request, 2, "optimization.validate.mesh_approximation");
  require_parameter_names(request, {"max_number_of_proxies", "number_of_iterations", "seeding"});
  const auto seeding = enum_parameter(request, "seeding", {"hierarchical", "incremental"});
  const auto proxies_requested = integer_parameter(request, "max_number_of_proxies", 1, kMaximumProxies);
  const auto iterations = integer_parameter(request, "number_of_iterations", 1, kMaximumIterations);
  const auto report = read_optimization_report(request.inputs[0], "mesh_approximation");
  const auto mesh = read_mesh(request.inputs[1]);
  Json checks = Json::object();
  const auto results = check_report_frame(
      request, report, "optimization.approximate_mesh",
      {{"max_number_of_proxies", proxies_requested}, {"number_of_iterations", iterations}, {"seeding", seeding}},
      checks);
  require_result_keys(results, {"proxy_count", "face_count", "face_proxy_map", "proxies", "l21_error", "anchors",
                                "triangles", "is_manifold", "anchor_max_distance_to_source", "length_unit"},
                      "results");
  const auto unit = request.inputs[1].unit;
  const std::size_t faces = mesh.faces.size();
  const auto k = count_value(results.at("proxy_count"), "proxy_count");
  if (count_value(results.at("face_count"), "face_count") != faces || results.at("length_unit") != unit) {
    validation_failure("RESULT_SET_INCOMPLETE", "Report mesh size or unit differs from the source");
  }
  if (k < 1 || k > proxies_requested) validation_failure("PARTITION_INVALID", "proxy_count exceeds max_number_of_proxies");
  const auto& map = results.at("face_proxy_map");
  if (!map.is_array() || map.size() != faces) validation_failure("PARTITION_INVALID", "face_proxy_map must cover every face");
  std::vector<std::size_t> proxy_of(faces);
  std::vector<std::size_t> used(k, 0);
  for (std::size_t f = 0; f < faces; ++f) {
    proxy_of[f] = count_value(map[f], "face_proxy_map entry");
    if (proxy_of[f] >= k) validation_failure("PARTITION_INVALID", "face_proxy_map names an unknown proxy");
    ++used[proxy_of[f]];
  }
  for (std::size_t p = 0; p < k; ++p) {
    if (used[p] == 0) validation_failure("PARTITION_INVALID", "A proxy has no faces");
  }
  checks["partition_complete"] = true;
  // Each patch must be edge-connected in the source mesh.
  std::map<std::pair<std::size_t, std::size_t>, std::vector<std::size_t>> edge_faces;
  for (std::size_t f = 0; f < faces; ++f) {
    for (int e = 0; e < 3; ++e) {
      auto a = mesh.faces[f][e], b = mesh.faces[f][(e + 1) % 3];
      edge_faces[{std::min(a, b), std::max(a, b)}].push_back(f);
    }
  }
  std::vector<std::vector<std::size_t>> adjacent(faces);
  for (const auto& item : edge_faces) {
    for (auto f : item.second) {
      for (auto g : item.second) {
        if (f != g) adjacent[f].push_back(g);
      }
    }
  }
  std::vector<bool> seen(faces, false);
  std::vector<bool> proxy_started(k, false);
  for (std::size_t f = 0; f < faces; ++f) {
    if (seen[f]) continue;
    if (proxy_started[proxy_of[f]]) validation_failure("PARTITION_INVALID", "A proxy patch is not edge-connected");
    proxy_started[proxy_of[f]] = true;
    std::queue<std::size_t> pending;
    pending.push(f);
    seen[f] = true;
    while (!pending.empty()) {
      const auto g = pending.front();
      pending.pop();
      for (auto h : adjacent[g]) {
        if (!seen[h] && proxy_of[h] == proxy_of[f]) {
          seen[h] = true;
          pending.push(h);
        }
      }
    }
  }
  checks["patches_connected"] = true;
  // L21 proxies: normalized area-weighted unit normals of each patch.
  std::vector<V3> unit_normal(faces);
  std::vector<long double> face_area(faces);
  long double total_area = 0, extent = 1;
  for (const auto& v : mesh.vertices) {
    for (double c : v) extent = std::max(extent, static_cast<long double>(std::fabs(c)));
  }
  for (std::size_t f = 0; f < faces; ++f) {
    const auto a = to_v3(mesh.vertices[mesh.faces[f][0]]), b = to_v3(mesh.vertices[mesh.faces[f][1]]),
               c = to_v3(mesh.vertices[mesh.faces[f][2]]);
    const V3 normal = cross(sub(b, a), sub(c, a));
    const long double length = std::sqrt(dot(normal, normal));
    if (!(length > 0)) validation_failure("DEGENERATE_FACE", "Source mesh has a degenerate face");
    unit_normal[f] = mul(1 / length, normal);
    face_area[f] = length / 2;
    total_area += face_area[f];
  }
  const auto& proxies = results.at("proxies");
  if (!proxies.is_array() || proxies.size() != k) validation_failure("PROXY_MISMATCH", "proxies must list proxy_count normals");
  std::vector<V3> fitted(k, V3{0, 0, 0});
  for (std::size_t f = 0; f < faces; ++f) fitted[proxy_of[f]] = add(fitted[proxy_of[f]], mul(face_area[f], unit_normal[f]));
  std::vector<V3> reported(k);
  long double max_proxy_error = 0;
  for (std::size_t p = 0; p < k; ++p) {
    if (!proxies[p].is_array() || proxies[p].size() != 3) validation_failure("PROXY_MISMATCH", "proxy normals need 3 values");
    for (int i = 0; i < 3; ++i) reported[p][i] = finite_number(proxies[p][i], "proxy normal");
    const long double length = std::sqrt(dot(fitted[p], fitted[p]));
    const V3 expected = length > 0 ? mul(1 / length, fitted[p]) : fitted[p];
    for (int i = 0; i < 3; ++i) max_proxy_error = std::max(max_proxy_error, std::fabs(expected[i] - reported[p][i]));
  }
  if (max_proxy_error > 1e-9L) validation_failure("PROXY_MISMATCH", "A proxy is not the area-weighted normal of its patch");
  checks["proxies_fit_patches"] = true;
  const auto& error = results.at("l21_error");
  require_result_keys(error, {"value", "unit", "squared_length"}, "l21_error");
  if (error.at("unit") != unit + "2" || error.at("squared_length") != true) {
    validation_failure("UNIT_MISMATCH", "l21_error must be an area in squared length units");
  }
  long double expected_error = 0;
  for (std::size_t f = 0; f < faces; ++f) {
    const V3 d = sub(unit_normal[f], reported[proxy_of[f]]);
    expected_error += face_area[f] * dot(d, d);
  }
  if (std::fabs(expected_error - finite_number(error.at("value"), "l21_error")) > 1e-9L * std::max(1.0L, total_area)) {
    validation_failure("ERROR_MISMATCH", "Reported L21 error differs from the recomputed value");
  }
  checks["l21_error_matches"] = true;
  const auto& anchors = results.at("anchors");
  const auto& triangles = results.at("triangles");
  if (!anchors.is_array() || anchors.empty() || !triangles.is_array() || triangles.empty() ||
      !results.at("is_manifold").is_boolean()) {
    validation_failure("OUTPUT_MESH_INVALID", "Approximation needs anchors, triangles and a manifold flag");
  }
  std::vector<V3> anchor_points;
  for (const auto& a : anchors) {
    if (!a.is_array() || a.size() != 3) validation_failure("OUTPUT_MESH_INVALID", "Anchors need 3 coordinates");
    anchor_points.push_back({finite_number(a[0], "anchor"), finite_number(a[1], "anchor"), finite_number(a[2], "anchor")});
  }
  std::map<std::pair<std::size_t, std::size_t>, int> edge_use;
  for (const auto& t : triangles) {
    if (!t.is_array() || t.size() != 3) validation_failure("OUTPUT_MESH_INVALID", "Triangles need 3 indices");
    std::array<std::size_t, 3> index{};
    for (int i = 0; i < 3; ++i) {
      index[i] = count_value(t[i], "triangle index");
      if (index[i] >= anchor_points.size()) validation_failure("OUTPUT_MESH_INVALID", "Triangle index out of range");
    }
    if (index[0] == index[1] || index[1] == index[2] || index[0] == index[2]) {
      validation_failure("OUTPUT_MESH_INVALID", "Output triangle repeats an anchor");
    }
    for (int e = 0; e < 3; ++e) {
      ++edge_use[{std::min(index[e], index[(e + 1) % 3]), std::max(index[e], index[(e + 1) % 3])}];
    }
  }
  if (results.at("is_manifold") == true) {
    for (const auto& item : edge_use) {
      if (item.second > 2) validation_failure("OUTPUT_MESH_INVALID", "A manifold output has an edge in 3+ triangles");
    }
  }
  checks["output_mesh_valid"] = true;
  const auto& deviation = results.at("anchor_max_distance_to_source");
  require_result_keys(deviation, {"value", "unit"}, "anchor_max_distance_to_source");
  if (deviation.at("unit") != unit) validation_failure("UNIT_MISMATCH", "Deviation must use the source length unit");
  long double expected_deviation = 0;
  for (const auto& p : anchor_points) {
    long double best = -1;
    for (const auto& f : mesh.faces) {
      const long double d = point_triangle_squared(p, to_v3(mesh.vertices[f[0]]), to_v3(mesh.vertices[f[1]]),
                                                   to_v3(mesh.vertices[f[2]]));
      if (best < 0 || d < best) best = d;
    }
    expected_deviation = std::max(expected_deviation, std::sqrt(best));
  }
  if (std::fabs(expected_deviation - finite_number(deviation.at("value"), "deviation")) > 1e-9L * extent) {
    validation_failure("DEVIATION_MISMATCH", "Reported anchor deviation differs from the brute-force value");
  }
  checks["deviation_matches"] = true;
  checks["result_set_complete"] = true;
  return finish_optimization_validation(
      request, "optimization.validate.mesh_approximation",
      validator_report("optimization.approximate_mesh", checks,
                       {{"proxy_count", k},
                        {"max_proxy_normal_error", static_cast<double>(max_proxy_error)},
                        {"recomputed_l21_error", static_cast<double>(expected_error)},
                        {"recomputed_anchor_deviation", static_cast<double>(expected_deviation)},
                        {"comparison_policy", "long double recomputation; normals within 1e-9, L21 error within "
                                              "1e-9*max(1, area), deviation within 1e-9*max(1, |coordinate|)"}}));
}

// ---- 7.15.04 interval p-center -----------------------------------------------------------------

std::size_t greedy_intervals(const std::vector<Q>& sorted, const Q& d) {
  std::size_t count = 0;
  std::size_t i = 0;
  while (i < sorted.size()) {
    ++count;
    const Q limit = sorted[i] + d;
    while (i < sorted.size() && sorted[i] <= limit) ++i;
  }
  return count;
}

Json validate_matrix_search(const Request& request) {
  require_inputs(request, 2, "optimization.validate.matrix_search");
  require_parameter_names(request, {"centers"});
  const auto centers = integer_parameter(request, "centers", 1, kMaximumLinePoints);
  const auto report = read_optimization_report(request.inputs[0], "interval_p_center");
  const auto points = read_point_set1(request.inputs[1]);
  Json checks = Json::object();
  const auto results = check_report_frame(request, report, "optimization.matrix_search", {{"centers", centers}}, checks);
  require_result_keys(results, {"point_count", "matrix_dimension", "optimal_diameter", "optimal_radius", "centers",
                                "assignment", "length_unit"},
                      "results");
  if (count_value(results.at("point_count"), "point_count") != points.size() ||
      count_value(results.at("matrix_dimension"), "matrix_dimension") != points.size() ||
      results.at("length_unit") != request.inputs[1].unit) {
    validation_failure("RESULT_SET_INCOMPLETE", "Report point set differs from the source");
  }
  if (centers >= points.size()) validation_failure("RESULT_SET_INCOMPLETE", "centers must be smaller than the point count");
  const Q diameter = reported_rational(results.at("optimal_diameter"), "optimal_diameter");
  const Q radius = reported_rational(results.at("optimal_radius"), "optimal_radius");
  if (diameter < 0 || radius * 2 != diameter) validation_failure("OPTIMUM_MISMATCH", "Radius must be half the diameter");
  std::vector<Q> sorted(points);
  std::sort(sorted.begin(), sorted.end());
  // Exhaustive candidate scan: d* must be a pairwise difference, feasible, and every
  // smaller candidate must be infeasible (feasibility is monotone in d).
  bool candidate = false;
  bool has_smaller = false;
  Q largest_smaller;
  for (std::size_t i = 0; i < sorted.size(); ++i) {
    for (std::size_t j = i; j < sorted.size(); ++j) {
      const Q difference = sorted[j] - sorted[i];
      if (difference == diameter) candidate = true;
      if (difference < diameter && (!has_smaller || difference > largest_smaller)) {
        largest_smaller = difference;
        has_smaller = true;
      }
    }
  }
  if (!candidate) validation_failure("OPTIMUM_MISMATCH", "Optimal diameter is not a pairwise point difference");
  checks["diameter_is_candidate"] = true;
  if (greedy_intervals(sorted, diameter) > centers) validation_failure("OPTIMUM_MISMATCH", "Optimal diameter is infeasible");
  checks["diameter_feasible"] = true;
  if (has_smaller && greedy_intervals(sorted, largest_smaller) <= centers) {
    validation_failure("OPTIMUM_MISMATCH", "A smaller candidate diameter is feasible");
  }
  checks["smaller_candidate_infeasible"] = true;
  const auto& center_values = results.at("centers");
  const auto& assignment = results.at("assignment");
  if (!center_values.is_array() || center_values.empty() || center_values.size() > centers || !assignment.is_array() ||
      assignment.size() != points.size()) {
    validation_failure("COVER_INVALID", "Centers or assignment have the wrong size");
  }
  std::vector<Q> c;
  for (const auto& value : center_values) c.push_back(reported_rational(value, "center"));
  for (std::size_t i = 0; i < points.size(); ++i) {
    const auto k = count_value(assignment[i], "assignment");
    if (k >= c.size() || abs(points[i] - c[k]) > radius) {
      validation_failure("COVER_INVALID", "Point " + std::to_string(i) + " is not within the radius of its center");
    }
  }
  checks["centers_cover_points"] = true;
  checks["result_set_complete"] = true;
  return finish_optimization_validation(
      request, "optimization.validate.matrix_search",
      validator_report("optimization.matrix_search", checks,
                       {{"candidate_pairs", sorted.size() * (sorted.size() + 1) / 2},
                        {"largest_infeasible_candidate", has_smaller ? Json(q_text(largest_smaller)) : Json(nullptr)},
                        {"proof", "exhaustive exact candidate scan with an independent greedy feasibility test"}}));
}

Json validator_info(const std::vector<std::string>& checks, const std::string& independence) {
  return Json{{"checks", checks}, {"input_slots", Json::array({"candidate", "source"})},
              {"output_slot", "validation"}, {"independence", independence}};
}

}  // namespace

std::vector<OperationDefinition> validator_operations() {
  auto qp = optimization_definition(
      "optimization.validate.quadratic_program", {"OptimizationReport", "QuadraticProgram"}, "ValidationReport",
      "validator", validate_quadratic_program, {"QP_solver"}, "exact:GMP",
      validator_info({"parameters_match", "source_matches", "objective_convex", "primal_feasible",
                      "certificate_valid", "objective_matches", "result_set_complete"},
                     "GMP rationals; certificate lemmas; no CGAL header"));
  auto interpolation = optimization_definition(
      "optimization.validate.interpolation", {"OptimizationReport", "InterpolationData2"}, "ValidationReport",
      "validator", validate_interpolation, {"Interpolation", "Triangulation_2"}, "exact:GMP",
      validator_info({"parameters_match", "source_matches", "kernel_matches", "coordinates_match",
                      "interpolated_values_match", "result_set_complete"},
                     "exact Voronoi-area clipping in GMP rationals; no CGAL header"));
  auto approximation = optimization_definition(
      "optimization.validate.mesh_approximation", {"OptimizationReport", "TriangleSurfaceMesh"},
      "ValidationReport", "validator", validate_mesh_approximation, {"Surface_mesh_approximation"},
      "long_double_recomputation",
      validator_info({"parameters_match", "source_matches", "partition_complete", "patches_connected",
                      "proxies_fit_patches", "l21_error_matches", "output_mesh_valid", "deviation_matches",
                      "result_set_complete"},
                     "long double recomputation and brute-force distances; no CGAL header"));
  auto matrix = optimization_definition(
      "optimization.validate.matrix_search", {"OptimizationReport", "PointSet1"}, "ValidationReport", "validator",
      validate_matrix_search, {"Matrix_search"}, "exact:GMP",
      validator_info({"parameters_match", "source_matches", "diameter_is_candidate", "diameter_feasible",
                      "smaller_candidate_infeasible", "centers_cover_points", "result_set_complete"},
                     "GMP rationals; exhaustive candidate scan; no CGAL header"));
  return {qp, interpolation, approximation, matrix};
}

}  // namespace cgal_master::optimization_ops
