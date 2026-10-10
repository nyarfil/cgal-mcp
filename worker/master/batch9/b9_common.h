#pragma once
// Batch-9 shared declarations (7.8.01 SDF segmentation, 7.11.04 periodic and on-sphere Delaunay
// triangulations). This header includes no CGAL header: the independent validators use it and must
// not touch the packages they check.

#include "../batch2/b2_geometry.h"
#include "../batch8/b8_common.h"

#include <cstddef>
#include <string>
#include <vector>

namespace cgal_master::batch9 {

using batch2::Q;
using batch2::Vec;
using query_ops::RawMesh;
using query_ops::V2;
using query_ops::V3;

inline constexpr std::size_t kMaximumSegmentationFaces = 1500;
inline constexpr std::size_t kMaximumPeriodicPoints = 400;
inline constexpr std::size_t kMaximumSpherePoints = 2000;
inline constexpr long long kMaximumReportedOffset = 3;

std::vector<OperationDefinition> producer_operations();
std::vector<OperationDefinition> validator_operations();

// Shared parameter readers (producers and validators parse the same request parameters).
double finite_number(const Json& parameters, const char* name, double minimum, double maximum, bool minimum_exclusive);
// "domain_min": array of `dimension` finite numbers in the artifact unit.
std::vector<double> domain_min_parameter(const Json& parameters, std::size_t dimension);
// "period" / "radius": TypedLength {value, unit} in the artifact unit, strictly positive.
double positive_length(const Json& parameters, const char* name, const std::string& unit);

}  // namespace cgal_master::batch9
