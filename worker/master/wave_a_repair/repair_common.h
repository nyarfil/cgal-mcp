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
  std::string unit;  // length unit of the source artifact (set by read_soup)
  std::string sha256;  // verified content digest of the source artifact (set by read_soup)
};

struct RepairResult {
  Soup soup;
  Json metrics = Json::object();
};

// Optional hole selection for the two hole-filling operations. Inactive means the original
// behaviour: every cycle with at most max_hole_edges edges is filled.
struct HoleSelection {
  bool active = false;
  bool by_ids = false;
  std::vector<std::size_t> ids;  // sorted, unique
  // hole_ids are only meaningful for the mesh they were listed on: required with hole_ids and
  // compared with the verified input digest (mesh.analysis.boundary_cycles results.source_mesh_sha256).
  std::string source_sha256;
  bool has_max_perimeter = false;
  double max_perimeter = 0;
  bool has_max_area = false;
  double max_area = 0;
};

struct HoleCycleStats {
  std::size_t hole_id = 0;  // smallest source vertex index on the cycle
  std::size_t edge_count = 0;
  double perimeter = 0;
  double area = 0;  // Newell polygon area of the boundary polygon (planar estimate)
};

// `unit` (mesh length unit) checks the typed filter units; empty skips that check.
HoleSelection parse_hole_selection(const Json& parameters, bool refine_fair, const std::string& unit = "");
// `cycle` lists the vertex indices along the border direction; the stats are rotation invariant.
HoleCycleStats hole_cycle_stats(const std::vector<std::size_t>& cycle,
                                const std::vector<RepairPoint>& points);
bool hole_matches_selection(const HoleSelection& selection, const HoleCycleStats& stats,
                            std::size_t max_hole_edges);
std::size_t hole_edge_limit(const Json& parameters);
// Refuses hole_ids listed on another mesh. `error_class` is PRECONDITION_FAILED for producers and
// VALIDATION_FAILED for validators.
void require_hole_ids_source(const HoleSelection& selection, const std::string& actual_sha256,
                             const std::string& error_class);

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
