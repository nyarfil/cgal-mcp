#pragma once

#include "../operation.h"

namespace cgal_master::wave_b {

OperationDefinition remove_outliers_operation();
OperationDefinition grid_simplify_operation();
OperationDefinition random_simplify_operation();
OperationDefinition hierarchy_simplify_operation();
OperationDefinition jet_smooth_operation();
OperationDefinition estimate_normals_operation();
OperationDefinition orient_normals_mst_operation();
OperationDefinition pointset_basic_validator_operation();
OperationDefinition pointset_subset_validator_operation();
OperationDefinition pointset_smoothed_validator_operation();
OperationDefinition pointset_normals_estimated_validator_operation();
OperationDefinition pointset_normals_oriented_validator_operation();

}  // namespace cgal_master::wave_b
