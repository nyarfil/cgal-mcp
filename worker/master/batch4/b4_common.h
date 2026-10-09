#pragma once
// Batch-4 shared helpers (7.8.04 shortest paths, 7.13.02 alpha shapes, ...). This header includes no
// CGAL header: the independent validators include it and must not touch the packages they check.

#include "../batch2/b2_geometry.h"

#include <array>
#include <vector>

namespace cgal_master::batch4 {

using batch2::Q;
using query_ops::V2;
using query_ops::V3;

std::vector<OperationDefinition> mesh_producers();
std::vector<OperationDefinition> mesh_validators();
std::vector<OperationDefinition> alpha_producers();
std::vector<OperationDefinition> alpha_validators();
std::vector<OperationDefinition> producer_operations();
std::vector<OperationDefinition> validator_operations();

// ---- 7.13.02 alpha shapes: brute-force validators bound the input size.
inline constexpr std::size_t kMaximumAlpha2Points = 60;
inline constexpr std::size_t kMaximumAlpha3Points = 24;

// ---- 7.8.04 locations on a triangle mesh -----------------------------------------------------------
inline constexpr std::size_t kMaximumShortestPathFaces = 64;
inline constexpr std::size_t kMaximumShortestPathSources = 8;
inline constexpr std::size_t kMaximumShortestPathTargets = 32;

struct SurfaceLocation {
  bool is_vertex = false;
  std::size_t vertex = 0;
  std::size_t face = 0;
  std::array<double, 3> barycentric{};
};

// Parses {"vertex": i} or {"face": f, "barycentric": [a,b,c]} (finite, >= 0, summing to 1 within 1e-12).
SurfaceLocation parse_surface_location(const Json& value, std::size_t vertex_count, std::size_t face_count,
                                       const std::string& context);
V3 location_position(const query_ops::RawMesh& mesh, const SurfaceLocation& location);
std::vector<SurfaceLocation> parse_location_list(const Request& request, const char* name, std::size_t maximum,
                                                 const query_ops::RawMesh& mesh);

}  // namespace cgal_master::batch4
