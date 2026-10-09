#pragma once
// Query / mesh-processing family additions (7.2.04, 7.3.02, 7.3.08, 7.5.05,
// 7.8.06, 7.13.05): strict input readers and report helpers shared by the CGAL
// producers (query_operations.cpp) and the independent validators
// (query_validators.cpp). This header includes no CGAL header so that the
// validators can use it without touching the packages they check.

#include "../operation.h"
#include "../protocol.h"

#include <gmpxx.h>

#include <array>
#include <cstddef>
#include <functional>
#include <initializer_list>
#include <string>
#include <vector>

namespace cgal_master::query_ops {

using Q = mpq_class;
using V2 = std::array<double, 2>;
using V3 = std::array<double, 3>;

inline constexpr std::size_t kMaximumQueryFaces = 20000;
inline constexpr std::size_t kMaximumQueries = 2000;
inline constexpr std::size_t kMaximumSubdivisionInputFaces = 2000;
inline constexpr std::size_t kMaximumSubdivisionOutputFaces = 60000;
inline constexpr std::size_t kMaximumSubdivisionSteps = 3;
inline constexpr std::size_t kMaximumPolygonVertices = 200;

struct RawMesh {
  std::vector<V3> vertices;
  std::vector<std::vector<std::size_t>> faces;
};

struct RayItem {
  V3 origin;
  V3 direction;
};

// Strict OFF reader (own parser, no CGAL algorithm) for the accepted types.
RawMesh read_raw_mesh(const ArtifactInput& input, std::initializer_list<const char*> types);
std::vector<V3> read_points3(const ArtifactInput& input);
std::vector<RayItem> read_rays(const ArtifactInput& input);
std::vector<V2> read_points2(const ArtifactInput& input);
std::vector<V2> read_polygon(const ArtifactInput& input);

// Exact rational conversions.
Q exact_of(double value);
std::string q_text(const Q& value);
// Strict canonical "p" or "p/q" string from a report.
Q reported_rational(const Json& value, const std::string& context);

// Parameter and input checks (wrappers over the shared helpers).
void require_inputs(const Request& request, std::size_t count, const std::string& operation);
void require_parameter_names(const Request& request, std::initializer_list<const char*> required,
                             std::initializer_list<const char*> optional = {});
std::size_t integer_parameter(const Request& request, const char* name, std::size_t minimum,
                              std::size_t maximum);
std::string enum_parameter(const Request& request, const char* name,
                           std::initializer_list<const char*> allowed);
// TypedLength parameter normalized to the artifact unit (finite, any sign).
double signed_length_parameter(const Request& request, const char* name, const std::string& unit);
// Array of exactly three finite numbers.
V3 vector_parameter(const Request& request, const char* name);
void require_same_unit(const ArtifactInput& first, const ArtifactInput& second);

[[noreturn]] void precondition(const std::string& code, const std::string& message);
[[noreturn]] void validation_failure(const std::string& code, const std::string& message);

// Reports.
Json write_report(const Request& request, const std::string& type, const Json& report);
Json read_report(const ArtifactInput& input, const std::string& type, const std::string& kind_key,
                 const std::string& kind);
Json finish_validation(const Request& request, const std::string& validator, Json report);
// Writes an OFF file (17 significant digits) and returns the geometry output record.
Json write_off_output(const Request& request, const std::vector<V3>& vertices,
                      const std::vector<std::vector<std::size_t>>& faces, const std::string& type,
                      const std::string& unit);

OperationDefinition query_definition(std::string id, std::vector<std::string> inputs,
                                     std::string output, std::string role,
                                     std::function<Json(const Request&)> execute,
                                     std::vector<std::string> dependencies, std::string kernel,
                                     Json info);

std::vector<OperationDefinition> producer_operations();
std::vector<OperationDefinition> validator_operations();

}  // namespace cgal_master::query_ops
