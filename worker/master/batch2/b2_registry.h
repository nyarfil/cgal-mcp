#pragma once
// Batch-2 operations: average spacing and outlier removal (Point_set_processing_3), minimum
// bounding circle / sphere (Bounding_volumes), sharp-edge detection and segmentation,
// self-intersection (Polygon_mesh_processing), plane clip / split and corefinement
// (PMP_Boolean_operations) and Boolean polygon set operations (Boolean_set_operations_2).

#include "../operation.h"

#include <vector>

namespace cgal_master::batch2 {

std::vector<OperationDefinition> points_producer_operations();
std::vector<OperationDefinition> mesh_producer_operations();
std::vector<OperationDefinition> polygon_producer_operations();
std::vector<OperationDefinition> points_validator_operations();
std::vector<OperationDefinition> mesh_validator_operations();
std::vector<OperationDefinition> polygon_validator_operations();

std::vector<OperationDefinition> producer_operations();
std::vector<OperationDefinition> validator_operations();

}  // namespace cgal_master::batch2
