#include "operation.h"
#include "protocol.h"

#include <CGAL/Random.h>

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <new>
#include <string>

namespace {

// Session protocol 1 (opt-in `--serve`): one JSONL request per line, one JSONL response
// per line, flushed. Control lines {"control":"ping"|"shutdown","request_id":...} support a
// supervisor health check. Process-global pseudo-random state is reset before every request so
// a reused process behaves like a fresh one; any failure that may leave the process state
// untrusted (bad_alloc, unexpected exception) answers and then exits so the host recycles it.
constexpr int kSessionProtocol = 1;

int serve() {
  using namespace cgal_master;
  std::uint64_t served = 0;
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line.find_first_not_of(" \t\r") == std::string::npos) continue;
    std::string request_id;
    Json response;
    try {
      const Json parsed = Json::parse(line);
      request_id = request_id_if_valid(parsed);
      if (parsed.is_object() && parsed.contains("control")) {
        const Json& control = parsed.at("control");
        if (control == "shutdown") return 0;
        if (control != "ping") {
          throw WorkerError("INVALID_REQUEST", "UNKNOWN_CONTROL",
                            "Unknown session control message");
        }
        std::cout << Json{{"protocol", 1}, {"session_protocol", kSessionProtocol},
                          {"request_id", request_id}, {"status", "pong"},
                          {"served", served}}.dump()
                  << std::endl;
        continue;
      }
      CGAL::get_default_random() = CGAL::Random();
      std::srand(1);
      const auto request = parse_request(parsed);
      request_id = request.request_id;
      response = dispatch(request);
    } catch (const WorkerError& error) {
      response = error_result(request_id, error);
    } catch (const nlohmann::json::exception& error) {
      response = error_result(request_id,
          WorkerError("INVALID_REQUEST", "MALFORMED_JSON",
                      std::string("Malformed JSON request: ") + error.what()));
    } catch (const std::bad_alloc&) {
      std::cerr << "bad_alloc: worker memory limit reached" << std::endl;
      std::cout << error_result(request_id,
                                WorkerError("RESOURCE_LIMIT", "MEMORY_LIMIT",
                                            "Worker exhausted its memory limit", false))
                       .dump()
                << std::endl;
      return 3;
    } catch (const std::exception& error) {
      std::cout << internal_error_result(request_id, error.what()).dump() << std::endl;
      return 1;
    } catch (...) {
      std::cout << internal_error_result(request_id, "Unknown worker failure").dump()
                << std::endl;
      return 1;
    }
    ++served;
    std::cout << response.dump() << std::endl;
  }
  return 0;
}

}  // namespace

int main(int argc, char** argv) {
  using namespace cgal_master;
  if (argc == 2 && std::string(argv[1]) == "--manifest") {
    std::cout << manifest().dump() << '\n';
    return 0;
  }
  if (argc == 2 && std::string(argv[1]) == "--serve") {
    return serve();
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
  } catch (const std::bad_alloc&) {
    // Memory cap (Job Object / rlimit) exhausted: report a structured resource limit, never a silent crash.
    std::cerr << "bad_alloc: worker memory limit reached" << std::endl;
    std::cout << error_result(request_id,
                              WorkerError("RESOURCE_LIMIT", "MEMORY_LIMIT",
                                          "Worker exhausted its memory limit", false))
                     .dump()
              << std::endl;
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
