// pointset.validate.smoothing_quality (7.9.03): CGAL-independent validator for point-set smoothing
// (jet_smooth_point_set and bilateral_smooth_point_set). No CGAL header is included and no CGAL
// algorithm is replayed: the checks use only the raw binary64 input and output.
//
// Contract (declared, not a proof of optimal smoothing):
//   1. the candidate has the same point count and type as the source, every coordinate is finite and,
//      when normals are present, every candidate normal is unit length (1e-6);
//   2. no point moves farther than the distance from its source position to its k-th nearest other
//      source point (brute force), so a point never leaves its own k-neighbourhood;
//   3. the local roughness does not stay put: the RMS distance of the points of every source
//      k-neighbourhood (plus the centre) to their own least-squares plane, taken over all
//      neighbourhoods (Jacobi eigen decomposition, long double), must DECREASE from the source to
//      the candidate whenever the source has any roughness, and must not exceed the source otherwise.
// Real smoothers that raise the plane-fit roughness (for example on strongly curved, noise-free data)
// are rejected on purpose: this validator accepts only measurable noise reduction.

#include "b7_common.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <numeric>

namespace cgal_master::batch7 {
namespace {

using batch2::concluded;
using batch2::vinfo;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;
using reconstruction_ops::V3;

using LD = long double;
constexpr LD kDisplacementTolerance = 1e-9L;
constexpr LD kRoughnessTolerance = 1e-9L;
constexpr double kUnitNormalTolerance = 1e-6;

struct Cloud {
  std::vector<V3> points;
  std::vector<V3> normals;
  bool has_normals = false;
};

Cloud read_cloud(const ArtifactInput& input) {
  Cloud cloud;
  if (input.type == "PointSet3Normals") {
    auto read = reconstruction_ops::read_points_with_normals(input);
    cloud.points = std::move(read.points);
    cloud.normals = std::move(read.normals);
    cloud.has_normals = true;
  } else if (input.type == "PointSet3") {
    cloud.points = reconstruction_ops::read_points(input).points;
  } else {
    throw WorkerError("TYPE_ERROR", "INPUT_TYPE_MISMATCH", "Expected PointSet3 or PointSet3Normals");
  }
  return cloud;
}

LD squared_distance(const V3& a, const V3& b) {
  const LD x = static_cast<LD>(a[0]) - b[0], y = static_cast<LD>(a[1]) - b[1], z = static_cast<LD>(a[2]) - b[2];
  return x * x + y * y + z * z;
}

// Smallest eigenvalue of a symmetric 3x3 matrix by cyclic Jacobi rotations.
LD smallest_eigenvalue(std::array<std::array<LD, 3>, 3> a) {
  for (int sweep = 0; sweep < 60; ++sweep) {
    const LD off = a[0][1] * a[0][1] + a[0][2] * a[0][2] + a[1][2] * a[1][2];
    const LD diagonal = a[0][0] * a[0][0] + a[1][1] * a[1][1] + a[2][2] * a[2][2];
    if (off <= std::numeric_limits<LD>::epsilon() * std::numeric_limits<LD>::epsilon() * (diagonal + off) ||
        off == 0) {
      break;
    }
    for (int p = 0; p < 2; ++p) {
      for (int q = p + 1; q < 3; ++q) {
        if (a[p][q] == 0) continue;
        const LD theta = (a[q][q] - a[p][p]) / (2 * a[p][q]);
        const LD t = (theta >= 0 ? 1 : -1) / (std::fabs(theta) + std::sqrt(theta * theta + 1));
        const LD c = 1 / std::sqrt(t * t + 1), s = t * c;
        for (int k = 0; k < 3; ++k) {
          const LD akp = a[k][p], akq = a[k][q];
          a[k][p] = c * akp - s * akq;
          a[k][q] = s * akp + c * akq;
        }
        for (int k = 0; k < 3; ++k) {
          const LD apk = a[p][k], aqk = a[q][k];
          a[p][k] = c * apk - s * aqk;
          a[q][k] = s * apk + c * aqk;
        }
      }
    }
  }
  return std::max<LD>(0, std::min({a[0][0], a[1][1], a[2][2]}));
}

// Mean squared distance of the points of `group` to their least-squares plane.
LD plane_variance(const std::vector<V3>& points, const std::vector<std::size_t>& group) {
  std::array<LD, 3> centroid{0, 0, 0};
  for (const auto index : group) {
    for (int k = 0; k < 3; ++k) centroid[k] += points[index][k];
  }
  for (auto& value : centroid) value /= static_cast<LD>(group.size());
  std::array<std::array<LD, 3>, 3> covariance{};
  for (const auto index : group) {
    LD d[3];
    for (int k = 0; k < 3; ++k) d[k] = static_cast<LD>(points[index][k]) - centroid[k];
    for (int r = 0; r < 3; ++r) {
      for (int c = 0; c < 3; ++c) covariance[r][c] += d[r] * d[c];
    }
  }
  for (auto& row : covariance) {
    for (auto& value : row) value /= static_cast<LD>(group.size());
  }
  return smallest_eigenvalue(covariance);
}

LD rms_roughness(const std::vector<V3>& points, const std::vector<std::vector<std::size_t>>& groups) {
  LD total = 0;
  for (const auto& group : groups) total += plane_variance(points, group);
  return std::sqrt(total / static_cast<LD>(groups.size()));
}

Json run_smoothing_quality(const Request& request) {
  const std::string validator = "pointset.validate.smoothing_quality";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"neighbors"});
  const auto& candidate_input = request.inputs[0];
  const auto& source_input = request.inputs[1];
  query_ops::require_same_unit(candidate_input, source_input);
  if (candidate_input.type != source_input.type) {
    validation_failure("TYPE_MISMATCH", "Candidate and source must be the same point-set type");
  }
  const auto candidate = read_cloud(candidate_input);
  const auto source = read_cloud(source_input);
  if (candidate.points.size() != source.points.size()) {
    validation_failure("POINT_COUNT_CHANGED", "Smoothing must preserve the point count");
  }
  const std::size_t count = source.points.size();
  if (count > kMaximumSmoothingPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "At most 5000 points are supported");
  }
  const std::size_t neighbors = query_ops::integer_parameter(request, "neighbors", 2, 1000);
  if (count <= neighbors + 1) validation_failure("NEIGHBORS_NOT_BELOW_POINT_COUNT", "neighbors must be smaller than the point count");
  Json checks;
  checks["finite_coordinates"] = true;  // the strict readers reject non-finite values
  checks["point_count_preserved"] = true;

  if (candidate.has_normals) {
    for (const auto& n : candidate.normals) {
      const double length = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
      if (!(std::fabs(length - 1.0) <= kUnitNormalTolerance)) {
        validation_failure("NON_UNIT_NORMAL", "Candidate normals must be unit length");
      }
    }
    checks["candidate_normals_unit"] = true;
  }

  // k nearest other source points of every point (ties broken by index), brute force.
  std::vector<std::vector<std::size_t>> groups(count);
  std::vector<LD> kth(count, 0);
  std::vector<std::size_t> order(count);
  for (std::size_t i = 0; i < count; ++i) {
    std::iota(order.begin(), order.end(), std::size_t{0});
    std::vector<LD> distance(count);
    for (std::size_t j = 0; j < count; ++j) distance[j] = squared_distance(source.points[i], source.points[j]);
    std::sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) {
      return distance[a] != distance[b] ? distance[a] < distance[b] : a < b;
    });
    groups[i].push_back(i);
    for (std::size_t r = 0; r < order.size() && groups[i].size() < neighbors + 1; ++r) {
      if (order[r] != i) groups[i].push_back(order[r]);
    }
    kth[i] = std::sqrt(distance[groups[i].back()]);
  }

  LD worst_ratio = 0;
  LD largest_displacement = 0;
  std::size_t moved = 0;
  for (std::size_t i = 0; i < count; ++i) {
    const LD displacement = std::sqrt(squared_distance(candidate.points[i], source.points[i]));
    largest_displacement = std::max(largest_displacement, displacement);
    if (displacement > 0) ++moved;
    if (displacement > kth[i] * (1 + kDisplacementTolerance)) {
      validation_failure("DISPLACEMENT_EXCEEDS_NEIGHBORHOOD",
                         "A point moved farther than the distance to its k-th nearest source neighbour");
    }
    if (kth[i] > 0) worst_ratio = std::max(worst_ratio, displacement / kth[i]);
  }
  checks["displacement_within_neighborhood"] = true;

  const LD diagonal = [&] {
    std::array<LD, 3> low, high;
    for (int k = 0; k < 3; ++k) low[k] = high[k] = source.points[0][k];
    for (const auto& p : source.points) {
      for (int k = 0; k < 3; ++k) {
        low[k] = std::min<LD>(low[k], p[k]);
        high[k] = std::max<LD>(high[k], p[k]);
      }
    }
    return std::sqrt((high[0] - low[0]) * (high[0] - low[0]) + (high[1] - low[1]) * (high[1] - low[1]) +
                     (high[2] - low[2]) * (high[2] - low[2]));
  }();
  const LD floor = 1e-12L * diagonal;
  const LD source_roughness = rms_roughness(source.points, groups);
  const LD candidate_roughness = rms_roughness(candidate.points, groups);
  const bool source_rough = source_roughness > floor;
  if (source_rough ? !(candidate_roughness < source_roughness * (1 - kRoughnessTolerance))
                   : candidate_roughness > floor) {
    validation_failure("ROUGHNESS_NOT_REDUCED",
                       "The local plane-fit roughness of the candidate is not smaller than that of the source");
  }
  checks["local_roughness_reduced"] = true;
  return concluded(request, validator, checks,
                   {{"point_count", count},
                    {"neighbors", neighbors},
                    {"moved_point_count", moved},
                    {"coordinates_modified", moved > 0},
                    {"source_roughness_rms", static_cast<double>(source_roughness)},
                    {"candidate_roughness_rms", static_cast<double>(candidate_roughness)},
                    {"roughness_ratio", source_rough ? static_cast<double>(candidate_roughness / source_roughness) : 1.0},
                    {"maximum_displacement", static_cast<double>(largest_displacement)},
                    {"maximum_displacement_to_neighborhood_ratio", static_cast<double>(worst_ratio)},
                    {"displacement_tolerance_relative", static_cast<double>(kDisplacementTolerance)},
                    {"roughness_tolerance_relative", static_cast<double>(kRoughnessTolerance)},
                    {"independence",
                     "brute-force k-nearest neighbours and a Jacobi plane fit over raw binary64 input and output; "
                     "no CGAL header and no replay of the smoothing algorithm"}});
}

}  // namespace

std::vector<OperationDefinition> smoothing_validators() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "pointset.validate.smoothing_quality", {"PointSet3", "PointSet3Normals", "PointSet3", "PointSet3Normals"},
      "ValidationReport", "validator", run_smoothing_quality, {"Point_set_processing_3"},
      "long double (no CGAL header)",
      vinfo({"finite_coordinates", "point_count_preserved", "displacement_within_neighborhood",
             "local_roughness_reduced"},
            {"candidate", "source"},
            "brute-force k-nearest neighbours and a Jacobi plane fit over raw binary64 input and output; no CGAL "
            "header and no replay of the smoothing algorithm")));
  result.back().info["required_parameters"] = Json::array({"neighbors"});
  result.back().info["bound_parameters"] = Json::array({"neighbors"});
  return result;
}

}  // namespace cgal_master::batch7
