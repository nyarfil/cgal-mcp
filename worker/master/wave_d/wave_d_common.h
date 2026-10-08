#pragma once
// Wave D: PMP meshing / remeshing adapters (family 7.6) and their independent
// validators. Producers wrap official CGAL Polygon_mesh_processing functions;
// validators re-derive every accepted property from raw OFF data with their
// own parser, combinatorics and a certified sampled Hausdorff bound. Validators
// never call the remeshing/refinement/smoothing/triangulation function under
// test.

#include "../operation.h"
#include "../protocol.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>

#include <array>
#include <cstddef>
#include <initializer_list>
#include <string>
#include <vector>

namespace cgal_master::wave_d {

using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using Point3 = Epick::Point_3;
using SurfaceMesh = CGAL::Surface_mesh<Point3>;
using V3 = std::array<double, 3>;

inline constexpr const char* kEpick =
    "CGAL::Exact_predicates_inexact_constructions_kernel";

// Producers refuse inputs/outputs whose mandatory validation would exceed the
// validator budget, so no candidate is produced that cannot be validated.
inline constexpr std::size_t kMaximumInputFaces = 20000;
inline constexpr std::size_t kMaximumOutputFaces = 60000;
inline constexpr std::size_t kMaximumFaceDegree = 64;
inline constexpr std::size_t kMaximumSamples = 3000000;
inline constexpr std::size_t kMaximumIterations = 50;

// Raw indexed mesh as written in an OFF file (independent of CGAL).
struct RawMesh {
  std::vector<V3> vertices;
  std::vector<std::vector<std::size_t>> faces;
};

// Independently derived combinatorial and metric facts.
struct MeshFacts {
  std::size_t vertex_count = 0;
  std::size_t face_count = 0;
  std::size_t edge_count = 0;
  std::size_t boundary_edge_count = 0;
  std::size_t boundary_loop_count = 0;
  std::size_t component_count = 0;
  std::size_t unreferenced_vertex_count = 0;
  std::size_t degenerate_face_count = 0;
  long long euler_characteristic = 0;
  bool all_triangles = false;
  bool manifold_edges = false;
  bool manifold_vertices = false;
  bool consistently_oriented = false;
  bool closed = false;
  double area = 0;
  double signed_volume = 0;
  double min_edge_length = 0;
  double max_edge_length = 0;
  double mean_edge_length = 0;
  double min_angle_degrees = 0;
  double bbox_diagonal = 0;
};

struct Deviation {
  double sampled_maximum = 0;
  double certified_upper_bound = 0;
  std::size_t sample_count = 0;
  bool orientation_agrees = true;
  std::size_t orientation_disagreements = 0;
  std::vector<double> face_sampled_maxima;  // sampled per-triangle maximum, in fan triangle order
};

// ---- Producer side (CGAL Surface_mesh) -------------------------------------
void require_kernel(const Request& request);
SurfaceMesh read_producer_mesh(const ArtifactInput& input,
                               std::initializer_list<const char*> accepted_types,
                               bool require_triangles);
void require_output_budget(const SurfaceMesh& mesh, const std::string& operation);
Json write_mesh_candidate(const Request& request, SurfaceMesh& mesh,
                          const std::string& unit);
double number_parameter(const Request& request, const char* name, double exclusive_minimum,
                        double maximum);

// ---- Validator side (independent) -------------------------------------------
RawMesh read_raw_mesh(const ArtifactInput& input,
                      std::initializer_list<const char*> accepted_types);
MeshFacts analyze(const RawMesh& mesh);
Json facts_json(const MeshFacts& facts);
std::vector<std::array<std::size_t, 2>> boundary_edges(const RawMesh& mesh);
std::vector<std::size_t> boundary_vertices(const RawMesh& mesh);
// Two-sided certified sampled Hausdorff estimate between triangle meshes.
// resolution bounds the sub-triangle edge length of the sampling lattice.
Deviation one_sided_deviation(const RawMesh& from, const RawMesh& to, double resolution,
                              bool check_orientation);
double point_triangle_distance(const V3& p, const V3& a, const V3& b, const V3& c);
double point_segment_distance(const V3& p, const V3& a, const V3& b);
double distance(const V3& a, const V3& b);
V3 face_normal(const RawMesh& mesh, std::size_t face);
// Sum of squared umbrella-Laplacian lengths over interior vertices.
double umbrella_roughness(const RawMesh& mesh);
bool same_faces(const RawMesh& first, const RawMesh& second);
bool vertices_prefix_identical(const RawMesh& source, const RawMesh& candidate);
bool boundary_vertices_fixed(const RawMesh& source, const RawMesh& candidate);
bool no_self_intersections(const RawMesh& mesh);
// Every candidate triangle lies in one source face (vertices within eps of it),
// and per source face the candidate area equals the source area.
struct PartitionResult {
  bool every_triangle_inside_one_source_face = true;
  bool per_face_area_preserved = true;
  bool every_source_face_covered = true;
  double maximum_relative_area_error = 0;
};
PartitionResult surface_partition(const RawMesh& source, const RawMesh& candidate, double eps);

OperationDefinition make_definition(std::string id, std::vector<std::string> inputs,
                                    std::string output, std::string role,
                                    std::function<Json(const Request&)> execute,
                                    std::vector<std::string> dependencies, Json info);

std::vector<OperationDefinition> remesh_operations();
std::vector<OperationDefinition> remesh_validators();

}  // namespace cgal_master::wave_d
