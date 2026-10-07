#include "artifact_io.h"
#include "operation.h"

#include <CGAL/Polygon_mesh_processing/measure.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/Side_of_triangle_mesh.h>
#include <CGAL/boost/graph/helpers.h>
#include <CGAL/convexity_check_3.h>
#include <CGAL/number_utils.h>

#include <filesystem>
#include <fstream>
#include <set>

namespace cgal_master {
namespace {

Json run_convex_enclosure_validator(const Request& request) {
  if (request.inputs.size() != 2) {
    throw WorkerError(
        "TYPE_ERROR", "INPUT_COUNT_MISMATCH",
        "hull.validate.convex_enclosure requires hull then original points");
  }
  if (!request.parameters.empty()) {
    throw WorkerError(
        "INVALID_REQUEST", "UNSUPPORTED_PARAMETER",
        "hull.validate.convex_enclosure accepts no parameters in revision 1");
  }
  const auto& hull_input = request.inputs[0];
  const auto& points_input = request.inputs[1];
  if (hull_input.unit != points_input.unit) {
    throw WorkerError("TYPE_ERROR", "UNIT_MISMATCH",
                      "Hull and original point set units must match");
  }
  auto mesh = read_off_mesh(hull_input);
  auto points = read_xyz_points(points_input);
  if (points.empty()) {
    throw WorkerError("PRECONDITION_FAILED", "EMPTY_POINT_SET",
                      "Original PointSet3 must not be empty");
  }
  namespace PMP = CGAL::Polygon_mesh_processing;
  if (!CGAL::is_closed(mesh)) {
    throw WorkerError("VALIDATION_FAILED", "HULL_NOT_CLOSED",
                      "Hull mesh is not closed");
  }
  if (!PMP::is_outward_oriented(mesh)) {
    throw WorkerError("VALIDATION_FAILED", "HULL_NOT_OUTWARD_ORIENTED",
                      "Hull mesh is not outward oriented");
  }
  const auto volume = PMP::volume(mesh);
  if (volume <= Kernel::FT(0)) {
    throw WorkerError("VALIDATION_FAILED", "HULL_NONPOSITIVE_VOLUME",
                      "Hull mesh does not have positive volume");
  }
  if (!CGAL::is_strongly_convex_3(mesh)) {
    throw WorkerError("VALIDATION_FAILED", "HULL_NOT_CONVEX",
                      "Hull mesh is not strongly convex");
  }

  {
    std::set<Kernel::Point_3, Kernel::Less_xyz_3> source(points.begin(), points.end());
    for (const auto vertex : mesh.vertices()) {
      if (source.find(mesh.point(vertex)) == source.end()) {
        throw WorkerError("VALIDATION_FAILED", "HULL_VERTEX_NOT_IN_SOURCE",
                          "A hull vertex is not an original source point");
      }
    }
  }

  CGAL::Side_of_triangle_mesh<Mesh, Kernel> side(mesh);
  std::size_t boundary_count = 0;
  std::size_t inside_count = 0;
  for (const auto& point : points) {
    const auto location = side(point);
    if (location == CGAL::ON_UNBOUNDED_SIDE) {
      throw WorkerError("VALIDATION_FAILED", "POINT_OUTSIDE_HULL",
                        "At least one original point lies outside the hull");
    }
    if (location == CGAL::ON_BOUNDARY)
      ++boundary_count;
    else
      ++inside_count;
  }

  Json report = {{"status", "pass"},
                 {"valid", true},
                 {"closed", true},
                 {"triangulated", true},
                 {"outward_oriented", true},
                 {"positive_volume", true},
                 {"strongly_convex", true},
                 {"all_original_points_enclosed", true},
                 {"original_point_count", points.size()},
                 {"inside_point_count", inside_count},
                 {"boundary_point_count", boundary_count},
                 {"volume", volume_metric(volume, hull_input.unit)}};

  const auto directory = checked_output_dir(request);
  const auto destination = output_path(directory, "validation.json");
  const auto temporary =
      directory / (".validation." + staging_filename_token(request.request_id) +
                   ".tmp.json");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("OUTPUT_ERROR", "TEMPORARY_OUTPUT_EXISTS",
                      "Temporary output path is not clean");
  }
  {
    std::ofstream output(temporary, std::ios::binary);
    output << report.dump() << '\n';
    if (!output) {
      output.close();
      std::filesystem::remove(temporary);
      throw WorkerError("OUTPUT_ERROR", "OUTPUT_WRITE_FAILED",
                        "Unable to write validation report");
    }
  }
  commit_output(temporary, destination);

  Json outputs = Json::array(
      {{{"slot", "validation"},
        {"type", "ValidationReport"},
        {"unit", "none"},
        {"format", "json"},
        {"path", portable_path(destination)}}});
  return success_result(request, std::move(outputs), report);
}

}  // namespace

OperationDefinition convex_enclosure_validator_operation() {
  return OperationDefinition{"hull.validate.convex_enclosure", 1,
                             {"TriangleSurfaceMesh", "PointSet3"},
                             "ValidationReport", "validator",
                             run_convex_enclosure_validator};
}

}  // namespace cgal_master
