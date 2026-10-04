#pragma once

#include "../operation.h"

namespace cgal_master::wave_c_spatial {

OperationDefinition aabb_closest_point_operation();
OperationDefinition kdtree_range_operation();
OperationDefinition nearest_neighbors_operation();
OperationDefinition intersection_candidates_operation();
OperationDefinition bounding_box_operation();

OperationDefinition validate_aabb_closest_point_operation();
OperationDefinition validate_kdtree_range_operation();
OperationDefinition validate_nearest_neighbors_operation();
OperationDefinition validate_intersection_candidates_operation();
OperationDefinition validate_bounding_box_operation();

Json analysis_reference_report(const std::string& operation_id,
                               const Request& source_request);

}  // namespace cgal_master::wave_c_spatial
