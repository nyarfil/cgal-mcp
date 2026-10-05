#pragma once

#include "../operation.h"

namespace cgal_master::spatial {

OperationDefinition aabb_closest_point_operation();
OperationDefinition validate_aabb_closest_point_operation();
OperationDefinition aabb_segment_candidates_operation();
OperationDefinition validate_aabb_segment_candidates_operation();

}  // namespace cgal_master::spatial
