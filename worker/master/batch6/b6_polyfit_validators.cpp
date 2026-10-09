// Independent validator for polygonal surface reconstructions (7.10.02: Polygonal_surface_reconstruction
// and Kinetic_surface_reconstruction). No CGAL header is included. The candidate is a polygon soup;
// everything is decided on the raw binary64 OFF/PLY data in exact GMP rationals:
//   * every face is a simple polygon whose vertices lie within `planarity_tolerance` of its Newell plane
//     (exact comparison of squares; the producers compute vertices with inexact constructions, so exact
//     planarity is neither claimed nor required),
//   * the soup is a closed, edge-manifold, vertex-manifold, consistently oriented, outward oriented
//     surface (directed-edge pairing, vertex-link cycles, exact signed volume of the ear-clipped faces),
//   * every source point lies within `max_deviation` of the surface (exact point-triangle squared distance
//     to the exactly ear-clipped faces) and its normal agrees with the orientation of a nearest face.

#include "b6_common.h"

#include "../batch5/b5_common.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>

namespace cgal_master::batch6 {
namespace {

using batch2::cross;
using batch2::dot;
using batch2::vec;
using batch2::vinfo;
using query_ops::exact_of;
using query_ops::read_raw_mesh;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::signed_length_parameter;
using query_ops::validation_failure;

constexpr std::size_t kMaximumValidatedPoints = 4000;

struct Triangle {
  std::size_t a, b, c;
  std::size_t face;
};

Vec newell_normal(const std::vector<Vec>& v, const std::vector<std::size_t>& face) {
  Vec n{0, 0, 0};
  for (std::size_t i = 0; i < face.size(); ++i) {
    const Vec& p = v[face[i]];
    const Vec& q = v[face[(i + 1) % face.size()]];
    n.x += (p.y - q.y) * (p.z + q.z);
    n.y += (p.z - q.z) * (p.x + q.x);
    n.z += (p.x - q.x) * (p.y + q.y);
  }
  return n;
}

int sign_of(const Q& value) { return value > 0 ? 1 : (value < 0 ? -1 : 0); }

// Exact ear clipping of a simple polygon in the projection that drops the dominant Newell axis.
// Returns false when the polygon is not simple enough to be ear-clipped (self-touching, bow-tie, ...).
bool ear_clip(const std::vector<Vec>& v, const std::vector<std::size_t>& face, const Vec& normal,
              std::size_t face_index, std::vector<Triangle>& out) {
  int axis = 0;
  Q best = abs(normal.x);
  if (abs(normal.y) > best) { axis = 1; best = abs(normal.y); }
  if (abs(normal.z) > best) { axis = 2; }
  const Q& component = axis == 0 ? normal.x : (axis == 1 ? normal.y : normal.z);
  const int orientation = sign_of(component);  // (y,z), (z,x), (x,y) are ccw for +x, +y, +z
  auto project = [&](std::size_t i) -> std::array<Q, 2> {
    const Vec& p = v[i];
    switch (axis) {
      case 0: return {p.y, p.z};
      case 1: return {p.z, p.x};
      default: return {p.x, p.y};
    }
  };
  auto turn = [&](std::size_t a, std::size_t b, std::size_t c) {
    const auto pa = project(a), pb = project(b), pc = project(c);
    return sign_of((pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0])) * orientation;
  };
  std::vector<std::size_t> ring = face;
  std::size_t guard = 0;
  while (ring.size() > 3) {
    if (++guard > face.size() * face.size() + 8) return false;
    bool clipped = false;
    for (std::size_t i = 0; i < ring.size() && !clipped; ++i) {
      const std::size_t prev = ring[(i + ring.size() - 1) % ring.size()], cur = ring[i], next = ring[(i + 1) % ring.size()];
      const int t = turn(prev, cur, next);
      if (t == 0) {
        // Collinear corner: removable only when cur lies strictly between its neighbours.
        const Vec a = v[prev] - v[cur], b = v[next] - v[cur];
        if (dot(a, b) < 0) {
          ring.erase(ring.begin() + static_cast<std::ptrdiff_t>(i));
          clipped = true;
        }
        continue;
      }
      if (t < 0) continue;
      bool empty = true;
      for (const auto other : ring) {
        if (other == prev || other == cur || other == next) continue;
        if (turn(prev, cur, other) >= 0 && turn(cur, next, other) >= 0 && turn(next, prev, other) >= 0) {
          empty = false;
          break;
        }
      }
      if (!empty) continue;
      out.push_back({prev, cur, next, face_index});
      ring.erase(ring.begin() + static_cast<std::ptrdiff_t>(i));
      clipped = true;
    }
    if (!clipped) return false;
  }
  if (ring.size() == 3) {
    if (turn(ring[0], ring[1], ring[2]) <= 0) return false;
    out.push_back({ring[0], ring[1], ring[2], face_index});
  } else {
    return false;
  }
  return true;
}

Json run_validator(const Request& request) {
  const std::string validator = "reconstruction.validate.polygonal_surface";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"max_deviation", "planarity_tolerance"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto mesh = read_raw_mesh(request.inputs[0], {"PolygonSoup3"});
  const auto source = reconstruction_ops::read_points_with_normals(request.inputs[1]);
  const double max_deviation = signed_length_parameter(request, "max_deviation", request.inputs[1].unit);
  const double planarity = signed_length_parameter(request, "planarity_tolerance", request.inputs[1].unit);
  if (!(max_deviation > 0) || !(planarity > 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "max_deviation and planarity_tolerance must be positive");
  }
  if (source.points.empty()) validation_failure("SOURCE_EMPTY", "The source point set is empty");
  if (source.points.size() > kMaximumValidatedPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "The source exceeds the validation point budget");
  }
  for (const auto& n : source.normals) {
    if (!(n[0] * n[0] + n[1] * n[1] + n[2] * n[2] > 0)) validation_failure("SOURCE_NORMAL_ZERO", "A source normal is zero");
  }
  Json checks = Json::object();
  checks["source_points_valid"] = true;
  if (mesh.faces.empty()) validation_failure("MESH_EMPTY", "The candidate has no faces");
  if (mesh.faces.size() > kMaximumPolygonFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "The candidate exceeds the face budget");
  }
  const std::size_t vertex_count = mesh.vertices.size();
  std::vector<Vec> v;
  for (const auto& p : mesh.vertices) v.push_back(vec(p));
  {
    std::set<Vec, bool (*)(const Vec&, const Vec&)> seen([](const Vec& a, const Vec& b) { return a < b; });
    for (const auto& p : v) {
      if (!seen.insert(p).second) validation_failure("DUPLICATE_VERTEX", "Two candidate vertices have the same coordinates");
    }
  }
  std::vector<bool> referenced(vertex_count, false);
  for (const auto& face : mesh.faces) {
    if (face.size() < 3) validation_failure("FACE_TOO_SMALL", "A face has fewer than three vertices");
    std::set<std::size_t> distinct(face.begin(), face.end());
    if (distinct.size() != face.size()) validation_failure("FACE_REPEATS_VERTEX", "A face repeats a vertex");
    for (const auto index : face) {
      if (index >= vertex_count) validation_failure("INDEX_OUT_OF_RANGE", "A face index is out of range");
      referenced[index] = true;
    }
  }
  if (std::find(referenced.begin(), referenced.end(), false) != referenced.end()) {
    validation_failure("UNREFERENCED_VERTEX", "A candidate vertex belongs to no face");
  }
  checks["polygon_faces_well_formed"] = true;

  // Planarity (exact) and ear clipping.
  const Q planarity_squared = exact_of(planarity) * exact_of(planarity);
  std::vector<Vec> normals;
  std::vector<Triangle> triangles;
  Q maximum_planarity_squared = 0;
  for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
    const auto& face = mesh.faces[f];
    const Vec n = newell_normal(v, face);
    if (is_zero(n)) validation_failure("DEGENERATE_FACE", "A face has zero area");
    const Q n2 = dot(n, n);
    // Plane through the centroid of the face vertices with the Newell normal.
    Vec centroid{0, 0, 0};
    for (const auto i : face) centroid = centroid + v[i];
    const Q count = Q(static_cast<unsigned long>(face.size()));
    centroid = Vec{centroid.x / count, centroid.y / count, centroid.z / count};
    for (const auto i : face) {
      const Q offset = dot(n, v[i] - centroid);
      const Q squared = offset * offset / n2;
      if (squared > maximum_planarity_squared) maximum_planarity_squared = squared;
      if (squared > planarity_squared) {
        validation_failure("FACE_NOT_PLANAR", "A face has a vertex farther from its plane than planarity_tolerance");
      }
    }
    normals.push_back(n);
    if (!ear_clip(v, face, n, f, triangles)) {
      validation_failure("FACE_NOT_SIMPLE", "A face is not a simple polygon (exact ear clipping failed)");
    }
  }
  checks["faces_planar_within_tolerance_exact"] = true;
  checks["faces_simple_polygons"] = true;

  // Directed-edge pairing: closed, edge-manifold and consistently oriented.
  std::map<std::pair<std::size_t, std::size_t>, std::size_t> directed;
  for (const auto& face : mesh.faces) {
    for (std::size_t i = 0; i < face.size(); ++i) {
      const auto edge = std::make_pair(face[i], face[(i + 1) % face.size()]);
      if (!directed.emplace(edge, 0).second) {
        validation_failure("EDGE_NOT_MANIFOLD_OR_INCONSISTENT",
                           "A directed edge is used twice (non-manifold edge or inconsistent orientation)");
      }
    }
  }
  std::set<std::pair<std::size_t, std::size_t>> undirected;
  for (const auto& entry : directed) {
    if (directed.count({entry.first.second, entry.first.first}) == 0) {
      validation_failure("SURFACE_NOT_CLOSED", "An edge has no opposite directed edge: the surface is open or inconsistently oriented");
    }
    undirected.insert({std::min(entry.first.first, entry.first.second), std::max(entry.first.first, entry.first.second)});
  }
  checks["closed_edge_manifold_consistently_oriented"] = true;

  // Vertex manifoldness: the corners around each vertex form a single cycle.
  std::vector<std::map<std::size_t, std::size_t>> corners(vertex_count);  // in-neighbour -> out-neighbour
  for (const auto& face : mesh.faces) {
    for (std::size_t i = 0; i < face.size(); ++i) {
      const std::size_t prev = face[(i + face.size() - 1) % face.size()], cur = face[i], next = face[(i + 1) % face.size()];
      corners[cur][prev] = next;
    }
  }
  for (std::size_t i = 0; i < vertex_count; ++i) {
    const auto& map = corners[i];
    std::size_t start = map.begin()->first, current = start, steps = 0;
    do {
      const auto it = map.find(map.at(current));
      if (it == map.end()) validation_failure("VERTEX_NOT_MANIFOLD", "The faces around a vertex do not close up");
      current = it->first;
      ++steps;
    } while (current != start && steps <= map.size());
    if (steps != map.size()) validation_failure("VERTEX_NOT_MANIFOLD", "The faces around a vertex form more than one fan");
  }
  checks["vertex_manifold"] = true;

  // Outward orientation from the exact signed volume of the ear-clipped faces.
  Q volume6 = 0;
  for (const auto& t : triangles) volume6 += dot(v[t.a], cross(v[t.b], v[t.c]));
  if (!(volume6 > 0)) validation_failure("NOT_OUTWARD_ORIENTED", "The exact signed volume is not positive");
  checks["outward_orientation_exact_volume"] = true;

  // Source points: exact distance to the surface and normal agreement.
  const Q bound_squared = exact_of(max_deviation) * exact_of(max_deviation);
  Q maximum_distance_squared = 0;
  std::vector<bool> face_supported(mesh.faces.size(), false);
  for (std::size_t s = 0; s < source.points.size(); ++s) {
    const Vec p = vec(source.points[s]);
    const Vec sn = vec(source.normals[s]);
    bool have = false;
    Q nearest = 0;
    std::vector<std::size_t> nearest_faces;
    std::vector<Q> per_face(mesh.faces.size());
    std::vector<bool> face_seen(mesh.faces.size(), false);
    for (const auto& t : triangles) {
      const Q d = batch5::squared_distance_point_triangle(p, v[t.a], v[t.b], v[t.c]);
      if (!face_seen[t.face] || d < per_face[t.face]) {
        per_face[t.face] = d;
        face_seen[t.face] = true;
      }
    }
    for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
      if (!face_seen[f]) continue;
      if (!have || per_face[f] < nearest) {
        nearest = per_face[f];
        have = true;
      }
    }
    if (nearest > bound_squared) {
      validation_failure("SOURCE_TO_SURFACE_BOUND_EXCEEDED", "A source point is farther from the surface than max_deviation");
    }
    if (nearest > maximum_distance_squared) maximum_distance_squared = nearest;
    bool agrees = false;
    for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
      if (face_seen[f] && per_face[f] == nearest && dot(normals[f], sn) > 0) agrees = true;
      if (face_seen[f] && per_face[f] <= bound_squared) face_supported[f] = true;
    }
    if (!agrees) {
      validation_failure("SOURCE_NORMAL_DISAGREES_WITH_ORIENTATION",
                         "A source normal points against the outward normal of every nearest face");
    }
  }
  checks["source_to_surface_within_bound_exact"] = true;
  checks["source_normals_agree_with_orientation"] = true;

  const std::size_t euler_v = vertex_count, euler_e = undirected.size(), euler_f = mesh.faces.size();
  const long long euler = static_cast<long long>(euler_v) - static_cast<long long>(euler_e) + static_cast<long long>(euler_f);
  std::size_t supported = 0;
  for (const bool item : face_supported) supported += item ? 1 : 0;
  Json details{{"vertex_count", euler_v},
               {"edge_count", euler_e},
               {"face_count", euler_f},
               {"euler_characteristic", euler},
               {"triangle_count_after_ear_clipping", triangles.size()},
               {"signed_volume", volume6.get_d() / 6.0},
               {"max_planarity_deviation", std::sqrt(maximum_planarity_squared.get_d())},
               {"planarity_tolerance", planarity},
               {"max_source_to_surface_distance", std::sqrt(maximum_distance_squared.get_d())},
               {"max_deviation", max_deviation},
               {"faces_with_a_source_point_within_bound", supported},
               {"source_point_count", source.points.size()},
               {"independence", "exact GMP rational Newell planes, ear clipping, directed-edge pairing, vertex-link cycles, signed volume and point-triangle distances on the raw OFF/PLY data; no CGAL header"}};
  return batch2::concluded(request, validator, checks, details);
}

}  // namespace

std::vector<OperationDefinition> polyfit_validators() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "reconstruction.validate.polygonal_surface", {"PolygonSoup3", "PointSet3Normals"}, "ValidationReport",
      "validator", run_validator, {"Polygonal_surface_reconstruction", "Kinetic_surface_reconstruction"}, "exact:GMP",
      Json{{"bound_parameters", {"max_deviation", "planarity_tolerance"}},
           {"checks", {"source_points_valid", "polygon_faces_well_formed", "faces_planar_within_tolerance_exact",
                       "faces_simple_polygons", "closed_edge_manifold_consistently_oriented", "vertex_manifold",
                       "outward_orientation_exact_volume", "source_to_surface_within_bound_exact",
                       "source_normals_agree_with_orientation"}},
           {"input_slots", {"candidate", "source"}},
           {"output_slot", "validation"}}));
  return result;
}

}  // namespace cgal_master::batch6
