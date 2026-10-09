#include "reconstruction_common.h"

#include "../artifact_io.h"
#include "../wave_c/wave_c_common.h"
#include "../wave_d/wave_d_common.h"

#include <gmpxx.h>

#include <algorithm>
#include <charconv>
#include <cmath>
#include <map>
#include <numeric>
#include <set>
#include <sstream>
#include <utility>

namespace cgal_master::reconstruction_ops {
namespace {

using Q = mpq_class;

[[noreturn]] void input_error(const std::string& code, const std::string& message) {
  throw WorkerError("INVALID_INPUT", code, message);
}

std::vector<std::string> split_lines(const std::string& bytes) {
  std::vector<std::string> lines;
  std::string line;
  std::istringstream stream(bytes);
  while (std::getline(stream, line)) {
    if (!line.empty() && line.back() == '\r') line.pop_back();
    lines.push_back(line);
  }
  return lines;
}

std::vector<std::string> tokens_of(const std::string& line) {
  std::vector<std::string> result;
  std::string current;
  for (const char c : line) {
    if (c == ' ' || c == '\t') {
      if (!current.empty()) result.push_back(current);
      current.clear();
    } else {
      current.push_back(c);
    }
  }
  if (!current.empty()) result.push_back(current);
  return result;
}

bool parse_double(const std::string& token, double& value) {
  const char* begin = token.data();
  const char* end = token.data() + token.size();
  if (begin != end && *begin == '+') ++begin;
  const auto parsed = std::from_chars(begin, end, value);
  return parsed.ec == std::errc() && parsed.ptr == end && std::isfinite(value);
}

double finite_number(const std::string& token, const std::string& code, std::size_t line) {
  double value = 0;
  if (!parse_double(token, value)) {
    input_error(code, "Invalid or non-finite number on line " + std::to_string(line));
  }
  return value == 0 ? 0.0 : value;
}

std::string verified_text(const ArtifactInput& input, const char* type, const char* format) {
  require_input_shape(input, type, format);
  auto bytes = read_verified_input_bytes(input);
  if (bytes.size() >= 3 && static_cast<unsigned char>(bytes[0]) == 0xEF &&
      static_cast<unsigned char>(bytes[1]) == 0xBB && static_cast<unsigned char>(bytes[2]) == 0xBF) {
    bytes.erase(0, 3);
  }
  return bytes;
}

Q exact(double value) {
  Q result;
  mpq_set_d(result.get_mpq_t(), value);
  return result;
}

}  // namespace

PointCloud read_points(const ArtifactInput& input) {
  const auto lines = split_lines(verified_text(input, "PointSet3", "xyz"));
  PointCloud cloud;
  for (std::size_t i = 0; i < lines.size(); ++i) {
    auto line = lines[i];
    const auto comment = line.find('#');
    if (comment != std::string::npos) line.erase(comment);
    const auto tokens = tokens_of(line);
    if (tokens.empty()) continue;
    if (tokens.size() != 3) input_error("MALFORMED_XYZ", "Each nonblank XYZ line must have exactly x y z");
    cloud.points.push_back({finite_number(tokens[0], "MALFORMED_XYZ", i + 1),
                            finite_number(tokens[1], "MALFORMED_XYZ", i + 1),
                            finite_number(tokens[2], "MALFORMED_XYZ", i + 1)});
    if (cloud.points.size() > kMaximumPoints) {
      throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "Point set exceeds the reconstruction limit");
    }
  }
  return cloud;
}

PointCloud read_points_with_normals(const ArtifactInput& input) {
  const auto lines = split_lines(verified_text(input, "PointSet3Normals", "ply"));
  if (lines.size() < 2 || lines[0] != "ply" || lines[1] != "format ascii 1.0") {
    input_error("UNSUPPORTED_PLY", "PointSet3Normals accepts ASCII PLY 1.0 only");
  }
  static const std::set<std::string> scalar_types = {"float", "double", "float32", "float64"};
  std::size_t count = 0;
  bool have_vertex = false;
  std::size_t line = 2;
  std::vector<std::string> properties;
  for (;; ++line) {
    if (line >= lines.size()) input_error("MALFORMED_PLY", "PLY header has no end_header");
    const auto fields = tokens_of(lines[line]);
    if (fields.empty()) continue;
    if (fields.size() == 1 && fields[0] == "end_header") break;
    if (fields[0] == "comment" || fields[0] == "obj_info") continue;
    if (fields[0] == "element") {
      if (have_vertex || fields.size() != 3 || fields[1] != "vertex") {
        input_error("UNSUPPORTED_PLY", "PLY must contain exactly one vertex element and no faces");
      }
      std::size_t consumed = 0;
      try {
        count = static_cast<std::size_t>(std::stoull(fields[2], &consumed));
      } catch (const std::exception&) {
        input_error("MALFORMED_PLY", "Invalid PLY vertex count");
      }
      if (consumed != fields[2].size()) input_error("MALFORMED_PLY", "Invalid PLY vertex count");
      have_vertex = true;
    } else if (fields[0] == "property") {
      if (!have_vertex || fields.size() != 3 || scalar_types.count(fields[1]) == 0 ||
          std::find(properties.begin(), properties.end(), fields[2]) != properties.end()) {
        input_error("MALFORMED_PLY", "Unsupported PLY property");
      }
      properties.push_back(fields[2]);
    } else {
      input_error("MALFORMED_PLY", "Unsupported PLY header line");
    }
  }
  const std::vector<std::string> required = {"x", "y", "z", "nx", "ny", "nz"};
  std::vector<std::size_t> slot;
  for (const auto& name : required) {
    const auto it = std::find(properties.begin(), properties.end(), name);
    if (it == properties.end()) {
      input_error("MISSING_NORMAL_PROPERTY", "PLY requires x, y, z, nx, ny and nz properties");
    }
    slot.push_back(static_cast<std::size_t>(it - properties.begin()));
  }
  if (properties.size() != required.size()) input_error("MALFORMED_PLY", "PLY must have exactly x y z nx ny nz");
  if (!have_vertex || count == 0) input_error("MALFORMED_PLY", "PLY has no vertices");
  if (count > kMaximumPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "Point set exceeds the reconstruction limit");
  }
  PointCloud cloud;
  std::size_t next = line + 1;
  for (std::size_t i = 0; i < count; ++i, ++next) {
    if (next >= lines.size()) input_error("MALFORMED_PLY", "PLY ended before all vertices");
    const auto tokens = tokens_of(lines[next]);
    if (tokens.size() != properties.size()) input_error("MALFORMED_PLY", "PLY vertex property count mismatch");
    std::array<double, 6> values{};
    for (std::size_t k = 0; k < 6; ++k) values[k] = finite_number(tokens[slot[k]], "MALFORMED_PLY", next + 1);
    cloud.points.push_back({values[0], values[1], values[2]});
    cloud.normals.push_back({values[3], values[4], values[5]});
  }
  for (; next < lines.size(); ++next) {
    if (!tokens_of(lines[next]).empty()) input_error("MALFORMED_PLY", "PLY has trailing data");
  }
  return cloud;
}

RawMesh read_candidate_mesh(const ArtifactInput& input) {
  require_input_shape(input, "TriangleSurfaceMesh", "off");
  const auto lines = split_lines(read_verified_input_bytes(input));
  std::vector<std::string> tokens;
  for (auto line : lines) {
    const auto comment = line.find('#');
    if (comment != std::string::npos) line.erase(comment);
    for (auto& token : tokens_of(line)) tokens.push_back(std::move(token));
  }
  std::size_t at = 0;
  const auto next = [&]() -> const std::string& {
    if (at >= tokens.size()) validation_failure("MALFORMED_CANDIDATE", "Candidate OFF ended early");
    return tokens[at++];
  };
  const auto count = [&](const std::string& token) {
    std::size_t value = 0;
    const auto parsed = std::from_chars(token.data(), token.data() + token.size(), value);
    if (parsed.ec != std::errc() || parsed.ptr != token.data() + token.size()) {
      validation_failure("MALFORMED_CANDIDATE", "Candidate OFF has an invalid count or index");
    }
    return value;
  };
  if (next() != "OFF") validation_failure("MALFORMED_CANDIDATE", "Candidate must be an OFF file");
  const std::size_t vertex_count = count(next());
  const std::size_t face_count = count(next());
  count(next());
  if (vertex_count == 0 || face_count == 0 || vertex_count > 3 * kMaximumOutputFaces ||
      face_count > kMaximumOutputFaces) {
    validation_failure("CANDIDATE_SIZE_UNSUPPORTED", "Candidate is empty or exceeds the validation budget");
  }
  RawMesh mesh;
  for (std::size_t i = 0; i < vertex_count; ++i) {
    V3 v{};
    for (auto& coordinate : v) {
      if (!parse_double(next(), coordinate)) validation_failure("MALFORMED_CANDIDATE", "Non-finite candidate vertex");
      if (coordinate == 0) coordinate = 0.0;
    }
    mesh.vertices.push_back(v);
  }
  for (std::size_t i = 0; i < face_count; ++i) {
    if (count(next()) != 3) validation_failure("NOT_TRIANGLE_MESH", "Candidate has a non-triangle face");
    std::array<std::size_t, 3> face{};
    for (auto& index : face) {
      index = count(next());
      if (index >= vertex_count) validation_failure("MALFORMED_CANDIDATE", "Candidate face index out of range");
    }
    mesh.faces.push_back(face);
  }
  if (at != tokens.size()) validation_failure("MALFORMED_CANDIDATE", "Candidate OFF has trailing data");
  return mesh;
}

void require_point_budget(const PointCloud& cloud) {
  if (cloud.points.size() < kMinimumPoints) {
    precondition("TOO_FEW_POINTS", "Surface reconstruction needs at least " + std::to_string(kMinimumPoints) +
                                       " points");
  }
  std::set<V3> seen(cloud.points.begin(), cloud.points.end());
  if (seen.size() != cloud.points.size()) precondition("DUPLICATE_POINT", "The point set repeats a point");
  if (affine_rank(cloud.points) < 3) {
    precondition("DEGENERATE_POINT_SET", "The points are coplanar, collinear or coincident (affine rank < 3)");
  }
}

int affine_rank(const std::vector<V3>& points) {
  if (points.empty()) return 0;
  // Exact Gaussian elimination on the difference vectors.
  std::vector<std::array<Q, 3>> basis;
  const auto origin = points[0];
  for (std::size_t i = 1; i < points.size() && basis.size() < 3; ++i) {
    std::array<Q, 3> v{exact(points[i][0]) - exact(origin[0]), exact(points[i][1]) - exact(origin[1]),
                       exact(points[i][2]) - exact(origin[2])};
    for (const auto& b : basis) {
      std::size_t pivot = 0;
      while (b[pivot] == 0) ++pivot;
      const Q factor = v[pivot] / b[pivot];
      for (int k = 0; k < 3; ++k) v[k] -= factor * b[k];
    }
    if (v[0] != 0 || v[1] != 0 || v[2] != 0) basis.push_back(v);
  }
  return static_cast<int>(basis.size());
}

Topology analyze_topology(const RawMesh& mesh) {
  Topology t;
  t.vertex_count = mesh.vertices.size();
  t.face_count = mesh.faces.size();
  std::vector<std::size_t> parent(mesh.faces.size());
  std::iota(parent.begin(), parent.end(), 0);
  const std::function<std::size_t(std::size_t)> find = [&](std::size_t x) {
    while (parent[x] != x) x = parent[x] = parent[parent[x]];
    return x;
  };
  std::map<std::pair<std::size_t, std::size_t>, std::vector<std::pair<std::size_t, bool>>> edges;
  std::vector<std::vector<std::size_t>> incident(mesh.vertices.size());
  for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
    const auto& face = mesh.faces[f];
    if (face[0] == face[1] || face[1] == face[2] || face[0] == face[2]) {
      ++t.repeated_index_face_count;
      continue;
    }
    for (int k = 0; k < 3; ++k) {
      const std::size_t a = face[k], b = face[(k + 1) % 3];
      edges[{std::min(a, b), std::max(a, b)}].push_back({f, a < b});
      incident[a].push_back(f);
    }
  }
  t.edge_count = edges.size();
  t.edge_manifold = true;
  t.consistently_oriented = true;
  for (const auto& [edge, uses] : edges) {
    if (uses.size() == 1) ++t.boundary_edge_count;
    if (uses.size() > 2) t.edge_manifold = false;
    if (uses.size() == 2) {
      if (uses[0].second == uses[1].second) t.consistently_oriented = false;
      parent[find(uses[0].first)] = find(uses[1].first);
    }
  }
  t.closed = t.boundary_edge_count == 0;
  for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
    if (find(f) == f) ++t.component_count;
  }
  // Vertex manifold: the faces around each vertex are one fan connected through
  // edges incident to that vertex.
  t.vertex_manifold = true;
  for (std::size_t v = 0; v < mesh.vertices.size(); ++v) {
    const auto& faces = incident[v];
    if (faces.empty()) {
      ++t.unreferenced_vertex_count;
      continue;
    }
    std::map<std::size_t, std::size_t> local;
    for (std::size_t i = 0; i < faces.size(); ++i) local[faces[i]] = i;
    std::vector<std::size_t> fan(faces.size());
    std::iota(fan.begin(), fan.end(), 0);
    const std::function<std::size_t(std::size_t)> root = [&](std::size_t x) {
      while (fan[x] != x) x = fan[x] = fan[fan[x]];
      return x;
    };
    for (const auto f : faces) {
      for (const auto w : mesh.faces[f]) {
        if (w == v) continue;
        const auto it = edges.find({std::min(v, w), std::max(v, w)});
        if (it == edges.end()) continue;
        for (const auto& use : it->second) {
          const auto other = local.find(use.first);
          if (other != local.end()) fan[root(local[f])] = root(other->second);
        }
      }
    }
    std::size_t roots = 0;
    for (std::size_t i = 0; i < fan.size(); ++i) roots += root(i) == i ? 1 : 0;
    if (roots != 1) t.vertex_manifold = false;
  }
  t.euler_characteristic = static_cast<long long>(t.vertex_count - t.unreferenced_vertex_count) -
                           static_cast<long long>(t.edge_count) + static_cast<long long>(t.face_count);
  return t;
}

void require_inputs(const Request& request, std::size_t count, const std::string& operation) {
  wave_c::require_input_count(request, count, operation);
}

void require_parameter_names(const Request& request, std::initializer_list<const char*> required,
                             std::initializer_list<const char*> optional) {
  wave_c::require_parameters(request, required, optional);
}

std::size_t integer_parameter(const Request& request, const char* name, std::size_t minimum,
                              std::size_t maximum) {
  return wave_c::integer_parameter(request, name, minimum, maximum);
}

double number_parameter(const Request& request, const char* name, double exclusive_minimum, double maximum) {
  return wave_d::number_parameter(request, name, exclusive_minimum, maximum);
}

double length_parameter(const Request& request, const char* name, const std::string& unit) {
  const double value = wave_c::typed_length_parameter(request, name, unit);
  if (!(value > 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be positive");
  }
  return value;
}

void require_same_unit(const ArtifactInput& first, const ArtifactInput& second) {
  wave_c::require_same_unit(first, second);
}

Json finish_reconstruction_validation(const Request& request, const std::string& validator, Json report) {
  return wave_c::finish_validation(request, validator, std::move(report));
}

void precondition(const std::string& code, const std::string& message) {
  throw WorkerError("PRECONDITION_FAILED", code, message);
}

void validation_failure(const std::string& code, const std::string& message) {
  wave_c::fail_validation(code, message);
}

OperationDefinition reconstruction_definition(std::string id, std::vector<std::string> inputs,
                                              std::string output, std::string role,
                                              std::function<Json(const Request&)> execute,
                                              std::vector<std::string> dependencies, Json info) {
  return wave_c::make_definition(std::move(id), std::move(inputs), std::move(output), std::move(role),
                                 std::move(execute), std::move(dependencies), std::move(info));
}

}  // namespace cgal_master::reconstruction_ops
