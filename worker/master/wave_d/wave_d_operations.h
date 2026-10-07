#pragma once

#include "../operation.h"

#include <vector>

namespace cgal_master::wave_d {

// All Wave D meshing / remeshing transforms and validators in registration order.
std::vector<OperationDefinition> operations();

}  // namespace cgal_master::wave_d
