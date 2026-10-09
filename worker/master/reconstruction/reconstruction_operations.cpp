// Surface reconstruction producers (family 7.10). Each wraps one official CGAL
// 6.2.1 entry point and publishes a TriangleSurfaceMesh candidate only after its
// independent validator (reconstruction_validators.cpp) passes.
//   reconstruction.poisson         Poisson_surface_reconstruction_3
//   reconstruction.poisson_delaunay poisson_surface_reconstruction_delaunay (7.10.01 convenience function; in
//                                  6.2.1 it always appends manifold_with_boundary(), so the result may have
//                                  boundary edges even on closed inputs: its validator accepts a manifold
//                                  WITH boundary and never claims a closed surface)
//   reconstruction.advancing_front Advancing_front_surface_reconstruction
//   reconstruction.scale_space     Scale_space_reconstruction_3
//   reconstruction.alpha_wrap      Alpha_wrap_3

#include "reconstruction_common.h"

#include "../wave_c/wave_c_common.h"
#include "../wave_d/wave_d_common.h"

#include <CGAL/Advancing_front_surface_reconstruction.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Scale_space_reconstruction_3/Advancing_front_mesher.h>
#include <CGAL/Scale_space_reconstruction_3/Jet_smoother.h>
#include <CGAL/Scale_space_surface_reconstruction_3.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/alpha_wrap_3.h>
#include <CGAL/compute_average_spacing.h>
#include <CGAL/Mesh_complex_3_in_triangulation_3.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/Mesh_criteria_3.h>
#include <CGAL/Mesh_triangulation_3.h>
#include <CGAL/Poisson_mesh_domain_3.h>
#include <CGAL/Poisson_reconstruction_function.h>
#include <CGAL/facets_in_complex_3_to_triangle_mesh.h>
#include <CGAL/make_mesh_3.h>
#include <CGAL/poisson_surface_reconstruction.h>
#include <CGAL/property_map.h>

#include <algorithm>
#include <cmath>
#include <limits>
#include <map>
#include <set>
#include <utility>
#include <vector>

namespace cgal_master::reconstruction_ops {
namespace {

using Kernel = CGAL::Exact_predicates_inexact_constructions_kernel;
using Point = Kernel::Point_3;
using Vector = Kernel::Vector_3;
using Mesh = CGAL::Surface_mesh<Point>;
using Facet = std::array<std::size_t, 3>;

constexpr std::size_t kAverageSpacingNeighbors = 6;
constexpr double kMaximumExtentToAlpha = 200.0;

std::vector<Point> cgal_points(const PointCloud& cloud) {
  std::vector<Point> points;
  points.reserve(cloud.points.size());
  for (const auto& p : cloud.points) points.emplace_back(p[0], p[1], p[2]);
  return points;
}

double bbox_diagonal(const PointCloud& cloud) {
  V3 low = cloud.points[0], high = cloud.points[0];
  for (const auto& p : cloud.points) {
    for (int k = 0; k < 3; ++k) {
      low[k] = std::min(low[k], p[k]);
      high[k] = std::max(high[k], p[k]);
    }
  }
  return std::sqrt((high[0] - low[0]) * (high[0] - low[0]) + (high[1] - low[1]) * (high[1] - low[1]) +
                   (high[2] - low[2]) * (high[2] - low[2]));
}

void require_output_budget(const Mesh& mesh) {
  if (mesh.number_of_faces() == 0) {
    precondition("EMPTY_RECONSTRUCTION", "The reconstruction produced no facets");
  }
  if (mesh.number_of_faces() > kMaximumOutputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "The reconstruction exceeds the bounded validation budget");
  }
}

// Builds a Surface_mesh whose vertices are the referenced input points (in
// ascending input order, coordinates unchanged) and whose faces are the facets.
Mesh mesh_from_facets(const std::vector<Point>& points, const std::vector<Facet>& facets) {
  std::map<std::size_t, Mesh::Vertex_index> used;
  for (const auto& facet : facets) {
    for (const auto index : facet) {
      if (index >= points.size()) throw WorkerError("INTERNAL", "FACET_INDEX_OUT_OF_RANGE", "Bad facet index");
      used.emplace(index, Mesh::Vertex_index());
    }
  }
  // A closed result whose facets are consistently oriented inward is reversed as a
  // whole (CGAL's advancing-front facets are consistently but not outwardly
  // oriented); the validator re-checks the orientation in exact arithmetic.
  std::vector<Facet> oriented = facets;
  double volume6 = 0;
  for (const auto& f : facets) {
    const auto& a = points[f[0]];
    const auto& b = points[f[1]];
    const auto& c = points[f[2]];
    volume6 += a.x() * (b.y() * c.z() - b.z() * c.y()) - a.y() * (b.x() * c.z() - b.z() * c.x()) +
               a.z() * (b.x() * c.y() - b.y() * c.x());
  }
  if (volume6 < 0) {
    for (auto& f : oriented) std::swap(f[1], f[2]);
  }
  // Canonical facet order (each facet rotated to start at its smallest index,
  // orientation kept): the advancing-front facet emission order is not
  // reproducible between runs, the facet set is.
  for (auto& f : oriented) {
    while (f[0] > f[1] || f[0] > f[2]) f = {f[1], f[2], f[0]};
  }
  std::sort(oriented.begin(), oriented.end());
  Mesh mesh;
  for (auto& entry : used) entry.second = mesh.add_vertex(points[entry.first]);
  for (const auto& facet : oriented) {
    if (mesh.add_face(used.at(facet[0]), used.at(facet[1]), used.at(facet[2])) == Mesh::null_face()) {
      precondition("NON_MANIFOLD_RECONSTRUCTION",
                   "The reconstructed facets do not form an oriented 2-manifold surface");
    }
  }
  return mesh;
}

double signed_volume_times_six(const Mesh& mesh) {
  double total = 0;
  for (const auto face : mesh.faces()) {
    std::array<Point, 3> p;
    int k = 0;
    for (const auto v : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      if (k < 3) p[k] = mesh.point(v);
      ++k;
    }
    total += CGAL::to_double(CGAL::determinant(p[0] - CGAL::ORIGIN, p[1] - CGAL::ORIGIN, p[2] - CGAL::ORIGIN));
  }
  return total;
}

Json mesh_metrics(const Mesh& mesh, const std::string& algorithm, std::size_t point_count) {
  std::size_t border = 0;
  for (const auto halfedge : mesh.halfedges()) border += mesh.is_border(halfedge) ? 1 : 0;
  const auto v = static_cast<long long>(mesh.number_of_vertices());
  const auto e = static_cast<long long>(mesh.number_of_edges());
  const auto f = static_cast<long long>(mesh.number_of_faces());
  return Json{{"algorithm", algorithm},
              {"point_count", point_count},
              {"vertex_count", v},
              {"facet_count", f},
              {"edge_count", e},
              {"boundary_edge_count", border},
              {"euler_characteristic", v - e + f},
              {"effective_kernel", kEpick}};
}

struct PoissonInput {
  PointCloud cloud;
  std::vector<std::pair<Point, Vector>> points;
  double spacing = 0;
  double angle = 0, radius = 0, distance = 0;
};

using PointNormal = std::pair<Point, Vector>;

PoissonInput prepare_poisson(const Request& request, const std::string& operation, bool delaunay = false) {
  require_inputs(request, 1, operation);
  if (delaunay) {
    require_parameter_names(request, {"sm_angle", "sm_radius", "sm_distance", "max_deviation", "max_circumradius", "min_coverage"});
    length_parameter(request, "max_circumradius", request.inputs[0].unit);  // enforced by the mandatory validator
    number_parameter(request, "min_coverage", 0.0, 1.0);                    // enforced by the mandatory validator
  } else {
    require_parameter_names(request, {"sm_angle", "sm_radius", "sm_distance", "max_deviation"});
  }
  const auto& source = request.inputs[0];
  PoissonInput input;
  input.cloud = read_points_with_normals(source);
  require_point_budget(input.cloud);
  for (const auto& n : input.cloud.normals) {
    if (!(n[0] * n[0] + n[1] * n[1] + n[2] * n[2] > 0)) {
      precondition("ZERO_NORMAL", "Poisson reconstruction needs a nonzero oriented normal at every point");
    }
  }
  input.angle = number_parameter(request, "sm_angle", 0.0, 30.0);
  input.radius = number_parameter(request, "sm_radius", 0.0, 100.0);
  input.distance = number_parameter(request, "sm_distance", 0.0, 10.0);
  length_parameter(request, "max_deviation", source.unit);  // enforced by the mandatory validator
  for (std::size_t i = 0; i < input.cloud.points.size(); ++i) {
    const auto& p = input.cloud.points[i];
    const auto& n = input.cloud.normals[i];
    input.points.emplace_back(Point(p[0], p[1], p[2]), Vector(n[0], n[1], n[2]));
  }
  input.spacing = CGAL::compute_average_spacing<CGAL::Sequential_tag>(
      input.points, kAverageSpacingNeighbors,
      CGAL::parameters::point_map(CGAL::First_of_pair_property_map<PointNormal>()));
  if (!(input.spacing > 0) || !std::isfinite(input.spacing)) {
    precondition("DEGENERATE_POINT_SET", "The average point spacing is not positive");
  }
  return input;
}

// An open Poisson surface may consist of several components (stray patches next to the main sheet), each
// consistently oriented but with its own sign. Every component is turned to agree with the oriented source
// normals: up to kVoteFaces evenly strided facets per component vote with the sign of the dot product of
// their normal and the normal of the source point nearest to their centroid. Returns the number of
// components reversed. The independent validator re-checks the result against every source normal.
constexpr std::size_t kVoteFaces = 256;

std::size_t orient_components_by_normals(Mesh& mesh, const PointCloud& cloud) {
  std::vector<std::size_t> parent(mesh.number_of_vertices());
  for (std::size_t i = 0; i < parent.size(); ++i) parent[i] = i;
  const auto find = [&](std::size_t x) {
    while (parent[x] != x) x = parent[x] = parent[parent[x]];
    return x;
  };
  for (const auto face : mesh.faces()) {
    std::size_t first = 0;
    bool have = false;
    for (const auto v : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      const auto index = static_cast<std::size_t>(v);
      if (!have) {
        first = index;
        have = true;
      } else {
        parent[find(index)] = find(first);
      }
    }
  }
  std::map<std::size_t, std::vector<Mesh::Face_index>> components;
  for (const auto face : mesh.faces()) {
    components[find(static_cast<std::size_t>(mesh.target(mesh.halfedge(face))))].push_back(face);
  }
  std::size_t reversed = 0;
  for (const auto& entry : components) {
    const auto& faces = entry.second;
    const std::size_t stride = std::max<std::size_t>(1, faces.size() / kVoteFaces);
    long long vote = 0;
    for (std::size_t k = 0; k < faces.size(); k += stride) {
      std::array<Point, 3> p;
      int count = 0;
      for (const auto v : CGAL::vertices_around_face(mesh.halfedge(faces[k]), mesh)) {
        if (count < 3) p[count] = mesh.point(v);
        ++count;
      }
      const Vector n = CGAL::cross_product(p[1] - p[0], p[2] - p[0]);
      const double cx = CGAL::to_double(p[0].x() + p[1].x() + p[2].x()) / 3;
      const double cy = CGAL::to_double(p[0].y() + p[1].y() + p[2].y()) / 3;
      const double cz = CGAL::to_double(p[0].z() + p[1].z() + p[2].z()) / 3;
      std::size_t best = 0;
      double best_distance = std::numeric_limits<double>::infinity();
      for (std::size_t i = 0; i < cloud.points.size(); ++i) {
        const double dx = cloud.points[i][0] - cx, dy = cloud.points[i][1] - cy, dz = cloud.points[i][2] - cz;
        const double d = dx * dx + dy * dy + dz * dz;
        if (d < best_distance) {
          best_distance = d;
          best = i;
        }
      }
      const auto& sn = cloud.normals[best];
      const double dot = CGAL::to_double(n.x()) * sn[0] + CGAL::to_double(n.y()) * sn[1] + CGAL::to_double(n.z()) * sn[2];
      vote += dot > 0 ? 1 : (dot < 0 ? -1 : 0);
    }
    if (vote < 0) {
      CGAL::Polygon_mesh_processing::reverse_face_orientations(faces, mesh);
      ++reversed;
    }
  }
  return reversed;
}

Json poisson_result(const Request& request, Mesh& mesh, const PoissonInput& input,
                    const std::string& algorithm, const std::string& mesh_3_options, bool open_surface = false) {
  // The surface is consistently but not always outward oriented; a negative enclosed
  // volume (open surfaces: each component by its source-normal vote) is reversed
  // (re-checked exactly by the validator).
  std::size_t reversed_components = 0;
  bool reversed = false;
  if (open_surface) {
    reversed_components = orient_components_by_normals(mesh, input.cloud);
    reversed = reversed_components > 0;
  } else {
    reversed = signed_volume_times_six(mesh) < 0;
    if (reversed) CGAL::Polygon_mesh_processing::reverse_face_orientations(mesh);
  }
  require_output_budget(mesh);
  auto metrics = mesh_metrics(mesh, algorithm, input.cloud.points.size());
  metrics["average_spacing"] = input.spacing;
  metrics["average_spacing_neighbors"] = kAverageSpacingNeighbors;
  metrics["spacing_function"] = "CGAL::compute_average_spacing";
  metrics["sm_angle"] = input.angle;
  metrics["sm_radius"] = input.radius;
  metrics["sm_distance"] = input.distance;
  metrics["orientation_reversed"] = reversed;
  if (open_surface) metrics["reversed_component_count"] = reversed_components;
  metrics["mesh_3_options"] = mesh_3_options;
  auto output = wave_d::write_mesh_candidate(request, mesh, request.inputs[0].unit);
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json run_poisson(const Request& request) {
  const auto input = prepare_poisson(request, "reconstruction.poisson");
  const auto& points = input.points;
  const double spacing = input.spacing;
  const double angle = input.angle, radius = input.radius, distance = input.distance;
  const auto point_map = CGAL::First_of_pair_property_map<PointNormal>();
  const auto normal_map = CGAL::Second_of_pair_property_map<PointNormal>();
  // The Poisson_surface_reconstruction_3 pipeline of the CGAL user manual
  // (poisson_reconstruction_example.cpp): implicit function, Poisson_mesh_domain_3
  // and a surface-only make_mesh_3. The convenience function
  // poisson_surface_reconstruction_delaunay always forces Mesh_3's
  // manifold_with_boundary option, which leaves holes on sparse closed inputs;
  // here the closed manifold() option is requested instead.
  using Function = CGAL::Poisson_reconstruction_function<Kernel>;
  using Domain = CGAL::Poisson_mesh_domain_3<Kernel>;
  using Tr = CGAL::Mesh_triangulation_3<Domain, CGAL::Default, CGAL::Sequential_tag>::type;
  using C3t3 = CGAL::Mesh_complex_3_in_triangulation_3<Tr>;
  using Criteria = CGAL::Mesh_criteria_3<Tr>;
  Function function(points.begin(), points.end(), point_map, normal_map);
  if (!function.compute_implicit_function()) {
    precondition("RECONSTRUCTION_FAILED", "The Poisson implicit function could not be solved");
  }
  const Point inner_point = function.get_inner_point();
  if (!(function(inner_point) < 0)) {
    precondition("RECONSTRUCTION_FAILED", "The Poisson implicit function has no interior seed point");
  }
  const auto bsphere = function.bounding_sphere();
  const double sphere_radius = 5.0 * std::sqrt(CGAL::to_double(bsphere.squared_radius()));
  const double dichotomy_error = distance * spacing / 1000.0;
  Domain domain = Domain::create_Poisson_mesh_domain(
      function, Kernel::Sphere_3(inner_point, sphere_radius * sphere_radius),
      CGAL::parameters::relative_error_bound(dichotomy_error / sphere_radius));
  Criteria criteria(CGAL::parameters::facet_angle = angle, CGAL::parameters::facet_size = radius * spacing,
                    CGAL::parameters::facet_distance = distance * spacing);
  const C3t3 c3t3 = CGAL::make_mesh_3<C3t3>(domain, criteria, CGAL::parameters::surface_only().manifold());
  if (c3t3.triangulation().number_of_vertices() == 0) {
    precondition("RECONSTRUCTION_FAILED", "Poisson surface meshing produced no vertices");
  }
  Mesh mesh;
  CGAL::facets_in_complex_3_to_triangle_mesh(c3t3, mesh);
  auto result = poisson_result(request, mesh, input, "CGAL::Poisson_reconstruction_function + CGAL::make_mesh_3",
                               "surface_only().manifold()");
  result["metrics"]["mesh_domain"] = "CGAL::Poisson_mesh_domain_3";
  return result;
}

Json run_poisson_delaunay(const Request& request) {
  const auto input = prepare_poisson(request, "reconstruction.poisson_delaunay", true);
  Mesh mesh;
  if (!CGAL::poisson_surface_reconstruction_delaunay(input.points.begin(), input.points.end(),
                                                     CGAL::First_of_pair_property_map<PointNormal>(),
                                                     CGAL::Second_of_pair_property_map<PointNormal>(), mesh,
                                                     input.spacing, input.angle, input.radius, input.distance)) {
    precondition("RECONSTRUCTION_FAILED", "poisson_surface_reconstruction_delaunay returned no surface");
  }
  if (mesh.number_of_faces() == 0) precondition("RECONSTRUCTION_FAILED", "The Poisson surface has no facets");
  auto result = poisson_result(request, mesh, input, "CGAL::poisson_surface_reconstruction_delaunay",
                               "manifold_with_boundary().surface_only() (forced by the 6.2.1 convenience function)", true);
  result["metrics"]["boundary_edges_are_disclosed_not_hidden"] = true;
  return result;
}

Json run_advancing_front(const Request& request) {
  require_inputs(request, 1, "reconstruction.advancing_front");
  require_parameter_names(request, {"radius_ratio_bound", "beta", "max_deviation"});
  const auto& source = request.inputs[0];
  const auto cloud = read_points(source);
  require_point_budget(cloud);
  const double radius_ratio_bound = number_parameter(request, "radius_ratio_bound", 0.0, 100.0);
  const double beta = number_parameter(request, "beta", 0.0, 1.5707963267948966);
  length_parameter(request, "max_deviation", source.unit);  // enforced by the mandatory validator
  const auto points = cgal_points(cloud);
  std::vector<Facet> facets;
  CGAL::advancing_front_surface_reconstruction(points.begin(), points.end(), std::back_inserter(facets),
                                               radius_ratio_bound, beta);
  if (facets.empty()) precondition("EMPTY_RECONSTRUCTION", "Advancing front produced no facets");
  auto mesh = mesh_from_facets(points, facets);
  require_output_budget(mesh);
  auto metrics = mesh_metrics(mesh, "CGAL::advancing_front_surface_reconstruction", cloud.points.size());
  metrics["radius_ratio_bound"] = radius_ratio_bound;
  metrics["beta"] = beta;
  metrics["unused_point_count"] = cloud.points.size() - mesh.number_of_vertices();
  auto output = wave_d::write_mesh_candidate(request, mesh, source.unit);
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json run_scale_space(const Request& request) {
  require_inputs(request, 1, "reconstruction.scale_space");
  require_parameter_names(request, {"iterations", "neighbors", "maximum_facet_length", "radius_ratio_bound",
                                    "beta", "max_deviation"});
  const auto& source = request.inputs[0];
  const auto cloud = read_points(source);
  require_point_budget(cloud);
  const auto iterations = integer_parameter(request, "iterations", 1, 10);
  const auto neighbors = integer_parameter(request, "neighbors", 6, 64);
  if (neighbors >= cloud.points.size()) {
    precondition("TOO_MANY_NEIGHBORS", "neighbors must be smaller than the point count");
  }
  const double maximum_facet_length = length_parameter(request, "maximum_facet_length", source.unit);
  const double radius_ratio_bound = number_parameter(request, "radius_ratio_bound", 0.0, 100.0);
  const double beta = number_parameter(request, "beta", 0.0, 1.5707963267948966);
  length_parameter(request, "max_deviation", source.unit);  // enforced by the mandatory validator
  const auto points = cgal_points(cloud);
  CGAL::Scale_space_surface_reconstruction_3<Kernel> reconstruct(points.begin(), points.end());
  reconstruct.increase_scale(iterations,
                             CGAL::Scale_space_reconstruction_3::Jet_smoother<Kernel>(
                                 static_cast<unsigned int>(neighbors)));
  reconstruct.reconstruct_surface(CGAL::Scale_space_reconstruction_3::Advancing_front_mesher<Kernel>(
      maximum_facet_length, radius_ratio_bound, beta));
  std::vector<Facet> facets;
  for (auto it = reconstruct.facets_begin(); it != reconstruct.facets_end(); ++it) {
    facets.push_back({(*it)[0], (*it)[1], (*it)[2]});
  }
  if (facets.empty()) precondition("EMPTY_RECONSTRUCTION", "Scale-space reconstruction produced no facets");
  // Facets index the input order; the mesh is published at the original (unsmoothed) positions.
  auto mesh = mesh_from_facets(points, facets);
  require_output_budget(mesh);
  auto metrics = mesh_metrics(mesh, "CGAL::Scale_space_surface_reconstruction_3", cloud.points.size());
  metrics["smoother"] = "CGAL::Scale_space_reconstruction_3::Jet_smoother";
  metrics["mesher"] = "CGAL::Scale_space_reconstruction_3::Advancing_front_mesher";
  metrics["output_positions"] = "original_input_points";
  metrics["iterations"] = iterations;
  metrics["neighbors"] = neighbors;
  metrics["unused_point_count"] = cloud.points.size() - mesh.number_of_vertices();
  auto output = wave_d::write_mesh_candidate(request, mesh, source.unit);
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json run_alpha_wrap(const Request& request) {
  require_inputs(request, 1, "reconstruction.alpha_wrap");
  require_parameter_names(request, {"alpha", "offset"});
  const auto& source = request.inputs[0];
  const auto cloud = read_points(source);
  if (cloud.points.empty()) precondition("TOO_FEW_POINTS", "Alpha wrapping needs a nonempty point set");
  {
    std::set<V3> seen(cloud.points.begin(), cloud.points.end());
    if (seen.size() != cloud.points.size()) precondition("DUPLICATE_POINT", "The point set repeats a point");
  }
  const double alpha = length_parameter(request, "alpha", source.unit);
  const double offset = length_parameter(request, "offset", source.unit);
  const double extent = std::max(bbox_diagonal(cloud), std::max(alpha, offset));
  if (extent / alpha > kMaximumExtentToAlpha || extent / offset > 10.0 * kMaximumExtentToAlpha) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "alpha or offset is too small relative to the input extent for bounded validation");
  }
  const auto points = cgal_points(cloud);
  Mesh mesh;
  CGAL::alpha_wrap_3(points, alpha, offset, mesh);
  require_output_budget(mesh);
  auto metrics = mesh_metrics(mesh, "CGAL::alpha_wrap_3", cloud.points.size());
  metrics["alpha"] = alpha;
  metrics["offset"] = offset;
  metrics["oracle"] = "CGAL::Alpha_wraps_3::internal::Point_set_oracle";
  auto output = wave_d::write_mesh_candidate(request, mesh, source.unit);
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> transform_operations() {
  std::vector<OperationDefinition> result;
  result.push_back(reconstruction_definition(
      "reconstruction.poisson", {"PointSet3Normals"}, "TriangleSurfaceMesh", "transform", run_poisson,
      {"Poisson_surface_reconstruction_3", "Mesh_3", "Point_set_processing_3", "Eigen3"},
      {{"source_header", "CGAL/Poisson_reconstruction_function.h"},
       {"symbols", {"Poisson_reconstruction_function", "Poisson_mesh_domain_3", "make_mesh_3",
                    "compute_average_spacing"}},
       {"input_format", "ascii_ply_with_x_y_z_nx_ny_nz"},
       {"output_format", "off"},
       {"required_parameters", {"sm_angle", "sm_radius", "sm_distance", "max_deviation"}},
       {"validators", {"reconstruction.validate.poisson"}},
       {"validator_parameter_bindings",
        {{"reconstruction.validate.poisson", {{"max_deviation", "max_deviation"}}}}}}));
  result.push_back(reconstruction_definition(
      "reconstruction.poisson_delaunay", {"PointSet3Normals"}, "TriangleSurfaceMesh", "transform",
      run_poisson_delaunay, {"Poisson_surface_reconstruction_3", "Mesh_3", "Point_set_processing_3", "Eigen3"},
      {{"source_header", "CGAL/poisson_surface_reconstruction.h"},
       {"symbols", {"poisson_surface_reconstruction_delaunay", "compute_average_spacing"}},
       {"input_format", "ascii_ply_with_x_y_z_nx_ny_nz"},
       {"output_format", "off"},
       {"required_parameters", {"sm_angle", "sm_radius", "sm_distance", "max_deviation", "max_circumradius", "min_coverage"}},
       {"validators", {"reconstruction.validate.poisson_boundary"}},
       {"validator_parameter_bindings",
        {{"reconstruction.validate.poisson_boundary",
          {{"max_deviation", "max_deviation"}, {"max_circumradius", "max_circumradius"}, {"min_coverage", "min_coverage"}}}}}}));
  result.push_back(reconstruction_definition(
      "reconstruction.advancing_front", {"PointSet3"}, "TriangleSurfaceMesh", "transform", run_advancing_front,
      {"Advancing_front_surface_reconstruction", "Triangulation_3"},
      {{"source_header", "CGAL/Advancing_front_surface_reconstruction.h"},
       {"symbols", {"advancing_front_surface_reconstruction"}},
       {"input_format", "xyz"},
       {"output_format", "off"},
       {"required_parameters", {"radius_ratio_bound", "beta", "max_deviation"}},
       {"validators", {"reconstruction.validate.interpolating"}},
       {"validator_parameter_bindings",
        {{"reconstruction.validate.interpolating", {{"max_deviation", "max_deviation"}}}}}}));
  result.push_back(reconstruction_definition(
      "reconstruction.scale_space", {"PointSet3"}, "TriangleSurfaceMesh", "transform", run_scale_space,
      {"Scale_space_reconstruction_3", "Advancing_front_surface_reconstruction", "Eigen3"},
      {{"source_header", "CGAL/Scale_space_surface_reconstruction_3.h"},
       {"symbols", {"Scale_space_surface_reconstruction_3", "Scale_space_reconstruction_3::Jet_smoother",
                    "Scale_space_reconstruction_3::Advancing_front_mesher"}},
       {"input_format", "xyz"},
       {"output_format", "off"},
       {"required_parameters",
        {"iterations", "neighbors", "maximum_facet_length", "radius_ratio_bound", "beta", "max_deviation"}},
       {"validators", {"reconstruction.validate.interpolating"}},
       {"validator_parameter_bindings",
        {{"reconstruction.validate.interpolating", {{"max_deviation", "max_deviation"}}}}}}));
  result.push_back(reconstruction_definition(
      "reconstruction.alpha_wrap", {"PointSet3"}, "TriangleSurfaceMesh", "transform", run_alpha_wrap,
      {"Alpha_wrap_3", "Triangulation_3"},
      {{"source_header", "CGAL/alpha_wrap_3.h"},
       {"symbols", {"alpha_wrap_3"}},
       {"input_format", "xyz"},
       {"output_format", "off"},
       {"required_parameters", {"alpha", "offset"}},
       {"maximum_extent_to_alpha", kMaximumExtentToAlpha},
       {"validators", {"reconstruction.validate.alpha_wrap"}},
       {"validator_parameter_bindings",
        {{"reconstruction.validate.alpha_wrap", {{"alpha", "alpha"}, {"offset", "offset"}}}}}}));
  return result;
}

}  // namespace cgal_master::reconstruction_ops
