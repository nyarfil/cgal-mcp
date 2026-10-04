#pragma once

#include <nlohmann/json.hpp>

#include <cstdint>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>

namespace cgal_master {

using Json = nlohmann::json;

class WorkerError : public std::runtime_error {
 public:
  WorkerError(std::string error_class, std::string code, std::string message,
              bool recoverable = false,
              std::vector<std::string> suggested_operations = {});

  const std::string error_class;
  const std::string code;
  const bool recoverable;
  const std::vector<std::string> suggested_operations;
};

struct ArtifactInput {
  std::string artifact_id;
  std::string type;
  std::string unit;
  std::string format;
  std::filesystem::path path;
  std::string sha256;
};

struct Limits {
  std::uint64_t wall_time_ms = 0;
  std::uint64_t memory_mb = 0;
};

struct Request {
  int protocol = 0;
  std::string request_id;
  std::string operation;
  std::vector<ArtifactInput> inputs;
  Json parameters;
  std::filesystem::path output_dir;
  std::string kernel;
  Limits limits;
};

Request parse_request(const Json& value);
Json success_result(const Request& request, Json outputs, Json metrics,
                    Json diagnostics = Json::array());
Json error_result(const std::string& request_id, const WorkerError& error);
Json internal_error_result(const std::string& request_id,
                           const std::string& message);
std::string request_id_if_valid(const Json& value);

}  // namespace cgal_master
