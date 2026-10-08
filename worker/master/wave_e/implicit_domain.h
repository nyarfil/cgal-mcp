// Shared typed implicit-domain model for Wave E (sphere, ellipsoid, torus): a CLOSED enumerated
// set, never an expression. Provides the strict JSON reader, analytic point-to-surface distance,
// outward gradient, area and volume used by the surface and volume mesh validators.
#pragma once

#include "../artifact_io.h"
#include "../wave_d/wave_d_common.h"

#include <algorithm>
#include <cmath>
#include <initializer_list>
#include <string>
#include <vector>

namespace cgal_master::wave_e::implicit {

using wave_d::V3;

constexpr double kPi = 3.14159265358979323846;
constexpr double kMaximumDimension = 1e6;
constexpr double kMaximumEllipsoidRatio = 8.0;
constexpr double kMaximumTorusRatio = 0.75;           // minor_radius / major_radius

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

[[noreturn]] inline void input_error(const std::string& code, const std::string& message) {
  throw WorkerError("INPUT_ERROR", code, message);
}

inline double positive_number(const Json& value, const std::string& name) {
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

inline Domain read_domain(const ArtifactInput& input) {
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


inline V3 sub(const V3& x, const V3& y) { return {x[0] - y[0], x[1] - y[1], x[2] - y[2]}; }
inline V3 add(const V3& x, const V3& y) { return {x[0] + y[0], x[1] + y[1], x[2] + y[2]}; }
inline V3 mul(const V3& x, double s) { return {x[0] * s, x[1] * s, x[2] * s}; }
inline double dot(const V3& x, const V3& y) { return x[0] * y[0] + x[1] * y[1] + x[2] * y[2]; }
inline V3 cross(const V3& x, const V3& y) {
  return {x[1] * y[2] - x[2] * y[1], x[2] * y[0] - x[0] * y[2], x[0] * y[1] - x[1] * y[0]};
}
inline double norm(const V3& x) { return std::sqrt(dot(x, x)); }

// Outward gradient direction of the (positive outside) implicit function.
inline V3 outward_gradient(const Domain& d, const V3& p) {
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
inline bool solve4(double j[4][4], double r[4]) {
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
inline double ellipsoid_distance(const Domain& d, const V3& p) {
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
inline double surface_distance(const Domain& d, const V3& p) {
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

inline double analytic_volume(const Domain& d) {
  switch (d.kind) {
    case Kind::Sphere: return 4.0 / 3.0 * kPi * d.a * d.a * d.a;
    case Kind::Ellipsoid: return 4.0 / 3.0 * kPi * d.a * d.b * d.c;
    case Kind::Torus: return 2.0 * kPi * kPi * d.a * d.b * d.b;
  }
  return 0;
}

// Analytic area; the ellipsoid has no closed form and is integrated over the (theta, phi)
// parametrisation by a midpoint rule that is spectrally accurate in phi.
inline double analytic_area(const Domain& d) {
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

// Circumcentre of a 3D triangle; writes the circumradius.
inline V3 circumcentre(const V3& a, const V3& b, const V3& c, double* radius) {
  const V3 u = sub(b, a), v = sub(c, a), w = cross(u, v);
  const double ww = dot(w, w);
  const V3 s = mul(add(mul(cross(v, w), dot(u, u)), mul(cross(w, u), dot(v, v))), 1.0 / (2.0 * ww));
  *radius = norm(s);
  return add(a, s);
}

}  // namespace cgal_master::wave_e::implicit
