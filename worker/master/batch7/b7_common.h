#pragma once
// Batch-7 shared declarations (7.9.03 point-set smoothing: bilateral_smooth_point_set and the
// CGAL-independent smoothing validator). This header includes no CGAL header: the independent
// validator includes it and must not touch the package it checks (Point_set_processing_3).

#include "../batch2/b2_geometry.h"
#include "../reconstruction/reconstruction_common.h"

#include <vector>

namespace cgal_master::batch7 {

inline constexpr std::size_t kMaximumSmoothingPoints = 5000;

std::vector<OperationDefinition> producer_operations();
std::vector<OperationDefinition> validator_operations();

}  // namespace cgal_master::batch7
