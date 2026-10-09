// Optimization / numerical-geometry family (7.15): CGAL QP_solver
// (solve_linear_program / solve_quadratic_program on Quadratic_program),
// Interpolation (natural_neighbor_coordinates_2, linear_interpolation,
// sibson_c1_interpolation), Surface_mesh_approximation
// (approximate_triangle_mesh) and Matrix_search (sorted_matrix_search over a
// Cartesian_matrix). Every report is checked by an independent validator in
// optimization_validators.cpp that includes no CGAL header.

#include "optimization_common.h"

#include <CGAL/AABB_face_graph_triangle_primitive.h>
#include <CGAL/AABB_traits_3.h>
#include <CGAL/AABB_tree.h>
#include <CGAL/Cartesian_matrix.h>
#include <CGAL/Delaunay_triangulation_2.h>
#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Gmpq.h>
#include <CGAL/Interpolation_gradient_fitting_traits_2.h>
#include <CGAL/QP_functions.h>
#include <CGAL/QP_models.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/Surface_mesh_approximation/approximate_triangle_mesh.h>
#include <CGAL/interpolation_functions.h>
#include <CGAL/natural_neighbor_coordinates_2.h>
#include <CGAL/sorted_matrix_search.h>

#include <algorithm>
#include <cmath>
#include <map>
#include <sstream>

namespace cgal_master::optimization_ops {
namespace {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using Epeck = CGAL::Exact_predicates_exact_constructions_kernel;
using ET = CGAL::Gmpq;

constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";
constexpr const char* kEpeckName = "CGAL::Exact_predicates_exact_constructions_kernel";

ET to_et(const Q& value) { return ET(value.get_mpq_t()); }
Q from_et(const ET& value) { return Q(value.mpq()); }
Q from_quotient(const CGAL::Quotient<ET>& value) {
  return from_et(value.numerator()) / from_et(value.denominator());
}

std::string epeck_text(const Epeck::FT& value) {
  std::ostringstream stream;
  stream << CGAL::exact(value);
  Q result;
  if (mpq_set_str(result.get_mpq_t(), stream.str().c_str(), 10) != 0) {
    throw WorkerError("INTERNAL_ERROR", "EXACT_FORMAT", "Exact value could not be formatted");
  }
  return q_text(result);
}

std::string double_text(double value) { return q_text(exact_of_double(value)); }

// Exact principal-minor test (Sylvester's criterion for semidefiniteness).
Q determinant(std::vector<std::vector<Q>> m) {
  const std::size_t n = m.size();
  Q result = 1;
  for (std::size_t k = 0; k < n; ++k) {
    std::size_t pivot = k;
    while (pivot < n && m[pivot][k] == 0) ++pivot;
    if (pivot == n) return 0;
    if (pivot != k) {
      std::swap(m[pivot], m[k]);
      result = -result;
    }
    result *= m[k][k];
    for (std::size_t i = k + 1; i < n; ++i) {
      const Q factor = m[i][k] / m[k][k];
      for (std::size_t j = k; j < n; ++j) m[i][j] -= factor * m[k][j];
    }
  }
  return result;
}

bool positive_semidefinite(const std::vector<std::vector<Q>>& d) {
  const std::size_t n = d.size();
  for (std::size_t mask = 1; mask < (std::size_t(1) << n); ++mask) {
    std::vector<std::size_t> index;
    for (std::size_t i = 0; i < n; ++i) {
      if (mask & (std::size_t(1) << i)) index.push_back(i);
    }
    std::vector<std::vector<Q>> minor(index.size(), std::vector<Q>(index.size()));
    for (std::size_t a = 0; a < index.size(); ++a) {
      for (std::size_t b = 0; b < index.size(); ++b) minor[a][b] = d[index[a]][index[b]];
    }
    if (determinant(std::move(minor)) < 0) return false;
  }
  return true;
}

// ---- 7.15.01 QP_solver ----------------------------------------------------------

Json solve_program(const Request& request) {
  require_inputs(request, 1, "optimization.quadratic_program");
  require_parameter_names(request, {"solver"});
  const auto solver = enum_parameter(request, "solver", {"linear", "quadratic"});
  const auto data = read_quadratic_program(request.inputs[0]);
  if (solver == "linear" && !data.d_is_zero) {
    precondition("NONZERO_QUADRATIC_TERM", "solver=linear requires a zero objective matrix d");
  }
  if (solver == "quadratic" && !positive_semidefinite(data.d)) {
    precondition("NOT_POSITIVE_SEMIDEFINITE", "QP_solver requires a positive semidefinite objective matrix d");
  }
  const int n = static_cast<int>(data.variables);
  const int m = static_cast<int>(data.constraints.size());
  CGAL::Quadratic_program<ET> program(CGAL::SMALLER, true, ET(0), false, ET(0));
  for (int i = 0; i < m; ++i) {
    const auto& row = data.constraints[i];
    for (int j = 0; j < n; ++j) program.set_a(j, i, to_et(row.coefficients[j]));
    program.set_b(i, to_et(row.rhs));
    program.set_r(i, row.relation == Relation::kLess
                         ? CGAL::SMALLER
                         : (row.relation == Relation::kEqual ? CGAL::EQUAL : CGAL::LARGER));
  }
  for (int j = 0; j < n; ++j) {
    program.set_l(j, data.lower[j].finite, to_et(data.lower[j].value));
    program.set_u(j, data.upper[j].finite, to_et(data.upper[j].value));
    program.set_c(j, to_et(data.c[j]));
    for (int k = 0; k <= j; ++k) {
      // set_d(i, j, v) stores the entries 2D_ij and 2D_ji (lower triangle only).
      if (data.d[j][k] != 0) program.set_d(j, k, to_et(2 * data.d[j][k]));
    }
  }
  program.set_c0(to_et(data.c0));
  const auto solution = solver == "linear" ? CGAL::solve_linear_program(program, ET())
                                           : CGAL::solve_quadratic_program(program, ET());
  if (!solution.is_valid()) {
    throw WorkerError("INTERNAL_ERROR", "QP_SOLUTION_INVALID", "QP_solver reported an invalid solution");
  }
  Json results{{"variables", n}, {"constraints", m}};
  Json values = Json::array();
  Json certificate;
  std::string status;
  if (solution.is_optimal() || solution.is_unbounded()) {
    for (auto it = solution.variable_values_begin(); it != solution.variable_values_end(); ++it) {
      values.push_back(q_text(from_quotient(*it)));
    }
  }
  if (solution.is_optimal()) {
    status = "optimal";
    Json lambda = Json::array();
    for (auto it = solution.optimality_certificate_begin(); it != solution.optimality_certificate_end(); ++it) {
      lambda.push_back(q_text(from_quotient(*it)));
    }
    certificate = Json{{"kind", "optimality"}, {"values", lambda}};
    results["objective_value"] = q_text(from_quotient(solution.objective_value()));
  } else if (solution.is_infeasible()) {
    status = "infeasible";
    Json lambda = Json::array();
    for (auto it = solution.infeasibility_certificate_begin(); it != solution.infeasibility_certificate_end(); ++it) {
      lambda.push_back(q_text(from_et(*it)));
    }
    certificate = Json{{"kind", "infeasibility"}, {"values", lambda}};
    results["objective_value"] = nullptr;
  } else {
    status = "unbounded";
    Json direction = Json::array();
    auto mutable_solution = solution;
    for (auto it = mutable_solution.unboundedness_certificate_begin();
         it != mutable_solution.unboundedness_certificate_end(); ++it) {
      direction.push_back(q_text(from_et(*it)));
    }
    certificate = Json{{"kind", "unboundedness"}, {"values", direction}};
    results["objective_value"] = nullptr;
  }
  results["status"] = status;
  results["variable_values"] = status == "infeasible" ? Json(nullptr) : values;
  results["certificate"] = certificate;
  const auto algorithm = solver == "linear" ? "CGAL::solve_linear_program" : "CGAL::solve_quadratic_program";
  auto output = write_report(request, report_frame(request, "quadratic_program", {{"solver", solver}}, results));
  Json metrics{{"solver", solver},
               {"status", status},
               {"variables", n},
               {"constraints", m},
               {"objective_value", results["objective_value"]},
               {"exact_number_type", "CGAL::Gmpq"},
               {"algorithm", std::string(algorithm) + " on CGAL::Quadratic_program<CGAL::Gmpq>"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.15.02 Interpolation --------------------------------------------------------

template <class K>
typename K::FT kernel_number(const Q& value, bool exact) {
  if (exact) return typename K::FT(mpz_get_d(value.get_num_mpz_t())) / typename K::FT(mpz_get_d(value.get_den_mpz_t()));
  return typename K::FT(nearest_double(value));
}

template <class K, bool Sibson, class Text>
Json interpolate_queries(const InterpolationData& data, bool exact, Text text) {
  using Point = typename K::Point_2;
  using FT = typename K::FT;
  using Triangulation = CGAL::Delaunay_triangulation_2<K>;
  using Traits = CGAL::Interpolation_gradient_fitting_traits_2<K>;
  std::map<Point, FT, typename K::Less_xy_2> values;
  std::map<Point, typename K::Vector_2, typename K::Less_xy_2> gradients;
  std::map<Point, std::size_t, typename K::Less_xy_2> index;
  Triangulation triangulation;
  for (std::size_t i = 0; i < data.sites.size(); ++i) {
    const auto& site = data.sites[i];
    const Point p(kernel_number<K>(site.point[0], exact), kernel_number<K>(site.point[1], exact));
    if (!index.emplace(p, i).second) {
      precondition("DUPLICATE_SITE", "Two sites coincide in the selected kernel's input representation");
    }
    values.emplace(p, kernel_number<K>(site.value, exact));
    gradients.emplace(p, typename K::Vector_2(kernel_number<K>(site.gradient[0], exact),
                                              kernel_number<K>(site.gradient[1], exact)));
    triangulation.insert(p);
  }
  if (triangulation.dimension() != 2) precondition("DEGENERATE_SITES", "Interpolation sites are collinear");
  Json queries = Json::array();
  for (std::size_t q = 0; q < data.queries.size(); ++q) {
    const Point p(kernel_number<K>(data.queries[q][0], exact), kernel_number<K>(data.queries[q][1], exact));
    std::vector<std::pair<Point, FT>> coordinates;
    const auto result = CGAL::natural_neighbor_coordinates_2(triangulation, p, std::back_inserter(coordinates));
    if (!result.third || coordinates.empty()) {
      precondition("QUERY_OUTSIDE_HULL", "Query " + std::to_string(q) + " is not inside the convex hull of the sites");
    }
    const FT norm = result.second;
    Json neighbors = Json::array();
    std::vector<std::pair<std::size_t, Json>> ordered;
    for (const auto& item : coordinates) {
      ordered.emplace_back(index.at(item.first), Json{{"site", index.at(item.first)}, {"coordinate", text(item.second)}});
    }
    std::sort(ordered.begin(), ordered.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
    for (auto& item : ordered) neighbors.push_back(std::move(item.second));
    FT value;
    if constexpr (Sibson) {
      const auto c1 = CGAL::sibson_c1_interpolation(coordinates.begin(), coordinates.end(), norm, p,
                                                    CGAL::Data_access<decltype(values)>(values),
                                                    CGAL::Data_access<decltype(gradients)>(gradients), Traits());
      if (!c1.second) precondition("GRADIENT_MISSING", "Sibson C1 interpolation lacks a gradient");
      value = c1.first;
    } else {
      value = CGAL::linear_interpolation(coordinates.begin(), coordinates.end(), norm,
                                         CGAL::Data_access<decltype(values)>(values));
    }
    queries.push_back(Json{{"index", q}, {"neighbors", neighbors}, {"norm", text(norm)}, {"value", text(value)}});
  }
  return queries;
}

Json interpolate(const Request& request) {
  require_inputs(request, 1, "optimization.interpolate");
  require_parameter_names(request, {"method"});
  const auto method = enum_parameter(request, "method", {"linear", "sibson_c1"});
  const auto data = read_interpolation_data(request.inputs[0]);
  const bool sibson = method == "sibson_c1";
  Json queries = sibson ? interpolate_queries<Epick, true>(data, false, [](double v) { return double_text(v); })
                        : interpolate_queries<Epeck, false>(data, true,
                                                     [](const Epeck::FT& v) { return epeck_text(v); });
  const std::string kernel = sibson ? kEpickName : kEpeckName;
  Json results{{"kernel", kernel},
               {"input_representation", sibson ? "binary64_round_to_nearest" : "exact_rational"},
               {"site_count", data.sites.size()},
               {"queries", queries}};
  auto output = write_report(request, report_frame(request, "natural_neighbor_interpolation",
                                                   {{"method", method}}, results));
  const auto algorithm = sibson ? "CGAL::natural_neighbor_coordinates_2 + CGAL::sibson_c1_interpolation"
                                : "CGAL::natural_neighbor_coordinates_2 + CGAL::linear_interpolation";
  Json metrics{{"method", method}, {"kernel", kernel}, {"site_count", data.sites.size()},
               {"query_count", data.queries.size()}, {"algorithm", algorithm}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.15.03 Surface_mesh_approximation -----------------------------------------------

Json approximate_mesh(const Request& request) {
  require_inputs(request, 1, "optimization.approximate_mesh");
  require_parameter_names(request, {"max_number_of_proxies", "number_of_iterations", "seeding"});
  const auto seeding = enum_parameter(request, "seeding", {"hierarchical", "incremental"});
  const auto proxies_requested = integer_parameter(request, "max_number_of_proxies", 1, kMaximumProxies);
  const auto iterations = integer_parameter(request, "number_of_iterations", 1, kMaximumIterations);
  const auto data = read_mesh(request.inputs[0]);
  if (proxies_requested > data.faces.size()) {
    precondition("TOO_MANY_PROXIES", "max_number_of_proxies exceeds the number of faces");
  }
  using Point = Epick::Point_3;
  using Mesh = CGAL::Surface_mesh<Point>;
  Mesh mesh;
  std::vector<Mesh::Vertex_index> vertices;
  for (const auto& v : data.vertices) vertices.push_back(mesh.add_vertex(Point(v[0], v[1], v[2])));
  for (const auto& f : data.faces) {
    if (mesh.add_face(vertices[f[0]], vertices[f[1]], vertices[f[2]]) == Mesh::null_face()) {
      precondition("NON_MANIFOLD_INPUT", "Mesh approximation needs a combinatorially manifold triangle mesh");
    }
  }
  for (const auto f : mesh.faces()) {
    const auto h = mesh.halfedge(f);
    if (CGAL::collinear(mesh.point(mesh.source(h)), mesh.point(mesh.target(h)),
                        mesh.point(mesh.target(mesh.next(h))))) {
      precondition("DEGENERATE_FACE", "Mesh approximation needs non-degenerate triangles");
    }
  }
  auto face_proxy = mesh.add_property_map<Mesh::Face_index, std::size_t>("f:proxy", 0).first;
  std::vector<Epick::Vector_3> proxies;
  std::vector<Point> anchors;
  std::vector<std::array<std::size_t, 3>> triangles;
  namespace VSA = CGAL::Surface_mesh_approximation;
  const bool manifold = VSA::approximate_triangle_mesh(
      mesh, CGAL::parameters::seeding_method(seeding == "incremental" ? VSA::INCREMENTAL : VSA::HIERARCHICAL)
                .max_number_of_proxies(proxies_requested)
                .number_of_iterations(iterations)
                .face_proxy_map(face_proxy)
                .proxies(std::back_inserter(proxies))
                .anchors(std::back_inserter(anchors))
                .triangles(std::back_inserter(triangles)));
  Json face_proxy_map = Json::array();
  for (const auto f : mesh.faces()) face_proxy_map.push_back(face_proxy[f]);
  Json proxy_json = Json::array();
  for (const auto& n : proxies) proxy_json.push_back(Json::array({n.x(), n.y(), n.z()}));
  // L21 error of the returned partition and proxies: sum_f area_f * |n_f - n_proxy|^2.
  double error = 0.0;
  for (const auto f : mesh.faces()) {
    const auto h = mesh.halfedge(f);
    const auto a = mesh.point(mesh.source(h)), b = mesh.point(mesh.target(h)),
               c = mesh.point(mesh.target(mesh.next(h)));
    const auto normal = CGAL::cross_product(b - a, c - a);
    const double length = std::sqrt(normal.squared_length());
    const auto unit = normal / length;
    const auto difference = unit - proxies.at(face_proxy[f]);
    error += 0.5 * length * difference.squared_length();
  }
  using Primitive = CGAL::AABB_face_graph_triangle_primitive<Mesh>;
  using Tree = CGAL::AABB_tree<CGAL::AABB_traits_3<Epick, Primitive>>;
  Tree tree(faces(mesh).first, faces(mesh).second, mesh);
  double deviation = 0.0;
  Json anchor_json = Json::array();
  for (const auto& p : anchors) {
    deviation = std::max(deviation, std::sqrt(tree.squared_distance(p)));
    anchor_json.push_back(Json::array({p.x(), p.y(), p.z()}));
  }
  Json triangle_json = Json::array();
  for (const auto& t : triangles) triangle_json.push_back(Json::array({t[0], t[1], t[2]}));
  const auto unit = request.inputs[0].unit;
  Json results{{"proxy_count", proxies.size()},
               {"face_count", data.faces.size()},
               {"face_proxy_map", face_proxy_map},
               {"proxies", proxy_json},
               {"l21_error", {{"value", error}, {"unit", unit + "2"}, {"squared_length", true}}},
               {"anchors", anchor_json},
               {"triangles", triangle_json},
               {"is_manifold", manifold},
               {"anchor_max_distance_to_source", {{"value", deviation}, {"unit", unit}}},
               {"length_unit", unit}};
  auto output = write_report(request, report_frame(request, "mesh_approximation",
                                                   {{"max_number_of_proxies", proxies_requested},
                                                    {"number_of_iterations", iterations},
                                                    {"seeding", seeding}},
                                                   results));
  Json metrics{{"proxy_count", proxies.size()},
               {"anchor_count", anchors.size()},
               {"triangle_count", triangles.size()},
               {"is_manifold", manifold},
               {"l21_error", error},
               {"kernel", kEpickName},
               {"algorithm", "CGAL::Surface_mesh_approximation::approximate_triangle_mesh (L21 metric, " + seeding + " seeding)"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.15.04 Matrix_search ----------------------------------------------------------------

// Greedy left-to-right cover of sorted points by intervals of length d.
std::size_t intervals_needed(const std::vector<ET>& sorted, const ET& d) {
  std::size_t count = 1;
  ET start = sorted.front();
  for (const auto& x : sorted) {
    if (x > start + d) {
      ++count;
      start = x;
    }
  }
  return count;
}

Json interval_p_center(const Request& request) {
  require_inputs(request, 1, "optimization.matrix_search");
  require_parameter_names(request, {"centers"});
  const auto points = read_point_set1(request.inputs[0]);
  const auto centers = integer_parameter(request, "centers", 1, kMaximumLinePoints);
  if (centers >= points.size()) {
    precondition("TRIVIAL_CENTER_COUNT", "centers must be smaller than the number of points");
  }
  std::vector<ET> sorted;
  for (const auto& p : points) sorted.push_back(to_et(p));
  std::sort(sorted.begin(), sorted.end());
  // Candidate diameters x_j - x_i form the sorted Cartesian matrix
  // M(i, j) = row_i + column_j with row_i = -x_(n-1-i) and column_j = x_j.
  std::vector<ET> rows, columns(sorted);
  for (auto it = sorted.rbegin(); it != sorted.rend(); ++it) rows.push_back(-*it);
  using Matrix = CGAL::Cartesian_matrix<std::plus<ET>, std::vector<ET>::const_iterator,
                                        std::vector<ET>::const_iterator>;
  const Matrix matrix(rows.cbegin(), rows.cend(), columns.cbegin(), columns.cend());
  const ET diameter = CGAL::sorted_matrix_search(
      &matrix, &matrix + 1,
      CGAL::sorted_matrix_search_traits_adaptor(
          [&](const ET& d) { return d >= ET(0) && intervals_needed(sorted, d) <= centers; }, matrix));
  // Centers: greedy interval midpoints at the optimal diameter.
  Json center_json = Json::array();
  std::vector<ET> starts;
  for (const auto& x : sorted) {
    if (starts.empty() || x > starts.back() + diameter) starts.push_back(x);
  }
  for (const auto& s : starts) center_json.push_back(q_text(from_et(s + diameter / ET(2))));
  Json assignment = Json::array();
  for (const auto& p : points) {
    const ET x = to_et(p);
    std::size_t k = 0;
    while (k + 1 < starts.size() && starts[k + 1] <= x) ++k;
    assignment.push_back(k);
  }
  const auto unit = request.inputs[0].unit;
  Json results{{"point_count", points.size()},
               {"matrix_dimension", sorted.size()},
               {"optimal_diameter", q_text(from_et(diameter))},
               {"optimal_radius", q_text(from_et(diameter / ET(2)))},
               {"centers", center_json},
               {"assignment", assignment},
               {"length_unit", unit}};
  auto output = write_report(request, report_frame(request, "interval_p_center", {{"centers", centers}}, results));
  Json metrics{{"point_count", points.size()},
               {"centers_requested", centers},
               {"centers_used", starts.size()},
               {"optimal_radius", results["optimal_radius"]},
               {"matrix_dimension", sorted.size()},
               {"algorithm", "CGAL::sorted_matrix_search over CGAL::Cartesian_matrix<std::plus<CGAL::Gmpq>>"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json info(const std::string& validator, const std::vector<std::string>& parameters, Json extra) {
  Json bindings = Json::object();
  for (const auto& name : parameters) bindings[name] = name;
  Json result{{"input_format", "json"},
              {"output_format", "json"},
              {"validators", Json::array({validator})},
              {"validator_parameter_bindings", {{validator, bindings}}}};
  for (auto& item : extra.items()) result[item.key()] = item.value();
  return result;
}

}  // namespace

std::vector<OperationDefinition> transform_operations() {
  auto qp = optimization_definition(
      "optimization.quadratic_program", {"QuadraticProgram"}, "OptimizationReport", "analysis", solve_program,
      {"QP_solver"}, "exact:CGAL::Gmpq",
      info("optimization.validate.quadratic_program", {"solver"}, {{"maximum_variables", kMaximumVariables},
                                                        {"maximum_constraints", kMaximumConstraints}}));
  auto interpolation = optimization_definition(
      "optimization.interpolate", {"InterpolationData2"}, "OptimizationReport", "analysis", interpolate,
      {"Interpolation", "Triangulation_2"}, "selected_by_parameter:method",
      info("optimization.validate.interpolation", {"method"},
           {{"kernels", {{"linear", kEpeckName}, {"sibson_c1", kEpickName}}},
            {"maximum_sites", kMaximumSites},
            {"maximum_queries", kMaximumInterpolationQueries}}));
  auto approximation = optimization_definition(
      "optimization.approximate_mesh", {"TriangleSurfaceMesh"}, "OptimizationReport", "analysis",
      approximate_mesh, {"Surface_mesh_approximation", "AABB_tree"}, kEpickName,
      info("optimization.validate.mesh_approximation",
           {"max_number_of_proxies", "number_of_iterations", "seeding"}, {{"input_format", "off"},
                                                         {"maximum_faces", kMaximumApproximationFaces},
                                                         {"maximum_proxies", kMaximumProxies}}));
  auto matrix = optimization_definition(
      "optimization.matrix_search", {"PointSet1"}, "OptimizationReport", "analysis", interval_p_center,
      {"Matrix_search"}, "exact:CGAL::Gmpq",
      info("optimization.validate.matrix_search", {"centers"}, {{"maximum_points", kMaximumLinePoints}}));
  return {qp, interpolation, approximation, matrix};
}

}  // namespace cgal_master::optimization_ops
