#pragma once

#include "../operation.h"

namespace cgal_master::wave_a_boolean {

OperationDefinition boolean_union_operation();
OperationDefinition boolean_intersection_operation();
OperationDefinition boolean_difference_operation();

OperationDefinition validate_boolean_union_operation();
OperationDefinition validate_boolean_intersection_operation();
OperationDefinition validate_boolean_difference_operation();

}  // namespace cgal_master::wave_a_boolean
