#include "repair_common.h"

#include "../artifact_io.h"

#include <algorithm>
#include <array>
#include <iomanip>
#include <map>
#include <set>
#include <sstream>

namespace cgal_master::wave_a_repair {
namespace {

const std::array<RepairKind, 6> kKinds = {
    RepairKind::kOrient, RepairKind::kStitchBorders,
    RepairKind::kRemoveDegenerate, RepairKind::kFillHoles,
    RepairKind::kPolygonSoup, RepairKind::kManifoldPreprocess};

std::vector<std::string> source_types(RepairKind kind) {
  if (kind == RepairKind::kOrient || kind == RepairKind::kPolygonSoup)
    return {"PolygonSoup3"};
  if (kind == RepairKind::kRemoveDegenerate)
    return {"PolygonSoup3", "TriangleSurfaceMesh"};
  return {"TriangleSurfaceMesh"};
}

std::string output_type(RepairKind kind) {
  return kind == RepairKind::kPolygonSoup ? "PolygonSoup3" : "TriangleSurfaceMesh";
}

std::string point_key(const RepairPoint& point) {
  std::ostringstream stream;
  stream.imbue(std::locale::classic());
  stream << std::setprecision(17) << point.x() << ',' << point.y() << ',' << point.z();
  return stream.str();
}

using TriangleBag = std::multiset<std::array<std::string, 3>>;

TriangleBag triangle_bag(const Soup& soup) {
  TriangleBag result;
  for (const auto& face : soup.faces) {
    if (face.size() != 3) continue;
    std::array<std::string, 3> triangle = {
        point_key(soup.points[face[0]]), point_key(soup.points[face[1]]),
        point_key(soup.points[face[2]])};
    std::sort(triangle.begin(), triangle.end());
    result.insert(std::move(triangle));
  }
  return result;
}

bool is_subbag(const TriangleBag& subset, const TriangleBag& superset) {
  std::map<std::array<std::string, 3>, std::size_t> counts;
  for (const auto& value : superset) ++counts[value];
  for (const auto& value : subset) {
    auto iterator = counts.find(value);
    if (iterator == counts.end() || iterator->second == 0) return false;
    --iterator->second;
  }
  return true;
}

bool points_are_subset(const Soup& subset, const Soup& superset) {
  std::set<std::string> keys;
  for (const auto& point : superset.points) keys.insert(point_key(point));
  for (const auto& point : subset.points) {
    if (keys.find(point_key(point)) == keys.end()) return false;
  }
  return true;
}

bool geometry_preserved(RepairKind kind, const Soup& source, const Soup& candidate) {
  const auto source_bag = triangle_bag(source);
  const auto candidate_bag = triangle_bag(candidate);
  // CGAL repairs collinear caps by flipping edges, which creates triangles that
  // are not in the source; only vertex positions are guaranteed to be preserved.
  if (kind == RepairKind::kRemoveDegenerate) return points_are_subset(candidate, source);
  if (kind == RepairKind::kPolygonSoup) return is_subbag(candidate_bag, source_bag);
  if (kind == RepairKind::kFillHoles) return is_subbag(source_bag, candidate_bag);
  return source_bag == candidate_bag;
}

std::size_t integer(const Json& value, const char* key) {
  return value.at(key).get<std::size_t>();
}

std::size_t repeated_index_faces(const Soup& soup) {
  std::size_t count = 0;
  for (const auto& face : soup.faces) {
    if (face.size() != 3 || face[0] == face[1] || face[1] == face[2] || face[2] == face[0]) ++count;
  }
  return count;
}

std::size_t duplicate_polygons(const Soup& soup, bool same_orientation_only) {
  std::set<std::array<std::size_t, 3>> seen;
  std::size_t count = 0;
  for (const auto& face : soup.faces) {
    if (face.size() != 3) continue;
    std::array<std::size_t, 3> key = {face[0], face[1], face[2]};
    if (same_orientation_only) {
      while (key[0] > key[1] || key[0] > key[2]) std::rotate(key.begin(), key.begin() + 1, key.end());
    } else {
      std::sort(key.begin(), key.end());
    }
    if (!seen.insert(key).second) ++count;
  }
  return count;
}

bool invariant(RepairKind kind, const Json& source_stats, const Json& candidate_stats,
               const RepairResult& reference, const Json& parameters, const Soup& candidate) {
  if (kind == RepairKind::kOrient) {
    if (!candidate_stats.at("polygon_mesh_constructible").get<bool>()) return false;
    const auto& mesh = candidate_stats.at("mesh");
    return !mesh.at("closed").get<bool>() || mesh.at("outward_oriented").get<bool>();
  }
  if (kind == RepairKind::kStitchBorders) {
    return integer(candidate_stats, "face_count") == integer(source_stats, "face_count") &&
           integer(candidate_stats, "vertex_count") <= integer(source_stats, "vertex_count") &&
           integer(candidate_stats.at("mesh"), "boundary_cycle_count") <=
               integer(source_stats.at("mesh"), "boundary_cycle_count");
  }
  if (kind == RepairKind::kRemoveDegenerate) {
    return integer(candidate_stats, "degenerate_face_count") == 0 &&
           candidate_stats.at("polygon_mesh_constructible").get<bool>();
  }
  if (kind == RepairKind::kFillHoles) {
    return integer(candidate_stats, "face_count") > integer(source_stats, "face_count") &&
           integer(candidate_stats.at("mesh"), "boundary_cycle_count") ==
               reference.metrics.at("skipped_hole_count").get<std::size_t>();
  }
  if (kind == RepairKind::kPolygonSoup) {
    // repair_polygon_soup removes combinatorially degenerate polygons and
    // duplicate polygons (same orientation only when require_same_orientation
    // is true); geometrically collinear triangles are intentionally kept.
    return repeated_index_faces(candidate) == 0 &&
           duplicate_polygons(candidate, parameters.at("require_same_orientation").get<bool>()) == 0 &&
           integer(candidate_stats, "duplicate_point_count") == 0 &&
           integer(candidate_stats, "unused_point_count") == 0;
  }
  return integer(candidate_stats, "face_count") == integer(source_stats, "face_count") &&
         integer(candidate_stats.at("mesh"), "non_manifold_vertex_count") == 0;
}

Json validate(const Request& request, RepairKind kind) {
  require_request(request, kind, true);
  const auto& candidate_input = request.inputs[0];
  const auto& source_input = request.inputs[1];
  if (candidate_input.type != output_type(kind) || candidate_input.format != "off") {
    throw WorkerError("INVALID_INPUT", "CANDIDATE_SHAPE_MISMATCH",
                      "Repair validator candidate type/format is incorrect");
  }
  if (candidate_input.unit != source_input.unit) {
    throw WorkerError("VALIDATION_FAILED", "REPAIR_UNIT_CHANGED",
                      "Repair candidate unit differs from its source");
  }
  const auto source = read_soup(source_input, source_types(kind));
  const auto candidate = read_soup(candidate_input, {output_type(kind)});
  const auto reference = compute_repair(kind, source, request.parameters);
  const auto source_stats = soup_statistics(source);
  const auto candidate_stats = soup_statistics(candidate);
  const bool replay_match = soup_equal(candidate, reference.soup);
  const bool invariant_valid = replay_match && invariant(kind, source_stats, candidate_stats, reference,
                                                  request.parameters, candidate);
  const bool preserved = geometry_preserved(kind, source, candidate);
  if (!replay_match || !invariant_valid || !preserved) {
    throw WorkerError("VALIDATION_FAILED", "REPAIR_VALIDATION_FAILED",
                      "Repair candidate failed official replay or operation invariants");
  }
  Json checks = {{"source_identity_matches", true},
                 {"candidate_matches_official_cgal_replay", true},
                 {"candidate_unit_matches_source", true},
                 {"repair_invariant_valid", true},
                 {"numeric_profile_valid", true},
                 {"source_geometry_preserved_as_required", true}};
  Json report = {{"schema_version", 1},
                 {"validator_id", validator_id(kind)},
                 {"validates", operation_id(kind)},
                 {"status", "pass"},
                 {"passed", true},
                 {"candidate_sha256", candidate_input.sha256},
                 {"source_sha256", source_input.sha256},
                 {"parameters", request.parameters},
                 {"source", source_stats},
                 {"candidate", candidate_stats},
                 {"reference_metrics", reference.metrics},
                 {"checks", std::move(checks)}};
  const auto path = write_json_output(request, report, "validation.json");
  return success_result(
      request,
      Json::array({{{"slot", "validation"}, {"type", "ValidationReport"},
                    {"unit", "none"}, {"format", "json"},
                    {"path", portable_path(path)}}}),
      {{"validator", validator_id(kind)},
       {"candidate_sha256", candidate_input.sha256},
       {"source_sha256", source_input.sha256}});
}

OperationDefinition definition(RepairKind kind) {
  auto types = std::vector<std::string>{output_type(kind)};  // candidate slot first, then source slot
  const auto accepted = source_types(kind);
  types.insert(types.end(), accepted.begin(), accepted.end());
  OperationDefinition operation{
      validator_id(kind), 1, std::move(types), "ValidationReport", "validator",
      [kind](const Request& request) { return validate(request, kind); }};
  operation.supported_kernels = {"package_recommended"};
  operation.effective_kernel = "CGAL::Exact_predicates_inexact_constructions_kernel";
  operation.dependencies = {"Polygon_mesh_processing", "Surface_mesh"};
  operation.info = operation_metadata(kind, true);
  return operation;
}

}  // namespace

std::vector<OperationDefinition> repair_validators() {
  std::vector<OperationDefinition> result;
  for (const auto kind : kKinds) result.push_back(definition(kind));
  return result;
}

}  // namespace cgal_master::wave_a_repair
