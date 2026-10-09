// Polygonal surface reconstruction producer (7.10.02): CGAL::Polygonal_surface_reconstruction (PolyFit)
// with the SCIP mixed-integer solver (optional dependency). Supporting planes are detected from the
// oriented point set by CGAL region growing (Shape_detection) with the caller's pinned parameters;
// PolyFit then selects candidate faces by a mixed-integer program. The polygonal result is published
// as PolygonSoup3 only after reconstruction.validate.polygonal_surface passes (CGAL-free).

#include "b6_common.h"

#include "../artifact_io.h"
#include "../reconstruction/reconstruction_common.h"

#ifdef CGAL_MASTER_HAVE_SCIP
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygonal_surface_reconstruction.h>
#include <CGAL/SCIP_mixed_integer_program_traits.h>
#include <CGAL/Shape_detection/Region_growing/Point_set.h>
#include <CGAL/Shape_detection/Region_growing/Region_growing.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/property_map.h>
#include <boost/range/irange.hpp>
#include <boost/tuple/tuple.hpp>
#endif

#include <cmath>
#include <map>

namespace cgal_master::batch6 {
namespace {

using query_ops::precondition;
using query_ops::require_inputs;
using query_ops::require_parameter_names;

constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";

#ifdef CGAL_MASTER_HAVE_SCIP
using Kernel = CGAL::Exact_predicates_inexact_constructions_kernel;
using FT = Kernel::FT;
using Point = Kernel::Point_3;
using Vector = Kernel::Vector_3;
using PNI = boost::tuple<Point, Vector, int>;
using PointVector = std::vector<PNI>;
using PointMap = CGAL::Nth_of_tuple_property_map<0, PNI>;
using NormalMap = CGAL::Nth_of_tuple_property_map<1, PNI>;
using PlaneIndexMap = CGAL::Nth_of_tuple_property_map<2, PNI>;
using PointMapRg = CGAL::Compose_property_map<CGAL::Random_access_property_map<PointVector>, PointMap>;
using NormalMapRg = CGAL::Compose_property_map<CGAL::Random_access_property_map<PointVector>, NormalMap>;
using RegionType =
    CGAL::Shape_detection::Point_set::Least_squares_plane_fit_region<Kernel, std::size_t, PointMapRg, NormalMapRg>;
using NeighborQuery = CGAL::Shape_detection::Point_set::Sphere_neighbor_query<Kernel, std::size_t, PointMapRg>;
using RegionGrowing = CGAL::Shape_detection::Region_growing<NeighborQuery, RegionType>;
using SurfaceMesh = CGAL::Surface_mesh<Point>;
using Reconstruction = CGAL::Polygonal_surface_reconstruction<Kernel>;
using MipSolver = CGAL::SCIP_mixed_integer_program_traits<double>;
#endif

double weight_parameter(const Request& request, const char* name) {
  const auto& value = request.parameters.at(name);
  if (!value.is_number() || value.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be a number");
  }
  const double weight = value.get<double>();
  if (!std::isfinite(weight) || weight < 0 || weight > 1) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must lie in [0,1]");
  }
  return weight;
}

Json run_polygonal(const Request& request) {
  const std::string operation = "reconstruction.polygonal_surface";
  require_inputs(request, 1, operation);
  require_parameter_names(request, {"sphere_radius", "maximum_distance", "maximum_angle", "minimum_region_size",
                                    "fitting", "coverage", "complexity", "max_deviation", "planarity_tolerance"});
  const auto& source = request.inputs[0];
#ifdef CGAL_MASTER_HAVE_SCIP
  auto cloud = reconstruction_ops::read_points_with_normals(source);
  reconstruction_ops::require_point_budget(cloud);
  for (const auto& n : cloud.normals) {
    if (!(n[0] * n[0] + n[1] * n[1] + n[2] * n[2] > 0)) {
      precondition("ZERO_NORMAL", "Polygonal surface reconstruction needs a nonzero oriented normal at every point");
    }
  }
  if (reconstruction_ops::affine_rank(cloud.points) < 3) {
    precondition("DEGENERATE_POINT_SET", "The point set does not span space");
  }
  const double sphere_radius = reconstruction_ops::length_parameter(request, "sphere_radius", source.unit);
  const double maximum_distance = reconstruction_ops::length_parameter(request, "maximum_distance", source.unit);
  const double maximum_angle = reconstruction_ops::number_parameter(request, "maximum_angle", 0.0, 90.0);
  const auto minimum_region_size = reconstruction_ops::integer_parameter(request, "minimum_region_size", 3, 100000);
  const double fitting = weight_parameter(request, "fitting");
  const double coverage = weight_parameter(request, "coverage");
  const double complexity = weight_parameter(request, "complexity");
  if (!(fitting + coverage + complexity > 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "At least one model weight must be positive");
  }
  reconstruction_ops::length_parameter(request, "max_deviation", source.unit);        // validator-enforced
  reconstruction_ops::length_parameter(request, "planarity_tolerance", source.unit);  // validator-enforced

  PointVector points;
  points.reserve(cloud.points.size());
  for (std::size_t i = 0; i < cloud.points.size(); ++i) {
    const auto& p = cloud.points[i];
    const auto& n = cloud.normals[i];
    const double length = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
    points.emplace_back(Point(p[0], p[1], p[2]), Vector(n[0] / length, n[1] / length, n[2] / length), -1);
  }
  PointMapRg point_map_rg(CGAL::make_random_access_property_map(points));
  NormalMapRg normal_map_rg(CGAL::make_random_access_property_map(points));
  NeighborQuery neighbor_query(boost::irange<std::size_t>(0, points.size()),
                               CGAL::parameters::sphere_radius(sphere_radius).point_map(point_map_rg));
  RegionType region_type(CGAL::parameters::maximum_distance(maximum_distance)
                             .maximum_angle(maximum_angle)
                             .minimum_region_size(minimum_region_size)
                             .point_map(point_map_rg)
                             .normal_map(normal_map_rg));
  RegionGrowing region_growing(boost::irange<std::size_t>(0, points.size()), neighbor_query, region_type);
  std::vector<RegionGrowing::Primitive_and_region> regions;
  region_growing.detect(std::back_inserter(regions));
  if (regions.size() < 4) {
    precondition("TOO_FEW_PLANES", "Region growing found fewer than four supporting planes");
  }
  std::size_t assigned = 0;
  for (std::size_t i = 0; i < points.size(); ++i) {
    points[i].get<2>() = static_cast<int>(get(region_growing.region_map(), i));
    if (points[i].get<2>() >= 0) ++assigned;
  }
  Reconstruction algorithm(points, PointMap(), NormalMap(), PlaneIndexMap());
  SurfaceMesh model;
  if (!algorithm.reconstruct<MipSolver>(model, fitting, coverage, complexity)) {
    precondition("RECONSTRUCTION_FAILED", "Polygonal surface reconstruction failed: " + algorithm.error_message());
  }
  if (model.number_of_faces() == 0) precondition("EMPTY_RECONSTRUCTION", "The reconstruction produced no faces");
  if (model.number_of_faces() > kMaximumPolygonFaces) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED", "The reconstruction exceeds the face budget");
  }
  std::map<SurfaceMesh::Vertex_index, std::size_t> index;
  std::vector<V3> vertices;
  for (const auto v : model.vertices()) {
    index[v] = vertices.size();
    const auto& p = model.point(v);
    vertices.push_back({CGAL::to_double(p.x()), CGAL::to_double(p.y()), CGAL::to_double(p.z())});
  }
  std::vector<std::vector<std::size_t>> faces;
  for (const auto f : model.faces()) {
    std::vector<std::size_t> face;
    for (const auto v : CGAL::vertices_around_face(model.halfedge(f), model)) face.push_back(index.at(v));
    faces.push_back(std::move(face));
  }
  bool reversed = false;
  auto output = publish_polygon_soup(request, vertices, std::move(faces), source.unit, reversed);
  Json metrics{{"algorithm", "CGAL::Polygonal_surface_reconstruction + CGAL::SCIP_mixed_integer_program_traits"},
               {"plane_detection", "CGAL::Shape_detection::Region_growing (Point_set::Least_squares_plane_fit_region)"},
               {"mip_solver", "SCIP 10.0.3 with SoPlex 8.0.3"},
               {"point_count", cloud.points.size()},
               {"plane_count", regions.size()},
               {"assigned_point_count", assigned},
               {"vertex_count", vertices.size()},
               {"face_count", model.number_of_faces()},
               {"orientation_reversed", reversed},
               {"sphere_radius", sphere_radius},
               {"maximum_distance", maximum_distance},
               {"maximum_angle", maximum_angle},
               {"minimum_region_size", minimum_region_size},
               {"fitting", fitting},
               {"coverage", coverage},
               {"complexity", complexity},
               {"effective_kernel", kEpickName}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
#else
  (void)source;
  optional_dependency_missing("SCIP", operation);
#endif
}

}  // namespace

std::vector<OperationDefinition> polyfit_producers() {
  using query_ops::query_definition;
#ifdef CGAL_MASTER_HAVE_SCIP
  const bool built = true;
#else
  const bool built = false;
#endif
  Json bindings = {{"max_deviation", "max_deviation"}, {"planarity_tolerance", "planarity_tolerance"}};
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "reconstruction.polygonal_surface", {"PointSet3Normals"}, "PolygonSoup3", "transform", run_polygonal,
      {"Polygonal_surface_reconstruction", "Shape_detection", "SCIP"}, kEpickName,
      Json{{"source_header", "CGAL/Polygonal_surface_reconstruction.h"},
           {"symbols", {"Polygonal_surface_reconstruction"}},
           {"input_format", "ascii_ply_with_x_y_z_nx_ny_nz"},
           {"output_format", "off"},
           {"maximum_input_points", reconstruction_ops::kMaximumPoints},
           {"optional_dependency", "SCIP"},
           {"optional_dependency_built", built},
           {"required_parameters",
            {"sphere_radius", "maximum_distance", "maximum_angle", "minimum_region_size", "fitting", "coverage",
             "complexity", "max_deviation", "planarity_tolerance"}},
           {"validators", {"reconstruction.validate.polygonal_surface"}},
           {"validator_parameter_bindings", {{"reconstruction.validate.polygonal_surface", bindings}}}}));
  return result;
}

}  // namespace cgal_master::batch6
