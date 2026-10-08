#pragma once

#include "../operation.h"

#include <vector>

namespace cgal_master::wave_e {

// All Wave E mesh-generation transforms and validators in registration order.
std::vector<OperationDefinition> operations();

// Per-family registrations combined by operations().
std::vector<OperationDefinition> surface_mesh_operations();

}  // namespace cgal_master::wave_e
