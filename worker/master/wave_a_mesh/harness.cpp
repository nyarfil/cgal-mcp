#include "wave_a_mesh_operations.h"

#include "../protocol.h"

#include <CGAL/version.h>

#include <iostream>
#include <string>
#include <vector>

namespace {

std::vector<cgal_master::OperationDefinition> operations() {
  using namespace cgal_master::wave_a_mesh;
  return {inspect_pmp_operation(), connected_components_operation(),
          normals_operation(), measures_operation(), sharp_features_operation(),
          self_intersections_operation(),
          validate_pmp_inspection_report_operation(),
          validate_connected_components_report_operation(),
          validate_normals_report_operation(),
          validate_measures_report_operation(),
          validate_sharp_features_report_operation(),
          validate_self_intersections_report_operation()};
}

cgal_master::Json manifest() {
  cgal_master::Json declared = cgal_master::Json::array();
  for (const auto& operation : operations()) {
    declared.push_back({{"id", operation.id},
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
          {"actual_cgal_version", CGAL_VERSION_STR},
          {"build", {{"actual_cgal_version", CGAL_VERSION_STR},
                     {"source_kind", "official_release"}}},
          {"operations", std::move(declared)}};
}

}  // namespace

int main(int argc, char** argv) {
  if (argc == 2 && std::string(argv[1]) == "--manifest") {
    std::cout << manifest().dump() << '\n';
    return 0;
  }
  if (argc != 1) return 2;
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
    throw cgal_master::WorkerError("UNSUPPORTED", "UNKNOWN_OPERATION",
                                   "Wave A mesh operation is not registered");
  } catch (const cgal_master::WorkerError& error) {
    std::cout << cgal_master::error_result(request_id, error).dump() << '\n';
  } catch (const std::exception& error) {
    std::cout << cgal_master::internal_error_result(request_id, error.what()).dump()
              << '\n';
  }
  return 0;
}
