#pragma once
// Batch-6 shared declarations (7.9.05 OpenGR registration, 7.10.01 Poisson wrapper, 7.10.02
// Polygonal_surface_reconstruction with SCIP and Kinetic_surface_reconstruction). This header
// includes no CGAL header: the independent validators include it and must not touch the packages
// they check. OpenGR and SCIP are optional third-party dependencies (CMakeLists.txt): without
// them the operations are still declared and report UNSUPPORTED / OPTIONAL_DEPENDENCY_NOT_BUILT.

#include "../batch2/b2_geometry.h"
#include "../reconstruction/reconstruction_common.h"

#include <array>
#include <string>
#include <vector>

namespace cgal_master::batch6 {

using batch2::Q;
using batch2::Vec;
using query_ops::V3;

std::vector<OperationDefinition> registration_producers();
std::vector<OperationDefinition> registration_validators();
std::vector<OperationDefinition> polyfit_producers();
std::vector<OperationDefinition> polyfit_validators();
std::vector<OperationDefinition> kinetic_producers();
std::vector<OperationDefinition> producer_operations();
std::vector<OperationDefinition> validator_operations();

inline constexpr std::size_t kMaximumRegistrationPoints = 400;
inline constexpr std::size_t kMaximumReconstructionPoints = 20000;
inline constexpr std::size_t kMaximumPolygonFaces = 2000;

[[noreturn]] void optional_dependency_missing(const std::string& dependency, const std::string& operation);

// Orients a polygon soup outward as a whole (fan signed volume, reversal of every face when negative;
// the validators re-check the orientation exactly) and writes it as PolygonSoup3 OFF. Returns the
// geometry output record; `reversed` tells whether the faces were reversed.
Json publish_polygon_soup(const Request& request, const std::vector<V3>& vertices,
                          std::vector<std::vector<std::size_t>> faces, const std::string& unit, bool& reversed);

// Writes a PointSet3 xyz output (17 significant digits) in the slot "points".
Json write_xyz_output(const Request& request, const std::vector<V3>& points, const std::string& unit);

}  // namespace cgal_master::batch6
