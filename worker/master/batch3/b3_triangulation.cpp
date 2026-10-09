// Producers wrapping CGAL 6.2.1 Regular_triangulation_2 / Regular_triangulation_3 (7.11.03) and the
// Voronoi_diagram_2 adaptor of Delaunay_triangulation_2 (7.11.05). Results are checked by the
// CGAL-free validators in b3_validators_triangulation.cpp.

#include "b3_common.h"

#include "../wave_c/wave_c_common.h"

#include <CGAL/Delaunay_triangulation_2.h>
#include <CGAL/Delaunay_triangulation_adaptation_policies_2.h>
#include <CGAL/Delaunay_triangulation_adaptation_traits_2.h>
#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Regular_triangulation_2.h>
#include <CGAL/Regular_triangulation_3.h>
#include <CGAL/Voronoi_diagram_2.h>

#include <algorithm>
#include <map>
#include <set>

namespace cgal_master::batch3 {
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

std::string exact_text(const Epeck::FT& value) { return wave_c::exact_string(value); }

template <typename Array>
void reject_duplicates(const std::vector<Array>& points) {
  std::set<Array> seen;
  for (const auto& p : points) {
    if (!seen.insert(p).second) precondition("DUPLICATE_POINT", "Input points must be pairwise distinct");
  }
}

// ---- 7.11.03 ---------------------------------------------------------------------------------

Json regular_2(const Request& request) {
  require_inputs(request, 1, "triangulation.regular_2");
  require_parameter_names(request, {"weights"});
  const auto points = read_points2(request.inputs[0]);
  if (points.size() < 3 || points.size() > kMaximumWeightedPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_COUNT", "Between 3 and 400 weighted points are supported");
  }
  const auto weights = weights_parameter(request, points.size());
  reject_duplicates(points);
  bool rank_two = false;
  for (std::size_t i = 2; i < points.size() && !rank_two; ++i) {
    rank_two = !CGAL::collinear(Epeck::Point_2(points[0][0], points[0][1]),
                                Epeck::Point_2(points[1][0], points[1][1]),
                                Epeck::Point_2(points[i][0], points[i][1]));
  }
  if (!rank_two) precondition("ALL_COLLINEAR", "The points must not all be collinear");
  using Rt = CGAL::Regular_triangulation_2<Epeck>;
  Rt triangulation;
  for (std::size_t i = 0; i < points.size(); ++i) {
    triangulation.insert(Rt::Weighted_point(Epeck::Point_2(points[i][0], points[i][1]), Epeck::FT(weights[i])));
  }
  std::map<V2, std::size_t> index;
  for (std::size_t i = 0; i < points.size(); ++i) index[points[i]] = i;
  auto id = [&](Rt::Vertex_handle v) {
    return index.at(V2{CGAL::to_double(v->point().point().x()), CGAL::to_double(v->point().point().y())});
  };
  std::set<std::size_t> visible;
  for (auto v = triangulation.finite_vertices_begin(); v != triangulation.finite_vertices_end(); ++v) {
    visible.insert(id(v));
  }
  std::vector<std::array<std::size_t, 3>> triangles;
  for (auto f = triangulation.finite_faces_begin(); f != triangulation.finite_faces_end(); ++f) {
    std::array<std::size_t, 3> t{id(f->vertex(0)), id(f->vertex(1)), id(f->vertex(2))};
    std::rotate(t.begin(), std::min_element(t.begin(), t.end()), t.end());
    triangles.push_back(t);
  }
  std::sort(triangles.begin(), triangles.end());
  Json vertices = Json::array(), hidden = Json::array(), faces = Json::array();
  for (std::size_t i = 0; i < points.size(); ++i) (visible.count(i) ? vertices : hidden).push_back(i);
  for (const auto& t : triangles) faces.push_back(Json::array({t[0], t[1], t[2]}));
  Json report = geometry_frame(request, "regular_triangulation_2", {{"weights", request.parameters.at("weights")}},
                               {{"points_sha256", request.inputs[0].sha256}},
                               {{"vertex_count", visible.size()}, {"hidden_count", hidden.size()},
                                {"triangle_count", triangles.size()}},
                               {{"vertices", vertices}, {"hidden", hidden}, {"triangles", faces}, {"weight_unit", request.inputs[0].unit + "^2"}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"input_point_count", points.size()}, {"vertex_count", visible.size()},
               {"hidden_count", hidden.size()}, {"triangle_count", triangles.size()},
               {"algorithm", "CGAL::Regular_triangulation_2"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json regular_3(const Request& request) {
  require_inputs(request, 1, "triangulation.regular_3");
  require_parameter_names(request, {"weights"});
  const auto points = read_points3(request.inputs[0]);
  if (points.size() < 4 || points.size() > kMaximumWeightedPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_COUNT", "Between 4 and 400 weighted points are supported");
  }
  const auto weights = weights_parameter(request, points.size());
  reject_duplicates(points);
  bool rank_three = false;
  for (std::size_t i = 3; i < points.size() && !rank_three; ++i) {
    rank_three = !CGAL::coplanar(Epeck::Point_3(points[0][0], points[0][1], points[0][2]),
                                 Epeck::Point_3(points[1][0], points[1][1], points[1][2]),
                                 Epeck::Point_3(points[2][0], points[2][1], points[2][2]),
                                 Epeck::Point_3(points[i][0], points[i][1], points[i][2]));
  }
  if (!rank_three) precondition("ALL_COPLANAR", "The first points must not all be coplanar");
  using Rt = CGAL::Regular_triangulation_3<Epeck>;
  Rt triangulation;
  for (std::size_t i = 0; i < points.size(); ++i) {
    triangulation.insert(Epeck::Weighted_point_3(Epeck::Point_3(points[i][0], points[i][1], points[i][2]),
                                              Epeck::FT(weights[i])));
  }
  if (triangulation.dimension() != 3) {
    precondition("DEGENERATE_TRIANGULATION", "The regular triangulation is not 3-dimensional");
  }
  std::map<V3, std::size_t> index;
  for (std::size_t i = 0; i < points.size(); ++i) index[points[i]] = i;
  auto id = [&](Rt::Vertex_handle v) {
    const auto& p = v->point().point();
    return index.at(V3{CGAL::to_double(p.x()), CGAL::to_double(p.y()), CGAL::to_double(p.z())});
  };
  std::set<std::size_t> visible;
  for (auto v = triangulation.finite_vertices_begin(); v != triangulation.finite_vertices_end(); ++v) {
    visible.insert(id(v));
  }
  std::vector<std::array<std::size_t, 4>> cells;
  for (auto c = triangulation.finite_cells_begin(); c != triangulation.finite_cells_end(); ++c) {
    std::array<std::size_t, 4> t{id(c->vertex(0)), id(c->vertex(1)), id(c->vertex(2)), id(c->vertex(3))};
    // Positive orientation in the validator's convention: det(b-a, c-a, d-a) > 0.
    const auto p = [&](std::size_t k) {
      return batch2::Vec{Q(points[t[k]][0]), Q(points[t[k]][1]), Q(points[t[k]][2])};
    };
    if (batch2::dot(batch2::cross(p(1) - p(0), p(2) - p(0)), p(3) - p(0)) < 0) std::swap(t[0], t[1]);
    cells.push_back(t);
  }
  std::sort(cells.begin(), cells.end(), [](const auto& l, const auto& r) {
    auto a = l, b = r;
    std::sort(a.begin(), a.end());
    std::sort(b.begin(), b.end());
    return a < b;
  });
  Json vertices = Json::array(), hidden = Json::array(), tetrahedra = Json::array();
  for (std::size_t i = 0; i < points.size(); ++i) (visible.count(i) ? vertices : hidden).push_back(i);
  for (const auto& t : cells) tetrahedra.push_back(Json::array({t[0], t[1], t[2], t[3]}));
  Json report = geometry_frame(request, "regular_triangulation_3", {{"weights", request.parameters.at("weights")}},
                               {{"points_sha256", request.inputs[0].sha256}},
                               {{"vertex_count", visible.size()}, {"hidden_count", hidden.size()},
                                {"tetrahedron_count", cells.size()}},
                               {{"vertices", vertices}, {"hidden", hidden}, {"tetrahedra", tetrahedra}, {"weight_unit", request.inputs[0].unit + "^2"}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"input_point_count", points.size()}, {"vertex_count", visible.size()},
               {"hidden_count", hidden.size()}, {"tetrahedron_count", cells.size()},
               {"algorithm", "CGAL::Regular_triangulation_3"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.11.05 ---------------------------------------------------------------------------------

struct PointLess {
  bool operator()(const Epeck::Point_2& a, const Epeck::Point_2& b) const {
    return a.x() != b.x() ? a.x() < b.x() : a.y() < b.y();
  }
};

Json voronoi_dual(const Request& request) {
  require_inputs(request, 1, "triangulation.voronoi_dual");
  require_parameter_names(request, {});
  const auto sites = read_points2(request.inputs[0]);
  if (sites.size() < 3 || sites.size() > kMaximumWeightedPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_COUNT", "Between 3 and 400 sites are supported");
  }
  reject_duplicates(sites);
  bool rank_two = false;
  for (std::size_t i = 2; i < sites.size() && !rank_two; ++i) {
    rank_two = !CGAL::collinear(Epeck::Point_2(sites[0][0], sites[0][1]), Epeck::Point_2(sites[1][0], sites[1][1]),
                                Epeck::Point_2(sites[i][0], sites[i][1]));
  }
  if (!rank_two) precondition("ALL_COLLINEAR", "The sites must not all be collinear");
  using DT = CGAL::Delaunay_triangulation_2<Epeck>;
  using AT = CGAL::Delaunay_triangulation_adaptation_traits_2<DT>;
  using AP = CGAL::Delaunay_triangulation_caching_degeneracy_removal_policy_2<DT>;
  using VD = CGAL::Voronoi_diagram_2<DT, AT, AP>;
  VD diagram;
  for (const auto& s : sites) diagram.insert(Epeck::Point_2(s[0], s[1]));
  std::map<V2, std::size_t> index;
  for (std::size_t i = 0; i < sites.size(); ++i) index[sites[i]] = i;
  auto site_id = [&](const VD::Face_handle& f) {
    const auto& p = f->dual()->point();
    return index.at(V2{CGAL::to_double(p.x()), CGAL::to_double(p.y())});
  };
  std::map<Epeck::Point_2, std::size_t, PointLess> vertex_ids;
  for (auto e = diagram.edges_begin(); e != diagram.edges_end(); ++e) {
    if (e->has_source()) vertex_ids.emplace(e->source()->point(), 0);
    if (e->has_target()) vertex_ids.emplace(e->target()->point(), 0);
  }
  Json vertices = Json::array();
  std::size_t next = 0;
  for (auto& item : vertex_ids) {
    item.second = next++;
    vertices.push_back(Json::array({exact_text(item.first.x()), exact_text(item.first.y())}));
  }
  std::vector<std::array<long long, 4>> rows;
  for (auto e = diagram.edges_begin(); e != diagram.edges_end(); ++e) {
    VD::Halfedge_handle h = e->twin()->twin();
    std::size_t a = site_id(h->face()), b = site_id(h->twin()->face());
    // With i < j the vector d = rot90(p_j - p_i) has p_i on its left, so the halfedge of cell i runs
    // from the "lo" end (parameter -infinity side) to the "hi" end.
    if (a > b) {
      h = h->twin();
      std::swap(a, b);
    }
    long long lo = -1, hi = -1;
    if (h->has_source()) lo = static_cast<long long>(vertex_ids.at(h->source()->point()));
    if (h->has_target()) hi = static_cast<long long>(vertex_ids.at(h->target()->point()));
    rows.push_back({static_cast<long long>(a), static_cast<long long>(b), lo, hi});
  }
  std::sort(rows.begin(), rows.end());
  std::set<std::size_t> unbounded;
  Json edges = Json::array();
  for (const auto& r : rows) {
    edges.push_back({{"sites", Json::array({r[0], r[1]})},
                     {"lo", r[2] < 0 ? Json(nullptr) : Json(r[2])},
                     {"hi", r[3] < 0 ? Json(nullptr) : Json(r[3])}});
    if (r[2] < 0 || r[3] < 0) {
      unbounded.insert(static_cast<std::size_t>(r[0]));
      unbounded.insert(static_cast<std::size_t>(r[1]));
    }
  }
  const std::size_t cells = diagram.number_of_faces();
  Json report = geometry_frame(request, "voronoi_diagram_2", Json::object(), {{"sites_sha256", request.inputs[0].sha256}},
                               {{"cell_count", cells}, {"unbounded_cell_count", unbounded.size()},
                                {"vertex_count", vertex_ids.size()}, {"edge_count", rows.size()}},
                               {{"vertices", vertices}, {"edges", edges}, {"cell_count", cells},
                                {"unbounded_cell_count", unbounded.size()}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"site_count", sites.size()}, {"cell_count", cells}, {"unbounded_cell_count", unbounded.size()},
               {"vertex_count", vertex_ids.size()}, {"edge_count", rows.size()},
               {"algorithm", "CGAL::Voronoi_diagram_2"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> triangulation_producers() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "triangulation.regular_2", {"PointSet2"}, "GeometryQueryReport", "analysis", regular_2, {"Triangulation_2"},
      kEpeckName,
      pinfo("triangulation.validate.regular_2", {"weights"}, {"points"},
            {{"source_header", "CGAL/Regular_triangulation_2.h"}, {"maximum_input_points", kMaximumWeightedPoints}})));
  result.push_back(query_definition(
      "triangulation.regular_3", {"PointSet3"}, "GeometryQueryReport", "analysis", regular_3, {"Triangulation_3"},
      kEpeckName,
      pinfo("triangulation.validate.regular_3", {"weights"}, {"points"},
            {{"source_header", "CGAL/Regular_triangulation_3.h"}, {"maximum_input_points", kMaximumWeightedPoints}})));
  result.push_back(query_definition(
      "triangulation.voronoi_dual", {"PointSet2"}, "GeometryQueryReport", "analysis", voronoi_dual,
      {"Voronoi_diagram_2", "Triangulation_2"}, kEpeckName,
      pinfo("triangulation.validate.voronoi_dual", {}, {"sites"},
            {{"source_header", "CGAL/Voronoi_diagram_2.h"}, {"maximum_input_points", kMaximumWeightedPoints}})));
  return result;
}

}  // namespace cgal_master::batch3
