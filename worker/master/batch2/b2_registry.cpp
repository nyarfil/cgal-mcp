#include "b2_registry.h"

namespace cgal_master::batch2 {

namespace {
void append(std::vector<OperationDefinition>& target, std::vector<OperationDefinition> source) {
  for (auto& operation : source) target.push_back(std::move(operation));
}
}  // namespace

std::vector<OperationDefinition> producer_operations() {
  std::vector<OperationDefinition> result;
  append(result, points_producer_operations());
  append(result, mesh_producer_operations());
  append(result, polygon_producer_operations());
  return result;
}

std::vector<OperationDefinition> validator_operations() {
  std::vector<OperationDefinition> result;
  append(result, points_validator_operations());
  append(result, mesh_validator_operations());
  append(result, polygon_validator_operations());
  return result;
}

}  // namespace cgal_master::batch2
