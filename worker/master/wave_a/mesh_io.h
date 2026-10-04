#pragma once

#include "../protocol.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>

#include <filesystem>
#include <string>

namespace cgal_master::wave_a {

using Kernel = CGAL::Exact_predicates_inexact_constructions_kernel;
using Point = Kernel::Point_3;
using Mesh = CGAL::Surface_mesh<Point>;

Mesh read_triangle_off(const ArtifactInput& input);
void require_same_unit(const ArtifactInput& first,
                       const ArtifactInput& second);

// Parses {"value": finite nonnegative number, "unit": "mm"|"cm"|"m"}
// and converts the value to the geometry artifact's unit.
double typed_length(const Json& value, const std::string& geometry_unit,
                    const std::string& parameter_name,
                    bool strictly_positive = false);

std::filesystem::path write_mesh_output(const Request& request,
                                        const Mesh& mesh);
std::filesystem::path write_validation_output(const Request& request,
                                              const Json& report);

Json geometry_output(const std::filesystem::path& path,
                     const std::string& unit);
Json validation_output(const std::filesystem::path& path);

void require_wave_a_kernel(const Request& request);
void require_healthy_triangle_mesh(const Mesh& mesh,
                                   const std::string& subject);

}  // namespace cgal_master::wave_a
