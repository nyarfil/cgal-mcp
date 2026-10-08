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

constexpr double kPi = 3.14159265358979323846;
constexpr double kMaximumProducerAngle = 30.0;       // Surface_mesher termination guarantee
constexpr double kMaximumValidatorAngle = 60.0;
constexpr std::size_t kMaximumSurfaceFacets = 30000;  // estimate-based refusal (producer)
constexpr double kMaximumDimension = 1e6;
constexpr double kMaximumEllipsoidRatio = 8.0;
constexpr double kMaximumTorusRatio = 0.75;           // minor_radius / major_radius
constexpr double kOracleErrorBound = 1e-8;            // relative to the bounding radius
constexpr double kMaximumDistanceRatio = 0.1;         // distance_bound / smallest curvature radius
constexpr double kVertexTolerance = 2e-6;             // relative to the domain extent

// ---------------------------------------------------------------------------
// Typed implicit domain (a closed enumerated set, never an expression)
// ---------------------------------------------------------------------------

enum class Kind { Sphere, Ellipsoid, Torus };

struct Domain {
  Kind kind = Kind::Sphere;
  double a = 0, b = 0, c = 0;  // sphere: a; ellipsoid: a,b,c; torus: a = major, b = minor
  std::string name() const {
    return kind == Kind::Sphere ? "sphere" : kind == Kind::Ellipsoid ? "ellipsoid" : "torus";
  }
  long long euler() const { return kind == Kind::Torus ? 0 : 2; }
  // Largest distance of the surface from the domain origin (coordinates are origin centred).
  double extent() const {
    switch (kind) {
      case Kind::Sphere: return a;
      case Kind::Ellipsoid: return std::max({a, b, c});
      case Kind::Torus: return a + b;
    }
    return a;
  }
  // Smallest absolute principal radius of curvature of the surface.
  double min_curvature_radius() const {
    switch (kind) {
      case Kind::Sphere: return a;
      case Kind::Ellipsoid: {
        const double smallest = std::min({a, b, c}), largest = std::max({a, b, c});
        return smallest * smallest / largest;
      }
      case Kind::Torus: return std::min(b, a - b);
    }
    return a;
  }
};

[[noreturn]] void input_error(const std::string& code, const std::string& message) {
  throw WorkerError("INPUT_ERROR", code, message);
}

double positive_number(const Json& value, const std::string& name) {
  if (!value.is_number() || value.is_boolean()) {
    input_error("SCHEMA_MISMATCH", "ImplicitSurfaceDomain " + name + " must be a number");
  }
  const double result = value.get<double>();
  if (!std::isfinite(result) || !(result > 0) || result > kMaximumDimension) {
    input_error("INVALID_DOMAIN", "ImplicitSurfaceDomain " + name +
                                      " must be positive, finite and at most 1e6");
  }
  return result;
}

Domain read_domain(const ArtifactInput& input) {
  if (input.type != "ImplicitSurfaceDomain") {
    throw WorkerError("TYPE_ERROR", "INPUT_TYPE_MISMATCH",
                      "Expected input type ImplicitSurfaceDomain, received " + input.type);
  }
  if (input.format != "json") {
    throw WorkerError("TYPE_ERROR", "INPUT_FORMAT_MISMATCH",
                      "Expected input format json, received " + input.format);
  }
  if (input.unit != "mm" && input.unit != "cm" && input.unit != "m") {
    throw WorkerError("TYPE_ERROR", "UNSUPPORTED_UNIT", "Geometry unit must be one of: mm, cm, m");
  }
  Json value;
  try {
    value = Json::parse(read_verified_input_bytes(input));
  } catch (const nlohmann::json::exception&) {
    input_error("MALFORMED_JSON", "ImplicitSurfaceDomain must be valid JSON");
  }
  if (!value.is_object() || value.size() != 2 || !value.contains("kind") ||
      !value.contains("parameters") || !value.at("kind").is_string() ||
      !value.at("parameters").is_object()) {
    input_error("SCHEMA_MISMATCH", "ImplicitSurfaceDomain needs exactly kind and parameters");
  }
  const std::string kind = value.at("kind").get<std::string>();
  const auto& parameters = value.at("parameters");
  auto require_keys = [&](std::initializer_list<const char*> keys) {
    if (parameters.size() != keys.size()) {
      input_error("SCHEMA_MISMATCH", "ImplicitSurfaceDomain parameters do not match its kind");
    }
    for (const char* key : keys) {
      if (!parameters.contains(key)) {
        input_error("SCHEMA_MISMATCH", "ImplicitSurfaceDomain parameters do not match its kind");
      }
    }
  };
  Domain domain;
  if (kind == "sphere") {
    require_keys({"radius"});
    domain.kind = Kind::Sphere;
    domain.a = positive_number(parameters.at("radius"), "radius");
  } else if (kind == "ellipsoid") {
    require_keys({"semi_axis_x", "semi_axis_y", "semi_axis_z"});
    domain.kind = Kind::Ellipsoid;
    domain.a = positive_number(parameters.at("semi_axis_x"), "semi_axis_x");
    domain.b = positive_number(parameters.at("semi_axis_y"), "semi_axis_y");
    domain.c = positive_number(parameters.at("semi_axis_z"), "semi_axis_z");
    if (std::max({domain.a, domain.b, domain.c}) >
        kMaximumEllipsoidRatio * std::min({domain.a, domain.b, domain.c})) {
      input_error("INVALID_DOMAIN", "Ellipsoid axis ratio exceeds the supported maximum of 8");
    }
  } else if (kind == "torus") {
    require_keys({"major_radius", "minor_radius"});
    domain.kind = Kind::Torus;
    domain.a = positive_number(parameters.at("major_radius"), "major_radius");
    domain.b = positive_number(parameters.at("minor_radius"), "minor_radius");
    if (domain.b > kMaximumTorusRatio * domain.a) {
      input_error("INVALID_DOMAIN", "Torus minor_radius must not exceed 0.75 * major_radius");
    }
  } else {
    input_error("UNSUPPORTED_DOMAIN_KIND", "ImplicitSurfaceDomain kind must be sphere, ellipsoid or torus");
  }
  return domain;
}

double positive_length(const Request& request, const char* name, const std::string& unit) {
  const double value = typed_length_parameter(request, name, unit);
  if (!(value > 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be positive");
  }
  return value;
}

// ---------------------------------------------------------------------------
// Vector helpers
// ---------------------------------------------------------------------------

V3 sub(const V3& x, const V3& y) { return {x[0] - y[0], x[1] - y[1], x[2] - y[2]}; }
V3 add(const V3& x, const V3& y) { return {x[0] + y[0], x[1] + y[1], x[2] + y[2]}; }
V3 mul(const V3& x, double s) { return {x[0] * s, x[1] * s, x[2] * s}; }
double dot(const V3& x, const V3& y) { return x[0] * y[0] + x[1] * y[1] + x[2] * y[2]; }
V3 cross(const V3& x, const V3& y) {
  return {x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]};
}
double norm(const V3& x) { return std::sqrt(dot(x, x)); }

// Outward gradient direction of the (positive outside) implicit function.
V3 outward_gradient(const Domain& d, const V3& p) {
  switch (d.kind) {
    case Kind::Sphere: return p;
    case Kind::Ellipsoid: return {p[0] / (d.a * d.a), p[1] / (d.b * d.b), p[2] / (d.c * d.c)};
    case Kind::Torus: {
      const double rho = std::hypot(p[0], p[1]);
      if (rho == 0) return {0, 0, p[2]};
      const double radial = (rho - d.a) / rho;
      return {radial * p[0], radial * p[1], p[2]};
    }
  }
  return p;
}

// Solve the 4x4 system J x = r in place (Gaussian elimination with partial pivoting).
bool solve4(double j[4][4], double r[4]) {
  for (int column = 0; column < 4; ++column) {
    int pivot = column;
    for (int row = column + 1; row < 4; ++row) {
      if (std::fabs(j[row][column]) > std::fabs(j[pivot][column])) pivot = row;
    }
    if (std::fabs(j[pivot][column]) < 1e-300) return false;
    if (pivot != column) {
      for (int k = 0; k < 4; ++k) std::swap(j[pivot][k], j[column][k]);
      std::swap(r[pivot], r[column]);
    }
    for (int row = column + 1; row < 4; ++row) {
      const double factor = j[row][column] / j[column][column];
      for (int k = column; k < 4; ++k) j[row][k] -= factor * j[column][k];
      r[row] -= factor * r[column];
    }
  }
  for (int row = 3; row >= 0; --row) {
    for (int k = row + 1; k < 4; ++k) r[row] -= j[row][k] * r[k];
    r[row] /= j[row][row];
  }
  return true;
}

// Distance of a point from an ellipsoid surface: Lagrange-Newton on |q-p|^2 subject to f(q)=0,
// started from a Sampson projection. Falls back to the Sampson distance (an upper bound).
double ellipsoid_distance(const Domain& d, const V3& p) {
  const double axes[3] = {d.a, d.b, d.c};
  auto value = [&](const V3& q) {
    return q[0] * q[0] / (axes[0] * axes[0]) + q[1] * q[1] / (axes[1] * axes[1]) +
           q[2] * q[2] / (axes[2] * axes[2]) - 1.0;
  };
  auto gradient = [&](const V3& q) {
    return V3{2 * q[0] / (axes[0] * axes[0]), 2 * q[1] / (axes[1] * axes[1]),
              2 * q[2] / (axes[2] * axes[2])};
  };
  V3 q = p;
  if (dot(q, q) == 0) return std::min({d.a, d.b, d.c});
  for (int step = 0; step < 60; ++step) {
    const V3 g = gradient(q);
    const double gg = dot(g, g);
    if (gg == 0) break;
    const double f = value(q);
    if (std::fabs(f) < 1e-15) break;
    q = sub(q, mul(g, f / gg));
  }
  const double sampson = norm(sub(p, q));
  V3 g = gradient(q);
  const double gg = dot(g, g);
  if (gg == 0) return sampson;
  double lambda = dot(sub(p, q), g) / gg;
  V3 best = q;
  for (int step = 0; step < 12; ++step) {
    g = gradient(q);
    double jacobian[4][4] = {};
    double residual[4];
    for (int i = 0; i < 3; ++i) {
      jacobian[i][i] = 1.0 + lambda * 2.0 / (axes[i] * axes[i]);
      jacobian[i][3] = g[i];
      jacobian[3][i] = g[i];
      residual[i] = -((q[i] - p[i]) + lambda * g[i]);
    }
    residual[3] = -value(q);
    if (!solve4(jacobian, residual)) return sampson;
    for (int i = 0; i < 3; ++i) q[i] += residual[i];
    lambda += residual[3];
    best = q;
    if (std::fabs(residual[0]) + std::fabs(residual[1]) + std::fabs(residual[2]) < 1e-14 * d.extent())
      break;
  }
  if (std::fabs(value(best)) > 1e-9) return sampson;
  return std::min(sampson, norm(sub(p, best)));
}

// Euclidean distance of a point from the analytic surface.
double surface_distance(const Domain& d, const V3& p) {
  switch (d.kind) {
    case Kind::Sphere: return std::fabs(norm(p) - d.a);
    case Kind::Torus: {
      const double rho = std::hypot(p[0], p[1]);
      return std::fabs(std::hypot(rho - d.a, p[2]) - d.b);
    }
    case Kind::Ellipsoid: return ellipsoid_distance(d, p);
  }
  return 0;
}

double analytic_volume(const Domain& d) {
  switch (d.kind) {
    case Kind::Sphere: return 4.0 / 3.0 * kPi * d.a * d.a * d.a;
    case Kind::Ellipsoid: return 4.0 / 3.0 * kPi * d.a * d.b * d.c;
    case Kind::Torus: return 2.0 * kPi * kPi * d.a * d.b * d.b;
  }
  return 0;
}

// Analytic area; the ellipsoid has no closed form and is integrated over the (theta, phi)
// parametrisation by a midpoint rule that is spectrally accurate in phi.
double analytic_area(const Domain& d) {
  switch (d.kind) {
    case Kind::Sphere: return 4.0 * kPi * d.a * d.a;
    case Kind::Torus: return 4.0 * kPi * kPi * d.a * d.b;
    case Kind::Ellipsoid: {
      const int n_theta = 2000, n_phi = 2000;
      std::vector<double> sin_phi(n_phi), cos_phi(n_phi);
      for (int j = 0; j < n_phi; ++j) {
        const double phi = 2.0 * kPi * (j + 0.5) / n_phi;
        sin_phi[j] = std::sin(phi);
        cos_phi[j] = std::cos(phi);
      }
      double total = 0;
      for (int i = 0; i < n_theta; ++i) {
        const double theta = kPi * (i + 0.5) / n_theta;
        const double s = std::sin(theta), c = std::cos(theta);
        double row = 0;
        for (int j = 0; j < n_phi; ++j) {
          const double x = d.b * d.c * s * cos_phi[j], y = d.a * d.c * s * sin_phi[j],
                       z = d.a * d.b * c;
          row += std::sqrt(x * x + y * y + z * z);
        }
        total += s * row;
      }
      return total * (kPi / n_theta) * (2.0 * kPi / n_phi);
    }
  }
  return 0;
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

V3 circumcentre(const V3& a, const V3& b, const V3& c, double* radius) {
  const V3 u = sub(b, a), v = sub(c, a), w = cross(u, v);
  const double ww = dot(w, w);
  const V3 s = mul(add(mul(cross(v, w), dot(u, u)), mul(cross(w, u), dot(v, v))), 1.0 / (2.0 * ww));
  *radius = norm(s);
  return add(a, s);
}

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
