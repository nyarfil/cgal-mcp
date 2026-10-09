#include "b4_common.h"

#include <cmath>

namespace cgal_master::batch4 {

SurfaceLocation parse_surface_location(const Json& value, std::size_t vertex_count, std::size_t face_count,
                                       const std::string& context) {
  SurfaceLocation location;
  if (!value.is_object()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", context + " must be an object");
  }
  if (value.size() == 1 && value.contains("vertex")) {
    if (!value["vertex"].is_number_unsigned() || value["vertex"].get<std::size_t>() >= vertex_count) {
      throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", context + " vertex index is out of range");
    }
    location.is_vertex = true;
    location.vertex = value["vertex"].get<std::size_t>();
    return location;
  }
  if (value.size() == 2 && value.contains("face") && value.contains("barycentric")) {
    const auto& coordinates = value["barycentric"];
    if (!value["face"].is_number_unsigned() || value["face"].get<std::size_t>() >= face_count ||
        !coordinates.is_array() || coordinates.size() != 3) {
      throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                        context + " needs an in-range face and three barycentric coordinates");
    }
    location.face = value["face"].get<std::size_t>();
    double sum = 0;
    for (std::size_t i = 0; i < 3; ++i) {
      if (!coordinates[i].is_number() || coordinates[i].is_boolean() ||
          !std::isfinite(coordinates[i].get<double>()) || coordinates[i].get<double>() < 0) {
        throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                          context + " barycentric coordinates must be finite and non-negative");
      }
      location.barycentric[i] = coordinates[i].get<double>();
      sum += location.barycentric[i];
    }
    if (std::fabs(sum - 1.0) > 1e-12) {
      throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", context + " barycentric coordinates must sum to 1");
    }
    return location;
  }
  throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                    context + " must be {vertex} or {face, barycentric}");
}

V3 location_position(const query_ops::RawMesh& mesh, const SurfaceLocation& location) {
  if (location.is_vertex) return mesh.vertices.at(location.vertex);
  const auto& face = mesh.faces.at(location.face);
  V3 result{0, 0, 0};
  for (std::size_t k = 0; k < 3; ++k) {
    for (std::size_t axis = 0; axis < 3; ++axis) {
      result[axis] += location.barycentric[k] * mesh.vertices.at(face.at(k))[axis];
    }
  }
  return result;
}

std::vector<SurfaceLocation> parse_location_list(const Request& request, const char* name, std::size_t maximum,
                                                 const query_ops::RawMesh& mesh) {
  const auto& value = request.parameters.at(name);
  if (!value.is_array() || value.empty() || value.size() > maximum) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " must be an array of 1 to " + std::to_string(maximum) + " locations");
  }
  std::vector<SurfaceLocation> result;
  for (const auto& item : value) {
    result.push_back(parse_surface_location(item, mesh.vertices.size(), mesh.faces.size(), name));
  }
  return result;
}

namespace {
void append(std::vector<OperationDefinition>& target, std::vector<OperationDefinition> source) {
  for (auto& operation : source) target.push_back(std::move(operation));
}
}  // namespace

std::vector<OperationDefinition> producer_operations() {
  std::vector<OperationDefinition> result;
  append(result, mesh_producers());
  return result;
}

std::vector<OperationDefinition> validator_operations() {
  std::vector<OperationDefinition> result;
  append(result, mesh_validators());
  return result;
}

}  // namespace cgal_master::batch4
