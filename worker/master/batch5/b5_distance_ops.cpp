// Producers wrapping CGAL 6.2.1 Polygon_mesh_processing distance functions (7.3.06):
// sample_triangle_mesh, max_distance_to_triangle_mesh, approximate_Hausdorff_distance,
// approximate_symmetric_Hausdorff_distance, approximate_max_distance_to_point_set and
// bounded_error_Hausdorff_distance. bounded_error_symmetric_Hausdorff_distance stays in the existing
// validator mesh.distance.symmetric_hausdorff. Every result is checked by an independent validator in
// b5_distance_validators.cpp (no CGAL header). Random sampling is seeded explicitly so results repeat.

#include "b5_common.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygon_mesh_processing/distance.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/tags.h>

#include <cmath>
#include <iterator>
#include <set>

namespace cgal_master::batch5 {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;
using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using Mesh = CGAL::Surface_mesh<Epick::Point_3>;
constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";

using batch2::geometry_frame;
using batch2::pinfo;
using query_ops::precondition;
using query_ops::RawMesh;
using query_ops::read_points3;
using query_ops::read_raw_mesh;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::write_report;

RawMesh load(const ArtifactInput& input) {
  auto raw = read_raw_mesh(input, {"TriangleSurfaceMesh"});
  if (raw.faces.empty() || raw.faces.size() > kMaximumDistanceFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "Between 1 and 400 triangles per mesh are supported");
  }
  for (const auto& face : raw.faces) {
    if (face.size() != 3) precondition("MESH_NOT_TRIANGULATED", "Input meshes must be triangulated");
  }
  return raw;
}

Mesh build(const RawMesh& raw) {
  Mesh mesh;
  std::vector<Mesh::Vertex_index> handles;
  for (const auto& v : raw.vertices) handles.push_back(mesh.add_vertex(Epick::Point_3(v[0], v[1], v[2])));
  std::size_t expected = 0;
  for (const auto& face : raw.faces) {
    const std::set<std::size_t> distinct(face.begin(), face.end());
    if (distinct.size() != 3) precondition("DEGENERATE_FACE", "A face repeats a vertex");
    const auto added = mesh.add_face(handles[face[0]], handles[face[1]], handles[face[2]]);
    if (added == Mesh::null_face() || static_cast<std::size_t>(added.idx()) != expected) {
      precondition("INVALID_POLYGON_MESH", "Faces are not a manifold, consistently oriented mesh indexable in file order");
    }
    ++expected;
  }
  for (const auto f : mesh.faces()) {
    const auto h = mesh.halfedge(f);
    if (CGAL::collinear(mesh.point(mesh.source(h)), mesh.point(mesh.target(h)), mesh.point(mesh.target(mesh.next(h))))) {
      precondition("DEGENERATE_FACE", "A face has zero area");
    }
  }
  return mesh;
}

double diagonal_of(const RawMesh& raw) {
  double low[3], high[3];
  for (int a = 0; a < 3; ++a) low[a] = high[a] = raw.vertices.at(0)[a];
  for (const auto& v : raw.vertices) {
    for (int a = 0; a < 3; ++a) {
      low[a] = std::min(low[a], v[a]);
      high[a] = std::max(high[a], v[a]);
    }
  }
  return std::sqrt((high[0] - low[0]) * (high[0] - low[0]) + (high[1] - low[1]) * (high[1] - low[1]) +
                   (high[2] - low[2]) * (high[2] - low[2]));
}

// Calls f(np) with the CGAL named parameters of the requested sampling method.
template <typename F>
auto with_sampling(const SamplingSpec& spec, F&& f) {
  namespace P = CGAL::parameters;
  if (spec.grid) {
    return f(P::use_grid_sampling(true).grid_spacing(spec.grid_spacing).do_sample_vertices(spec.include_vertices));
  }
  // CGAL 6.2.1 draws the edge samples from the process-wide default Random, not from the random_seed named
  // parameter, so the same request would otherwise return different edge points on every run. Reseeding the
  // default generator with the request seed makes the whole sample reproducible.
  CGAL::get_default_random() = CGAL::Random(static_cast<unsigned int>(spec.seed));
  return f(P::use_random_uniform_sampling(true)
               .random_seed(static_cast<unsigned int>(spec.seed))
               .number_of_points_on_faces(spec.points_on_faces)
               .number_of_points_on_edges(spec.points_on_edges)
               .do_sample_vertices(spec.include_vertices));
}

SamplingSpec checked_sampling(const Request& request, const RawMesh& raw) {
  const auto spec = parse_sampling(request.parameters.at("sampling"), request.inputs[0].unit);
  if (spec.grid && spec.grid_spacing < diagonal_of(raw) / 200.0) {
    throw WorkerError("RESOURCE_LIMIT", "SAMPLE_COUNT", "grid_spacing must be at least 1/200 of the mesh diagonal");
  }
  return spec;
}

Json distance_report(const Request& request, const std::string& kind, Json source, Json summary, double distance) {
  Json report = geometry_frame(request, kind, request.parameters, std::move(source), std::move(summary),
                               {{"distance", distance}, {"distance_unit", request.inputs[0].unit}});
  return report;
}

Json finish(const Request& request, const Json& report, Json metrics) {
  auto output = write_report(request, "GeometryQueryReport", report);
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

void check_finite(double value) {
  if (!std::isfinite(value)) throw WorkerError("NUMERIC_FAILURE", "NON_FINITE_DISTANCE", "CGAL returned a non-finite distance");
}

Json sample_points(const Request& request) {
  require_inputs(request, 1, "mesh.distance.sample_points");
  require_parameter_names(request, {"sampling"});
  const auto raw = load(request.inputs[0]);
  const auto spec = checked_sampling(request, raw);
  const auto mesh = build(raw);
  std::vector<Epick::Point_3> points;
  with_sampling(spec, [&](const auto& np) {
    PMP::sample_triangle_mesh(mesh, std::back_inserter(points), np);
    return 0;
  });
  if (points.size() > kMaximumSamplePoints) {
    throw WorkerError("RESOURCE_LIMIT", "SAMPLE_COUNT", "The sampling produced too many points");
  }
  Json list = Json::array();
  for (const auto& p : points) list.push_back(Json::array({p.x(), p.y(), p.z()}));
  Json report = geometry_frame(request, "mesh_samples", request.parameters, {{"mesh_sha256", request.inputs[0].sha256}},
                               {{"point_count", points.size()}}, {{"points", list}, {"length_unit", request.inputs[0].unit}});
  return finish(request, report, {{"point_count", points.size()}, {"algorithm", "CGAL::Polygon_mesh_processing::sample_triangle_mesh"}});
}

Json max_to_mesh(const Request& request) {
  require_inputs(request, 2, "mesh.distance.max_to_mesh");
  require_parameter_names(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto raw_points = read_points3(request.inputs[0]);
  if (raw_points.empty() || raw_points.size() > kMaximumDistancePoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_COUNT", "Between 1 and 2000 points are supported");
  }
  const auto raw = load(request.inputs[1]);
  const auto mesh = build(raw);
  std::vector<Epick::Point_3> points;
  for (const auto& p : raw_points) points.emplace_back(p[0], p[1], p[2]);
  const double distance = PMP::max_distance_to_triangle_mesh<CGAL::Sequential_tag>(points, mesh);
  check_finite(distance);
  auto report = distance_report(request, "max_distance_to_mesh",
                                {{"points_sha256", request.inputs[0].sha256}, {"mesh_sha256", request.inputs[1].sha256}},
                                {{"point_count", points.size()}, {"face_count", raw.faces.size()}}, distance);
  return finish(request, report, {{"distance", distance}, {"algorithm", "CGAL::Polygon_mesh_processing::max_distance_to_triangle_mesh"}});
}

Json hausdorff(const Request& request, bool symmetric) {
  const std::string name = symmetric ? "mesh.distance.hausdorff_approximate_symmetric" : "mesh.distance.hausdorff_approximate";
  require_inputs(request, 2, name);
  require_parameter_names(request, {"sampling"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto first = load(request.inputs[0]);
  const auto second = load(request.inputs[1]);
  const auto spec = checked_sampling(request, first);
  if (symmetric && spec.grid && spec.grid_spacing < diagonal_of(second) / 200.0) {
    throw WorkerError("RESOURCE_LIMIT", "SAMPLE_COUNT", "grid_spacing must be at least 1/200 of the second mesh diagonal");
  }
  const auto a = build(first);
  const auto b = build(second);
  const double distance = with_sampling(spec, [&](const auto& np) {
    return symmetric ? PMP::approximate_symmetric_Hausdorff_distance<CGAL::Sequential_tag>(a, b, np, np)
                     : PMP::approximate_Hausdorff_distance<CGAL::Sequential_tag>(a, b, np);
  });
  check_finite(distance);
  auto report = distance_report(request, symmetric ? "hausdorff_approximate_symmetric" : "hausdorff_approximate",
                                {{"first_sha256", request.inputs[0].sha256}, {"second_sha256", request.inputs[1].sha256}},
                                {{"first_face_count", first.faces.size()}, {"second_face_count", second.faces.size()}}, distance);
  return finish(request, report,
                {{"distance", distance},
                 {"algorithm", symmetric ? "CGAL::Polygon_mesh_processing::approximate_symmetric_Hausdorff_distance"
                                         : "CGAL::Polygon_mesh_processing::approximate_Hausdorff_distance"}});
}

Json hausdorff_one_sided(const Request& request) { return hausdorff(request, false); }
Json hausdorff_symmetric(const Request& request) { return hausdorff(request, true); }

Json max_to_points(const Request& request) {
  require_inputs(request, 2, "mesh.distance.max_to_points");
  require_parameter_names(request, {"precision"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto raw = load(request.inputs[0]);
  const auto raw_points = read_points3(request.inputs[1]);
  if (raw_points.empty() || raw_points.size() > kMaximumDistancePoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_COUNT", "Between 1 and 2000 points are supported");
  }
  const double precision = positive_length(request.parameters.at("precision"), "precision", request.inputs[0].unit);
  if (precision < diagonal_of(raw) * 1e-6) {
    throw WorkerError("RESOURCE_LIMIT", "PRECISION_TOO_FINE", "precision must be at least 1e-6 of the mesh diagonal");
  }
  const auto mesh = build(raw);
  std::vector<Epick::Point_3> points;
  for (const auto& p : raw_points) points.emplace_back(p[0], p[1], p[2]);
  const double distance = PMP::approximate_max_distance_to_point_set(mesh, points, precision);
  check_finite(distance);
  auto report = distance_report(request, "max_distance_to_points",
                                {{"mesh_sha256", request.inputs[0].sha256}, {"points_sha256", request.inputs[1].sha256}},
                                {{"face_count", raw.faces.size()}, {"point_count", points.size()}}, distance);
  return finish(request, report, {{"distance", distance}, {"algorithm", "CGAL::Polygon_mesh_processing::approximate_max_distance_to_point_set"}});
}

Json hausdorff_bounded(const Request& request) {
  require_inputs(request, 2, "mesh.distance.hausdorff_bounded");
  require_parameter_names(request, {"error_bound"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto first = load(request.inputs[0]);
  const auto second = load(request.inputs[1]);
  const double error_bound = positive_length(request.parameters.at("error_bound"), "error_bound", request.inputs[0].unit);
  const auto a = build(first);
  const auto b = build(second);
  const double distance = PMP::bounded_error_Hausdorff_distance<CGAL::Sequential_tag>(a, b, error_bound);
  check_finite(distance);
  auto report = distance_report(request, "hausdorff_bounded",
                                {{"first_sha256", request.inputs[0].sha256}, {"second_sha256", request.inputs[1].sha256}},
                                {{"first_face_count", first.faces.size()}, {"second_face_count", second.faces.size()}}, distance);
  return finish(request, report, {{"distance", distance}, {"algorithm", "CGAL::Polygon_mesh_processing::bounded_error_Hausdorff_distance"}});
}

}  // namespace

std::vector<OperationDefinition> distance_producers() {
  using query_ops::query_definition;
  const Json extra_base{{"source_header", "CGAL/Polygon_mesh_processing/distance.h"}, {"maximum_input_faces", kMaximumDistanceFaces}};
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.distance.sample_points", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", sample_points,
      {"Polygon_mesh_processing", "Surface_mesh"}, kEpickName,
      pinfo("mesh.validate.distance_samples", {"sampling"}, {"mesh"}, extra_base)));
  result.push_back(query_definition(
      "mesh.distance.max_to_mesh", {"PointSet3", "TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", max_to_mesh,
      {"Polygon_mesh_processing", "Surface_mesh"}, kEpickName,
      pinfo("mesh.validate.max_distance_to_mesh", {}, {"points", "mesh"}, extra_base)));
  result.push_back(query_definition(
      "mesh.distance.hausdorff_approximate", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "GeometryQueryReport",
      "analysis", hausdorff_one_sided, {"Polygon_mesh_processing", "Surface_mesh"}, kEpickName,
      pinfo("mesh.validate.hausdorff_report", {"sampling"}, {"first", "second"}, extra_base)));
  result.push_back(query_definition(
      "mesh.distance.hausdorff_approximate_symmetric", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "GeometryQueryReport",
      "analysis", hausdorff_symmetric, {"Polygon_mesh_processing", "Surface_mesh"}, kEpickName,
      pinfo("mesh.validate.hausdorff_report", {"sampling"}, {"first", "second"}, extra_base)));
  result.push_back(query_definition(
      "mesh.distance.max_to_points", {"TriangleSurfaceMesh", "PointSet3"}, "GeometryQueryReport", "analysis", max_to_points,
      {"Polygon_mesh_processing", "Surface_mesh"}, kEpickName,
      pinfo("mesh.validate.max_distance_to_points", {"precision"}, {"mesh", "points"}, extra_base)));
  result.push_back(query_definition(
      "mesh.distance.hausdorff_bounded", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis",
      hausdorff_bounded, {"Polygon_mesh_processing", "Surface_mesh"}, kEpickName,
      pinfo("mesh.validate.hausdorff_report", {"error_bound"}, {"first", "second"}, extra_base)));
  return result;
}

}  // namespace cgal_master::batch5
