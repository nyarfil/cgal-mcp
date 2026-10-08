#pragma once
// Wave C: typed 2D / triangulation / spatial-search adapters.
// Shared strict JSON artifact readers, writers and exact helpers.

#include "../operation.h"
#include "../protocol.h"

#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>

#include <array>
#include <cstddef>
#include <functional>
#include <initializer_list>
#include <string>
#include <vector>

namespace cgal_master::wave_c {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using Epeck = CGAL::Exact_predicates_exact_constructions_kernel;
using XY = std::array<double, 2>;
using XYZ = std::array<double, 3>;
using Index2 = std::array<std::size_t, 2>;
using Index3 = std::array<std::size_t, 3>;
using Index4 = std::array<std::size_t, 4>;

inline constexpr const char* kEpick =
    "CGAL::Exact_predicates_inexact_constructions_kernel";

// Size caps shared by producers and validators. Producers refuse inputs whose
// mandatory validation would exceed the validator budget, so no candidate is
// produced that cannot be validated.
inline constexpr std::size_t kMaximumPlanarPoints = 200000;
inline constexpr std::size_t kMaximumTetrahedra = 1000000;
inline constexpr std::size_t kMaximumSpatialPoints = 1000000;
inline constexpr std::size_t kMaximumConstraintSegments = 4000;
inline constexpr std::size_t kMaximumPolygonVertices = 5000;
inline constexpr std::size_t kMaximumBruteForcePairs = 20000000;
inline constexpr std::size_t kMaximumQueryCount = 100000;
inline constexpr std::size_t kMaximumNeighbors = 1000;

struct PolygonWithHolesData {
  std::vector<XY> outer;
  std::vector<std::vector<XY>> holes;
};

struct SegmentGraphData {
  std::vector<XY> points;
  std::vector<Index2> segments;
};

struct Triangulation2Data {
  std::vector<XY> vertices;
  std::vector<Index3> triangles;
  std::vector<Index2> constrained_edges;
};

struct Triangulation3Data {
  std::vector<XYZ> vertices;
  std::vector<Index4> tetrahedra;
};

struct TetrahedralMeshData {
  std::vector<XYZ> vertices;
  std::vector<Index4> tetrahedra;
  std::vector<std::size_t> subdomains;  // one positive cell subdomain index per tetrahedron
};

struct RayData {
  XYZ origin;
  XYZ direction;
};

struct TriangleMeshData {
  std::vector<XYZ> vertices;
  std::vector<Index3> faces;
};

// Input checks.
void require_input_count(const Request& request, std::size_t count,
                         const std::string& operation);
void require_parameters(const Request& request,
                        std::initializer_list<const char*> required,
                        std::initializer_list<const char*> optional = {});
std::size_t integer_parameter(const Request& request, const char* name,
                              std::size_t minimum, std::size_t maximum);
bool boolean_parameter(const Request& request, const char* name);
std::string enum_parameter(const Request& request, const char* name,
                           std::initializer_list<const char*> allowed);
double typed_length_parameter(const Request& request, const char* name,
                              const std::string& artifact_unit);
void require_same_unit(const ArtifactInput& first, const ArtifactInput& second);

// Strict artifact readers (type/format/unit/sha256 checked).
std::vector<XY> read_point_set2(const ArtifactInput& input);
std::vector<XY> read_polygon2(const ArtifactInput& input);
PolygonWithHolesData read_polygon_with_holes2(const ArtifactInput& input);
SegmentGraphData read_segment_graph2(const ArtifactInput& input);
Triangulation2Data read_triangulation2(const ArtifactInput& input);
Triangulation3Data read_triangulation3(const ArtifactInput& input);
TetrahedralMeshData read_tetrahedral_mesh(const ArtifactInput& input);
std::vector<XYZ> read_point_set3(const ArtifactInput& input);
std::vector<RayData> read_ray_batch3(const ArtifactInput& input);
TriangleMeshData read_triangle_mesh(const ArtifactInput& input);
Json read_report(const ArtifactInput& input, const std::string& type,
                 const std::string& kind_key, const std::string& kind);

// Outputs.
Json write_json_output(const Request& request, const std::string& slot,
                       const std::string& type, const std::string& unit,
                       const Json& value);
Json finish_validation(const Request& request, const std::string& validator,
                       Json report);
[[noreturn]] void fail_validation(const std::string& code,
                                  const std::string& message);

// Exact helpers.
std::string exact_string(const Epeck::FT& value);
Json exact_metric(const Epeck::FT& value, const std::string& unit);
Json xy_json(const XY& point);
Json xyz_json(const XYZ& point);
bool same_double(double first, double second);

OperationDefinition make_definition(
    std::string id, std::vector<std::string> inputs, std::string output,
    std::string role, std::function<Json(const Request&)> execute,
    std::vector<std::string> dependencies, Json info);

std::vector<OperationDefinition> planar_operations();
std::vector<OperationDefinition> triangulation_operations();
std::vector<OperationDefinition> spatial_operations();

}  // namespace cgal_master::wave_c
