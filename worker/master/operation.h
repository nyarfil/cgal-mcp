#pragma once

#include "protocol.h"

#include <functional>
#include <string>
#include <vector>

namespace cgal_master {

struct OperationDefinition {
  std::string id;
  int revision;
  std::vector<std::string> input_types;
  std::string output_type;
  std::string role;
  std::function<Json(const Request&)> execute;
};

OperationDefinition convex_hull_operation();
OperationDefinition convex_enclosure_validator_operation();

const std::vector<OperationDefinition>& operation_registry();
Json dispatch(const Request& request);
Json manifest();

}  // namespace cgal_master
