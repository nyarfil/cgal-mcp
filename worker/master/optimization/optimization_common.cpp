#include "optimization_common.h"

#include "../artifact_io.h"
#include "../wave_c/wave_c_common.h"

#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <set>

namespace cgal_master::optimization_ops {
namespace {

constexpr std::int64_t kLimit = std::int64_t(1) << 53;

[[noreturn]] void input_error(const std::string& code, const std::string& message) {
  throw WorkerError("INPUT_ERROR", code, message);
}

std::int64_t append_digit(std::int64_t value, char digit, const std::string& context) {
  value = value * 10 + (digit - '0');
  if (value >= kLimit) input_error("RATIONAL_OUT_OF_RANGE", context + " exceeds 2^53");
  return value;
}

// Grammar: -?D+(\.D+)? | -?D+/D+ ; numerator and denominator below 2^53.
Q parse_rational(const Json& value, const std::string& context) {
  if (!value.is_string()) input_error("SCHEMA_MISMATCH", context + " must be a decimal or p/q string");
  const auto text = value.get<std::string>();
  std::size_t position = 0;
  bool negative = false;
  if (position < text.size() && text[position] == '-') {
    negative = true;
    ++position;
  }
  std::int64_t numerator = 0, denominator = 1;
  const std::size_t start = position;
  while (position < text.size() && std::isdigit(static_cast<unsigned char>(text[position]))) {
    numerator = append_digit(numerator, text[position++], context);
  }
  if (position == start) input_error("MALFORMED_RATIONAL", context + " is not a decimal or p/q string");
  if (position < text.size() && text[position] == '.') {
    ++position;
    const std::size_t fraction = position;
    while (position < text.size() && std::isdigit(static_cast<unsigned char>(text[position]))) {
      numerator = append_digit(numerator, text[position++], context);
      denominator = append_digit(denominator, '0', context);
    }
    if (position == fraction) input_error("MALFORMED_RATIONAL", context + " has an empty fraction");
  } else if (position < text.size() && text[position] == '/') {
    ++position;
    const std::size_t digits = position;
    denominator = 0;
    while (position < text.size() && std::isdigit(static_cast<unsigned char>(text[position]))) {
      denominator = append_digit(denominator, text[position++], context);
    }
    if (position == digits || denominator == 0) {
      input_error("MALFORMED_RATIONAL", context + " has an invalid denominator");
    }
  }
  if (position != text.size()) input_error("MALFORMED_RATIONAL", context + " has trailing characters");
  // int64 does not convert to mpq_class portably (32-bit long on Windows).
  Q result((negative ? "-" : "") + std::to_string(numerator) + "/" + std::to_string(denominator), 10);
  result.canonicalize();
  return result;
}

void require_keys(const Json& value, std::initializer_list<const char*> keys, const std::string& context,
                  bool validation = false) {
  const auto fail = [&](const std::string& message) {
    if (validation) validation_failure("REPORT_SCHEMA_MISMATCH", message);
    input_error("SCHEMA_MISMATCH", message);
  };
  if (!value.is_object()) fail(context + " must be an object");
  std::set<std::string> expected(keys.begin(), keys.end());
  std::set<std::string> actual;
  for (const auto& item : value.items()) actual.insert(item.key());
  if (actual != expected) fail(context + " has missing or unexpected keys");
}

Json parse_input(const ArtifactInput& input, const std::string& type, bool length_unit) {
  if (input.type != type) {
    throw WorkerError("TYPE_ERROR", "INPUT_TYPE_MISMATCH",
                      "Expected input type " + type + ", received " + input.type);
  }
  if (input.format != "json") throw WorkerError("TYPE_ERROR", "INPUT_FORMAT_MISMATCH", type + " must be json");
  if (length_unit ? (input.unit != "mm" && input.unit != "cm" && input.unit != "m") : input.unit != "none") {
    throw WorkerError("TYPE_ERROR", "UNSUPPORTED_UNIT",
                      length_unit ? "Geometry unit must be one of: mm, cm, m"
                                  : type + " unit must be none");
  }
  try {
    return Json::parse(read_verified_input_bytes(input));
  } catch (const nlohmann::json::exception&) {
    input_error("MALFORMED_JSON", type + " must be valid JSON");
  }
}

std::vector<Q> rational_row(const Json& value, std::size_t size, const std::string& context) {
  if (!value.is_array() || value.size() != size) {
    input_error("SCHEMA_MISMATCH", context + " must have " + std::to_string(size) + " entries");
  }
  std::vector<Q> row;
  for (std::size_t i = 0; i < size; ++i) row.push_back(parse_rational(value[i], context + "[" + std::to_string(i) + "]"));
  return row;
}

Bound parse_bound(const Json& value, const std::string& context) {
  if (value.is_null()) return Bound{};
  return Bound{true, parse_rational(value, context)};
}

}  // namespace

const char* relation_name(Relation relation) {
  return relation == Relation::kLess ? "<=" : (relation == Relation::kEqual ? "=" : ">=");
}

QuadraticProgramData read_quadratic_program(const ArtifactInput& input) {
  const auto value = parse_input(input, "QuadraticProgram", false);
  require_keys(value, {"variables", "constraints", "bounds", "objective"}, "QuadraticProgram");
  const auto& variables = value.at("variables");
  if (!variables.is_number_unsigned() || variables.get<std::uint64_t>() < 1 ||
      variables.get<std::uint64_t>() > kMaximumVariables) {
    input_error("SCHEMA_MISMATCH", "QuadraticProgram variables must be 1.." + std::to_string(kMaximumVariables));
  }
  QuadraticProgramData result;
  result.variables = variables.get<std::size_t>();
  const auto n = result.variables;
  const auto& constraints = value.at("constraints");
  if (!constraints.is_array() || constraints.empty() || constraints.size() > kMaximumConstraints) {
    input_error("SCHEMA_MISMATCH", "QuadraticProgram constraints must be a bounded nonempty array");
  }
  for (std::size_t i = 0; i < constraints.size(); ++i) {
    const std::string context = "constraint " + std::to_string(i);
    require_keys(constraints[i], {"coefficients", "relation", "rhs"}, context);
    Constraint row;
    row.coefficients = rational_row(constraints[i].at("coefficients"), n, context + " coefficients");
    const auto& relation = constraints[i].at("relation");
    if (relation == "<=") row.relation = Relation::kLess;
    else if (relation == "=") row.relation = Relation::kEqual;
    else if (relation == ">=") row.relation = Relation::kGreater;
    else input_error("SCHEMA_MISMATCH", context + " relation must be <=, = or >=");
    row.rhs = parse_rational(constraints[i].at("rhs"), context + " rhs");
    result.constraints.push_back(std::move(row));
  }
  const auto& bounds = value.at("bounds");
  if (!bounds.is_array() || bounds.size() != n) input_error("SCHEMA_MISMATCH", "QuadraticProgram needs one bound per variable");
  for (std::size_t j = 0; j < n; ++j) {
    const std::string context = "bound " + std::to_string(j);
    require_keys(bounds[j], {"lower", "upper"}, context);
    result.lower.push_back(parse_bound(bounds[j].at("lower"), context + " lower"));
    result.upper.push_back(parse_bound(bounds[j].at("upper"), context + " upper"));
    if (result.lower[j].finite && result.upper[j].finite && result.lower[j].value > result.upper[j].value) {
      input_error("EMPTY_BOUNDS", context + " has lower > upper");
    }
  }
  const auto& objective = value.at("objective");
  require_keys(objective, {"c", "c0", "d"}, "objective");
  result.c = rational_row(objective.at("c"), n, "objective c");
  result.c0 = parse_rational(objective.at("c0"), "objective c0");
  const auto& d = objective.at("d");
  if (!d.is_array() || d.size() != n) input_error("SCHEMA_MISMATCH", "objective d must be an n x n matrix");
  for (std::size_t i = 0; i < n; ++i) result.d.push_back(rational_row(d[i], n, "objective d row " + std::to_string(i)));
  for (std::size_t i = 0; i < n; ++i) {
    for (std::size_t j = 0; j < n; ++j) {
      if (result.d[i][j] != result.d[j][i]) input_error("ASYMMETRIC_OBJECTIVE", "objective d must be symmetric");
      if (result.d[i][j] != 0) result.d_is_zero = false;
    }
  }
  return result;
}

InterpolationData read_interpolation_data(const ArtifactInput& input) {
  const auto value = parse_input(input, "InterpolationData2", true);
  require_keys(value, {"sites", "queries"}, "InterpolationData2");
  const auto& sites = value.at("sites");
  const auto& queries = value.at("queries");
  if (!sites.is_array() || sites.size() < 3 || sites.size() > kMaximumSites) {
    input_error("SCHEMA_MISMATCH", "InterpolationData2 needs 3.." + std::to_string(kMaximumSites) + " sites");
  }
  if (!queries.is_array() || queries.empty() || queries.size() > kMaximumInterpolationQueries) {
    input_error("SCHEMA_MISMATCH", "InterpolationData2 needs a bounded nonempty query array");
  }
  InterpolationData result;
  std::set<std::pair<Q, Q>> seen;
  for (std::size_t i = 0; i < sites.size(); ++i) {
    const std::string context = "site " + std::to_string(i);
    require_keys(sites[i], {"point", "value", "gradient"}, context);
    const auto point = rational_row(sites[i].at("point"), 2, context + " point");
    const auto gradient = rational_row(sites[i].at("gradient"), 2, context + " gradient");
    Site site{{point[0], point[1]}, parse_rational(sites[i].at("value"), context + " value"),
              {gradient[0], gradient[1]}};
    if (!seen.insert({site.point[0], site.point[1]}).second) input_error("DUPLICATE_SITE", context + " repeats a site");
    result.sites.push_back(std::move(site));
  }
  for (std::size_t i = 0; i < queries.size(); ++i) {
    const auto point = rational_row(queries[i], 2, "query " + std::to_string(i));
    result.queries.push_back({point[0], point[1]});
  }
  return result;
}

std::vector<Q> read_point_set1(const ArtifactInput& input) {
  const auto value = parse_input(input, "PointSet1", true);
  require_keys(value, {"points"}, "PointSet1");
  const auto& points = value.at("points");
  if (!points.is_array() || points.size() < 2 || points.size() > kMaximumLinePoints) {
    input_error("SCHEMA_MISMATCH", "PointSet1 needs 2.." + std::to_string(kMaximumLinePoints) + " points");
  }
  std::vector<Q> result;
  for (std::size_t i = 0; i < points.size(); ++i) result.push_back(parse_rational(points[i], "point " + std::to_string(i)));
  return result;
}

MeshData read_mesh(const ArtifactInput& input) {
  const auto mesh = wave_c::read_triangle_mesh(input);
  if (mesh.faces.empty() || mesh.faces.size() > kMaximumApproximationFaces) {
    precondition("MESH_SIZE_UNSUPPORTED",
                 "Mesh approximation needs 1.." + std::to_string(kMaximumApproximationFaces) + " faces");
  }
  MeshData result;
  result.vertices = mesh.vertices;
  result.faces = mesh.faces;
  return result;
}

double nearest_double(const Q& value) {
  // Input rationals are canonical with |num|, den < 2^53: both convert exactly and
  // the IEEE-754 division rounds the quotient to nearest.
  return mpz_get_d(value.get_num_mpz_t()) / mpz_get_d(value.get_den_mpz_t());
}

Q exact_of_double(double value) {
  if (!std::isfinite(value)) precondition("NONFINITE_RESULT", "A computed value is not finite");
  Q result;
  mpq_set_d(result.get_mpq_t(), value);
  result.canonicalize();
  return result;
}

std::string q_text(const Q& value) {
  Q copy(value);
  copy.canonicalize();
  return copy.get_str(10);
}

Q reported_rational(const Json& value, const std::string& context) {
  if (!value.is_string()) validation_failure("REPORT_VALUE_INVALID", context + " must be an exact rational string");
  const auto text = value.get<std::string>();
  if (text.empty() || text.size() > 4096) validation_failure("REPORT_VALUE_INVALID", context + " has an invalid length");
  std::size_t slash = 0;
  for (std::size_t i = 0; i < text.size(); ++i) {
    const char c = text[i];
    if (c == '-' && i == 0) continue;
    if (c == '/') {
      if (slash != 0) validation_failure("REPORT_VALUE_INVALID", context + " is malformed");
      slash = i;
      continue;
    }
    if (!std::isdigit(static_cast<unsigned char>(c))) validation_failure("REPORT_VALUE_INVALID", context + " is malformed");
  }
  Q result;
  if (mpq_set_str(result.get_mpq_t(), text.c_str(), 10) != 0 || mpz_sgn(result.get_den_mpz_t()) == 0) {
    validation_failure("REPORT_VALUE_INVALID", context + " is malformed");
  }
  Q canonical(result);
  canonical.canonicalize();
  if (canonical.get_str(10) != text) validation_failure("REPORT_VALUE_INVALID", context + " is not canonical");
  return canonical;
}

void require_inputs(const Request& request, std::size_t count, const std::string& operation) {
  wave_c::require_input_count(request, count, operation);
}

void require_parameter_names(const Request& request, std::initializer_list<const char*> required,
                             std::initializer_list<const char*> optional) {
  wave_c::require_parameters(request, required, optional);
}

std::size_t integer_parameter(const Request& request, const char* name, std::size_t minimum,
                              std::size_t maximum) {
  return wave_c::integer_parameter(request, name, minimum, maximum);
}

std::string enum_parameter(const Request& request, const char* name,
                           std::initializer_list<const char*> allowed) {
  return wave_c::enum_parameter(request, name, allowed);
}

Json write_report(const Request& request, const Json& report) {
  return wave_c::write_json_output(request, "analysis", "OptimizationReport", "none", report);
}

Json finish_optimization_validation(const Request& request, const std::string& validator, Json report) {
  return wave_c::finish_validation(request, validator, std::move(report));
}

Json read_optimization_report(const ArtifactInput& input, const std::string& kind) {
  return wave_c::read_report(input, "OptimizationReport", "report_kind", kind);
}

void precondition(const std::string& code, const std::string& message) {
  throw WorkerError("PRECONDITION_FAILED", code, message);
}

void validation_failure(const std::string& code, const std::string& message) {
  wave_c::fail_validation(code, message);
}

Json report_frame(const Request& request, const std::string& kind, Json parameters, Json results) {
  return Json{{"schema_version", 1},
              {"report_type", "OptimizationReport"},
              {"report_kind", kind},
              {"operation", request.operation},
              {"parameters", std::move(parameters)},
              {"source", {{"sha256", request.inputs[0].sha256}, {"unit", request.inputs[0].unit}}},
              {"results", std::move(results)}};
}

Json check_report_frame(const Request& request, const Json& report, const std::string& operation,
                        const Json& parameters, Json& checks) {
  require_keys(report, {"schema_version", "report_type", "report_kind", "operation", "parameters", "source",
                        "results"},
               "OptimizationReport", true);
  if (report.at("operation") != operation || report.at("parameters") != parameters) {
    validation_failure("PARAMETER_MISMATCH", "Report operation or parameters differ from the validated request");
  }
  checks["parameters_match"] = true;
  const auto& source = request.inputs[1];
  if (report.at("source") != Json{{"sha256", source.sha256}, {"unit", source.unit}}) {
    validation_failure("SOURCE_MISMATCH", "Report does not describe the validated source artifact");
  }
  checks["source_matches"] = true;
  if (!report.at("results").is_object()) validation_failure("REPORT_SCHEMA_MISMATCH", "results must be an object");
  return report.at("results");
}

OperationDefinition optimization_definition(std::string id, std::vector<std::string> inputs,
                                            std::string output, std::string role,
                                            std::function<Json(const Request&)> execute,
                                            std::vector<std::string> dependencies, std::string kernel,
                                            Json info) {
  OperationDefinition definition{std::move(id),   1, std::move(inputs), std::move(output),
                                 std::move(role), std::move(execute)};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel = std::move(kernel);
  definition.dependencies = std::move(dependencies);
  definition.info = std::move(info);
  return definition;
}

}  // namespace cgal_master::optimization_ops
