#include "kernel_query_set.h"

#include "../artifact_io.h"
#include "../wave_c/wave_c_common.h"

#include <cctype>
#include <set>

namespace cgal_master::kernel_ops {
namespace {

constexpr std::int64_t kLimit = std::int64_t(1) << 53;

[[noreturn]] void input_error(const std::string& code, const std::string& message) {
  throw WorkerError("INPUT_ERROR", code, message);
}

struct Shape {
  int dimension;
  std::size_t points;  // 0 for affine transformations
  bool squared_radius;
  std::size_t rows;     // affine matrix rows (0 otherwise)
};

const std::map<std::string, Shape>& shapes() {
  static const std::map<std::string, Shape> table = {
      {"Point_2", {2, 1, false, 0}},         {"Vector_2", {2, 1, false, 0}},
      {"Segment_2", {2, 2, false, 0}},       {"Line_2", {2, 2, false, 0}},
      {"Ray_2", {2, 2, false, 0}},           {"Triangle_2", {2, 3, false, 0}},
      {"Circle_2", {2, 1, true, 0}},         {"Iso_rectangle_2", {2, 2, false, 0}},
      {"Aff_transformation_2", {2, 0, false, 2}},
      {"Point_3", {3, 1, false, 0}},         {"Vector_3", {3, 1, false, 0}},
      {"Segment_3", {3, 2, false, 0}},       {"Line_3", {3, 2, false, 0}},
      {"Ray_3", {3, 2, false, 0}},           {"Plane_3", {3, 3, false, 0}},
      {"Triangle_3", {3, 3, false, 0}},      {"Tetrahedron_3", {3, 4, false, 0}},
      {"Sphere_3", {3, 1, true, 0}},         {"Iso_cuboid_3", {3, 2, false, 0}},
      {"Aff_transformation_3", {3, 0, false, 3}}};
  return table;
}

std::int64_t append_digit(std::int64_t value, char digit, const std::string& context) {
  value = value * 10 + (digit - '0');
  if (value >= kLimit) input_error("RATIONAL_OUT_OF_RANGE", context + " exceeds 2^53");
  return value;
}

// Grammar: -?D+(\.D+)? | -?D+/D+ ; numerator and denominator below 2^53.
Rational parse_rational(const Json& value, const std::string& context) {
  if (!value.is_string()) input_error("SCHEMA_MISMATCH", context + " must be a decimal or p/q string");
  const auto text = value.get<std::string>();
  std::size_t position = 0;
  bool negative = false;
  if (position < text.size() && text[position] == '-') {
    negative = true;
    ++position;
  }
  auto digits = [&](std::int64_t& out, std::size_t& count) {
    const std::size_t start = position;
    while (position < text.size() && std::isdigit(static_cast<unsigned char>(text[position]))) {
      out = append_digit(out, text[position], context);
      ++position;
    }
    count = position - start;
  };
  Rational result;
  std::size_t count = 0;
  digits(result.numerator, count);
  if (count == 0) input_error("MALFORMED_RATIONAL", context + " is not a decimal or p/q string");
  if (position < text.size() && text[position] == '.') {
    ++position;
    const std::size_t start = position;
    while (position < text.size() && std::isdigit(static_cast<unsigned char>(text[position]))) {
      result.numerator = append_digit(result.numerator, text[position], context);
      result.denominator = append_digit(result.denominator, '0', context);
      ++position;
    }
    if (position == start) input_error("MALFORMED_RATIONAL", context + " has an empty fraction");
  } else if (position < text.size() && text[position] == '/') {
    ++position;
    std::int64_t denominator = 0;
    digits(denominator, count);
    if (count == 0 || denominator == 0) {
      input_error("MALFORMED_RATIONAL", context + " has an invalid denominator");
    }
    result.denominator = denominator;
  }
  if (position != text.size()) input_error("MALFORMED_RATIONAL", context + " has trailing characters");
  if (negative) result.numerator = -result.numerator;
  return result;
}

Coordinates parse_coordinates(const Json& value, int dimension, const std::string& context) {
  if (!value.is_array() || value.size() != static_cast<std::size_t>(dimension)) {
    input_error("SCHEMA_MISMATCH", context + " must have " + std::to_string(dimension) + " coordinates");
  }
  Coordinates result;
  for (std::size_t i = 0; i < value.size(); ++i) {
    result.push_back(parse_rational(value[i], context + "[" + std::to_string(i) + "]"));
  }
  return result;
}

void require_keys(const Json& value, std::initializer_list<const char*> keys, const std::string& context) {
  if (!value.is_object()) input_error("SCHEMA_MISMATCH", context + " must be an object");
  std::set<std::string> expected(keys.begin(), keys.end());
  std::set<std::string> actual;
  for (const auto& item : value.items()) actual.insert(item.key());
  if (actual != expected) input_error("SCHEMA_MISMATCH", context + " has missing or unexpected keys");
}

bool valid_identifier(const std::string& text) {
  if (text.empty() || text.size() > 64) return false;
  for (char c : text) {
    if (!std::isalnum(static_cast<unsigned char>(c)) && c != '_' && c != '-') return false;
  }
  return true;
}

}  // namespace

const Primitive& QuerySet::at(const std::string& id) const {
  const auto found = index.find(id);
  if (found == index.end()) input_error("UNKNOWN_PRIMITIVE", "Query names an unknown primitive: " + id);
  return primitives[found->second];
}

std::string kernel_type_name(const std::string& kernel) {
  if (kernel == kSimpleCartesian) return "CGAL::Simple_cartesian<double>";
  if (kernel == kCartesian) return "CGAL::Cartesian<double>";
  if (kernel == kEpick) return "CGAL::Exact_predicates_inexact_constructions_kernel";
  if (kernel == kEpeck) return "CGAL::Exact_predicates_exact_constructions_kernel";
  throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "Unknown kernel " + kernel);
}

bool kernel_has_exact_predicates(const std::string& kernel) {
  return kernel == kEpick || kernel == kEpeck;
}

bool kernel_has_exact_constructions(const std::string& kernel) { return kernel == kEpeck; }

bool kernel_uses_double_input(const std::string& kernel) { return kernel != kEpeck; }

QuerySet read_query_set(const ArtifactInput& input) {
  if (input.type != "KernelQuerySet") {
    throw WorkerError("TYPE_ERROR", "INPUT_TYPE_MISMATCH",
                      "Expected input type KernelQuerySet, received " + input.type);
  }
  if (input.format != "json") {
    throw WorkerError("TYPE_ERROR", "INPUT_FORMAT_MISMATCH", "KernelQuerySet must be json");
  }
  if (input.unit != "mm" && input.unit != "cm" && input.unit != "m") {
    throw WorkerError("TYPE_ERROR", "UNSUPPORTED_UNIT", "Geometry unit must be one of: mm, cm, m");
  }
  Json value;
  try {
    value = Json::parse(read_verified_input_bytes(input));
  } catch (const nlohmann::json::exception&) {
    input_error("MALFORMED_JSON", "KernelQuerySet must be valid JSON");
  }
  require_keys(value, {"primitives", "queries"}, "KernelQuerySet");
  const auto& primitives = value.at("primitives");
  const auto& queries = value.at("queries");
  if (!primitives.is_array() || primitives.empty() || primitives.size() > kMaximumPrimitives) {
    input_error("SCHEMA_MISMATCH", "KernelQuerySet primitives must be a bounded nonempty array");
  }
  if (!queries.is_array() || queries.size() > kMaximumQueries) {
    input_error("SCHEMA_MISMATCH", "KernelQuerySet queries must be a bounded array");
  }
  QuerySet result;
  for (std::size_t i = 0; i < primitives.size(); ++i) {
    const auto& item = primitives[i];
    const std::string context = "primitive " + std::to_string(i);
    if (!item.is_object() || !item.contains("kind") || !item.at("kind").is_string()) {
      input_error("SCHEMA_MISMATCH", context + " needs a kind");
    }
    Primitive primitive;
    primitive.kind = item.at("kind").get<std::string>();
    const auto shape = shapes().find(primitive.kind);
    if (shape == shapes().end()) input_error("UNSUPPORTED_PRIMITIVE", context + " kind is not supported");
    primitive.dimension = shape->second.dimension;
    if (shape->second.rows != 0) {
      require_keys(item, {"id", "kind", "matrix"}, context);
      const auto& matrix = item.at("matrix");
      if (!matrix.is_array() || matrix.size() != shape->second.rows) {
        input_error("SCHEMA_MISMATCH", context + " matrix has the wrong number of rows");
      }
      for (std::size_t r = 0; r < matrix.size(); ++r) {
        primitive.matrix.push_back(parse_coordinates(matrix[r], primitive.dimension + 1,
                                                     context + " matrix row " + std::to_string(r)));
      }
    } else {
      if (shape->second.squared_radius) {
        require_keys(item, {"id", "kind", "points", "squared_radius"}, context);
        primitive.squared_radius = parse_rational(item.at("squared_radius"), context + " squared_radius");
        if (primitive.squared_radius.numerator < 0) {
          input_error("NEGATIVE_SQUARED_RADIUS", context + " squared_radius must be non-negative");
        }
      } else {
        require_keys(item, {"id", "kind", "points"}, context);
      }
      const auto& points = item.at("points");
      if (!points.is_array() || points.size() != shape->second.points) {
        input_error("SCHEMA_MISMATCH", context + " has the wrong number of points");
      }
      for (std::size_t p = 0; p < points.size(); ++p) {
        primitive.points.push_back(parse_coordinates(points[p], primitive.dimension,
                                                     context + " point " + std::to_string(p)));
      }
    }
    if (!item.at("id").is_string() || !valid_identifier(item.at("id").get<std::string>())) {
      input_error("SCHEMA_MISMATCH", context + " id must be 1-64 characters [A-Za-z0-9_-]");
    }
    primitive.id = item.at("id").get<std::string>();
    if (!result.index.emplace(primitive.id, result.primitives.size()).second) {
      input_error("DUPLICATE_PRIMITIVE", "Duplicate primitive id " + primitive.id);
    }
    result.primitives.push_back(std::move(primitive));
  }
  std::set<std::string> query_ids;
  for (std::size_t i = 0; i < queries.size(); ++i) {
    const auto& item = queries[i];
    const std::string context = "query " + std::to_string(i);
    require_keys(item, {"id", "query", "arguments"}, context);
    Query query;
    if (!item.at("id").is_string() || !valid_identifier(item.at("id").get<std::string>()) ||
        !item.at("query").is_string() || !item.at("arguments").is_array() ||
        item.at("arguments").empty() || item.at("arguments").size() > 4) {
      input_error("SCHEMA_MISMATCH", context + " needs an id, a query name and 1-4 arguments");
    }
    query.id = item.at("id").get<std::string>();
    query.query = item.at("query").get<std::string>();
    if (!query_ids.insert(query.id).second) input_error("DUPLICATE_QUERY", "Duplicate query id " + query.id);
    for (const auto& argument : item.at("arguments")) {
      if (!argument.is_string()) input_error("SCHEMA_MISMATCH", context + " arguments must be ids");
      const auto name = argument.get<std::string>();
      result.at(name);
      query.arguments.push_back(name);
    }
    result.queries.push_back(std::move(query));
  }
  return result;
}

std::string kernel_parameter(const Request& request, bool allow_inexact_predicates) {
  require_parameter_names(request, {"kernel"});
  const auto& value = request.parameters.at("kernel");
  if (value.is_string()) {
    const auto text = value.get<std::string>();
    if (text == kEpick || text == kEpeck) return text;
    if (allow_inexact_predicates && (text == kSimpleCartesian || text == kCartesian)) return text;
  }
  throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                    allow_inexact_predicates
                        ? "kernel must be simple_cartesian_double, cartesian_double, epick or epeck"
                        : "kernel must be epick or epeck for this operation");
}

void require_inputs(const Request& request, std::size_t count, const std::string& operation) {
  wave_c::require_input_count(request, count, operation);
}

void require_parameter_names(const Request& request, std::initializer_list<const char*> names) {
  wave_c::require_parameters(request, names);
}

Json write_report(const Request& request, const Json& report) {
  return wave_c::write_json_output(request, "analysis", "KernelReport", "none", report);
}

Json finish_kernel_validation(const Request& request, const std::string& validator, Json report) {
  return wave_c::finish_validation(request, validator, std::move(report));
}

Json read_kernel_report(const ArtifactInput& input, const std::string& kind) {
  return wave_c::read_report(input, "KernelReport", "report_kind", kind);
}

void precondition(const std::string& code, const std::string& message) {
  throw WorkerError("PRECONDITION_FAILED", code, message);
}

void validation_failure(const std::string& code, const std::string& message) {
  wave_c::fail_validation(code, message);
}

OperationDefinition kernel_definition(std::string id, std::vector<std::string> inputs,
                                      std::string output, std::string role,
                                      std::function<Json(const Request&)> execute, Json info) {
  OperationDefinition definition{std::move(id),   1, std::move(inputs), std::move(output),
                                 std::move(role), std::move(execute)};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel = "selected_by_parameter:kernel";
  definition.dependencies = {"Kernel_23"};
  definition.info = std::move(info);
  return definition;
}

}  // namespace cgal_master::kernel_ops
