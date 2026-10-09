// Producers wrapping CGAL 6.2.1 Alpha_shape_2, Alpha_shape_3 and Fixed_alpha_shape_3 (7.13.02).
// Results are checked by the CGAL-free validators in b4_validators_alpha.cpp.

#include "b4_common.h"

#include <CGAL/Alpha_shape_2.h>
#include <CGAL/Alpha_shape_3.h>
#include <CGAL/Alpha_shape_cell_base_3.h>
#include <CGAL/Alpha_shape_face_base_2.h>
#include <CGAL/Alpha_shape_vertex_base_2.h>
#include <CGAL/Alpha_shape_vertex_base_3.h>
#include <CGAL/Delaunay_triangulation_2.h>
#include <CGAL/Delaunay_triangulation_3.h>
#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Fixed_alpha_shape_3.h>
#include <CGAL/Fixed_alpha_shape_cell_base_3.h>
#include <CGAL/Fixed_alpha_shape_vertex_base_3.h>

#include <algorithm>
#include <cmath>
#include <map>
#include <set>

namespace cgal_master::batch4 {
namespace {

using Epeck = CGAL::Exact_predicates_exact_constructions_kernel;
constexpr const char* kEpeckName = "CGAL::Exact_predicates_exact_constructions_kernel";

using batch2::geometry_frame;
using batch2::pinfo;
using query_ops::precondition;
using query_ops::read_points2;
using query_ops::read_points3;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::write_report;

using Tuple = std::vector<std::size_t>;

double alpha_parameter(const Request& request) {
  const auto& value = request.parameters.at("alpha");
  if (!value.is_number() || value.is_boolean() || !std::isfinite(value.get<double>()) || value.get<double>() < 0) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "alpha must be a finite non-negative number (squared artifact unit)");
  }
  return value.get<double>();
}

template <typename Array>
void reject_duplicates(const std::vector<Array>& points) {
  std::set<Array> seen;
  for (const auto& p : points) {
    if (!seen.insert(p).second) precondition("DUPLICATE_POINT", "Input points must be pairwise distinct");
  }
}

Json sorted_json(std::set<Tuple> tuples) {
  Json result = Json::array();
  for (const auto& t : tuples) {
    Json entry = Json::array();
    for (const auto index : t) entry.push_back(index);
    result.push_back(std::move(entry));
  }
  return result;
}

// ---- 2D ------------------------------------------------------------------------------------------

Json alpha_shape_2(const Request& request) {
  require_inputs(request, 1, "shape.alpha_shape_2");
  require_parameter_names(request, {"alpha"});
  const auto points = read_points2(request.inputs[0]);
  if (points.size() < 3 || points.size() > kMaximumAlpha2Points) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_COUNT", "Between 3 and 60 points are supported");
  }
  const double alpha = alpha_parameter(request);
  reject_duplicates(points);

  using Vb = CGAL::Alpha_shape_vertex_base_2<Epeck>;
  using Fb = CGAL::Alpha_shape_face_base_2<Epeck>;
  using Tds = CGAL::Triangulation_data_structure_2<Vb, Fb>;
  using Dt = CGAL::Delaunay_triangulation_2<Epeck, Tds>;
  using Alpha = CGAL::Alpha_shape_2<Dt>;
  std::vector<Epeck::Point_2> input;
  std::map<V2, std::size_t> index;
  for (std::size_t i = 0; i < points.size(); ++i) {
    input.emplace_back(points[i][0], points[i][1]);
    index[points[i]] = i;
  }
  Alpha shape(input.begin(), input.end(), Epeck::FT(0), Alpha::REGULARIZED);
  if (shape.dimension() != 2) precondition("ALL_COLLINEAR", "The points must not all be collinear");
  // A point on the circumcircle of a Delaunay triangle makes the triangulation (and the alpha complex
  // at a tie) depend on insertion order: reject.
  for (auto f = shape.finite_faces_begin(); f != shape.finite_faces_end(); ++f) {
    for (const auto& q : input) {
      const auto side = Epeck().side_of_oriented_circle_2_object()(f->vertex(0)->point(), f->vertex(1)->point(), f->vertex(2)->point(), q);
      if (side == CGAL::ON_ORIENTED_BOUNDARY && q != f->vertex(0)->point() && q != f->vertex(1)->point() &&
          q != f->vertex(2)->point()) {
        precondition("DEGENERATE_COCIRCULAR", "Four input points lie on one circle");
      }
    }
  }
  shape.set_alpha(Epeck::FT(alpha));
  auto id = [&](Dt::Vertex_handle v) {
    return index.at(V2{CGAL::to_double(v->point().x()), CGAL::to_double(v->point().y())});
  };
  std::set<Tuple> interior, regular;
  for (auto f = shape.finite_faces_begin(); f != shape.finite_faces_end(); ++f) {
    if (shape.classify(f) != Alpha::INTERIOR) continue;
    Tuple t{id(f->vertex(0)), id(f->vertex(1)), id(f->vertex(2))};
    std::sort(t.begin(), t.end());
    interior.insert(t);
  }
  for (auto e = shape.finite_edges_begin(); e != shape.finite_edges_end(); ++e) {
    if (shape.classify(*e) != Alpha::REGULAR) continue;
    Tuple t{id(e->first->vertex((e->second + 1) % 3)), id(e->first->vertex((e->second + 2) % 3))};
    std::sort(t.begin(), t.end());
    regular.insert(t);
  }
  Json report = geometry_frame(request, "alpha_shape_2", {{"alpha", request.parameters.at("alpha")}},
                               {{"points_sha256", request.inputs[0].sha256}},
                               {{"interior_triangle_count", interior.size()}, {"regular_edge_count", regular.size()}},
                               {{"interior_triangles", sorted_json(interior)}, {"regular_edges", sorted_json(regular)},
                                {"alpha_unit", request.inputs[0].unit + "^2"}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"input_point_count", points.size()}, {"interior_triangle_count", interior.size()},
               {"regular_edge_count", regular.size()}, {"algorithm", "CGAL::Alpha_shape_2"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 3D ------------------------------------------------------------------------------------------

template <typename Shape, typename Dt>
Json report_3(const Request& request, const std::string& kind, const std::string& algorithm,
              const std::vector<V3>& points, Shape& shape) {
  std::map<V3, std::size_t> index;
  for (std::size_t i = 0; i < points.size(); ++i) index[points[i]] = i;
  auto id = [&](typename Dt::Vertex_handle v) {
    return index.at(V3{CGAL::to_double(v->point().x()), CGAL::to_double(v->point().y()),
                       CGAL::to_double(v->point().z())});
  };
  std::set<Tuple> interior, regular;
  for (auto c = shape.finite_cells_begin(); c != shape.finite_cells_end(); ++c) {
    if (shape.classify(c) != Shape::INTERIOR) continue;
    Tuple t;
    for (int k = 0; k < 4; ++k) t.push_back(id(c->vertex(k)));
    std::sort(t.begin(), t.end());
    interior.insert(t);
  }
  for (auto f = shape.finite_facets_begin(); f != shape.finite_facets_end(); ++f) {
    if (shape.classify(*f) != Shape::REGULAR) continue;
    Tuple t;
    for (int k = 0; k < 4; ++k) if (k != f->second) t.push_back(id(f->first->vertex(k)));
    std::sort(t.begin(), t.end());
    regular.insert(t);
  }
  Json report = geometry_frame(request, kind, {{"alpha", request.parameters.at("alpha")}},
                               {{"points_sha256", request.inputs[0].sha256}},
                               {{"interior_cell_count", interior.size()}, {"regular_facet_count", regular.size()}},
                               {{"interior_cells", sorted_json(interior)}, {"regular_facets", sorted_json(regular)},
                                {"alpha_unit", request.inputs[0].unit + "^2"}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"input_point_count", points.size()}, {"interior_cell_count", interior.size()},
               {"regular_facet_count", regular.size()}, {"algorithm", algorithm}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

std::vector<V3> read_alpha_points_3(const Request& request, const std::string& operation) {
  require_inputs(request, 1, operation);
  require_parameter_names(request, {"alpha"});
  const auto points = read_points3(request.inputs[0]);
  if (points.size() < 4 || points.size() > kMaximumAlpha3Points) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_COUNT", "Between 4 and 24 points are supported");
  }
  reject_duplicates(points);
  return points;
}

template <typename Dt>
void require_nondegenerate_3(const Dt& dt, const std::vector<Epeck::Point_3>& input) {
  if (dt.dimension() != 3) precondition("ALL_COPLANAR", "The points must not all be coplanar");
  for (auto c = dt.finite_cells_begin(); c != dt.finite_cells_end(); ++c) {
    for (const auto& q : input) {
      if (q == c->vertex(0)->point() || q == c->vertex(1)->point() || q == c->vertex(2)->point() ||
          q == c->vertex(3)->point()) {
        continue;
      }
      if (Epeck().side_of_oriented_sphere_3_object()(c->vertex(0)->point(), c->vertex(1)->point(), c->vertex(2)->point(),
                                     c->vertex(3)->point(), q) == CGAL::ON_ORIENTED_BOUNDARY) {
        precondition("DEGENERATE_COSPHERICAL", "Five input points lie on one sphere");
      }
    }
  }
}

Json alpha_shape_3(const Request& request) {
  const auto points = read_alpha_points_3(request, "shape.alpha_shape_3");
  const double alpha = alpha_parameter(request);
  using Vb = CGAL::Alpha_shape_vertex_base_3<Epeck>;
  using Cb = CGAL::Alpha_shape_cell_base_3<Epeck>;
  using Tds = CGAL::Triangulation_data_structure_3<Vb, Cb>;
  using Dt = CGAL::Delaunay_triangulation_3<Epeck, Tds>;
  using Alpha = CGAL::Alpha_shape_3<Dt>;
  std::vector<Epeck::Point_3> input;
  for (const auto& p : points) input.emplace_back(p[0], p[1], p[2]);
  Alpha shape(input.begin(), input.end(), Epeck::FT(0), Alpha::REGULARIZED);
  require_nondegenerate_3(shape, input);
  shape.set_alpha(Epeck::FT(alpha));
  return report_3<Alpha, Dt>(request, "alpha_shape_3", "CGAL::Alpha_shape_3", points, shape);
}

Json fixed_alpha_shape_3(const Request& request) {
  const auto points = read_alpha_points_3(request, "shape.fixed_alpha_shape_3");
  const double alpha = alpha_parameter(request);
  using Vb = CGAL::Fixed_alpha_shape_vertex_base_3<Epeck>;
  using Cb = CGAL::Fixed_alpha_shape_cell_base_3<Epeck>;
  using Tds = CGAL::Triangulation_data_structure_3<Vb, Cb>;
  using Dt = CGAL::Delaunay_triangulation_3<Epeck, Tds>;
  using Alpha = CGAL::Fixed_alpha_shape_3<Dt>;
  std::vector<Epeck::Point_3> input;
  for (const auto& p : points) input.emplace_back(p[0], p[1], p[2]);
  Alpha shape(input.begin(), input.end(), Epeck::FT(alpha));
  require_nondegenerate_3(shape, input);
  return report_3<Alpha, Dt>(request, "alpha_shape_3", "CGAL::Fixed_alpha_shape_3", points, shape);
}

}  // namespace

std::vector<OperationDefinition> alpha_producers() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "shape.alpha_shape_2", {"PointSet2"}, "GeometryQueryReport", "analysis", alpha_shape_2, {"Alpha_shapes_2"},
      kEpeckName,
      pinfo("shape.validate.alpha_shape_2", {"alpha"}, {"points"},
            {{"source_header", "CGAL/Alpha_shape_2.h"}, {"maximum_input_points", kMaximumAlpha2Points}})));
  result.push_back(query_definition(
      "shape.alpha_shape_3", {"PointSet3"}, "GeometryQueryReport", "analysis", alpha_shape_3, {"Alpha_shapes_3"},
      kEpeckName,
      pinfo("shape.validate.alpha_shape_3", {"alpha"}, {"points"},
            {{"source_header", "CGAL/Alpha_shape_3.h"}, {"maximum_input_points", kMaximumAlpha3Points}})));
  result.push_back(query_definition(
      "shape.fixed_alpha_shape_3", {"PointSet3"}, "GeometryQueryReport", "analysis", fixed_alpha_shape_3,
      {"Alpha_shapes_3"}, kEpeckName,
      pinfo("shape.validate.alpha_shape_3", {"alpha"}, {"points"},
            {{"source_header", "CGAL/Fixed_alpha_shape_3.h"}, {"maximum_input_points", kMaximumAlpha3Points}})));
  return result;
}

}  // namespace cgal_master::batch4
