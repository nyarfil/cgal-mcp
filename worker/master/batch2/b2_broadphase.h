#pragma once
// Conservative broad phase for the exact validators. No CGAL header.
//
// The validators decide every property with GMP rationals; this file only selects which
// pairs reach those exact tests. A pair is skipped only when the closed binary64 bounding
// boxes of the two primitives are disjoint, in which case the primitives cannot share a
// point. The boxes of triangles are the exact min/max of the binary64 input coordinates
// (the same test as boxes_overlap); boxes of rational points are padded outward by two
// ulps of the rounded value, so they contain the exact point. The verdict of a validator is
// therefore the same as with the all-pairs loop; only the running time changes.

#include "b2_geometry.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <numeric>
#include <vector>

namespace cgal_master::batch2 {

struct Box {
  double lo[3];
  double hi[3];
};

inline Box empty_box() {
  const double inf = std::numeric_limits<double>::infinity();
  return {{inf, inf, inf}, {-inf, -inf, -inf}};
}

inline void extend(Box& box, const Box& other) {
  for (int axis = 0; axis < 3; ++axis) {
    box.lo[axis] = std::min(box.lo[axis], other.lo[axis]);
    box.hi[axis] = std::max(box.hi[axis], other.hi[axis]);
  }
}

inline bool overlap(const Box& a, const Box& b) {
  for (int axis = 0; axis < 3; ++axis) {
    if (a.hi[axis] < b.lo[axis] || b.hi[axis] < a.lo[axis]) return false;
  }
  return true;
}

inline Box box_of(const Tri& t) {
  Box box = empty_box();
  for (int i = 0; i < 3; ++i) {
    for (int axis = 0; axis < 3; ++axis) {
      box.lo[axis] = std::min(box.lo[axis], t.raw[i][axis]);
      box.hi[axis] = std::max(box.hi[axis], t.raw[i][axis]);
    }
  }
  return box;
}

// Interval containing the exact rational: mpq_class::get_d truncates, so the exact value is
// within one ulp of the result; two steps outward leave a margin.
inline void rational_interval(const Q& value, double& lo, double& hi) {
  const double d = value.get_d();
  const double inf = std::numeric_limits<double>::infinity();
  lo = std::nextafter(std::nextafter(d, -inf), -inf);
  hi = std::nextafter(std::nextafter(d, inf), inf);
}

inline Box box_of(const Vec& p) {
  Box box;
  rational_interval(p.x, box.lo[0], box.hi[0]);
  rational_interval(p.y, box.lo[1], box.hi[1]);
  rational_interval(p.z, box.lo[2], box.hi[2]);
  return box;
}

inline Box box_of(const Vec& a, const Vec& b) {
  Box box = box_of(a);
  extend(box, box_of(b));
  return box;
}

// Static bounding-volume hierarchy over a fixed list of boxes.
class BoxTree {
 public:
  BoxTree() = default;
  explicit BoxTree(std::vector<Box> boxes) : boxes_(std::move(boxes)) {
    order_.resize(boxes_.size());
    std::iota(order_.begin(), order_.end(), std::size_t{0});
    if (!boxes_.empty()) {
      nodes_.reserve(2 * boxes_.size() / kLeafSize + 2);
      build(0, boxes_.size());
    }
  }

  std::size_t size() const { return boxes_.size(); }
  const Box& box(std::size_t index) const { return boxes_[index]; }

  // Calls visit(index) for every stored box that overlaps `query` (closed boxes).
  template <typename Visit>
  void query(const Box& query, Visit&& visit) const {
    if (nodes_.empty()) return;
    std::vector<std::size_t> stack{0};
    while (!stack.empty()) {
      const Node& node = nodes_[stack.back()];
      stack.pop_back();
      if (!overlap(node.box, query)) continue;
      if (node.left == kNone) {
        for (std::size_t k = node.begin; k < node.end; ++k) {
          if (overlap(boxes_[order_[k]], query)) visit(order_[k]);
        }
      } else {
        stack.push_back(node.left);
        stack.push_back(node.right);
      }
    }
  }

  // Sorted indices of the stored boxes overlapping `query`.
  std::vector<std::size_t> overlapping(const Box& box) const {
    std::vector<std::size_t> result;
    query(box, [&](std::size_t index) { result.push_back(index); });
    std::sort(result.begin(), result.end());
    return result;
  }

 private:
  static constexpr std::size_t kNone = static_cast<std::size_t>(-1);
  static constexpr std::size_t kLeafSize = 8;
  struct Node {
    Box box;
    std::size_t left = kNone, right = kNone, begin = 0, end = 0;
  };

  std::size_t build(std::size_t begin, std::size_t end) {
    const std::size_t id = nodes_.size();
    nodes_.push_back({});
    Box bound = empty_box();
    for (std::size_t k = begin; k < end; ++k) extend(bound, boxes_[order_[k]]);
    nodes_[id].box = bound;
    nodes_[id].begin = begin;
    nodes_[id].end = end;
    if (end - begin <= kLeafSize) return id;
    int axis = 0;
    double widest = -1;
    for (int a = 0; a < 3; ++a) {
      const double width = bound.hi[a] - bound.lo[a];
      if (width > widest) {
        widest = width;
        axis = a;
      }
    }
    const std::size_t middle = begin + (end - begin) / 2;
    std::nth_element(order_.begin() + static_cast<std::ptrdiff_t>(begin),
                     order_.begin() + static_cast<std::ptrdiff_t>(middle),
                     order_.begin() + static_cast<std::ptrdiff_t>(end), [&](std::size_t a, std::size_t b) {
                       return boxes_[a].lo[axis] + boxes_[a].hi[axis] < boxes_[b].lo[axis] + boxes_[b].hi[axis];
                     });
    const std::size_t left = build(begin, middle);
    const std::size_t right = build(middle, end);
    nodes_[id].left = left;
    nodes_[id].right = right;
    return id;
  }

  std::vector<Box> boxes_;
  std::vector<std::size_t> order_;
  std::vector<Node> nodes_;
};

inline BoxTree tree_of(const std::vector<Tri>& tris) {
  std::vector<Box> boxes;
  boxes.reserve(tris.size());
  for (const auto& t : tris) boxes.push_back(box_of(t));
  return BoxTree(std::move(boxes));
}

// Calls visit(i, j), i < j, for every pair of `subset` members whose boxes overlap.
template <typename Visit>
void overlapping_pairs(const std::vector<Tri>& tris, const std::vector<std::size_t>& subset, Visit&& visit) {
  if (subset.size() <= 16) {
    for (std::size_t i = 0; i < subset.size(); ++i) {
      for (std::size_t j = i + 1; j < subset.size(); ++j) {
        if (boxes_overlap(tris[subset[i]], tris[subset[j]])) visit(subset[i], subset[j]);
      }
    }
    return;
  }
  std::vector<Box> boxes;
  boxes.reserve(subset.size());
  for (const auto index : subset) boxes.push_back(box_of(tris[index]));
  const BoxTree tree(boxes);
  for (std::size_t i = 0; i < subset.size(); ++i) {
    tree.query(boxes[i], [&](std::size_t j) {
      if (i < j) visit(subset[i], subset[j]);
    });
  }
}

}  // namespace cgal_master::batch2
