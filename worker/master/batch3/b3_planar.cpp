// Producers wrapping CGAL 6.2.1 Minkowski_sum_2 (7.12.07) and Arrangement_2 (7.12.02, 7.12.03):
// minkowski_sum_2, minkowski_sum_by_reduced_convolution_2, Arrangement_2 insertion, zone() and
// overlay() with a face-overlay traits. Every result is checked by an independent CGAL-free
// validator in b3_validators_planar.cpp.

#include "b3_common.h"

#include "../wave_c/wave_c_common.h"

#include <CGAL/Arr_default_overlay_traits.h>
#include <CGAL/Arr_extended_dcel.h>
#include <CGAL/Arr_overlay_2.h>
#include <CGAL/Arr_segment_traits_2.h>
#include <CGAL/Arrangement_2.h>
#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Polygon_2.h>
#include <CGAL/Polygon_with_holes_2.h>
#include <CGAL/minkowski_sum_2.h>

#include <algorithm>
#include <functional>
#include <iterator>
#include <map>
#include <set>
#include <variant>

namespace cgal_master::batch3 {
namespace {

using Epeck = CGAL::Exact_predicates_exact_constructions_kernel;
constexpr const char* kEpeckName = "CGAL::Exact_predicates_exact_constructions_kernel";
using Polygon = CGAL::Polygon_2<Epeck>;
using PolygonWithHoles = CGAL::Polygon_with_holes_2<Epeck>;

using batch2::geometry_frame;
using batch2::pinfo;
using query_ops::precondition;
using query_ops::read_polygon;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::write_report;

std::string exact_text(const Epeck::FT& value) { return wave_c::exact_string(value); }

Polygon operand(const ArtifactInput& input) {
  const auto raw = read_polygon(input);
  if (raw.size() < 3 || raw.size() > kMaximumMinkowskiVertices) {
    precondition("POLYGON_SIZE", "Each polygon needs 3..16 vertices");
  }
  Polygon polygon;
  for (const auto& v : raw) polygon.push_back(Epeck::Point_2(v[0], v[1]));
  if (!polygon.is_simple()) precondition("POLYGON_NOT_SIMPLE", "Each operand must be a simple polygon");
  if (polygon.is_clockwise_oriented()) polygon.reverse_orientation();
  if (!polygon.is_counterclockwise_oriented()) precondition("POLYGON_ZERO_AREA", "Each operand must have non-zero area");
  return polygon;
}

Json ring_json(const Polygon& ring) {
  Json points = Json::array();
  for (auto it = ring.vertices_begin(); it != ring.vertices_end(); ++it) {
    points.push_back(Json::array({exact_text(it->x()), exact_text(it->y())}));
  }
  return points;
}

// ---- 7.12.07 ---------------------------------------------------------------------------------

Json minkowski_report(const Request& request, const std::string& operation, const std::string& algorithm,
                      const PolygonWithHoles& sum) {
  Json holes = Json::array();
  for (auto it = sum.holes_begin(); it != sum.holes_end(); ++it) holes.push_back(ring_json(*it));
  Json report = geometry_frame(request, "minkowski_sum_2", Json::object(),
                               {{"first_sha256", request.inputs[0].sha256}, {"second_sha256", request.inputs[1].sha256}},
                               {{"hole_count", holes.size()}, {"outer_vertex_count", sum.outer_boundary().size()}},
                               {{"outer", ring_json(sum.outer_boundary())}, {"holes", holes}});
  report["operation"] = operation;
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"hole_count", holes.size()}, {"outer_vertex_count", sum.outer_boundary().size()},
               {"algorithm", algorithm}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json minkowski_sum(const Request& request) {
  require_inputs(request, 2, "polygon.minkowski_sum");
  require_parameter_names(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const Polygon first = operand(request.inputs[0]);
  const Polygon second = operand(request.inputs[1]);
  return minkowski_report(request, "polygon.minkowski_sum", "CGAL::minkowski_sum_2", CGAL::minkowski_sum_2(first, second));
}

Json minkowski_reduced(const Request& request) {
  require_inputs(request, 2, "polygon.minkowski_sum_reduced_convolution");
  require_parameter_names(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const Polygon first = operand(request.inputs[0]);
  const Polygon second = operand(request.inputs[1]);
  return minkowski_report(request, "polygon.minkowski_sum_reduced_convolution",
                          "CGAL::minkowski_sum_by_reduced_convolution_2",
                          CGAL::minkowski_sum_by_reduced_convolution_2(first, second));
}

// ---- 7.12.02 / 7.12.03 -----------------------------------------------------------------------

using Traits = CGAL::Arr_segment_traits_2<Epeck>;
using Segment = Traits::Curve_2;
using Plain = CGAL::Arrangement_2<Traits>;
using Dcel = CGAL::Arr_face_extended_dcel<Traits, int>;
using Labeled = CGAL::Arrangement_2<Traits, Dcel>;
using SumOverlay = CGAL::Arr_face_overlay_traits<Labeled, Labeled, Labeled, std::plus<int>>;

struct PointLess {
  bool operator()(const Epeck::Point_2& a, const Epeck::Point_2& b) const {
    return a.x() != b.x() ? a.x() < b.x() : a.y() < b.y();
  }
};
using VertexIds = std::map<Epeck::Point_2, std::size_t, PointLess>;

template <typename Arr>
VertexIds vertex_ids(const Arr& arr) {
  VertexIds ids;
  for (auto v = arr.vertices_begin(); v != arr.vertices_end(); ++v) ids.emplace(v->point(), 0);
  std::size_t next = 0;
  for (auto& item : ids) item.second = next++;
  return ids;
}

Json vertex_list(const VertexIds& ids) {
  Json result = Json::array();
  for (const auto& item : ids) {
    result.push_back(Json::array({exact_text(item.first.x()), exact_text(item.first.y())}));
  }
  return result;
}

Json rotated(std::vector<std::size_t> ring) {
  std::vector<std::size_t> best = ring;
  for (std::size_t k = 1; k < ring.size(); ++k) {
    std::rotate(ring.begin(), ring.begin() + 1, ring.end());
    if (ring < best) best = ring;
  }
  Json result = Json::array();
  for (const auto id : best) result.push_back(id);
  return result;
}

template <typename Arr>
Json cycle_json(typename Arr::Halfedge_const_handle start, const VertexIds& ids, Epeck::FT& area2) {
  std::vector<std::size_t> ring;
  area2 = 0;
  auto he = start;
  do {
    const auto& p = he->source()->point();
    const auto& q = he->target()->point();
    ring.push_back(ids.at(p));
    area2 += p.x() * q.y() - q.x() * p.y();
    he = he->next();
  } while (he != start);
  return rotated(ring);
}

template <typename Arr>
Json edge_list(const Arr& arr, const VertexIds& ids) {
  std::set<std::pair<std::size_t, std::size_t>> edges;
  for (auto e = arr.edges_begin(); e != arr.edges_end(); ++e) {
    const auto a = ids.at(e->source()->point()), b = ids.at(e->target()->point());
    edges.insert({std::min(a, b), std::max(a, b)});
  }
  Json result = Json::array();
  for (const auto& edge : edges) result.push_back(Json::array({edge.first, edge.second}));
  return result;
}

// Every halfedge cycle is traced once through next(); a counter-clockwise cycle (positive exact
// area) is the outer boundary of the face on its left, every other cycle is a hole of that face.
template <typename Arr>
std::map<const void*, Json> face_records(const Arr& arr, const VertexIds& ids) {
  struct Accumulator {
    Json outer = nullptr;
    std::vector<std::string> holes;
  };
  std::map<const void*, Accumulator> accumulators;
  for (auto f = arr.faces_begin(); f != arr.faces_end(); ++f) accumulators[static_cast<const void*>(&*f)];
  std::set<const void*> visited;
  for (auto he = arr.halfedges_begin(); he != arr.halfedges_end(); ++he) {
    if (visited.count(static_cast<const void*>(&*he))) continue;
    typename Arr::Halfedge_const_handle start = he;
    auto walker = start;
    do {
      visited.insert(static_cast<const void*>(&*walker));
      walker = walker->next();
    } while (walker != start);
    Epeck::FT area2;
    const Json cycle = cycle_json<Arr>(start, ids, area2);
    auto& accumulator = accumulators[static_cast<const void*>(&*start->face())];
    if (area2 > 0) {
      accumulator.outer = cycle;
    } else {
      accumulator.holes.push_back(cycle.dump());
    }
  }
  std::map<const void*, Json> records;
  for (auto& item : accumulators) {
    std::sort(item.second.holes.begin(), item.second.holes.end());
    Json holes = Json::array();
    for (const auto& d : item.second.holes) holes.push_back(Json::parse(d));
    records[item.first] = Json{{"outer", item.second.outer}, {"holes", holes}};
  }
  return records;
}

Json sorted_faces(std::vector<Json> faces) {
  std::sort(faces.begin(), faces.end(), [](const Json& l, const Json& r) { return l.dump() < r.dump(); });
  Json result = Json::array();
  for (auto& f : faces) result.push_back(std::move(f));
  return result;
}

template <typename Arr>
Json arrangement_results(const Arr& arr, bool labelled) {
  const auto ids = vertex_ids(arr);
  std::vector<Json> faces;
  auto records = face_records(arr, ids);
  for (auto f = arr.faces_begin(); f != arr.faces_end(); ++f) {
    Json record = records.at(static_cast<const void*>(&*f));
    if constexpr (std::is_same_v<Arr, Labeled>) {
      if (labelled) record["label"] = f->data();
    }
    faces.push_back(std::move(record));
  }
  return Json{{"vertices", vertex_list(ids)}, {"edges", edge_list(arr, ids)}, {"faces", sorted_faces(std::move(faces))}};
}

std::vector<Segment> read_segments(const ArtifactInput& input, std::size_t minimum) {
  const auto graph = wave_c::read_segment_graph2(input);
  if (graph.segments.size() < minimum || graph.segments.size() > kMaximumArrangementSegments) {
    throw WorkerError("RESOURCE_LIMIT", "SEGMENT_COUNT", "The segment count is outside the supported range");
  }
  std::vector<Segment> result;
  for (const auto& s : graph.segments) {
    const auto& a = graph.points.at(s[0]);
    const auto& b = graph.points.at(s[1]);
    if (a[0] == b[0] && a[1] == b[1]) precondition("ZERO_LENGTH_SEGMENT", "A segment has zero length");
    result.emplace_back(Epeck::Point_2(a[0], a[1]), Epeck::Point_2(b[0], b[1]));
  }
  return result;
}

Json arrangement_build(const Request& request) {
  require_inputs(request, 1, "arrangement.build");
  require_parameter_names(request, {});
  const auto segments = read_segments(request.inputs[0], 1);
  Plain arrangement;
  CGAL::insert(arrangement, segments.begin(), segments.end());
  const auto results = arrangement_results(arrangement, false);
  Json report = geometry_frame(request, "arrangement_2", Json::object(), {{"segments_sha256", request.inputs[0].sha256}},
                               {{"vertex_count", results["vertices"].size()}, {"edge_count", results["edges"].size()},
                                {"face_count", results["faces"].size()}},
                               results);
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"input_segment_count", segments.size()}, {"vertex_count", results["vertices"].size()},
               {"edge_count", results["edges"].size()}, {"face_count", results["faces"].size()},
               {"algorithm", "CGAL::Arrangement_2"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json arrangement_zone(const Request& request) {
  require_inputs(request, 2, "arrangement.zone");
  require_parameter_names(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto segments = read_segments(request.inputs[0], 1);
  const auto curve = read_segments(request.inputs[1], 1);
  if (curve.size() != 1) precondition("QUERY_NOT_ONE_SEGMENT", "The query graph must contain exactly one segment");
  Plain arrangement;
  CGAL::insert(arrangement, segments.begin(), segments.end());
  using Object = std::variant<Plain::Vertex_handle, Plain::Halfedge_handle, Plain::Face_handle>;
  std::vector<Object> zone;
  CGAL::zone(arrangement, curve[0], std::back_inserter(zone));
  const auto ids = vertex_ids(arrangement);
  const auto zone_records = face_records(arrangement, ids);
  std::set<std::size_t> vertices;
  std::set<std::pair<std::size_t, std::size_t>> edges;
  std::map<std::string, Json> faces;
  for (const auto& object : zone) {
    if (const auto* v = std::get_if<Plain::Vertex_handle>(&object)) {
      vertices.insert(ids.at((*v)->point()));
    } else if (const auto* h = std::get_if<Plain::Halfedge_handle>(&object)) {
      const auto a = ids.at((*h)->source()->point()), b = ids.at((*h)->target()->point());
      edges.insert({std::min(a, b), std::max(a, b)});
    } else {
      const auto record = zone_records.at(static_cast<const void*>(&*std::get<Plain::Face_handle>(object)));
      faces.emplace(record.dump(), record);
    }
  }
  Json vertex_json = Json::array(), edge_json = Json::array(), face_json = Json::array();
  for (const auto v : vertices) vertex_json.push_back(v);
  for (const auto& e : edges) edge_json.push_back(Json::array({e.first, e.second}));
  for (const auto& f : faces) face_json.push_back(f.second);
  Json report = geometry_frame(request, "arrangement_zone", Json::object(),
                               {{"segments_sha256", request.inputs[0].sha256}, {"curve_sha256", request.inputs[1].sha256}},
                               {{"vertex_count", vertices.size()}, {"edge_count", edges.size()}, {"face_count", faces.size()}},
                               {{"arrangement_vertices", vertex_list(ids)}, {"vertices", vertex_json},
                                {"edges", edge_json}, {"faces", face_json}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"vertex_count", vertices.size()}, {"edge_count", edges.size()}, {"face_count", faces.size()},
               {"algorithm", "CGAL::zone"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Labeled labelled_polygon(const Polygon& polygon) {
  Labeled arrangement;
  const std::size_t n = polygon.size();
  for (std::size_t i = 0; i < n; ++i) {
    CGAL::insert_non_intersecting_curve(arrangement, Segment(polygon.vertex(i), polygon.vertex((i + 1) % n)));
  }
  for (auto f = arrangement.faces_begin(); f != arrangement.faces_end(); ++f) f->set_data(f->is_unbounded() ? 0 : 1);
  return arrangement;
}

Json arrangement_overlay(const Request& request) {
  require_inputs(request, 2, "arrangement.overlay");
  require_parameter_names(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const Polygon first = operand(request.inputs[0]);
  const Polygon second = operand(request.inputs[1]);
  const Labeled red = labelled_polygon(first);
  const Labeled blue = labelled_polygon(second);
  Labeled result;
  SumOverlay traits;
  CGAL::overlay(red, blue, result, traits);
  const auto results = arrangement_results(result, true);
  Json report = geometry_frame(request, "arrangement_overlay", Json::object(),
                               {{"first_sha256", request.inputs[0].sha256}, {"second_sha256", request.inputs[1].sha256}},
                               {{"vertex_count", results["vertices"].size()}, {"edge_count", results["edges"].size()},
                                {"face_count", results["faces"].size()}},
                               results);
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"vertex_count", results["vertices"].size()}, {"edge_count", results["edges"].size()},
               {"face_count", results["faces"].size()}, {"algorithm", "CGAL::overlay"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> planar_producers() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "polygon.minkowski_sum", {"Polygon2", "Polygon2"}, "GeometryQueryReport", "analysis", minkowski_sum,
      {"Minkowski_sum_2"}, kEpeckName,
      pinfo("polygon.validate.minkowski_sum", {}, {"first", "second"},
            {{"source_header", "CGAL/minkowski_sum_2.h"}, {"maximum_polygon_vertices", kMaximumMinkowskiVertices}})));
  result.push_back(query_definition(
      "polygon.minkowski_sum_reduced_convolution", {"Polygon2", "Polygon2"}, "GeometryQueryReport", "analysis",
      minkowski_reduced, {"Minkowski_sum_2"}, kEpeckName,
      pinfo("polygon.validate.minkowski_sum", {}, {"first", "second"},
            {{"source_header", "CGAL/minkowski_sum_2.h"}, {"maximum_polygon_vertices", kMaximumMinkowskiVertices}})));
  result.push_back(query_definition(
      "arrangement.build", {"SegmentGraph2"}, "GeometryQueryReport", "analysis", arrangement_build, {"Arrangement_on_surface_2"},
      kEpeckName,
      pinfo("arrangement.validate.build", {}, {"segments"},
            {{"source_header", "CGAL/Arrangement_2.h"}, {"maximum_segments", kMaximumArrangementSegments}})));
  result.push_back(query_definition(
      "arrangement.zone", {"SegmentGraph2", "SegmentGraph2"}, "GeometryQueryReport", "analysis", arrangement_zone,
      {"Arrangement_on_surface_2"}, kEpeckName,
      pinfo("arrangement.validate.zone", {}, {"segments", "curve"},
            {{"source_header", "CGAL/Arrangement_2/Arrangement_on_surface_2_global.h"},
             {"maximum_segments", kMaximumArrangementSegments}})));
  result.push_back(query_definition(
      "arrangement.overlay", {"Polygon2", "Polygon2"}, "GeometryQueryReport", "analysis", arrangement_overlay,
      {"Arrangement_on_surface_2"}, kEpeckName,
      pinfo("arrangement.validate.overlay", {}, {"first", "second"},
            {{"source_header", "CGAL/Arr_overlay_2.h"}, {"maximum_polygon_vertices", kMaximumMinkowskiVertices}})));
  return result;
}

}  // namespace cgal_master::batch3
