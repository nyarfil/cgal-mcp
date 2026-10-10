#include "b7_common.h"

namespace cgal_master::batch7 {

std::vector<OperationDefinition> bilateral_producers();
std::vector<OperationDefinition> smoothing_validators();

std::vector<OperationDefinition> producer_operations() { return bilateral_producers(); }
std::vector<OperationDefinition> validator_operations() { return smoothing_validators(); }

}  // namespace cgal_master::batch7
