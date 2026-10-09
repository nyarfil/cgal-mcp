// Producer wrapping CGAL 6.2.1 Boolean_set_operations_2 (7.12.04): Polygon_set_2 join,
// intersection and difference of two simple polygons in exact arithmetic. The result is
// checked by polygon.validate.boolean (b2_validators_polygon.cpp), which has no CGAL header.

#include "b2_geometry.h"
#include "b2_registry.h"

#include "../wave_c/wave_c_common.h"

#include <CGAL/Boolean_set_operations_2.h>
#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Polygon_2.h>
#include <CGAL/Polygon_set_2.h>

#include <iterator>

namespace cgal_master::batch2 {
namespace {

using Epeck = CGAL::Exact_predicates_exact_constructions_kernel;
using Polygon = CGAL::Polygon_2<Epeck>;
using PolygonWithHoles = CGAL::Polygon_with_holes_2<Epeck>;
using PolygonSet = CGAL::Polygon_set_2<Epeck>;
constexpr const char* kEpeckName = "CGAL::Exact_predicates_exact_constructions_kernel";

using query_ops::enum_parameter;
using query_ops::precondition;
using query_ops::read_polygon;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::write_report;

Polygon operand(const ArtifactInput& input) {
  const auto raw = read_polygon(input);
  if (raw.size() < 3) precondition("POLYGON_TOO_SMALL", "A polygon needs at least three vertices");
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
    points.push_back(Json::array({wave_c::exact_string(it->x()), wave_c::exact_string(it->y())}));
  }
  return points;
}

Json boolean_polygons(const Request& request) {
  require_inputs(request, 2, "polygon.boolean");
  require_parameter_names(request, {"operation"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto operation = enum_parameter(request, "operation", {"join", "intersection", "difference"});
  const Polygon first = operand(request.inputs[0]);
  const Polygon second = operand(request.inputs[1]);
  PolygonSet set(first);
  if (operation == "join") set.join(second);
  else if (operation == "intersection") set.intersection(second);
  else set.difference(second);
  std::vector<PolygonWithHoles> pieces;
  set.polygons_with_holes(std::back_inserter(pieces));
  Json polygons = Json::array();
  std::size_t hole_count = 0;
  for (const auto& piece : pieces) {
    Json holes = Json::array();
    for (auto it = piece.holes_begin(); it != piece.holes_end(); ++it) {
      holes.push_back(ring_json(*it));
      ++hole_count;
    }
    polygons.push_back({{"outer", ring_json(piece.outer_boundary())}, {"holes", holes}});
  }
  Json report = geometry_frame(
      request, "polygon_boolean", {{"operation", operation}},
      {{"first_sha256", request.inputs[0].sha256}, {"second_sha256", request.inputs[1].sha256}},
      {{"polygon_count", pieces.size()}, {"hole_count", hole_count}}, {{"polygons", polygons}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"polygon_count", pieces.size()}, {"hole_count", hole_count}, {"operation", operation},
               {"algorithm", "CGAL::Polygon_set_2"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> polygon_producer_operations() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "polygon.boolean", {"Polygon2", "Polygon2"}, "GeometryQueryReport", "analysis", boolean_polygons,
      {"Boolean_set_operations_2"}, kEpeckName,
      pinfo("polygon.validate.boolean", {"operation"}, {"first", "second"},
            {{"source_header", "CGAL/Boolean_set_operations_2.h"}})));
  return result;
}

}  // namespace cgal_master::batch2
