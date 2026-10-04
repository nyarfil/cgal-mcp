#include "mesh_io.h"

#include "../artifact_io.h"
#include "../sha256.h"

#include <CGAL/Polygon_mesh_processing/manifoldness.h>
#include <CGAL/Polygon_mesh_processing/shape_predicates.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/boost/graph/IO/OFF.h>
#include <CGAL/boost/graph/helpers.h>
#include <CGAL/number_utils.h>

#include <array>
#include <cmath>
#include <fstream>
#include <iterator>
#include <locale>
#include <sstream>
#include <unordered_map>
#include <vector>

namespace cgal_master::wave_a {
namespace {

constexpr std::size_t kMaximumArtifactBytes = 512ULL * 1024ULL * 1024ULL;

std::string read_verified_bytes(const ArtifactInput& input) {
  std::error_code error;
  const auto canonical = std::filesystem::canonical(input.path, error);
  if (error || !std::filesystem::is_regular_file(canonical, error) || error) {
    throw WorkerError("INPUT_ERROR", "INPUT_NOT_REGULAR_FILE",
                      "Input artifact must resolve to a regular file");
  }
  std::ifstream stream(canonical, std::ios::binary);
  if (!stream) {
    throw WorkerError("INPUT_ERROR", "INPUT_OPEN_FAILED",
                      "Unable to open input artifact");
  }
  std::string bytes;
  std::array<char, 64 * 1024> buffer{};
  while (stream) {
    stream.read(buffer.data(), static_cast<std::streamsize>(buffer.size()));
    const auto count = stream.gcount();
    if (count > 0) {
      if (bytes.size() + static_cast<std::size_t>(count) >
          kMaximumArtifactBytes) {
        throw WorkerError("RESOURCE_LIMIT", "ARTIFACT_SIZE_LIMIT_EXCEEDED",
                          "Input artifact exceeds the worker byte limit");
      }
      bytes.append(buffer.data(), static_cast<std::size_t>(count));
    }
  }
  if (!stream.eof()) {
    throw WorkerError("INPUT_ERROR", "INPUT_READ_FAILED",
                      "Unable to read input artifact");
  }
  if (sha256_bytes(bytes) != input.sha256) {
    throw WorkerError("INPUT_ERROR", "DIGEST_MISMATCH",
                      "Input artifact sha256 does not match the request");
  }
  return bytes;
}

double unit_in_metres(const std::string& unit) {
  if (unit == "mm") return 0.001;
  if (unit == "cm") return 0.01;
  if (unit == "m") return 1.0;
  throw WorkerError("TYPE_ERROR", "UNSUPPORTED_UNIT",
                    "Length unit must be one of: mm, cm, m");
}

std::filesystem::path temporary_path(const std::filesystem::path& directory,
                                     const Request& request,
                                     const std::string& stem,
                                     const std::string& extension) {
  const auto path = directory /
                    ("." + stem + "." +
                     staging_filename_token(request.request_id) + ".tmp." +
                     extension);
  std::error_code error;
  if (std::filesystem::exists(path, error) || error) {
    throw WorkerError("OUTPUT_ERROR", "TEMPORARY_OUTPUT_EXISTS",
                      "Temporary output path is not clean");
  }
  return path;
}

}  // namespace

Mesh read_triangle_off(const ArtifactInput& input) {
  require_input_shape(input, "TriangleSurfaceMesh", "off");
  const auto bytes = read_verified_bytes(input);
  std::istringstream stream(bytes);
  stream.imbue(std::locale::classic());
  Mesh mesh;
  if (!CGAL::IO::read_OFF(stream, mesh) || mesh.number_of_vertices() == 0 ||
      mesh.number_of_faces() == 0) {
    throw WorkerError("INPUT_ERROR", "MALFORMED_OFF",
                      "Input must be a nonempty readable OFF mesh");
  }
  if (!CGAL::is_valid_polygon_mesh(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "INVALID_POLYGON_MESH",
                      "Input is not a valid polygon mesh");
  }
  if (!CGAL::is_triangle_mesh(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED",
                      "Input mesh must be triangulated");
  }
  for (const auto vertex : mesh.vertices()) {
    const auto& point = mesh.point(vertex);
    if (!std::isfinite(CGAL::to_double(point.x())) ||
        !std::isfinite(CGAL::to_double(point.y())) ||
        !std::isfinite(CGAL::to_double(point.z()))) {
      throw WorkerError("INPUT_ERROR", "NONFINITE_COORDINATE",
                        "OFF coordinates must be finite");
    }
  }
  return mesh;
}

void require_same_unit(const ArtifactInput& first,
                       const ArtifactInput& second) {
  if (first.unit != second.unit) {
    throw WorkerError("TYPE_ERROR", "UNIT_MISMATCH",
                      "Mesh artifact units must match");
  }
}

double typed_length(const Json& value, const std::string& geometry_unit,
                    const std::string& parameter_name,
                    bool strictly_positive) {
  if (!value.is_object() || !value.contains("value") ||
      !value.at("value").is_number() || !value.contains("unit") ||
      !value.at("unit").is_string() || value.size() != 2) {
    throw WorkerError(
        "INVALID_REQUEST", "INVALID_TYPED_LENGTH",
        parameter_name +
            " must be an object containing only numeric value and length unit");
  }
  const double amount = value.at("value").get<double>();
  if (!std::isfinite(amount) || amount < 0 ||
      (strictly_positive && amount <= 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_TYPED_LENGTH",
                      parameter_name +
                          (strictly_positive ? " must be finite and positive"
                                             : " must be finite and nonnegative"));
  }
  const auto parameter_unit = value.at("unit").get<std::string>();
  const double converted = amount * unit_in_metres(parameter_unit) /
                           unit_in_metres(geometry_unit);
  if (!std::isfinite(converted) || converted < 0 ||
      (strictly_positive && converted <= 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_TYPED_LENGTH",
                      parameter_name +
                          " is not finite and representable with the required sign after conversion to the geometry unit");
  }
  return converted;
}

std::filesystem::path write_mesh_output(const Request& request,
                                        const Mesh& mesh) {
  const auto directory = checked_output_dir(request);
  const auto destination = output_path(directory, "geometry.off");
  const auto temporary = temporary_path(directory, request, "geometry", "off");
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
                      "Unable to write OFF output");
  }
  commit_output(temporary, destination);
  return destination;
}

std::filesystem::path write_validation_output(const Request& request,
                                              const Json& report) {
  const auto directory = checked_output_dir(request);
  const auto destination = output_path(directory, "validation.json");
  const auto temporary =
      temporary_path(directory, request, "validation", "json");
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
  return destination;
}

Json geometry_output(const std::filesystem::path& path,
                     const std::string& unit) {
  return Json{{"slot", "geometry"},
              {"type", "TriangleSurfaceMesh"},
              {"unit", unit},
              {"format", "off"},
              {"path", portable_path(path)}};
}

Json validation_output(const std::filesystem::path& path) {
  return Json{{"slot", "validation"},
              {"type", "ValidationReport"},
              {"unit", "none"},
              {"format", "json"},
              {"path", portable_path(path)}};
}

void require_wave_a_kernel(const Request& request) {
  if (request.kernel != "package_recommended") {
    throw WorkerError(
        "UNSUPPORTED", "UNSUPPORTED_KERNEL",
        "Wave A mesh operations support package_recommended (EPICK) only");
  }
}

void require_healthy_triangle_mesh(const Mesh& mesh,
                                   const std::string& subject) {
  namespace PMP = CGAL::Polygon_mesh_processing;
  for (const auto face : mesh.faces()) {
    if (PMP::is_degenerate_triangle_face(face, mesh)) {
      throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_FACE",
                        subject + " contains a degenerate triangle");
    }
  }
  std::vector<Mesh::Halfedge_index> non_manifold_vertices;
  PMP::non_manifold_vertices(mesh,
                            std::back_inserter(non_manifold_vertices));
  if (!non_manifold_vertices.empty()) {
    throw WorkerError("PRECONDITION_FAILED", "NON_MANIFOLD_VERTEX",
                      subject + " contains a non-manifold vertex");
  }
  if (PMP::does_self_intersect(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "SELF_INTERSECTION",
                      subject + " self-intersects");
  }
}

}  // namespace cgal_master::wave_a
