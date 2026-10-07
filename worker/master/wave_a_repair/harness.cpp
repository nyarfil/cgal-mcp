#include "repair_operations.h"

#include "../protocol.h"

#include <iostream>
#include <string>
#include <vector>

namespace {

std::vector<cgal_master::OperationDefinition> operations() {
  auto result = cgal_master::wave_a_repair::repair_operations();
  auto validators = cgal_master::wave_a_repair::repair_validators();
  result.insert(result.end(), validators.begin(), validators.end());
  return result;
}

cgal_master::Json manifest() {
  auto entries = cgal_master::Json::array();
  for (const auto& operation : operations()) {
    entries.push_back({{"id", operation.id},
                       {"revision", operation.revision},
                       {"input_types", operation.input_types},
                       {"output_type", operation.output_type},
                       {"role", operation.role},
                       {"supported_kernels", operation.supported_kernels},
                       {"effective_kernel", operation.effective_kernel},
                       {"dependencies", operation.dependencies},
                       {"info", operation.info}});
  }
  return {{"protocol", 1},
          {"actual_cgal_version", "6.2.1"},
          {"build", {{"source_kind", "official_release"},
                      {"source_sha256", "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf"},
                      {"scope", "isolated_wave_a_repair_harness"}}},
          {"operations", std::move(entries)}};
}

}  // namespace

int main(int argc, char** argv) {
  if (argc == 2 && std::string(argv[1]) == "--manifest") {
    std::cout << manifest().dump() << '\n';
    return 0;
  }
  std::string line;
  if (!std::getline(std::cin, line)) return 2;
  std::string request_id;
  try {
    const auto raw = cgal_master::Json::parse(line);
    request_id = cgal_master::request_id_if_valid(raw);
    const auto request = cgal_master::parse_request(raw);
    for (const auto& operation : operations()) {
      if (operation.id == request.operation) {
        std::cout << operation.execute(request).dump() << '\n';
        return 0;
      }
    }
    std::cout << cgal_master::error_result(
        request.request_id,
        cgal_master::WorkerError("UNSUPPORTED_ADAPTER", "UNKNOWN_OPERATION",
                                 "Wave A repair operation is not registered")).dump() << '\n';
  } catch (const cgal_master::WorkerError& error) {
    std::cout << cgal_master::error_result(request_id, error).dump() << '\n';
  } catch (const std::exception& error) {
    std::cout << cgal_master::internal_error_result(request_id, error.what()).dump() << '\n';
  }
  return 0;
}
