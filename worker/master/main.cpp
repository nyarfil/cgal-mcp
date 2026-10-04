#include "operation.h"
#include "protocol.h"

#include <iostream>
#include <string>

int main(int argc, char** argv) {
  using namespace cgal_master;
  if (argc == 2 && std::string(argv[1]) == "--manifest") {
    std::cout << manifest().dump() << '\n';
    return 0;
  }
  if (argc != 1) {
    const auto response = error_result(
        "", WorkerError("INVALID_REQUEST", "INVALID_ARGUMENTS",
                         "Usage: cgal-master-worker [--manifest]"));
    std::cout << response.dump() << '\n';
    return 1;
  }

  Json parsed;
  std::string request_id;
  try {
    std::string line;
    if (!std::getline(std::cin, line) || line.empty()) {
      throw WorkerError("INVALID_REQUEST", "EMPTY_REQUEST",
                        "Expected one JSON request line");
    }
    parsed = Json::parse(line);
    request_id = request_id_if_valid(parsed);
    std::string trailing;
    while (std::getline(std::cin, trailing)) {
      if (trailing.find_first_not_of(" \t\r") != std::string::npos) {
        throw WorkerError("INVALID_REQUEST", "MULTIPLE_REQUESTS",
                          "Worker accepts one request per process");
      }
    }
    const auto request = parse_request(parsed);
    request_id = request.request_id;
    std::cout << dispatch(request).dump() << '\n';
    return 0;
  } catch (const WorkerError& error) {
    std::cout << error_result(request_id, error).dump() << '\n';
    return 0;
  } catch (const nlohmann::json::exception& error) {
    const WorkerError wrapped("INVALID_REQUEST", "MALFORMED_JSON",
                              std::string("Malformed JSON request: ") +
                                  error.what());
    std::cout << error_result(request_id, wrapped).dump() << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cout << internal_error_result(request_id, error.what()).dump() << '\n';
    return 1;
  } catch (...) {
    std::cout << internal_error_result(request_id, "Unknown worker failure").dump()
              << '\n';
    return 1;
  }
}
