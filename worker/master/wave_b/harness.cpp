// Local Wave B verification harness. The production worker registers the same
// operation definitions through worker/master/operation.cpp.
#include "wave_b_operations.h"

#include "../protocol.h"

#include <iostream>
#include <string>
#include <vector>

int main() {
  const std::vector<cgal_master::OperationDefinition> operations = {
      cgal_master::wave_b::remove_outliers_operation(),
      cgal_master::wave_b::grid_simplify_operation(),
      cgal_master::wave_b::random_simplify_operation(),
      cgal_master::wave_b::hierarchy_simplify_operation(),
      cgal_master::wave_b::jet_smooth_operation(),
      cgal_master::wave_b::estimate_normals_operation(),
      cgal_master::wave_b::orient_normals_mst_operation(),
      cgal_master::wave_b::pointset_basic_validator_operation(),
      cgal_master::wave_b::pointset_subset_validator_operation(),
      cgal_master::wave_b::pointset_smoothed_validator_operation(),
      cgal_master::wave_b::pointset_normals_estimated_validator_operation(),
      cgal_master::wave_b::pointset_normals_oriented_validator_operation()};
  std::string line;
  if (!std::getline(std::cin, line)) return 2;
  std::string request_id;
  try {
    const auto raw = cgal_master::Json::parse(line);
    request_id = cgal_master::request_id_if_valid(raw);
    const auto request = cgal_master::parse_request(raw);
    for (const auto& operation : operations) {
      if (operation.id == request.operation) {
        std::cout << operation.execute(request).dump() << '\n';
        return 0;
      }
    }
    std::cout << cgal_master::error_result(
                     request.request_id,
                     cgal_master::WorkerError("UNSUPPORTED_ADAPTER", "UNKNOWN_OPERATION",
                                               "Wave B operation is not registered"))
                     .dump()
              << '\n';
    return 0;
  } catch (const cgal_master::WorkerError& error) {
    std::cout << cgal_master::error_result(request_id, error).dump() << '\n';
  } catch (const std::exception& error) {
    std::cout << cgal_master::internal_error_result(request_id, error.what()).dump() << '\n';
  }
  return 0;
}
