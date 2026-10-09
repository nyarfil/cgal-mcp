#include "b6_common.h"

#include <algorithm>

namespace cgal_master::batch6 {
namespace {
void append(std::vector<OperationDefinition>& target, std::vector<OperationDefinition> source) {
  for (auto& operation : source) target.push_back(std::move(operation));
}
}  // namespace

void optional_dependency_missing(const std::string& dependency, const std::string& operation) {
  throw WorkerError("UNSUPPORTED", "OPTIONAL_DEPENDENCY_NOT_BUILT",
                    operation + " needs the optional third-party library " + dependency +
                        ", which this worker build was configured without");
}

Json publish_polygon_soup(const Request& request, const std::vector<V3>& vertices,
                          std::vector<std::vector<std::size_t>> faces, const std::string& unit, bool& reversed) {
  double volume6 = 0;
  for (const auto& face : faces) {
    for (std::size_t k = 1; k + 1 < face.size(); ++k) {
      const auto &a = vertices.at(face[0]), &b = vertices.at(face[k]), &c = vertices.at(face[k + 1]);
      volume6 += a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) +
                 a[2] * (b[0] * c[1] - b[1] * c[0]);
    }
  }
  reversed = volume6 < 0;
  if (reversed) {
    for (auto& face : faces) std::reverse(face.begin(), face.end());
  }
  // Canonical form so that equal geometry gives byte-identical output (PolyFit's face and vertex order
  // depends on hash-map iteration): vertices sorted by coordinates, each face rotated to start at its
  // smallest vertex index (orientation kept), faces sorted lexicographically.
  std::vector<std::size_t> order(vertices.size());
  for (std::size_t i = 0; i < order.size(); ++i) order[i] = i;
  std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) { return vertices[a] < vertices[b]; });
  std::vector<std::size_t> rank(vertices.size());
  std::vector<V3> sorted_vertices(vertices.size());
  for (std::size_t i = 0; i < order.size(); ++i) {
    rank[order[i]] = i;
    sorted_vertices[i] = vertices[order[i]];
    for (auto& c : sorted_vertices[i]) {
      if (c == 0.0) c = 0.0;  // -0 and +0 are the same coordinate: publish +0
    }
  }
  for (auto& face : faces) {
    for (auto& index : face) index = rank.at(index);
    std::rotate(face.begin(), std::min_element(face.begin(), face.end()), face.end());
  }
  std::sort(faces.begin(), faces.end());
  return query_ops::write_off_output(request, sorted_vertices, faces, "PolygonSoup3", unit);
}

std::vector<OperationDefinition> producer_operations() {
  std::vector<OperationDefinition> result;
  append(result, registration_producers());
  append(result, polyfit_producers());
  append(result, kinetic_producers());
  return result;
}

std::vector<OperationDefinition> validator_operations() {
  std::vector<OperationDefinition> result;
  append(result, registration_validators());
  append(result, polyfit_validators());
  return result;
}

}  // namespace cgal_master::batch6
