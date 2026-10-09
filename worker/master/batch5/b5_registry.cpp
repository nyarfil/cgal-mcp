#include "b5_common.h"

namespace cgal_master::batch5 {
namespace {
void append(std::vector<OperationDefinition>& target, std::vector<OperationDefinition> source) {
  for (auto& operation : source) target.push_back(std::move(operation));
}
}  // namespace

std::vector<OperationDefinition> producer_operations() {
  std::vector<OperationDefinition> result;
  append(result, distance_producers());
  append(result, intersection_producers());
  return result;
}

std::vector<OperationDefinition> validator_operations() {
  std::vector<OperationDefinition> result;
  append(result, distance_validators());
  append(result, intersection_validators());
  return result;
}

}  // namespace cgal_master::batch5
