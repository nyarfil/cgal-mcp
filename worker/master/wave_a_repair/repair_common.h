#pragma once

#include "repair_operations.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>

#include <cstddef>
#include <filesystem>
#include <string>
#include <vector>

namespace cgal_master::wave_a_repair {

using RepairKernel = CGAL::Exact_predicates_inexact_constructions_kernel;
using RepairPoint = RepairKernel::Point_3;
using RepairMesh = CGAL::Surface_mesh<RepairPoint>;

struct Soup {
  std::vector<RepairPoint> points;
  std::vector<std::vector<std::size_t>> faces;
};

struct RepairResult {
  Soup soup;
  Json metrics = Json::object();
};

void require_request(const Request& request, RepairKind kind, bool validator);
Soup read_soup(const ArtifactInput& input,
               const std::vector<std::string>& accepted_types);
RepairResult compute_repair(RepairKind kind, const Soup& source,
                            const Json& parameters);
bool soup_equal(const Soup& first, const Soup& second);
Json soup_statistics(const Soup& soup);
std::filesystem::path write_soup_output(const Request& request,
                                        const Soup& soup,
                                        const std::string& filename);
std::filesystem::path write_json_output(const Request& request,
                                        const Json& value,
                                        const std::string& filename);
Json operation_metadata(RepairKind kind, bool validator);

}  // namespace cgal_master::wave_a_repair
