// pointset.smooth.bilateral (7.9.03): CGAL::bilateral_smooth_point_set on an oriented point set. The
// function moves every point along its weighted-average normal and updates the normals; the weights
// combine spatial distance (guessed radius) and normal similarity (sharpness_angle), which keeps
// creases. Results are checked by the independent validator in b7_smoothing_validators.cpp (no CGAL
// header). The sequential tag keeps the result deterministic.

#include "b7_common.h"

#include "../artifact_io.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/bilateral_smooth_point_set.h>
#include <CGAL/property_map.h>

#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <locale>

namespace cgal_master::batch7 {
namespace {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using PointNormal = std::pair<Epick::Point_3, Epick::Vector_3>;
using query_ops::precondition;
using query_ops::require_inputs;
using query_ops::require_parameter_names;

constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";
constexpr double kUnitNormalTolerance = 1e-6;

Json write_ply_output(const Request& request, const std::vector<PointNormal>& points, const std::string& unit) {
  const auto directory = checked_output_dir(request);
  const auto destination = output_path(directory, "points.ply");
  const auto temporary =
      directory / ("." + std::string("points") + "." + staging_filename_token(request.request_id) + ".tmp.ply");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("OUTPUT_ERROR", "TEMPORARY_OUTPUT_EXISTS", "Temporary output path is not clean");
  }
  {
    std::ofstream stream(temporary, std::ios::binary);
    stream.imbue(std::locale::classic());
    stream << "ply\nformat ascii 1.0\nelement vertex " << points.size()
           << "\nproperty double x\nproperty double y\nproperty double z\n"
              "property double nx\nproperty double ny\nproperty double nz\nend_header\n";
    stream << std::setprecision(17);
    for (const auto& item : points) {
      stream << item.first.x() << ' ' << item.first.y() << ' ' << item.first.z() << ' ' << item.second.x() << ' '
             << item.second.y() << ' ' << item.second.z() << '\n';
    }
    stream.close();
    if (!stream) {
      std::filesystem::remove(temporary);
      throw WorkerError("OUTPUT_ERROR", "OUTPUT_WRITE_FAILED", "Unable to write PLY output");
    }
  }
  commit_output(temporary, destination);
  return Json{{"slot", "points"}, {"type", "PointSet3Normals"}, {"unit", unit}, {"format", "ply"},
              {"path", portable_path(destination)}};
}

Json run_bilateral(const Request& request) {
  require_inputs(request, 1, "pointset.smooth.bilateral");
  require_parameter_names(request, {"neighbors", "sharpness_angle"});
  const auto cloud = reconstruction_ops::read_points_with_normals(request.inputs[0]);
  reconstruction_ops::require_point_budget(cloud);
  if (cloud.points.size() > kMaximumSmoothingPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "At most 5000 points are supported");
  }
  const auto neighbors = query_ops::integer_parameter(request, "neighbors", 2, 1000);
  const auto& angle_value = request.parameters.at("sharpness_angle");
  if (!angle_value.is_number() || angle_value.is_boolean() || !std::isfinite(angle_value.get<double>()) ||
      angle_value.get<double>() <= 0 || angle_value.get<double>() >= 90) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "sharpness_angle must lie strictly between 0 and 90 degrees");
  }
  const double angle = angle_value.get<double>();
  if (cloud.points.size() <= neighbors) {
    precondition("NEIGHBORS_NOT_BELOW_POINT_COUNT", "neighbors must be smaller than the point count");
  }
  if (reconstruction_ops::affine_rank(cloud.points) < 2) {
    precondition("DEGENERATE_POINT_SET", "The points are collinear or coincident");
  }
  std::vector<PointNormal> points;
  for (std::size_t i = 0; i < cloud.points.size(); ++i) {
    const auto& n = cloud.normals[i];
    const double length = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
    if (length == 0) precondition("ZERO_NORMAL", "Every point needs a nonzero normal");
    if (std::fabs(length - 1.0) > kUnitNormalTolerance) {
      precondition("NORMAL_NOT_UNIT", "Every normal must have unit length");
    }
    points.emplace_back(Epick::Point_3(cloud.points[i][0], cloud.points[i][1], cloud.points[i][2]),
                        Epick::Vector_3(n[0], n[1], n[2]));
  }
  const auto original = points;
  const double movement = CGAL::bilateral_smooth_point_set<CGAL::Sequential_tag>(
      points, static_cast<unsigned int>(neighbors),
      CGAL::parameters::point_map(CGAL::First_of_pair_property_map<PointNormal>())
          .normal_map(CGAL::Second_of_pair_property_map<PointNormal>())
          .sharpness_angle(angle));
  if (!std::isfinite(movement)) {
    throw WorkerError("NUMERIC_FAILURE", "NON_FINITE_MOVEMENT", "CGAL returned a non-finite movement");
  }
  std::size_t moved = 0;
  for (std::size_t i = 0; i < points.size(); ++i) {
    for (const double value : {points[i].first.x(), points[i].first.y(), points[i].first.z(), points[i].second.x(),
                               points[i].second.y(), points[i].second.z()}) {
      if (!std::isfinite(value)) {
        throw WorkerError("NUMERIC_FAILURE", "NON_FINITE_OUTPUT", "The smoothed point set is not finite");
      }
    }
    if (points[i].first != original[i].first) ++moved;
  }
  const auto output = write_ply_output(request, points, request.inputs[0].unit);
  return success_result(request, Json::array({output}),
                        {{"algorithm", "CGAL::bilateral_smooth_point_set"},
                         {"neighbors", neighbors},
                         {"sharpness_angle", angle},
                         {"mean_squared_movement", movement},
                         {"moved_point_count", moved},
                         {"point_count", points.size()},
                         {"deterministic", true}});
}

}  // namespace

std::vector<OperationDefinition> bilateral_producers() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "pointset.smooth.bilateral", {"PointSet3Normals"}, "PointSet3Normals", "transform", run_bilateral,
      {"Point_set_processing_3"}, kEpickName,
      Json{{"source_header", "CGAL/bilateral_smooth_point_set.h"},
           {"input_format", "ascii_ply_with_x_y_z_nx_ny_nz"},
           {"output_format", "ascii_ply_with_x_y_z_nx_ny_nz"},
           {"required_parameters", {"neighbors", "sharpness_angle"}},
           {"validators", {"pointset.validate.basic", "pointset.validate.smoothing_quality"}},
           {"validator_parameter_bindings", {{"pointset.validate.smoothing_quality", {{"neighbors", "neighbors"}}}}}}));
  return result;
}

}  // namespace cgal_master::batch7
