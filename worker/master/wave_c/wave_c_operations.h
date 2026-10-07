#pragma once

#include "../operation.h"

#include <vector>

namespace cgal_master::wave_c {

// All Wave C transforms, analyses and validators in registration order.
std::vector<OperationDefinition> operations();

}  // namespace cgal_master::wave_c
