#pragma once
// Geometry kernel family (7.1): strict KernelQuerySet reader and shared report
// helpers. This header deliberately includes no CGAL kernel header so that the
// independent validators (kernel_validators.cpp) can use it without touching
// the CGAL kernel functors they check.

#include "../operation.h"
#include "../protocol.h"

#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <map>
#include <string>
#include <vector>

namespace cgal_master::kernel_ops {

inline constexpr std::size_t kMaximumPrimitives = 10000;
inline constexpr std::size_t kMaximumQueries = 10000;

// Exact input scalar num/den with |num| < 2^53 and 0 < den < 2^53, so both are
// exactly representable in binary64 and num/den rounds correctly in IEEE-754.
struct Rational {
  std::int64_t numerator = 0;
  std::int64_t denominator = 1;
};

using Coordinates = std::vector<Rational>;

struct Primitive {
  std::string id;
  std::string kind;
  int dimension = 0;
  std::vector<Coordinates> points;          // every kind except Aff_transformation_*
  Rational squared_radius;                  // Circle_2 / Sphere_3 only
  std::vector<Coordinates> matrix;          // Aff_transformation_* only (rows)
};

struct Query {
  std::string id;
  std::string query;
  std::vector<std::string> arguments;
};

struct QuerySet {
  std::vector<Primitive> primitives;
  std::map<std::string, std::size_t> index;
  std::vector<Query> queries;

  const Primitive& at(const std::string& id) const;
};

// Kernel names accepted by the kernel family operations.
inline constexpr const char* kSimpleCartesian = "simple_cartesian_double";
inline constexpr const char* kCartesian = "cartesian_double";
inline constexpr const char* kEpick = "epick";
inline constexpr const char* kEpeck = "epeck";

std::string kernel_type_name(const std::string& kernel);
bool kernel_has_exact_predicates(const std::string& kernel);
bool kernel_has_exact_constructions(const std::string& kernel);
bool kernel_uses_double_input(const std::string& kernel);

QuerySet read_query_set(const ArtifactInput& input);
std::string kernel_parameter(const Request& request, bool allow_inexact_predicates);

// Thin wrappers over the shared JSON artifact helpers.
void require_inputs(const Request& request, std::size_t count, const std::string& operation);
void require_parameter_names(const Request& request, std::initializer_list<const char*> names);
Json write_report(const Request& request, const Json& report);
Json finish_kernel_validation(const Request& request, const std::string& validator, Json report);
Json read_kernel_report(const ArtifactInput& input, const std::string& kind);
[[noreturn]] void precondition(const std::string& code, const std::string& message);
[[noreturn]] void validation_failure(const std::string& code, const std::string& message);

OperationDefinition kernel_definition(std::string id, std::vector<std::string> inputs,
                                      std::string output, std::string role,
                                      std::function<Json(const Request&)> execute, Json info);

std::vector<OperationDefinition> transform_operations();
std::vector<OperationDefinition> validator_operations();

}  // namespace cgal_master::kernel_ops
