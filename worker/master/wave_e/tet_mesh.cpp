// Wave E (family 7.14) volume-mesh foundation: the independent validator for the TetrahedralMesh
// artifact (vertices, tetrahedra, per-cell subdomain index). It never calls Mesh_3. It recomputes,
// from the raw JSON alone: exact orientation of every cell, face adjacency (each interior face is
// shared by exactly two cells with opposite outward orientations), a closed boundary surface,
// 3-manifold vertex links (sphere for interior vertices, disk for boundary vertices), face
// connectivity, signed volume (cell sum and boundary divergence sum must agree), an optional
// declared domain volume, and dihedral-angle / radius-edge statistics with optional bounds.
//
// Known limit: global interpenetration of cells that are combinatorially consistent is not
// excluded except through the declared domain volume; internal cavities are rejected.
#include "wave_e_operations.h"

#include "../artifact_io.h"
#include "../wave_c/wave_c_common.h"
#include "../wave_d/wave_d_common.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <map>
#include <numeric>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace cgal_master::wave_e {
namespace {

using wave_c::fail_validation;
using wave_c::finish_validation;
using wave_c::require_input_count;
using wave_c::require_parameters;
using XYZ = wave_c::XYZ;
using Index4 = wave_c::Index4;
using K = CGAL::Exact_predicates_inexact_constructions_kernel;

constexpr double kPi = 3.14159265358979323846;
constexpr double kMaximumMinimumDihedral = 70.5;   // regular tetrahedron: 70.5288 degrees
constexpr double kMinimumRadiusEdgeBound = 0.6123; // regular tetrahedron: sqrt(6)/4
constexpr double kDefaultVolumeTolerance = 1e-6;

XYZ sub(const XYZ& a, const XYZ& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
XYZ add(const XYZ& a, const XYZ& b) { return {a[0] + b[0], a[1] + b[1], a[2] + b[2]}; }
XYZ mul(const XYZ& a, double s) { return {a[0] * s, a[1] * s, a[2] * s}; }
XYZ cross(const XYZ& a, const XYZ& b) {
  return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
double dot(const XYZ& a, const XYZ& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
double norm(const XYZ& a) { return std::sqrt(dot(a, a)); }

// True when CGAL's POSITIVE orientation means the right-handed determinant is positive. Evaluated
// on a reference tetrahedron so the exact predicate is used without assuming its sign convention.
bool cgal_positive_is_right_handed() {
  return CGAL::orientation(K::Point_3(0, 0, 0), K::Point_3(1, 0, 0), K::Point_3(0, 1, 0),
                           K::Point_3(0, 0, 1)) == CGAL::POSITIVE;
}

// Exact orientation sign of a cell: +1 right-handed, -1 inverted, 0 degenerate.
int exact_orientation(const XYZ& a, const XYZ& b, const XYZ& c, const XYZ& d, bool positive_is_rh) {
  const auto result = CGAL::orientation(K::Point_3(a[0], a[1], a[2]), K::Point_3(b[0], b[1], b[2]),
                                        K::Point_3(c[0], c[1], c[2]), K::Point_3(d[0], d[1], d[2]));
  if (result == CGAL::COPLANAR) return 0;
  return (result == CGAL::POSITIVE) == positive_is_rh ? 1 : -1;
}

double optional_number(const Request& request, const char* name, double exclusive_minimum,
                       double maximum, double fallback, bool* present) {
  *present = request.parameters.contains(name);
  if (!*present) return fallback;
  return wave_d::number_parameter(request, name, exclusive_minimum, maximum);
}

// Outward-oriented faces of a positively oriented cell (v0..v3), opposite v0, v1, v2, v3.
constexpr int kOutwardFaces[4][3] = {{1, 2, 3}, {0, 3, 2}, {0, 1, 3}, {0, 2, 1}};

using Triple = std::array<std::size_t, 3>;

Triple sorted_triple(Triple t) {
  std::sort(t.begin(), t.end());
  return t;
}

struct FaceUse {
  std::size_t cell;
  Triple outward;
};

Json run_validate(const Request& request) {
  require_input_count(request, 1, "mesh.validate.tetrahedral_mesh");
  require_parameters(request,
                     {},
                     {"domain_volume", "volume_relative_tolerance", "minimum_dihedral_angle",
                      "maximum_radius_edge_ratio", "minimum_tetrahedron_volume"});
  const auto mesh = wave_c::read_tetrahedral_mesh(request.inputs[0]);
  const std::string& unit = request.inputs[0].unit;
  bool has_domain_volume = false, has_tolerance = false, has_dihedral = false, has_ratio = false,
       has_minimum_volume = false;
  const double domain_volume = optional_number(request, "domain_volume", 0.0, 1e18, 0.0, &has_domain_volume);
  const double volume_tolerance = optional_number(request, "volume_relative_tolerance", 0.0, 0.5,
                                                  kDefaultVolumeTolerance, &has_tolerance);
  const double dihedral_bound = optional_number(request, "minimum_dihedral_angle", 0.0,
                                                kMaximumMinimumDihedral, 0.0, &has_dihedral);
  const double ratio_bound = optional_number(request, "maximum_radius_edge_ratio",
                                             kMinimumRadiusEdgeBound, 1e6, 0.0, &has_ratio);
  const double minimum_volume_bound = optional_number(request, "minimum_tetrahedron_volume", 0.0, 1e18,
                                                      0.0, &has_minimum_volume);
  if (has_tolerance && !has_domain_volume) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "volume_relative_tolerance requires domain_volume");
  }

  const auto& vertices = mesh.vertices;
  const auto& cells = mesh.tetrahedra;
  const std::size_t vertex_count = vertices.size(), cell_count = cells.size();

  // Distinct vertices and no unused vertices.
  {
    std::map<XYZ, int> seen;
    for (const auto& v : vertices) {
      if (++seen[v] > 1) fail_validation("REPEATED_VERTEX", "Mesh repeats a vertex position");
    }
  }
  std::vector<char> used(vertex_count, 0);
  for (const auto& cell : cells) {
    for (const auto index : cell) used[index] = 1;
  }
  if (std::count(used.begin(), used.end(), 0) != 0) {
    fail_validation("UNUSED_VERTEX", "A vertex belongs to no tetrahedron");
  }

  // Cells: distinct indices, exact positive orientation, volume, quality statistics.
  const bool positive_is_rh = cgal_positive_is_right_handed();
  std::vector<Index4> oriented = cells;
  long double volume_sum = 0.0L;
  double minimum_volume = std::numeric_limits<double>::infinity();
  double minimum_dihedral = 180.0, maximum_dihedral = 0.0, maximum_radius_edge = 0.0;
  std::map<std::size_t, long double> subdomain_volume;
  std::map<std::size_t, std::size_t> subdomain_cells;
  constexpr int kEdges[6][4] = {{0, 1, 2, 3}, {0, 2, 1, 3}, {0, 3, 1, 2},
                                {1, 2, 0, 3}, {1, 3, 0, 2}, {2, 3, 0, 1}};
  for (std::size_t c = 0; c < cell_count; ++c) {
    const auto& cell = cells[c];
    const XYZ p[4] = {vertices[cell[0]], vertices[cell[1]], vertices[cell[2]], vertices[cell[3]]};
    std::set<std::size_t> distinct(cell.begin(), cell.end());
    if (distinct.size() != 4) fail_validation("DEGENERATE_TETRAHEDRON", "A tetrahedron repeats a vertex");
    const int sign = exact_orientation(p[0], p[1], p[2], p[3], positive_is_rh);
    if (sign == 0) fail_validation("DEGENERATE_TETRAHEDRON", "A tetrahedron has zero volume");
    if (sign < 0) {
      fail_validation("INVERTED_TETRAHEDRON", "A tetrahedron is negatively oriented");
    }
    const XYZ a = sub(p[1], p[0]), b = sub(p[2], p[0]), d = sub(p[3], p[0]);
    const double determinant = dot(a, cross(b, d));
    const double volume = determinant / 6.0;
    if (!(volume > 0)) fail_validation("INVERTED_TETRAHEDRON", "A tetrahedron has non-positive volume");
    volume_sum += volume;
    subdomain_volume[mesh.subdomains[c]] += volume;
    ++subdomain_cells[mesh.subdomains[c]];
    minimum_volume = std::min(minimum_volume, volume);
    // Radius-edge ratio.
    const XYZ numerator = add(add(mul(cross(b, d), dot(a, a)), mul(cross(d, a), dot(b, b))),
                              mul(cross(a, b), dot(d, d)));
    const double circumradius = norm(numerator) / (2.0 * determinant);
    double shortest = std::numeric_limits<double>::infinity();
    for (int i = 0; i < 4; ++i) {
      for (int j = i + 1; j < 4; ++j) shortest = std::min(shortest, norm(sub(p[i], p[j])));
    }
    maximum_radius_edge = std::max(maximum_radius_edge, circumradius / shortest);
    // Dihedral angles about each of the six edges.
    for (const auto& e : kEdges) {
      const XYZ axis = sub(p[e[1]], p[e[0]]);
      const double axis_length = dot(axis, axis);
      auto perpendicular = [&](int k) {
        const XYZ w = sub(p[k], p[e[0]]);
        return sub(w, mul(axis, dot(w, axis) / axis_length));
      };
      const XYZ u = perpendicular(e[2]), w = perpendicular(e[3]);
      const double cosine = std::max(-1.0, std::min(1.0, dot(u, w) / (norm(u) * norm(w))));
      const double angle = std::acos(cosine) * 180.0 / kPi;
      minimum_dihedral = std::min(minimum_dihedral, angle);
      maximum_dihedral = std::max(maximum_dihedral, angle);
    }
  }

  // Face adjacency.
  std::map<Triple, std::vector<FaceUse>> faces;
  for (std::size_t c = 0; c < cell_count; ++c) {
    for (const auto& slot : kOutwardFaces) {
      const Triple outward{cells[c][slot[0]], cells[c][slot[1]], cells[c][slot[2]]};
      faces[sorted_triple(outward)].push_back({c, outward});
    }
  }
  for (const auto& entry : faces) {
    if (entry.second.size() > 2) {
      fail_validation("NON_MANIFOLD_FACE", "A face is shared by more than two tetrahedra");
    }
  }
  std::size_t interior_faces = 0;
  std::vector<Triple> boundary_faces;
  std::vector<std::size_t> parent(cell_count);
  std::iota(parent.begin(), parent.end(), 0);
  auto find = [&](std::size_t x) {
    while (parent[x] != x) x = parent[x] = parent[parent[x]];
    return x;
  };
  for (const auto& entry : faces) {
    const auto& uses = entry.second;
    if (uses.size() > 2) fail_validation("NON_MANIFOLD_FACE", "A face is shared by more than two tetrahedra");
    if (uses.size() == 2) {
      ++interior_faces;
      const Triple& first = uses[0].outward;
      const Triple& second = uses[1].outward;
      // Opposite outward orientations: the cyclic order of the second is the reverse of the first.
      const bool reversed = (second[0] == first[0] && second[1] == first[2] && second[2] == first[1]) ||
                            (second[0] == first[1] && second[1] == first[0] && second[2] == first[2]) ||
                            (second[0] == first[2] && second[1] == first[1] && second[2] == first[0]);
      if (!reversed) {
        fail_validation("FACE_ORIENTATION_CONFLICT",
                        "Two tetrahedra sharing a face lie on the same side of it (overlap)");
      }
      parent[find(uses[0].cell)] = find(uses[1].cell);
    } else {
      boundary_faces.push_back(uses[0].outward);
    }
  }
  std::size_t components = 0;
  for (std::size_t c = 0; c < cell_count; ++c) {
    if (find(c) == c) ++components;
  }

  // Boundary: a closed oriented 2-manifold (every directed edge once, with its reverse once).
  std::map<std::pair<std::size_t, std::size_t>, int> directed;
  for (const auto& f : boundary_faces) {
    for (int i = 0; i < 3; ++i) ++directed[{f[i], f[(i + 1) % 3]}];
  }
  for (const auto& entry : directed) {
    const auto reverse = directed.find({entry.first.second, entry.first.first});
    if (entry.second != 1 || reverse == directed.end() || reverse->second != 1) {
      fail_validation("BOUNDARY_NOT_CLOSED",
                      "Boundary faces do not form a closed consistently oriented surface "
                      "(hole, T-junction or non-manifold edge)");
    }
  }
  if (components != 1) {
    fail_validation("MULTIPLE_COMPONENTS", "Tetrahedra are not face-connected into one body");
  }

  // Boundary components (faces joined across edges) and boundary divergence volume.
  std::vector<std::size_t> face_parent(boundary_faces.size());
  std::iota(face_parent.begin(), face_parent.end(), 0);
  auto face_find = [&](std::size_t x) {
    while (face_parent[x] != x) x = face_parent[x] = face_parent[face_parent[x]];
    return x;
  };
  std::map<std::pair<std::size_t, std::size_t>, std::size_t> edge_owner;
  long double boundary_volume = 0.0L;
  for (std::size_t i = 0; i < boundary_faces.size(); ++i) {
    const auto& f = boundary_faces[i];
    const XYZ &a = vertices[f[0]], &b = vertices[f[1]], &c = vertices[f[2]];
    boundary_volume += dot(a, cross(b, c)) / 6.0;
    for (int k = 0; k < 3; ++k) {
      auto key = std::minmax(f[k], f[(k + 1) % 3]);
      const auto [position, inserted] = edge_owner.emplace(std::make_pair(key.first, key.second), i);
      if (!inserted) face_parent[face_find(i)] = face_find(position->second);
    }
  }
  std::size_t boundary_components = 0;
  for (std::size_t i = 0; i < boundary_faces.size(); ++i) {
    if (face_find(i) == i) ++boundary_components;
  }
  if (boundary_components != 1) {
    fail_validation("MULTIPLE_BOUNDARY_SURFACES",
                    "Boundary is not a single surface (internal cavity or pinched body)");
  }
  const long double volume_difference = std::fabs(boundary_volume - volume_sum);
  if (volume_difference > 1e-9L * std::max<long double>(volume_sum, 1e-300L)) {
    fail_validation("BOUNDARY_VOLUME_MISMATCH",
                    "Boundary divergence volume differs from the sum of tetrahedron volumes");
  }

  // 3-manifold vertex links.
  std::vector<std::vector<std::size_t>> incident(vertex_count);
  for (std::size_t c = 0; c < cell_count; ++c) {
    for (const auto v : cells[c]) incident[v].push_back(c);
  }
  std::size_t boundary_vertices = 0;
  for (std::size_t v = 0; v < vertex_count; ++v) {
    std::map<std::pair<std::size_t, std::size_t>, int> link_edges;
    std::set<std::size_t> link_vertices;
    std::vector<std::array<std::size_t, 3>> link_triangles;
    for (const auto c : incident[v]) {
      std::array<std::size_t, 3> t{};
      int slot = 0;
      for (const auto w : cells[c]) {
        if (w != v) t[slot++] = w;
      }
      link_triangles.push_back(t);
      for (const auto w : t) link_vertices.insert(w);
      for (int i = 0; i < 3; ++i) {
        const auto key = std::minmax(t[i], t[(i + 1) % 3]);
        ++link_edges[{key.first, key.second}];
      }
    }
    bool link_boundary = false;
    for (const auto& edge : link_edges) {
      if (edge.second > 2) fail_validation("NON_MANIFOLD_VERTEX", "A vertex link is not a 2-manifold");
      if (edge.second == 1) link_boundary = true;
    }
    // Connectivity of the link through shared edges.
    std::vector<std::size_t> link_parent(link_triangles.size());
    std::iota(link_parent.begin(), link_parent.end(), 0);
    auto link_find = [&](std::size_t x) {
      while (link_parent[x] != x) x = link_parent[x] = link_parent[link_parent[x]];
      return x;
    };
    std::map<std::pair<std::size_t, std::size_t>, std::size_t> owner;
    for (std::size_t i = 0; i < link_triangles.size(); ++i) {
      for (int k = 0; k < 3; ++k) {
        const auto key = std::minmax(link_triangles[i][k], link_triangles[i][(k + 1) % 3]);
        const auto [position, inserted] = owner.emplace(std::make_pair(key.first, key.second), i);
        if (!inserted) link_parent[link_find(i)] = link_find(position->second);
      }
    }
    std::size_t link_components = 0;
    for (std::size_t i = 0; i < link_triangles.size(); ++i) {
      if (link_find(i) == i) ++link_components;
    }
    const long long chi = static_cast<long long>(link_vertices.size()) -
                          static_cast<long long>(link_edges.size()) +
                          static_cast<long long>(link_triangles.size());
    if (link_components != 1 || chi != (link_boundary ? 1 : 2)) {
      fail_validation("NON_MANIFOLD_VERTEX",
                      "A vertex link is not a sphere (interior) or a disk (boundary)");
    }
    if (link_boundary) ++boundary_vertices;
  }

  // Euler characteristic of the cell complex (a ball gives 1).
  std::set<std::pair<std::size_t, std::size_t>> edges;
  for (const auto& cell : cells) {
    for (int i = 0; i < 4; ++i) {
      for (int j = i + 1; j < 4; ++j) {
        const auto key = std::minmax(cell[i], cell[j]);
        edges.insert({key.first, key.second});
      }
    }
  }
  const long long euler = static_cast<long long>(vertex_count) - static_cast<long long>(edges.size()) +
                          static_cast<long long>(faces.size()) - static_cast<long long>(cell_count);
  const long long boundary_euler = static_cast<long long>(boundary_vertices) -
                                   static_cast<long long>(edge_owner.size()) +
                                   static_cast<long long>(boundary_faces.size());
  const long long boundary_genus = (2 - boundary_euler) / 2;

  Json checks = {{"vertices_distinct", true},
                 {"no_unused_vertices", true},
                 {"subdomain_indices_valid", true},
                 {"tetrahedra_nondegenerate", true},
                 {"tetrahedra_positively_oriented", true},
                 {"face_adjacency_valid", true},
                 {"interior_faces_shared_by_two", true},
                 {"single_connected_component", true},
                 {"boundary_closed_surface", true},
                 {"single_boundary_surface", true},
                 {"boundary_volume_consistent", true},
                 {"vertex_links_are_manifold", true}};
  Json criteria = Json::array();
  const double total_volume = static_cast<double>(volume_sum);
  if (has_minimum_volume) {
    if (!(minimum_volume >= minimum_volume_bound)) {
      fail_validation("MINIMUM_VOLUME_VIOLATED", "A tetrahedron is smaller than minimum_tetrahedron_volume");
    }
    checks["minimum_volume_criterion_satisfied"] = true;
    criteria.push_back("minimum_tetrahedron_volume");
  }
  if (has_dihedral) {
    if (minimum_dihedral < dihedral_bound - 1e-9) {
      fail_validation("DIHEDRAL_ANGLE_VIOLATED", "A dihedral angle is below minimum_dihedral_angle");
    }
    checks["dihedral_angle_criterion_satisfied"] = true;
    criteria.push_back("minimum_dihedral_angle");
  }
  if (has_ratio) {
    if (maximum_radius_edge > ratio_bound * (1.0 + 1e-9)) {
      fail_validation("RADIUS_EDGE_VIOLATED", "A radius-edge ratio exceeds maximum_radius_edge_ratio");
    }
    checks["radius_edge_criterion_satisfied"] = true;
    criteria.push_back("maximum_radius_edge_ratio");
  }
  Json volume_report = {{"value", total_volume}, {"unit", unit + "^3"}};
  if (has_domain_volume) {
    const double error = std::fabs(total_volume - domain_volume) / domain_volume;
    if (error > volume_tolerance) {
      fail_validation("DOMAIN_VOLUME_MISMATCH", "Total volume differs from the declared domain volume");
    }
    checks["domain_volume_matches"] = true;
    criteria.push_back("domain_volume");
    volume_report["declared_domain_volume"] = domain_volume;
    volume_report["relative_error"] = error;
    volume_report["relative_tolerance"] = volume_tolerance;
  }
  Json subdomains = Json::object();
  for (const auto& entry : subdomain_volume) {
    subdomains[std::to_string(entry.first)] = {
        {"cell_count", subdomain_cells[entry.first]}, {"volume", static_cast<double>(entry.second)}};
  }
  Json report = {
      {"checks", checks},
      {"criteria_enforced", criteria},
      {"vertex_count", vertex_count},
      {"tetrahedron_count", cell_count},
      {"edge_count", edges.size()},
      {"face_count", faces.size()},
      {"interior_face_count", interior_faces},
      {"boundary_face_count", boundary_faces.size()},
      {"boundary_vertex_count", boundary_vertices},
      {"euler_characteristic", euler},
      {"boundary_euler_characteristic", boundary_euler},
      {"boundary_genus", boundary_genus},
      {"minimum_tetrahedron_volume", minimum_volume},
      {"volume", volume_report},
      {"subdomains", subdomains},
      {"minimum_dihedral_angle_degrees", minimum_dihedral},
      {"maximum_dihedral_angle_degrees", maximum_dihedral},
      {"maximum_radius_edge_ratio", maximum_radius_edge},
      {"known_limits", "cell interpenetration that is combinatorially consistent is only excluded "
                       "through domain_volume; internal cavities and multiple bodies are rejected"},
      {"independence",
       "raw JSON parse, CGAL exact orientation predicate only, own face/edge/link combinatorics, "
       "own volume, dihedral and circumradius arithmetic; CGAL Mesh_3 is not used"}};
  return finish_validation(request, "mesh.validate.tetrahedral_mesh", std::move(report));
}

}  // namespace

std::vector<OperationDefinition> tetrahedral_mesh_operations() {
  std::vector<OperationDefinition> result;
  result.push_back(wave_c::make_definition(
      "mesh.validate.tetrahedral_mesh", {"TetrahedralMesh"}, "ValidationReport", "validator",
      run_validate, {"Kernel_23"},
      {{"input_slots", {"candidate"}},
       {"output_slot", "validation"},
       {"optional_parameters",
        {"domain_volume", "volume_relative_tolerance", "minimum_dihedral_angle",
         "maximum_radius_edge_ratio", "minimum_tetrahedron_volume"}},
       {"checks",
        {"vertices_distinct", "no_unused_vertices", "subdomain_indices_valid",
         "tetrahedra_nondegenerate", "tetrahedra_positively_oriented", "face_adjacency_valid",
         "interior_faces_shared_by_two", "single_connected_component", "boundary_closed_surface",
         "single_boundary_surface", "boundary_volume_consistent", "vertex_links_are_manifold"}}}));
  return result;
}

}  // namespace cgal_master::wave_e
