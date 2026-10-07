// Wave C spatial adapters: kd-tree k-NN / radius search, axis-aligned
// bounding boxes, and AABB-tree closest-point / first-hit ray queries, each
// with an independent brute-force validator.
#include "wave_c_common.h"

#include <CGAL/AABB_face_graph_triangle_primitive.h>
#include <CGAL/AABB_traits_3.h>
#include <CGAL/AABB_tree.h>
#include <CGAL/Bbox_2.h>
#include <CGAL/Bbox_3.h>
#include <CGAL/Fuzzy_sphere.h>
#include <CGAL/K_neighbor_search.h>
#include <CGAL/Kd_tree.h>
#include <CGAL/Orthogonal_k_neighbor_search.h>
#include <CGAL/Search_traits_3.h>
#include <CGAL/Search_traits_adapter.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/boost/iterator/counting_iterator.hpp>

#include <algorithm>
#include <cmath>
#include <iterator>
#include <limits>
#include <map>
#include <set>
#include <string>
#include <variant>
#include <vector>

namespace cgal_master::wave_c {
namespace {

using P2 = Epick::Point_2;
using P3 = Epick::Point_3;

struct IndexPointMap {
  using key_type = std::size_t;
  using value_type = P3;
  using reference = const P3&;
  using category = boost::readable_property_map_tag;
  const std::vector<P3>* points = nullptr;
  IndexPointMap() = default;
  explicit IndexPointMap(const std::vector<P3>* values) : points(values) {}
  friend reference get(const IndexPointMap& map, std::size_t index) {
    return (*map.points)[index];
  }
};

using BaseTraits = CGAL::Search_traits_3<Epick>;
using Traits = CGAL::Search_traits_adapter<std::size_t, IndexPointMap, BaseTraits>;
using OrthogonalSearch = CGAL::Orthogonal_k_neighbor_search<Traits>;
using OrthogonalTree = OrthogonalSearch::Tree;
using GeneralSearch = CGAL::K_neighbor_search<Traits>;
using GeneralTree = GeneralSearch::Tree;
using SearchDistance = OrthogonalSearch::Distance;
using GeneralDistance = GeneralSearch::Distance;
using Sphere = CGAL::Fuzzy_sphere<Traits>;

using EMesh = CGAL::Surface_mesh<P3>;
using Primitive = CGAL::AABB_face_graph_triangle_primitive<EMesh>;
using AabbTraits = CGAL::AABB_traits_3<Epick, Primitive>;
using AabbTree = CGAL::AABB_tree<AabbTraits>;

P3 p3(const XYZ& point) { return P3(point[0], point[1], point[2]); }

void require_budget(std::size_t first, std::size_t second, const char* what) {
  if (first != 0 && second > kMaximumBruteForcePairs / first) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED",
                      std::string(what) + " exceeds the mandatory validation budget");
  }
}

double distance_of(const XYZ& a, const XYZ& b) {
  const double dx = a[0] - b[0], dy = a[1] - b[1], dz = a[2] - b[2];
  return std::sqrt(dx * dx + dy * dy + dz * dz);
}

Json spatial_report(const Request& request, const std::string& kind, const std::string& operation,
                    Json source, Json parameters, Json summary, Json results,
                    const std::string& unit) {
  return Json{{"schema_version", 1},
              {"report_type", "SpatialQueryReport"},
              {"query_kind", kind},
              {"operation", operation},
              {"length_unit", unit},
              {"source", std::move(source)},
              {"parameters", std::move(parameters)},
              {"summary", std::move(summary)},
              {"results", std::move(results)}};
}

Json emit_report(const Request& request, Json report, Json metrics) {
  auto output = write_json_output(request, "analysis", "SpatialQueryReport", "none", report);
  metrics["effective_kernel"] = kEpick;
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

void require_source(const Json& report, const char* key, const ArtifactInput& input) {
  if (report.value(nlohmann::json::json_pointer(std::string("/source/") + key), std::string()) !=
      input.sha256) {
    fail_validation("REPORT_SOURCE_MISMATCH", "Report does not describe the bound inputs");
  }
}

// ---------------------------------------------------------------------------
// spatial.knn_3
// ---------------------------------------------------------------------------

Json run_knn(const Request& request) {
  require_input_count(request, 2, "spatial.knn_3");
  require_parameters(request, {"k", "search"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto k = integer_parameter(request, "k", 1, kMaximumNeighbors);
  const auto search = enum_parameter(request, "search", {"orthogonal", "general"});
  const auto data = read_point_set3(request.inputs[0]);
  const auto queries = read_point_set3(request.inputs[1]);
  if (queries.size() > kMaximumQueryCount) {
    throw WorkerError("RESOURCE_LIMIT", "QUERY_LIMIT_EXCEEDED", "Too many k-NN queries");
  }
  require_budget(queries.size(), data.size(), "k-NN validation");
  std::vector<P3> points;
  for (const auto& point : data) points.push_back(p3(point));
  const IndexPointMap map(&points);
  Json results = Json::array();
  auto record = [&](std::size_t query_index, auto& found) {
    Json neighbors = Json::array();
    for (auto it = found.begin(); it != found.end(); ++it) {
      neighbors.push_back({{"index", it->first},
                           {"distance", distance_of(queries[query_index], data[it->first])}});
    }
    results.push_back({{"query_index", query_index}, {"neighbors", neighbors}});
  };
  if (search == "orthogonal") {
    OrthogonalTree tree(boost::counting_iterator<std::size_t>(0),
                        boost::counting_iterator<std::size_t>(points.size()),
                        OrthogonalTree::Splitter(), Traits(map));
    const SearchDistance distance(map);
    for (std::size_t i = 0; i < queries.size(); ++i) {
      OrthogonalSearch found(tree, p3(queries[i]), static_cast<unsigned int>(k), 0, true,
                             distance);
      record(i, found);
    }
  } else {
    GeneralTree tree(boost::counting_iterator<std::size_t>(0),
                     boost::counting_iterator<std::size_t>(points.size()),
                     GeneralTree::Splitter(), Traits(map));
    const GeneralDistance distance(map);
    for (std::size_t i = 0; i < queries.size(); ++i) {
      GeneralSearch found(tree, p3(queries[i]), static_cast<unsigned int>(k), 0, true, distance);
      record(i, found);
    }
  }
  const auto& unit = request.inputs[0].unit;
  Json report = spatial_report(
      request, "k_nearest_neighbors", "spatial.knn_3",
      {{"points_sha256", request.inputs[0].sha256}, {"queries_sha256", request.inputs[1].sha256}},
      {{"k", k}, {"search", search}},
      {{"query_count", queries.size()}, {"point_count", data.size()},
       {"neighbors_per_query", std::min(k, data.size())}},
      results, unit);
  return emit_report(request, std::move(report),
                     {{"query_count", queries.size()},
                      {"point_count", data.size()},
                      {"k", k},
                      {"search", search},
                      {"algorithm", search == "orthogonal" ? "CGAL::Orthogonal_k_neighbor_search"
                                                           : "CGAL::K_neighbor_search"},
                      {"tree", "CGAL::Kd_tree"}});
}

Json run_knn_validator(const Request& request) {
  require_input_count(request, 3, "spatial.validate.knn_report");
  require_parameters(request, {"k", "search"});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto k = integer_parameter(request, "k", 1, kMaximumNeighbors);
  const auto search = enum_parameter(request, "search", {"orthogonal", "general"});
  const auto report =
      read_report(request.inputs[0], "SpatialQueryReport", "query_kind", "k_nearest_neighbors");
  const auto data = read_point_set3(request.inputs[1]);
  const auto queries = read_point_set3(request.inputs[2]);
  require_source(report, "points_sha256", request.inputs[1]);
  require_source(report, "queries_sha256", request.inputs[2]);
  if (report.value("length_unit", "") != request.inputs[1].unit ||
      report.value("/parameters/k"_json_pointer, std::size_t(0)) != k ||
      report.value("/parameters/search"_json_pointer, std::string()) != search) {
    fail_validation("REPORT_PARAMETER_MISMATCH", "Report parameters differ from the request");
  }
  require_budget(queries.size(), data.size(), "k-NN validation");
  const auto& results = report.at("results");
  if (!results.is_array() || results.size() != queries.size()) {
    fail_validation("RESULT_COUNT_MISMATCH", "Every query needs exactly one result");
  }
  const std::size_t expected = std::min(k, data.size());
  for (std::size_t q = 0; q < queries.size(); ++q) {
    const auto& entry = results[q];
    const auto& neighbors = entry.at("neighbors");
    if (entry.value("query_index", std::size_t(-1)) != q || !neighbors.is_array() ||
        neighbors.size() != expected) {
      fail_validation("NEIGHBOR_COUNT_MISMATCH", "Query result has the wrong neighbor count");
    }
    const P3 query = p3(queries[q]);
    std::vector<std::size_t> chosen;
    std::set<std::size_t> chosen_set;
    for (const auto& neighbor : neighbors) {
      const auto index = neighbor.at("index").get<std::size_t>();
      if (index >= data.size() || !chosen_set.insert(index).second) {
        fail_validation("INVALID_NEIGHBOR_INDEX", "Neighbor index is invalid or repeated");
      }
      const double reported = neighbor.at("distance").get<double>();
      const double actual = distance_of(queries[q], data[index]);
      if (!(std::fabs(reported - actual) <= 1e-12 * std::max(1.0, actual))) {
        fail_validation("DISTANCE_MISMATCH", "Reported neighbor distance is wrong");
      }
      chosen.push_back(index);
    }
    for (std::size_t i = 0; i + 1 < chosen.size(); ++i) {
      if (CGAL::compare_distance_to_point(query, p3(data[chosen[i]]), p3(data[chosen[i + 1]])) ==
          CGAL::LARGER) {
        fail_validation("NEIGHBORS_NOT_SORTED", "Neighbors are not sorted by exact distance");
      }
    }
    if (chosen.empty()) continue;
    const P3 farthest = p3(data[chosen.back()]);
    for (std::size_t j = 0; j < data.size(); ++j) {
      if (chosen_set.count(j) != 0) continue;
      if (CGAL::compare_distance_to_point(query, p3(data[j]), farthest) == CGAL::SMALLER) {
        fail_validation("NOT_K_NEAREST",
                        "A non-selected point is strictly closer than a selected neighbor");
      }
    }
  }
  Json out = {{"checks",
               {{"every_query_answered", true},
                {"neighbor_count_matches", true},
                {"exact_k_nearest", true},
                {"sorted_by_exact_distance", true},
                {"distances_match", true}}},
              {"query_count", queries.size()},
              {"point_count", data.size()},
              {"neighbors_per_query", expected},
              {"independence",
               "brute-force exact distance comparisons over every point; no kd-tree is used"}};
  return finish_validation(request, "spatial.validate.knn_report", std::move(out));
}

// ---------------------------------------------------------------------------
// spatial.range_search_3 (closed ball, exact membership)
// ---------------------------------------------------------------------------

bool exact_within(const XYZ& query, const XYZ& point, double radius) {
  using FT = Epeck::FT;
  const FT dx = FT(point[0]) - FT(query[0]);
  const FT dy = FT(point[1]) - FT(query[1]);
  const FT dz = FT(point[2]) - FT(query[2]);
  return dx * dx + dy * dy + dz * dz <= FT(radius) * FT(radius);
}

Json run_range_search(const Request& request) {
  require_input_count(request, 2, "spatial.range_search_3");
  require_parameters(request, {"radius"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto& unit = request.inputs[0].unit;
  const double radius = typed_length_parameter(request, "radius", unit);
  const auto data = read_point_set3(request.inputs[0]);
  const auto queries = read_point_set3(request.inputs[1]);
  if (queries.size() > kMaximumQueryCount) {
    throw WorkerError("RESOURCE_LIMIT", "QUERY_LIMIT_EXCEEDED", "Too many range queries");
  }
  require_budget(queries.size(), data.size(), "Range-search validation");
  std::vector<P3> points;
  for (const auto& point : data) points.push_back(p3(point));
  const IndexPointMap map(&points);
  OrthogonalTree tree(boost::counting_iterator<std::size_t>(0),
                      boost::counting_iterator<std::size_t>(points.size()),
                      OrthogonalTree::Splitter(), Traits(map));
  // Slightly inflated fuzzy sphere, then exact closed-ball membership.
  const double inflated = radius * (1.0 + 1e-9) + std::numeric_limits<double>::min();
  Json results = Json::array();
  std::size_t total = 0;
  for (std::size_t q = 0; q < queries.size(); ++q) {
    std::vector<std::size_t> candidates;
    tree.search(std::back_inserter(candidates), Sphere(p3(queries[q]), inflated, 0.0, Traits(map)));
    std::vector<std::size_t> inside;
    for (const auto index : candidates) {
      if (exact_within(queries[q], data[index], radius)) inside.push_back(index);
    }
    std::sort(inside.begin(), inside.end());
    Json members = Json::array();
    for (const auto index : inside) {
      members.push_back({{"index", index}, {"distance", distance_of(queries[q], data[index])}});
    }
    total += inside.size();
    results.push_back({{"query_index", q}, {"neighbors", members}});
  }
  Json report = spatial_report(
      request, "radius_search", "spatial.range_search_3",
      {{"points_sha256", request.inputs[0].sha256}, {"queries_sha256", request.inputs[1].sha256}},
      {{"radius", {{"value", radius}, {"unit", unit}}}},
      {{"query_count", queries.size()}, {"point_count", data.size()}, {"total_matches", total}},
      results, unit);
  return emit_report(request, std::move(report),
                     {{"query_count", queries.size()},
                      {"point_count", data.size()},
                      {"total_matches", total},
                      {"algorithm", "CGAL::Fuzzy_sphere on CGAL::Kd_tree + exact closed-ball filter"}});
}

// Filtered closed-ball test written independently of the producer.
bool filtered_within(const XYZ& query, const XYZ& point, double radius) {
  const double dx = point[0] - query[0], dy = point[1] - query[1], dz = point[2] - query[2];
  const double squared = dx * dx + dy * dy + dz * dz;
  const double limit = radius * radius;
  const double slack = 1e-12 * std::max(squared, limit);
  if (squared < limit - slack) return true;
  if (squared > limit + slack) return false;
  return exact_within(query, point, radius);
}

Json run_range_validator(const Request& request) {
  require_input_count(request, 3, "spatial.validate.range_report");
  require_parameters(request, {"radius"});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto& unit = request.inputs[1].unit;
  const double radius = typed_length_parameter(request, "radius", unit);
  const auto report =
      read_report(request.inputs[0], "SpatialQueryReport", "query_kind", "radius_search");
  const auto data = read_point_set3(request.inputs[1]);
  const auto queries = read_point_set3(request.inputs[2]);
  require_source(report, "points_sha256", request.inputs[1]);
  require_source(report, "queries_sha256", request.inputs[2]);
  if (report.value("length_unit", "") != unit ||
      report.value("/parameters/radius/value"_json_pointer, -1.0) != radius) {
    fail_validation("REPORT_PARAMETER_MISMATCH", "Report radius differs from the request");
  }
  require_budget(queries.size(), data.size(), "Range-search validation");
  const auto& results = report.at("results");
  if (!results.is_array() || results.size() != queries.size()) {
    fail_validation("RESULT_COUNT_MISMATCH", "Every query needs exactly one result");
  }
  std::size_t total = 0;
  for (std::size_t q = 0; q < queries.size(); ++q) {
    std::vector<std::size_t> expected;
    for (std::size_t j = 0; j < data.size(); ++j) {
      if (filtered_within(queries[q], data[j], radius)) expected.push_back(j);
    }
    const auto& members = results[q].at("neighbors");
    if (results[q].value("query_index", std::size_t(-1)) != q || !members.is_array() ||
        members.size() != expected.size()) {
      fail_validation("RANGE_SET_MISMATCH", "Range result differs from exact brute force");
    }
    for (std::size_t i = 0; i < expected.size(); ++i) {
      const auto index = members[i].at("index").get<std::size_t>();
      const double reported = members[i].at("distance").get<double>();
      const double actual = distance_of(queries[q], data[expected[i]]);
      if (index != expected[i] ||
          !(std::fabs(reported - actual) <= 1e-12 * std::max(1.0, actual))) {
        fail_validation("RANGE_SET_MISMATCH", "Range result differs from exact brute force");
      }
    }
    total += expected.size();
  }
  Json out = {{"checks",
               {{"every_query_answered", true},
                {"exact_closed_ball_membership", true},
                {"distances_match", true}}},
              {"query_count", queries.size()},
              {"point_count", data.size()},
              {"total_matches", total},
              {"independence", "brute-force filtered-exact membership; no kd-tree is used"}};
  return finish_validation(request, "spatial.validate.range_report", std::move(out));
}

// ---------------------------------------------------------------------------
// spatial.bbox_2 / spatial.bbox_3
// ---------------------------------------------------------------------------

Json run_bbox_2(const Request& request) {
  require_input_count(request, 1, "spatial.bbox_2");
  require_parameters(request, {});
  const auto points = read_point_set2(request.inputs[0]);
  std::vector<P2> values;
  for (const auto& point : points) values.emplace_back(point[0], point[1]);
  const CGAL::Bbox_2 box = CGAL::bbox_2(values.begin(), values.end());
  const auto& unit = request.inputs[0].unit;
  Json results = {{"dimension", 2},
                  {"min", Json::array({box.xmin(), box.ymin()})},
                  {"max", Json::array({box.xmax(), box.ymax()})}};
  Json report = spatial_report(request, "axis_aligned_bounding_box", "spatial.bbox_2",
                               {{"geometry_sha256", request.inputs[0].sha256},
                                {"geometry_type", request.inputs[0].type}},
                               Json::object(), {{"point_count", points.size()}}, results, unit);
  return emit_report(request, std::move(report),
                     {{"point_count", points.size()}, {"algorithm", "CGAL::bbox_2 -> CGAL::Bbox_2"}});
}

std::vector<XYZ> points_of_3d_source(const ArtifactInput& input) {
  if (input.type == "TriangleSurfaceMesh") return read_triangle_mesh(input).vertices;
  return read_point_set3(input);
}

Json run_bbox_3(const Request& request) {
  require_input_count(request, 1, "spatial.bbox_3");
  require_parameters(request, {});
  const auto points = points_of_3d_source(request.inputs[0]);
  std::vector<P3> values;
  for (const auto& point : points) values.push_back(p3(point));
  const CGAL::Bbox_3 box = CGAL::bbox_3(values.begin(), values.end());
  const auto& unit = request.inputs[0].unit;
  Json results = {{"dimension", 3},
                  {"min", Json::array({box.xmin(), box.ymin(), box.zmin()})},
                  {"max", Json::array({box.xmax(), box.ymax(), box.zmax()})}};
  Json report = spatial_report(request, "axis_aligned_bounding_box", "spatial.bbox_3",
                               {{"geometry_sha256", request.inputs[0].sha256},
                                {"geometry_type", request.inputs[0].type}},
                               Json::object(), {{"point_count", points.size()}}, results, unit);
  return emit_report(request, std::move(report),
                     {{"point_count", points.size()}, {"algorithm", "CGAL::bbox_3 -> CGAL::Bbox_3"}});
}

Json run_bbox_validator(const Request& request) {
  require_input_count(request, 2, "spatial.validate.bbox_report");
  require_parameters(request, {});
  const auto report = read_report(request.inputs[0], "SpatialQueryReport", "query_kind",
                                  "axis_aligned_bounding_box");
  const auto& source = request.inputs[1];
  require_source(report, "geometry_sha256", source);
  if (report.value("length_unit", "") != source.unit) {
    fail_validation("REPORT_SOURCE_MISMATCH", "Report unit differs from its source");
  }
  std::vector<double> low, high;
  std::size_t count = 0;
  auto extend = [&](const double* coordinates, std::size_t dimension) {
    if (low.empty()) {
      low.assign(coordinates, coordinates + dimension);
      high = low;
    }
    for (std::size_t axis = 0; axis < dimension; ++axis) {
      if (coordinates[axis] < low[axis]) low[axis] = coordinates[axis];
      if (coordinates[axis] > high[axis]) high[axis] = coordinates[axis];
    }
    ++count;
  };
  if (source.type == "PointSet2") {
    for (const auto& point : read_point_set2(source)) extend(point.data(), 2);
  } else {
    for (const auto& point : points_of_3d_source(source)) extend(point.data(), 3);
  }
  const auto& results = report.at("results");
  if (results.value("dimension", 0) != static_cast<int>(low.size()) ||
      results.value("min", Json()) != Json(low) || results.value("max", Json()) != Json(high)) {
    fail_validation("BBOX_MISMATCH", "Bounding box differs from coordinate-wise extrema");
  }
  Json out = {{"checks", {{"bbox_matches_extrema", true}, {"all_points_inside", true}}},
              {"point_count", count},
              {"dimension", low.size()},
              {"independence", "coordinate-wise min/max loop; CGAL bbox functions are not called"}};
  return finish_validation(request, "spatial.validate.bbox_report", std::move(out));
}

// ---------------------------------------------------------------------------
// AABB tree queries
// ---------------------------------------------------------------------------

EMesh build_mesh(const TriangleMeshData& data) {
  EMesh mesh;
  std::vector<EMesh::Vertex_index> vertices;
  for (const auto& vertex : data.vertices) vertices.push_back(mesh.add_vertex(p3(vertex)));
  for (const auto& face : data.faces) {
    const auto added = mesh.add_face(vertices[face[0]], vertices[face[1]], vertices[face[2]]);
    if (added == EMesh::null_face() ||
        static_cast<std::size_t>(added.idx()) + 1 != mesh.number_of_faces()) {
      throw WorkerError("PRECONDITION_FAILED", "INVALID_POLYGON_MESH",
                        "Mesh faces cannot be indexed in file order");
    }
  }
  return mesh;
}

double scene_scale(const TriangleMeshData& mesh, const std::vector<XYZ>& extra) {
  double scale = 0;
  for (const auto& vertex : mesh.vertices) {
    for (double value : vertex) scale = std::max(scale, std::fabs(value));
  }
  for (const auto& point : extra) {
    for (double value : point) scale = std::max(scale, std::fabs(value));
  }
  return std::max(scale, 1e-300);
}

Json run_closest_points(const Request& request) {
  require_input_count(request, 2, "spatial.aabb.closest_points");
  require_parameters(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto mesh_data = read_triangle_mesh(request.inputs[0]);
  const auto queries = read_point_set3(request.inputs[1]);
  if (queries.size() > kMaximumQueryCount) {
    throw WorkerError("RESOURCE_LIMIT", "QUERY_LIMIT_EXCEEDED", "Too many closest-point queries");
  }
  require_budget(queries.size(), mesh_data.faces.size(), "Closest-point validation");
  const auto mesh = build_mesh(mesh_data);
  AabbTree tree(faces(mesh).first, faces(mesh).second, mesh);
  tree.accelerate_distance_queries();
  Json results = Json::array();
  for (std::size_t q = 0; q < queries.size(); ++q) {
    const auto found = tree.closest_point_and_primitive(p3(queries[q]));
    const XYZ point{found.first.x(), found.first.y(), found.first.z()};
    results.push_back({{"query_index", q},
                       {"face_index", static_cast<std::size_t>(found.second.idx())},
                       {"point", xyz_json(point)},
                       {"distance", distance_of(queries[q], point)}});
  }
  const auto& unit = request.inputs[0].unit;
  Json report = spatial_report(
      request, "aabb_closest_points", "spatial.aabb.closest_points",
      {{"mesh_sha256", request.inputs[0].sha256}, {"queries_sha256", request.inputs[1].sha256}},
      Json::object(),
      {{"query_count", queries.size()}, {"face_count", mesh_data.faces.size()}}, results, unit);
  return emit_report(request, std::move(report),
                     {{"query_count", queries.size()},
                      {"face_count", mesh_data.faces.size()},
                      {"algorithm", "CGAL::AABB_tree::closest_point_and_primitive"}});
}

using Vec = std::array<double, 3>;
Vec sub(const XYZ& a, const XYZ& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
double dot(const Vec& a, const Vec& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
XYZ along(const XYZ& a, const Vec& d, double t) {
  return {a[0] + t * d[0], a[1] + t * d[1], a[2] + t * d[2]};
}

// Ericson, Real-Time Collision Detection 5.1.5 (closest point on triangle).
XYZ closest_on_triangle(const XYZ& p, const XYZ& a, const XYZ& b, const XYZ& c) {
  const Vec ab = sub(b, a), ac = sub(c, a), ap = sub(p, a);
  const double d1 = dot(ab, ap), d2 = dot(ac, ap);
  if (d1 <= 0 && d2 <= 0) return a;
  const Vec bp = sub(p, b);
  const double d3 = dot(ab, bp), d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return b;
  const double vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) return along(a, ab, d1 / (d1 - d3));
  const Vec cp = sub(p, c);
  const double d5 = dot(ab, cp), d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return c;
  const double vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) return along(a, ac, d2 / (d2 - d6));
  const double va = d3 * d6 - d5 * d4;
  if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
    return along(b, sub(c, b), (d4 - d3) / ((d4 - d3) + (d5 - d6)));
  }
  const double denominator = 1.0 / (va + vb + vc);
  const double v = vb * denominator, w = vc * denominator;
  return {a[0] + ab[0] * v + ac[0] * w, a[1] + ab[1] * v + ac[1] * w,
          a[2] + ab[2] * v + ac[2] * w};
}

double point_triangle_distance(const XYZ& p, const TriangleMeshData& mesh, std::size_t face) {
  const auto& f = mesh.faces[face];
  return distance_of(p, closest_on_triangle(p, mesh.vertices[f[0]], mesh.vertices[f[1]],
                                            mesh.vertices[f[2]]));
}

Json run_closest_points_validator(const Request& request) {
  require_input_count(request, 3, "spatial.validate.closest_points_report");
  require_parameters(request, {});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto report =
      read_report(request.inputs[0], "SpatialQueryReport", "query_kind", "aabb_closest_points");
  const auto mesh = read_triangle_mesh(request.inputs[1]);
  const auto queries = read_point_set3(request.inputs[2]);
  require_source(report, "mesh_sha256", request.inputs[1]);
  require_source(report, "queries_sha256", request.inputs[2]);
  require_budget(queries.size(), mesh.faces.size(), "Closest-point validation");
  const auto& results = report.at("results");
  if (!results.is_array() || results.size() != queries.size()) {
    fail_validation("RESULT_COUNT_MISMATCH", "Every query needs exactly one result");
  }
  const double tolerance = 1e-9 * scene_scale(mesh, queries);
  double worst = 0;
  for (std::size_t q = 0; q < queries.size(); ++q) {
    double best = std::numeric_limits<double>::infinity();
    for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
      best = std::min(best, point_triangle_distance(queries[q], mesh, f));
    }
    const auto& entry = results[q];
    const auto face = entry.at("face_index").get<std::size_t>();
    if (entry.value("query_index", std::size_t(-1)) != q || face >= mesh.faces.size()) {
      fail_validation("INVALID_FACE_INDEX", "Closest-point face index is invalid");
    }
    const auto point_json = entry.at("point");
    const XYZ point{point_json.at(0).get<double>(), point_json.at(1).get<double>(),
                    point_json.at(2).get<double>()};
    const double reported = entry.at("distance").get<double>();
    const double face_distance = point_triangle_distance(queries[q], mesh, face);
    const double on_face = point_triangle_distance(point, mesh, face);
    const double error = std::max({std::fabs(face_distance - best), std::fabs(reported - best),
                                   std::fabs(distance_of(queries[q], point) - best), on_face});
    worst = std::max(worst, error);
    if (!(error <= tolerance)) {
      fail_validation("NOT_CLOSEST_POINT",
                      "Reported closest point/face differs from brute force beyond tolerance");
    }
  }
  Json out = {{"checks",
               {{"every_query_answered", true},
                {"closest_face_matches_brute_force", true},
                {"point_on_reported_face", true},
                {"distances_match", true}}},
              {"query_count", queries.size()},
              {"face_count", mesh.faces.size()},
              {"absolute_tolerance", tolerance},
              {"maximum_observed_error", worst},
              {"independence",
               "brute-force Ericson closest-point routine over every face; no AABB tree is used"}};
  return finish_validation(request, "spatial.validate.closest_points_report", std::move(out));
}

Json run_ray_hits(const Request& request) {
  require_input_count(request, 2, "spatial.aabb.ray_first_hits");
  require_parameters(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto mesh_data = read_triangle_mesh(request.inputs[0]);
  const auto rays = read_ray_batch3(request.inputs[1]);
  require_budget(rays.size(), mesh_data.faces.size(), "Ray-hit validation");
  const auto mesh = build_mesh(mesh_data);
  AabbTree tree(faces(mesh).first, faces(mesh).second, mesh);
  Json results = Json::array();
  std::size_t hits = 0;
  for (std::size_t r = 0; r < rays.size(); ++r) {
    const Epick::Ray_3 ray(p3(rays[r].origin),
                           Epick::Vector_3(rays[r].direction[0], rays[r].direction[1],
                                           rays[r].direction[2]));
    const auto found = tree.first_intersection(ray);
    if (!found) {
      results.push_back({{"ray_index", r}, {"hit", false}});
      continue;
    }
    P3 point;
    if (const auto* hit_point = std::get_if<P3>(&found->first)) {
      point = *hit_point;
    } else if (const auto* segment = std::get_if<Epick::Segment_3>(&found->first)) {
      const auto origin = p3(rays[r].origin);
      point = CGAL::compare_distance_to_point(origin, segment->source(), segment->target()) ==
                      CGAL::LARGER
                  ? segment->target()
                  : segment->source();
    } else {
      throw WorkerError("INTERNAL", "UNEXPECTED_INTERSECTION", "Unexpected ray intersection type");
    }
    const XYZ hit{point.x(), point.y(), point.z()};
    ++hits;
    results.push_back({{"ray_index", r},
                       {"hit", true},
                       {"face_index", static_cast<std::size_t>(found->second.idx())},
                       {"point", xyz_json(hit)},
                       {"distance", distance_of(rays[r].origin, hit)}});
  }
  const auto& unit = request.inputs[0].unit;
  Json report = spatial_report(
      request, "aabb_ray_first_hits", "spatial.aabb.ray_first_hits",
      {{"mesh_sha256", request.inputs[0].sha256}, {"rays_sha256", request.inputs[1].sha256}},
      Json::object(),
      {{"ray_count", rays.size()}, {"hit_count", hits}, {"face_count", mesh_data.faces.size()}},
      results, unit);
  return emit_report(request, std::move(report),
                     {{"ray_count", rays.size()},
                      {"hit_count", hits},
                      {"face_count", mesh_data.faces.size()},
                      {"algorithm", "CGAL::AABB_tree::first_intersection"}});
}

// Exact first-hit distance of a ray on one triangle, or -1 when disjoint.
double exact_first_hit(const RayData& ray, const TriangleMeshData& mesh, std::size_t face) {
  const auto& f = mesh.faces[face];
  const Epick::Triangle_3 inexact(p3(mesh.vertices[f[0]]), p3(mesh.vertices[f[1]]),
                                  p3(mesh.vertices[f[2]]));
  const Epick::Ray_3 inexact_ray(
      p3(ray.origin), Epick::Vector_3(ray.direction[0], ray.direction[1], ray.direction[2]));
  if (!CGAL::do_intersect(inexact_ray, inexact)) return -1;
  using EP = Epeck::Point_3;
  auto exact = [](const XYZ& value) { return EP(value[0], value[1], value[2]); };
  const Epeck::Triangle_3 triangle(exact(mesh.vertices[f[0]]), exact(mesh.vertices[f[1]]),
                                   exact(mesh.vertices[f[2]]));
  const EP origin = exact(ray.origin);
  const Epeck::Ray_3 exact_ray(origin, Epeck::Vector_3(ray.direction[0], ray.direction[1],
                                                       ray.direction[2]));
  const auto intersection = CGAL::intersection(exact_ray, triangle);
  if (!intersection) return -1;
  Epeck::FT squared;
  if (const auto* point = std::get_if<EP>(&*intersection)) {
    squared = CGAL::squared_distance(origin, *point);
  } else if (const auto* segment = std::get_if<Epeck::Segment_3>(&*intersection)) {
    squared = std::min(CGAL::squared_distance(origin, segment->source()),
                       CGAL::squared_distance(origin, segment->target()));
  } else {
    return -1;
  }
  return std::sqrt(CGAL::to_double(squared));
}

Json run_ray_hits_validator(const Request& request) {
  require_input_count(request, 3, "spatial.validate.ray_hits_report");
  require_parameters(request, {});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto report =
      read_report(request.inputs[0], "SpatialQueryReport", "query_kind", "aabb_ray_first_hits");
  const auto mesh = read_triangle_mesh(request.inputs[1]);
  const auto rays = read_ray_batch3(request.inputs[2]);
  require_source(report, "mesh_sha256", request.inputs[1]);
  require_source(report, "rays_sha256", request.inputs[2]);
  require_budget(rays.size(), mesh.faces.size(), "Ray-hit validation");
  const auto& results = report.at("results");
  if (!results.is_array() || results.size() != rays.size()) {
    fail_validation("RESULT_COUNT_MISMATCH", "Every ray needs exactly one result");
  }
  std::vector<XYZ> origins;
  for (const auto& ray : rays) origins.push_back(ray.origin);
  const double tolerance = 1e-9 * scene_scale(mesh, origins);
  std::size_t hits = 0;
  double worst = 0;
  for (std::size_t r = 0; r < rays.size(); ++r) {
    double best = std::numeric_limits<double>::infinity();
    for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
      const double hit = exact_first_hit(rays[r], mesh, f);
      if (hit >= 0) best = std::min(best, hit);
    }
    const auto& entry = results[r];
    const bool expected_hit = std::isfinite(best);
    if (entry.value("ray_index", std::size_t(-1)) != r ||
        entry.value("hit", !expected_hit) != expected_hit) {
      fail_validation("HIT_STATUS_MISMATCH", "Ray hit/miss status differs from exact brute force");
    }
    if (!expected_hit) continue;
    ++hits;
    const auto face = entry.at("face_index").get<std::size_t>();
    if (face >= mesh.faces.size()) fail_validation("INVALID_FACE_INDEX", "Hit face is invalid");
    const double face_hit = exact_first_hit(rays[r], mesh, face);
    const auto point_json = entry.at("point");
    const XYZ point{point_json.at(0).get<double>(), point_json.at(1).get<double>(),
                    point_json.at(2).get<double>()};
    const double reported = entry.at("distance").get<double>();
    if (face_hit < 0) fail_validation("FACE_NOT_HIT", "Reported face does not intersect the ray");
    const double error =
        std::max({std::fabs(face_hit - best), std::fabs(reported - best),
                  std::fabs(distance_of(rays[r].origin, point) - best),
                  point_triangle_distance(point, mesh, face)});
    worst = std::max(worst, error);
    if (!(error <= tolerance)) {
      fail_validation("NOT_FIRST_HIT", "Reported first hit differs from brute force beyond tolerance");
    }
  }
  Json out = {{"checks",
               {{"every_ray_answered", true},
                {"hit_status_exact", true},
                {"first_hit_matches_brute_force", true},
                {"point_on_reported_face", true}}},
              {"ray_count", rays.size()},
              {"hit_count", hits},
              {"face_count", mesh.faces.size()},
              {"absolute_tolerance", tolerance},
              {"maximum_observed_error", worst},
              {"independence",
               "exact ray/triangle predicates and exact intersections over every face; no AABB "
               "tree is used"}};
  return finish_validation(request, "spatial.validate.ray_hits_report", std::move(out));
}

}  // namespace

std::vector<OperationDefinition> spatial_operations() {
  std::vector<OperationDefinition> result;
  result.push_back(make_definition(
      "spatial.knn_3", {"PointSet3", "PointSet3"}, "SpatialQueryReport", "analysis", run_knn,
      {"Spatial_searching"},
      {{"source_header", "CGAL/Orthogonal_k_neighbor_search.h"},
       {"input_slots", {"points", "queries"}},
       {"required_parameters", {"k", "search"}},
       {"validators", {"spatial.validate.knn_report"}},
       {"validator_parameter_bindings",
        {{"spatial.validate.knn_report", {{"k", "k"}, {"search", "search"}}}}},
       {"maximum_neighbors", kMaximumNeighbors},
       {"maximum_brute_force_pairs", kMaximumBruteForcePairs}}));
  result.push_back(make_definition(
      "spatial.validate.knn_report", {"SpatialQueryReport", "PointSet3", "PointSet3"},
      "ValidationReport", "validator", run_knn_validator, {"Spatial_searching"},
      {{"input_slots", {"candidate", "points", "queries"}},
       {"output_slot", "validation"},
       {"bound_parameters", {"k", "search"}},
       {"checks",
        {"every_query_answered", "neighbor_count_matches", "exact_k_nearest",
         "sorted_by_exact_distance", "distances_match"}}}));
  result.push_back(make_definition(
      "spatial.range_search_3", {"PointSet3", "PointSet3"}, "SpatialQueryReport", "analysis",
      run_range_search, {"Spatial_searching"},
      {{"source_header", "CGAL/Fuzzy_sphere.h"},
       {"input_slots", {"points", "queries"}},
       {"required_parameters", {"radius"}},
       {"membership", "exact_closed_ball"},
       {"validators", {"spatial.validate.range_report"}},
       {"validator_parameter_bindings", {{"spatial.validate.range_report", {{"radius", "radius"}}}}},
       {"maximum_brute_force_pairs", kMaximumBruteForcePairs}}));
  result.push_back(make_definition(
      "spatial.validate.range_report", {"SpatialQueryReport", "PointSet3", "PointSet3"},
      "ValidationReport", "validator", run_range_validator, {"Spatial_searching"},
      {{"input_slots", {"candidate", "points", "queries"}},
       {"output_slot", "validation"},
       {"bound_parameters", {"radius"}},
       {"checks", {"every_query_answered", "exact_closed_ball_membership", "distances_match"}}}));
  result.push_back(make_definition(
      "spatial.bbox_2", {"PointSet2"}, "SpatialQueryReport", "analysis", run_bbox_2, {"Kernel_23"},
      {{"source_header", "CGAL/Bbox_2.h"},
       {"validators", {"spatial.validate.bbox_report"}}}));
  result.push_back(make_definition(
      "spatial.bbox_3", {"PointSet3", "TriangleSurfaceMesh"}, "SpatialQueryReport", "analysis",
      run_bbox_3, {"Kernel_23"},
      {{"source_header", "CGAL/Bbox_3.h"},
       {"validators", {"spatial.validate.bbox_report"}}}));
  result.push_back(make_definition(
      "spatial.validate.bbox_report",
      {"SpatialQueryReport", "PointSet2", "PointSet3", "TriangleSurfaceMesh"}, "ValidationReport",
      "validator", run_bbox_validator, {"Kernel_23"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"checks", {"bbox_matches_extrema", "all_points_inside"}}}));
  result.push_back(make_definition(
      "spatial.aabb.closest_points", {"TriangleSurfaceMesh", "PointSet3"}, "SpatialQueryReport",
      "analysis", run_closest_points, {"AABB_tree"},
      {{"source_header", "CGAL/AABB_tree.h"},
       {"primitive", "CGAL::AABB_face_graph_triangle_primitive"},
       {"traits", "CGAL::AABB_traits_3"},
       {"input_slots", {"mesh", "queries"}},
       {"validators", {"spatial.validate.closest_points_report"}},
       {"maximum_brute_force_pairs", kMaximumBruteForcePairs}}));
  result.push_back(make_definition(
      "spatial.validate.closest_points_report",
      {"SpatialQueryReport", "TriangleSurfaceMesh", "PointSet3"}, "ValidationReport", "validator",
      run_closest_points_validator, {"AABB_tree"},
      {{"input_slots", {"candidate", "mesh", "queries"}},
       {"output_slot", "validation"},
       {"relative_tolerance", 1e-9},
       {"checks",
        {"every_query_answered", "closest_face_matches_brute_force", "point_on_reported_face",
         "distances_match"}}}));
  result.push_back(make_definition(
      "spatial.aabb.ray_first_hits", {"TriangleSurfaceMesh", "RayBatch3"}, "SpatialQueryReport",
      "analysis", run_ray_hits, {"AABB_tree"},
      {{"source_header", "CGAL/AABB_tree.h"},
       {"primitive", "CGAL::AABB_face_graph_triangle_primitive"},
       {"traits", "CGAL::AABB_traits_3"},
       {"input_slots", {"mesh", "rays"}},
       {"validators", {"spatial.validate.ray_hits_report"}},
       {"maximum_brute_force_pairs", kMaximumBruteForcePairs}}));
  result.push_back(make_definition(
      "spatial.validate.ray_hits_report",
      {"SpatialQueryReport", "TriangleSurfaceMesh", "RayBatch3"}, "ValidationReport", "validator",
      run_ray_hits_validator, {"AABB_tree"},
      {{"input_slots", {"candidate", "mesh", "rays"}},
       {"output_slot", "validation"},
       {"relative_tolerance", 1e-9},
       {"checks",
        {"every_ray_answered", "hit_status_exact", "first_hit_matches_brute_force",
         "point_on_reported_face"}}}));
  return result;
}

}  // namespace cgal_master::wave_c
