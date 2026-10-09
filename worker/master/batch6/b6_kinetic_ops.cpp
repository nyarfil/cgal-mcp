// Kinetic surface reconstruction producer (7.10.02): CGAL::Kinetic_surface_reconstruction_3.
// The pipeline is the documented one: detection_and_partition (region-growing shape detection with
// optional regularization, then the kinetic space partition of the given depth k) followed by the
// graph-cut labelling reconstruct(lambda, external_nodes, ...), which yields indexed polygons. The
// result is published as PolygonSoup3 only after reconstruction.validate.polygonal_surface passes
// (CGAL-free). No optional third-party library is needed.

#include "b6_common.h"

#include "../artifact_io.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Kinetic_surface_reconstruction_3.h>
#include <CGAL/Point_set_3.h>

#include <cmath>
#include <map>

namespace cgal_master::batch6 {
namespace {

using query_ops::precondition;
using query_ops::require_inputs;
using query_ops::require_parameter_names;

constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";
constexpr const char* kKsrKernel = "CGAL::Exact_predicates_exact_constructions_kernel (intersection kernel)";

using Kernel = CGAL::Exact_predicates_inexact_constructions_kernel;
using Point = Kernel::Point_3;
using Vector = Kernel::Vector_3;
using PointSet = CGAL::Point_set_3<Point>;
using PointMap = PointSet::Point_map;
using NormalMap = PointSet::Vector_map;
using Ksr = CGAL::Kinetic_surface_reconstruction_3<Kernel, PointSet, PointMap, NormalMap>;

bool boolean_parameter(const Request& request, const char* name) {
  const auto& value = request.parameters.at(name);
  if (!value.is_boolean()) throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be a boolean");
  return value.get<bool>();
}

Json run_kinetic(const Request& request) {
  require_inputs(request, 1, "reconstruction.kinetic_surface");
  require_parameter_names(request, {"k_neighbors", "maximum_distance", "maximum_angle", "minimum_region_size",
                                    "angle_tolerance", "maximum_offset", "regularize_parallelism",
                                    "regularize_orthogonality", "regularize_coplanarity", "regularize_axis_symmetry",
                                    "partition_depth", "lambda", "max_deviation", "planarity_tolerance"});
  const auto& source = request.inputs[0];
  const auto cloud = reconstruction_ops::read_points_with_normals(source);
  reconstruction_ops::require_point_budget(cloud);
  for (const auto& n : cloud.normals) {
    if (!(n[0] * n[0] + n[1] * n[1] + n[2] * n[2] > 0)) {
      precondition("ZERO_NORMAL", "Kinetic surface reconstruction needs a nonzero oriented normal at every point");
    }
  }
  if (reconstruction_ops::affine_rank(cloud.points) < 3) {
    precondition("DEGENERATE_POINT_SET", "The point set does not span space");
  }
  const auto k_neighbors = reconstruction_ops::integer_parameter(request, "k_neighbors", 3, 200);
  const double maximum_distance = reconstruction_ops::length_parameter(request, "maximum_distance", source.unit);
  const double maximum_angle = reconstruction_ops::number_parameter(request, "maximum_angle", 0.0, 90.0);
  const auto minimum_region_size = reconstruction_ops::integer_parameter(request, "minimum_region_size", 3, 100000);
  const double angle_tolerance = reconstruction_ops::number_parameter(request, "angle_tolerance", 0.0, 45.0);
  const double maximum_offset = reconstruction_ops::length_parameter(request, "maximum_offset", source.unit);
  const bool parallelism = boolean_parameter(request, "regularize_parallelism");
  const bool orthogonality = boolean_parameter(request, "regularize_orthogonality");
  const bool coplanarity = boolean_parameter(request, "regularize_coplanarity");
  const bool axis_symmetry = boolean_parameter(request, "regularize_axis_symmetry");
  const auto partition_depth = reconstruction_ops::integer_parameter(request, "partition_depth", 1, 3);
  const double lambda = reconstruction_ops::number_parameter(request, "lambda", 0.0, 0.999999);
  reconstruction_ops::length_parameter(request, "max_deviation", source.unit);        // validator-enforced
  reconstruction_ops::length_parameter(request, "planarity_tolerance", source.unit);  // validator-enforced

  PointSet point_set;
  point_set.add_normal_map();
  for (std::size_t i = 0; i < cloud.points.size(); ++i) {
    const auto& p = cloud.points[i];
    const auto& n = cloud.normals[i];
    const double length = std::sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]);
    const auto it = point_set.insert(Point(p[0], p[1], p[2]));
    point_set.normal(*it) = Vector(n[0] / length, n[1] / length, n[2] / length);
  }
  auto parameters = CGAL::parameters::maximum_distance(maximum_distance)
                        .maximum_angle(maximum_angle)
                        .k_neighbors(k_neighbors)
                        .minimum_region_size(minimum_region_size)
                        .angle_tolerance(angle_tolerance)
                        .maximum_offset(maximum_offset)
                        .regularize_parallelism(parallelism)
                        .regularize_orthogonality(orthogonality)
                        .regularize_coplanarity(coplanarity)
                        .regularize_axis_symmetry(axis_symmetry);
  Ksr ksr(point_set, parameters);
  ksr.detection_and_partition(partition_depth, parameters);
  const std::size_t shapes = ksr.detected_planar_shapes().size();
  if (shapes < 4) precondition("TOO_FEW_PLANES", "Shape detection found fewer than four planar shapes");
  std::vector<Point> vertices_cgal;
  std::vector<std::vector<std::size_t>> faces;
  ksr.reconstruct(lambda, std::map<Ksr::KSP::Face_support, bool>(), std::back_inserter(vertices_cgal),
                  std::back_inserter(faces));
  if (faces.empty()) precondition("EMPTY_RECONSTRUCTION", "The kinetic reconstruction produced no faces");
  if (faces.size() > kMaximumPolygonFaces) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED", "The reconstruction exceeds the face budget");
  }
  std::vector<V3> vertices;
  for (const auto& p : vertices_cgal) {
    vertices.push_back({CGAL::to_double(p.x()), CGAL::to_double(p.y()), CGAL::to_double(p.z())});
  }
  const std::size_t face_count = faces.size();
  bool reversed = false;
  auto output = publish_polygon_soup(request, vertices, std::move(faces), source.unit, reversed);
  Json metrics{{"algorithm", "CGAL::Kinetic_surface_reconstruction_3 (detection_and_partition + reconstruct)"},
               {"intersection_kernel", kKsrKernel},
               {"point_count", cloud.points.size()},
               {"planar_shape_count", shapes},
               {"vertex_count", vertices.size()},
               {"face_count", face_count},
               {"orientation_reversed", reversed},
               {"k_neighbors", k_neighbors},
               {"maximum_distance", maximum_distance},
               {"maximum_angle", maximum_angle},
               {"minimum_region_size", minimum_region_size},
               {"angle_tolerance", angle_tolerance},
               {"maximum_offset", maximum_offset},
               {"partition_depth", partition_depth},
               {"lambda", lambda},
               {"effective_kernel", kEpickName}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

}  // namespace

std::vector<OperationDefinition> kinetic_producers() {
  using query_ops::query_definition;
  Json bindings = {{"max_deviation", "max_deviation"}, {"planarity_tolerance", "planarity_tolerance"}};
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "reconstruction.kinetic_surface", {"PointSet3Normals"}, "PolygonSoup3", "transform", run_kinetic,
      {"Kinetic_surface_reconstruction", "Kinetic_space_partition", "Shape_detection"}, kEpickName,
      Json{{"source_header", "CGAL/Kinetic_surface_reconstruction_3.h"},
           {"symbols", {"Kinetic_surface_reconstruction_3"}},
           {"input_format", "ascii_ply_with_x_y_z_nx_ny_nz"},
           {"output_format", "off"},
           {"maximum_input_points", reconstruction_ops::kMaximumPoints},
           {"required_parameters",
            {"k_neighbors", "maximum_distance", "maximum_angle", "minimum_region_size", "angle_tolerance",
             "maximum_offset", "regularize_parallelism", "regularize_orthogonality", "regularize_coplanarity",
             "regularize_axis_symmetry", "partition_depth", "lambda", "max_deviation", "planarity_tolerance"}},
           {"validators", {"reconstruction.validate.polygonal_surface"}},
           {"validator_parameter_bindings", {{"reconstruction.validate.polygonal_surface", bindings}}}}));
  return result;
}

}  // namespace cgal_master::batch6
