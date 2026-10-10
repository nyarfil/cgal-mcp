#include "b8_common.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <numeric>
#include <set>

namespace cgal_master::batch8 {
namespace {

std::size_t find_root(std::vector<std::size_t>& parent, std::size_t x) {
  while (parent[x] != x) {
    parent[x] = parent[parent[x]];
    x = parent[x];
  }
  return x;
}

}  // namespace

Topology analyze_topology(const RawMesh& mesh) {
  Topology t;
  t.faces = mesh.faces.size();
  const std::size_t n = mesh.vertices.size();
  std::vector<bool> used(n, false);
  std::map<std::pair<std::size_t, std::size_t>, int> directed;
  bool bad = false;
  for (const auto& face : mesh.faces) {
    if (face.size() != 3) {
      bad = true;
      continue;
    }
    for (std::size_t k = 0; k < 3; ++k) {
      const std::size_t a = face[k], b = face[(k + 1) % 3];
      if (a >= n || b >= n || a == b) {
        bad = true;
        continue;
      }
      used[a] = true;
      ++directed[{a, b}];
    }
  }
  for (std::size_t i = 0; i < n; ++i) {
    if (used[i]) ++t.vertices;
    else t.unreferenced_vertex = true;
  }
  std::set<std::pair<std::size_t, std::size_t>> undirected;
  std::map<std::size_t, std::vector<std::size_t>> boundary_next;
  for (const auto& [edge, count] : directed) {
    if (count > 1) bad = true;
    undirected.insert({std::min(edge.first, edge.second), std::max(edge.first, edge.second)});
    if (directed.find({edge.second, edge.first}) == directed.end()) {
      ++t.boundary_edges;
      boundary_next[edge.first].push_back(edge.second);
    }
  }
  t.edges = undirected.size();
  // Components through shared vertices.
  std::vector<std::size_t> parent(n);
  std::iota(parent.begin(), parent.end(), 0);
  for (const auto& face : mesh.faces) {
    if (face.size() != 3) continue;
    for (std::size_t k = 1; k < 3; ++k) {
      if (face[0] < n && face[k] < n) parent[find_root(parent, face[0])] = find_root(parent, face[k]);
    }
  }
  t.vertex_component.assign(n, static_cast<std::size_t>(-1));
  std::map<std::size_t, std::size_t> ids;
  for (std::size_t i = 0; i < n; ++i) {
    if (!used[i]) continue;
    const auto root = find_root(parent, i);
    auto [it, inserted] = ids.insert({root, ids.size()});
    t.vertex_component[i] = it->second;
  }
  t.components = ids.size();
  // Vertex links: the faces around a vertex must form one fan.
  std::vector<std::vector<std::size_t>> around(n);
  for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
    if (mesh.faces[f].size() != 3) continue;
    for (const auto v : mesh.faces[f]) {
      if (v < n) around[v].push_back(f);
    }
  }
  for (std::size_t v = 0; v < n && !bad; ++v) {
    const auto& faces = around[v];
    if (faces.empty()) continue;
    std::vector<std::size_t> fan(faces.size());
    std::iota(fan.begin(), fan.end(), 0);
    for (std::size_t i = 0; i < faces.size(); ++i) {
      for (std::size_t j = i + 1; j < faces.size(); ++j) {
        // Faces i and j are neighbours at v when they share an edge through v.
        std::size_t shared = 0;
        for (const auto a : mesh.faces[faces[i]]) {
          if (a == v) continue;
          for (const auto b : mesh.faces[faces[j]]) {
            if (a == b) ++shared;
          }
        }
        if (shared > 0) fan[find_root(fan, i)] = find_root(fan, j);
      }
    }
    std::set<std::size_t> roots;
    for (std::size_t i = 0; i < faces.size(); ++i) roots.insert(find_root(fan, i));
    if (roots.size() != 1) bad = true;
  }
  for (const auto& entry : boundary_next) {
    if (entry.second.size() != 1) bad = true;
  }
  t.oriented_manifold = !bad;
  t.closed = t.oriented_manifold && t.boundary_edges == 0;
  if (t.oriented_manifold && t.boundary_edges > 0) {
    std::set<std::size_t> visited;
    for (const auto& entry : boundary_next) {
      if (visited.count(entry.first)) continue;
      std::vector<std::size_t> loop;
      std::size_t current = entry.first;
      while (!visited.count(current)) {
        visited.insert(current);
        loop.push_back(current);
        const auto next = boundary_next.find(current);
        if (next == boundary_next.end()) break;
        current = next->second.front();
      }
      t.boundary_loops.push_back(std::move(loop));
    }
  }
  return t;
}

Q signed_volume(const RawMesh& mesh) {
  Q six;
  for (const auto& face : mesh.faces) {
    const Vec a = batch2::vec(mesh.vertices.at(face.at(0)));
    const Vec b = batch2::vec(mesh.vertices.at(face.at(1)));
    const Vec c = batch2::vec(mesh.vertices.at(face.at(2)));
    six += batch2::dot(a, batch2::cross(b, c));
  }
  return six / 6;
}

Location locate_point(const RawMesh& mesh, const Vec& p) {
  static const Vec directions[] = {
      {Q(10007), Q(1303), Q(2791)}, {Q(-3011), Q(9973), Q(701)}, {Q(211), Q(-509), Q(10009)},
      {Q(-7919), Q(-1013), Q(-6007)}, {Q(4001), Q(-9001), Q(1999)}};
  for (const auto& d : directions) {
    std::size_t crossings = 0;
    bool ambiguous = false;
    for (const auto& face : mesh.faces) {
      const Vec a = batch2::vec(mesh.vertices.at(face.at(0)));
      const Vec b = batch2::vec(mesh.vertices.at(face.at(1)));
      const Vec c = batch2::vec(mesh.vertices.at(face.at(2)));
      const Vec n = batch2::cross(b - a, c - a);
      const Q den = batch2::dot(n, d);
      const Q height = batch2::dot(n, a - p);
      if (den == 0) {
        if (height == 0) {  // ray parallel to and in the plane of the triangle
          ambiguous = true;
          break;
        }
        continue;
      }
      const Q t = height / den;
      if (t < 0) continue;
      const Vec h = p + t * d;
      const Q wa = batch2::dot(n, batch2::cross(c - b, h - b));
      const Q wb = batch2::dot(n, batch2::cross(a - c, h - c));
      const Q wc = batch2::dot(n, batch2::cross(b - a, h - a));
      if (wa < 0 || wb < 0 || wc < 0) continue;
      if (t == 0) return Location::OnSurface;  // p is in the closed triangle
      if (wa == 0 || wb == 0 || wc == 0) {
        ambiguous = true;
        break;
      }
      ++crossings;
    }
    if (ambiguous) continue;
    return crossings % 2 == 1 ? Location::Inside : Location::Outside;
  }
  return Location::Ambiguous;
}

std::vector<V3> read_vertex_array(const Json& value, const std::string& context) {
  if (!value.is_array()) query_ops::validation_failure("REPORT_VALUE_INVALID", context + " must be an array");
  std::vector<V3> result;
  for (const auto& item : value) {
    if (!item.is_array() || item.size() != 3) {
      query_ops::validation_failure("REPORT_VALUE_INVALID", context + " entries must be [x,y,z]");
    }
    V3 p{};
    for (std::size_t k = 0; k < 3; ++k) {
      if (!item[k].is_number() || !std::isfinite(item[k].get<double>())) {
        query_ops::validation_failure("REPORT_VALUE_INVALID", context + " coordinates must be finite numbers");
      }
      p[k] = item[k].get<double>();
    }
    result.push_back(p);
  }
  return result;
}

}  // namespace cgal_master::batch8
