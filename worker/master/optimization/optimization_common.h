#pragma once
// Optimization / numerical-geometry family (7.15): strict input readers and
// shared report helpers. This header includes no CGAL header so that the
// independent validators (optimization_validators.cpp) can use it without
// touching the CGAL packages they check (QP_solver, Interpolation,
// Surface_mesh_approximation, Matrix_search).

#include "../operation.h"
#include "../protocol.h"

#include <gmpxx.h>

#include <array>
#include <cstddef>
#include <functional>
#include <initializer_list>
#include <string>
#include <vector>

namespace cgal_master::optimization_ops {

using Q = mpq_class;

inline constexpr std::size_t kMaximumVariables = 12;
inline constexpr std::size_t kMaximumConstraints = 64;
inline constexpr std::size_t kMaximumSites = 128;
inline constexpr std::size_t kMaximumInterpolationQueries = 32;
inline constexpr std::size_t kMaximumLinePoints = 2000;
inline constexpr std::size_t kMaximumApproximationFaces = 20000;
inline constexpr std::size_t kMaximumProxies = 200;
inline constexpr std::size_t kMaximumIterations = 100;

// ---- 7.15.01 QuadraticProgram -------------------------------------------------
// minimize x^T D x + c^T x + c0 subject to A x (<=,=,>=) b and l <= x <= u.
enum class Relation { kLess, kEqual, kGreater };

struct Constraint {
  std::vector<Q> coefficients;
  Relation relation = Relation::kLess;
  Q rhs;
};

struct Bound {
  bool finite = false;
  Q value;
};

struct QuadraticProgramData {
  std::size_t variables = 0;
  std::vector<Constraint> constraints;
  std::vector<Bound> lower;
  std::vector<Bound> upper;
  std::vector<Q> c;
  Q c0;
  std::vector<std::vector<Q>> d;  // symmetric n x n (objective term x^T D x)
  bool d_is_zero = true;
};

// ---- 7.15.02 InterpolationData2 ----------------------------------------------
struct Site {
  std::array<Q, 2> point;
  Q value;
  std::array<Q, 2> gradient;
};

struct InterpolationData {
  std::vector<Site> sites;
  std::vector<std::array<Q, 2>> queries;
};

// ---- 7.15.03 TriangleSurfaceMesh (double coordinates) -------------------------
struct MeshData {
  std::vector<std::array<double, 3>> vertices;
  std::vector<std::array<std::size_t, 3>> faces;
};

const char* relation_name(Relation relation);

QuadraticProgramData read_quadratic_program(const ArtifactInput& input);
InterpolationData read_interpolation_data(const ArtifactInput& input);
std::vector<Q> read_point_set1(const ArtifactInput& input);
MeshData read_mesh(const ArtifactInput& input);

// Binary64 nearest to an input rational (inputs have |num|, den < 2^53).
double nearest_double(const Q& value);
// Exact rational of a finite binary64 value.
Q exact_of_double(double value);
std::string q_text(const Q& value);
// Strict canonical "p" or "p/q" string (arbitrary precision) from a report.
Q reported_rational(const Json& value, const std::string& context);

// Thin wrappers over the shared JSON artifact helpers.
void require_inputs(const Request& request, std::size_t count, const std::string& operation);
void require_parameter_names(const Request& request, std::initializer_list<const char*> required,
                             std::initializer_list<const char*> optional = {});
std::size_t integer_parameter(const Request& request, const char* name, std::size_t minimum,
                              std::size_t maximum);
std::string enum_parameter(const Request& request, const char* name,
                           std::initializer_list<const char*> allowed);
Json write_report(const Request& request, const Json& report);
Json finish_optimization_validation(const Request& request, const std::string& validator, Json report);
Json read_optimization_report(const ArtifactInput& input, const std::string& kind);
[[noreturn]] void precondition(const std::string& code, const std::string& message);
[[noreturn]] void validation_failure(const std::string& code, const std::string& message);

Json report_frame(const Request& request, const std::string& kind, Json parameters, Json results);
// Checks schema, operation, parameters and source identity; returns results.
Json check_report_frame(const Request& request, const Json& report, const std::string& operation,
                        const Json& parameters, Json& checks);

OperationDefinition optimization_definition(std::string id, std::vector<std::string> inputs,
                                            std::string output, std::string role,
                                            std::function<Json(const Request&)> execute,
                                            std::vector<std::string> dependencies, std::string kernel,
                                            Json info);

std::vector<OperationDefinition> transform_operations();
std::vector<OperationDefinition> validator_operations();

}  // namespace cgal_master::optimization_ops
