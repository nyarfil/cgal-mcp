// Independent validator for mesh.path.shortest (7.8.04). No CGAL header is included.
//
// The geodesic distance on a triangulated polyhedral surface is recomputed from the raw OFF data:
// every shortest path is a polyline whose bends are mesh vertices and whose straight pieces are
// straight in the unfolding of a face sequence. Pieces are enumerated by a depth-first unfolding with
// a visibility window (no face repeats, since a piece that re-enters a convex face is not shortest),
// the pieces form a visibility graph over {sources, mesh vertices, targets} and Dijkstra gives the
// optimum. Unfolding needs square roots, so lengths are long double with the documented
// tolerance kLengthTolerance (relative to the mesh diagonal); no exact claim is made.

#include "b4_common.h"

#include <algorithm>
#include <cmath>
#include <functional>
#include <limits>
#include <map>
#include <queue>

namespace cgal_master::batch4 {
namespace {

using batch2::concluded;
using batch2::require_member;
using batch2::vinfo;
using query_ops::read_raw_mesh;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;

using LD = long double;
constexpr LD kLengthTolerance = 1e-9L;  // relative to (1 + mesh diagonal)
constexpr std::size_t kNodeBudget = 4000000;

struct P2 {
  LD x, y;
};
P2 operator-(const P2& a, const P2& b) { return {a.x - b.x, a.y - b.y}; }
P2 operator+(const P2& a, const P2& b) { return {a.x + b.x, a.y + b.y}; }
P2 operator*(LD s, const P2& a) { return {s * a.x, s * a.y}; }
LD cross2(const P2& a, const P2& b) { return a.x * b.y - a.y * b.x; }
LD length2(const P2& a) { return std::sqrt(a.x * a.x + a.y * a.y); }

struct P3 {
  LD x, y, z;
};
P3 operator-(const P3& a, const P3& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
LD dot3(const P3& a, const P3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
P3 cross3(const P3& a, const P3& b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
LD length3(const P3& a) { return std::sqrt(dot3(a, a)); }

struct SurfaceMesh {
  std::vector<P3> v;
  std::vector<std::array<std::size_t, 3>> f;
  // (min vertex, max vertex) -> faces containing that edge
  std::map<std::pair<std::size_t, std::size_t>, std::vector<std::size_t>> edge_faces;
  LD diagonal = 0;
};

std::pair<std::size_t, std::size_t> edge_key(std::size_t a, std::size_t b) {
  return {std::min(a, b), std::max(a, b)};
}

SurfaceMesh build_mesh(const query_ops::RawMesh& raw) {
  SurfaceMesh mesh;
  LD low[3] = {1e300L, 1e300L, 1e300L}, high[3] = {-1e300L, -1e300L, -1e300L};
  for (const auto& p : raw.vertices) {
    mesh.v.push_back({p[0], p[1], p[2]});
    for (int k = 0; k < 3; ++k) {
      low[k] = std::min<LD>(low[k], p[k]);
      high[k] = std::max<LD>(high[k], p[k]);
    }
  }
  mesh.diagonal = std::sqrt((high[0] - low[0]) * (high[0] - low[0]) + (high[1] - low[1]) * (high[1] - low[1]) +
                            (high[2] - low[2]) * (high[2] - low[2]));
  for (std::size_t i = 0; i < raw.faces.size(); ++i) {
    const auto& face = raw.faces[i];
    if (face.size() != 3) validation_failure("NOT_TRIANGULATED", "Every face must be a triangle");
    std::array<std::size_t, 3> t{face[0], face[1], face[2]};
    if (t[0] == t[1] || t[1] == t[2] || t[0] == t[2]) validation_failure("DEGENERATE_FACE", "A face repeats a vertex");
    const P3 n = cross3(mesh.v[t[1]] - mesh.v[t[0]], mesh.v[t[2]] - mesh.v[t[0]]);
    if (length3(n) == 0) validation_failure("DEGENERATE_FACE", "A face has zero area");
    mesh.f.push_back(t);
    for (int k = 0; k < 3; ++k) mesh.edge_faces[edge_key(t[k], t[(k + 1) % 3])].push_back(i);
  }
  for (const auto& [key, faces] : mesh.edge_faces) {
    if (faces.size() > 2) validation_failure("NON_MANIFOLD_EDGE", "An edge has more than two faces");
  }
  return mesh;
}

P3 position(const SurfaceMesh& mesh, const SurfaceLocation& l) {
  if (l.is_vertex) return mesh.v.at(l.vertex);
  P3 r{0, 0, 0};
  const auto& t = mesh.f.at(l.face);
  for (int k = 0; k < 3; ++k) {
    r.x += l.barycentric[k] * mesh.v[t[k]].x;
    r.y += l.barycentric[k] * mesh.v[t[k]].y;
    r.z += l.barycentric[k] * mesh.v[t[k]].z;
  }
  return r;
}

// Barycentric coordinates of p in face i and the distance of p from the face plane.
bool in_face(const SurfaceMesh& mesh, std::size_t i, const P3& p, LD eps, std::array<LD, 3>* coordinates = nullptr) {
  const auto& t = mesh.f[i];
  const P3 &a = mesh.v[t[0]], &b = mesh.v[t[1]], &c = mesh.v[t[2]];
  const P3 n = cross3(b - a, c - a);
  const LD area2 = dot3(n, n);
  const LD plane = dot3(p - a, n) / std::sqrt(area2);
  if (std::fabs(plane) > eps) return false;
  const LD u = dot3(cross3(c - b, p - b), n) / area2;
  const LD w = dot3(cross3(a - c, p - c), n) / area2;
  const LD s = dot3(cross3(b - a, p - a), n) / area2;
  // tolerance in barycentric units derived from the length tolerance and the smallest altitude
  const LD altitude = std::sqrt(area2) / std::max({length3(b - a), length3(c - b), length3(a - c)});
  const LD slack = eps / altitude;
  if (u < -slack || w < -slack || s < -slack) return false;
  if (coordinates) *coordinates = {u, w, s};
  return true;
}

// Barycentric coordinates in face i of a point of the face (uses vertex ids for vertex locations).
std::array<LD, 3> face_coordinates(const SurfaceMesh& mesh, std::size_t i, const P3& p) {
  std::array<LD, 3> c{};
  in_face(mesh, i, p, std::numeric_limits<LD>::infinity(), &c);
  return c;
}

struct Unfolder {
  const SurfaceMesh& mesh;
  LD eps;
  std::size_t& budget;
  // Key points: mesh vertices (ids 0..V-1) then targets.
  const std::vector<P3>& targets;
  // dist[Y] is lowered when a piece reaches key Y; keys 0..V-1 are vertices, V.. are targets.
  std::vector<LD>& best;
  const std::size_t start_vertex;  // key id to skip (distance zero), or SIZE_MAX
  std::vector<bool> visited;

  void test_keys(std::size_t face, const P2 (&u)[3], const P2& origin, bool has_window, const P2& right,
                 const P2& left) {
    const auto& t = mesh.f[face];
    auto visible = [&](const P2& y) {
      const P2 d = y - origin;
      const LD size = length2(d);
      if (size == 0) return false;
      if (!has_window) return true;
      return cross2(right, d) >= -eps * length2(right) * size && cross2(d, left) >= -eps * length2(left) * size;
    };
    for (int k = 0; k < 3; ++k) {
      if (t[k] == start_vertex) continue;
      if (visible(u[k])) best[t[k]] = std::min(best[t[k]], length2(u[k] - origin));
    }
    for (std::size_t j = 0; j < targets.size(); ++j) {
      std::array<LD, 3> c{};
      if (!in_face(mesh, face, targets[j], eps, &c)) continue;
      const P2 y = c[0] * u[0] + c[1] * u[1] + c[2] * u[2];
      if (length2(y - origin) == 0) {
        best[mesh.v.size() + j] = 0;
      } else if (visible(y)) {
        best[mesh.v.size() + j] = std::min(best[mesh.v.size() + j], length2(y - origin));
      }
    }
  }

  void walk(std::size_t face, const P2 (&u)[3], const P2& origin, bool has_window, P2 right, P2 left) {
    if (++budget > kNodeBudget) validation_failure("SEARCH_BUDGET", "The unfolding search exceeded its budget");
    visited[face] = true;
    test_keys(face, u, origin, has_window, right, left);
    const auto& t = mesh.f[face];
    for (int k = 0; k < 3; ++k) {
      const std::size_t va = t[k], vb = t[(k + 1) % 3], vc = t[(k + 2) % 3];
      const auto& neighbours = mesh.edge_faces.at(edge_key(va, vb));
      for (const std::size_t next : neighbours) {
        if (next == face || visited[next]) continue;
        const P2 pa = u[k] - origin, pb = u[(k + 1) % 3] - origin;
        const LD width = cross2(pa, pb);
        if (std::fabs(width) <= eps * length2(pa) * length2(pb)) continue;  // grazing: covered via vertex keys
        const P2 edge_right = width > 0 ? pa : pb;  // clockwise end of the edge as seen from the origin
        const P2 edge_left = width > 0 ? pb : pa;
        P2 new_right = edge_right, new_left = edge_left;
        if (has_window) {
          if (cross2(right, edge_right) <= 0) new_right = right;
          if (cross2(left, edge_left) >= 0) new_left = left;
          if (cross2(new_right, new_left) < -eps * length2(new_right) * length2(new_left)) continue;
        }
        // Unfold the neighbour across edge (va,vb): place its third vertex on the far side.
        const auto& tn = mesh.f[next];
        std::size_t third = tn[0];
        for (int m = 0; m < 3; ++m) if (tn[m] != va && tn[m] != vb) third = tn[m];
        const LD d = length3(mesh.v[vb] - mesh.v[va]);
        const LD a = length3(mesh.v[third] - mesh.v[va]);
        const LD b = length3(mesh.v[third] - mesh.v[vb]);
        const LD x = (a * a - b * b + d * d) / (2 * d);
        const LD h = std::sqrt(std::max<LD>(a * a - x * x, 0));
        const P2 ex = (1 / length2(u[(k + 1) % 3] - u[k])) * (u[(k + 1) % 3] - u[k]);
        P2 normal{-ex.y, ex.x};
        const P2 own_third = u[(k + 2) % 3] - u[k];
        if (cross2(ex, own_third) > 0) normal = {ex.y, -ex.x};  // away from the current face
        const P2 placed = u[k] + x * ex + h * normal;
        // Order the neighbour's corners like its vertex ids.
        P2 un[3];
        for (int m = 0; m < 3; ++m) {
          if (tn[m] == va) un[m] = u[k];
          else if (tn[m] == vb) un[m] = u[(k + 1) % 3];
          else un[m] = placed;
        }
        (void)vc;
        walk(next, un, origin, true, new_right, new_left);
      }
    }
    visited[face] = false;
  }

  // Start from a point of `face` with the given barycentric coordinates.
  void start(std::size_t face, const std::array<LD, 3>& coordinates) {
    const auto& t = mesh.f[face];
    const P3 &a = mesh.v[t[0]], &b = mesh.v[t[1]], &c = mesh.v[t[2]];
    const LD ab = length3(b - a), ac = length3(c - a);
    const LD x = dot3(b - a, c - a) / ab;
    const LD y = std::sqrt(std::max<LD>(ac * ac - x * x, 0));
    P2 u[3] = {{0, 0}, {ab, 0}, {x, y}};
    const P2 origin = coordinates[0] * u[0] + coordinates[1] * u[1] + coordinates[2] * u[2];
    visited.assign(mesh.f.size(), false);
    walk(face, u, origin, false, {0, 0}, {0, 0});
  }
};

struct Query {
  std::vector<std::size_t> start_faces;
  std::vector<std::array<LD, 3>> coordinates;
};

Query containing_faces(const SurfaceMesh& mesh, const P3& p, LD eps) {
  Query q;
  for (std::size_t i = 0; i < mesh.f.size(); ++i) {
    std::array<LD, 3> c{};
    if (in_face(mesh, i, p, eps, &c)) {
      q.start_faces.push_back(i);
      q.coordinates.push_back(c);
    }
  }
  if (q.start_faces.empty()) validation_failure("POINT_NOT_ON_SURFACE", "A point does not lie on the mesh surface");
  return q;
}

Json run_validator(const Request& request) {
  const std::string validator = "mesh.validate.shortest_path";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"sources", "targets"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "shortest_paths");
  const auto raw = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  if (raw.faces.empty() || raw.faces.size() > kMaximumShortestPathFaces) {
    validation_failure("FACE_COUNT", "Between 1 and 64 triangles are supported");
  }
  const auto mesh = build_mesh(raw);
  const auto sources = parse_location_list(request, "sources", kMaximumShortestPathSources, raw);
  const auto targets = parse_location_list(request, "targets", kMaximumShortestPathTargets, raw);
  Json checks;
  const auto results = batch2::check_report_frame(
      report, "mesh.path.shortest", {{"sources", request.parameters.at("sources")}, {"targets", request.parameters.at("targets")}},
      {{"mesh_sha256", &request.inputs[1]}}, checks);
  const LD eps = kLengthTolerance * (1 + mesh.diagonal);
  if (require_member(results, "distance_unit", "results") != request.inputs[1].unit) {
    validation_failure("UNIT_MISMATCH", "The report distance unit differs from the mesh unit");
  }
  checks["distance_unit_matches_mesh"] = true;
  const auto& rows = require_member(results, "targets", "results");
  if (!rows.is_array() || rows.size() != targets.size()) {
    validation_failure("TARGET_COUNT_MISMATCH", "There must be one result row per target");
  }

  const std::size_t V = mesh.v.size();
  std::vector<P3> target_points;
  for (const auto& t : targets) target_points.push_back(position(mesh, t));
  std::size_t budget = 0;

  // best[X][Y]: shortest straight piece from key X to key Y (keys: vertices, then targets).
  const std::size_t keys = V + targets.size();
  const LD infinity = std::numeric_limits<LD>::infinity();
  auto piece_lengths = [&](const Query& q, std::size_t start_vertex) {
    std::vector<LD> best(keys, infinity);
    Unfolder unfolder{mesh, eps, budget, target_points, best, start_vertex, {}};
    for (std::size_t s = 0; s < q.start_faces.size(); ++s) unfolder.start(q.start_faces[s], q.coordinates[s]);
    return best;
  };
  std::vector<std::vector<LD>> vertex_pieces(V);
  for (std::size_t x = 0; x < V; ++x) {
    Query q;
    for (std::size_t i = 0; i < mesh.f.size(); ++i) {
      for (int k = 0; k < 3; ++k) {
        if (mesh.f[i][k] == x) {
          q.start_faces.push_back(i);
          std::array<LD, 3> c{0, 0, 0};
          c[k] = 1;
          q.coordinates.push_back(c);
        }
      }
    }
    if (!q.start_faces.empty()) vertex_pieces[x] = piece_lengths(q, x);
    else vertex_pieces[x].assign(keys, infinity);
  }
  // Distance from each source over the visibility graph (Dijkstra over mesh vertices + targets).
  std::vector<std::vector<LD>> source_distance;  // [source][key]
  for (const auto& s : sources) {
    const P3 p = position(mesh, s);
    const auto q = containing_faces(mesh, p, eps);
    std::size_t start_vertex = static_cast<std::size_t>(-1);
    auto first = piece_lengths(q, start_vertex);
    std::vector<LD> dist = first;
    std::vector<bool> done(keys, false);
    for (;;) {
      std::size_t pick = keys;
      for (std::size_t y = 0; y < V; ++y) {
        if (!done[y] && dist[y] < infinity && (pick == keys || dist[y] < dist[pick])) pick = y;
      }
      if (pick == keys) break;
      done[pick] = true;
      for (std::size_t y = 0; y < keys; ++y) {
        const LD w = std::min(vertex_pieces[pick][y], y < V ? vertex_pieces[y][pick] : infinity);
        if (w < infinity) dist[y] = std::min(dist[y], dist[pick] + w);
      }
    }
    source_distance.push_back(std::move(dist));
  }

  std::vector<LD> recomputed;
  for (std::size_t j = 0; j < targets.size(); ++j) {
    const auto& row = rows[j];
    if (!row.is_object()) validation_failure("REPORT_VALUE_INVALID", "A result row must be an object");
    const auto& distance_json = require_member(row, "distance", "row");
    const auto& source_json = require_member(row, "source_index", "row");
    const auto& path_json = require_member(row, "path", "row");
    if (!distance_json.is_number() || !source_json.is_number_unsigned() || !path_json.is_array() ||
        source_json.get<std::size_t>() >= sources.size() || path_json.size() < 2) {
      validation_failure("REPORT_VALUE_INVALID", "A result row needs distance, source_index and a path of 2+ points");
    }
    const LD reported = distance_json.get<double>();
    const std::size_t source_index = source_json.get<std::size_t>();
    LD best = infinity;
    for (const auto& d : source_distance) best = std::min(best, d[V + j]);
    if (best == infinity) validation_failure("TARGET_UNREACHABLE", "A target is not reachable on the surface");
    recomputed.push_back(best);
    if (std::fabs(reported - best) > eps) {
      validation_failure("DISTANCE_MISMATCH", "The reported distance differs from the recomputed geodesic distance");
    }
    if (source_distance[source_index][V + j] > best + eps) {
      validation_failure("SOURCE_NOT_NEAREST", "The reported source is not a nearest source point");
    }
    // The path: points on the surface, consecutive points in a common face, correct endpoints, length.
    std::vector<P3> points;
    for (const auto& item : path_json) {
      if (!item.is_array() || item.size() != 3) validation_failure("REPORT_VALUE_INVALID", "A path point must be [x,y,z]");
      for (const auto& c : item) {
        if (!c.is_number() || !std::isfinite(c.get<double>())) validation_failure("REPORT_VALUE_INVALID", "Path coordinates must be finite");
      }
      points.push_back({item[0].get<double>(), item[1].get<double>(), item[2].get<double>()});
    }
    if (length3(points.front() - position(mesh, sources[source_index])) > eps ||
        length3(points.back() - target_points[j]) > eps) {
      validation_failure("PATH_ENDPOINT_MISMATCH", "The path must run from the reported source to the target");
    }
    LD total = 0;
    for (std::size_t i = 0; i + 1 < points.size(); ++i) {
      bool shared = false;
      for (std::size_t f = 0; f < mesh.f.size() && !shared; ++f) {
        shared = in_face(mesh, f, points[i], eps) && in_face(mesh, f, points[i + 1], eps);
      }
      if (!shared) validation_failure("PATH_LEAVES_SURFACE", "A path segment does not lie inside a single triangle");
      total += length3(points[i + 1] - points[i]);
    }
    if (std::fabs(total - reported) > eps * static_cast<LD>(points.size())) {
      validation_failure("PATH_LENGTH_MISMATCH", "The path length differs from the reported distance");
    }
  }
  checks["path_points_lie_on_surface_in_shared_faces"] = true;
  checks["path_endpoints_match_source_and_target"] = true;
  checks["path_length_equals_reported_distance"] = true;
  checks["distance_equals_recomputed_geodesic"] = true;
  checks["source_is_nearest"] = true;
  Json distances = Json::array();
  for (const LD d : recomputed) distances.push_back(static_cast<double>(d));
  return concluded(request, validator, checks,
                   {{"recomputed_distances", distances}, {"face_count", mesh.f.size()},
                    {"length_tolerance_relative_to_diagonal", static_cast<double>(kLengthTolerance)},
                    {"independence", "face-sequence unfolding with visibility windows and Dijkstra over mesh vertices in long double; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> mesh_validators() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.validate.shortest_path", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      run_validator, {"Surface_mesh_shortest_path"}, "long double (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "distance_unit_matches_mesh", "path_points_lie_on_surface_in_shared_faces",
             "path_endpoints_match_source_and_target", "path_length_equals_reported_distance",
             "distance_equals_recomputed_geodesic", "source_is_nearest"},
            {"candidate", "mesh"},
            "face-sequence unfolding with visibility windows and Dijkstra over mesh vertices in long double; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch4
