#pragma once
// Independent combinatorial / metric analysis of a TetrahedralMesh, shared by the tetrahedral and
// volume mesh validators. It never calls a mesher; it throws a validation failure on any defect.
#include "../wave_c/wave_c_common.h"

#include <array>
#include <cstddef>
#include <map>
#include <vector>

namespace cgal_master::wave_e {

struct TetAnalysis {
  std::size_t vertex_count = 0, cell_count = 0, edge_count = 0, face_count = 0;
  std::size_t interior_faces = 0, boundary_vertices = 0, boundary_edge_count = 0;
  std::vector<std::array<std::size_t, 3>> boundary_faces;  // outward oriented
  long double volume_sum = 0, boundary_volume = 0;
  double minimum_volume = 0, minimum_dihedral = 0, maximum_dihedral = 0;
  double maximum_radius_edge = 0, maximum_circumradius = 0;
  long long euler = 0, boundary_euler = 0, boundary_genus = 0;
  std::map<std::size_t, long double> subdomain_volume;
  std::map<std::size_t, std::size_t> subdomain_cells;
};

TetAnalysis analyze_tetrahedral_mesh(const wave_c::TetrahedralMeshData& mesh);

}  // namespace cgal_master::wave_e
