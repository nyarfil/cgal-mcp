#include "b9_common.h"

#include <cmath>

namespace cgal_master::batch9 {

std::vector<OperationDefinition> sdf_producers();
std::vector<OperationDefinition> triangulation_producers();
std::vector<OperationDefinition> sdf_validators();
std::vector<OperationDefinition> triangulation_validators();

std::vector<OperationDefinition> producer_operations() {
  auto result = sdf_producers();
  for (auto& operation : triangulation_producers()) result.push_back(std::move(operation));
  return result;
}

std::vector<OperationDefinition> validator_operations() {
  auto result = sdf_validators();
  for (auto& operation : triangulation_validators()) result.push_back(std::move(operation));
  return result;
}

double finite_number(const Json& parameters, const char* name, double minimum, double maximum,
                     bool minimum_exclusive) {
  if (!parameters.contains(name)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " is required");
  }
  const auto& value = parameters.at(name);
  if (!value.is_number() || value.is_boolean() || !std::isfinite(value.get<double>())) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be a finite number");
  }
  const double number = value.get<double>();
  if (number > maximum || number < minimum || (minimum_exclusive && number <= minimum)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " is out of range");
  }
  return number;
}

std::vector<double> domain_min_parameter(const Json& parameters, std::size_t dimension) {
  const auto& value = parameters.at("domain_min");
  if (!value.is_array() || value.size() != dimension) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "domain_min must be an array of " + std::to_string(dimension) + " numbers");
  }
  std::vector<double> result;
  for (const auto& item : value) {
    if (!item.is_number() || item.is_boolean() || !std::isfinite(item.get<double>()) ||
        std::fabs(item.get<double>()) > 1e9) {
      throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "domain_min entries must be finite numbers");
    }
    result.push_back(item.get<double>());
  }
  return result;
}

double positive_length(const Json& parameters, const char* name, const std::string& unit) {
  const auto& value = parameters.at(name);
  if (!value.is_object() || value.size() != 2 || !value.contains("value") || !value.contains("unit") ||
      !value.at("unit").is_string() || !value.at("value").is_number() || value.at("value").is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be a TypedLength {value, unit}");
  }
  if (value.at("unit").get<std::string>() != unit) {
    throw WorkerError("TYPE_ERROR", "UNIT_MISMATCH", std::string(name) + " must be normalized to the artifact unit");
  }
  const double result = value.at("value").get<double>();
  if (!std::isfinite(result) || result <= 0 || result > 1e9) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be a positive finite length");
  }
  return result;
}

}  // namespace cgal_master::batch9
