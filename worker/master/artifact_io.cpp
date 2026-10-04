#include "artifact_io.h"

#include "sha256.h"

#include <CGAL/boost/graph/IO/OFF.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/boost/graph/helpers.h>
#include <CGAL/number_utils.h>

#include <array>
#include <cmath>
#include <fstream>
#include <limits>
#include <locale>
#include <sstream>
#include <system_error>
#include <unordered_set>

namespace cgal_master {
namespace {

constexpr std::size_t kMaximumPointCount = 10000000;
constexpr std::size_t kMaximumArtifactBytes = 512ULL * 1024ULL * 1024ULL;
const std::unordered_set<std::string> kLengthUnits = {"mm", "cm", "m"};

bool is_contained_path(const std::filesystem::path& root,
                       const std::filesystem::path& child) {
  auto root_iterator = root.begin();
  auto child_iterator = child.begin();
  for (; root_iterator != root.end(); ++root_iterator, ++child_iterator) {
    if (child_iterator == child.end() || *root_iterator != *child_iterator) {
      return false;
    }
  }
  return true;
}

double parse_coordinate(const std::string& token, std::size_t line_number) {
  std::size_t consumed = 0;
  double value = 0;
  try {
    value = std::stod(token, &consumed);
  } catch (const std::exception&) {
    throw WorkerError("INPUT_ERROR", "MALFORMED_XYZ",
                      "Invalid numeric coordinate on XYZ line " +
                          std::to_string(line_number));
  }
  if (consumed != token.size() || !std::isfinite(value)) {
    throw WorkerError("INPUT_ERROR", "NONFINITE_OR_INVALID_COORDINATE",
                      "XYZ coordinates must be finite numbers (line " +
                          std::to_string(line_number) + ")");
  }
  return value;
}

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

}  // namespace

void require_input_shape(const ArtifactInput& input,
                         const std::string& expected_type,
                         const std::string& expected_format) {
  if (input.type != expected_type) {
    throw WorkerError("TYPE_ERROR", "INPUT_TYPE_MISMATCH",
                      "Expected input type " + expected_type + ", received " +
                          input.type);
  }
  if (input.format != expected_format) {
    throw WorkerError("TYPE_ERROR", "INPUT_FORMAT_MISMATCH",
                      "Expected input format " + expected_format + ", received " +
                          input.format);
  }
  if (kLengthUnits.find(input.unit) == kLengthUnits.end()) {
    throw WorkerError("TYPE_ERROR", "UNSUPPORTED_UNIT",
                      "Geometry unit must be one of: mm, cm, m");
  }
}

std::vector<Point> read_xyz_points(const ArtifactInput& input) {
  require_input_shape(input, "PointSet3", "xyz");
  const auto bytes = read_verified_bytes(input);
  std::istringstream stream(bytes);
  stream.imbue(std::locale::classic());
  if (!stream) {
    throw WorkerError("INPUT_ERROR", "INPUT_OPEN_FAILED",
                      "Unable to open XYZ input");
  }
  std::vector<Point> points;
  std::string line;
  std::size_t line_number = 0;
  while (std::getline(stream, line)) {
    ++line_number;
    std::istringstream tokens(line);
    tokens.imbue(std::locale::classic());
    std::string x;
    std::string y;
    std::string z;
    std::string extra;
    if (!(tokens >> x)) continue;
    if (!(tokens >> y >> z) || (tokens >> extra)) {
      throw WorkerError("INPUT_ERROR", "MALFORMED_XYZ",
                        "Every nonblank XYZ line must contain exactly three "
                        "coordinates (line " +
                            std::to_string(line_number) + ")");
    }
    const auto px = parse_coordinate(x, line_number);
    const auto py = parse_coordinate(y, line_number);
    const auto pz = parse_coordinate(z, line_number);
    points.emplace_back(px, py, pz);
    if (points.size() > kMaximumPointCount) {
      throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED",
                        "XYZ input exceeds the worker point limit");
    }
  }
  if (!stream.eof()) {
    throw WorkerError("INPUT_ERROR", "INPUT_READ_FAILED",
                      "Unable to read XYZ input");
  }
  return points;
}

Mesh read_off_mesh(const ArtifactInput& input) {
  require_input_shape(input, "TriangleSurfaceMesh", "off");
  const auto bytes = read_verified_bytes(input);
  std::istringstream stream(bytes);
  Mesh mesh;
  if (!CGAL::IO::read_OFF(stream, mesh) ||
      mesh.number_of_vertices() == 0 || mesh.number_of_faces() == 0) {
    throw WorkerError("INPUT_ERROR", "MALFORMED_OFF",
                      "Input must be a nonempty readable OFF mesh");
  }
  if (!CGAL::is_valid_polygon_mesh(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "INVALID_POLYGON_MESH",
                      "Hull input is not a valid polygon mesh");
  }
  if (!CGAL::is_triangle_mesh(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED",
                      "Hull input must be triangulated");
  }
  return mesh;
}

std::filesystem::path checked_output_dir(const Request& request) {
  std::error_code error;
  const auto canonical = std::filesystem::canonical(request.output_dir, error);
  if (error || !std::filesystem::is_directory(canonical, error) || error) {
    throw WorkerError("INVALID_REQUEST", "OUTPUT_DIR_INVALID",
                      "output_dir must resolve to an existing directory");
  }
  return canonical;
}

std::filesystem::path output_path(const std::filesystem::path& output_dir,
                                  const std::string& filename) {
  const auto candidate = (output_dir / filename).lexically_normal();
  if (!is_contained_path(output_dir, candidate) ||
      candidate.parent_path() != output_dir) {
    throw WorkerError("INTERNAL", "UNSAFE_OUTPUT_PATH",
                      "Worker output escaped the staging directory");
  }
  std::error_code error;
  if (std::filesystem::exists(candidate, error) || error) {
    throw WorkerError("OUTPUT_ERROR", "OUTPUT_EXISTS",
                      "Worker refuses to overwrite an existing output");
  }
  return candidate;
}

void commit_output(const std::filesystem::path& temporary,
                   const std::filesystem::path& destination) {
  std::error_code error;
  // A hard-link publish is an atomic no-replace operation on both NTFS and
  // POSIX filesystems. The temporary and destination are in the same staging
  // directory, so they necessarily share a filesystem.
  std::filesystem::create_hard_link(temporary, destination, error);
  if (error) {
    std::filesystem::remove(temporary);
    throw WorkerError("OUTPUT_ERROR", "OUTPUT_COMMIT_FAILED",
                      "Unable to commit worker output");
  }
  std::filesystem::remove(temporary, error);
  // The destination is already committed. A cleanup failure must not turn a
  // valid atomic publish into an error that cannot be safely retried.
}

std::string portable_path(const std::filesystem::path& path) {
  return path.generic_u8string();
}

std::string staging_filename_token(const std::string& identifier) {
  std::string token;
  token.reserve(identifier.size());
  for (const char character : identifier) {
    // ':' is valid in protocol identifiers and used by parent artifact IDs,
    // but denotes an NTFS alternate data stream in a Windows filename.
    if (character == ':')
      token += "%3A";
    else
      token += character;
  }
  return token;
}

Json volume_metric(const Kernel::FT& volume, const std::string& length_unit) {
  std::ostringstream exact;
  exact << CGAL::exact(volume);
  Json result = {{"exact", exact.str()}, {"unit", length_unit + "^3"}};
  const auto approximation = CGAL::to_double(volume);
  if (std::isfinite(approximation) && approximation > 0) {
    result["approximate"] = approximation;
  }
  return result;
}

}  // namespace cgal_master
