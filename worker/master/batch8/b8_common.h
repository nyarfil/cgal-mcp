#pragma once
// Batch-8 shared declarations (7.8.02 approximate convex decomposition, 7.8.03 mean curvature flow
// skeletonization, 7.8.05 surface parameterization). This header and b8_common.cpp include no CGAL
// header: the independent validators use them and must not touch the packages they check.

#include "../batch2/b2_geometry.h"

#include <array>
#include <cstddef>
#include <string>
#include <vector>

namespace cgal_master::batch8 {

using batch2::Q;
using batch2::Vec;
using query_ops::RawMesh;
using query_ops::V3;

inline constexpr std::size_t kMaximumDecompositionFaces = 2000;
inline constexpr std::size_t kMaximumSkeletonFaces = 3000;
inline constexpr std::size_t kMaximumParameterizationFaces = 2000;

std::vector<OperationDefinition> producer_operations();
std::vector<OperationDefinition> validator_operations();

// Combinatorial analysis of an indexed triangle mesh (no geometry).
struct Topology {
  std::size_t vertices = 0;  // referenced vertices
  std::size_t edges = 0;
  std::size_t faces = 0;
  std::size_t components = 0;  // connected through shared vertices
  std::size_t boundary_edges = 0;
  bool unreferenced_vertex = false;
  bool oriented_manifold = false;  // each directed edge at most once, each vertex link one fan
  bool closed = false;             // oriented_manifold and no boundary edge
  std::vector<std::size_t> vertex_component;
  // Boundary cycles in the direction of the boundary directed edges (the face lies on their left).
  std::vector<std::vector<std::size_t>> boundary_loops;
  long long euler() const {
    return static_cast<long long>(vertices) - static_cast<long long>(edges) + static_cast<long long>(faces);
  }
};
Topology analyze_topology(const RawMesh& mesh);

// Exact signed volume of a closed triangle mesh (divergence theorem), positive for outward faces.
Q signed_volume(const RawMesh& mesh);

enum class Location { Inside, Outside, OnSurface, Ambiguous };
// Exact parity test of a point against a closed oriented triangle mesh (ray casting in the first of a
// fixed list of rational directions whose ray meets no edge or vertex; Ambiguous when all of them do).
Location locate_point(const RawMesh& mesh, const Vec& point);

// A report vertex list [[x,y,z],...] read exactly (finite doubles only).
std::vector<V3> read_vertex_array(const Json& value, const std::string& context);

}  // namespace cgal_master::batch8
