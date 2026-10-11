// Scalable certified symmetric Hausdorff bracket (validation_mode "certified_bvh"). No CGAL header.
//
// What is certified. For triangle meshes A and B, h(A,B) = sup_{p in A} d(p,B) and H = max(h(A,B), h(B,A)).
// The routine returns [lower, upper] with lower <= H <= upper up to the binary64 rounding of the evaluated
// point-triangle distances, which the caller covers with the declared margin eps (1e-9 * (1 + diagonal)):
//  * lower: every value is an actual distance d(p, other mesh) of a point p of a mesh (vertices, then
//    midpoints of refined sub-triangles), found by an exact nearest-triangle branch-and-bound over a
//    self-written bounding-volume hierarchy (pruning only boxes whose distance is >= the best triangle
//    distance, so no closer triangle is skipped).
//  * upper: for a (sub-)triangle T with corners v_i and ANY triangle S of the other mesh,
//    sup_{p in T} d(p,B) <= sup_{p in T} d(p,S) = max_i d(v_i,S)   (d(.,S) is convex on T).
//    The bound min_S max_i d(v_i,S) is evaluated exactly over all S by branch-and-bound (box lower bound
//    max_i d(v_i, box)); the 1-Lipschitz bound d(v_i) + max edge length from v_i is also used. T is split
//    into four midpoint children while its bound exceeds lower + width (width = min(0.5% diagonal,
//    error_bound / 2)); a sub-triangle whose bound is <= lower + width is closed, so upper <= lower + width.
//  * independent cross-checks: the BVH query is compared with an exhaustive scan over every triangle for a
//    deterministic subsample (the two witness points plus stride-sampled vertices), and the distance of
//    each witness point is recomputed in exact GMP rationals over every triangle within eps of the
//    floating minimum.
// The subdivision principle (convex distance bound on sub-triangles) is a standard bound also used by the
// CGAL producer; the code (hierarchy, distance, refinement, cross-checks) is independent of CGAL.

#include "b5_certified_hausdorff.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <numeric>
#include <vector>

namespace cgal_master::batch5 {
namespace {

using query_ops::validation_failure;

struct P {
  double x, y, z;
};
P operator-(const P& a, const P& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
P operator+(const P& a, const P& b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
P operator*(double s, const P& a) { return {s * a.x, s * a.y, s * a.z}; }
double dot(const P& a, const P& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
double norm(const P& a) { return std::sqrt(dot(a, a)); }
P mid(const P& a, const P& b) { return {(a.x + b.x) * 0.5, (a.y + b.y) * 0.5, (a.z + b.z) * 0.5}; }
P to_p(const V3& v) { return {v[0], v[1], v[2]}; }

struct T3 {
  P a, b, c;
};

// Squared distance from p to the closed triangle (Ericson, Real-Time Collision Detection 5.1.5).
double squared_distance(const P& p, const T3& t) {
  const P ab = t.b - t.a, ac = t.c - t.a, ap = p - t.a;
  const double d1 = dot(ab, ap), d2 = dot(ac, ap);
  if (d1 <= 0 && d2 <= 0) return dot(ap, ap);
  const P bp = p - t.b;
  const double d3 = dot(ab, bp), d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return dot(bp, bp);
  const double vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) {
    const P q = ap - (d1 / (d1 - d3)) * ab;
    return dot(q, q);
  }
  const P cp = p - t.c;
  const double d5 = dot(ab, cp), d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return dot(cp, cp);
  const double vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) {
    const P q = ap - (d2 / (d2 - d6)) * ac;
    return dot(q, q);
  }
  const double va = d3 * d6 - d5 * d4;
  if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
    const double w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
    const P q = bp - w * (t.c - t.b);
    return dot(q, q);
  }
  const double denominator = va + vb + vc;
  const P q = ap - (vb / denominator) * ab - (vc / denominator) * ac;
  return dot(q, q);
}

struct Box {
  double lo[3], hi[3];
};

double box_squared_distance(const P& p, const Box& box) {
  const double c[3] = {p.x, p.y, p.z};
  double s = 0;
  for (int k = 0; k < 3; ++k) {
    const double g = c[k] < box.lo[k] ? box.lo[k] - c[k] : (c[k] > box.hi[k] ? c[k] - box.hi[k] : 0.0);
    s += g * g;
  }
  return s;
}

// Median-split bounding-volume hierarchy over the triangles of one mesh (leaf size <= 4).
class Hierarchy {
 public:
  explicit Hierarchy(std::vector<T3> triangles) : tris_(std::move(triangles)) {
    order_.resize(tris_.size());
    std::iota(order_.begin(), order_.end(), std::size_t{0});
    std::vector<P> centroid(tris_.size());
    for (std::size_t i = 0; i < tris_.size(); ++i) {
      const T3& t = tris_[i];
      centroid[i] = {(t.a.x + t.b.x + t.c.x) / 3, (t.a.y + t.b.y + t.c.y) / 3, (t.a.z + t.b.z + t.c.z) / 3};
    }
    nodes_.reserve(2 * tris_.size() / 2 + 8);
    struct Work {
      std::size_t node, begin, end;
    };
    nodes_.push_back({});
    std::vector<Work> stack{{0, 0, tris_.size()}};
    while (!stack.empty()) {
      const Work w = stack.back();
      stack.pop_back();
      Node& node = nodes_[w.node];
      Box box{{1e300, 1e300, 1e300}, {-1e300, -1e300, -1e300}};
      Box cbox = box;
      for (std::size_t i = w.begin; i < w.end; ++i) {
        const T3& t = tris_[order_[i]];
        for (const P* q : {&t.a, &t.b, &t.c}) {
          const double c[3] = {q->x, q->y, q->z};
          for (int k = 0; k < 3; ++k) {
            box.lo[k] = std::min(box.lo[k], c[k]);
            box.hi[k] = std::max(box.hi[k], c[k]);
          }
        }
        const P& m = centroid[order_[i]];
        const double c[3] = {m.x, m.y, m.z};
        for (int k = 0; k < 3; ++k) {
          cbox.lo[k] = std::min(cbox.lo[k], c[k]);
          cbox.hi[k] = std::max(cbox.hi[k], c[k]);
        }
      }
      node.box = box;
      if (w.end - w.begin <= 4) {
        node.first = w.begin;
        node.count = w.end - w.begin;
        continue;
      }
      int axis = 0;
      for (int k = 1; k < 3; ++k) {
        if (cbox.hi[k] - cbox.lo[k] > cbox.hi[axis] - cbox.lo[axis]) axis = k;
      }
      const std::size_t half = w.begin + (w.end - w.begin) / 2;
      std::nth_element(order_.begin() + static_cast<std::ptrdiff_t>(w.begin),
                       order_.begin() + static_cast<std::ptrdiff_t>(half),
                       order_.begin() + static_cast<std::ptrdiff_t>(w.end), [&](std::size_t x, std::size_t y) {
                         const P& a = centroid[x];
                         const P& b = centroid[y];
                         return (axis == 0 ? a.x : axis == 1 ? a.y : a.z) < (axis == 0 ? b.x : axis == 1 ? b.y : b.z);
                       });
      const std::size_t left = nodes_.size();
      nodes_.push_back({});
      nodes_.push_back({});
      nodes_[w.node].left = left;
      nodes_[w.node].count = 0;
      stack.push_back({left, w.begin, half});
      stack.push_back({left + 1, half, w.end});
    }
  }

  const std::vector<T3>& triangles() const { return tris_; }

  // Exact (up to rounding) nearest triangle: boxes are pruned only when their distance is >= the best.
  double nearest_squared(const P& p, std::size_t& best_index, std::size_t& evaluations) const {
    double best = std::numeric_limits<double>::infinity();
    best_index = 0;
    std::size_t stack[128];
    std::size_t top = 0;
    stack[top++] = 0;
    while (top) {
      const Node& node = nodes_[stack[--top]];
      if (box_squared_distance(p, node.box) >= best) continue;
      if (node.count) {
        for (std::size_t i = node.first; i < node.first + node.count; ++i) {
          const double d = squared_distance(p, tris_[order_[i]]);
          ++evaluations;
          if (d < best) {
            best = d;
            best_index = order_[i];
          }
        }
        continue;
      }
      const double dl = box_squared_distance(p, nodes_[node.left].box);
      const double dr = box_squared_distance(p, nodes_[node.left + 1].box);
      if (top + 2 > 128) validation_failure("BVH_DEPTH", "The bounding-volume hierarchy is too deep");
      if (dl < dr) {
        stack[top++] = node.left + 1;
        stack[top++] = node.left;
      } else {
        stack[top++] = node.left;
        stack[top++] = node.left + 1;
      }
    }
    return best;
  }

  // min over triangles S of max_i d(corner_i, S)^2, seeded with an initial value.
  double minmax_squared(const P* corners, double seed, std::size_t& evaluations) const {
    double best = seed;
    std::size_t stack[128];
    std::size_t top = 0;
    stack[top++] = 0;
    auto bound = [&](const Box& box) {
      return std::max({box_squared_distance(corners[0], box), box_squared_distance(corners[1], box),
                       box_squared_distance(corners[2], box)});
    };
    while (top) {
      const Node& node = nodes_[stack[--top]];
      if (bound(node.box) >= best) continue;
      if (node.count) {
        for (std::size_t i = node.first; i < node.first + node.count; ++i) {
          const T3& s = tris_[order_[i]];
          double m = squared_distance(corners[0], s);
          if (m >= best) continue;
          m = std::max(m, squared_distance(corners[1], s));
          if (m >= best) continue;
          m = std::max(m, squared_distance(corners[2], s));
          evaluations += 3;
          best = std::min(best, m);
        }
        continue;
      }
      const double bl = bound(nodes_[node.left].box), br = bound(nodes_[node.left + 1].box);
      if (top + 2 > 128) validation_failure("BVH_DEPTH", "The bounding-volume hierarchy is too deep");
      if (bl < br) {
        stack[top++] = node.left + 1;
        stack[top++] = node.left;
      } else {
        stack[top++] = node.left;
        stack[top++] = node.left + 1;
      }
    }
    return best;
  }

 private:
  struct Node {
    Box box{};
    std::size_t left = 0, first = 0, count = 0;
  };
  std::vector<T3> tris_;
  std::vector<std::size_t> order_;
  std::vector<Node> nodes_;
};

std::vector<T3> triangles_checked(const RawMesh& raw, const std::string& context) {
  if (raw.faces.empty()) validation_failure("MESH_EMPTY", context + " has no faces");
  if (raw.faces.size() > kMaximumCertifiedDistanceFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", context + " exceeds the certified face limit");
  }
  std::vector<T3> result;
  result.reserve(raw.faces.size());
  for (const auto& face : raw.faces) {
    if (face.size() != 3) validation_failure("MESH_NOT_TRIANGULATED", context + " must be triangulated");
    if (face[0] == face[1] || face[1] == face[2] || face[0] == face[2]) {
      validation_failure("DEGENERATE_FACE", context + " has a face repeating a vertex");
    }
    const T3 t{to_p(raw.vertices.at(face[0])), to_p(raw.vertices.at(face[1])), to_p(raw.vertices.at(face[2]))};
    const P u = t.b - t.a, v = t.c - t.a;
    const P n = {u.y * v.z - u.z * v.y, u.z * v.x - u.x * v.z, u.x * v.y - u.y * v.x};
    const double scale = norm(u) * norm(v);
    // A component above 1e-12 |u||v| cannot be a rounding artefact of an exactly zero cross product;
    // otherwise decide exactly in rationals.
    const double largest = std::max({std::fabs(n.x), std::fabs(n.y), std::fabs(n.z)});
    if (!(largest > 1e-12 * scale) && batch2::tri_degenerate(batch2::make_tri(raw, face))) {
      validation_failure("DEGENERATE_FACE", context + " has a zero-area face");
    }
    result.push_back(t);
  }
  return result;
}

double diagonal(const RawMesh& raw) {
  double lo[3], hi[3];
  for (int k = 0; k < 3; ++k) lo[k] = hi[k] = raw.vertices.at(0)[k];
  for (const auto& v : raw.vertices) {
    for (int k = 0; k < 3; ++k) {
      lo[k] = std::min(lo[k], v[k]);
      hi[k] = std::max(hi[k], v[k]);
    }
  }
  return std::sqrt((hi[0] - lo[0]) * (hi[0] - lo[0]) + (hi[1] - lo[1]) * (hi[1] - lo[1]) +
                   (hi[2] - lo[2]) * (hi[2] - lo[2]));
}

struct Direction {
  double vertex_lower = 0;  // max over the face corners of d(v, other)
  double upper = 0;         // max over closed sub-triangles of their bound
  P witness{};              // point attaining the largest distance found in this direction
  double witness_distance = -1;
  std::size_t roots = 0;
};

struct Refiner {
  const Hierarchy& other;
  double width;
  double& lower;  // shared symmetric lower bound
  std::size_t& nodes;
  std::size_t node_budget;
  std::size_t& evaluations;
  Direction& direction;

  struct Item {
    P v[3];
    double d2[3];
    std::size_t near[3];
    unsigned depth;
  };

  void note(const P& p, double d2) {
    const double d = std::sqrt(d2);
    if (d > direction.witness_distance) {
      direction.witness_distance = d;
      direction.witness = p;
    }
    lower = std::max(lower, d);
  }

  void run(const Item& root) {
    std::vector<Item> stack{root};
    while (!stack.empty()) {
      const Item item = stack.back();
      stack.pop_back();
      if (++nodes > node_budget) {
        validation_failure("BRACKET_NOT_CONVERGED", "The certified Hausdorff bracket exceeded its node budget");
      }
      const double e01 = norm(item.v[0] - item.v[1]), e12 = norm(item.v[1] - item.v[2]),
                   e20 = norm(item.v[2] - item.v[0]);
      const double d0 = std::sqrt(item.d2[0]), d1 = std::sqrt(item.d2[1]), d2 = std::sqrt(item.d2[2]);
      double bound = std::min({d0 + std::max(e01, e20), d1 + std::max(e01, e12), d2 + std::max(e12, e20)});
      if (bound > lower + width) {
        // Seed with the nearest triangles of the corners, then search all triangles exactly.
        double seed = std::numeric_limits<double>::infinity();
        const auto& tris = other.triangles();
        for (int i = 0; i < 3; ++i) {
          const T3& s = tris[item.near[i]];
          seed = std::min(seed, std::max({squared_distance(item.v[0], s), squared_distance(item.v[1], s),
                                          squared_distance(item.v[2], s)}));
        }
        evaluations += 9;
        bound = std::min(bound, std::sqrt(other.minmax_squared(item.v, seed, evaluations)));
      }
      if (bound <= lower + width) {
        direction.upper = std::max(direction.upper, bound);
        continue;
      }
      if (item.depth >= 48) {
        validation_failure("BRACKET_NOT_CONVERGED", "The certified Hausdorff bracket exceeded its depth limit");
      }
      const P m[3] = {mid(item.v[0], item.v[1]), mid(item.v[1], item.v[2]), mid(item.v[2], item.v[0])};
      double md2[3];
      std::size_t mn[3];
      for (int i = 0; i < 3; ++i) {
        md2[i] = other.nearest_squared(m[i], mn[i], evaluations);
        note(m[i], md2[i]);
      }
      const unsigned depth = item.depth + 1;
      stack.push_back({{item.v[0], m[0], m[2]}, {item.d2[0], md2[0], md2[2]}, {item.near[0], mn[0], mn[2]}, depth});
      stack.push_back({{m[0], item.v[1], m[1]}, {md2[0], item.d2[1], md2[1]}, {mn[0], item.near[1], mn[1]}, depth});
      stack.push_back({{m[2], m[1], item.v[2]}, {md2[2], md2[1], item.d2[2]}, {mn[2], mn[1], item.near[2]}, depth});
      stack.push_back({{m[0], m[1], m[2]}, {md2[0], md2[1], md2[2]}, {mn[0], mn[1], mn[2]}, depth});
    }
  }
};

struct VertexData {
  std::vector<double> d2;
  std::vector<std::size_t> near;
};

VertexData vertex_distances(const RawMesh& mesh, const Hierarchy& other, std::size_t& evaluations,
                            Direction& direction, double& lower) {
  VertexData data;
  data.d2.assign(mesh.vertices.size(), -1);
  data.near.assign(mesh.vertices.size(), 0);
  for (const auto& face : mesh.faces) {
    for (std::size_t index : face) {
      if (data.d2[index] >= 0) continue;
      const P p = to_p(mesh.vertices[index]);
      data.d2[index] = other.nearest_squared(p, data.near[index], evaluations);
      const double d = std::sqrt(data.d2[index]);
      direction.vertex_lower = std::max(direction.vertex_lower, d);
      if (d > direction.witness_distance) {
        direction.witness_distance = d;
        direction.witness = p;
      }
      lower = std::max(lower, d);
    }
  }
  return data;
}

double brute_force(const P& p, const std::vector<T3>& triangles) {
  double best = std::numeric_limits<double>::infinity();
  for (const T3& t : triangles) best = std::min(best, squared_distance(p, t));
  return std::sqrt(best);
}

// Exact rational distance of p to the mesh, evaluated on every triangle within eps of the floating minimum.
double exact_distance(const P& p, const RawMesh& mesh, const std::vector<T3>& triangles, double eps) {
  const double approximate = brute_force(p, triangles);
  const double limit = (approximate + eps) * (approximate + eps);
  const auto point = batch2::vec(V3{p.x, p.y, p.z});
  bool first = true;
  Q best = 0;
  for (std::size_t i = 0; i < triangles.size(); ++i) {
    if (squared_distance(p, triangles[i]) > limit) continue;
    const auto& face = mesh.faces[i];
    const Q d = squared_distance_point_triangle(point, batch2::vec(mesh.vertices[face[0]]),
                                                batch2::vec(mesh.vertices[face[1]]),
                                                batch2::vec(mesh.vertices[face[2]]));
    if (first || d < best) best = d;
    first = false;
  }
  if (first) validation_failure("EXACT_RECHECK_FAILED", "No triangle lies within the margin of the floating minimum");
  return std::sqrt(best.get_d());
}

}  // namespace

CertifiedHausdorff certified_symmetric_hausdorff(const RawMesh& reference, const RawMesh& candidate,
                                                 double error_bound, double relative_tolerance,
                                                 double relative_width, std::size_t node_budget) {
  CertifiedHausdorff out;
  const Hierarchy tree_r(triangles_checked(reference, "The reference mesh"));
  const Hierarchy tree_c(triangles_checked(candidate, "The candidate mesh"));
  const double diag = std::max(diagonal(reference), diagonal(candidate));
  out.rounding_margin = relative_tolerance * (1 + diag);
  out.width = std::min(relative_width * diag, error_bound / 2);
  double lower = 0;
  Direction forward, backward;  // forward: reference -> candidate
  const auto vr = vertex_distances(reference, tree_c, out.distance_evaluations, forward, lower);
  const auto vc = vertex_distances(candidate, tree_r, out.distance_evaluations, backward, lower);
  out.vertex_lower = lower;

  auto refine = [&](const RawMesh& mesh, const VertexData& data, const Hierarchy& other, Direction& direction) {
    Refiner refiner{other, out.width, lower, out.nodes, node_budget, out.distance_evaluations, direction};
    for (const auto& face : mesh.faces) {
      Refiner::Item root{};
      for (int i = 0; i < 3; ++i) {
        root.v[i] = to_p(mesh.vertices[face[i]]);
        root.d2[i] = data.d2[face[i]];
        root.near[i] = data.near[face[i]];
      }
      root.depth = 0;
      refiner.run(root);
      ++direction.roots;
    }
  };
  refine(reference, vr, tree_c, forward);
  refine(candidate, vc, tree_r, backward);
  out.lower = lower;
  out.upper = std::max({lower, forward.upper, backward.upper});
  out.forward_lower = forward.witness_distance;
  out.backward_lower = backward.witness_distance;
  out.forward_upper = std::max(forward.upper, forward.witness_distance);
  out.backward_upper = std::max(backward.upper, backward.witness_distance);

  // Independent cross-check of the hierarchy queries against an exhaustive scan.
  auto crosscheck = [&](const RawMesh& mesh, const Hierarchy& self_tree, const Hierarchy& other, const P& witness,
                        double witness_distance) {
    std::vector<P> points{witness};
    const std::size_t stride = std::max<std::size_t>(1, mesh.vertices.size() / 32);
    for (std::size_t i = 0; i < mesh.vertices.size(); i += stride) points.push_back(to_p(mesh.vertices[i]));
    (void)self_tree;
    for (std::size_t k = 0; k < points.size(); ++k) {
      std::size_t index = 0, ignored = 0;
      const double fast = std::sqrt(other.nearest_squared(points[k], index, ignored));
      const double slow = brute_force(points[k], other.triangles());
      const double deviation = std::fabs(fast - slow);
      out.crosscheck_max_deviation = std::max(out.crosscheck_max_deviation, deviation);
      if (deviation > out.rounding_margin) {
        validation_failure("BVH_CROSSCHECK_MISMATCH",
                           "A hierarchy distance query disagrees with the exhaustive scan over all triangles");
      }
      if (k == 0 && std::fabs(fast - witness_distance) > out.rounding_margin) {
        validation_failure("BVH_CROSSCHECK_MISMATCH", "The witness distance is not reproduced");
      }
      ++out.crosscheck_points;
    }
  };
  crosscheck(reference, tree_r, tree_c, forward.witness, forward.witness_distance);
  crosscheck(candidate, tree_c, tree_r, backward.witness, backward.witness_distance);

  out.exact_forward_witness = exact_distance(forward.witness, candidate, tree_c.triangles(), out.rounding_margin);
  out.exact_backward_witness = exact_distance(backward.witness, reference, tree_r.triangles(), out.rounding_margin);
  if (std::fabs(out.exact_forward_witness - forward.witness_distance) > out.rounding_margin ||
      std::fabs(out.exact_backward_witness - backward.witness_distance) > out.rounding_margin) {
    validation_failure("EXACT_RECHECK_FAILED", "The exact rational witness distance disagrees with the bracket");
  }
  out.forward_roots = forward.roots;
  out.backward_roots = backward.roots;
  return out;
}

}  // namespace cgal_master::batch5
