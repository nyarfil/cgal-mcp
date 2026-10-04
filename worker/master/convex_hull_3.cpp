#include "artifact_io.h"
#include "operation.h"

#include <CGAL/boost/graph/IO/OFF.h>
#include <CGAL/Polygon_mesh_processing/measure.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/boost/graph/helpers.h>
#include <CGAL/convex_hull_3.h>
#include <CGAL/number_utils.h>

#include <algorithm>
#include <filesystem>
#include <fstream>

namespace cgal_master {
namespace {

void require_full_dimensional(const std::vector<Point>& points) {
  if (points.size() < 4) {
    throw WorkerError("PRECONDITION_FAILED", "INSUFFICIENT_POINTS",
                      "At least four points are required for a 3D convex hull");
  }
  const auto first = points.begin();
  auto second = std::find_if(first + 1, points.end(),
                             [&](const Point& point) { return point != *first; });
  if (second == points.end()) {
    throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_3",
                      "Point set has affine rank 0");
  }
  auto third = std::find_if(second + 1, points.end(), [&](const Point& point) {
    return !CGAL::collinear(*first, *second, point);
  });
  if (third == points.end()) {
    throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_3",
                      "Point set has affine rank at most 1");
  }
  const auto fourth =
      std::find_if(third + 1, points.end(), [&](const Point& point) {
        return !CGAL::coplanar(*first, *second, *third, point);
      });
  if (fourth == points.end()) {
    throw WorkerError("PRECONDITION_FAILED", "AFFINE_RANK_LT_3",
                      "Point set has affine rank at most 2");
  }
}

Json run_convex_hull(const Request& request) {
  if (request.inputs.size() != 1) {
    throw WorkerError("TYPE_ERROR", "INPUT_COUNT_MISMATCH",
                      "hull.convex_3 requires exactly one PointSet3 input");
  }
  if (!request.parameters.empty()) {
    throw WorkerError("INVALID_REQUEST", "UNSUPPORTED_PARAMETER",
                      "hull.convex_3 does not accept parameters in revision 1");
  }
  auto points = read_xyz_points(request.inputs.front());
  require_full_dimensional(points);

  Mesh mesh;
  CGAL::convex_hull_3(points.begin(), points.end(), mesh);
  if (mesh.number_of_faces() == 0 || !CGAL::is_valid_polygon_mesh(mesh) ||
      !CGAL::is_triangle_mesh(mesh) || !CGAL::is_closed(mesh)) {
    throw WorkerError("INTERNAL", "INVALID_HULL_GENERATED",
                      "CGAL produced an invalid hull mesh");
  }
  namespace PMP = CGAL::Polygon_mesh_processing;
  if (!PMP::is_outward_oriented(mesh)) PMP::reverse_face_orientations(mesh);
  const auto volume = PMP::volume(mesh);
  if (volume <= Kernel::FT(0)) {
    throw WorkerError("INTERNAL", "NONPOSITIVE_HULL_VOLUME",
                      "CGAL produced a hull with nonpositive volume");
  }

  const auto directory = checked_output_dir(request);
  const auto destination = output_path(directory, "geometry.off");
  // Keep the format extension on the temporary file so CGAL selects the OFF
  // writer before the atomic rename.
  const auto temporary =
      directory / (".geometry." + staging_filename_token(request.request_id) +
                   ".tmp.off");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("OUTPUT_ERROR", "TEMPORARY_OUTPUT_EXISTS",
                      "Temporary output path is not clean");
  }
  bool written = false;
  {
    std::ofstream output(temporary, std::ios::binary);
    written = output && CGAL::IO::write_OFF(
                            output, mesh,
                            CGAL::parameters::stream_precision(17));
    output.flush();
    written = written && static_cast<bool>(output);
  }
  if (!written) {
    std::filesystem::remove(temporary);
    throw WorkerError("OUTPUT_ERROR", "OUTPUT_WRITE_FAILED",
                      "Unable to write hull OFF output");
  }
  commit_output(temporary, destination);

  Json outputs = Json::array(
      {{{"slot", "geometry"},
        {"type", "TriangleSurfaceMesh"},
        {"unit", request.inputs.front().unit},
        {"format", "off"},
        {"path", portable_path(destination)}}});
  Json metrics = {{"input_point_count", points.size()},
                  {"hull_vertex_count", mesh.number_of_vertices()},
                  {"hull_face_count", mesh.number_of_faces()},
                  {"volume", volume_metric(volume, request.inputs.front().unit)},
                  {"effective_kernel",
                   "CGAL::Exact_predicates_exact_constructions_kernel"}};
  return success_result(request, std::move(outputs), std::move(metrics));
}

}  // namespace

OperationDefinition convex_hull_operation() {
  return OperationDefinition{"hull.convex_3", 1, {"PointSet3"},
                             "TriangleSurfaceMesh", "transform",
                             run_convex_hull};
}

}  // namespace cgal_master
