#include "protocol.h"

#include <algorithm>
#include <cctype>
#include <limits>
#include <regex>

namespace cgal_master {
namespace {

const std::regex kIdentifier("^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$");
const std::regex kSha256("^[0-9a-f]{64}$");

std::string required_string(const Json& object, const char* key) {
  if (!object.contains(key) || !object.at(key).is_string()) {
    throw WorkerError("INVALID_REQUEST", "MISSING_OR_INVALID_FIELD",
                      std::string("Field '") + key + "' must be a string");
  }
  return object.at(key).get<std::string>();
}

std::uint64_t required_positive_uint(const Json& object, const char* key) {
  if (!object.contains(key) || !object.at(key).is_number_unsigned()) {
    throw WorkerError("INVALID_REQUEST", "MISSING_OR_INVALID_FIELD",
                      std::string("Field '") + key +
                          "' must be a positive unsigned integer");
  }
  const auto value = object.at(key).get<std::uint64_t>();
  if (value == 0) {
    throw WorkerError("INVALID_REQUEST", "MISSING_OR_INVALID_FIELD",
                      std::string("Field '") + key + "' must be positive");
  }
  return value;
}

void require_identifier(const std::string& value, const char* field) {
  if (!std::regex_match(value, kIdentifier)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_IDENTIFIER",
                      std::string("Field '") + field +
                          "' contains an invalid identifier");
  }
}

}  // namespace

WorkerError::WorkerError(std::string error_class_value, std::string code_value,
                         std::string message, bool recoverable_value,
                         std::vector<std::string> suggestions)
    : std::runtime_error(std::move(message)),
      error_class(std::move(error_class_value)),
      code(std::move(code_value)),
      recoverable(recoverable_value),
      suggested_operations(std::move(suggestions)) {}

Request parse_request(const Json& value) {
  if (!value.is_object()) {
    throw WorkerError("INVALID_REQUEST", "REQUEST_NOT_OBJECT",
                      "Request must be a JSON object");
  }
  Request request;
  if (!value.contains("protocol") || !value.at("protocol").is_number_integer() ||
      value.at("protocol").get<int>() != 1) {
    throw WorkerError("INVALID_REQUEST", "UNSUPPORTED_PROTOCOL",
                      "Only protocol 1 is supported");
  }
  request.protocol = 1;
  request.request_id = required_string(value, "request_id");
  require_identifier(request.request_id, "request_id");
  request.operation = required_string(value, "operation");
  require_identifier(request.operation, "operation");
  request.kernel = required_string(value, "kernel");
  if (request.kernel != "exact_constructions" &&
      request.kernel != "package_recommended") {
    throw WorkerError("UNSUPPORTED", "UNSUPPORTED_KERNEL",
                      "Unsupported kernel policy: " + request.kernel, false);
  }

  if (!value.contains("inputs") || !value.at("inputs").is_array()) {
    throw WorkerError("INVALID_REQUEST", "MISSING_OR_INVALID_FIELD",
                      "Field 'inputs' must be an array");
  }
  for (const auto& item : value.at("inputs")) {
    if (!item.is_object()) {
      throw WorkerError("INVALID_REQUEST", "INVALID_INPUT",
                        "Every input must be an object");
    }
    ArtifactInput input;
    input.artifact_id = required_string(item, "artifact_id");
    require_identifier(input.artifact_id, "artifact_id");
    input.type = required_string(item, "type");
    input.unit = required_string(item, "unit");
    input.format = required_string(item, "format");
    const auto path_text = required_string(item, "path");
    input.path = std::filesystem::u8path(path_text);
    if (!input.path.is_absolute()) {
      throw WorkerError("INVALID_REQUEST", "INPUT_PATH_NOT_ABSOLUTE",
                        "Input paths must be absolute");
    }
    input.sha256 = required_string(item, "sha256");
    std::transform(input.sha256.begin(), input.sha256.end(), input.sha256.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    if (!std::regex_match(input.sha256, kSha256)) {
      throw WorkerError("INVALID_REQUEST", "INVALID_SHA256",
                        "Input sha256 must contain 64 hexadecimal characters");
    }
    request.inputs.push_back(std::move(input));
  }

  if (!value.contains("parameters") || !value.at("parameters").is_object()) {
    throw WorkerError("INVALID_REQUEST", "MISSING_OR_INVALID_FIELD",
                      "Field 'parameters' must be an object");
  }
  request.parameters = value.at("parameters");

  request.output_dir =
      std::filesystem::u8path(required_string(value, "output_dir"));
  if (!request.output_dir.is_absolute()) {
    throw WorkerError("INVALID_REQUEST", "OUTPUT_PATH_NOT_ABSOLUTE",
                      "output_dir must be absolute");
  }

  if (!value.contains("limits") || !value.at("limits").is_object()) {
    throw WorkerError("INVALID_REQUEST", "MISSING_OR_INVALID_FIELD",
                      "Field 'limits' must be an object");
  }
  request.limits.wall_time_ms =
      required_positive_uint(value.at("limits"), "wall_time_ms");
  request.limits.memory_mb =
      required_positive_uint(value.at("limits"), "memory_mb");
  return request;
}

Json success_result(const Request& request, Json outputs, Json metrics,
                    Json diagnostics) {
  return Json{{"protocol", 1},
              {"request_id", request.request_id},
              {"status", "ok"},
              {"outputs", std::move(outputs)},
              {"metrics", std::move(metrics)},
              {"diagnostics", std::move(diagnostics)}};
}

Json error_result(const std::string& request_id, const WorkerError& error) {
  return Json{{"protocol", 1},
              {"request_id", request_id},
              {"status", "error"},
              {"outputs", Json::array()},
              {"metrics", Json::object()},
              {"diagnostics", Json::array()},
              {"error",
               {{"class", error.error_class},
                {"code", error.code},
                {"message", error.what()},
                {"recoverable", error.recoverable},
                {"suggested_operations", error.suggested_operations}}}};
}

Json internal_error_result(const std::string& request_id,
                           const std::string& message) {
  return error_result(
      request_id,
      WorkerError("INTERNAL", "UNEXPECTED_FAILURE", message, false));
}

std::string request_id_if_valid(const Json& value) {
  if (value.is_object() && value.contains("request_id") &&
      value.at("request_id").is_string()) {
    const auto candidate = value.at("request_id").get<std::string>();
    if (std::regex_match(candidate, kIdentifier)) return candidate;
  }
  return "";
}

}  // namespace cgal_master
