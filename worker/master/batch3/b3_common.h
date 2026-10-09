#pragma once
// Batch-3 shared helpers (7.11.03, 7.11.05, 7.12.02, 7.12.03, 7.12.07, 7.5.01). The headers of the
// independent validators include no CGAL header; they use exact GMP rationals only.

#include "../batch2/b2_geometry.h"

#include <vector>

namespace cgal_master::batch3 {

using batch2::Q;
using query_ops::V2;
using query_ops::V3;

std::vector<OperationDefinition> triangulation_producers();
std::vector<OperationDefinition> triangulation_validators();
std::vector<OperationDefinition> planar_producers();
std::vector<OperationDefinition> planar_validators();
std::vector<OperationDefinition> producer_operations();
std::vector<OperationDefinition> validator_operations();

// Weights parameter: an array of exactly `count` finite numbers (squared artifact unit).
std::vector<double> weights_parameter(const Request& request, std::size_t count);

// Determinant of a square rational matrix (Gaussian elimination, exact).
Q determinant(std::vector<std::vector<Q>> matrix);

inline constexpr std::size_t kMaximumWeightedPoints = 400;
inline constexpr std::size_t kMaximumMinkowskiVertices = 16;
inline constexpr std::size_t kMaximumArrangementSegments = 60;

}  // namespace cgal_master::batch3
