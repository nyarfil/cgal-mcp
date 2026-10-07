#pragma once

#include "../operation.h"

#include <array>
#include <string>
#include <vector>

namespace cgal_master::wave_a_repair {

enum class RepairKind {
  kOrient,
  kStitchBorders,
  kRemoveDegenerate,
  kFillHoles,
  kPolygonSoup,
  kManifoldPreprocess,
};

std::string operation_id(RepairKind kind);
std::string validator_id(RepairKind kind);
std::vector<OperationDefinition> repair_operations();
std::vector<OperationDefinition> repair_validators();

}  // namespace cgal_master::wave_a_repair
