#include "boolean_common.h"

#include "../artifact_io.h"
#include "../sha256.h"

#include <CGAL/Polygon_mesh_processing/corefinement.h>
#include <CGAL/Polygon_mesh_processing/intersection.h>
#include <CGAL/Polygon_mesh_processing/manifoldness.h>
#include <CGAL/Polygon_mesh_processing/measure.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Polygon_mesh_processing/shape_predicates.h>
#include <CGAL/Side_of_triangle_mesh.h>
#include <CGAL/boost/graph/helpers.h>
#include <CGAL/number_utils.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <limits>
#include <locale>
#include <set>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

namespace cgal_master::wave_a_boolean {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;
using Face = Mesh::Face_index;
using Vertex = Mesh::Vertex_index;
using Halfedge = Mesh::Halfedge_index;

constexpr std::size_t kMaxArtifactBytes = 256ULL * 1024ULL * 1024ULL;
constexpr std::size_t kMaxInputVertices = 200000;
constexpr std::size_t kMaxInputFaces = 400000;
constexpr std::size_t kMaxOutputVertices = 1000000;
constexpr std::size_t kMaxOutputFaces = 2000000;
constexpr double kMaximumCoordinate = 1e100;
constexpr double kMinimumSpan = 1e-100;
constexpr double kMaximumTranslationToSpanRatio = 1e6;
const std::set<std::string> kLengthUnits = {"mm", "cm", "m"};

std::string verified_bytes(const ArtifactInput& input) {
  std::error_code error;
  const auto canonical = std::filesystem::canonical(input.path, error);
  if (error || !std::filesystem::is_regular_file(canonical, error) || error) {
    throw WorkerError("INVALID_INPUT", "INPUT_NOT_REGULAR_FILE",
                      "Boolean input must resolve to a regular file");
  }
  const auto size = std::filesystem::file_size(canonical, error);
  if (error) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Cannot stat Boolean input");
  }
  if (size > kMaxArtifactBytes) {
    throw WorkerError("RESOURCE_LIMIT", "ARTIFACT_SIZE_LIMIT_EXCEEDED",
                      "Boolean input exceeds the byte limit");
  }
  std::ifstream stream(canonical, std::ios::binary);
  if (!stream) {
    throw WorkerError("INVALID_INPUT", "INPUT_OPEN_FAILED",
                      "Cannot open Boolean input");
  }
  std::string bytes((std::istreambuf_iterator<char>(stream)),
                    std::istreambuf_iterator<char>());
  if (!stream.eof() && stream.fail()) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Cannot read Boolean input");
  }
  if (sha256_bytes(bytes) != input.sha256) {
    throw WorkerError("INVALID_INPUT", "DIGEST_MISMATCH",
                      "Boolean input sha256 does not match parsed bytes");
  }
  return bytes;
}

std::vector<std::string> off_tokens(const std::string& bytes) {
  std::istringstream source(bytes);
  source.imbue(std::locale::classic());
  std::vector<std::string> result;
  std::string line;
  while (std::getline(source, line)) {
    const auto comment = line.find('#');
    if (comment != std::string::npos) line.erase(comment);
    std::istringstream fields(line);
    fields.imbue(std::locale::classic());
    std::string token;
    while (fields >> token) result.push_back(token);
  }
  return result;
}

std::uint64_t unsigned_token(const std::string& token, const char* field) {
  std::size_t consumed = 0;
  try {
    if (token.empty() || token.front() == '-') throw std::invalid_argument(field);
    const auto value = std::stoull(token, &consumed);
    if (consumed != token.size()) throw std::invalid_argument(field);
    return value;
  } catch (const std::exception&) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      std::string("Invalid OFF ") + field);
  }
}

double coordinate_token(const std::string& token) {
  std::size_t consumed = 0;
  double value = 0;
  try {
    value = std::stod(token, &consumed);
  } catch (const std::exception&) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      "OFF coordinates must be binary64 numbers");
  }
  if (consumed != token.size() || !std::isfinite(value)) {
    throw WorkerError("INVALID_INPUT", "NONFINITE_COORDINATE",
                      "OFF coordinates must be finite binary64 numbers");
  }
  return value;
}

Mesh parse_off(const ArtifactInput& input, bool allow_empty) {
  const auto tokens = off_tokens(verified_bytes(input));
  std::size_t cursor = 0;
  const auto next = [&]() -> const std::string& {
    if (cursor >= tokens.size()) {
      throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                        "OFF input ended before declared data");
    }
    return tokens[cursor++];
  };
  if (next() != "OFF") {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      "Only ASCII OFF is accepted");
  }
  const auto vertex_count = unsigned_token(next(), "vertex count");
  const auto face_count = unsigned_token(next(), "face count");
  (void)unsigned_token(next(), "edge count");
  if (vertex_count > kMaxInputVertices || face_count > kMaxInputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "Boolean input exceeds vertex or face limits");
  }
  if (!allow_empty && (vertex_count == 0 || face_count == 0)) {
    throw WorkerError("PRECONDITION_FAILED", "EMPTY_SOURCE_MESH",
                      "Boolean source meshes must be nonempty");
  }
  if (allow_empty && vertex_count == 0 && face_count == 0) {
    if (cursor != tokens.size()) {
      throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                        "Empty OFF candidate has trailing data");
    }
    return Mesh{};
  }
  if (vertex_count == 0 || face_count == 0) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      "OFF cannot contain only vertices or only faces");
  }
  Mesh mesh;
  std::vector<Vertex> vertices;
  vertices.reserve(static_cast<std::size_t>(vertex_count));
  for (std::uint64_t index = 0; index < vertex_count; ++index) {
    const auto x = coordinate_token(next());
    const auto y = coordinate_token(next());
    const auto z = coordinate_token(next());
    vertices.push_back(mesh.add_vertex(Point(x, y, z)));
  }
  for (std::uint64_t index = 0; index < face_count; ++index) {
    const auto degree = unsigned_token(next(), "face degree");
    if (degree != 3) {
      throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED",
                        "Boolean source and candidate meshes must be triangulated");
    }
    std::array<std::uint64_t, 3> indices = {
        unsigned_token(next(), "face index"),
        unsigned_token(next(), "face index"),
        unsigned_token(next(), "face index")};
    if (indices[0] >= vertex_count || indices[1] >= vertex_count ||
        indices[2] >= vertex_count) {
      throw WorkerError("INVALID_INPUT", "OFF_INDEX_OUT_OF_RANGE",
                        "OFF face index is outside the vertex table");
    }
    const auto face = mesh.add_face(vertices[indices[0]], vertices[indices[1]],
                                    vertices[indices[2]]);
    if (face == Mesh::null_face()) {
      throw WorkerError("PRECONDITION_FAILED", "INVALID_POLYGON_MESH",
                        "OFF faces do not form an orientable manifold polygon mesh");
    }
  }
  if (cursor != tokens.size()) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      "OFF input has trailing tokens");
  }
  return mesh;
}

void require_numeric_scale(const Mesh& mesh, const std::string& subject) {
  double min_x = (std::numeric_limits<double>::max)();
  double min_y = min_x;
  double min_z = min_x;
  double max_x = -(std::numeric_limits<double>::max)();
  double max_y = max_x;
  double max_z = max_x;
  double max_abs = 0;
  for (const auto vertex : mesh.vertices()) {
    const auto& point = mesh.point(vertex);
    const double x = CGAL::to_double(point.x());
    const double y = CGAL::to_double(point.y());
    const double z = CGAL::to_double(point.z());
    max_abs = (std::max)({max_abs, std::abs(x), std::abs(y), std::abs(z)});
    min_x = (std::min)(min_x, x);
    min_y = (std::min)(min_y, y);
    min_z = (std::min)(min_z, z);
    max_x = (std::max)(max_x, x);
    max_y = (std::max)(max_y, y);
    max_z = (std::max)(max_z, z);
  }
  const auto span = (std::max)({max_x - min_x, max_y - min_y, max_z - min_z});
  if (!std::isfinite(span) || max_abs > kMaximumCoordinate ||
      span < kMinimumSpan || max_abs / span > kMaximumTranslationToSpanRatio) {
    throw WorkerError(
        "PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
        subject +
            " exceeds the documented binary64 scale or translation-to-span limits");
  }
}

void require_positive_component_orientation(const Mesh& mesh,
                                            const std::string& subject) {
  // Correct volume boundaries may contain negatively oriented inner shells
  // around cavities. does_bound_a_volume() verifies their nesting/orientation;
  // the aggregate signed volume must still be positive.
  if (!(PMP::volume(mesh) > Kernel::FT(0))) {
    throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_OUTWARD_ORIENTED",
                      subject + " does not have positive volume orientation");
  }
}

void require_healthy_volume_mesh(const Mesh& mesh, const std::string& subject,
                                 bool allow_empty) {
  if (mesh.number_of_faces() == 0) {
    if (allow_empty && mesh.number_of_vertices() == 0) return;
    throw WorkerError("PRECONDITION_FAILED", "EMPTY_SOURCE_MESH",
                      subject + " must be nonempty");
  }
  if (mesh.number_of_vertices() > kMaxOutputVertices ||
      mesh.number_of_faces() > kMaxOutputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "BOOLEAN_OUTPUT_SIZE_LIMIT_EXCEEDED",
                      subject + " exceeds Boolean output limits");
  }
  if (!CGAL::is_valid_polygon_mesh(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "INVALID_POLYGON_MESH",
                      subject + " is not a valid polygon mesh");
  }
  if (!CGAL::is_triangle_mesh(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED",
                      subject + " must be triangulated");
  }
  if (!CGAL::is_closed(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_CLOSED",
                      subject + " must be closed");
  }
  for (const auto vertex : mesh.vertices()) {
    if (mesh.halfedge(vertex) == Mesh::null_halfedge()) {
      throw WorkerError("PRECONDITION_FAILED", "ISOLATED_VERTEX",
                        subject + " contains an isolated vertex");
    }
  }
  for (const auto face : mesh.faces()) {
    if (PMP::is_degenerate_triangle_face(face, mesh)) {
      throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_FACE",
                        subject + " contains a degenerate triangle");
    }
  }
  std::vector<Halfedge> non_manifold;
  PMP::non_manifold_vertices(mesh, std::back_inserter(non_manifold));
  if (!non_manifold.empty()) {
    throw WorkerError("PRECONDITION_FAILED", "NON_MANIFOLD_VERTEX",
                      subject + " contains a non-manifold vertex");
  }
  if (PMP::does_self_intersect(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "SELF_INTERSECTION",
                      subject + " self-intersects");
  }
  if (!PMP::does_bound_a_volume(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "MESH_DOES_NOT_BOUND_VOLUME",
                      subject + " does not bound a valid volume");
  }
  require_positive_component_orientation(mesh, subject);
}

void require_shape(const ArtifactInput& input) {
  if (input.type != "TriangleSurfaceMesh" || input.format != "off") {
    throw WorkerError("INVALID_INPUT", "INPUT_TYPE_OR_FORMAT_MISMATCH",
                      "Boolean operations require TriangleSurfaceMesh/OFF inputs");
  }
  if (kLengthUnits.count(input.unit) == 0) {
    throw WorkerError("INVALID_INPUT", "UNSUPPORTED_UNIT",
                      "Boolean mesh units must be mm, cm, or m");
  }
}

bool exactly_binary64(const Kernel::FT& coordinate, double& converted) {
  converted = CGAL::to_double(coordinate);
  return std::isfinite(converted) && Kernel::FT(converted) == coordinate;
}

std::filesystem::path boolean_output_dir(const Request& request) {
  try {
    return checked_output_dir(request);
  } catch (const WorkerError& error) {
    if (error.error_class == "INVALID_REQUEST") {
      throw WorkerError("INVALID_INPUT", error.code, error.what(),
                        error.recoverable, error.suggested_operations);
    }
    throw;
  }
}

std::filesystem::path boolean_output_path(
    const std::filesystem::path& directory, const std::string& filename) {
  try {
    return output_path(directory, filename);
  } catch (const WorkerError& error) {
    if (error.error_class == "OUTPUT_ERROR") {
      throw WorkerError("IO_FAILURE", error.code, error.what(),
                        error.recoverable, error.suggested_operations);
    }
    throw;
  }
}

void commit_boolean_output(const std::filesystem::path& temporary,
                           const std::filesystem::path& destination) {
  try {
    commit_output(temporary, destination);
  } catch (const WorkerError& error) {
    if (error.error_class == "OUTPUT_ERROR") {
      throw WorkerError("IO_FAILURE", error.code, error.what(),
                        error.recoverable, error.suggested_operations);
    }
    throw;
  }
}

std::filesystem::path temporary_path(const Request& request,
                                     const std::string& extension) {
  const auto directory = boolean_output_dir(request);
  const auto path = directory /
                    ("." + staging_filename_token(request.request_id) +
                     ".boolean." + extension + ".tmp");
  std::error_code error;
  if (std::filesystem::exists(path, error) || error) {
    throw WorkerError("IO_FAILURE", "TEMPORARY_OUTPUT_EXISTS",
                      "Boolean temporary output already exists");
  }
  return path;
}

template <class Predicate>
bool all_samples(const Mesh& samples, const Mesh& domain, Predicate predicate) {
  CGAL::Side_of_triangle_mesh<Mesh, Kernel> side(domain);
  for (const auto vertex : samples.vertices()) {
    if (!predicate(side(samples.point(vertex)))) return false;
  }
  for (const auto face : samples.faces()) {
    const auto h = samples.halfedge(face);
    const auto& a = samples.point(samples.target(h));
    const auto& b = samples.point(samples.target(samples.next(h)));
    const auto& c = samples.point(samples.target(samples.prev(h)));
    const Point centroid((a.x() + b.x() + c.x()) / Kernel::FT(3),
                         (a.y() + b.y() + c.y()) / Kernel::FT(3),
                         (a.z() + b.z() + c.z()) / Kernel::FT(3));
    if (!predicate(side(centroid))) return false;
  }
  return true;
}

bool same_exact_volume(const Mesh& candidate, const BooleanResult& reference) {
  if (candidate.number_of_faces() == 0) return reference.empty;
  return !reference.empty && mesh_volume(candidate) == reference.volume;
}

}  // namespace

std::string operation_name(BooleanKind kind) {
  if (kind == BooleanKind::kUnion) return "union";
  if (kind == BooleanKind::kIntersection) return "intersection";
  return "difference";
}

std::string operation_id(BooleanKind kind) {
  return "mesh.boolean." + operation_name(kind);
}

std::string validator_id(BooleanKind kind) {
  return "mesh.validate.boolean_" + operation_name(kind);
}

void require_boolean_request(const Request& request, BooleanKind kind,
                             bool validator) {
  if (request.kernel != "exact_constructions" &&
      request.kernel != "package_recommended") {
    throw WorkerError(
        "UNSUPPORTED_ADAPTER", "UNSUPPORTED_KERNEL",
        "PMP Boolean revision 1 supports exact_constructions and "
        "package_recommended, both mapped to EPECK");
  }
  const std::size_t expected = validator ? 3 : 2;
  if (request.inputs.size() != expected) {
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "PMP Boolean request has the wrong input count");
  }
  for (const auto& input : request.inputs) require_shape(input);
  const auto& unit = request.inputs.front().unit;
  for (const auto& input : request.inputs) {
    if (input.unit != unit) {
      throw WorkerError("INVALID_INPUT", "UNIT_MISMATCH",
                        "Both Boolean sources and candidate must use one unit");
    }
  }
  if (request.parameters.size() != 1 ||
      !request.parameters.contains("operation") ||
      !request.parameters.at("operation").is_string() ||
      request.parameters.at("operation").get<std::string>() !=
          operation_name(kind)) {
    throw WorkerError(
        "INVALID_INPUT", "BOOLEAN_OPERATION_BINDING_MISMATCH",
        "The exact operation parameter must match the registered Boolean handler");
  }
}

Mesh read_boolean_source(const ArtifactInput& input,
                         const std::string& subject) {
  require_shape(input);
  auto mesh = parse_off(input, false);
  require_numeric_scale(mesh, subject);
  require_healthy_volume_mesh(mesh, subject, false);
  return mesh;
}

Mesh read_boolean_candidate(const ArtifactInput& input) {
  require_shape(input);
  auto mesh = parse_off(input, true);
  if (mesh.number_of_faces() != 0) {
    require_numeric_scale(mesh, "Boolean candidate");
  }
  require_healthy_volume_mesh(mesh, "Boolean candidate", true);
  return mesh;
}

Kernel::FT mesh_volume(const Mesh& mesh) {
  if (mesh.number_of_faces() == 0) return Kernel::FT(0);
  return PMP::volume(mesh);
}

std::string exact_number(const Kernel::FT& value) {
  std::ostringstream stream;
  stream << CGAL::exact(value);
  return stream.str();
}

BooleanResult compute_boolean(const Mesh& source_a, const Mesh& source_b,
                              BooleanKind kind) {
  Mesh first = source_a;
  Mesh second = source_b;
  Mesh output;
  bool manifold = false;
  try {
    if (kind == BooleanKind::kUnion) {
      manifold = PMP::corefine_and_compute_union(first, second, output);
    } else if (kind == BooleanKind::kIntersection) {
      manifold = PMP::corefine_and_compute_intersection(first, second, output);
    } else {
      manifold = PMP::corefine_and_compute_difference(first, second, output);
    }
  } catch (const std::exception& error) {
    throw WorkerError("CGAL_EXCEPTION", "BOOLEAN_ALGORITHM_FAILED",
                      std::string("CGAL corefinement failed: ") + error.what());
  }
  if (!manifold) {
    throw WorkerError(
        "PRECONDITION_FAILED", "BOOLEAN_RESULT_NOT_MANIFOLD",
        "CGAL could not construct a manifold result; contact is not published");
  }
  output.collect_garbage();
  BooleanResult result;
  result.surfaces_contact = PMP::do_intersect(source_a, source_b);
  if (output.number_of_faces() == 0) {
    output.clear();
    result.empty = true;
    if (kind == BooleanKind::kUnion) {
      throw WorkerError("CGAL_EXCEPTION", "UNEXPECTED_EMPTY_UNION",
                        "Union of two nonempty volumes cannot be empty");
    }
    if (kind == BooleanKind::kIntersection) {
      result.empty_reason = result.surfaces_contact
                                ? "lower_dimensional_contact"
                                : "disjoint_or_nonoverlapping_volumes";
    } else {
      result.empty_reason = "source_a_contained_in_or_equal_to_source_b";
    }
  } else {
    require_healthy_volume_mesh(output, "Boolean result", false);
    result.volume = mesh_volume(output);
  }
  result.mesh = std::move(output);
  return result;
}

std::filesystem::path write_boolean_mesh(const Request& request,
                                         const Mesh& mesh) {
  const auto directory = boolean_output_dir(request);
  const auto destination = boolean_output_path(directory, "geometry.off");
  const auto temporary = temporary_path(request, "off");
  std::ofstream output(temporary, std::ios::binary);
  output.imbue(std::locale::classic());
  output << "OFF\n" << mesh.number_of_vertices() << ' '
         << mesh.number_of_faces() << " 0\n";
  std::vector<std::size_t> indices(mesh.number_of_vertices());
  std::size_t next_index = 0;
  output << std::setprecision(17);
  for (const auto vertex : mesh.vertices()) {
    const auto& point = mesh.point(vertex);
    double x = 0, y = 0, z = 0;
    if (!exactly_binary64(point.x(), x) || !exactly_binary64(point.y(), y) ||
        !exactly_binary64(point.z(), z)) {
      output.close();
      std::filesystem::remove(temporary);
      throw WorkerError(
          "NUMERIC_FAILURE", "OUTPUT_BINARY64_LOSS",
          "Exact Boolean coordinates are not representable in standard binary64 OFF");
    }
    indices[vertex.idx()] = next_index++;
    output << x << ' ' << y << ' ' << z << '\n';
  }
  for (const auto face : mesh.faces()) {
    output << '3';
    for (const auto vertex : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      output << ' ' << indices[vertex.idx()];
    }
    output << '\n';
  }
  output.flush();
  if (!output) {
    output.close();
    std::filesystem::remove(temporary);
    throw WorkerError("IO_FAILURE", "OUTPUT_WRITE_FAILED",
                      "Unable to write Boolean OFF output");
  }
  output.close();
  commit_boolean_output(temporary, destination);
  return destination;
}

std::filesystem::path write_boolean_validation(const Request& request,
                                               const Json& report) {
  const auto directory = boolean_output_dir(request);
  const auto destination = boolean_output_path(directory, "validation.json");
  const auto temporary = temporary_path(request, "json");
  std::ofstream output(temporary, std::ios::binary);
  output << report.dump() << '\n';
  if (!output) {
    output.close();
    std::filesystem::remove(temporary);
    throw WorkerError("IO_FAILURE", "OUTPUT_WRITE_FAILED",
                      "Unable to write Boolean validation report");
  }
  output.close();
  commit_boolean_output(temporary, destination);
  return destination;
}

Json validate_boolean_semantics(const Mesh& source_a, const Mesh& source_b,
                                const Mesh& candidate, BooleanKind kind,
                                const BooleanResult& reference) {
  const bool candidate_empty = candidate.number_of_faces() == 0;
  const bool status_matches = candidate_empty == reference.empty;
  const bool volume_matches = same_exact_volume(candidate, reference);
  bool exact_set_matches = candidate_empty && reference.empty;
  if (!candidate_empty && !reference.empty) {
    try {
      const auto candidate_minus_reference =
          compute_boolean(candidate, reference.mesh, BooleanKind::kDifference);
      const auto reference_minus_candidate =
          compute_boolean(reference.mesh, candidate, BooleanKind::kDifference);
      exact_set_matches = candidate_minus_reference.empty &&
                          reference_minus_candidate.empty;
    } catch (const WorkerError&) {
      exact_set_matches = false;
    }
  }
  bool classification_matches = true;
  if (!candidate_empty) {
    const auto not_outside = [](CGAL::Bounded_side side) {
      return side != CGAL::ON_UNBOUNDED_SIDE;
    };
    const auto not_inside = [](CGAL::Bounded_side side) {
      return side != CGAL::ON_BOUNDED_SIDE;
    };
    if (kind == BooleanKind::kUnion) {
      classification_matches =
          all_samples(source_a, candidate, not_outside) &&
          all_samples(source_b, candidate, not_outside) &&
          all_samples(candidate, source_a, not_inside) &&
          all_samples(candidate, source_b, not_inside);
    } else if (kind == BooleanKind::kIntersection) {
      classification_matches =
          all_samples(candidate, source_a, not_outside) &&
          all_samples(candidate, source_b, not_outside);
    } else {
      classification_matches =
          all_samples(candidate, source_a, not_outside) &&
          all_samples(candidate, source_b, not_inside);
    }
  }
  if (!status_matches || !volume_matches || !classification_matches ||
      !exact_set_matches) {
    throw WorkerError(
        "VALIDATION_FAILED", "BOOLEAN_SET_SEMANTICS_MISMATCH",
        "Candidate status, exact volume, exact set, or operation-specific classification differs from the bound sources");
  }
  const auto candidate_volume = mesh_volume(candidate);
  return {{"topology_valid", true},
          {"closed_or_canonical_empty", true},
          {"volume_boundary_orientation_valid", true},
          {"self_intersection_free", true},
          {"operation_parameter_bound", true},
          {"result_status_matches_reference", true},
          {"exact_volume_matches_reference", true},
          {"mutual_exact_difference_empty", true},
          {"operation_classification_matches", true},
          {"result_status", candidate_empty ? "empty" : "volume"},
          {"empty_reason", candidate_empty ? reference.empty_reason : ""},
          {"candidate_exact_volume", exact_number(candidate_volume)},
          {"reference_exact_volume", exact_number(reference.volume)}};
}

}  // namespace cgal_master::wave_a_boolean
