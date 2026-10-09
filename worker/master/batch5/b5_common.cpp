// Batch-5 exact helpers (GMP rationals). No CGAL header: shared by producers (input checks only)
// and by the independent validators.

#include "b5_common.h"

#include <cmath>
#include <set>

namespace cgal_master::batch5 {

using batch2::cross;
using batch2::dot;
using query_ops::precondition;
using query_ops::validation_failure;
using Pt = std::array<Q, 2>;

double positive_length(const Json& value, const std::string& name, const std::string& unit) {
  if (!value.is_object() || value.size() != 2 || !value.contains("value") || !value.contains("unit") ||
      !value.at("unit").is_string() || !value.at("value").is_number() || value.at("value").is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", name + " must be a TypedLength {value, unit}");
  }
  if (value.at("unit").get<std::string>() != unit) {
    throw WorkerError("TYPE_ERROR", "UNIT_MISMATCH", name + " must be normalized to the artifact unit");
  }
  const double result = value.at("value").get<double>();
  if (!std::isfinite(result) || result <= 0) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", name + " must be finite and strictly positive");
  }
  return result;
}

namespace {
std::size_t bounded_integer(const Json& object, const char* key, std::size_t minimum, std::size_t maximum) {
  const auto& value = object.at(key);
  if (!value.is_number_integer() || value.is_boolean() || value.get<long long>() < static_cast<long long>(minimum) ||
      value.get<long long>() > static_cast<long long>(maximum)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string("sampling.") + key + " must be an integer in [" + std::to_string(minimum) + "," +
                          std::to_string(maximum) + "]");
  }
  return static_cast<std::size_t>(value.get<long long>());
}
}  // namespace

SamplingSpec parse_sampling(const Json& value, const std::string& unit) {
  auto bad = [](const std::string& message) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "sampling " + message);
  };
  if (!value.is_object() || !value.contains("method") || !value.at("method").is_string() ||
      !value.contains("include_vertices") || !value.at("include_vertices").is_boolean()) {
    bad("must be an object with method and include_vertices");
  }
  SamplingSpec spec;
  spec.include_vertices = value.at("include_vertices").get<bool>();
  const std::string method = value.at("method").get<std::string>();
  std::set<std::string> allowed{"method", "include_vertices"};
  if (method == "grid") {
    allowed.insert("grid_spacing");
    if (!value.contains("grid_spacing")) bad("grid method needs grid_spacing");
    spec.grid = true;
    spec.grid_spacing = positive_length(value.at("grid_spacing"), "sampling.grid_spacing", unit);
  } else if (method == "random_uniform") {
    for (const char* key : {"random_seed", "points_on_faces", "points_on_edges"}) {
      allowed.insert(key);
      if (!value.contains(key)) bad(std::string("random_uniform method needs ") + key);
    }
    spec.seed = bounded_integer(value, "random_seed", 0, 2147483647);
    spec.points_on_faces = bounded_integer(value, "points_on_faces", 1, kMaximumSamplePoints);
    spec.points_on_edges = bounded_integer(value, "points_on_edges", 1, kMaximumSamplePoints);
  } else {
    bad("method must be grid or random_uniform");
  }
  for (const auto& item : value.items()) {
    if (!allowed.count(item.key())) bad("has an unsupported key " + item.key());
  }
  return spec;
}

Q squared_distance_point_triangle(const Vec& p, const Vec& a, const Vec& b, const Vec& c) {
  const Vec ab = b - a, ac = c - a, ap = p - a;
  const Q d1 = dot(ab, ap), d2 = dot(ac, ap);
  Vec closest = a;
  auto finish = [&](const Vec& q) {
    const Vec d = p - q;
    return dot(d, d);
  };
  if (d1 <= 0 && d2 <= 0) return finish(a);
  const Vec bp = p - b;
  const Q d3 = dot(ab, bp), d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return finish(b);
  const Q vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) return finish(a + (d1 / (d1 - d3)) * ab);
  const Vec cp = p - c;
  const Q d5 = dot(ab, cp), d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return finish(c);
  const Q vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) return finish(a + (d2 / (d2 - d6)) * ac);
  const Q va = d3 * d6 - d5 * d4;
  if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
    return finish(b + ((d4 - d3) / ((d4 - d3) + (d5 - d6))) * (c - b));
  }
  const Q denominator = va + vb + vc;
  closest = a + (vb / denominator) * ab + (vc / denominator) * ac;
  return finish(closest);
}

Ring ring_from_doubles(const std::vector<V2>& points) {
  Ring ring;
  for (const auto& p : points) ring.points.push_back({query_ops::exact_of(p[0]), query_ops::exact_of(p[1])});
  return ring;
}

Q ring_signed_area(const Ring& ring) {
  Q twice = 0;
  const std::size_t n = ring.points.size();
  for (std::size_t i = 0; i < n; ++i) {
    const auto& a = ring.points[i];
    const auto& b = ring.points[(i + 1) % n];
    twice += a[0] * b[1] - a[1] * b[0];
  }
  return twice / 2;
}

namespace {
int orient(const Pt& a, const Pt& b, const Pt& c) {
  const Q value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  return value > 0 ? 1 : (value < 0 ? -1 : 0);
}
bool on_segment(const Pt& a, const Pt& b, const Pt& p) {
  if (orient(a, b, p) != 0) return false;
  return std::min(a[0], b[0]) <= p[0] && p[0] <= std::max(a[0], b[0]) && std::min(a[1], b[1]) <= p[1] &&
         p[1] <= std::max(a[1], b[1]);
}
}  // namespace

bool segments_touch(const Pt& a, const Pt& b, const Pt& c, const Pt& d) {
  const int o1 = orient(a, b, c), o2 = orient(a, b, d), o3 = orient(c, d, a), o4 = orient(c, d, b);
  if (o1 != o2 && o3 != o4) return true;
  return on_segment(a, b, c) || on_segment(a, b, d) || on_segment(c, d, a) || on_segment(c, d, b);
}

int point_in_ring(const Pt& p, const Ring& ring) {
  const std::size_t n = ring.points.size();
  bool inside = false;
  for (std::size_t i = 0; i < n; ++i) {
    const Pt& a = ring.points[i];
    const Pt& b = ring.points[(i + 1) % n];
    if (on_segment(a, b, p)) return 0;
    if ((a[1] > p[1]) != (b[1] > p[1])) {
      // x coordinate of the crossing compared with p[0], evaluated exactly.
      const Q crossing = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1]);
      if (p[0] < crossing) inside = !inside;
    }
  }
  return inside ? 1 : -1;
}

void check_polygon_with_holes(const Ring& outer, const std::vector<Ring>& holes, bool as_validator) {
  auto fail = [&](const char* code, const char* message) {
    if (as_validator) validation_failure(code, message);
    precondition(code, message);
  };
  std::vector<const Ring*> rings{&outer};
  for (const auto& hole : holes) rings.push_back(&hole);
  for (const Ring* ring : rings) {
    const std::size_t n = ring->points.size();
    if (n < 3) fail("POLYGON_TOO_SMALL", "Every ring needs at least three vertices");
    if (ring_signed_area(*ring) == 0) fail("POLYGON_ZERO_AREA", "Every ring must have non-zero area");
    for (std::size_t i = 0; i < n; ++i) {
      const Pt& a = ring->points[i];
      const Pt& b = ring->points[(i + 1) % n];
      if (a == b) fail("POLYGON_NOT_SIMPLE", "A ring repeats a vertex");
      for (std::size_t j = i + 1; j < n; ++j) {
        const Pt& c = ring->points[j];
        const Pt& d = ring->points[(j + 1) % n];
        const bool adjacent = (j == i + 1) || (i == 0 && j + 1 == n);
        if (!adjacent) {
          if (segments_touch(a, b, c, d)) fail("POLYGON_NOT_SIMPLE", "A ring is not simple");
        } else {
          // Adjacent edges may only share their common endpoint: reject a fold-back overlap.
          const Pt& shared = (j == i + 1) ? b : a;
          const Pt& other1 = (j == i + 1) ? a : b;
          const Pt& other2 = (j == i + 1) ? d : c;
          if (orient(other1, shared, other2) == 0) {
            const Q along = (other1[0] - shared[0]) * (other2[0] - shared[0]) +
                            (other1[1] - shared[1]) * (other2[1] - shared[1]);
            if (along > 0) fail("POLYGON_NOT_SIMPLE", "A ring folds back on itself");
          }
        }
      }
    }
  }
  for (std::size_t r = 0; r < rings.size(); ++r) {
    for (std::size_t s = r + 1; s < rings.size(); ++s) {
      const std::size_t n = rings[r]->points.size(), m = rings[s]->points.size();
      for (std::size_t i = 0; i < n; ++i) {
        for (std::size_t j = 0; j < m; ++j) {
          if (segments_touch(rings[r]->points[i], rings[r]->points[(i + 1) % n], rings[s]->points[j],
                             rings[s]->points[(j + 1) % m])) {
            fail("POLYGON_RINGS_TOUCH", "Outer boundary and holes must be pairwise disjoint");
          }
        }
      }
    }
  }
  for (const auto& hole : holes) {
    if (point_in_ring(hole.points[0], outer) != 1) fail("HOLE_OUTSIDE", "Every hole must lie inside the outer boundary");
  }
  for (std::size_t r = 0; r < holes.size(); ++r) {
    for (std::size_t s = 0; s < holes.size(); ++s) {
      if (r != s && point_in_ring(holes[s].points[0], holes[r]) != -1) {
        fail("HOLE_NESTED", "Holes must not be nested");
      }
    }
  }
}

}  // namespace cgal_master::batch5
