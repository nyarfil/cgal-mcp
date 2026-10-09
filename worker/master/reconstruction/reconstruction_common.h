#pragma once
// Surface reconstruction family (7.10): strict input readers, parameter helpers
// and independent mesh/point combinatorics. This header includes no CGAL header
// so the independent validators (reconstruction_validators.cpp) can use it
// without touching the packages they check (Poisson_surface_reconstruction_3,
// Advancing_front_surface_reconstruction, Scale_space_reconstruction_3,
// Alpha_wrap_3).

#include "../operation.h"
#include "../protocol.h"

#include <array>
#include <cstddef>
#include <functional>
#include <initializer_list>
#include <string>
#include <vector>

namespace cgal_master::reconstruction_ops {

using V3 = std::array<double, 3>;

inline constexpr std::size_t kMinimumPoints = 10;
inline constexpr std::size_t kMaximumPoints = 20000;
inline constexpr std::size_t kMaximumOutputFaces = 60000;
inline constexpr const char* kEpick = "CGAL::Exact_predicates_inexact_constructions_kernel";

struct PointCloud {
  std::vector<V3> points;
  std::vector<V3> normals;  // empty unless read from PointSet3Normals
};

struct RawMesh {
  std::vector<V3> vertices;
  std::vector<std::array<std::size_t, 3>> faces;
};

// Independently derived combinatorial facts of an indexed triangle mesh.
struct Topology {
  std::size_t vertex_count = 0;
  std::size_t face_count = 0;
  std::size_t edge_count = 0;
  std::size_t boundary_edge_count = 0;
  std::size_t component_count = 0;
  std::size_t unreferenced_vertex_count = 0;
  std::size_t repeated_index_face_count = 0;
  long long euler_characteristic = 0;
  bool edge_manifold = false;
  bool vertex_manifold = false;
  bool consistently_oriented = false;
  bool closed = false;
};

// Strict readers (type/format/unit/sha256 checked; finite coordinates).
PointCloud read_points(const ArtifactInput& input);           // PointSet3 xyz
PointCloud read_points_with_normals(const ArtifactInput& input);  // PointSet3Normals ascii ply
RawMesh read_candidate_mesh(const ArtifactInput& input);     // TriangleSurfaceMesh off (own parser)

// Producer-side preconditions shared by all operations.
void require_point_budget(const PointCloud& cloud);
// Affine rank (0..3) of the point set, computed in exact rational arithmetic.
int affine_rank(const std::vector<V3>& points);

Topology analyze_topology(const RawMesh& mesh);

void require_inputs(const Request& request, std::size_t count, const std::string& operation);
void require_parameter_names(const Request& request, std::initializer_list<const char*> required,
                             std::initializer_list<const char*> optional = {});
std::size_t integer_parameter(const Request& request, const char* name, std::size_t minimum,
                              std::size_t maximum);
double number_parameter(const Request& request, const char* name, double exclusive_minimum,
                        double maximum);
double length_parameter(const Request& request, const char* name, const std::string& unit);
void require_same_unit(const ArtifactInput& first, const ArtifactInput& second);
Json finish_reconstruction_validation(const Request& request, const std::string& validator, Json report);
[[noreturn]] void precondition(const std::string& code, const std::string& message);
[[noreturn]] void validation_failure(const std::string& code, const std::string& message);

OperationDefinition reconstruction_definition(std::string id, std::vector<std::string> inputs,
                                              std::string output, std::string role,
                                              std::function<Json(const Request&)> execute,
                                              std::vector<std::string> dependencies, Json info);

std::vector<OperationDefinition> transform_operations();
std::vector<OperationDefinition> validator_operations();

}  // namespace cgal_master::reconstruction_ops
