#pragma once
// Batch-5 shared declarations (7.3.06 mesh distances, 7.3.07 mesh-mesh intersections, 7.12.05 straight
// skeletons, 7.12.06 polygon offsets). This header includes no CGAL header: the independent validators
// include it and must not touch the packages they check.

#include "../batch2/b2_geometry.h"

#include <array>
#include <vector>

namespace cgal_master::batch5 {

using batch2::Q;
using batch2::Vec;
using query_ops::V2;
using query_ops::V3;

std::vector<OperationDefinition> distance_producers();
std::vector<OperationDefinition> distance_validators();
std::vector<OperationDefinition> intersection_producers();
std::vector<OperationDefinition> intersection_validators();
std::vector<OperationDefinition> skeleton_producers();
std::vector<OperationDefinition> skeleton_validators();
std::vector<OperationDefinition> producer_operations();
std::vector<OperationDefinition> validator_operations();

inline constexpr std::size_t kMaximumDistanceFaces = 400;
inline constexpr std::size_t kMaximumDistancePoints = 2000;
inline constexpr std::size_t kMaximumSamplePoints = 20000;
inline constexpr std::size_t kMaximumIntersectionFaces = 200;
inline constexpr std::size_t kMaximumSkeletonVertices = 64;

// Parameters of sample_triangle_mesh shared by the sampling-based distance operations.
struct SamplingSpec {
  bool grid = false;
  double grid_spacing = 0;
  std::size_t seed = 0;
  std::size_t points_on_faces = 0;
  std::size_t points_on_edges = 0;
  bool include_vertices = true;
};

// Parses the "sampling" parameter object (see operations.json) and validates its keys and ranges.
SamplingSpec parse_sampling(const Json& value, const std::string& unit);
// Strictly positive TypedLength {value, unit} normalized to `unit`.
double positive_length(const Json& value, const std::string& name, const std::string& unit);

// Squared distance from p to the closed triangle (a, b, c), exact in rationals (Ericson).
Q squared_distance_point_triangle(const Vec& p, const Vec& a, const Vec& b, const Vec& c);

// Exact rings (mpq coordinates parsed from binary64) for the 2D validators and producer pre-checks.
struct Ring {
  std::vector<std::array<Q, 2>> points;
};
Q ring_signed_area(const Ring& ring);
// Proper or improper intersection of the closed segments (a,b) and (c,d).
bool segments_touch(const std::array<Q, 2>& a, const std::array<Q, 2>& b, const std::array<Q, 2>& c,
                    const std::array<Q, 2>& d);
// -1 outside, 0 on boundary, +1 strictly inside (exact).
int point_in_ring(const std::array<Q, 2>& p, const Ring& ring);
// Rejects non simple rings, intersecting rings or holes outside the outer ring ("POLYGON_*" preconditions).
void check_polygon_with_holes(const Ring& outer, const std::vector<Ring>& holes, bool as_validator);
Ring ring_from_doubles(const std::vector<V2>& points);

}  // namespace cgal_master::batch5
