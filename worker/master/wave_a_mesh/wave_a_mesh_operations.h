#pragma once

#include "../operation.h"

namespace cgal_master::wave_a_mesh {

OperationDefinition inspect_pmp_operation();
OperationDefinition connected_components_operation();
OperationDefinition normals_operation();
OperationDefinition measures_operation();
OperationDefinition sharp_features_operation();
OperationDefinition self_intersections_operation();

// Deterministic official-CGAL replay used by separately registered validators.
Json analysis_reference_report(const std::string& operation_id,
                               const Request& source_request);

OperationDefinition validate_pmp_inspection_report_operation();
OperationDefinition validate_connected_components_report_operation();
OperationDefinition validate_normals_report_operation();
OperationDefinition validate_measures_report_operation();
OperationDefinition validate_sharp_features_report_operation();
OperationDefinition validate_self_intersections_report_operation();

}  // namespace cgal_master::wave_a_mesh
