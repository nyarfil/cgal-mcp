#include "wave_d_common.h"
#include "wave_d_operations.h"

#include "../artifact_io.h"
#include "../wave_a/mesh_io.h"

#include <CGAL/Polygon_mesh_processing/repair_degeneracies.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Polygon_mesh_processing/shape_predicates.h>
#include <CGAL/Polygon_mesh_processing/repair.h>
#include <CGAL/boost/graph/helpers.h>

#include <algorithm>
#include <cmath>
#include <cstdlib>
#include <limits>
#include <numeric>
#include <set>
#include <sstream>
#include <unordered_map>

namespace cgal_master::wave_d {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;

constexpr double kPi = 3.14159265358979323846;

[[noreturn]] void input_error(const std::string& code, const std::string& message) {
  throw WorkerError("INPUT_ERROR", code, message);
}

void require_shape(const ArtifactInput& input, std::initializer_list<const char*> types) {
  bool accepted = false;
  std::string names;
  for (const char* type : types) {
    accepted = accepted || input.type == type;
    names += (names.empty() ? "" : ", ") + std::string(type);
  }
  if (!accepted) {
    throw WorkerError("TYPE_ERROR", "INPUT_TYPE_MISMATCH",
                      "Expected input type " + names + ", received " + input.type);
  }
  if (input.format != "off") {
    throw WorkerError("TYPE_ERROR", "INPUT_FORMAT_MISMATCH",
                      "Expected input format off, received " + input.format);
  }
  if (input.unit != "mm" && input.unit != "cm" && input.unit != "m") {
    throw WorkerError("TYPE_ERROR", "UNSUPPORTED_UNIT", "Geometry unit must be one of: mm, cm, m");
  }
}

// Strict OFF parser shared by the independent validators (no CGAL IO).
RawMesh parse_off(const std::string& bytes) {
  std::vector<std::string> tokens;
  {
    std::istringstream stream(bytes);
    stream.imbue(std::locale::classic());
    std::string token;
    while (stream >> token) tokens.push_back(token);
  }
  std::size_t position = 0;
  auto next = [&]() -> const std::string& {
    if (position >= tokens.size()) input_error("MALFORMED_OFF", "OFF data is truncated");
    return tokens[position++];
  };
  auto integer = [&](const std::string& token) -> std::size_t {
    if (token.empty() || token.find_first_not_of("0123456789") != std::string::npos ||
        token.size() > 12) {
      input_error("MALFORMED_OFF", "OFF count/index must be a non-negative integer");
    }
    return static_cast<std::size_t>(std::stoull(token));
  };
  if (next() != "OFF") input_error("MALFORMED_OFF", "OFF header is missing");
  const std::size_t vertex_count = integer(next());
  const std::size_t face_count = integer(next());
  integer(next());
  if (vertex_count == 0 || face_count == 0) {
    input_error("MALFORMED_OFF", "OFF mesh must contain vertices and faces");
  }
  if (face_count > kMaximumOutputFaces || vertex_count > 3 * kMaximumOutputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED",
                      "OFF mesh exceeds the Wave D validation size limit");
  }
  RawMesh mesh;
  mesh.vertices.reserve(vertex_count);
  for (std::size_t index = 0; index < vertex_count; ++index) {
    V3 point{};
    for (double& coordinate : point) {
      const std::string& token = next();
      char* end = nullptr;
      coordinate = std::strtod(token.c_str(), &end);
      if (end != token.c_str() + token.size() || !std::isfinite(coordinate)) {
        input_error("NONFINITE_COORDINATE", "OFF coordinate is not a finite number");
      }
    }
    mesh.vertices.push_back(point);
  }
  mesh.faces.reserve(face_count);
  for (std::size_t index = 0; index < face_count; ++index) {
    const std::size_t size = integer(next());
    if (size < 3) input_error("MALFORMED_OFF", "OFF face has fewer than three vertices");
    if (size > kMaximumFaceDegree) {
      throw WorkerError("RESOURCE_LIMIT", "FACE_DEGREE_LIMIT_EXCEEDED",
                        "OFF face degree exceeds the Wave D limit");
    }
    std::vector<std::size_t> face;
    face.reserve(size);
    for (std::size_t corner = 0; corner < size; ++corner) {
      const std::size_t vertex = integer(next());
      if (vertex >= vertex_count) input_error("INDEX_OUT_OF_RANGE", "OFF face index is out of range");
      face.push_back(vertex);
    }
    mesh.faces.push_back(std::move(face));
  }
  if (position != tokens.size()) input_error("MALFORMED_OFF", "OFF has unexpected trailing tokens");
  return mesh;
}

V3 sub(const V3& a, const V3& b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
V3 add(const V3& a, const V3& b) { return {a[0] + b[0], a[1] + b[1], a[2] + b[2]}; }
V3 scale(const V3& a, double s) { return {a[0] * s, a[1] * s, a[2] * s}; }
double dot(const V3& a, const V3& b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
V3 cross(const V3& a, const V3& b) {
  return {a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]};
}
double norm(const V3& a) { return std::sqrt(dot(a, a)); }

struct UnionFind {
  std::vector<std::size_t> parent;
  explicit UnionFind(std::size_t size) : parent(size) {
    std::iota(parent.begin(), parent.end(), std::size_t{0});
  }
  std::size_t find(std::size_t item) {
    while (parent[item] != item) item = parent[item] = parent[parent[item]];
    return item;
  }
  void unite(std::size_t first, std::size_t second) { parent[find(first)] = find(second); }
};

std::uint64_t edge_key(std::size_t first, std::size_t second, std::size_t count) {
  const auto low = std::min(first, second);
  const auto high = std::max(first, second);
  return static_cast<std::uint64_t>(low) * static_cast<std::uint64_t>(count) + high;
}

struct EdgeUse {
  std::size_t forward = 0;   // directed low -> high
  std::size_t backward = 0;  // directed high -> low
};

std::unordered_map<std::uint64_t, EdgeUse> edge_uses(const RawMesh& mesh) {
  std::unordered_map<std::uint64_t, EdgeUse> uses;
  const auto count = mesh.vertices.size();
  for (const auto& face : mesh.faces) {
    for (std::size_t corner = 0; corner < face.size(); ++corner) {
      const auto from = face[corner];
      const auto to = face[(corner + 1) % face.size()];
      auto& use = uses[edge_key(from, to, count)];
      if (from < to) {
        ++use.forward;
      } else {
        ++use.backward;
      }
    }
  }
  return uses;
}

using Triangle = std::array<V3, 3>;

std::vector<Triangle> fan_triangles(const RawMesh& mesh, std::vector<std::size_t>* owner) {
  std::vector<Triangle> triangles;
  for (std::size_t face = 0; face < mesh.faces.size(); ++face) {
    const auto& indices = mesh.faces[face];
    for (std::size_t corner = 1; corner + 1 < indices.size(); ++corner) {
      triangles.push_back({mesh.vertices[indices[0]], mesh.vertices[indices[corner]],
                           mesh.vertices[indices[corner + 1]]});
      if (owner != nullptr) owner->push_back(face);
    }
  }
  return triangles;
}

// Uniform-grid nearest-triangle search written for the validators (no AABB tree).
class TriangleGrid {
 public:
  explicit TriangleGrid(const std::vector<Triangle>& triangles)
      : triangles_(triangles), stamp_(triangles.size(), 0) {
    lower_ = {std::numeric_limits<double>::max(), std::numeric_limits<double>::max(),
              std::numeric_limits<double>::max()};
    V3 upper = {-lower_[0], -lower_[1], -lower_[2]};
    for (const auto& triangle : triangles_) {
      for (const auto& point : triangle) {
        for (int axis = 0; axis < 3; ++axis) {
          lower_[axis] = std::min(lower_[axis], point[axis]);
          upper[axis] = std::max(upper[axis], point[axis]);
        }
      }
    }
    const double diagonal = std::max(norm(sub(upper, lower_)), 1e-300);
    const double target = std::max(1.0, std::cbrt(static_cast<double>(triangles_.size())));
    cell_ = diagonal / target;
    for (int axis = 0; axis < 3; ++axis) {
      dims_[axis] = std::clamp<std::size_t>(
          static_cast<std::size_t>(std::ceil((upper[axis] - lower_[axis]) / cell_)) + 1, 1, 96);
    }
    cells_.resize(dims_[0] * dims_[1] * dims_[2]);
    for (std::size_t index = 0; index < triangles_.size(); ++index) {
      std::array<std::size_t, 3> low{};
      std::array<std::size_t, 3> high{};
      for (int axis = 0; axis < 3; ++axis) {
        double minimum = triangles_[index][0][axis];
        double maximum = minimum;
        for (const auto& point : triangles_[index]) {
          minimum = std::min(minimum, point[axis]);
          maximum = std::max(maximum, point[axis]);
        }
        low[axis] = cell_index(minimum, axis);
        high[axis] = cell_index(maximum, axis);
      }
      for (auto x = low[0]; x <= high[0]; ++x) {
        for (auto y = low[1]; y <= high[1]; ++y) {
          for (auto z = low[2]; z <= high[2]; ++z) cells_[flat(x, y, z)].push_back(index);
        }
      }
    }
  }

  std::pair<double, std::size_t> nearest(const V3& point) {
    ++query_;
    double best = std::numeric_limits<double>::infinity();
    std::size_t best_index = 0;
    std::array<long long, 3> centre{};
    for (int axis = 0; axis < 3; ++axis) {
      centre[axis] = static_cast<long long>(cell_index(point[axis], axis));
    }
    const long long maximum_ring =
        static_cast<long long>(std::max({dims_[0], dims_[1], dims_[2]}));
    for (long long ring = 0; ring <= maximum_ring; ++ring) {
      for (long long dx = -ring; dx <= ring; ++dx) {
        for (long long dy = -ring; dy <= ring; ++dy) {
          for (long long dz = -ring; dz <= ring; ++dz) {
            if (std::max({std::llabs(dx), std::llabs(dy), std::llabs(dz)}) != ring) continue;
            const long long x = centre[0] + dx;
            const long long y = centre[1] + dy;
            const long long z = centre[2] + dz;
            if (x < 0 || y < 0 || z < 0 || x >= static_cast<long long>(dims_[0]) ||
                y >= static_cast<long long>(dims_[1]) || z >= static_cast<long long>(dims_[2])) {
              continue;
            }
            for (const auto index : cells_[flat(static_cast<std::size_t>(x),
                                                 static_cast<std::size_t>(y),
                                                 static_cast<std::size_t>(z))]) {
              if (stamp_[index] == query_) continue;
              stamp_[index] = query_;
              const auto& triangle = triangles_[index];
              const double value =
                  point_triangle_distance(point, triangle[0], triangle[1], triangle[2]);
              if (value < best) {
                best = value;
                best_index = index;
              }
            }
          }
        }
      }
      if (best <= static_cast<double>(ring) * cell_) break;
    }
    return {best, best_index};
  }

 private:
  std::size_t cell_index(double value, int axis) const {
    const double offset = (value - lower_[axis]) / cell_;
    if (!(offset > 0)) return 0;
    return std::min(static_cast<std::size_t>(offset), dims_[axis] - 1);
  }
  std::size_t flat(std::size_t x, std::size_t y, std::size_t z) const {
    return (x * dims_[1] + y) * dims_[2] + z;
  }

  const std::vector<Triangle>& triangles_;
  std::vector<std::uint64_t> stamp_;
  std::uint64_t query_ = 0;
  V3 lower_{};
  double cell_ = 1;
  std::array<std::size_t, 3> dims_{1, 1, 1};
  std::vector<std::vector<std::size_t>> cells_;
};

V3 triangle_normal(const Triangle& triangle) {
  return cross(sub(triangle[1], triangle[0]), sub(triangle[2], triangle[0]));
}

}  // namespace

// ---------------------------------------------------------------- producers --

void require_kernel(const Request& request) {
  if (request.kernel != "package_recommended") {
    throw WorkerError("UNSUPPORTED", "UNSUPPORTED_KERNEL",
                      "Wave D remeshing supports package_recommended (EPICK) only");
  }
}

SurfaceMesh read_producer_mesh(const ArtifactInput& input,
                               std::initializer_list<const char*> accepted_types,
                               bool require_triangles) {
  require_shape(input, accepted_types);
  const auto raw = parse_off(read_verified_input_bytes(input));
  if (raw.faces.size() > kMaximumInputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED",
                      "Input mesh exceeds the Wave D input face limit");
  }
  std::vector<bool> referenced(raw.vertices.size(), false);
  for (const auto& face : raw.faces) {
    if (require_triangles && face.size() != 3) {
      throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED",
                        "Input mesh must be triangulated");
    }
    if (std::set<std::size_t>(face.begin(), face.end()).size() != face.size()) {
      throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_FACE",
                        "Input face repeats a vertex");
    }
    for (const auto vertex : face) referenced[vertex] = true;
  }
  if (std::find(referenced.begin(), referenced.end(), false) != referenced.end()) {
    throw WorkerError("PRECONDITION_FAILED", "ISOLATED_VERTEX",
                      "Input mesh has vertices not used by any face");
  }
  SurfaceMesh mesh;
  std::vector<SurfaceMesh::Vertex_index> handles;
  handles.reserve(raw.vertices.size());
  for (const auto& point : raw.vertices) {
    handles.push_back(mesh.add_vertex(Point3(point[0], point[1], point[2])));
  }
  for (const auto& face : raw.faces) {
    std::vector<SurfaceMesh::Vertex_index> cycle;
    for (const auto vertex : face) cycle.push_back(handles[vertex]);
    if (mesh.add_face(cycle) == SurfaceMesh::null_face()) {
      throw WorkerError("PRECONDITION_FAILED", "NON_MANIFOLD_INPUT",
                        "Input is not an oriented 2-manifold polygon mesh");
    }
  }
  if (!CGAL::is_valid_polygon_mesh(mesh)) {
    throw WorkerError("PRECONDITION_FAILED", "INVALID_POLYGON_MESH",
                      "Input is not a valid polygon mesh");
  }
  std::vector<SurfaceMesh::Halfedge_index> pinched;
  PMP::non_manifold_vertices(mesh, std::back_inserter(pinched));
  if (!pinched.empty()) {
    throw WorkerError("PRECONDITION_FAILED", "NON_MANIFOLD_VERTEX",
                      "Input contains a non-manifold vertex");
  }
  for (const auto face : mesh.faces()) {
    if (CGAL::is_triangle(mesh.halfedge(face), mesh)) {
      if (PMP::is_degenerate_triangle_face(face, mesh)) {
        throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_FACE",
                          "Input contains a degenerate triangle");
      }
    }
  }
  const auto facts = analyze(raw);
  if (facts.degenerate_face_count != 0) {
    throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_FACE",
                      "Input contains a degenerate face");
  }
  return mesh;
}

void require_output_budget(const SurfaceMesh& mesh, const std::string& operation) {
  if (mesh.number_of_faces() > kMaximumOutputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "OUTPUT_FACE_LIMIT_EXCEEDED",
                      operation + " output exceeds the Wave D validation budget");
  }
}

Json write_mesh_candidate(const Request& request, SurfaceMesh& mesh, const std::string& unit) {
  if (mesh.has_garbage()) mesh.collect_garbage();
  if (mesh.number_of_faces() == 0) {
    throw WorkerError("INTERNAL", "EMPTY_OUTPUT", "Operation produced an empty mesh");
  }
  for (const auto vertex : mesh.vertices()) {
    const auto& point = mesh.point(vertex);
    if (!std::isfinite(point.x()) || !std::isfinite(point.y()) || !std::isfinite(point.z())) {
      throw WorkerError("INTERNAL", "NONFINITE_OUTPUT", "Operation produced a non-finite vertex");
    }
  }
  const auto path = wave_a::write_mesh_output(request, mesh);
  return wave_a::geometry_output(path, unit);
}

double number_parameter(const Request& request, const char* name, double exclusive_minimum,
                        double maximum) {
  const auto& value = request.parameters.at(name);
  if (!value.is_number() || value.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be a number");
  }
  const double result = value.get<double>();
  if (!std::isfinite(result) || !(result > exclusive_minimum) || result > maximum) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " is outside its supported range");
  }
  return result;
}

// --------------------------------------------------------------- validators --

RawMesh read_raw_mesh(const ArtifactInput& input,
                      std::initializer_list<const char*> accepted_types) {
  require_shape(input, accepted_types);
  return parse_off(read_verified_input_bytes(input));
}

double distance(const V3& a, const V3& b) { return norm(sub(a, b)); }

double point_segment_distance(const V3& p, const V3& a, const V3& b) {
  const V3 ab = sub(b, a);
  const double length2 = dot(ab, ab);
  double t = length2 > 0 ? dot(sub(p, a), ab) / length2 : 0.0;
  t = std::clamp(t, 0.0, 1.0);
  return distance(p, add(a, scale(ab, t)));
}

// Closest point on triangle (Ericson, Real-Time Collision Detection 5.1.5).
double point_triangle_distance(const V3& p, const V3& a, const V3& b, const V3& c) {
  const V3 ab = sub(b, a);
  const V3 ac = sub(c, a);
  const V3 ap = sub(p, a);
  const double d1 = dot(ab, ap);
  const double d2 = dot(ac, ap);
  if (d1 <= 0 && d2 <= 0) return distance(p, a);
  const V3 bp = sub(p, b);
  const double d3 = dot(ab, bp);
  const double d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return distance(p, b);
  const double vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) {
    const double v = d1 / (d1 - d3);
    return distance(p, add(a, scale(ab, v)));
  }
  const V3 cp = sub(p, c);
  const double d5 = dot(ab, cp);
  const double d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return distance(p, c);
  const double vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) {
    const double w = d2 / (d2 - d6);
    return distance(p, add(a, scale(ac, w)));
  }
  const double va = d3 * d6 - d5 * d4;
  if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
    const double w = (d4 - d3) / ((d4 - d3) + (d5 - d6));
    return distance(p, add(b, scale(sub(c, b), w)));
  }
  const double denominator = va + vb + vc;
  if (!(denominator > 0)) {
    // Degenerate triangle: fall back to its edges.
    return std::min({point_segment_distance(p, a, b), point_segment_distance(p, b, c),
                     point_segment_distance(p, c, a)});
  }
  const double v = vb / denominator;
  const double w = vc / denominator;
  return distance(p, add(a, add(scale(ab, v), scale(ac, w))));
}

V3 face_normal(const RawMesh& mesh, std::size_t face) {
  // Newell normal (twice the vector area).
  V3 normal{0, 0, 0};
  const auto& indices = mesh.faces[face];
  for (std::size_t corner = 0; corner < indices.size(); ++corner) {
    normal = add(normal, cross(mesh.vertices[indices[corner]],
                               mesh.vertices[indices[(corner + 1) % indices.size()]]));
  }
  return normal;
}

MeshFacts analyze(const RawMesh& mesh) {
  MeshFacts facts;
  const auto count = mesh.vertices.size();
  facts.vertex_count = count;
  facts.face_count = mesh.faces.size();
  facts.all_triangles = std::all_of(mesh.faces.begin(), mesh.faces.end(),
                                    [](const auto& face) { return face.size() == 3; });
  const auto uses = edge_uses(mesh);
  facts.edge_count = uses.size();
  facts.manifold_edges = true;
  facts.consistently_oriented = true;
  for (const auto& item : uses) {
    const auto total = item.second.forward + item.second.backward;
    if (total > 2) facts.manifold_edges = false;
    if (total == 1) ++facts.boundary_edge_count;
    if (total == 2 && (item.second.forward != 1 || item.second.backward != 1)) {
      facts.consistently_oriented = false;
    }
  }
  facts.closed = facts.boundary_edge_count == 0;
  facts.euler_characteristic = static_cast<long long>(count) -
                               static_cast<long long>(facts.edge_count) +
                               static_cast<long long>(facts.face_count);

  // Components, unreferenced vertices.
  UnionFind components(count);
  std::vector<bool> referenced(count, false);
  for (const auto& face : mesh.faces) {
    for (std::size_t corner = 0; corner < face.size(); ++corner) {
      referenced[face[corner]] = true;
      components.unite(face[corner], face[(corner + 1) % face.size()]);
    }
  }
  std::set<std::size_t> roots;
  for (std::size_t vertex = 0; vertex < count; ++vertex) {
    if (referenced[vertex]) {
      roots.insert(components.find(vertex));
    } else {
      ++facts.unreferenced_vertex_count;
    }
  }
  facts.component_count = roots.size();

  // Boundary loops (components of the boundary-edge graph).
  UnionFind loops(count);
  std::set<std::size_t> boundary;
  for (const auto& item : uses) {
    if (item.second.forward + item.second.backward != 1) continue;
    const auto low = static_cast<std::size_t>(item.first / count);
    const auto high = static_cast<std::size_t>(item.first % count);
    loops.unite(low, high);
    boundary.insert(low);
    boundary.insert(high);
  }
  std::set<std::size_t> loop_roots;
  for (const auto vertex : boundary) loop_roots.insert(loops.find(vertex));
  facts.boundary_loop_count = loop_roots.size();

  // Vertex manifoldness: the faces around each vertex form a single fan.
  std::vector<std::vector<std::pair<std::size_t, std::size_t>>> star(count);
  for (std::size_t face = 0; face < mesh.faces.size(); ++face) {
    const auto& indices = mesh.faces[face];
    const auto size = indices.size();
    for (std::size_t corner = 0; corner < size; ++corner) {
      const auto vertex = indices[corner];
      star[vertex].push_back({indices[(corner + size - 1) % size], face});
      star[vertex].push_back({indices[(corner + 1) % size], face});
    }
  }
  facts.manifold_vertices = true;
  for (std::size_t vertex = 0; vertex < count && facts.manifold_vertices; ++vertex) {
    auto& entries = star[vertex];
    if (entries.empty()) continue;
    std::vector<std::size_t> faces;
    for (const auto& entry : entries) faces.push_back(entry.second);
    std::sort(faces.begin(), faces.end());
    faces.erase(std::unique(faces.begin(), faces.end()), faces.end());
    UnionFind fan(faces.size());
    std::sort(entries.begin(), entries.end());
    for (std::size_t index = 1; index < entries.size(); ++index) {
      if (entries[index].first == entries[index - 1].first) {
        const auto first = static_cast<std::size_t>(
            std::lower_bound(faces.begin(), faces.end(), entries[index - 1].second) - faces.begin());
        const auto second = static_cast<std::size_t>(
            std::lower_bound(faces.begin(), faces.end(), entries[index].second) - faces.begin());
        fan.unite(first, second);
      }
    }
    std::set<std::size_t> fans;
    for (std::size_t index = 0; index < faces.size(); ++index) fans.insert(fan.find(index));
    if (fans.size() != 1) facts.manifold_vertices = false;
  }

  // Metrics.
  double edge_sum = 0;
  facts.min_edge_length = std::numeric_limits<double>::infinity();
  for (const auto& item : uses) {
    const auto low = static_cast<std::size_t>(item.first / count);
    const auto high = static_cast<std::size_t>(item.first % count);
    const double length = distance(mesh.vertices[low], mesh.vertices[high]);
    edge_sum += length;
    facts.min_edge_length = std::min(facts.min_edge_length, length);
    facts.max_edge_length = std::max(facts.max_edge_length, length);
  }
  facts.mean_edge_length = uses.empty() ? 0 : edge_sum / static_cast<double>(uses.size());
  facts.min_angle_degrees = 180;
  for (std::size_t face = 0; face < mesh.faces.size(); ++face) {
    const auto& indices = mesh.faces[face];
    if (std::set<std::size_t>(indices.begin(), indices.end()).size() != indices.size()) {
      ++facts.degenerate_face_count;
      continue;
    }
    const V3 normal = face_normal(mesh, face);
    facts.area += norm(normal) / 2;
    for (std::size_t corner = 1; corner + 1 < indices.size(); ++corner) {
      const auto& a = mesh.vertices[indices[0]];
      const auto& b = mesh.vertices[indices[corner]];
      const auto& c = mesh.vertices[indices[corner + 1]];
      facts.signed_volume += dot(a, cross(b, c)) / 6.0;
    }
    if (indices.size() == 3) {
      const auto& a = mesh.vertices[indices[0]];
      const auto& b = mesh.vertices[indices[1]];
      const auto& c = mesh.vertices[indices[2]];
      if (CGAL::collinear(Point3(a[0], a[1], a[2]), Point3(b[0], b[1], b[2]),
                          Point3(c[0], c[1], c[2]))) {
        ++facts.degenerate_face_count;
        continue;
      }
      const std::array<V3, 3> corners{a, b, c};
      for (int corner = 0; corner < 3; ++corner) {
        const V3 u = sub(corners[(corner + 1) % 3], corners[corner]);
        const V3 v = sub(corners[(corner + 2) % 3], corners[corner]);
        const double cosine = std::clamp(dot(u, v) / (norm(u) * norm(v)), -1.0, 1.0);
        facts.min_angle_degrees = std::min(facts.min_angle_degrees, std::acos(cosine) * 180 / kPi);
      }
    } else if (!(norm(face_normal(mesh, face)) > 0)) {
      ++facts.degenerate_face_count;
    }
  }
  V3 lower = mesh.vertices.front();
  V3 upper = lower;
  for (const auto& point : mesh.vertices) {
    for (int axis = 0; axis < 3; ++axis) {
      lower[axis] = std::min(lower[axis], point[axis]);
      upper[axis] = std::max(upper[axis], point[axis]);
    }
  }
  facts.bbox_diagonal = distance(lower, upper);
  return facts;
}

Json facts_json(const MeshFacts& facts) {
  return Json{{"vertex_count", facts.vertex_count},
              {"face_count", facts.face_count},
              {"edge_count", facts.edge_count},
              {"boundary_edge_count", facts.boundary_edge_count},
              {"boundary_loop_count", facts.boundary_loop_count},
              {"component_count", facts.component_count},
              {"euler_characteristic", facts.euler_characteristic},
              {"closed", facts.closed},
              {"area", facts.area},
              {"signed_volume", facts.signed_volume},
              {"min_edge_length", facts.min_edge_length},
              {"max_edge_length", facts.max_edge_length},
              {"mean_edge_length", facts.mean_edge_length},
              {"min_angle_degrees", facts.min_angle_degrees}};
}

std::vector<std::array<std::size_t, 2>> boundary_edges(const RawMesh& mesh) {
  const auto count = mesh.vertices.size();
  const auto uses = edge_uses(mesh);
  std::vector<std::array<std::size_t, 2>> result;
  for (const auto& item : uses) {
    if (item.second.forward + item.second.backward == 1) {
      result.push_back({static_cast<std::size_t>(item.first / count),
                        static_cast<std::size_t>(item.first % count)});
    }
  }
  std::sort(result.begin(), result.end());
  return result;
}

std::vector<std::size_t> boundary_vertices(const RawMesh& mesh) {
  std::set<std::size_t> vertices;
  for (const auto& edge : boundary_edges(mesh)) {
    vertices.insert(edge[0]);
    vertices.insert(edge[1]);
  }
  return {vertices.begin(), vertices.end()};
}

Deviation one_sided_deviation(const RawMesh& from, const RawMesh& to, double resolution,
                              bool check_orientation) {
  if (!(resolution > 0) || !std::isfinite(resolution)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "Deviation resolution must be positive");
  }
  const auto from_triangles = fan_triangles(from, nullptr);
  const auto to_triangles = fan_triangles(to, nullptr);
  std::size_t planned = 0;
  std::vector<std::size_t> divisions;
  divisions.reserve(from_triangles.size());
  for (const auto& triangle : from_triangles) {
    const double longest = std::max({distance(triangle[0], triangle[1]),
                                     distance(triangle[1], triangle[2]),
                                     distance(triangle[2], triangle[0])});
    const auto k = static_cast<std::size_t>(
        std::clamp(std::ceil(longest / resolution), 1.0, 4096.0));
    divisions.push_back(k);
    planned += (k + 1) * (k + 2) / 2;
  }
  if (planned > kMaximumSamples) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED",
                      "Deviation sampling exceeds the Wave D validator budget");
  }
  TriangleGrid grid(to_triangles);
  Deviation result;
  for (std::size_t index = 0; index < from_triangles.size(); ++index) {
    const auto& triangle = from_triangles[index];
    const auto k = divisions[index];
    const double longest = std::max({distance(triangle[0], triangle[1]),
                                     distance(triangle[1], triangle[2]),
                                     distance(triangle[2], triangle[0])});
    const double cover = longest / static_cast<double>(k) / std::sqrt(3.0);
    double face_maximum = 0;
    const V3 u = sub(triangle[1], triangle[0]);
    const V3 v = sub(triangle[2], triangle[0]);
    for (std::size_t i = 0; i <= k; ++i) {
      for (std::size_t j = 0; i + j <= k; ++j) {
        const V3 point = add(triangle[0], add(scale(u, static_cast<double>(i) / k),
                                              scale(v, static_cast<double>(j) / k)));
        face_maximum = std::max(face_maximum, grid.nearest(point).first);
        ++result.sample_count;
      }
    }
    result.sampled_maximum = std::max(result.sampled_maximum, face_maximum);
    result.certified_upper_bound = std::max(result.certified_upper_bound, face_maximum + cover);
    if (check_orientation) {
      const V3 centroid = scale(add(triangle[0], add(triangle[1], triangle[2])), 1.0 / 3.0);
      const auto nearest = grid.nearest(centroid);
      if (dot(triangle_normal(triangle), triangle_normal(to_triangles[nearest.second])) <= 0) {
        ++result.orientation_disagreements;
        result.orientation_agrees = false;
      }
    }
  }
  return result;
}

double umbrella_roughness(const RawMesh& mesh) {
  const auto count = mesh.vertices.size();
  std::vector<std::set<std::size_t>> neighbours(count);
  for (const auto& face : mesh.faces) {
    for (std::size_t corner = 0; corner < face.size(); ++corner) {
      const auto a = face[corner];
      const auto b = face[(corner + 1) % face.size()];
      neighbours[a].insert(b);
      neighbours[b].insert(a);
    }
  }
  std::vector<bool> on_boundary(count, false);
  for (const auto vertex : boundary_vertices(mesh)) on_boundary[vertex] = true;
  double total = 0;
  for (std::size_t vertex = 0; vertex < count; ++vertex) {
    if (on_boundary[vertex] || neighbours[vertex].empty()) continue;
    V3 mean{0, 0, 0};
    for (const auto other : neighbours[vertex]) mean = add(mean, mesh.vertices[other]);
    mean = scale(mean, 1.0 / static_cast<double>(neighbours[vertex].size()));
    const V3 laplacian = sub(mean, mesh.vertices[vertex]);
    total += dot(laplacian, laplacian);
  }
  return total;
}

bool same_faces(const RawMesh& first, const RawMesh& second) {
  if (first.faces.size() != second.faces.size()) return false;
  auto canonical = [](const RawMesh& mesh) {
    std::vector<std::vector<std::size_t>> faces;
    for (auto face : mesh.faces) {
      std::rotate(face.begin(), std::min_element(face.begin(), face.end()), face.end());
      faces.push_back(std::move(face));
    }
    std::sort(faces.begin(), faces.end());
    return faces;
  };
  return canonical(first) == canonical(second);
}

bool vertices_prefix_identical(const RawMesh& source, const RawMesh& candidate) {
  if (candidate.vertices.size() < source.vertices.size()) return false;
  for (std::size_t index = 0; index < source.vertices.size(); ++index) {
    if (source.vertices[index] != candidate.vertices[index]) return false;
  }
  return true;
}

bool boundary_vertices_fixed(const RawMesh& source, const RawMesh& candidate) {
  if (candidate.vertices.size() != source.vertices.size()) return false;
  for (const auto vertex : boundary_vertices(source)) {
    if (source.vertices[vertex] != candidate.vertices[vertex]) return false;
  }
  return true;
}

bool no_self_intersections(const RawMesh& mesh) {
  // CGAL's exact-predicate self-intersection test (box_intersection_d +
  // Triangle_3 predicates); it is not any remeshing function under test.
  SurfaceMesh surface;
  std::vector<SurfaceMesh::Vertex_index> handles;
  for (const auto& point : mesh.vertices) {
    handles.push_back(surface.add_vertex(Point3(point[0], point[1], point[2])));
  }
  for (const auto& face : mesh.faces) {
    std::vector<SurfaceMesh::Vertex_index> cycle;
    for (const auto vertex : face) cycle.push_back(handles[vertex]);
    if (surface.add_face(cycle) == SurfaceMesh::null_face()) return false;
  }
  return !PMP::does_self_intersect(surface);
}

PartitionResult surface_partition(const RawMesh& source, const RawMesh& candidate, double eps) {
  std::vector<std::size_t> owner;
  const auto source_triangles = fan_triangles(source, &owner);
  TriangleGrid grid(source_triangles);
  std::vector<double> covered(source.faces.size(), 0);
  PartitionResult result;
  for (std::size_t face = 0; face < candidate.faces.size(); ++face) {
    const auto& indices = candidate.faces[face];
    if (indices.size() != 3) {
      result.every_triangle_inside_one_source_face = false;
      continue;
    }
    const Triangle triangle{candidate.vertices[indices[0]], candidate.vertices[indices[1]],
                            candidate.vertices[indices[2]]};
    const V3 centroid = scale(add(triangle[0], add(triangle[1], triangle[2])), 1.0 / 3.0);
    auto inside = [&](std::size_t index) {
      const auto& host = source_triangles[index];
      for (const auto& point : triangle) {
        if (point_triangle_distance(point, host[0], host[1], host[2]) > eps) return false;
      }
      return dot(triangle_normal(triangle), triangle_normal(host)) > 0;
    };
    std::size_t host = grid.nearest(centroid).second;
    bool found = inside(host);
    for (std::size_t index = 0; !found && index < source_triangles.size(); ++index) {
      if (inside(index)) {
        host = index;
        found = true;
      }
    }
    if (!found) {
      result.every_triangle_inside_one_source_face = false;
      continue;
    }
    covered[owner[host]] += norm(triangle_normal(triangle)) / 2;
  }
  for (std::size_t face = 0; face < source.faces.size(); ++face) {
    const double area = norm(face_normal(source, face)) / 2;
    if (!(covered[face] > 0)) result.every_source_face_covered = false;
    const double error = std::fabs(covered[face] - area) / area;
    result.maximum_relative_area_error = std::max(result.maximum_relative_area_error, error);
    if (error > 1e-9) result.per_face_area_preserved = false;
  }
  return result;
}

OperationDefinition make_definition(std::string id, std::vector<std::string> inputs,
                                    std::string output, std::string role,
                                    std::function<Json(const Request&)> execute,
                                    std::vector<std::string> dependencies, Json info) {
  OperationDefinition definition{std::move(id),   1, std::move(inputs), std::move(output),
                                 std::move(role), std::move(execute)};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel = kEpick;
  definition.dependencies = std::move(dependencies);
  definition.info = std::move(info);
  return definition;
}

std::vector<OperationDefinition> operations() {
  std::vector<OperationDefinition> result;
  for (auto& item : remesh_operations()) result.push_back(std::move(item));
  for (auto& item : remesh_validators()) result.push_back(std::move(item));
  return result;
}

}  // namespace cgal_master::wave_d
