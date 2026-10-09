#include "b3_common.h"

#include <cmath>

namespace cgal_master::batch3 {

std::vector<double> weights_parameter(const Request& request, std::size_t count) {
  const auto& value = request.parameters.at("weights");
  if (!value.is_array() || value.size() != count) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "weights must be an array with one number per point");
  }
  std::vector<double> result;
  for (const auto& item : value) {
    if (!item.is_number() || item.is_boolean() || !std::isfinite(item.get<double>())) {
      throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "weights must be finite numbers");
    }
    result.push_back(item.get<double>());
  }
  return result;
}

Q determinant(std::vector<std::vector<Q>> m) {
  const std::size_t n = m.size();
  Q det = 1;
  for (std::size_t col = 0; col < n; ++col) {
    std::size_t pivot = col;
    while (pivot < n && m[pivot][col] == 0) ++pivot;
    if (pivot == n) return Q(0);
    if (pivot != col) {
      std::swap(m[pivot], m[col]);
      det = -det;
    }
    det *= m[col][col];
    for (std::size_t row = col + 1; row < n; ++row) {
      const Q factor = m[row][col] / m[col][col];
      for (std::size_t k = col; k < n; ++k) m[row][k] -= factor * m[col][k];
    }
  }
  return det;
}

namespace {
void append(std::vector<OperationDefinition>& target, std::vector<OperationDefinition> source) {
  for (auto& operation : source) target.push_back(std::move(operation));
}
}  // namespace

std::vector<OperationDefinition> producer_operations() {
  std::vector<OperationDefinition> result;
  append(result, triangulation_producers());
  append(result, planar_producers());
  append(result, mesh_producers());
  return result;
}

std::vector<OperationDefinition> validator_operations() {
  std::vector<OperationDefinition> result;
  append(result, triangulation_validators());
  append(result, planar_validators());
  append(result, mesh_validators());
  return result;
}

}  // namespace cgal_master::batch3
