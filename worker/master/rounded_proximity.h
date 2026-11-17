#pragma once
// Shared pieces of the "rounded output" contract (mesh.boolean.rounded and the rounded plane /
// refinement operations): the exact EPECK result keeps its combinatorics, every coordinate is
// replaced by a neighbouring binary64 value, and a validator accepts the candidate only within a
// stated absolute tolerance of an exact replay.

#include "geometry.h"
#include "protocol.h"

#include <CGAL/AABB_traits_3.h>
#include <CGAL/AABB_tree.h>
#include <CGAL/AABB_triangle_primitive_3.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <vector>

namespace cgal_master::rounded {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;

inline std::array<Point, 3> face_points(const Mesh& mesh, Mesh::Face_index face) {
  const auto h = mesh.halfedge(face);
  return {mesh.point(mesh.source(h)), mesh.point(mesh.target(h)), mesh.point(mesh.target(mesh.next(h)))};
}

// Finds, for a query point, a triangle of `mesh` close to it with a binary64 search structure and
// certifies the distance to that witness exactly. The search only chooses the witness; the bound is
// an exact rational comparison, so an accepted point is provably within the tolerance of the surface.
class SurfaceProximity {
 public:
  explicit SurfaceProximity(const Mesh& mesh) {
    for (const auto face : mesh.faces()) {
      const auto points = face_points(mesh, face);
      const Epick::Triangle_3 triangle(approximate(points[0]), approximate(points[1]), approximate(points[2]));
      if (triangle.is_degenerate()) continue;  // cannot be a search primitive; never a certificate
      approximate_.push_back(triangle);
      exact_.emplace_back(points[0], points[1], points[2]);
    }
    if (approximate_.empty()) {
      throw WorkerError("VALIDATION_FAILED", "ROUNDED_NO_SEARCH_TRIANGLE",
                        "No triangle of the surface is usable for the proximity search");
    }
    tree_.insert(approximate_.begin(), approximate_.end());
    tree_.build();
    tree_.accelerate_distance_queries();
  }

  // Exact squared distance from `point` to the witness triangle chosen for it.
  Kernel::FT witness_squared_distance(const Point& point) const {
    const auto closest = tree_.closest_point_and_primitive(approximate(point));
    const auto index = static_cast<std::size_t>(closest.second - approximate_.begin());
    return CGAL::squared_distance(point, exact_[index]);
  }

 private:
  static Epick::Point_3 approximate(const Point& point) {
    return Epick::Point_3(CGAL::to_double(point.x()), CGAL::to_double(point.y()), CGAL::to_double(point.z()));
  }
  using Iterator = std::vector<Epick::Triangle_3>::const_iterator;
  using Primitive = CGAL::AABB_triangle_primitive_3<Epick, Iterator>;
  using Tree = CGAL::AABB_tree<CGAL::AABB_traits_3<Epick, Primitive>>;
  std::vector<Epick::Triangle_3> approximate_;
  std::vector<Kernel::Triangle_3> exact_;
  Tree tree_;
};

// Largest exact squared distance from a vertex of `samples` to its witness on `surface`.
inline Kernel::FT max_vertex_squared_distance(const Mesh& samples, const SurfaceProximity& surface) {
  Kernel::FT maximum(0);
  for (const auto vertex : samples.vertices()) {
    const auto distance = surface.witness_squared_distance(samples.point(vertex));
    if (distance > maximum) maximum = distance;
  }
  return maximum;
}

inline double approximate_area(const Mesh& mesh) {
  double area = 0;
  for (const auto face : mesh.faces()) {
    const auto points = face_points(mesh, face);
    area += std::sqrt((std::max)(0.0, CGAL::to_double(CGAL::squared_area(points[0], points[1], points[2]))));
  }
  return area;
}

// 2^-40 times the power of two above `largest` (the largest absolute source coordinate): a binary64
// value, so comparisons against it are exact.
inline double tolerance_for_scale(double largest) {
  if (!(largest > 0) || !std::isfinite(largest)) {
    throw WorkerError("PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
                      "The sources have no positive finite coordinate scale");
  }
  return std::ldexp(1.0, std::ilogb(largest) + 1 - 40);
}

inline double largest_coordinate(const Mesh& mesh, double largest = 0) {
  for (const auto vertex : mesh.vertices()) {
    const auto& point = mesh.point(vertex);
    largest = (std::max)({largest, std::abs(CGAL::to_double(point.x())), std::abs(CGAL::to_double(point.y())),
                          std::abs(CGAL::to_double(point.z()))});
  }
  return largest;
}

}  // namespace cgal_master::rounded
