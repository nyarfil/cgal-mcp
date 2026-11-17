// Producers wrapping official CGAL 6.2.1 APIs: compute_average_spacing and remove_outliers
// (Point_set_processing_3, 7.9.02 / 7.9.06), Min_circle_2 / Min_sphere_of_spheres_d
// (Bounding_volumes, 7.13.04) and oriented_bounding_box (Optimal_bounding_box). Every result is checked by an independent validator in
// b2_validators_points.cpp that includes no CGAL header.

#include "b2_geometry.h"
#include "b2_registry.h"

#include "../artifact_io.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Min_circle_2.h>
#include <CGAL/Min_circle_2_traits_2.h>
#include <CGAL/Min_sphere_of_spheres_d.h>
#include <CGAL/compute_average_spacing.h>
#include <CGAL/optimal_bounding_box.h>
#include <CGAL/remove_outliers.h>

#include <array>
#include <cmath>
#include <fstream>
#include <locale>

namespace cgal_master::batch2 {
namespace {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";

using query_ops::enum_parameter;
using query_ops::integer_parameter;
using query_ops::precondition;
using query_ops::read_points2;
using query_ops::read_points3;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::signed_length_parameter;
using query_ops::write_report;

std::vector<Epick::Point_3> epick_points(const std::vector<V3>& points) {
  std::vector<Epick::Point_3> result;
  for (const auto& p : points) result.emplace_back(p[0], p[1], p[2]);
  return result;
}

void require_point_budget(const std::vector<V3>& points) {
  if (points.empty()) precondition("POINT_SET_EMPTY", "The point set is empty");
  if (points.size() > kMaximumNeighborhoodPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "The point set exceeds the point limit");
  }
}

Json spacing(const Request& request) {
  require_inputs(request, 1, "pointset.spacing.average");
  require_parameter_names(request, {"neighbors"});
  const auto points = read_points3(request.inputs[0]);
  require_point_budget(points);
  const auto neighbors = integer_parameter(request, "neighbors", 2, 1000);
  if (neighbors >= points.size()) precondition("NEIGHBORHOOD_TOO_LARGE", "neighbors must be smaller than the point count");
  const auto cgal_points = epick_points(points);
  const double value = CGAL::compute_average_spacing<CGAL::Sequential_tag>(cgal_points, static_cast<unsigned int>(neighbors));
  Json report = geometry_frame(
      request, "average_spacing", {{"neighbors", neighbors}}, {{"points_sha256", request.inputs[0].sha256}},
      {{"point_count", points.size()}},
      {{"average_spacing", {{"value", value}, {"unit", request.inputs[0].unit}}}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"point_count", points.size()}, {"neighbors", neighbors}, {"average_spacing", value},
               {"algorithm", "CGAL::compute_average_spacing"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json bounding_circle(const Request& request) {
  require_inputs(request, 1, "shape.bounding.circle");
  require_parameter_names(request, {});
  const auto points = read_points2(request.inputs[0]);
  if (points.empty()) precondition("POINT_SET_EMPTY", "The point set is empty");
  if (points.size() > kMaximumBoundingPoints) throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "The point set exceeds the point limit");
  std::vector<Epick::Point_2> cgal_points;
  for (const auto& p : points) cgal_points.emplace_back(p[0], p[1]);
  using Traits = CGAL::Min_circle_2_traits_2<Epick>;
  CGAL::Min_circle_2<Traits> circle(cgal_points.begin(), cgal_points.end(), false);
  const auto center = circle.circle().center();
  const double squared = CGAL::to_double(circle.circle().squared_radius());
  const double radius = std::sqrt(squared);
  Json report = geometry_frame(
      request, "minimum_bounding_ball", Json::object(), {{"points_sha256", request.inputs[0].sha256}},
      {{"point_count", points.size()}},
      {{"center", Json::array({CGAL::to_double(center.x()), CGAL::to_double(center.y())})},
       {"radius", {{"value", radius}, {"unit", request.inputs[0].unit}}}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"point_count", points.size()}, {"radius", radius}, {"algorithm", "CGAL::Min_circle_2"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json bounding_sphere(const Request& request) {
  require_inputs(request, 1, "shape.bounding.sphere");
  require_parameter_names(request, {"radius"});
  const auto points = read_points3(request.inputs[0]);
  if (points.empty()) precondition("POINT_SET_EMPTY", "The point set is empty");
  if (points.size() > kMaximumBoundingPoints) throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "The point set exceeds the point limit");
  const double radius = signed_length_parameter(request, "radius", request.inputs[0].unit);
  if (radius < 0) throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "radius must be >= 0");
  using Traits = CGAL::Min_sphere_of_spheres_d_traits_3<Epick, double>;
  using Sphere = Traits::Sphere;
  std::vector<Sphere> spheres;
  for (const auto& p : points) spheres.emplace_back(Epick::Point_3(p[0], p[1], p[2]), radius);
  CGAL::Min_sphere_of_spheres_d<Traits> minimum(spheres.begin(), spheres.end());
  if (!minimum.is_valid()) throw WorkerError("INTERNAL_ERROR", "MINIMUM_SPHERE_INVALID", "CGAL reported an invalid minimum sphere");
  Json center = Json::array();
  auto it = minimum.center_cartesian_begin();
  for (int i = 0; i < 3; ++i, ++it) center.push_back(static_cast<double>(*it));
  const double result_radius = static_cast<double>(minimum.radius());
  Json report = geometry_frame(
      request, "minimum_bounding_ball", {{"radius", {{"value", radius}, {"unit", request.inputs[0].unit}}}},
      {{"points_sha256", request.inputs[0].sha256}}, {{"point_count", points.size()}},
      {{"center", center}, {"radius", {{"value", result_radius}, {"unit", request.inputs[0].unit}}}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"point_count", points.size()}, {"radius", result_radius},
               {"algorithm", "CGAL::Min_sphere_of_spheres_d"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// Oriented bounding box of a point set (CGAL::oriented_bounding_box). The orientation comes from a
// randomized optimization: it is a tight box for the orientation found, not a certified minimum.
Json oriented_box(const Request& request) {
  require_inputs(request, 1, "shape.bounding.oriented_box");
  require_parameter_names(request, {"random_seed"});
  const auto seed = integer_parameter(request, "random_seed", 0, 2147483647);
  const auto points = read_points3(request.inputs[0]);
  if (points.size() < 4) precondition("POINT_SET_TOO_SMALL", "At least four points are required");
  if (points.size() > kMaximumBoundingPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "The point set exceeds the point limit");
  }
  std::vector<Epick::Point_3> cgal_points;
  cgal_points.reserve(points.size());
  for (const auto& p : points) cgal_points.emplace_back(p[0], p[1], p[2]);
  // The points must span space: a second distinct point, a third off their line, a fourth off their plane.
  std::size_t second = 1;
  while (second < cgal_points.size() && cgal_points[second] == cgal_points[0]) ++second;
  std::size_t third = second + 1;
  while (third < cgal_points.size() && CGAL::collinear(cgal_points[0], cgal_points[second], cgal_points[third])) ++third;
  std::size_t fourth = third + 1;
  while (fourth < cgal_points.size() &&
         CGAL::coplanar(cgal_points[0], cgal_points[second], cgal_points[third], cgal_points[fourth])) {
    ++fourth;
  }
  if (fourth >= cgal_points.size()) precondition("DEGENERATE_POINT_SET", "The points lie in one plane");
  std::array<Epick::Point_3, 8> corners;
  CGAL::oriented_bounding_box(cgal_points, corners,
                              CGAL::parameters::use_convex_hull(true).random_seed(static_cast<unsigned int>(seed)));
  Json list = Json::array();
  for (const auto& corner : corners) {
    for (int axis = 0; axis < 3; ++axis) {
      if (!std::isfinite(corner[axis])) {
        throw WorkerError("NUMERIC_FAILURE", "NONFINITE_COORDINATE", "CGAL returned a non-finite corner");
      }
    }
    list.push_back(Json::array({corner.x(), corner.y(), corner.z()}));
  }
  // Corner order of CGAL (as Iso_cuboid_3): 1, 3 and 5 are the neighbours of corner 0.
  const double extents[3] = {std::sqrt(CGAL::squared_distance(corners[0], corners[1])),
                             std::sqrt(CGAL::squared_distance(corners[0], corners[3])),
                             std::sqrt(CGAL::squared_distance(corners[0], corners[5]))};
  const double volume = extents[0] * extents[1] * extents[2];
  Json report = geometry_frame(
      request, "oriented_bounding_box", {{"random_seed", seed}}, {{"points_sha256", request.inputs[0].sha256}},
      {{"point_count", points.size()}},
      {{"corners", list}, {"extents", Json::array({extents[0], extents[1], extents[2]})},
       {"length_unit", request.inputs[0].unit}, {"volume", volume}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"point_count", points.size()}, {"extents", Json::array({extents[0], extents[1], extents[2]})},
               {"volume", volume}, {"algorithm", "CGAL::oriented_bounding_box"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> points_producer_operations() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "pointset.spacing.average", {"PointSet3"}, "GeometryQueryReport", "analysis", spacing,
      {"Point_set_processing_3"}, kEpickName,
      pinfo("pointset.validate.average_spacing", {"neighbors"}, {"points"},
            {{"source_header", "CGAL/compute_average_spacing.h"}, {"maximum_input_points", kMaximumNeighborhoodPoints}})));
  result.push_back(query_definition(
      "shape.bounding.circle", {"PointSet2"}, "GeometryQueryReport", "analysis", bounding_circle, {"Bounding_volumes"},
      kEpickName,
      pinfo("shape.validate.min_circle", {}, {"points"},
            {{"source_header", "CGAL/Min_circle_2.h"}, {"maximum_input_points", kMaximumBoundingPoints}})));
  result.push_back(query_definition(
      "shape.bounding.sphere", {"PointSet3"}, "GeometryQueryReport", "analysis", bounding_sphere, {"Bounding_volumes"},
      kEpickName,
      pinfo("shape.validate.min_sphere", {"radius"}, {"points"},
            {{"source_header", "CGAL/Min_sphere_of_spheres_d.h"}, {"maximum_input_points", kMaximumBoundingPoints}})));
  result.push_back(query_definition(
      "shape.bounding.oriented_box", {"PointSet3"}, "GeometryQueryReport", "analysis", oriented_box,
      {"Optimal_bounding_box"}, kEpickName,
      pinfo("shape.validate.oriented_box", {"random_seed"}, {"points"},
            {{"source_header", "CGAL/optimal_bounding_box.h"}, {"maximum_input_points", kMaximumBoundingPoints}})));
  return result;
}

}  // namespace cgal_master::batch2
