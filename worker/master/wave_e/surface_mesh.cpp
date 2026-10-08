// Wave E (family 7.14) surface mesh generation: CGAL Surface_mesher make_surface_mesh over a
// FIXED ENUMERATED set of typed implicit domains (sphere, ellipsoid, torus) and an independent
// validator that recomputes topology, orientation, analytic distance, criteria and analytic
// area / volume / genus from the raw OFF candidate and the domain specification only.
// No free-form expression or code is ever accepted: the domain kind selects one of the
// compiled-in implicit functions below. The validator never calls the mesher.
//
// Surface_mesher is a deprecated CGAL 6.2.1 package; the deprecation guard is disabled on
// purpose and the operation catalog states this explicitly.
#include <CGAL/Installation/internal/disable_deprecation_warnings_and_errors.h>

#include "wave_e_operations.h"

#include "../artifact_io.h"
#include "../wave_c/wave_c_common.h"
#include "../wave_d/wave_d_common.h"
#include "implicit_domain.h"

#include <CGAL/Complex_2_in_triangulation_3.h>
#include <CGAL/Implicit_surface_3.h>
#include <CGAL/Random.h>
#include <CGAL/Surface_mesh_default_criteria_3.h>
#include <CGAL/Surface_mesh_default_triangulation_3.h>
#include <CGAL/make_surface_mesh.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <map>
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
using namespace implicit;

constexpr double kMaximumProducerAngle = 30.0;       // Surface_mesher termination guarantee
constexpr double kMaximumValidatorAngle = 60.0;
constexpr std::size_t kMaximumSurfaceFacets = 30000;  // estimate-based refusal (producer)
constexpr double kOracleErrorBound = 1e-8;            // relative to the bounding radius
constexpr double kMaximumDistanceRatio = 0.1;         // distance_bound / smallest curvature radius
constexpr double kVertexTolerance = 2e-6;             // relative to the domain extent

double positive_length(const Request& request, const char* name, const std::string& unit) {
  const double value = typed_length_parameter(request, name, unit);
  if (!(value > 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be positive");
  }
  return value;
}

// ---------------------------------------------------------------------------
// Producer: CGAL Surface_mesher make_surface_mesh
// ---------------------------------------------------------------------------

using Tr = CGAL::Surface_mesh_default_triangulation_3;
using C2t3 = CGAL::Complex_2_in_triangulation_3<Tr>;
using GT = Tr::Geom_traits;
using Sphere_3 = GT::Sphere_3;
using Point_3 = GT::Point_3;
using FT = GT::FT;

// A closed set of implicit functions, positive outside / negative inside the surface.
struct ImplicitFunction {
  Domain domain;
  FT operator()(Point_3 p) const {
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
using Surface_3 = CGAL::Implicit_surface_3<GT, ImplicitFunction>;

double estimated_facets(const Domain& d, double size, double distance) {
  const double radius = std::min(size, std::sqrt(2.0 * d.min_curvature_radius() * distance));
  const double area = d.kind == Kind::Ellipsoid
      ? 4.0 * kPi * std::pow((std::pow(d.a * d.b, 1.6075) + std::pow(d.a * d.c, 1.6075) +
                              std::pow(d.b * d.c, 1.6075)) / 3.0, 1.0 / 1.6075)
      : analytic_area(d);
  // An equilateral facet of circumradius r has area 1.299 r^2; refined meshes are about half as
  // efficient, so this deliberately overestimates the facet count.
  return area / (0.65 * radius * radius);
}

Json run_generate(const Request& request) {
  require_input_count(request, 1, "mesh.surface.generate");
  require_parameters(request, {"angle_bound", "size_bound", "distance_bound"});
  const auto& source = request.inputs[0];
  const Domain domain = read_domain(source);
  const double angle = wave_d::number_parameter(request, "angle_bound", 0.0, kMaximumProducerAngle);
  const double size = positive_length(request, "size_bound", source.unit);
  const double distance = positive_length(request, "distance_bound", source.unit);
  if (distance > kMaximumDistanceRatio * domain.min_curvature_radius()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "distance_bound must not exceed 0.1 times the smallest curvature radius of the "
                      "domain (coarser meshes cannot be validated against analytic area and volume)");
  }
  if (!(estimated_facets(domain, size, distance) <= static_cast<double>(kMaximumSurfaceFacets))) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "size_bound / distance_bound are too small for bounded validation");
  }
  // Deterministic initial points: the oracle draws from CGAL's default random generator.
  CGAL::get_default_random() = CGAL::Random(0);

  Tr tr;
  C2t3 c2t3(tr);
  const double centre_x = domain.kind == Kind::Torus ? domain.a : 0.0;
  const double radius = 1.25 * (domain.kind == Kind::Torus ? 2.0 * domain.a + domain.b
                                                            : domain.extent());
  Surface_3 surface(ImplicitFunction{domain}, Sphere_3(Point_3(centre_x, 0, 0), radius * radius),
                    kOracleErrorBound);
  CGAL::Surface_mesh_default_criteria_3<Tr> criteria(angle, size, distance);
  CGAL::make_surface_mesh(c2t3, surface, criteria, CGAL::Manifold_tag());

  // Collect facets as coordinate triples, oriented along the outward gradient.
  std::vector<std::array<V3, 3>> facets;
  for (auto facet = tr.finite_facets_begin(); facet != tr.finite_facets_end(); ++facet) {
    if (!facet->first->is_facet_on_surface(facet->second)) continue;
    std::array<V3, 3> corners;
    int slot = 0;
    for (int k = 0; k < 4; ++k) {
      if (k == facet->second) continue;
      const auto& point = facet->first->vertex(k)->point();
      corners[slot++] = {CGAL::to_double(point.x()), CGAL::to_double(point.y()),
                         CGAL::to_double(point.z())};
    }
    const V3 centroid = mul(add(add(corners[0], corners[1]), corners[2]), 1.0 / 3.0);
    const V3 normal = cross(sub(corners[1], corners[0]), sub(corners[2], corners[0]));
    if (dot(normal, outward_gradient(domain, centroid)) < 0) std::swap(corners[1], corners[2]);
    facets.push_back(corners);
  }
  if (facets.empty()) {
    throw WorkerError("INTERNAL", "EMPTY_OUTPUT", "Surface_mesher produced no facets");
  }
  if (facets.size() > 2 * kMaximumSurfaceFacets) {
    throw WorkerError("RESOURCE_LIMIT", "MESH_SIZE_LIMIT_EXCEEDED",
                      "Surface_mesher output exceeds the bounded validation budget");
  }
  // Canonical vertex order and triangle order, independent of triangulation memory layout.
  std::map<V3, std::size_t> index;
  for (const auto& facet : facets) {
    for (const auto& corner : facet) index.emplace(corner, 0);
  }
  std::size_t next = 0;
  std::vector<V3> vertices;
  for (auto& entry : index) {
    entry.second = next++;
    vertices.push_back(entry.first);
  }
  std::vector<std::array<std::size_t, 3>> triangles;
  for (const auto& facet : facets) {
    std::array<std::size_t, 3> t{index.at(facet[0]), index.at(facet[1]), index.at(facet[2])};
    if (t[1] < t[0] && t[1] < t[2]) t = {t[1], t[2], t[0]};
    else if (t[2] < t[0] && t[2] < t[1]) t = {t[2], t[0], t[1]};
    triangles.push_back(t);
  }
  std::sort(triangles.begin(), triangles.end());
  // Each surface facet is visited from both of its incident cells; the oriented copies coincide.
  triangles.erase(std::unique(triangles.begin(), triangles.end()), triangles.end());

  wave_d::SurfaceMesh mesh;
  std::vector<wave_d::SurfaceMesh::Vertex_index> handles;
  for (const auto& v : vertices) handles.push_back(mesh.add_vertex(wave_d::Point3(v[0], v[1], v[2])));
  for (const auto& t : triangles) {
    if (mesh.add_face(handles[t[0]], handles[t[1]], handles[t[2]]) ==
        wave_d::SurfaceMesh::null_face()) {
      throw WorkerError("INTERNAL", "NON_MANIFOLD_OUTPUT", "Surface_mesher output is not a manifold");
    }
  }
  const auto vertex_count = mesh.number_of_vertices();
  const auto face_count = mesh.number_of_faces();
  const auto edge_count = mesh.number_of_edges();
  auto output = wave_d::write_mesh_candidate(request, mesh, source.unit);
  Json metrics = {{"algorithm", "CGAL::make_surface_mesh"},
                  {"criteria", "CGAL::Surface_mesh_default_criteria_3"},
                  {"domain_kind", domain.name()},
                  {"vertex_count", vertex_count},
                  {"facet_count", face_count},
                  {"edge_count", edge_count},
                  {"euler_characteristic", static_cast<long long>(vertex_count) -
                                               static_cast<long long>(edge_count) +
                                               static_cast<long long>(face_count)},
                  {"angle_bound", angle},
                  {"size_bound", size},
                  {"distance_bound", distance},
                  {"manifold_tag", "CGAL::Manifold_tag"},
                  {"deprecated_package", "Surface_mesher"},
                  {"effective_kernel", wave_c::kEpick}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---------------------------------------------------------------------------
// Validator (independent): topology, orientation, analytic geometry, criteria
// ---------------------------------------------------------------------------

Json run_validate(const Request& request) {
  require_input_count(request, 2, "mesh.validate.surface_mesh");
  require_parameters(request, {"angle_bound", "size_bound", "distance_bound"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const double angle = wave_d::number_parameter(request, "angle_bound", 0.0, kMaximumValidatorAngle);
  const std::string& unit = request.inputs[0].unit;
  const double size = positive_length(request, "size_bound", unit);
  const double distance_bound = positive_length(request, "distance_bound", unit);
  const Domain domain = read_domain(request.inputs[1]);
  const auto mesh = wave_d::read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  const auto facts = wave_d::analyze(mesh);
  const double extent = domain.extent();
  const double vertex_tolerance = kVertexTolerance * extent;

  {
    std::map<V3, int> seen;
    for (const auto& v : mesh.vertices) {
      if (++seen[v] > 1) fail_validation("REPEATED_VERTEX", "Candidate repeats a vertex position");
    }
  }
  if (!facts.all_triangles) fail_validation("NOT_TRIANGLE_MESH", "Candidate has non-triangle faces");
  if (facts.degenerate_face_count != 0) {
    fail_validation("DEGENERATE_TRIANGLE", "Candidate has degenerate triangles");
  }
  if (facts.unreferenced_vertex_count != 0) {
    fail_validation("UNUSED_VERTEX", "A candidate vertex is in no triangle");
  }
  if (!facts.closed) fail_validation("SURFACE_NOT_CLOSED", "Candidate has boundary edges");
  if (!facts.manifold_edges) fail_validation("NON_MANIFOLD_EDGE", "An edge is used by more than two triangles");
  if (!facts.manifold_vertices) fail_validation("NON_MANIFOLD_VERTEX", "A vertex star is not a single fan");
  if (!facts.consistently_oriented) {
    fail_validation("INCONSISTENT_ORIENTATION", "Adjacent triangles are not consistently oriented");
  }
  if (facts.component_count != 1) {
    fail_validation("MULTIPLE_COMPONENTS", "Candidate is not a single connected surface");
  }
  if (facts.euler_characteristic != domain.euler()) {
    fail_validation("EULER_CHARACTERISTIC_MISMATCH",
                    "V - E + F differs from the Euler characteristic of the domain genus");
  }
  const long long genus = (2 - facts.euler_characteristic) / 2;

  double maximum_vertex_deviation = 0;
  for (const auto& v : mesh.vertices) {
    maximum_vertex_deviation = std::max(maximum_vertex_deviation, surface_distance(domain, v));
  }
  if (!(maximum_vertex_deviation <= vertex_tolerance)) {
    fail_validation("VERTEX_OFF_SURFACE", "A vertex does not lie on the analytic surface");
  }
  if (!(facts.signed_volume > 0)) {
    fail_validation("ORIENTATION_NOT_OUTWARD", "Candidate is oriented inward (non-positive volume)");
  }
  std::size_t inward = 0;
  double minimum_sine_angle = 180.0;
  double maximum_circumradius = 0, maximum_circumcentre_distance = 0, maximum_sample_distance = 0;
  for (const auto& face : mesh.faces) {
    const V3& a = mesh.vertices[face[0]];
    const V3& b = mesh.vertices[face[1]];
    const V3& c = mesh.vertices[face[2]];
    const V3 normal = cross(sub(b, a), sub(c, a));
    const V3 centroid = mul(add(add(a, b), c), 1.0 / 3.0);
    if (dot(normal, outward_gradient(domain, centroid)) <= 0) ++inward;
    double radius = 0;
    const V3 centre = circumcentre(a, b, c, &radius);
    maximum_circumradius = std::max(maximum_circumradius, radius);
    maximum_circumcentre_distance =
        std::max(maximum_circumcentre_distance, surface_distance(domain, centre));
    // Barycentric lattice samples (corners, edge points, interior) of the flat triangle.
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
    fail_validation("ORIENTATION_NOT_OUTWARD", "A triangle normal opposes the outward surface gradient");
  }
  minimum_sine_angle = facts.min_angle_degrees;
  if (minimum_sine_angle < angle - 1e-6) {
    fail_validation("ANGLE_CRITERION_VIOLATED", "A facet angle is below angle_bound");
  }
  if (maximum_circumradius > size * (1.0 + 1e-9) + vertex_tolerance) {
    fail_validation("SIZE_CRITERION_VIOLATED", "A facet circumradius exceeds size_bound");
  }
  if (maximum_circumcentre_distance > distance_bound * (1.0 + 1e-9) + vertex_tolerance) {
    fail_validation("DISTANCE_CRITERION_VIOLATED",
                    "A facet circumcentre is farther than distance_bound from the surface");
  }
  // Every point of a facet lies inside its surface Delaunay ball, whose centre is on the surface
  // and whose radius is bounded by size_bound; hence its distance from the surface is too.
  if (maximum_sample_distance > size * (1.0 + 1e-9) + vertex_tolerance) {
    fail_validation("HAUSDORFF_BOUND_EXCEEDED", "A facet point is farther than size_bound from the surface");
  }
  // Analytic area and volume, with a tolerance scaled by the measured facet size: an inscribed
  // facet of circumradius r on a surface of curvature radius R loses at most about 0.375 (r / R)^2 of area; the tolerances keep a 2x margin
  // and are capped so that grossly coarse candidates are rejected.
  const double ratio = maximum_circumradius / domain.min_curvature_radius();
  const double expected_area = analytic_area(domain);
  const double expected_volume = analytic_volume(domain);
  const double area_error = std::fabs(facts.area - expected_area) / expected_area;
  const double volume_error = std::fabs(facts.signed_volume - expected_volume) / expected_volume;
  const double area_tolerance = std::min(0.75 * ratio * ratio, 0.25) + 1e-6;
  const double volume_tolerance = std::min(1.5 * ratio * ratio, 0.5) + 1e-6;
  if (area_error > area_tolerance) {
    fail_validation("AREA_MISMATCH", "Mesh area differs from the analytic surface area");
  }
  if (volume_error > volume_tolerance) {
    fail_validation("VOLUME_MISMATCH", "Mesh volume differs from the analytic enclosed volume");
  }
  Json report = {
      {"checks",
       {{"source_domain_valid", true},
        {"triangle_mesh", true},
        {"closed_surface", true},
        {"edge_manifold", true},
        {"vertex_manifold", true},
        {"consistent_orientation", true},
        {"single_component", true},
        {"euler_characteristic_matches_domain", true},
        {"vertices_on_analytic_surface", true},
        {"outward_orientation", true},
        {"angle_criterion_satisfied", true},
        {"size_criterion_satisfied", true},
        {"distance_criterion_satisfied", true},
        {"hausdorff_bound_satisfied", true},
        {"area_matches_analytic", true},
        {"volume_matches_analytic", true}}},
      {"domain_kind", domain.name()},
      {"vertex_count", facts.vertex_count},
      {"facet_count", facts.face_count},
      {"edge_count", facts.edge_count},
      {"euler_characteristic", facts.euler_characteristic},
      {"genus", genus},
      {"minimum_angle_degrees", minimum_sine_angle},
      {"maximum_circumradius", maximum_circumradius},
      {"maximum_vertex_deviation", maximum_vertex_deviation},
      {"maximum_circumcentre_distance", maximum_circumcentre_distance},
      {"maximum_sampled_distance", maximum_sample_distance},
      {"area", {{"value", facts.area}, {"analytic", expected_area}, {"relative_error", area_error},
                {"relative_tolerance", area_tolerance}, {"unit", unit + "^2"}}},
      {"volume", {{"value", facts.signed_volume}, {"analytic", expected_volume},
                  {"relative_error", volume_error}, {"relative_tolerance", volume_tolerance},
                  {"unit", unit + "^3"}}},
      {"independence",
       "raw OFF parse, own combinatorics, closed-form (or Lagrange-Newton) point-to-surface "
       "distance, own circumcentres and quadrature; CGAL Surface_mesher, Mesh_3 and the "
       "implicit-surface oracle are not used"}};
  return finish_validation(request, "mesh.validate.surface_mesh", std::move(report));
}

}  // namespace

std::vector<OperationDefinition> surface_mesh_operations() {
  std::vector<OperationDefinition> result;
  result.push_back(wave_c::make_definition(
      "mesh.surface.generate", {"ImplicitSurfaceDomain"}, "TriangleSurfaceMesh", "transform",
      run_generate, {"Surface_mesher", "Triangulation_3"},
      {{"source_header", "CGAL/make_surface_mesh.h"},
       {"symbols", {"make_surface_mesh", "Implicit_surface_3", "Surface_mesh_default_criteria_3"}},
       {"input_format", "json"},
       {"output_format", "off"},
       {"domain_kinds", {"sphere", "ellipsoid", "torus"}},
       {"required_parameters", {"angle_bound", "size_bound", "distance_bound"}},
       {"validators", {"mesh.validate.surface_mesh"}},
       {"validator_parameter_bindings",
        {{"mesh.validate.surface_mesh",
          {{"angle_bound", "angle_bound"}, {"size_bound", "size_bound"},
           {"distance_bound", "distance_bound"}}}}},
       {"maximum_estimated_facets", kMaximumSurfaceFacets}}));
  result.push_back(wave_c::make_definition(
      "mesh.validate.surface_mesh", {"TriangleSurfaceMesh", "ImplicitSurfaceDomain"},
      "ValidationReport", "validator", run_validate, {"Surface_mesher", "Triangulation_3"},
      {{"input_slots", {"candidate", "source"}},
       {"output_slot", "validation"},
       {"bound_parameters", {"angle_bound", "size_bound", "distance_bound"}},
       {"checks",
        {"source_domain_valid", "triangle_mesh", "closed_surface", "edge_manifold",
         "vertex_manifold", "consistent_orientation", "single_component",
         "euler_characteristic_matches_domain", "vertices_on_analytic_surface",
         "outward_orientation", "angle_criterion_satisfied", "size_criterion_satisfied",
         "distance_criterion_satisfied", "hausdorff_bound_satisfied", "area_matches_analytic",
         "volume_matches_analytic"}}}));
  return result;
}

}  // namespace cgal_master::wave_e
