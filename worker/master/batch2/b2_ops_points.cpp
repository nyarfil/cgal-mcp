// Producers wrapping official CGAL 6.2.1 APIs: compute_average_spacing and remove_outliers
// (Point_set_processing_3, 7.9.02 / 7.9.06) and Min_circle_2 / Min_sphere_of_spheres_d
// (Bounding_volumes, 7.13.04). Every result is checked by an independent validator in
// b2_validators_points.cpp that includes no CGAL header.

#include "b2_geometry.h"
#include "b2_registry.h"

#include "../artifact_io.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Min_circle_2.h>
#include <CGAL/Min_circle_2_traits_2.h>
#include <CGAL/Min_sphere_of_spheres_d.h>
#include <CGAL/compute_average_spacing.h>
#include <CGAL/remove_outliers.h>

#include <cmath>
#include <fstream>
#include <locale>

namespace cgal_master::batch2 {
namespace {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";
constexpr std::size_t kMaximumPoints3 = 400;

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
  if (points.size() > kMaximumPoints3) {
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

Json write_xyz_output(const Request& request, const std::vector<Epick::Point_3>& points, const std::string& unit) {
  const auto directory = checked_output_dir(request);
  const auto destination = output_path(directory, "points.xyz");
  const auto temporary = directory / ("." + std::string("points") + "." + staging_filename_token(request.request_id) + ".tmp.xyz");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("OUTPUT_ERROR", "TEMPORARY_OUTPUT_EXISTS", "Temporary output path is not clean");
  }
  {
    std::ofstream output(temporary, std::ios::binary);
    output.imbue(std::locale::classic());
    output.precision(17);
    for (const auto& p : points) output << p.x() << ' ' << p.y() << ' ' << p.z() << '\n';
    output.close();
    if (!output) {
      std::filesystem::remove(temporary);
      throw WorkerError("OUTPUT_ERROR", "OUTPUT_WRITE_FAILED", "Unable to write XYZ output");
    }
  }
  commit_output(temporary, destination);
  return Json{{"slot", "points"}, {"type", "PointSet3"}, {"unit", unit}, {"format", "xyz"}, {"path", portable_path(destination)}};
}

Json outliers(const Request& request) {
  require_inputs(request, 1, "pointset.outliers.remove");
  require_parameter_names(request, {"neighbors", "threshold_percent", "threshold_distance"});
  const auto points = read_points3(request.inputs[0]);
  require_point_budget(points);
  const auto neighbors = integer_parameter(request, "neighbors", 2, 1000);
  if (neighbors >= points.size()) precondition("NEIGHBORHOOD_TOO_LARGE", "neighbors must be smaller than the point count");
  const auto& percent_value = request.parameters.at("threshold_percent");
  if (!percent_value.is_number() || percent_value.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "threshold_percent must be a number in [0,100]");
  }
  const double percent = percent_value.get<double>();
  if (!std::isfinite(percent) || percent < 0 || percent > 100) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "threshold_percent must be in [0,100]");
  }
  const double distance = signed_length_parameter(request, "threshold_distance", request.inputs[0].unit);
  if (distance < 0) throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "threshold_distance must be >= 0");
  auto cgal_points = epick_points(points);
  const auto first = CGAL::remove_outliers<CGAL::Sequential_tag>(
      cgal_points, static_cast<unsigned int>(neighbors),
      CGAL::parameters::threshold_percent(percent).threshold_distance(distance));
  const std::size_t removed = static_cast<std::size_t>(std::distance(first, cgal_points.end()));
  cgal_points.erase(first, cgal_points.end());
  if (cgal_points.empty()) precondition("EMPTY_RESULT", "Every point was removed as an outlier");
  auto output = write_xyz_output(request, cgal_points, request.inputs[0].unit);
  Json metrics{{"input_point_count", points.size()}, {"output_point_count", cgal_points.size()},
               {"removed_point_count", removed}, {"neighbors", neighbors},
               {"algorithm", "CGAL::remove_outliers"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json bounding_circle(const Request& request) {
  require_inputs(request, 1, "shape.bounding.circle");
  require_parameter_names(request, {});
  const auto points = read_points2(request.inputs[0]);
  if (points.empty()) precondition("POINT_SET_EMPTY", "The point set is empty");
  if (points.size() > 64) throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "At most 64 points");
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
  if (points.size() > 32) throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "At most 32 points");
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

}  // namespace

std::vector<OperationDefinition> points_producer_operations() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "pointset.spacing.average", {"PointSet3"}, "GeometryQueryReport", "analysis", spacing,
      {"Point_set_processing_3"}, kEpickName,
      pinfo("pointset.validate.average_spacing", {"neighbors"}, {"points"},
            {{"source_header", "CGAL/compute_average_spacing.h"}, {"maximum_input_points", kMaximumPoints3}})));
  result.push_back(query_definition(
      "pointset.outliers.remove", {"PointSet3"}, "PointSet3", "transform", outliers, {"Point_set_processing_3"},
      kEpickName,
      pinfo("pointset.validate.outliers_removed", {"neighbors", "threshold_percent", "threshold_distance"}, {"points"},
            {{"source_header", "CGAL/remove_outliers.h"}, {"maximum_input_points", kMaximumPoints3}})));
  result.push_back(query_definition(
      "shape.bounding.circle", {"PointSet2"}, "GeometryQueryReport", "analysis", bounding_circle, {"Bounding_volumes"},
      kEpickName,
      pinfo("shape.validate.min_circle", {}, {"points"},
            {{"source_header", "CGAL/Min_circle_2.h"}, {"maximum_input_points", 64}})));
  result.push_back(query_definition(
      "shape.bounding.sphere", {"PointSet3"}, "GeometryQueryReport", "analysis", bounding_sphere, {"Bounding_volumes"},
      kEpickName,
      pinfo("shape.validate.min_sphere", {"radius"}, {"points"},
            {{"source_header", "CGAL/Min_sphere_of_spheres_d.h"}, {"maximum_input_points", 32}})));
  return result;
}

}  // namespace cgal_master::batch2
