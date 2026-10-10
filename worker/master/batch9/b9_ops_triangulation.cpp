// Producers wrapping CGAL 6.2.1 Periodic_2_Delaunay_triangulation_2 (a Periodic_2_triangulation_2),
// Periodic_3_Delaunay_triangulation_3 and Delaunay_triangulation_on_sphere_2 (7.11.04). Results are checked by
// the CGAL-free validators in b9_validators_triangulation.cpp.

#include "b9_common.h"

#include <CGAL/Delaunay_triangulation_on_sphere_2.h>
#include <CGAL/Delaunay_triangulation_on_sphere_traits_2.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Periodic_2_Delaunay_triangulation_2.h>
#include <CGAL/Periodic_2_Delaunay_triangulation_traits_2.h>
#include <CGAL/Periodic_3_Delaunay_triangulation_3.h>
#include <CGAL/Periodic_3_Delaunay_triangulation_traits_3.h>

#include <algorithm>
#include <array>
#include <map>
#include <set>

namespace cgal_master::batch9 {
namespace {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";
using batch2::geometry_frame;
using batch2::pinfo;
using query_ops::precondition;
using query_ops::read_points2;
using query_ops::read_points3;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::write_report;

template <typename Array>
void reject_duplicates(const std::vector<Array>& points) {
  std::set<Array> seen;
  for (const auto& p : points) {
    if (!seen.insert(p).second) precondition("DUPLICATE_POINT", "Input points must be pairwise distinct");
  }
}

template <typename Array>
void require_in_domain(const std::vector<Array>& points, const std::vector<double>& minimum, double period,
                       std::size_t dimension, std::size_t maximum_points) {
  if (points.size() > maximum_points) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_COUNT",
                      "At most " + std::to_string(maximum_points) + " points are supported");
  }
  if (points.empty()) precondition("EMPTY_POINT_SET", "At least one point is required");
  for (std::size_t k = 0; k < dimension; ++k) {
    if ((minimum[k] + period) - minimum[k] != period) {
      throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                        "domain_min + period must be exactly representable (exact periodic domain)");
    }
  }
  for (const auto& p : points) {
    for (std::size_t k = 0; k < dimension; ++k) {
      if (p[k] < minimum[k] || p[k] >= minimum[k] + period) {
        precondition("POINT_OUTSIDE_DOMAIN", "Every point must lie in the half-open domain [min, min + period)");
      }
    }
  }
}

Json offset_vertex(std::size_t index, std::initializer_list<int> offset) {
  Json row = Json::array({index});
  for (const int o : offset) row.push_back(o);
  return row;
}

// ---- Periodic_2_Delaunay_triangulation_2 ------------------------------------------------------------
Json periodic_2(const Request& request) {
  require_inputs(request, 1, "triangulation.periodic_delaunay_2");
  require_parameter_names(request, {"domain_min", "period"});
  const auto minimum = domain_min_parameter(request.parameters, 2);
  const double period = positive_length(request.parameters, "period", request.inputs[0].unit);
  const auto points = read_points2(request.inputs[0]);
  require_in_domain(points, minimum, period, 2, kMaximumPeriodicPoints);
  reject_duplicates(points);
  using Gt = CGAL::Periodic_2_Delaunay_triangulation_traits_2<Epick>;
  using P2 = CGAL::Periodic_2_Delaunay_triangulation_2<Gt>;
  P2 triangulation(Gt::Iso_rectangle_2(minimum[0], minimum[1], minimum[0] + period, minimum[1] + period));
  for (const auto& p : points) triangulation.insert(Epick::Point_2(p[0], p[1]));
  if (!triangulation.is_triangulation_in_1_sheet()) {
    precondition("NOT_ONE_SHEETED", "The point set is too sparse for a 1-sheeted periodic triangulation");
  }
  std::map<V2, std::size_t> index;
  for (std::size_t i = 0; i < points.size(); ++i) index[points[i]] = i;
  std::vector<std::array<std::array<long long, 3>, 3>> triangles;
  for (auto it = triangulation.periodic_triangles_begin(P2::STORED);
       it != triangulation.periodic_triangles_end(P2::STORED); ++it) {
    std::array<std::array<long long, 3>, 3> t{};
    for (int k = 0; k < 3; ++k) {
      const auto& pp = (*it)[k];
      t[k] = {static_cast<long long>(index.at(V2{pp.first.x(), pp.first.y()})), pp.second.x(), pp.second.y()};
    }
    std::rotate(t.begin(), std::min_element(t.begin(), t.end()), t.end());
    triangles.push_back(t);
  }
  std::sort(triangles.begin(), triangles.end());
  Json rows = Json::array();
  for (const auto& t : triangles) {
    Json row = Json::array();
    for (const auto& v : t) row.push_back(offset_vertex(v[0], {static_cast<int>(v[1]), static_cast<int>(v[2])}));
    rows.push_back(std::move(row));
  }
  Json report = geometry_frame(request, "periodic_delaunay_triangulation_2", request.parameters,
                               {{"points_sha256", request.inputs[0].sha256}},
                               {{"vertex_count", triangulation.number_of_vertices()}, {"triangle_count", triangles.size()}},
                               {{"triangles", std::move(rows)}, {"distance_unit", request.inputs[0].unit}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"input_point_count", points.size()}, {"vertex_count", triangulation.number_of_vertices()},
               {"triangle_count", triangles.size()}, {"algorithm", "CGAL::Periodic_2_Delaunay_triangulation_2"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- Periodic_3_Delaunay_triangulation_3 ------------------------------------------------------------
Json periodic_3(const Request& request) {
  require_inputs(request, 1, "triangulation.periodic_delaunay_3");
  require_parameter_names(request, {"domain_min", "period"});
  const auto minimum = domain_min_parameter(request.parameters, 3);
  const double period = positive_length(request.parameters, "period", request.inputs[0].unit);
  const auto points = read_points3(request.inputs[0]);
  require_in_domain(points, minimum, period, 3, kMaximumPeriodicPoints);
  reject_duplicates(points);
  using Gt = CGAL::Periodic_3_Delaunay_triangulation_traits_3<Epick>;
  using P3 = CGAL::Periodic_3_Delaunay_triangulation_3<Gt>;
  P3 triangulation(Gt::Iso_cuboid_3(minimum[0], minimum[1], minimum[2], minimum[0] + period, minimum[1] + period,
                                    minimum[2] + period));
  for (const auto& p : points) triangulation.insert(Epick::Point_3(p[0], p[1], p[2]));
  if (!triangulation.is_1_cover()) {
    precondition("NOT_ONE_SHEETED", "The point set is too sparse for a 1-sheeted periodic triangulation");
  }
  std::map<V3, std::size_t> index;
  for (std::size_t i = 0; i < points.size(); ++i) index[points[i]] = i;
  const Q period_q = query_ops::exact_of(period);
  std::vector<std::array<std::array<long long, 4>, 4>> cells;
  for (auto it = triangulation.periodic_tetrahedra_begin(P3::STORED);
       it != triangulation.periodic_tetrahedra_end(P3::STORED); ++it) {
    std::array<std::array<long long, 4>, 4> t{};
    std::array<Vec, 4> position;
    for (int k = 0; k < 4; ++k) {
      const auto& pp = (*it)[k];
      const auto i = index.at(V3{pp.first.x(), pp.first.y(), pp.first.z()});
      t[k] = {static_cast<long long>(i), pp.second.x(), pp.second.y(), pp.second.z()};
      position[k] = batch2::vec(points[i]) +
                    Vec{period_q * pp.second.x(), period_q * pp.second.y(), period_q * pp.second.z()};
    }
    // Positive orientation in the validator's convention: det(b-a, c-a, d-a) > 0.
    if (batch2::dot(batch2::cross(position[1] - position[0], position[2] - position[0]), position[3] - position[0]) < 0) {
      std::swap(t[0], t[1]);
    }
    cells.push_back(t);
  }
  std::sort(cells.begin(), cells.end());
  Json rows = Json::array();
  for (const auto& t : cells) {
    Json row = Json::array();
    for (const auto& v : t) {
      row.push_back(offset_vertex(v[0], {static_cast<int>(v[1]), static_cast<int>(v[2]), static_cast<int>(v[3])}));
    }
    rows.push_back(std::move(row));
  }
  Json report = geometry_frame(request, "periodic_delaunay_triangulation_3", request.parameters,
                               {{"points_sha256", request.inputs[0].sha256}},
                               {{"vertex_count", triangulation.number_of_vertices()}, {"tetrahedron_count", cells.size()}},
                               {{"tetrahedra", std::move(rows)}, {"distance_unit", request.inputs[0].unit}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"input_point_count", points.size()}, {"vertex_count", triangulation.number_of_vertices()},
               {"edge_count", triangulation.number_of_edges()}, {"facet_count", triangulation.number_of_facets()},
               {"tetrahedron_count", cells.size()}, {"algorithm", "CGAL::Periodic_3_Delaunay_triangulation_3"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- Delaunay_triangulation_on_sphere_2 ---------------------------------------------------------------
Json on_sphere(const Request& request) {
  require_inputs(request, 1, "triangulation.delaunay_on_sphere_2");
  require_parameter_names(request, {"center", "radius"});
  const V3 center = query_ops::vector_parameter(request, "center");
  const double radius = positive_length(request.parameters, "radius", request.inputs[0].unit);
  const auto points = read_points3(request.inputs[0]);
  if (points.size() < 4 || points.size() > kMaximumSpherePoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_COUNT",
                      "Between 4 and " + std::to_string(kMaximumSpherePoints) + " points are supported");
  }
  reject_duplicates(points);
  using Traits = CGAL::Delaunay_triangulation_on_sphere_traits_2<Epick>;
  using Dt = CGAL::Delaunay_triangulation_on_sphere_2<Traits>;
  Traits traits(Epick::Point_3(center[0], center[1], center[2]), radius);
  Dt triangulation(traits);
  for (const auto& p : points) {
    const Epick::Point_3 point(p[0], p[1], p[2]);
    if (!traits.is_on_sphere(point)) {
      precondition("POINT_NOT_ON_SPHERE", "A point is outside CGAL's on-sphere tolerance of the declared sphere");
    }
    if (triangulation.insert(point) == Dt::Vertex_handle()) {
      precondition("POINT_NOT_INSERTED", "A point was rejected by Delaunay_triangulation_on_sphere_2 (too close to another)");
    }
  }
  if (triangulation.number_of_vertices() != points.size()) {
    precondition("POINT_NOT_INSERTED", "A point was merged or rejected by Delaunay_triangulation_on_sphere_2");
  }
  if (triangulation.dimension() != 2 || triangulation.number_of_ghost_faces() != 0) {
    precondition("SPHERE_NOT_COVERED", "The points must not lie in a closed hemisphere (the triangulation has ghost faces)");
  }
  std::map<V3, std::size_t> index;
  for (std::size_t i = 0; i < points.size(); ++i) index[points[i]] = i;
  const Vec c = batch2::vec(center);
  std::vector<std::array<std::size_t, 3>> faces;
  for (auto f = triangulation.all_faces_begin(); f != triangulation.all_faces_end(); ++f) {
    std::array<std::size_t, 3> t{};
    for (int k = 0; k < 3; ++k) {
      const auto& p = f->vertex(k)->point();
      t[k] = index.at(V3{p.x(), p.y(), p.z()});
    }
    // Outward counter-clockwise: det(q-p, r-p, centre-p) < 0.
    const Vec a = batch2::vec(points[t[0]]), b = batch2::vec(points[t[1]]), d = batch2::vec(points[t[2]]);
    if (batch2::dot(batch2::cross(b - a, d - a), c - a) > 0) std::swap(t[1], t[2]);
    std::rotate(t.begin(), std::min_element(t.begin(), t.end()), t.end());
    faces.push_back(t);
  }
  std::sort(faces.begin(), faces.end());
  Json rows = Json::array();
  for (const auto& t : faces) rows.push_back(Json::array({t[0], t[1], t[2]}));
  Json report = geometry_frame(request, "delaunay_triangulation_on_sphere_2", request.parameters,
                               {{"points_sha256", request.inputs[0].sha256}},
                               {{"vertex_count", triangulation.number_of_vertices()}, {"triangle_count", faces.size()}},
                               {{"triangles", std::move(rows)}, {"distance_unit", request.inputs[0].unit}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"input_point_count", points.size()}, {"vertex_count", triangulation.number_of_vertices()},
               {"triangle_count", faces.size()}, {"algorithm", "CGAL::Delaunay_triangulation_on_sphere_2"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> triangulation_producers() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "triangulation.periodic_delaunay_2", {"PointSet2"}, "GeometryQueryReport", "analysis", periodic_2,
      {"Periodic_2_triangulation_2"}, kEpickName,
      pinfo("triangulation.validate.periodic_delaunay_2", {"domain_min", "period"}, {"points"},
            {{"source_header", "CGAL/Periodic_2_Delaunay_triangulation_2.h"},
             {"maximum_input_points", kMaximumPeriodicPoints}})));
  result.push_back(query_definition(
      "triangulation.periodic_delaunay_3", {"PointSet3"}, "GeometryQueryReport", "analysis", periodic_3,
      {"Periodic_3_triangulation_3"}, kEpickName,
      pinfo("triangulation.validate.periodic_delaunay_3", {"domain_min", "period"}, {"points"},
            {{"source_header", "CGAL/Periodic_3_Delaunay_triangulation_3.h"},
             {"maximum_input_points", kMaximumPeriodicPoints}})));
  result.push_back(query_definition(
      "triangulation.delaunay_on_sphere_2", {"PointSet3"}, "GeometryQueryReport", "analysis", on_sphere,
      {"Triangulation_on_sphere_2"}, kEpickName,
      pinfo("triangulation.validate.delaunay_on_sphere_2", {"center", "radius"}, {"points"},
            {{"source_header", "CGAL/Delaunay_triangulation_on_sphere_2.h"},
             {"maximum_input_points", kMaximumSpherePoints}})));
  return result;
}

}  // namespace cgal_master::batch9
