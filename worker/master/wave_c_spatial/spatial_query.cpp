#include "wave_c_spatial_operations.h"

#include "../artifact_io.h"
#include "../sha256.h"

#include <CGAL/AABB_tree.h>
#include <CGAL/AABB_traits_3.h>
#include <CGAL/AABB_triangle_primitive_3.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Fuzzy_sphere.h>
#include <CGAL/Orthogonal_k_neighbor_search.h>
#include <CGAL/Search_traits_3.h>
#include <CGAL/bounding_box.h>
#include <CGAL/number_utils.h>
#include <CGAL/squared_distance_3.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace cgal_master::wave_c_spatial {
namespace {

using ExactTriangle = Kernel::Triangle_3;
using ExactSegment = Kernel::Segment_3;
using TriangleList = std::vector<ExactTriangle>;
using AabbPrimitive =
    CGAL::AABB_triangle_primitive_3<Kernel, TriangleList::const_iterator>;
using AabbTraits = CGAL::AABB_traits_3<Kernel, AabbPrimitive>;
using AabbTree = CGAL::AABB_tree<AabbTraits>;

using SearchKernel = CGAL::Exact_predicates_inexact_constructions_kernel;
using SearchPoint = SearchKernel::Point_3;
using SearchTraits = CGAL::Search_traits_3<SearchKernel>;
using NeighborSearch = CGAL::Orthogonal_k_neighbor_search<SearchTraits>;
using KdTree = NeighborSearch::Tree;
using FuzzySphere = CGAL::Fuzzy_sphere<SearchTraits>;

constexpr std::size_t kMaxMeshFaces = 400000;
constexpr std::size_t kMaxSpatialPoints = 2000000;
constexpr std::size_t kMaxReportBytes = 16ULL * 1024ULL * 1024ULL;
constexpr std::size_t kMaxListedResults = 100000;

struct Profile {
  std::string id;
  std::string validator_id;
  std::string kind;
  std::string input_type;
  std::string input_format;
  std::vector<std::string> parameter_names;
};

const std::set<std::string> kUnits = {"mm", "cm", "m"};

double unit_scale_mm(const std::string& unit) {
  if (unit == "mm") return 1.0;
  if (unit == "cm") return 10.0;
  if (unit == "m") return 1000.0;
  throw WorkerError("INVALID_INPUT", "UNSUPPORTED_UNIT",
                    "Spatial length unit must be mm, cm, or m");
}

double convert_length(double value, const std::string& from,
                      const std::string& to) {
  const double converted = value * unit_scale_mm(from) / unit_scale_mm(to);
  if (!std::isfinite(converted)) {
    throw WorkerError("NUMERIC_FAILURE", "UNIT_CONVERSION_NOT_FINITE",
                      "Spatial unit conversion produced a non-finite value");
  }
  return converted;
}

void require_kernel(const Request& request) {
  if (request.kernel != "exact_constructions" &&
      request.kernel != "package_recommended") {
    throw WorkerError("UNSUPPORTED", "UNSUPPORTED_KERNEL",
                      "Spatial Query supports exact_constructions and "
                      "package_recommended where declared by the operation");
  }
}

void require_package_recommended(const Request& request,
                                 const char* operation) {
  require_kernel(request);
  if (request.kernel != "package_recommended") {
    throw WorkerError(
        "UNSUPPORTED", "OUTPUT_PRECISION_PROFILE_UNSUPPORTED",
        std::string(operation) +
            " uses CGAL Spatial_searching with EPICK and does not silently "
            "downgrade an exact_constructions request");
  }
}

void require_parameters(const Json& parameters,
                        const std::set<std::string>& allowed,
                        const std::set<std::string>& required) {
  if (!parameters.is_object()) {
    throw WorkerError("INVALID_INPUT", "PARAMETERS_NOT_OBJECT",
                      "Spatial parameters must be a JSON object");
  }
  for (auto it = parameters.begin(); it != parameters.end(); ++it) {
    if (allowed.count(it.key()) == 0) {
      throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PARAMETER",
                        "Unsupported spatial parameter: " + it.key());
    }
  }
  for (const auto& name : required) {
    if (!parameters.contains(name)) {
      throw WorkerError("INVALID_INPUT", "MISSING_PARAMETER",
                        "Missing required spatial parameter: " + name);
    }
  }
}

std::array<double, 3> typed_point(const Json& value,
                                  const std::string& target_unit,
                                  const char* name) {
  if (!value.is_object() || value.size() != 2 ||
      !value.contains("value") || !value.contains("unit") ||
      !value.at("value").is_array() || value.at("value").size() != 3 ||
      !value.at("unit").is_string()) {
    throw WorkerError("INVALID_INPUT", "INVALID_TYPED_POINT",
                      std::string(name) +
                          " must be {value:[x,y,z],unit:mm|cm|m}");
  }
  const auto unit = value.at("unit").get<std::string>();
  if (kUnits.count(unit) == 0) {
    throw WorkerError("INVALID_INPUT", "UNSUPPORTED_UNIT",
                      std::string(name) + " has unsupported unit");
  }
  std::array<double, 3> result{};
  for (std::size_t axis = 0; axis < 3; ++axis) {
    if (!value.at("value")[axis].is_number()) {
      throw WorkerError("INVALID_INPUT", "INVALID_TYPED_POINT",
                        std::string(name) + " coordinates must be numbers");
    }
    const auto coordinate = value.at("value")[axis].get<double>();
    if (!std::isfinite(coordinate)) {
      throw WorkerError("INVALID_INPUT", "NONFINITE_COORDINATE",
                        std::string(name) + " coordinates must be finite");
    }
    result[axis] = convert_length(coordinate, unit, target_unit);
  }
  return result;
}

double typed_length(const Json& value, const std::string& target_unit,
                    const char* name, bool allow_zero) {
  if (!value.is_object() || value.size() != 2 ||
      !value.contains("value") || !value.contains("unit") ||
      !value.at("value").is_number() || !value.at("unit").is_string()) {
    throw WorkerError("INVALID_INPUT", "INVALID_TYPED_LENGTH",
                      std::string(name) +
                          " must be {value:number,unit:mm|cm|m}");
  }
  const auto raw = value.at("value").get<double>();
  const auto unit = value.at("unit").get<std::string>();
  if (!std::isfinite(raw) || kUnits.count(unit) == 0) {
    throw WorkerError("INVALID_INPUT", "INVALID_TYPED_LENGTH",
                      std::string(name) + " must be finite with a known unit");
  }
  const auto result = convert_length(raw, unit, target_unit);
  if (result < 0 || (!allow_zero && result == 0)) {
    throw WorkerError("INVALID_INPUT", "LENGTH_OUT_OF_RANGE",
                      std::string(name) +
                          (allow_zero ? " must be non-negative"
                                      : " must be strictly positive"));
  }
  return result;
}

Json typed_point_json(const std::array<double, 3>& value,
                      const std::string& unit) {
  return {{"value", {value[0], value[1], value[2]}}, {"unit", unit}};
}

Json exact_point_json(const Point& point, const std::string& unit) {
  std::array<double, 3> values = {CGAL::to_double(point.x()),
                                  CGAL::to_double(point.y()),
                                  CGAL::to_double(point.z())};
  for (const auto value : values) {
    if (!std::isfinite(value)) {
      throw WorkerError("NUMERIC_FAILURE", "RESULT_NOT_REPRESENTABLE",
                        "Spatial point result is not representable in binary64");
    }
  }
  std::array<std::string, 3> exact_values;
  std::ostringstream x;
  std::ostringstream y;
  std::ostringstream z;
  x << CGAL::exact(point.x());
  y << CGAL::exact(point.y());
  z << CGAL::exact(point.z());
  exact_values = {x.str(), y.str(), z.str()};
  return {{"value", {values[0], values[1], values[2]}},
          {"exact", {exact_values[0], exact_values[1], exact_values[2]}},
          {"unit", unit}};
}

Json search_point_json(const SearchPoint& point, const std::string& unit) {
  std::array<double, 3> values = {point.x(), point.y(), point.z()};
  for (const auto value : values) {
    if (!std::isfinite(value)) {
      throw WorkerError("NUMERIC_FAILURE", "RESULT_NOT_REPRESENTABLE",
                        "Spatial point result is not representable in binary64");
    }
  }
  return typed_point_json(values, unit);
}

template <typename FT>
Json exact_scalar(const FT& value, const std::string& unit) {
  std::ostringstream exact;
  exact << CGAL::exact(value);
  Json result = {{"exact", exact.str()}, {"unit", unit}};
  const auto approximate = CGAL::to_double(value);
  if (std::isfinite(approximate)) result["approximate"] = approximate;
  return result;
}

Json source_descriptor(const ArtifactInput& input) {
  return {{"artifact_id", input.artifact_id},
          {"type", input.type},
          {"format", input.format},
          {"unit", input.unit},
          {"sha256", input.sha256}};
}

std::vector<SearchPoint> search_points(const ArtifactInput& input) {
  const auto exact = read_xyz_points(input);
  if (exact.empty()) {
    throw WorkerError("PRECONDITION_FAILED", "EMPTY_POINT_SET",
                      "Spatial point queries require at least one point");
  }
  if (exact.size() > kMaxSpatialPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED",
                      "Spatial point query exceeds the bounded point limit");
  }
  std::vector<SearchPoint> result;
  result.reserve(exact.size());
  for (const auto& point : exact) {
    const auto x = CGAL::to_double(point.x());
    const auto y = CGAL::to_double(point.y());
    const auto z = CGAL::to_double(point.z());
    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) {
      throw WorkerError("NUMERIC_FAILURE", "INPUT_NOT_REPRESENTABLE",
                        "Point cannot be represented by the spatial-search "
                        "package-recommended kernel");
    }
    result.emplace_back(x, y, z);
  }
  return result;
}

TriangleList mesh_triangles(const ArtifactInput& input) {
  const auto mesh = read_off_mesh(input);
  if (mesh.number_of_faces() > kMaxMeshFaces) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_FACE_LIMIT_EXCEEDED",
                      "AABB query exceeds the bounded face limit");
  }
  TriangleList triangles;
  triangles.reserve(mesh.number_of_faces());
  for (const auto face : mesh.faces()) {
    auto halfedge = mesh.halfedge(face);
    const auto p0 = mesh.point(mesh.target(halfedge));
    halfedge = mesh.next(halfedge);
    const auto p1 = mesh.point(mesh.target(halfedge));
    halfedge = mesh.next(halfedge);
    const auto p2 = mesh.point(mesh.target(halfedge));
    ExactTriangle triangle(p0, p1, p2);
    if (triangle.is_degenerate()) {
      throw WorkerError(
          "PRECONDITION_FAILED", "AABB_DEGENERATE_PRIMITIVE",
          "AABB Tree queries reject degenerate triangles because CGAL "
          "documents them as unsafe for the standard AABB traits");
    }
    triangles.push_back(std::move(triangle));
  }
  if (triangles.empty()) {
    throw WorkerError("PRECONDITION_FAILED", "EMPTY_MESH",
                      "AABB Tree queries require at least one triangle");
  }
  return triangles;
}

Json report_shell(const Request& request, const Profile& profile, Json results,
                  Json checks) {
  return {{"schema_version", 1},
          {"analysis_kind", profile.kind},
          {"source", source_descriptor(request.inputs.front())},
          {"results", std::move(results)},
          {"validation",
           {{"validator_id", profile.validator_id},
            {"authoritative", false},
            {"passed", true},
            {"checks", std::move(checks)}}}};
}

std::size_t bounded_limit(const Json& parameters, const char* name,
                          std::size_t fallback) {
  if (!parameters.contains(name)) return fallback;
  if (!parameters.at(name).is_number_unsigned() &&
      !parameters.at(name).is_number_integer()) {
    throw WorkerError("INVALID_INPUT", "INVALID_LIMIT",
                      std::string(name) + " must be an integer");
  }
  const auto raw = parameters.at(name).get<long long>();
  if (raw <= 0 || static_cast<unsigned long long>(raw) > kMaxListedResults) {
    throw WorkerError("INVALID_INPUT", "INVALID_LIMIT",
                      std::string(name) + " is outside the supported range");
  }
  return static_cast<std::size_t>(raw);
}

Json compute_aabb_closest(const Request& request, const Profile& profile) {
  require_kernel(request);
  require_parameters(request.parameters, {"query_point"}, {"query_point"});
  if (request.inputs.size() != 1)
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "AABB closest-point query requires one mesh");
  const auto& source = request.inputs.front();
  require_input_shape(source, "TriangleSurfaceMesh", "off");
  const auto query_values =
      typed_point(request.parameters.at("query_point"), source.unit,
                  "query_point");
  const Point query(query_values[0], query_values[1], query_values[2]);
  auto triangles = mesh_triangles(source);
  AabbTree tree(triangles.cbegin(), triangles.cend());
  tree.accelerate_distance_queries();
  const auto hit = tree.closest_point_and_primitive(query);
  const auto squared = tree.squared_distance(query);
  const auto primitive_index =
      static_cast<std::size_t>(std::distance(triangles.cbegin(), hit.second));
  Json results = {
      {"query_point", typed_point_json(query_values, source.unit)},
      {"closest_point", exact_point_json(hit.first, source.unit)},
      {"primitive_index", primitive_index},
      {"squared_distance", exact_scalar(squared, source.unit + "^2")},
      {"primitive_count", triangles.size()}};
  return report_shell(request, profile, std::move(results),
                      {{"aabb_tree_built", true}, {"nondegenerate_primitives", true},
                       {"closest_point_and_primitive_found", true}});
}

Json compute_kdtree_range(const Request& request, const Profile& profile) {
  require_package_recommended(request, "spatial.kdtree.range");
  require_parameters(request.parameters,
                     {"center", "radius", "epsilon", "max_results"},
                     {"center", "radius"});
  if (request.inputs.size() != 1)
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "KD range query requires one point set");
  const auto& source = request.inputs.front();
  require_input_shape(source, "PointSet3", "xyz");
  const auto center_values =
      typed_point(request.parameters.at("center"), source.unit, "center");
  const auto radius =
      typed_length(request.parameters.at("radius"), source.unit, "radius",
                   true);
  double epsilon = 0.0;
  if (request.parameters.contains("epsilon"))
    epsilon = typed_length(request.parameters.at("epsilon"), source.unit,
                           "epsilon", true);
  const auto max_results =
      bounded_limit(request.parameters, "max_results", 10000);
  auto points = search_points(source);
  KdTree tree(points.begin(), points.end());
  const SearchPoint center(center_values[0], center_values[1], center_values[2]);
  FuzzySphere sphere(center, radius, epsilon);
  std::vector<SearchPoint> hits;
  tree.search(std::back_inserter(hits), sphere);
  std::sort(hits.begin(), hits.end(), [](const auto& a, const auto& b) {
    return std::make_tuple(a.x(), a.y(), a.z()) <
           std::make_tuple(b.x(), b.y(), b.z());
  });
  const auto total = hits.size();
  if (hits.size() > max_results) hits.resize(max_results);
  Json listed = Json::array();
  for (const auto& point : hits)
    listed.push_back(search_point_json(point, source.unit));
  Json results = {
      {"center", typed_point_json(center_values, source.unit)},
      {"radius", {{"value", radius}, {"unit", source.unit}}},
      {"epsilon", {{"value", epsilon}, {"unit", source.unit}}},
      {"point_count", points.size()},
      {"match_count", total},
      {"listed_count", hits.size()},
      {"truncated", total > hits.size()},
      {"points", std::move(listed)}};
  return report_shell(request, profile, std::move(results),
                      {{"kd_tree_built", true}, {"range_query_executed", true},
                       {"result_bound_recorded", true}});
}

Json compute_nearest(const Request& request, const Profile& profile) {
  require_package_recommended(request, "spatial.nearest_neighbors");
  require_parameters(request.parameters,
                     {"query_point", "k", "epsilon"},
                     {"query_point", "k"});
  if (request.inputs.size() != 1)
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "Nearest-neighbor query requires one point set");
  const auto& source = request.inputs.front();
  require_input_shape(source, "PointSet3", "xyz");
  auto points = search_points(source);
  if (!request.parameters.at("k").is_number_integer()) {
    throw WorkerError("INVALID_INPUT", "INVALID_K",
                      "k must be an integer");
  }
  const auto k_raw = request.parameters.at("k").get<long long>();
  if (k_raw <= 0 || static_cast<std::size_t>(k_raw) > points.size() ||
      static_cast<unsigned long long>(k_raw) > kMaxListedResults) {
    throw WorkerError("INVALID_INPUT", "INVALID_K",
                      "k must be between 1 and the point count");
  }
  double epsilon = request.parameters.value("epsilon", 0.0);
  if (!std::isfinite(epsilon) || epsilon < 0) {
    throw WorkerError("INVALID_INPUT", "INVALID_EPSILON",
                      "nearest-neighbor epsilon must be finite and non-negative");
  }
  const auto query_values =
      typed_point(request.parameters.at("query_point"), source.unit,
                  "query_point");
  const SearchPoint query(query_values[0], query_values[1], query_values[2]);
  KdTree tree(points.begin(), points.end());
  NeighborSearch search(tree, query, static_cast<unsigned int>(k_raw),
                        SearchKernel::FT(epsilon), true);
  Json neighbors = Json::array();
  for (auto it = search.begin(); it != search.end(); ++it) {
    const auto squared = CGAL::to_double(CGAL::squared_distance(query, it->first));
    const auto actual = std::sqrt(squared);
    if (!std::isfinite(actual)) {
      throw WorkerError("NUMERIC_FAILURE", "RESULT_NOT_REPRESENTABLE",
                        "Nearest-neighbor distance is not finite");
    }
    neighbors.push_back(
        {{"point", search_point_json(it->first, source.unit)},
         {"distance", {{"value", actual}, {"unit", source.unit}}}});
  }
  Json results = {{"query_point", typed_point_json(query_values, source.unit)},
                  {"k", k_raw},
                  {"epsilon", epsilon},
                  {"point_count", points.size()},
                  {"neighbors", std::move(neighbors)}};
  return report_shell(request, profile, std::move(results),
                      {{"kd_tree_built", true},
                       {"orthogonal_k_neighbor_search_executed", true},
                       {"neighbor_count_bounded", true}});
}

Json compute_intersections(const Request& request, const Profile& profile) {
  require_kernel(request);
  require_parameters(request.parameters,
                     {"segment_start", "segment_end", "max_candidates"},
                     {"segment_start", "segment_end"});
  if (request.inputs.size() != 1)
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "Intersection-candidate query requires one mesh");
  const auto& source = request.inputs.front();
  require_input_shape(source, "TriangleSurfaceMesh", "off");
  const auto start_values =
      typed_point(request.parameters.at("segment_start"), source.unit,
                  "segment_start");
  const auto end_values =
      typed_point(request.parameters.at("segment_end"), source.unit,
                  "segment_end");
  const Point start(start_values[0], start_values[1], start_values[2]);
  const Point end(end_values[0], end_values[1], end_values[2]);
  if (start == end) {
    throw WorkerError("INVALID_INPUT", "DEGENERATE_SEGMENT_QUERY",
                      "Intersection query segment endpoints must differ");
  }
  const auto max_candidates =
      bounded_limit(request.parameters, "max_candidates", 10000);
  auto triangles = mesh_triangles(source);
  AabbTree tree(triangles.cbegin(), triangles.cend());
  ExactSegment segment(start, end);
  std::vector<TriangleList::const_iterator> hits;
  tree.all_intersected_primitives(segment, std::back_inserter(hits));
  std::vector<std::size_t> indices;
  indices.reserve(hits.size());
  for (const auto& hit : hits)
    indices.push_back(
        static_cast<std::size_t>(std::distance(triangles.cbegin(), hit)));
  std::sort(indices.begin(), indices.end());
  indices.erase(std::unique(indices.begin(), indices.end()), indices.end());
  const auto total = indices.size();
  if (indices.size() > max_candidates) indices.resize(max_candidates);
  Json results = {
      {"segment_start", typed_point_json(start_values, source.unit)},
      {"segment_end", typed_point_json(end_values, source.unit)},
      {"primitive_count", triangles.size()},
      {"does_intersect", tree.do_intersect(segment)},
      {"candidate_count", total},
      {"listed_count", indices.size()},
      {"truncated", total > indices.size()},
      {"primitive_indices", indices}};
  return report_shell(request, profile, std::move(results),
                      {{"aabb_tree_built", true}, {"nondegenerate_primitives", true},
                       {"intersection_candidates_enumerated", true}});
}

Json compute_bbox(const Request& request, const Profile& profile) {
  require_kernel(request);
  require_parameters(request.parameters, {}, {});
  if (request.inputs.size() != 1)
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "Bounding-box query requires one point set");
  const auto& source = request.inputs.front();
  require_input_shape(source, "PointSet3", "xyz");
  const auto points = read_xyz_points(source);
  if (points.empty()) {
    throw WorkerError("PRECONDITION_FAILED", "EMPTY_POINT_SET",
                      "Bounding-box query requires at least one point");
  }
  if (points.size() > kMaxSpatialPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED",
                      "Bounding-box query exceeds the bounded point limit");
  }
  const auto box = CGAL::bounding_box(points.begin(), points.end());
  const std::array<double, 3> minimum = {
      CGAL::to_double(box.xmin()), CGAL::to_double(box.ymin()),
      CGAL::to_double(box.zmin())};
  const std::array<double, 3> maximum = {
      CGAL::to_double(box.xmax()), CGAL::to_double(box.ymax()),
      CGAL::to_double(box.zmax())};
  Json results = {{"point_count", points.size()},
                  {"minimum", typed_point_json(minimum, source.unit)},
                  {"maximum", typed_point_json(maximum, source.unit)},
                  {"extent",
                   typed_point_json(
                       {maximum[0] - minimum[0], maximum[1] - minimum[1],
                        maximum[2] - minimum[2]},
                       source.unit)}};
  return report_shell(request, profile, std::move(results),
                      {{"bounding_box_executed", true}, {"finite_bounds", true}});
}

const Profile& profile_for(const std::string& operation) {
  static const std::vector<Profile> profiles = {
      {"spatial.aabb.closest_point", "spatial.validate.aabb_closest_point",
       "aabb_closest_point", "TriangleSurfaceMesh", "off", {"query_point"}},
      {"spatial.kdtree.range", "spatial.validate.kdtree_range",
       "kdtree_range", "PointSet3", "xyz",
       {"center", "radius", "epsilon", "max_results"}},
      {"spatial.nearest_neighbors", "spatial.validate.nearest_neighbors",
       "nearest_neighbors", "PointSet3", "xyz",
       {"query_point", "k", "epsilon"}},
      {"spatial.intersection_candidates",
       "spatial.validate.intersection_candidates",
       "intersection_candidates", "TriangleSurfaceMesh", "off",
       {"segment_start", "segment_end", "max_candidates"}},
      {"spatial.bounding_box", "spatial.validate.bounding_box",
       "bounding_box", "PointSet3", "xyz", {}}};
  for (const auto& profile : profiles)
    if (profile.id == operation) return profile;
  throw WorkerError("UNSUPPORTED", "UNKNOWN_SPATIAL_OPERATION",
                    "Unknown spatial analysis operation: " + operation);
}

Json compute_report(const Request& request) {
  const auto& profile = profile_for(request.operation);
  if (profile.id == "spatial.aabb.closest_point")
    return compute_aabb_closest(request, profile);
  if (profile.id == "spatial.kdtree.range")
    return compute_kdtree_range(request, profile);
  if (profile.id == "spatial.nearest_neighbors")
    return compute_nearest(request, profile);
  if (profile.id == "spatial.intersection_candidates")
    return compute_intersections(request, profile);
  if (profile.id == "spatial.bounding_box")
    return compute_bbox(request, profile);
  throw WorkerError("UNSUPPORTED", "UNKNOWN_SPATIAL_OPERATION",
                    "Spatial analysis dispatch failed");
}

Json write_analysis(const Request& request, const Json& report) {
  const auto destination =
      output_path(checked_output_dir(request), "analysis.json");
  const auto temporary = destination.parent_path() /
                         (".analysis.json." +
                          staging_filename_token(request.request_id) + ".tmp");
  std::ofstream output(temporary, std::ios::binary);
  output << report.dump() << '\n';
  output.close();
  if (!output) {
    std::filesystem::remove(temporary);
    throw WorkerError("IO_FAILURE", "OUTPUT_WRITE_FAILED",
                      "Cannot write spatial analysis report");
  }
  commit_output(temporary, destination);
  return success_result(
      request,
      Json::array({{{"slot", "analysis"},
                    {"type", "GeometryAnalysisReport"},
                    {"unit", "none"},
                    {"format", "json"},
                    {"path", portable_path(destination)}}}),
      {{"analysis_kind", report.at("analysis_kind")},
       {"source_sha256", request.inputs.front().sha256}});
}

std::string verified_report_bytes(const ArtifactInput& input) {
  if (input.type != "GeometryAnalysisReport" || input.format != "json" ||
      input.unit != "none") {
    throw WorkerError("INVALID_INPUT", "INPUT_TYPE_OR_FORMAT_MISMATCH",
                      "Spatial validator candidate must be "
                      "GeometryAnalysisReport/json/none");
  }
  std::error_code error;
  const auto canonical = std::filesystem::canonical(input.path, error);
  if (error || !std::filesystem::is_regular_file(canonical, error) || error) {
    throw WorkerError("INVALID_INPUT", "INPUT_NOT_REGULAR_FILE",
                      "Spatial validator candidate must be a regular file");
  }
  if (std::filesystem::file_size(canonical, error) > kMaxReportBytes || error) {
    throw WorkerError("RESOURCE_LIMIT", "REPORT_SIZE_LIMIT_EXCEEDED",
                      "Spatial report exceeds the bounded report limit");
  }
  std::ifstream stream(canonical, std::ios::binary);
  std::string bytes((std::istreambuf_iterator<char>(stream)),
                    std::istreambuf_iterator<char>());
  if (!stream.eof() && stream.fail()) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Cannot read spatial analysis report");
  }
  if (sha256_bytes(bytes) != input.sha256) {
    throw WorkerError("INVALID_INPUT", "DIGEST_MISMATCH",
                      "Spatial report sha256 does not match request");
  }
  return bytes;
}

Json read_candidate(const ArtifactInput& input) {
  try {
    return Json::parse(verified_report_bytes(input));
  } catch (const Json::exception&) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_ANALYSIS_REPORT",
                      "Spatial candidate report is not strict JSON");
  }
}

Json write_validation(const Request& request, const Profile& profile,
                      const Json& checks) {
  Json report = {{"schema_version", 1},
                 {"validator_id", profile.validator_id},
                 {"validates", profile.id},
                 {"candidate_sha256", request.inputs[0].sha256},
                 {"source_sha256", request.inputs[1].sha256},
                 {"status", "pass"},
                 {"passed", true},
                 {"checks", checks}};
  const auto destination =
      output_path(checked_output_dir(request), "validation.json");
  const auto temporary = destination.parent_path() /
                         (".validation.json." +
                          staging_filename_token(request.request_id) + ".tmp");
  std::ofstream output(temporary, std::ios::binary);
  output << report.dump() << '\n';
  output.close();
  if (!output) {
    std::filesystem::remove(temporary);
    throw WorkerError("IO_FAILURE", "OUTPUT_WRITE_FAILED",
                      "Cannot write spatial validation report");
  }
  commit_output(temporary, destination);
  return success_result(
      request,
      Json::array({{{"slot", "validation"},
                    {"type", "ValidationReport"},
                    {"unit", "none"},
                    {"format", "json"},
                    {"path", portable_path(destination)}}}),
      {{"validator_id", profile.validator_id}, {"passed", true}});
}

Json validate(const Request& request, const Profile& producer) {
  require_kernel(request);
  if (request.inputs.size() != 2) {
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "Spatial validator requires candidate then source");
  }
  const auto candidate = read_candidate(request.inputs[0]);
  const auto& source = request.inputs[1];
  require_input_shape(source, producer.input_type, producer.input_format);
  Request replay = request;
  replay.operation = producer.id;
  replay.inputs = {source};
  const auto reference = compute_report(replay);
  const bool schema =
      candidate.is_object() && candidate.value("schema_version", 0) == 1 &&
      candidate.value("analysis_kind", "") == producer.kind &&
      candidate.contains("source") && candidate.contains("results") &&
      candidate.contains("validation");
  if (!schema) {
    throw WorkerError("VALIDATION_FAILED", "REPORT_SCHEMA_MISMATCH",
                      "Spatial candidate does not satisfy report schema");
  }
  if (candidate.at("source") != source_descriptor(source)) {
    throw WorkerError("VALIDATION_FAILED", "REPORT_IDENTITY_MISMATCH",
                      "Spatial candidate is not bound to the source artifact");
  }
  if (candidate != reference) {
    throw WorkerError("VALIDATION_FAILED", "REPORT_SEMANTICS_MISMATCH",
                      "Spatial candidate differs from independent CGAL replay");
  }
  Json checks = {{"schema_valid", true},
                 {"source_identity_matches", true},
                 {"analysis_kind_matches", true},
                 {"result_semantics_valid", true},
                 {"official_cgal_reference_match", true}};
  return write_validation(request, producer, checks);
}

OperationDefinition analysis_definition(const Profile& profile) {
  const auto p = profile;
  OperationDefinition definition{
      p.id,
      1,
      {p.input_type},
      "GeometryAnalysisReport",
      "analysis",
      [p](const Request& request) { return write_analysis(request, compute_report(request)); }};
  definition.supported_kernels =
      (p.id == "spatial.kdtree.range" ||
       p.id == "spatial.nearest_neighbors")
          ? std::vector<std::string>{"package_recommended"}
          : std::vector<std::string>{"exact_constructions",
                                     "package_recommended"};
  definition.effective_kernel =
      (p.id == "spatial.kdtree.range" ||
       p.id == "spatial.nearest_neighbors")
          ? "CGAL::Exact_predicates_inexact_constructions_kernel"
          : "CGAL::Exact_predicates_exact_constructions_kernel";
  definition.dependencies =
      (p.id == "spatial.kdtree.range" ||
       p.id == "spatial.nearest_neighbors")
          ? std::vector<std::string>{"Spatial_searching"}
          : (p.id == "spatial.bounding_box"
                 ? std::vector<std::string>{"Principal_component_analysis_LGPL"}
                 : std::vector<std::string>{"AABB_tree", "Surface_mesh"});
  Json bindings = Json::object();
  Json parameter_bindings = Json::object();
  for (const auto& name : p.parameter_names)
    parameter_bindings[name] = name;
  bindings[p.validator_id] = {{"candidate", {{"output", "analysis"}}},
                              {"source", {{"input", "source"}}}};
  definition.info = {
      {"geometry_mutation", false},
      {"input_format", p.input_format},
      {"output_format", "json"},
      {"output_slot", "analysis"},
      {"max_report_bytes", kMaxReportBytes},
      {"validators", {p.validator_id}},
      {"validator_artifact_bindings", bindings},
      {"validator_parameter_bindings",
       {{p.validator_id, parameter_bindings}}},
      {"source_version", "6.2.1"},
      {"source_kind", "official_release"}};
  return definition;
}

OperationDefinition validator_definition(const Profile& producer) {
  const auto p = producer;
  OperationDefinition definition{
      p.validator_id,
      1,
      {"GeometryAnalysisReport", p.input_type},
      "ValidationReport",
      "validator",
      [p](const Request& request) { return validate(request, p); }};
  definition.supported_kernels =
      (p.id == "spatial.kdtree.range" ||
       p.id == "spatial.nearest_neighbors")
          ? std::vector<std::string>{"package_recommended"}
          : std::vector<std::string>{"exact_constructions",
                                     "package_recommended"};
  definition.effective_kernel =
      (p.id == "spatial.kdtree.range" ||
       p.id == "spatial.nearest_neighbors")
          ? "CGAL::Exact_predicates_inexact_constructions_kernel"
          : "CGAL::Exact_predicates_exact_constructions_kernel";
  definition.dependencies =
      (p.id == "spatial.kdtree.range" ||
       p.id == "spatial.nearest_neighbors")
          ? std::vector<std::string>{"Spatial_searching"}
          : (p.id == "spatial.bounding_box"
                 ? std::vector<std::string>{"Bounding_box"}
                 : std::vector<std::string>{"AABB_tree", "Surface_mesh"});
  definition.info = {
      {"validates", p.id},
      {"candidate_report_schema", "GeometryAnalysisReport/v1"},
      {"report_schema", "ValidationReport/v1"},
      {"required_report_checks",
       {{"schema_version", 1},
        {"status", "pass"},
        {"passed", true},
        {"checks.schema_valid", true},
        {"checks.source_identity_matches", true},
        {"checks.analysis_kind_matches", true},
        {"checks.result_semantics_valid", true},
        {"checks.official_cgal_reference_match", true}}},
      {"source_version", "6.2.1"},
      {"source_kind", "official_release"}};
  return definition;
}

}  // namespace

Json analysis_reference_report(const std::string& operation_id,
                               const Request& source_request) {
  Request replay = source_request;
  replay.operation = operation_id;
  return compute_report(replay);
}

OperationDefinition aabb_closest_point_operation() {
  return analysis_definition(profile_for("spatial.aabb.closest_point"));
}
OperationDefinition kdtree_range_operation() {
  return analysis_definition(profile_for("spatial.kdtree.range"));
}
OperationDefinition nearest_neighbors_operation() {
  return analysis_definition(profile_for("spatial.nearest_neighbors"));
}
OperationDefinition intersection_candidates_operation() {
  return analysis_definition(profile_for("spatial.intersection_candidates"));
}
OperationDefinition bounding_box_operation() {
  return analysis_definition(profile_for("spatial.bounding_box"));
}
OperationDefinition validate_aabb_closest_point_operation() {
  return validator_definition(profile_for("spatial.aabb.closest_point"));
}
OperationDefinition validate_kdtree_range_operation() {
  return validator_definition(profile_for("spatial.kdtree.range"));
}
OperationDefinition validate_nearest_neighbors_operation() {
  return validator_definition(profile_for("spatial.nearest_neighbors"));
}
OperationDefinition validate_intersection_candidates_operation() {
  return validator_definition(profile_for("spatial.intersection_candidates"));
}
OperationDefinition validate_bounding_box_operation() {
  return validator_definition(profile_for("spatial.bounding_box"));
}

}  // namespace cgal_master::wave_c_spatial
