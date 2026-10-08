// Wave E (family 7.14, requirement 7.14.03) tetrahedral volume mesh generation with CGAL Mesh_3
// make_mesh_3 and an independent validator. Two domain kinds are supported:
//   * a FIXED ENUMERATED set of typed implicit domains (sphere, ellipsoid, torus; the same
//     ImplicitSurfaceDomain artifact as the surface mesher; no free-form expressions or generated
//     code), meshed through Labeled_mesh_domain_3; and
//   * a closed, oriented, intersection-free TriangleSurfaceMesh (a polyhedral domain), meshed
//     through Polyhedral_mesh_domain_3 WITHOUT sharp-feature protection (feature edges and corners
//     are approximated within the facet criteria, not preserved).
// Image domains, polyhedral features, perturbation and exudation are not supported.
//
// The validator never calls Mesh_3. It runs the shared tetrahedral analysis (exact orientation,
// face adjacency, closed single boundary, 3-manifold vertex links, cell-versus-boundary volume
// agreement), then recomputes against the domain specification alone.
//   Implicit domains: every vertex inside the domain, boundary vertices on the analytic surface,
//   outward boundary orientation, boundary and solid Euler characteristics, facet and cell criteria,
//   analytic volume and area.
//   Polyhedral domains: the source mesh is re-validated from raw OFF (closed, manifold, oriented
//   outward, single component, no self-intersection), boundary vertices lie on the source triangles,
//   a two-sided sampled Hausdorff comparison between the boundary facets and the source triangles,
//   boundary orientation against the nearest source triangle (at most 5% of facets may disagree), facet and cell criteria, the Euler
//   characteristics, and the cell volume against the source's divergence-theorem volume within a
//   bound derived from the measured Hausdorff distance and the source area.
// The cell volume sum equals the boundary divergence volume and every interior face is shared by two
// opposite-facing cells, so the cells cover the region bounded by the boundary exactly once; the
// boundary-versus-domain relation (surface distance, orientation, area and volume) then excludes
// a boundary that merely encloses a different region. A hidden overlap that preserves the boundary
// and the volume sum is excluded only by the face-adjacency analysis, not by an independent
// point-location test.
#include "wave_e_operations.h"

#include "../artifact_io.h"
#include "../wave_c/wave_c_common.h"
#include "../wave_d/wave_d_common.h"
#include "implicit_domain.h"
#include "tet_analysis.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Labeled_mesh_domain_3.h>
#include <CGAL/Mesh_complex_3_in_triangulation_3.h>
#include <CGAL/Mesh_criteria_3.h>
#include <CGAL/Mesh_triangulation_3.h>
#include <CGAL/Polyhedral_mesh_domain_3.h>
#include <CGAL/Random.h>
#include <CGAL/make_mesh_3.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace cgal_master::wave_e {
namespace {

using wave_c::fail_validation;
using wave_c::finish_validation;
using wave_c::require_input_count;
using wave_c::require_parameters;
using wave_c::require_same_unit;
using wave_c::typed_length_parameter;
using wave_d::V3;
using wave_d::kMaximumInputFaces;
using namespace implicit;

constexpr double kMaximumFacetAngle = 30.0;       // Mesh_3 facet criterion termination guarantee
constexpr double kMinimumProducerRadiusEdge = 2.0;  // Mesh_3 cell criterion termination guarantee
constexpr double kMaximumRadiusEdge = 100.0;
constexpr double kMaximumValidatorAngle = 60.0;
constexpr double kMinimumValidatorRadiusEdge = 0.6123;  // regular tetrahedron: sqrt(6) / 4
constexpr double kMaximumDistanceRatio = 0.1;       // facet_distance / smallest curvature radius
constexpr double kOracleErrorBound = 1e-8;          // relative to the bounding box diagonal
constexpr double kVertexTolerance = 2e-6;           // relative to the domain extent
constexpr double kInsideTolerance = 1e-6;           // relative implicit value
constexpr std::size_t kMaximumEstimatedCells = 50000;
constexpr std::size_t kMaximumOutputCells = 100000;
constexpr double kPolyhedralDistanceFactor = 10.0;  // facet radius scale used by the budget estimate
constexpr double kSampleDivisions = 4.0;            // lattice divisions per facet size in the validator
constexpr double kOrientationDisagreementFraction = 0.05;  // tolerated facets at sharp source corners
constexpr double kReverseHausdorffFactor = 2.0;     // source-to-boundary bound, in facet sizes

double positive_length(const Request& request, const char* name, const std::string& unit) {
  const double value = typed_length_parameter(request, name, unit);
  if (!(value > 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be positive");
  }
  return value;
}

// Normalised implicit value: negative inside, zero on the surface, positive outside.
double implicit_value(const Domain& d, const V3& p) {
  switch (d.kind) {
    case Kind::Sphere: return norm(p) / d.a - 1.0;
    case Kind::Ellipsoid:
      return std::sqrt(p[0] * p[0] / (d.a * d.a) + p[1] * p[1] / (d.b * d.b) +
                       p[2] * p[2] / (d.c * d.c)) - 1.0;
    case Kind::Torus: return std::hypot(std::hypot(p[0], p[1]) - d.a, p[2]) / d.b - 1.0;
  }
  return 1.0;
}

// ---------------------------------------------------------------------------
// Producer: CGAL Mesh_3 make_mesh_3
// ---------------------------------------------------------------------------

using K = CGAL::Exact_predicates_inexact_constructions_kernel;
using MeshDomain = CGAL::Labeled_mesh_domain_3<K>;
using Tr = CGAL::Mesh_triangulation_3<MeshDomain, CGAL::Default, CGAL::Sequential_tag>::type;
using C3t3 = CGAL::Mesh_complex_3_in_triangulation_3<Tr>;
using MeshCriteria = CGAL::Mesh_criteria_3<Tr>;

// A closed set of implicit functions, negative inside / positive outside the surface.
struct ImplicitFunction {
  Domain domain;
  K::FT operator()(const K::Point_3& p) const {
    const double x = CGAL::to_double(p.x()), y = CGAL::to_double(p.y()), z = CGAL::to_double(p.z());
    switch (domain.kind) {
      case Kind::Sphere: return (x * x + y * y + z * z) / (domain.a * domain.a) - 1.0;
      case Kind::Ellipsoid:
        return x * x / (domain.a * domain.a) + y * y / (domain.b * domain.b) +
               z * z / (domain.c * domain.c) - 1.0;
      case Kind::Torus: {
        const double rho = std::sqrt(x * x + y * y) - domain.a;
        return (rho * rho + z * z) / (domain.b * domain.b) - 1.0;
      }
    }
    return 1.0;
  }
};

double estimated_facets(const Domain& d, double size, double distance) {
  const double radius = std::min(size, std::sqrt(2.0 * d.min_curvature_radius() * distance));
  const double area = d.kind == Kind::Ellipsoid
      ? 4.0 * kPi * std::pow((std::pow(d.a * d.b, 1.6075) + std::pow(d.a * d.c, 1.6075) +
                              std::pow(d.b * d.c, 1.6075)) / 3.0, 1.0 / 1.6075)
      : analytic_area(d);
  return area / (0.65 * radius * radius);
}

// Deliberately generous: a regular tetrahedron of circumradius s has volume 0.513 s^3 and refined
// Delaunay meshes are far less efficient.
double estimated_cells(const Domain& d, double cell_size) {
  return analytic_volume(d) / (0.05 * cell_size * cell_size * cell_size);
}

struct Extracted {
  std::vector<V3> vertices;
  std::vector<std::array<std::size_t, 4>> tetrahedra;
  std::size_t boundary_facets = 0;
};

// Canonical vertex order, canonical cell order and a fixed orientation sign.
template <class C3>
Extracted extract_complex(C3& c3t3) {
  const bool reference_positive =
      CGAL::orientation(K::Point_3(0, 0, 0), K::Point_3(1, 0, 0), K::Point_3(0, 1, 0),
                        K::Point_3(0, 0, 1)) == CGAL::POSITIVE;
  Extracted result;
  std::vector<std::array<V3, 4>> cells;
  std::size_t& boundary_facets = result.boundary_facets;
  for (auto cell = c3t3.cells_in_complex_begin(); cell != c3t3.cells_in_complex_end(); ++cell) {
    std::array<V3, 4> corners;
    for (int k = 0; k < 4; ++k) {
      const auto& point = cell->vertex(k)->point().point();
      corners[k] = {CGAL::to_double(point.x()), CGAL::to_double(point.y()), CGAL::to_double(point.z())};
    }
    cells.push_back(corners);
    for (int k = 0; k < 4; ++k) {
      if (c3t3.is_in_complex(cell, k)) ++boundary_facets;
    }
  }
  if (cells.empty()) throw WorkerError("INTERNAL", "EMPTY_OUTPUT", "Mesh_3 produced no cells");
  if (cells.size() > kMaximumOutputCells) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "Mesh_3 output exceeds the bounded validation budget");
  }
  // Canonical vertex order, canonical cell order and orientation.
  std::map<V3, std::size_t> index;
  for (const auto& cell : cells) {
    for (const auto& corner : cell) index.emplace(corner, 0);
  }
  std::size_t next = 0;
  std::vector<V3>& vertices = result.vertices;
  for (auto& entry : index) {
    entry.second = next++;
    vertices.push_back(entry.first);
  }
  std::vector<std::array<std::size_t, 4>>& tetrahedra = result.tetrahedra;
  for (const auto& cell : cells) {
    std::array<std::size_t, 4> t{index.at(cell[0]), index.at(cell[1]), index.at(cell[2]),
                                 index.at(cell[3])};
    std::sort(t.begin(), t.end());
    auto point = [&](std::size_t i) {
      return K::Point_3(vertices[i][0], vertices[i][1], vertices[i][2]);
    };
    const auto orientation = CGAL::orientation(point(t[0]), point(t[1]), point(t[2]), point(t[3]));
    if (orientation == CGAL::COPLANAR) {
      throw WorkerError("INTERNAL", "DEGENERATE_OUTPUT", "Mesh_3 produced a degenerate cell");
    }
    if ((orientation == CGAL::POSITIVE) != reference_positive) std::swap(t[2], t[3]);
    tetrahedra.push_back(t);
  }
  std::sort(tetrahedra.begin(), tetrahedra.end());

  return result;
}

Json emit_volume_mesh(const Request& request, const std::string& unit, Extracted& extracted, Json metrics) {
  const auto& vertices = extracted.vertices;
  const auto& tetrahedra = extracted.tetrahedra;
  Json vertex_array = Json::array();
  for (const auto& v : vertices) vertex_array.push_back(wave_c::xyz_json({v[0], v[1], v[2]}));
  Json cell_array = Json::array(), subdomain_array = Json::array();
  for (const auto& t : tetrahedra) {
    cell_array.push_back(Json::array({t[0], t[1], t[2], t[3]}));
    subdomain_array.push_back(1);
  }
  auto output = wave_c::write_json_output(
      request, "geometry", "TetrahedralMesh", unit,
      Json{{"vertices", vertex_array}, {"tetrahedra", cell_array}, {"subdomains", subdomain_array}});
  metrics["vertex_count"] = vertices.size();
  metrics["tetrahedron_count"] = tetrahedra.size();
  metrics["boundary_facet_count"] = extracted.boundary_facets;
  metrics["perturbation"] = false;
  metrics["exudation"] = false;
  metrics["effective_kernel"] = wave_c::kEpick;
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json generate_implicit(const Request& request) {
  require_parameters(request, {"facet_angle", "facet_size", "facet_distance",
                               "cell_radius_edge_ratio", "cell_size"});
  const auto& source = request.inputs[0];
  const Domain domain = read_domain(source);
  const double facet_angle = wave_d::number_parameter(request, "facet_angle", 0.0, kMaximumFacetAngle);
  const double facet_size = positive_length(request, "facet_size", source.unit);
  const double facet_distance = positive_length(request, "facet_distance", source.unit);
  const double radius_edge =
      wave_d::number_parameter(request, "cell_radius_edge_ratio", 0.0, kMaximumRadiusEdge);
  if (radius_edge < kMinimumProducerRadiusEdge) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "cell_radius_edge_ratio must be at least 2 (Mesh_3 termination guarantee)");
  }
  const double cell_size = positive_length(request, "cell_size", source.unit);
  if (facet_distance > kMaximumDistanceRatio * domain.min_curvature_radius()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "facet_distance must not exceed 0.1 times the smallest curvature radius of the "
                      "domain (coarser meshes cannot be validated against analytic area and volume)");
  }
  if (!(estimated_facets(domain, facet_size, facet_distance) <= 30000.0) ||
      !(estimated_cells(domain, cell_size) <= static_cast<double>(kMaximumEstimatedCells))) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "facet and cell criteria are too small for bounded validation");
  }
  // Deterministic initial points.
  CGAL::get_default_random() = CGAL::Random(0);

  ImplicitFunction function{domain};
  const double bound = 1.25 * domain.extent();
  MeshDomain mesh_domain = MeshDomain::create_implicit_mesh_domain(
      function, K::Sphere_3(CGAL::ORIGIN, K::FT(bound * bound)),
      CGAL::parameters::relative_error_bound(kOracleErrorBound));
  MeshCriteria criteria(CGAL::parameters::facet_angle(facet_angle)
                            .facet_size(facet_size)
                            .facet_distance(facet_distance)
                            .cell_radius_edge_ratio(radius_edge)
                            .cell_size(cell_size));
  C3t3 c3t3 = CGAL::make_mesh_3<C3t3>(mesh_domain, criteria, CGAL::parameters::no_perturb().no_exude());

  Extracted extracted = extract_complex(c3t3);
  Json metrics = {{"algorithm", "CGAL::make_mesh_3"},
                  {"criteria", "CGAL::Mesh_criteria_3"},
                  {"domain", "CGAL::Labeled_mesh_domain_3"},
                  {"domain_kind", domain.name()},
                  {"facet_angle", facet_angle},
                  {"facet_size", facet_size},
                  {"facet_distance", facet_distance},
                  {"cell_radius_edge_ratio", radius_edge},
                  {"cell_size", cell_size}};
  return emit_volume_mesh(request, source.unit, extracted, std::move(metrics));
}

// ---------------------------------------------------------------------------
// Polyhedral domain (closed TriangleSurfaceMesh) producer
// ---------------------------------------------------------------------------

using PolyMesh = wave_d::SurfaceMesh;
using PolyDomain = CGAL::Polyhedral_mesh_domain_3<PolyMesh, K>;
using PolyTr = CGAL::Mesh_triangulation_3<PolyDomain, CGAL::Default, CGAL::Sequential_tag>::type;
using PolyC3t3 = CGAL::Mesh_complex_3_in_triangulation_3<PolyTr>;
using PolyCriteria = CGAL::Mesh_criteria_3<PolyTr>;

struct SourceProblem {
  const char* code;
  const char* message;
};

// The one definition of an acceptable polyhedral source, used by the producer (as a precondition)
// and by the validator (as a recomputed check): a closed, consistently oriented, outward oriented,
// single-component, edge- and vertex-manifold triangle mesh without degenerate faces or
// self-intersections.
std::optional<SourceProblem> source_problem(const wave_d::RawMesh& raw, const wave_d::MeshFacts& facts) {
  if (!facts.all_triangles) return SourceProblem{"MESH_NOT_TRIANGULATED", "The source mesh must be triangulated"};
  if (facts.degenerate_face_count != 0) return SourceProblem{"DEGENERATE_FACE", "The source mesh has a degenerate face"};
  if (facts.unreferenced_vertex_count != 0) return SourceProblem{"ISOLATED_VERTEX", "The source mesh has an unused vertex"};
  if (!facts.manifold_edges || !facts.manifold_vertices) {
    return SourceProblem{"NON_MANIFOLD_INPUT", "The source mesh is not an edge- and vertex-manifold surface"};
  }
  if (!facts.closed) return SourceProblem{"MESH_NOT_CLOSED", "The source mesh is not closed (it has boundary edges)"};
  if (!facts.consistently_oriented) {
    return SourceProblem{"INCONSISTENT_ORIENTATION", "The source mesh faces are not consistently oriented"};
  }
  if (facts.component_count != 1) {
    return SourceProblem{"MULTIPLE_COMPONENTS", "The source mesh must be a single connected closed surface"};
  }
  if (!(facts.signed_volume > 0)) {
    return SourceProblem{"INWARD_ORIENTED_INPUT", "The source mesh is oriented inward (non-positive signed volume)"};
  }
  if (!wave_d::no_self_intersections(raw)) {
    return SourceProblem{"SELF_INTERSECTING_INPUT", "The source mesh intersects itself"};
  }
  return std::nullopt;
}

double bounding_diagonal(const wave_d::RawMesh& raw) {
  V3 low{1e300, 1e300, 1e300}, high{-1e300, -1e300, -1e300};
  for (const auto& v : raw.vertices) {
    for (int axis = 0; axis < 3; ++axis) {
      low[axis] = std::min(low[axis], v[axis]);
      high[axis] = std::max(high[axis], v[axis]);
    }
  }
  return norm(sub(high, low));
}

// Number of samples the validator's two-sided comparison draws from the source triangles; the
// producer refuses requests whose output could not be validated within the validator budget.
std::size_t planned_samples(const wave_d::RawMesh& raw, double resolution) {
  std::size_t planned = 0;
  for (const auto& face : raw.faces) {
    double longest = 0;
    for (std::size_t i = 0; i < face.size(); ++i) {
      longest = std::max(longest, wave_d::distance(raw.vertices[face[i]], raw.vertices[face[(i + 1) % face.size()]]));
    }
    const auto k = static_cast<std::size_t>(std::clamp(std::ceil(longest / resolution), 1.0, 4096.0));
    planned += (k + 1) * (k + 2) / 2;
  }
  return planned;
}

Json generate_polyhedral(const Request& request) {
  require_parameters(request, {"facet_angle", "facet_size", "facet_distance",
                               "cell_radius_edge_ratio", "cell_size"});
  const auto& source = request.inputs[0];
  const double facet_angle = wave_d::number_parameter(request, "facet_angle", 0.0, kMaximumFacetAngle);
  const double facet_size = positive_length(request, "facet_size", source.unit);
  const double facet_distance = positive_length(request, "facet_distance", source.unit);
  const double radius_edge =
      wave_d::number_parameter(request, "cell_radius_edge_ratio", 0.0, kMaximumRadiusEdge);
  if (radius_edge < kMinimumProducerRadiusEdge) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "cell_radius_edge_ratio must be at least 2 (Mesh_3 termination guarantee)");
  }
  const double cell_size = positive_length(request, "cell_size", source.unit);

  const auto raw = wave_d::read_raw_mesh(source, {"TriangleSurfaceMesh"});
  if (raw.faces.size() > kMaximumInputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "The source mesh exceeds the input face limit");
  }
  const auto facts = wave_d::analyze(raw);
  if (const auto problem = source_problem(raw, facts)) {
    throw WorkerError("PRECONDITION_FAILED", problem->code, problem->message);
  }
  const double facet_radius = std::min(facet_size, kPolyhedralDistanceFactor * facet_distance);
  if (!(facts.area / (0.65 * facet_radius * facet_radius) <= 30000.0) ||
      !(facts.signed_volume / (0.05 * cell_size * cell_size * cell_size) <=
        static_cast<double>(kMaximumEstimatedCells)) ||
      planned_samples(raw, facet_size / kSampleDivisions) > wave_d::kMaximumSamples) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "facet and cell criteria are too small for bounded validation");
  }

  PolyMesh mesh = wave_d::read_producer_mesh(source, {"TriangleSurfaceMesh"}, true);
  CGAL::get_default_random() = CGAL::Random(0);  // deterministic initial points
  PolyDomain domain(mesh);
  PolyCriteria criteria(CGAL::parameters::facet_angle(facet_angle)
                            .facet_size(facet_size)
                            .facet_distance(facet_distance)
                            .cell_radius_edge_ratio(radius_edge)
                            .cell_size(cell_size));
  PolyC3t3 c3t3 = CGAL::make_mesh_3<PolyC3t3>(domain, criteria, CGAL::parameters::no_perturb().no_exude());
  Extracted extracted = extract_complex(c3t3);
  Json metrics = {{"algorithm", "CGAL::make_mesh_3"},
                  {"criteria", "CGAL::Mesh_criteria_3"},
                  {"domain", "CGAL::Polyhedral_mesh_domain_3"},
                  {"domain_kind", "polyhedral"},
                  {"feature_protection", false},
                  {"source_vertex_count", raw.vertices.size()},
                  {"source_face_count", raw.faces.size()},
                  {"source_area", facts.area},
                  {"source_volume", facts.signed_volume},
                  {"facet_angle", facet_angle},
                  {"facet_size", facet_size},
                  {"facet_distance", facet_distance},
                  {"cell_radius_edge_ratio", radius_edge},
                  {"cell_size", cell_size}};
  return emit_volume_mesh(request, source.unit, extracted, std::move(metrics));
}

Json run_generate(const Request& request) {
  require_input_count(request, 1, "mesh.volume.generate");
  if (request.inputs[0].type == "TriangleSurfaceMesh") return generate_polyhedral(request);
  return generate_implicit(request);
}

// ---------------------------------------------------------------------------
// Validator (independent)
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Polyhedral domain validator (independent)
// ---------------------------------------------------------------------------

// Points as degenerate triangles, so the validator's own grid search measures point distances.
wave_d::RawMesh point_cloud(const std::vector<V3>& points) {
  wave_d::RawMesh cloud;
  cloud.vertices = points;
  for (std::size_t i = 0; i < points.size(); ++i) cloud.faces.push_back({i, i, i});
  return cloud;
}

Json validate_polyhedral(const Request& request, double facet_angle, double facet_size,
                         double facet_distance, double radius_edge, double cell_size,
                         const std::string& unit) {
  const auto& source_input = request.inputs[1];
  const auto raw = wave_d::read_raw_mesh(source_input, {"TriangleSurfaceMesh"});
  if (raw.faces.size() > kMaximumInputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "The source mesh exceeds the input face limit");
  }
  const auto facts = wave_d::analyze(raw);
  if (const auto problem = source_problem(raw, facts)) {
    fail_validation(std::string("SOURCE_") + problem->code, problem->message);
  }
  const auto mesh = wave_c::read_tetrahedral_mesh(request.inputs[0]);
  const double diagonal = bounding_diagonal(raw);
  const double vertex_tolerance = kVertexTolerance * diagonal;

  const TetAnalysis analysis = analyze_tetrahedral_mesh(mesh);
  const auto& vertices = mesh.vertices;
  for (const auto label : mesh.subdomains) {
    if (label != 1) {
      fail_validation("SUBDOMAIN_INDEX_INVALID",
                      "The domain has one region; every cell must carry subdomain index 1");
    }
  }
  if (analysis.boundary_euler != facts.euler_characteristic) {
    fail_validation("EULER_CHARACTERISTIC_MISMATCH",
                    "The boundary V - E + F differs from the Euler characteristic of the source surface");
  }
  if (analysis.euler != facts.euler_characteristic / 2) {
    fail_validation("EULER_CHARACTERISTIC_MISMATCH",
                    "The solid's Euler characteristic differs from half that of the source surface");
  }
  if (planned_samples(raw, facet_size / kSampleDivisions) > wave_d::kMaximumSamples) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED",
                      "Source sampling exceeds the validator budget");
  }

  // Boundary facets as an indexed triangle soup over the tetrahedral vertices.
  std::vector<V3> points;
  points.reserve(vertices.size());
  for (const auto& v : vertices) points.push_back({v[0], v[1], v[2]});
  wave_d::RawMesh boundary;
  boundary.vertices = points;
  std::set<std::size_t> boundary_vertex_set;
  for (const auto& f : analysis.boundary_faces) {
    boundary.faces.push_back({f[0], f[1], f[2]});
    boundary_vertex_set.insert(f.begin(), f.end());
  }

  // Boundary vertices lie on the source triangles.
  std::vector<V3> boundary_points;
  for (const auto index : boundary_vertex_set) boundary_points.push_back(points[index]);
  const double kNoSubdivision = 1e30;
  const auto vertex_deviation =
      wave_d::one_sided_deviation(point_cloud(boundary_points), raw, kNoSubdivision, false).sampled_maximum;
  if (!(vertex_deviation <= vertex_tolerance)) {
    fail_validation("VERTEX_OFF_SURFACE", "A boundary vertex does not lie on the source surface");
  }

  // Boundary facets: orientation against the nearest source triangle and the forward Hausdorff bound.
  const auto forward = wave_d::one_sided_deviation(boundary, raw, facet_size / kSampleDivisions, true);
  // A facet that cuts a sharp corner of the source can legitimately tilt past 90 degrees from the
  // nearest source triangle, so a small fraction of disagreeing facets is tolerated. Reversing the
  // boundary (or meshing the complement) flips essentially all of them.
  const double orientation_disagreement =
      static_cast<double>(forward.orientation_disagreements) / static_cast<double>(boundary.faces.size());
  if (!(orientation_disagreement <= kOrientationDisagreementFraction)) {
    fail_validation("ORIENTATION_NOT_OUTWARD",
                    "Boundary facet normals oppose the nearest source triangle normals");
  }
  if (forward.sampled_maximum > facet_size * (1.0 + 1e-9) + vertex_tolerance) {
    fail_validation("HAUSDORFF_BOUND_EXCEEDED",
                    "A boundary facet point is farther than facet_size from the source surface");
  }

  double minimum_facet_angle = 180.0, maximum_facet_circumradius = 0.0;
  long double boundary_area = 0.0L;
  std::vector<V3> centres;
  for (const auto& face : analysis.boundary_faces) {
    const V3 a = points[face[0]], b = points[face[1]], c = points[face[2]];
    boundary_area += 0.5 * norm(cross(sub(b, a), sub(c, a)));
    const double sides[3] = {norm(sub(b, c)), norm(sub(c, a)), norm(sub(a, b))};
    for (int i = 0; i < 3; ++i) {
      const double s1 = sides[(i + 1) % 3], s2 = sides[(i + 2) % 3];
      const double cosine =
          std::max(-1.0, std::min(1.0, (s1 * s1 + s2 * s2 - sides[i] * sides[i]) / (2.0 * s1 * s2)));
      minimum_facet_angle = std::min(minimum_facet_angle, std::acos(cosine) * 180.0 / kPi);
    }
    double radius = 0;
    centres.push_back(circumcentre(a, b, c, &radius));
    maximum_facet_circumradius = std::max(maximum_facet_circumradius, radius);
  }
  const double maximum_centre_distance =
      wave_d::one_sided_deviation(point_cloud(centres), raw, kNoSubdivision, false).sampled_maximum;
  if (minimum_facet_angle < facet_angle - 1e-6) {
    fail_validation("FACET_ANGLE_VIOLATED", "A boundary facet angle is below facet_angle");
  }
  if (maximum_facet_circumradius > facet_size * (1.0 + 1e-9) + vertex_tolerance) {
    fail_validation("FACET_SIZE_VIOLATED", "A boundary facet circumradius exceeds facet_size");
  }
  if (maximum_centre_distance > facet_distance * (1.0 + 1e-9) + vertex_tolerance) {
    fail_validation("FACET_DISTANCE_VIOLATED",
                    "A boundary facet circumcentre is farther than facet_distance from the source surface");
  }

  // Reverse direction: every part of the source surface is covered by boundary facets.
  const auto reverse = wave_d::one_sided_deviation(raw, boundary, facet_size / kSampleDivisions, false);
  if (reverse.sampled_maximum > kReverseHausdorffFactor * facet_size * (1.0 + 1e-9) + vertex_tolerance) {
    fail_validation("COVERAGE_BOUND_EXCEEDED",
                    "A source surface point is farther than twice facet_size from the boundary facets");
  }

  // Cell criteria.
  if (analysis.maximum_circumradius > cell_size * (1.0 + 1e-9)) {
    fail_validation("CELL_SIZE_VIOLATED", "A tetrahedron circumradius exceeds cell_size");
  }
  if (analysis.maximum_radius_edge > radius_edge * (1.0 + 1e-9)) {
    fail_validation("RADIUS_EDGE_VIOLATED", "A tetrahedron radius-edge ratio exceeds cell_radius_edge_ratio");
  }

  // Volume against the divergence-theorem volume of the source. The region between the boundary
  // and the source surface lies within the measured Hausdorff distance of the source, so the
  // volume difference is at most the source area times that distance.
  const double hausdorff = std::max(forward.sampled_maximum, reverse.sampled_maximum) + vertex_tolerance;
  const double expected_volume = facts.signed_volume;
  const double total_volume = static_cast<double>(analysis.volume_sum);
  const double volume_error = std::fabs(total_volume - expected_volume) / expected_volume;
  const double volume_tolerance = std::min(facts.area * hausdorff / expected_volume, 0.5) + 1e-6;
  if (volume_error > volume_tolerance) {
    fail_validation("VOLUME_MISMATCH", "Total cell volume differs from the source's enclosed volume");
  }

  Json subdomains = Json::object();
  for (const auto& entry : analysis.subdomain_volume) {
    subdomains[std::to_string(entry.first)] = {
        {"cell_count", analysis.subdomain_cells.at(entry.first)}, {"volume", static_cast<double>(entry.second)}};
  }
  Json report = {
      {"checks",
       {{"source_domain_valid", true},
        {"tetrahedral_mesh_valid", true},
        {"single_region_subdomain", true},
        {"boundary_euler_characteristic_matches_domain", true},
        {"solid_euler_characteristic_matches_domain", true},
        {"boundary_vertices_on_domain_surface", true},
        {"outward_boundary_orientation", true},
        {"facet_angle_criterion_satisfied", true},
        {"facet_size_criterion_satisfied", true},
        {"facet_distance_criterion_satisfied", true},
        {"hausdorff_bound_satisfied", true},
        {"source_coverage_bound_satisfied", true},
        {"cell_size_criterion_satisfied", true},
        {"cell_radius_edge_criterion_satisfied", true},
        {"volume_matches_domain", true}}},
      {"domain_kind", "polyhedral"},
      {"source_vertex_count", raw.vertices.size()},
      {"source_face_count", raw.faces.size()},
      {"vertex_count", analysis.vertex_count},
      {"tetrahedron_count", analysis.cell_count},
      {"boundary_facet_count", analysis.boundary_faces.size()},
      {"boundary_vertex_count", analysis.boundary_vertices},
      {"euler_characteristic", analysis.euler},
      {"boundary_euler_characteristic", analysis.boundary_euler},
      {"genus", (2 - analysis.boundary_euler) / 2},
      {"minimum_facet_angle_degrees", minimum_facet_angle},
      {"maximum_facet_circumradius", maximum_facet_circumradius},
      {"maximum_facet_circumcentre_distance", maximum_centre_distance},
      {"maximum_boundary_vertex_deviation", vertex_deviation},
      {"orientation_disagreeing_facets", forward.orientation_disagreements},
      {"forward_hausdorff_sampled", forward.sampled_maximum},
      {"reverse_hausdorff_sampled", reverse.sampled_maximum},
      {"maximum_cell_circumradius", analysis.maximum_circumradius},
      {"maximum_radius_edge_ratio", analysis.maximum_radius_edge},
      {"minimum_dihedral_angle_degrees", analysis.minimum_dihedral},
      {"maximum_dihedral_angle_degrees", analysis.maximum_dihedral},
      {"volume", {{"value", total_volume}, {"source", expected_volume},
                  {"relative_error", volume_error}, {"relative_tolerance", volume_tolerance},
                  {"unit", unit + "^3"}}},
      {"boundary_area", {{"value", static_cast<double>(boundary_area)}, {"source", facts.area},
                         {"unit", unit + "^2"}}},
      {"subdomains", subdomains},
      {"known_limits",
       "no sharp-feature protection is requested or checked: edges and corners may be cut within the "
       "facet criteria; the reverse coverage bound is a sampled two-facet-size bound and the volume "
       "bound is source area times the measured Hausdorff distance; interior cells are accepted as "
       "covering the region once by face adjacency and the volume sum, not by point location"},
      {"independence",
       "raw OFF/JSON parse, own combinatorics, CGAL exact orientation predicate and the PMP "
       "self-intersection test only, own circumcentres, own grid nearest-triangle search; CGAL Mesh_3 "
       "and Polyhedral_mesh_domain_3 are not used"}};
  return finish_validation(request, "mesh.validate.volume_mesh", std::move(report));
}

Json run_validate(const Request& request) {
  require_input_count(request, 2, "mesh.validate.volume_mesh");
  require_parameters(request, {"facet_angle", "facet_size", "facet_distance",
                               "cell_radius_edge_ratio", "cell_size"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const std::string& unit = request.inputs[0].unit;
  const double facet_angle = wave_d::number_parameter(request, "facet_angle", 0.0, kMaximumValidatorAngle);
  const double facet_size = positive_length(request, "facet_size", unit);
  const double facet_distance = positive_length(request, "facet_distance", unit);
  const double radius_edge = wave_d::number_parameter(request, "cell_radius_edge_ratio",
                                                      kMinimumValidatorRadiusEdge, 1e6);
  const double cell_size = positive_length(request, "cell_size", unit);
  if (request.inputs[1].type == "TriangleSurfaceMesh") {
    return validate_polyhedral(request, facet_angle, facet_size, facet_distance, radius_edge, cell_size, unit);
  }
  const Domain domain = read_domain(request.inputs[1]);
  const auto mesh = wave_c::read_tetrahedral_mesh(request.inputs[0]);
  const double extent = domain.extent();
  const double vertex_tolerance = kVertexTolerance * extent;

  // Topology, orientation, adjacency, closed single boundary, vertex links, volume agreement.
  const TetAnalysis analysis = analyze_tetrahedral_mesh(mesh);
  const auto& vertices = mesh.vertices;
  for (const auto label : mesh.subdomains) {
    if (label != 1) {
      fail_validation("SUBDOMAIN_INDEX_INVALID",
                      "The domain has one region; every cell must carry subdomain index 1");
    }
  }
  if (analysis.boundary_euler != domain.euler()) {
    fail_validation("EULER_CHARACTERISTIC_MISMATCH",
                    "The boundary V - E + F differs from the Euler characteristic of the domain genus");
  }
  if (analysis.euler != domain.euler() / 2) {
    fail_validation("EULER_CHARACTERISTIC_MISMATCH",
                    "The solid's Euler characteristic differs from that of a ball (sphere, ellipsoid) "
                    "or solid torus");
  }
  const long long genus = (2 - analysis.boundary_euler) / 2;

  // Every vertex lies in the closed domain; boundary vertices lie on the analytic surface.
  double maximum_outside = -1.0;
  for (const auto& v : vertices) {
    maximum_outside = std::max(maximum_outside, implicit_value(domain, {v[0], v[1], v[2]}));
  }
  if (!(maximum_outside <= kInsideTolerance)) {
    fail_validation("VERTEX_OUTSIDE_DOMAIN", "A vertex lies outside the domain");
  }
  std::set<std::size_t> boundary_vertex_set;
  for (const auto& f : analysis.boundary_faces) boundary_vertex_set.insert(f.begin(), f.end());
  double maximum_vertex_deviation = 0;
  for (const auto index : boundary_vertex_set) {
    maximum_vertex_deviation = std::max(
        maximum_vertex_deviation, surface_distance(domain, {vertices[index][0], vertices[index][1], vertices[index][2]}));
  }
  if (!(maximum_vertex_deviation <= vertex_tolerance)) {
    fail_validation("VERTEX_OFF_SURFACE", "A boundary vertex does not lie on the analytic surface");
  }
  // Interior vertices are strictly inside: none touches the surface.
  for (std::size_t i = 0; i < vertices.size(); ++i) {
    if (boundary_vertex_set.count(i) != 0) continue;
    if (!(implicit_value(domain, {vertices[i][0], vertices[i][1], vertices[i][2]}) < -kInsideTolerance)) {
      fail_validation("INTERIOR_VERTEX_ON_SURFACE", "An interior vertex lies on or outside the surface");
    }
  }

  // Boundary facets: outward orientation and the facet criteria.
  double minimum_facet_angle = 180.0, maximum_facet_circumradius = 0.0;
  double maximum_circumcentre_distance = 0.0, maximum_sample_distance = 0.0;
  long double boundary_area = 0.0L;
  std::size_t inward = 0;
  for (const auto& face : analysis.boundary_faces) {
    const V3 a{vertices[face[0]][0], vertices[face[0]][1], vertices[face[0]][2]};
    const V3 b{vertices[face[1]][0], vertices[face[1]][1], vertices[face[1]][2]};
    const V3 c{vertices[face[2]][0], vertices[face[2]][1], vertices[face[2]][2]};
    const V3 normal = cross(sub(b, a), sub(c, a));
    boundary_area += 0.5 * norm(normal);
    const V3 centroid = mul(add(add(a, b), c), 1.0 / 3.0);
    if (dot(normal, outward_gradient(domain, centroid)) <= 0) ++inward;
    const double sides[3] = {norm(sub(b, c)), norm(sub(c, a)), norm(sub(a, b))};
    for (int i = 0; i < 3; ++i) {
      const double s1 = sides[(i + 1) % 3], s2 = sides[(i + 2) % 3];
      const double cosine =
          std::max(-1.0, std::min(1.0, (s1 * s1 + s2 * s2 - sides[i] * sides[i]) / (2.0 * s1 * s2)));
      minimum_facet_angle = std::min(minimum_facet_angle, std::acos(cosine) * 180.0 / kPi);
    }
    double radius = 0;
    const V3 centre = circumcentre(a, b, c, &radius);
    maximum_facet_circumradius = std::max(maximum_facet_circumradius, radius);
    maximum_circumcentre_distance =
        std::max(maximum_circumcentre_distance, surface_distance(domain, centre));
    constexpr int kLattice = 4;
    for (int i = 0; i <= kLattice; ++i) {
      for (int j = 0; i + j <= kLattice; ++j) {
        const double s = static_cast<double>(i) / kLattice, t = static_cast<double>(j) / kLattice;
        const V3 point = add(add(mul(a, 1.0 - s - t), mul(b, s)), mul(c, t));
        maximum_sample_distance = std::max(maximum_sample_distance, surface_distance(domain, point));
      }
    }
  }
  if (inward != 0) {
    fail_validation("ORIENTATION_NOT_OUTWARD", "A boundary facet normal opposes the outward surface gradient");
  }
  if (minimum_facet_angle < facet_angle - 1e-6) {
    fail_validation("FACET_ANGLE_VIOLATED", "A boundary facet angle is below facet_angle");
  }
  if (maximum_facet_circumradius > facet_size * (1.0 + 1e-9) + vertex_tolerance) {
    fail_validation("FACET_SIZE_VIOLATED", "A boundary facet circumradius exceeds facet_size");
  }
  if (maximum_circumcentre_distance > facet_distance * (1.0 + 1e-9) + vertex_tolerance) {
    fail_validation("FACET_DISTANCE_VIOLATED",
                    "A boundary facet circumcentre is farther than facet_distance from the surface");
  }
  if (maximum_sample_distance > facet_size * (1.0 + 1e-9) + vertex_tolerance) {
    fail_validation("HAUSDORFF_BOUND_EXCEEDED",
                    "A boundary facet point is farther than facet_size from the surface");
  }

  // Cell criteria.
  if (analysis.maximum_circumradius > cell_size * (1.0 + 1e-9)) {
    fail_validation("CELL_SIZE_VIOLATED", "A tetrahedron circumradius exceeds cell_size");
  }
  if (analysis.maximum_radius_edge > radius_edge * (1.0 + 1e-9)) {
    fail_validation("RADIUS_EDGE_VIOLATED", "A tetrahedron radius-edge ratio exceeds cell_radius_edge_ratio");
  }

  // Analytic volume and boundary area, tolerance scaled by the measured facet size.
  const double ratio = maximum_facet_circumradius / domain.min_curvature_radius();
  const double expected_volume = analytic_volume(domain);
  const double expected_area = analytic_area(domain);
  const double total_volume = static_cast<double>(analysis.volume_sum);
  const double volume_error = std::fabs(total_volume - expected_volume) / expected_volume;
  const double area_error = std::fabs(static_cast<double>(boundary_area) - expected_area) / expected_area;
  // Vertices lie on the surface, so each flat facet of circumradius r sits below it by at most
  // r^2 / (2 R_min); the relative volume deficit is bounded by area * r^2 / (2 R_min * volume).
  const double volume_tolerance =
      std::min(expected_area * maximum_facet_circumradius * maximum_facet_circumradius /
                   (2.0 * domain.min_curvature_radius() * expected_volume), 0.5) + 1e-6;
  const double area_tolerance = std::min(0.75 * ratio * ratio, 0.25) + 1e-6;
  if (area_error > area_tolerance) {
    fail_validation("AREA_MISMATCH", "Boundary area differs from the analytic surface area");
  }
  if (volume_error > volume_tolerance) {
    fail_validation("VOLUME_MISMATCH", "Total cell volume differs from the analytic enclosed volume");
  }

  Json subdomains = Json::object();
  for (const auto& entry : analysis.subdomain_volume) {
    subdomains[std::to_string(entry.first)] = {
        {"cell_count", analysis.subdomain_cells.at(entry.first)}, {"volume", static_cast<double>(entry.second)}};
  }
  Json report = {
      {"checks",
       {{"source_domain_valid", true},
        {"tetrahedral_mesh_valid", true},
        {"single_region_subdomain", true},
        {"vertices_inside_domain", true},
        {"boundary_vertices_on_domain_surface", true},
        {"interior_vertices_strictly_inside", true},
        {"boundary_euler_characteristic_matches_domain", true},
        {"solid_euler_characteristic_matches_domain", true},
        {"outward_boundary_orientation", true},
        {"facet_angle_criterion_satisfied", true},
        {"facet_size_criterion_satisfied", true},
        {"facet_distance_criterion_satisfied", true},
        {"hausdorff_bound_satisfied", true},
        {"cell_size_criterion_satisfied", true},
        {"cell_radius_edge_criterion_satisfied", true},
        {"boundary_area_matches_analytic", true},
        {"volume_matches_domain", true}}},
      {"domain_kind", domain.name()},
      {"vertex_count", analysis.vertex_count},
      {"tetrahedron_count", analysis.cell_count},
      {"boundary_facet_count", analysis.boundary_faces.size()},
      {"boundary_vertex_count", analysis.boundary_vertices},
      {"euler_characteristic", analysis.euler},
      {"boundary_euler_characteristic", analysis.boundary_euler},
      {"genus", genus},
      {"minimum_facet_angle_degrees", minimum_facet_angle},
      {"maximum_facet_circumradius", maximum_facet_circumradius},
      {"maximum_facet_circumcentre_distance", maximum_circumcentre_distance},
      {"maximum_boundary_vertex_deviation", maximum_vertex_deviation},
      {"maximum_cell_circumradius", analysis.maximum_circumradius},
      {"maximum_radius_edge_ratio", analysis.maximum_radius_edge},
      {"minimum_dihedral_angle_degrees", analysis.minimum_dihedral},
      {"maximum_dihedral_angle_degrees", analysis.maximum_dihedral},
      {"volume", {{"value", total_volume}, {"analytic", expected_volume},
                  {"relative_error", volume_error}, {"relative_tolerance", volume_tolerance},
                  {"unit", unit + "^3"}}},
      {"boundary_area", {{"value", static_cast<double>(boundary_area)}, {"analytic", expected_area},
                         {"relative_error", area_error}, {"relative_tolerance", area_tolerance},
                         {"unit", unit + "^2"}}},
      {"subdomains", subdomains},
      {"known_limits",
       "cells are accepted as covering the region exactly once because adjacent cells face opposite "
       "ways, the cell volume sum equals the boundary divergence volume and that volume equals the "
       "analytic volume within the stated tolerance"},
      {"independence",
       "raw JSON parse, CGAL exact orientation predicate only, own combinatorics, closed-form (or "
       "Lagrange-Newton) point-to-surface distance, own circumcentres and quadrature; CGAL Mesh_3 "
       "and its implicit-domain oracle are not used"}};
  return finish_validation(request, "mesh.validate.volume_mesh", std::move(report));
}

}  // namespace

std::vector<OperationDefinition> volume_mesh_operations() {
  std::vector<OperationDefinition> result;
  const Json bindings = {{"facet_angle", "facet_angle"},
                         {"facet_size", "facet_size"},
                         {"facet_distance", "facet_distance"},
                         {"cell_radius_edge_ratio", "cell_radius_edge_ratio"},
                         {"cell_size", "cell_size"}};
  result.push_back(wave_c::make_definition(
      "mesh.volume.generate", {"ImplicitSurfaceDomain", "TriangleSurfaceMesh"}, "TetrahedralMesh", "transform", run_generate,
      {"Mesh_3", "Triangulation_3"},
      {{"source_header", "CGAL/make_mesh_3.h"},
       {"symbols", {"make_mesh_3", "Labeled_mesh_domain_3", "Polyhedral_mesh_domain_3", "Mesh_criteria_3"}},
       {"input_format", "json|off"},
       {"output_format", "json"},
       {"domain_kinds", {"sphere", "ellipsoid", "torus", "polyhedral"}},
       {"required_parameters", {"facet_angle", "facet_size", "facet_distance",
                                "cell_radius_edge_ratio", "cell_size"}},
       {"validators", {"mesh.validate.volume_mesh"}},
       {"validator_parameter_bindings", {{"mesh.validate.volume_mesh", bindings}}},
       {"maximum_estimated_cells", kMaximumEstimatedCells}}));
  result.push_back(wave_c::make_definition(
      "mesh.validate.volume_mesh", {"TetrahedralMesh", "ImplicitSurfaceDomain", "TriangleSurfaceMesh"},
      "ValidationReport",
      "validator", run_validate, {"Mesh_3", "Triangulation_3"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"bound_parameters", {"facet_angle", "facet_size", "facet_distance", "cell_radius_edge_ratio",
                             "cell_size"}},
       {"checks",
        {"source_domain_valid", "tetrahedral_mesh_valid", "single_region_subdomain",
         "boundary_euler_characteristic_matches_domain", "solid_euler_characteristic_matches_domain",
         "boundary_vertices_on_domain_surface", "outward_boundary_orientation",
         "facet_angle_criterion_satisfied", "facet_size_criterion_satisfied",
         "facet_distance_criterion_satisfied", "hausdorff_bound_satisfied",
         "cell_size_criterion_satisfied", "cell_radius_edge_criterion_satisfied",
         "volume_matches_domain"}},
       {"implicit_domain_extra_checks",
        {"vertices_inside_domain", "interior_vertices_strictly_inside", "boundary_area_matches_analytic"}},
       {"polyhedral_domain_extra_checks", {"source_coverage_bound_satisfied"}}}));
  return result;
}

}  // namespace cgal_master::wave_e
