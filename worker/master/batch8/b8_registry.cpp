#include "b8_common.h"

namespace cgal_master::batch8 {

std::vector<OperationDefinition> decomposition_skeleton_validators();
std::vector<OperationDefinition> parameterization_validators();

std::vector<OperationDefinition> validator_operations() {
  auto result = decomposition_skeleton_validators();
  for (auto& operation : parameterization_validators()) result.push_back(std::move(operation));
  return result;
}

}  // namespace cgal_master::batch8
