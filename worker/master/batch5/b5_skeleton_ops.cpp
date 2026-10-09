// Producers wrapping CGAL 6.2.1 straight skeletons and skeleton offsets (7.12.05, 7.12.06):
// create_interior_straight_skeleton_2, create_exterior_straight_skeleton_2,
// create_interior_skeleton_and_offset_polygons_2 and create_exterior_skeleton_and_offset_polygons_2 on
// Epick. Results are checked by b5_skeleton_validators.cpp, which includes no CGAL header.

#include "b5_common.h"

#include "../batch2/b2_registry.h"
#include "../wave_c/wave_c_common.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygon_2.h>
#include <CGAL/Straight_skeleton_2.h>
#include <CGAL/create_offset_polygons_2.h>
#include <CGAL/create_straight_skeleton_2.h>

#include <algorithm>
#include <cmath>
#include <map>
#include <set>

namespace cgal_master::batch5 {
namespace {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using Point = Epick::Point_2;
using Polygon = CGAL::Polygon_2<Epick>;
using Ss = CGAL::Straight_skeleton_2<Epick>;
constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";

using batch2::geometry_frame;
using batch2::pinfo;
using query_ops::precondition;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::write_report;

struct Source {
  std::vector<V2> outer;
  std::vector<std::vector<V2>> holes;
};

// Reads the polygon, rejects non simple input and normalizes the orientation (outer counter-clockwise,
// holes clockwise) with exact predicates. The coordinates are not changed.
Source load(const ArtifactInput& input, bool allow_holes) {
  const auto data = wave_c::read_polygon_with_holes2(input);
  std::size_t total = data.outer.size();
  for (const auto& hole : data.holes) total += hole.size();
  if (total > kMaximumSkeletonVertices) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "At most 64 polygon vertices are supported");
  }
  Source source;
  source.outer.assign(data.outer.begin(), data.outer.end());
  for (const auto& hole : data.holes) source.holes.emplace_back(hole.begin(), hole.end());
  if (!allow_holes && !source.holes.empty()) {
    precondition("HOLES_NOT_SUPPORTED", "The exterior construction takes a simple polygon without holes");
  }
  auto outer = ring_from_doubles(source.outer);
  std::vector<Ring> holes;
  for (const auto& hole : source.holes) holes.push_back(ring_from_doubles(hole));
  check_polygon_with_holes(outer, holes, false);
  if (ring_signed_area(outer) < 0) std::reverse(source.outer.begin(), source.outer.end());
  for (std::size_t i = 0; i < holes.size(); ++i) {
    if (ring_signed_area(holes[i]) > 0) std::reverse(source.holes[i].begin(), source.holes[i].end());
  }
  return source;
}

Polygon to_polygon(const std::vector<V2>& ring) {
  Polygon polygon;
  for (const auto& p : ring) polygon.push_back(Point(p[0], p[1]));
  return polygon;
}

Json ring_json(const Polygon& polygon) {
  Json ring = Json::array();
  for (auto it = polygon.vertices_begin(); it != polygon.vertices_end(); ++it) {
    ring.push_back(Json::array({it->x(), it->y()}));
  }
  return ring;
}

std::string area_unit(const std::string& unit) { return unit + "^2"; }

Json skeleton_report(const Request& request, const Ss& skeleton, const std::string& kind) {
  std::map<Ss::Vertex_const_handle, std::size_t> ids;
  Json vertices = Json::array();
  for (auto v = skeleton.vertices_begin(); v != skeleton.vertices_end(); ++v) {
    ids[v] = vertices.size();
    vertices.push_back({{"id", vertices.size()}, {"x", v->point().x()}, {"y", v->point().y()},
                        {"time", v->time()}, {"contour", v->is_contour()}});
  }
  Json faces = Json::array();
  for (auto f = skeleton.faces_begin(); f != skeleton.faces_end(); ++f) {
    Json ring = Json::array();
    Json edge = Json::array();
    auto start = f->halfedge();
    auto h = start;
    std::size_t contour_edges = 0;
    do {
      ring.push_back(ids.at(h->vertex()));
      if (!h->is_bisector()) {
        ++contour_edges;
        edge = Json::array({ids.at(h->opposite()->vertex()), ids.at(h->vertex())});
      }
      h = h->next();
    } while (h != start);
    if (contour_edges != 1) {
      throw WorkerError("CGAL_ERROR", "SKELETON_FACE_INVALID", "A skeleton face must have exactly one contour edge");
    }
    faces.push_back({{"edge", std::move(edge)}, {"vertices", std::move(ring)}});
  }
  std::set<std::pair<std::size_t, std::size_t>> unique;
  for (auto h = skeleton.halfedges_begin(); h != skeleton.halfedges_end(); ++h) {
    if (!h->is_bisector()) continue;
    const std::size_t a = ids.at(h->opposite()->vertex()), b = ids.at(h->vertex());
    unique.insert({std::min(a, b), std::max(a, b)});
  }
  Json bisectors = Json::array();
  for (const auto& [a, b] : unique) bisectors.push_back(Json::array({a, b}));
  const std::size_t vertex_count = vertices.size(), face_count = faces.size(), bisector_count = bisectors.size();
  const std::string unit = request.inputs[0].unit;
  Json frame_flag = kind == "exterior" ? Json(true) : Json(false);
  return geometry_frame(request, "straight_skeleton", request.parameters, {{"polygon_sha256", request.inputs[0].sha256}},
                        {{"vertex_count", vertex_count}, {"face_count", face_count}, {"bisector_count", bisector_count}},
                        {{"skeleton_kind", kind}, {"length_unit", unit}, {"area_unit", area_unit(unit)},
                         {"includes_outer_frame", frame_flag}, {"vertices", std::move(vertices)},
                         {"faces", std::move(faces)}, {"bisectors", std::move(bisectors)}});
}

Json finish(const Request& request, const Json& report, Json metrics) {
  auto output = write_report(request, "GeometryQueryReport", report);
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json interior_skeleton_op(const Request& request) {
  require_inputs(request, 1, "polygon.straight_skeleton.interior");
  require_parameter_names(request, {});
  const auto source = load(request.inputs[0], true);
  const Polygon outer = to_polygon(source.outer);
  std::vector<Polygon> holes;
  for (const auto& hole : source.holes) holes.push_back(to_polygon(hole));
  const auto skeleton = CGAL::create_interior_straight_skeleton_2(outer.vertices_begin(), outer.vertices_end(),
                                                                  holes.begin(), holes.end(), Epick());
  if (!skeleton) throw WorkerError("CGAL_ERROR", "SKELETON_FAILED", "CGAL could not construct the straight skeleton");
  const Json report = skeleton_report(request, *skeleton, "interior");
  return finish(request, report, {{"vertex_count", report["summary"]["vertex_count"]}, {"face_count", report["summary"]["face_count"]},
                                  {"algorithm", "CGAL::create_interior_straight_skeleton_2"}});
}

Json exterior_skeleton_op(const Request& request) {
  require_inputs(request, 1, "polygon.straight_skeleton.exterior");
  require_parameter_names(request, {"max_offset"});
  const double max_offset = positive_length(request.parameters.at("max_offset"), "max_offset", request.inputs[0].unit);
  const auto source = load(request.inputs[0], false);
  const Polygon outer = to_polygon(source.outer);
  const auto skeleton = CGAL::create_exterior_straight_skeleton_2(max_offset, outer, Epick());
  if (!skeleton) throw WorkerError("CGAL_ERROR", "SKELETON_FAILED", "CGAL could not construct the exterior straight skeleton");
  const Json report = skeleton_report(request, *skeleton, "exterior");
  return finish(request, report, {{"vertex_count", report["summary"]["vertex_count"]}, {"face_count", report["summary"]["face_count"]},
                                  {"algorithm", "CGAL::create_exterior_straight_skeleton_2"}});
}

Json offset_report(const Request& request, const std::string& kind, double offset,
                   const std::vector<std::shared_ptr<Polygon>>& rings) {
  Json list = Json::array();
  for (const auto& ring : rings) list.push_back({{"points", ring_json(*ring)}});
  const std::string unit = request.inputs[0].unit;
  return geometry_frame(request, "polygon_offset", request.parameters, {{"polygon_sha256", request.inputs[0].sha256}},
                        {{"ring_count", rings.size()}},
                        {{"offset_kind", kind}, {"offset", offset}, {"length_unit", unit}, {"area_unit", area_unit(unit)},
                         {"rings", std::move(list)}});
}

Json interior_offset_op(const Request& request) {
  require_inputs(request, 1, "polygon.offset.interior");
  require_parameter_names(request, {"offset"});
  const double offset = positive_length(request.parameters.at("offset"), "offset", request.inputs[0].unit);
  const auto source = load(request.inputs[0], true);
  const Polygon outer = to_polygon(source.outer);
  std::vector<Polygon> holes;
  for (const auto& hole : source.holes) holes.push_back(to_polygon(hole));
  const auto rings = CGAL::create_interior_skeleton_and_offset_polygons_2<Polygon>(
      offset, outer, holes.begin(), holes.end(), Epick(), Epick());
  const Json report = offset_report(request, "interior", offset, rings);
  return finish(request, report, {{"ring_count", rings.size()}, {"empty", rings.empty()},
                                  {"algorithm", "CGAL::create_interior_skeleton_and_offset_polygons_2"}});
}

Json exterior_offset_op(const Request& request) {
  require_inputs(request, 1, "polygon.offset.exterior");
  require_parameter_names(request, {"offset"});
  const double offset = positive_length(request.parameters.at("offset"), "offset", request.inputs[0].unit);
  const auto source = load(request.inputs[0], false);
  const Polygon outer = to_polygon(source.outer);
  auto rings = CGAL::create_exterior_skeleton_and_offset_polygons_2<Polygon>(offset, outer, Epick(), Epick());
  // The raw result starts with the offset of the outer frame that CGAL adds around the polygon; like
  // CGAL's own *_with_holes variant, drop it (it is the first element, and the largest ring).
  if (rings.empty()) throw WorkerError("CGAL_ERROR", "OFFSET_FAILED", "The exterior offset returned no frame ring");
  std::size_t largest = 0;
  double largest_area = -1;
  for (std::size_t i = 0; i < rings.size(); ++i) {
    const double area = std::fabs(CGAL::to_double(rings[i]->area()));
    if (area > largest_area) {
      largest_area = area;
      largest = i;
    }
  }
  if (largest != 0) throw WorkerError("CGAL_ERROR", "OFFSET_FAILED", "The frame ring is not the first exterior offset ring");
  rings.erase(rings.begin());
  const Json report = offset_report(request, "exterior", offset, rings);
  return finish(request, report, {{"ring_count", rings.size()}, {"algorithm", "CGAL::create_exterior_skeleton_and_offset_polygons_2"}});
}

}  // namespace

std::vector<OperationDefinition> skeleton_producers() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "polygon.straight_skeleton.interior", {"PolygonWithHoles2"}, "GeometryQueryReport", "analysis",
      interior_skeleton_op, {"Straight_skeleton_2"}, kEpickName,
      pinfo("polygon.validate.straight_skeleton", {}, {"polygon"},
            {{"source_header", "CGAL/create_straight_skeleton_2.h"}, {"maximum_input_vertices", kMaximumSkeletonVertices}})));
  result.push_back(query_definition(
      "polygon.straight_skeleton.exterior", {"PolygonWithHoles2"}, "GeometryQueryReport", "analysis",
      exterior_skeleton_op, {"Straight_skeleton_2"}, kEpickName,
      pinfo("polygon.validate.straight_skeleton", {"max_offset"}, {"polygon"},
            {{"source_header", "CGAL/create_straight_skeleton_2.h"}, {"maximum_input_vertices", kMaximumSkeletonVertices}})));
  result.push_back(query_definition(
      "polygon.offset.interior", {"PolygonWithHoles2"}, "GeometryQueryReport", "analysis", interior_offset_op,
      {"Straight_skeleton_2"}, kEpickName,
      pinfo("polygon.validate.offset", {"offset"}, {"polygon"},
            {{"source_header", "CGAL/create_offset_polygons_2.h"}, {"maximum_input_vertices", kMaximumSkeletonVertices}})));
  result.push_back(query_definition(
      "polygon.offset.exterior", {"PolygonWithHoles2"}, "GeometryQueryReport", "analysis", exterior_offset_op,
      {"Straight_skeleton_2"}, kEpickName,
      pinfo("polygon.validate.offset", {"offset"}, {"polygon"},
            {{"source_header", "CGAL/create_offset_polygons_2.h"}, {"maximum_input_vertices", kMaximumSkeletonVertices}})));
  return result;
}

}  // namespace cgal_master::batch5
