#include "repair_common.h"

#include "../artifact_io.h"
#include "../sha256.h"

#include <CGAL/boost/graph/border.h>
#include <CGAL/Polygon_mesh_processing/manifoldness.h>
#include <CGAL/Polygon_mesh_processing/orient_polygon_soup.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/Polygon_mesh_processing/polygon_soup_to_polygon_mesh.h>
#include <CGAL/Polygon_mesh_processing/repair.h>
#include <CGAL/Polygon_mesh_processing/repair_degeneracies.h>
#include <CGAL/Polygon_mesh_processing/repair_polygon_soup.h>
#include <CGAL/Polygon_mesh_processing/stitch_borders.h>
#include <CGAL/Polygon_mesh_processing/triangulate_hole.h>
#include <CGAL/Polygon_mesh_processing/refine.h>
#include <CGAL/Polygon_mesh_processing/fair.h>
#include <CGAL/boost/graph/helpers.h>
#include <CGAL/boost/graph/iterator.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <locale>
#include <map>
#include <set>
#include <sstream>
#include <unordered_map>
#include <unordered_set>

namespace cgal_master::wave_a_repair {
namespace PMP = CGAL::Polygon_mesh_processing;
namespace {

constexpr std::size_t kMaximumArtifactBytes = 64ULL * 1024ULL * 1024ULL;
constexpr std::size_t kMaximumVertices = 1000000;
constexpr std::size_t kMaximumFaces = 2000000;
constexpr double kMinimumSpan = 1e-100;
constexpr double kMaximumAbsoluteCoordinate = 1e100;
constexpr double kMaximumTranslationToSpanRatio = 1e6;

std::string verified_bytes(const ArtifactInput& input) {
  std::error_code error;
  const auto path = std::filesystem::canonical(input.path, error);
  if (error || !std::filesystem::is_regular_file(path, error) || error) {
    throw WorkerError("INVALID_INPUT", "INPUT_NOT_REGULAR_FILE",
                      "Repair input must resolve to a regular file");
  }
  const auto size = std::filesystem::file_size(path, error);
  if (error || size > kMaximumArtifactBytes) {
    throw WorkerError("RESOURCE_LIMIT", "ARTIFACT_SIZE_LIMIT_EXCEEDED",
                      "Repair input exceeds the 64 MiB profile limit");
  }
  std::ifstream stream(path, std::ios::binary);
  if (!stream) {
    throw WorkerError("INVALID_INPUT", "INPUT_OPEN_FAILED",
                      "Unable to open repair input");
  }
  std::string bytes((std::istreambuf_iterator<char>(stream)),
                    std::istreambuf_iterator<char>());
  if (!stream.eof() && stream.fail()) {
    throw WorkerError("INVALID_INPUT", "INPUT_READ_FAILED",
                      "Unable to read repair input");
  }
  if (sha256_bytes(bytes) != input.sha256) {
    throw WorkerError("INVALID_INPUT", "DIGEST_MISMATCH",
                      "Repair input sha256 does not match the request");
  }
  return bytes;
}

std::vector<std::string> off_tokens(const std::string& bytes) {
  std::vector<std::string> tokens;
  std::istringstream lines(bytes);
  lines.imbue(std::locale::classic());
  std::string line;
  while (std::getline(lines, line)) {
    const auto comment = line.find('#');
    if (comment != std::string::npos) line.resize(comment);
    std::istringstream words(line);
    words.imbue(std::locale::classic());
    for (std::string token; words >> token;) tokens.push_back(std::move(token));
  }
  return tokens;
}

std::size_t parse_size(const std::string& token, const char* field) {
  if (token.empty() || token[0] == '-') {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      std::string("Invalid OFF ") + field);
  }
  std::size_t consumed = 0;
  unsigned long long value = 0;
  try {
    value = std::stoull(token, &consumed);
  } catch (const std::exception&) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      std::string("Invalid OFF ") + field);
  }
  if (consumed != token.size() || value > std::numeric_limits<std::size_t>::max()) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      std::string("Invalid OFF ") + field);
  }
  return static_cast<std::size_t>(value);
}

double parse_coordinate(const std::string& token) {
  std::size_t consumed = 0;
  double value = 0;
  try {
    value = std::stod(token, &consumed);
  } catch (const std::exception&) {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF",
                      "OFF coordinates must be binary64 numbers");
  }
  if (consumed != token.size() || !std::isfinite(value)) {
    throw WorkerError("INVALID_INPUT", "NONFINITE_COORDINATE",
                      "OFF coordinates must be finite");
  }
  return value;
}

void validate_numeric_profile(const Soup& soup) {
  std::array<double, 3> minimum = {std::numeric_limits<double>::infinity(),
                                    std::numeric_limits<double>::infinity(),
                                    std::numeric_limits<double>::infinity()};
  std::array<double, 3> maximum = {-std::numeric_limits<double>::infinity(),
                                    -std::numeric_limits<double>::infinity(),
                                    -std::numeric_limits<double>::infinity()};
  double max_abs = 0;
  for (const auto& point : soup.points) {
    const std::array<double, 3> values = {point.x(), point.y(), point.z()};
    for (std::size_t axis = 0; axis < 3; ++axis) {
      minimum[axis] = (std::min)(minimum[axis], values[axis]);
      maximum[axis] = (std::max)(maximum[axis], values[axis]);
      max_abs = (std::max)(max_abs, std::abs(values[axis]));
    }
  }
  const double span = (std::max)({maximum[0] - minimum[0],
                                  maximum[1] - minimum[1],
                                  maximum[2] - minimum[2]});
  if (!std::isfinite(span) || span < kMinimumSpan ||
      max_abs > kMaximumAbsoluteCoordinate || max_abs / span > kMaximumTranslationToSpanRatio) {
    throw WorkerError("PRECONDITION_FAILED", "UNSUPPORTED_NUMERIC_SCALE",
                      "Repair profile requires span >= 1e-100, max |coordinate| <= 1e100, and translation/span <= 1e6");
  }
}

RepairMesh mesh_from_soup(const Soup& soup, const std::string& subject) {
  if (!PMP::is_polygon_soup_a_polygon_mesh(soup.faces)) {
    throw WorkerError("PRECONDITION_FAILED", "MESH_GRAPH_NOT_CONSTRUCTIBLE",
                      subject + " does not define a constructible polygon mesh");
  }
  RepairMesh mesh;
  PMP::polygon_soup_to_polygon_mesh(soup.points, soup.faces, mesh);
  if (!CGAL::is_valid_polygon_mesh(mesh) || !CGAL::is_triangle_mesh(mesh) ||
      mesh.number_of_faces() == 0) {
    throw WorkerError("PRECONDITION_FAILED", "MESH_GRAPH_NOT_CONSTRUCTIBLE",
                      subject + " is not a nonempty triangle polygon mesh");
  }
  return mesh;
}

RepairMesh nonmanifold_mesh_from_soup(const Soup& soup) {
  // Surface_mesh rejects a non-manifold vertex through its ordinary add_face
  // path. Reconstruct each triangle independently, stitch true shared edges,
  // then merge only the remaining vertex copies that came from one original
  // soup index. This is the same explicit set_target construction used by the
  // official CGAL manifoldness repair example, generalized to bounded OFF.
  RepairMesh mesh;
  std::vector<std::vector<RepairMesh::Vertex_index>> occurrences(soup.points.size());
  for (const auto& face : soup.faces) {
    if (face.size() != 3 || face[0] == face[1] || face[1] == face[2] || face[2] == face[0]) {
      throw WorkerError("PRECONDITION_FAILED", "MESH_GRAPH_NOT_CONSTRUCTIBLE",
                        "Manifold preprocessing requires combinatorially valid triangles");
    }
    std::array<RepairMesh::Vertex_index, 3> vertices;
    for (std::size_t i = 0; i < 3; ++i) {
      vertices[i] = mesh.add_vertex(soup.points[face[i]]);
      occurrences[face[i]].push_back(vertices[i]);
    }
    if (mesh.add_face(vertices[0], vertices[1], vertices[2]) == RepairMesh::null_face()) {
      throw WorkerError("PRECONDITION_FAILED", "MESH_GRAPH_NOT_CONSTRUCTIBLE",
                        "Unable to construct triangle for manifold preprocessing");
    }
  }
  PMP::stitch_borders(mesh);
  for (const auto& copies : occurrences) {
    RepairMesh::Vertex_index keep = RepairMesh::null_vertex();
    for (const auto vertex : copies) {
      if (mesh.is_removed(vertex)) continue;
      if (keep == RepairMesh::null_vertex()) {
        keep = vertex;
        continue;
      }
      for (const auto halfedge : CGAL::halfedges_around_target(vertex, mesh)) {
        set_target(halfedge, keep, mesh);
      }
      remove_vertex(vertex, mesh);
    }
  }
  if (mesh.number_of_faces() == 0) {
    throw WorkerError("PRECONDITION_FAILED", "MESH_GRAPH_NOT_CONSTRUCTIBLE",
                      "Unable to reconstruct the non-manifold input graph");
  }
  return mesh;
}

Soup soup_from_mesh(const RepairMesh& mesh) {
  Soup soup;
  std::unordered_map<std::size_t, std::size_t> index;
  soup.points.reserve(mesh.number_of_vertices());
  for (const auto vertex : vertices(mesh)) {
    index.emplace(vertex.idx(), soup.points.size());
    soup.points.push_back(mesh.point(vertex));
  }
  soup.faces.reserve(mesh.number_of_faces());
  for (const auto face : faces(mesh)) {
    std::vector<std::size_t> polygon;
    for (const auto vertex : CGAL::vertices_around_face(halfedge(face, mesh), mesh)) {
      polygon.push_back(index.at(vertex.idx()));
    }
    soup.faces.push_back(std::move(polygon));
  }
  return soup;
}

std::size_t degenerate_faces(const Soup& soup) {
  std::size_t count = 0;
  for (const auto& face : soup.faces) {
    if (face.size() != 3 || face[0] == face[1] || face[1] == face[2] || face[2] == face[0] ||
        CGAL::collinear(soup.points[face[0]], soup.points[face[1]], soup.points[face[2]])) {
      ++count;
    }
  }
  return count;
}

std::size_t duplicate_faces(const Soup& soup) {
  std::set<std::array<std::size_t, 3>> seen;
  std::size_t count = 0;
  for (const auto& face : soup.faces) {
    if (face.size() != 3) continue;
    std::array<std::size_t, 3> key = {face[0], face[1], face[2]};
    std::sort(key.begin(), key.end());
    if (!seen.insert(key).second) ++count;
  }
  return count;
}

std::size_t duplicate_points(const Soup& soup) {
  std::set<std::array<double, 3>> seen;
  std::size_t count = 0;
  for (const auto& p : soup.points) {
    if (!seen.insert({p.x(), p.y(), p.z()}).second) ++count;
  }
  return count;
}

std::size_t unused_points(const Soup& soup) {
  std::vector<bool> used(soup.points.size(), false);
  for (const auto& face : soup.faces) for (const auto value : face) used[value] = true;
  return static_cast<std::size_t>(std::count(used.begin(), used.end(), false));
}

Json mesh_metrics(const RepairMesh& mesh) {
  std::vector<RepairMesh::Halfedge_index> boundaries;
  CGAL::extract_boundary_cycles(mesh, std::back_inserter(boundaries));
  // One-shot scan; the per-vertex PMP::is_non_manifold_vertex loop cost ~2 s per 35k vertices.
  // non_manifold_vertices reports one halfedge per pinched umbrella, so count distinct vertices.
  std::vector<RepairMesh::Halfedge_index> pinched;
  PMP::non_manifold_vertices(mesh, std::back_inserter(pinched));
  std::unordered_set<std::size_t> pinched_vertices;
  for (const auto halfedge : pinched) pinched_vertices.insert(target(halfedge, mesh).idx());
  const std::size_t nonmanifold = pinched_vertices.size();
  Json result = {{"vertex_count", mesh.number_of_vertices()},
          {"face_count", mesh.number_of_faces()},
          {"boundary_cycle_count", boundaries.size()},
          {"closed", CGAL::is_closed(mesh)},
          {"non_manifold_vertex_count", nonmanifold}};
  if (CGAL::is_closed(mesh)) result["outward_oriented"] = PMP::is_outward_oriented(mesh);
  return result;
}

PMP::Duplicate_polygon_erase_policy duplicate_policy(const Json& parameters) {
  const auto value = parameters.at("duplicate_polygon_policy").get<std::string>();
  if (value == "keep_one") return PMP::Duplicate_polygon_erase_policy::KEEP_ONE;
  if (value == "erase_all") return PMP::Duplicate_polygon_erase_policy::ERASE_ALL;
  if (value == "keep_one_if_odd") return PMP::Duplicate_polygon_erase_policy::KEEP_ONE_IF_ODD;
  throw WorkerError("INVALID_INPUT", "INVALID_DUPLICATE_POLYGON_POLICY",
                    "duplicate_polygon_policy must be keep_one, erase_all, or keep_one_if_odd");
}

std::size_t required_hole_limit(const Json& parameters) {
  if (!parameters.is_object() || !parameters.contains("max_hole_edges") ||
      !parameters["max_hole_edges"].is_number_unsigned()) {
    throw WorkerError("INVALID_INPUT", "INVALID_MAX_HOLE_EDGES",
                      "max_hole_edges must be an unsigned integer");
  }
  const auto value = parameters["max_hole_edges"].get<std::uint64_t>();
  if (value < 3 || value > 2000) {
    throw WorkerError("INVALID_INPUT", "INVALID_MAX_HOLE_EDGES",
                      "max_hole_edges must be in [3, 2000]");
  }
  return static_cast<std::size_t>(value);
}

constexpr std::size_t kMaximumHoleIds = 10000;

struct HolePlan {
  std::vector<std::size_t> ids;  // hole_id per cycle (parallel to the cycle list)
  std::vector<bool> fill;        // fill decision per cycle
};

// Explicit selections are honoured or refused, never silently reduced.
HolePlan plan_hole_selection(const RepairMesh& mesh,
                             const std::vector<RepairMesh::Halfedge_index>& cycles,
                             const HoleSelection& selection, std::size_t limit) {
  HolePlan plan;
  if (!selection.active) return plan;
  std::vector<RepairPoint> points(mesh.number_of_vertices());
  for (const auto vertex : vertices(mesh)) points[vertex.idx()] = mesh.point(vertex);
  std::vector<HoleCycleStats> stats;
  stats.reserve(cycles.size());
  for (const auto halfedge : cycles) {
    std::vector<std::size_t> ring;
    auto cursor = halfedge;
    do {
      ring.push_back(source(cursor, mesh).idx());
      cursor = next(cursor, mesh);
    } while (cursor != halfedge && ring.size() <= kMaximumFaces);
    stats.push_back(hole_cycle_stats(ring, points));
  }
  std::set<std::size_t> known;
  for (const auto& item : stats) known.insert(item.hole_id);
  if (selection.by_ids) {
    for (const auto id : selection.ids) {
      if (known.count(id) == 0) {
        throw WorkerError("PRECONDITION_FAILED", "HOLE_ID_NOT_FOUND",
                          "hole_ids contains id " + std::to_string(id) +
                              " which is not a current boundary cycle id; list the holes again");
      }
    }
    for (const auto& item : stats) {
      if (std::binary_search(selection.ids.begin(), selection.ids.end(), item.hole_id) &&
          item.edge_count > limit) {
        throw WorkerError("PRECONDITION_FAILED", "HOLE_EXCEEDS_MAX_HOLE_EDGES",
                          "Selected hole " + std::to_string(item.hole_id) + " has " +
                              std::to_string(item.edge_count) + " edges, above max_hole_edges");
      }
    }
  }
  for (const auto& item : stats) {
    plan.ids.push_back(item.hole_id);
    plan.fill.push_back(hole_matches_selection(selection, item, limit));
  }
  return plan;
}

void record_hole_selection(Json& metrics, const HoleSelection& selection,
                           std::vector<std::size_t> filled_ids, std::vector<std::size_t> skipped_ids) {
  std::sort(filled_ids.begin(), filled_ids.end());
  std::sort(skipped_ids.begin(), skipped_ids.end());
  metrics["filled_hole_ids"] = filled_ids;
  metrics["skipped_hole_ids"] = skipped_ids;
  Json description = {{"mode", selection.by_ids ? "hole_ids" : "filters"}};
  if (selection.by_ids) {
    description["hole_ids"] = selection.ids;
    description["source_mesh_sha256"] = selection.source_sha256;
  }
  if (selection.has_max_perimeter) description["max_hole_perimeter"] = selection.max_perimeter;
  if (selection.has_max_area) description["max_hole_area"] = selection.max_area;
  metrics["hole_selection"] = std::move(description);
}

struct RefineFairParameters {
  std::size_t limit;
  double density_control_factor;
  unsigned int fairing_continuity;
};

RefineFairParameters refine_fair_parameters(const Json& parameters) {
  if (!parameters.is_object() || !parameters.contains("max_hole_edges") ||
      !parameters.contains("density_control_factor") || !parameters.contains("fairing_continuity")) {
    throw WorkerError("INVALID_INPUT", "INVALID_REFINE_FAIR_PARAMETERS",
                      "max_hole_edges, density_control_factor and fairing_continuity are required");
  }
  (void)parse_hole_selection(parameters, true);
  const auto& factor = parameters["density_control_factor"];
  const auto& continuity = parameters["fairing_continuity"];
  if (!factor.is_number() || !std::isfinite(factor.get<double>()) || factor.get<double>() < 1.0 ||
      factor.get<double>() > 4.0) {
    throw WorkerError("INVALID_INPUT", "INVALID_DENSITY_CONTROL_FACTOR",
                      "density_control_factor must be a number in [1, 4]");
  }
  if (!continuity.is_number_unsigned() || continuity.get<std::uint64_t>() > 2) {
    throw WorkerError("INVALID_INPUT", "INVALID_FAIRING_CONTINUITY",
                      "fairing_continuity must be an integer in [0, 2]");
  }
  return {required_hole_limit(parameters), factor.get<double>(),
          static_cast<unsigned int>(continuity.get<std::uint64_t>())};
}

void require_empty_parameters(const Json& parameters) {
  if (!parameters.is_object() || !parameters.empty()) {
    throw WorkerError("INVALID_INPUT", "UNEXPECTED_PARAMETERS",
                      "This repair operation accepts no parameters");
  }
}

}  // namespace

HoleSelection parse_hole_selection(const Json& parameters, bool refine_fair, const std::string& unit) {
  HoleSelection selection;
  if (!parameters.is_object()) {
    throw WorkerError("INVALID_INPUT", "INVALID_HOLE_SELECTION", "Hole-fill parameters must be an object");
  }
  for (auto it = parameters.begin(); it != parameters.end(); ++it) {
    const auto& key = it.key();
    const bool known = key == "max_hole_edges" || key == "hole_ids" || key == "source_mesh_sha256" ||
                       key == "max_hole_perimeter" ||
                       key == "max_hole_area" ||
                       (refine_fair && (key == "density_control_factor" || key == "fairing_continuity"));
    if (!known) {
      throw WorkerError("INVALID_INPUT", "UNSUPPORTED_PARAMETER", "Unsupported hole-fill parameter: " + key);
    }
  }
  if (parameters.contains("hole_ids")) {
    const auto& ids = parameters["hole_ids"];
    if (!ids.is_array() || ids.empty() || ids.size() > kMaximumHoleIds) {
      throw WorkerError("INVALID_INPUT", "INVALID_HOLE_IDS",
                        "hole_ids must be a non-empty array of at most 10000 unsigned integers");
    }
    for (const auto& item : ids) {
      if (!item.is_number_unsigned()) {
        throw WorkerError("INVALID_INPUT", "INVALID_HOLE_IDS", "hole_ids must contain unsigned integers");
      }
      selection.ids.push_back(static_cast<std::size_t>(item.get<std::uint64_t>()));
    }
    std::sort(selection.ids.begin(), selection.ids.end());
    if (std::adjacent_find(selection.ids.begin(), selection.ids.end()) != selection.ids.end()) {
      throw WorkerError("INVALID_INPUT", "INVALID_HOLE_IDS", "hole_ids must be unique");
    }
    selection.active = true;
    selection.by_ids = true;
  }
  if (parameters.contains("source_mesh_sha256")) {
    const auto& digest = parameters["source_mesh_sha256"];
    bool hex = digest.is_string() && digest.get<std::string>().size() == 64;
    if (hex) {
      for (const char c : digest.get<std::string>())
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) hex = false;
    }
    if (!hex) {
      throw WorkerError("INVALID_INPUT", "INVALID_SOURCE_MESH_SHA256",
                        "source_mesh_sha256 must be 64 lowercase hex characters");
    }
    if (!selection.by_ids) {
      throw WorkerError("INVALID_INPUT", "HOLE_SELECTION_CONFLICT",
                        "source_mesh_sha256 binds hole_ids and is only accepted together with hole_ids");
    }
    selection.source_sha256 = digest.get<std::string>();
  } else if (selection.by_ids) {
    throw WorkerError("INVALID_INPUT", "HOLE_IDS_SOURCE_REQUIRED",
                      "hole_ids require source_mesh_sha256 (results.source_mesh_sha256 of the "
                      "mesh.analysis.boundary_cycles report that listed them)");
  }
  const auto positive = [&](const char* key, const std::string& expected_unit, bool& present, double& value) {
    if (!parameters.contains(key)) return;
    const auto& item = parameters[key];
    if (!item.is_object() || item.size() != 2 || !item.contains("value") || !item.contains("unit") ||
        !item["value"].is_number() || !item["unit"].is_string() ||
        !std::isfinite(item["value"].get<double>()) || item["value"].get<double>() <= 0.0) {
      throw WorkerError("INVALID_INPUT", "INVALID_HOLE_FILTER",
                        std::string(key) + " must be {value > 0, unit}");
    }
    if (!unit.empty() && item["unit"].get<std::string>() != expected_unit) {
      throw WorkerError("INVALID_INPUT", "HOLE_FILTER_UNIT_MISMATCH",
                        std::string(key) + " must use unit " + expected_unit +
                            " (the mesh unit); no implicit conversion");
    }
    present = true;
    value = item["value"].get<double>();
  };
  positive("max_hole_perimeter", unit, selection.has_max_perimeter, selection.max_perimeter);
  positive("max_hole_area", unit + "^2", selection.has_max_area, selection.max_area);
  if (selection.has_max_perimeter || selection.has_max_area) {
    if (selection.by_ids) {
      throw WorkerError("INVALID_INPUT", "HOLE_SELECTION_CONFLICT",
                        "Use either hole_ids or the max_hole_perimeter/max_hole_area filters, not both");
    }
    selection.active = true;
  }
  return selection;
}

void require_hole_ids_source(const HoleSelection& selection, const std::string& actual_sha256,
                             const std::string& error_class) {
  if (!selection.by_ids || selection.source_sha256 == actual_sha256) return;
  throw WorkerError(error_class, "HOLE_IDS_SOURCE_MISMATCH",
                    "hole_ids were listed on mesh " + selection.source_sha256 +
                        " but the input mesh is " + actual_sha256 +
                        "; hole ids are not portable between meshes, list the holes of this mesh again");
}

HoleCycleStats hole_cycle_stats(const std::vector<std::size_t>& cycle,
                                const std::vector<RepairPoint>& points) {
  HoleCycleStats stats;
  const auto count = cycle.size();
  stats.edge_count = count;
  if (count == 0) return stats;
  const auto minimum = static_cast<std::size_t>(std::min_element(cycle.begin(), cycle.end()) - cycle.begin());
  stats.hole_id = cycle[minimum];
  // Rotate so the sum order is independent of the traversal start.
  std::vector<std::array<double, 3>> ring;
  ring.reserve(count);
  for (std::size_t k = 0; k < count; ++k) {
    const auto& p = points[cycle[(minimum + k) % count]];
    ring.push_back({p.x(), p.y(), p.z()});
  }
  std::array<double, 3> centroid = {0, 0, 0};
  for (const auto& p : ring) for (int a = 0; a < 3; ++a) centroid[a] += p[a];
  for (int a = 0; a < 3; ++a) centroid[a] /= static_cast<double>(count);
  double perimeter = 0;
  std::array<double, 3> normal = {0, 0, 0};
  for (std::size_t k = 0; k < count; ++k) {
    const auto& p = ring[k];
    const auto& q = ring[(k + 1) % count];
    const double dx = q[0] - p[0], dy = q[1] - p[1], dz = q[2] - p[2];
    perimeter += std::sqrt(dx * dx + dy * dy + dz * dz);
    const double ax = p[0] - centroid[0], ay = p[1] - centroid[1], az = p[2] - centroid[2];
    const double bx = q[0] - centroid[0], by = q[1] - centroid[1], bz = q[2] - centroid[2];
    normal[0] += ay * bz - az * by;
    normal[1] += az * bx - ax * bz;
    normal[2] += ax * by - ay * bx;
  }
  stats.perimeter = perimeter;
  stats.area = 0.5 * std::sqrt(normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2]);
  return stats;
}

bool hole_matches_selection(const HoleSelection& selection, const HoleCycleStats& stats,
                            std::size_t max_hole_edges) {
  if (stats.edge_count > max_hole_edges) return false;
  if (selection.by_ids) {
    return std::binary_search(selection.ids.begin(), selection.ids.end(), stats.hole_id);
  }
  if (selection.has_max_perimeter && stats.perimeter > selection.max_perimeter) return false;
  if (selection.has_max_area && stats.area > selection.max_area) return false;
  return true;
}

std::size_t hole_edge_limit(const Json& parameters) { return required_hole_limit(parameters); }

std::string operation_id(RepairKind kind) {
  switch (kind) {
    case RepairKind::kOrient: return "mesh.repair.orient";
    case RepairKind::kStitchBorders: return "mesh.repair.stitch_borders";
    case RepairKind::kRemoveDegenerate: return "mesh.repair.remove_degenerate";
    case RepairKind::kFillHoles: return "mesh.repair.fill_holes";
    case RepairKind::kFillHolesRefineFair: return "mesh.repair.fill_holes_refine_fair";
    case RepairKind::kPolygonSoup: return "mesh.repair.polygon_soup";
    case RepairKind::kManifoldPreprocess: return "mesh.repair.manifold_preprocess";
  }
  throw std::logic_error("Unknown repair kind");
}

std::string validator_id(RepairKind kind) {
  switch (kind) {
    case RepairKind::kOrient: return "mesh.validate.repair_orientation";
    case RepairKind::kStitchBorders: return "mesh.validate.repair_stitch_borders";
    case RepairKind::kRemoveDegenerate: return "mesh.validate.repair_remove_degenerate";
    case RepairKind::kFillHoles: return "mesh.validate.repair_fill_holes";
    case RepairKind::kFillHolesRefineFair: return "mesh.validate.repair_fill_holes_refine_fair";
    case RepairKind::kPolygonSoup: return "mesh.validate.repair_polygon_soup";
    case RepairKind::kManifoldPreprocess: return "mesh.validate.repair_manifold_preprocess";
  }
  throw std::logic_error("Unknown repair kind");
}

void require_request(const Request& request, RepairKind kind, bool validator) {
  if (request.kernel != "package_recommended") {
    throw WorkerError("UNSUPPORTED_ADAPTER", "OUTPUT_PRECISION_PROFILE_UNSUPPORTED",
                      "Mesh repair adapters support package_recommended only");
  }
  const std::size_t expected = validator ? 2 : 1;
  if (request.inputs.size() != expected) {
    throw WorkerError("INVALID_INPUT", "INPUT_COUNT_MISMATCH",
                      "Repair request has the wrong number of inputs");
  }
  if (!validator) {
    if (kind == RepairKind::kFillHoles) {
      (void)required_hole_limit(request.parameters);
      (void)parse_hole_selection(request.parameters, false);
    } else if (kind == RepairKind::kFillHolesRefineFair) {
      (void)refine_fair_parameters(request.parameters);
    } else if (kind == RepairKind::kPolygonSoup) {
      if (!request.parameters.is_object() ||
          !request.parameters.contains("duplicate_polygon_policy") ||
          !request.parameters.contains("require_same_orientation") ||
          !request.parameters["require_same_orientation"].is_boolean() ||
          request.parameters.size() != 2) {
        throw WorkerError("INVALID_INPUT", "INVALID_POLYGON_SOUP_PARAMETERS",
                          "polygon soup repair requires duplicate_polygon_policy and require_same_orientation");
      }
      (void)duplicate_policy(request.parameters);
    } else {
      require_empty_parameters(request.parameters);
    }
  } else {
    if (kind == RepairKind::kFillHoles) {
      (void)required_hole_limit(request.parameters);
      (void)parse_hole_selection(request.parameters, false);
    } else if (kind == RepairKind::kFillHolesRefineFair) (void)refine_fair_parameters(request.parameters);
    else if (kind == RepairKind::kPolygonSoup) (void)duplicate_policy(request.parameters);
    else require_empty_parameters(request.parameters);
  }
}

Soup read_soup(const ArtifactInput& input,
               const std::vector<std::string>& accepted_types) {
  if (std::find(accepted_types.begin(), accepted_types.end(), input.type) == accepted_types.end() ||
      input.format != "off" ||
      (input.unit != "mm" && input.unit != "cm" && input.unit != "m")) {
    throw WorkerError("INVALID_INPUT", "INPUT_SHAPE_MISMATCH",
                      "Repair input type/format/unit does not match its operation");
  }
  const auto tokens = off_tokens(verified_bytes(input));
  if (tokens.size() < 4 || tokens[0] != "OFF") {
    throw WorkerError("INVALID_INPUT", "MALFORMED_OFF", "Expected ASCII OFF input");
  }
  const auto vertices = parse_size(tokens[1], "vertex count");
  const auto faces = parse_size(tokens[2], "face count");
  (void)parse_size(tokens[3], "edge count");
  if (vertices == 0 || faces == 0 || vertices > kMaximumVertices || faces > kMaximumFaces) {
    throw WorkerError("RESOURCE_LIMIT", "OFF_ELEMENT_LIMIT_EXCEEDED",
                      "Repair OFF must be nonempty and within element limits");
  }
  std::size_t cursor = 4;
  Soup soup;
  soup.unit = input.unit;
  soup.sha256 = input.sha256;
  soup.points.reserve(vertices);
  for (std::size_t i = 0; i < vertices; ++i) {
    if (cursor + 3 > tokens.size()) throw WorkerError("INVALID_INPUT", "MALFORMED_OFF", "Truncated OFF vertices");
    soup.points.emplace_back(parse_coordinate(tokens[cursor]),
                             parse_coordinate(tokens[cursor + 1]),
                             parse_coordinate(tokens[cursor + 2]));
    cursor += 3;
  }
  soup.faces.reserve(faces);
  for (std::size_t i = 0; i < faces; ++i) {
    if (cursor >= tokens.size() || parse_size(tokens[cursor++], "face size") != 3 ||
        cursor + 3 > tokens.size()) {
      throw WorkerError("INVALID_INPUT", "NON_TRIANGLE_OFF",
                        "Bounded repair profile accepts triangle OFF only");
    }
    std::vector<std::size_t> face;
    for (int j = 0; j < 3; ++j) {
      const auto value = parse_size(tokens[cursor++], "face index");
      if (value >= vertices) throw WorkerError("INVALID_INPUT", "OFF_INDEX_OUT_OF_RANGE", "OFF face index is out of range");
      face.push_back(value);
    }
    soup.faces.push_back(std::move(face));
  }
  if (cursor != tokens.size()) throw WorkerError("INVALID_INPUT", "MALFORMED_OFF", "Unexpected trailing OFF fields");
  validate_numeric_profile(soup);
  return soup;
}

RepairResult compute_repair(RepairKind kind, const Soup& source,
                            const Json& parameters) {
  RepairResult result;
  result.metrics["source"] = soup_statistics(source);
  if (kind == RepairKind::kOrient) {
    require_empty_parameters(parameters);
    result.soup = source;
    for (const auto& face : source.faces) {
      // orient_polygon_soup does not terminate on repeated-index polygons.
      if (face[0] == face[1] || face[1] == face[2] || face[2] == face[0]) {
        throw WorkerError("PRECONDITION_FAILED", "COMBINATORIALLY_DEGENERATE_FACE",
                          "Orientation requires faces without repeated vertex indices; "
                          "run mesh.repair.remove_degenerate first");
      }
    }
    const bool orientable = PMP::orient_polygon_soup(result.soup.points, result.soup.faces);
    if (!orientable || !PMP::is_polygon_soup_a_polygon_mesh(result.soup.faces)) {
      throw WorkerError("PRECONDITION_FAILED", "POLYGON_SOUP_NOT_ORIENTABLE",
                        "Polygon soup cannot be oriented as a polygon mesh");
    }
    auto mesh = mesh_from_soup(result.soup, "Oriented soup");
    if (CGAL::is_closed(mesh)) PMP::orient_to_bound_a_volume(mesh);
    result.soup = soup_from_mesh(mesh);
    result.metrics["orientation_changed"] = !soup_equal(source, result.soup);
  } else if (kind == RepairKind::kStitchBorders) {
    require_empty_parameters(parameters);
    auto mesh = mesh_from_soup(source, "Stitch source");
    const auto stitched = PMP::stitch_borders(mesh);
    result.soup = soup_from_mesh(mesh);
    result.metrics["stitched_pair_count"] = stitched;
  } else if (kind == RepairKind::kRemoveDegenerate) {
    require_empty_parameters(parameters);
    Soup filtered = source;
    filtered.faces.erase(std::remove_if(filtered.faces.begin(), filtered.faces.end(),
      [](const auto& face) { return face[0] == face[1] || face[1] == face[2] || face[2] == face[0]; }), filtered.faces.end());
    if (filtered.faces.empty()) throw WorkerError("PRECONDITION_FAILED", "REPAIR_WOULD_EMPTY_MESH", "No non-combinatorial-degenerate faces remain");
    auto mesh = mesh_from_soup(filtered, "Degenerate-repair source");
    const bool faces_removed = PMP::remove_degenerate_faces(mesh);
    const bool edges_removed = PMP::remove_degenerate_edges(mesh);
    PMP::remove_isolated_vertices(mesh);
    if (mesh.number_of_faces() == 0) throw WorkerError("PRECONDITION_FAILED", "REPAIR_WOULD_EMPTY_MESH", "Degenerate repair removed every face");
    result.soup = soup_from_mesh(mesh);
    if (degenerate_faces(result.soup) != 0) {
      throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_REPAIR_INCOMPLETE",
                        "CGAL could not remove every degenerate face; no candidate is published");
    }
    result.metrics["remove_degenerate_faces_complete"] = faces_removed;
    result.metrics["remove_degenerate_edges_complete"] = edges_removed;
  } else if (kind == RepairKind::kFillHoles) {
    auto mesh = mesh_from_soup(source, "Hole-fill source");
    const auto limit = required_hole_limit(parameters);
    const auto selection = parse_hole_selection(parameters, false, source.unit);
    require_hole_ids_source(selection, source.sha256, "PRECONDITION_FAILED");
    std::vector<RepairMesh::Halfedge_index> cycles;
    CGAL::extract_boundary_cycles(mesh, std::back_inserter(cycles));
    const auto plan = plan_hole_selection(mesh, cycles, selection, limit);
    std::size_t filled = 0;
    std::size_t skipped = 0;
    std::size_t added_faces = 0;
    std::vector<std::size_t> filled_ids, skipped_ids;
    for (std::size_t cycle_index = 0; cycle_index < cycles.size(); ++cycle_index) {
      const auto halfedge = cycles[cycle_index];
      std::size_t length = 0;
      auto cursor = halfedge;
      do { ++length; cursor = next(cursor, mesh); } while (cursor != halfedge && length <= kMaximumFaces);
      const bool fill = selection.active ? static_cast<bool>(plan.fill[cycle_index]) : length <= limit;
      if (!fill) {
        ++skipped;
        if (selection.active) skipped_ids.push_back(plan.ids[cycle_index]);
        continue;
      }
      std::vector<RepairMesh::Face_index> patch;
      // Disable the cubic-time fallback so run time stays bounded by max_hole_edges.
      PMP::triangulate_hole(mesh, halfedge, CGAL::parameters::face_output_iterator(std::back_inserter(patch))
                                                 .do_not_use_cubic_algorithm(true));
      if (patch.empty()) throw WorkerError("PRECONDITION_FAILED", "HOLE_TRIANGULATION_FAILED", "CGAL did not create a hole patch");
      ++filled;
      if (selection.active) filled_ids.push_back(plan.ids[cycle_index]);
      added_faces += patch.size();
    }
    if (filled == 0) throw WorkerError("PRECONDITION_FAILED", "NO_ELIGIBLE_HOLES", "No boundary cycle is eligible for bounded hole filling");
    result.soup = soup_from_mesh(mesh);
    result.metrics["filled_hole_count"] = filled;
    result.metrics["skipped_hole_count"] = skipped;
    result.metrics["added_face_count"] = added_faces;
    result.metrics["max_hole_edges"] = limit;
    if (selection.active) record_hole_selection(result.metrics, selection, filled_ids, skipped_ids);
  } else if (kind == RepairKind::kFillHolesRefineFair) {
    auto mesh = mesh_from_soup(source, "Refine-and-fair source");
    const auto settings = refine_fair_parameters(parameters);
    const auto selection = parse_hole_selection(parameters, true, source.unit);
    require_hole_ids_source(selection, source.sha256, "PRECONDITION_FAILED");
    std::vector<RepairMesh::Halfedge_index> cycles;
    CGAL::extract_boundary_cycles(mesh, std::back_inserter(cycles));
    const auto plan = plan_hole_selection(mesh, cycles, selection, settings.limit);
    std::size_t filled = 0, skipped = 0, added_faces = 0, added_vertices = 0, fairing_failures = 0;
    std::vector<std::size_t> filled_ids, skipped_ids;
    for (std::size_t cycle_index = 0; cycle_index < cycles.size(); ++cycle_index) {
      const auto halfedge = cycles[cycle_index];
      std::size_t length = 0;
      auto cursor = halfedge;
      do { ++length; cursor = next(cursor, mesh); } while (cursor != halfedge && length <= kMaximumFaces);
      const bool fill = selection.active ? static_cast<bool>(plan.fill[cycle_index]) : length <= settings.limit;
      if (!fill) {
        ++skipped;
        if (selection.active) skipped_ids.push_back(plan.ids[cycle_index]);
        continue;
      }
      std::vector<RepairMesh::Face_index> patch_faces;
      std::vector<RepairMesh::Vertex_index> patch_vertices;
      const auto outcome = PMP::triangulate_refine_and_fair_hole(
          mesh, halfedge, std::back_inserter(patch_faces), std::back_inserter(patch_vertices),
          CGAL::parameters::density_control_factor(settings.density_control_factor)
              .fairing_continuity(settings.fairing_continuity));
      if (patch_faces.empty()) throw WorkerError("PRECONDITION_FAILED", "HOLE_TRIANGULATION_FAILED", "CGAL did not create a hole patch");
      if (!std::get<0>(outcome)) ++fairing_failures;
      ++filled;
      if (selection.active) filled_ids.push_back(plan.ids[cycle_index]);
      added_faces += patch_faces.size();
      added_vertices += patch_vertices.size();
    }
    if (filled == 0) throw WorkerError("PRECONDITION_FAILED", "NO_ELIGIBLE_HOLES", "No boundary cycle is eligible for bounded hole filling");
    if (fairing_failures != 0) {
      throw WorkerError("PRECONDITION_FAILED", "FAIRING_FAILED", "CGAL could not fair every hole patch; no candidate is published");
    }
    result.soup = soup_from_mesh(mesh);
    result.metrics["filled_hole_count"] = filled;
    result.metrics["skipped_hole_count"] = skipped;
    result.metrics["added_face_count"] = added_faces;
    result.metrics["added_vertex_count"] = added_vertices;
    result.metrics["max_hole_edges"] = settings.limit;
    result.metrics["density_control_factor"] = settings.density_control_factor;
    result.metrics["fairing_continuity"] = settings.fairing_continuity;
    if (selection.active) record_hole_selection(result.metrics, selection, filled_ids, skipped_ids);
  } else if (kind == RepairKind::kPolygonSoup) {
    result.soup = source;
    const auto policy = duplicate_policy(parameters);
    if (!parameters.is_object() || parameters.size() != 2 ||
        !parameters.contains("require_same_orientation") ||
        !parameters["require_same_orientation"].is_boolean()) {
      throw WorkerError("INVALID_INPUT", "INVALID_POLYGON_SOUP_PARAMETERS", "Invalid polygon soup repair parameters");
    }
    PMP::repair_polygon_soup(
        result.soup.points, result.soup.faces,
        CGAL::parameters::erase_policy(policy).require_same_orientation(
            parameters["require_same_orientation"].get<bool>()));
    if (result.soup.points.empty() || result.soup.faces.empty()) {
      throw WorkerError("PRECONDITION_FAILED", "REPAIR_WOULD_EMPTY_SOUP", "Polygon soup repair produced empty geometry");
    }
    result.metrics["duplicate_polygon_policy"] = parameters["duplicate_polygon_policy"];
    result.metrics["require_same_orientation"] = parameters["require_same_orientation"];
  } else {
    require_empty_parameters(parameters);
    auto mesh = nonmanifold_mesh_from_soup(source);
    std::vector<std::vector<RepairMesh::Vertex_index>> duplicated;
    const auto created = PMP::duplicate_non_manifold_vertices(
        mesh, CGAL::parameters::output_iterator(std::back_inserter(duplicated)));
    result.soup = soup_from_mesh(mesh);
    result.metrics["duplicated_vertex_count"] = created;
    result.metrics["repaired_vertex_group_count"] = duplicated.size();
  }
  result.metrics["candidate"] = soup_statistics(result.soup);
  return result;
}

bool soup_equal(const Soup& first, const Soup& second) {
  if (first.faces != second.faces || first.points.size() != second.points.size()) return false;
  for (std::size_t i = 0; i < first.points.size(); ++i) {
    if (first.points[i].x() != second.points[i].x() ||
        first.points[i].y() != second.points[i].y() ||
        first.points[i].z() != second.points[i].z()) return false;
  }
  return true;
}

Json soup_statistics(const Soup& soup) {
  Json result = {{"vertex_count", soup.points.size()},
                 {"face_count", soup.faces.size()},
                 {"degenerate_face_count", degenerate_faces(soup)},
                 {"duplicate_face_count", duplicate_faces(soup)},
                 {"duplicate_point_count", duplicate_points(soup)},
                 {"unused_point_count", unused_points(soup)},
                 {"polygon_mesh_constructible", PMP::is_polygon_soup_a_polygon_mesh(soup.faces)}};
  if (result["polygon_mesh_constructible"].get<bool>() && !soup.faces.empty()) {
    try { result["mesh"] = mesh_metrics(mesh_from_soup(soup, "Statistics input")); }
    catch (const WorkerError&) { result["polygon_mesh_constructible"] = false; }
  }
  return result;
}

std::filesystem::path write_soup_output(const Request& request,
                                        const Soup& soup,
                                        const std::string& filename) {
  const auto root = checked_output_dir(request);
  const auto destination = output_path(root, filename);
  const auto temporary = output_path(root, "." + staging_filename_token(request.request_id) + ".tmp");
  try {
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    stream.imbue(std::locale::classic());
    if (!stream) throw std::runtime_error("open");
    stream << "OFF\n" << soup.points.size() << ' ' << soup.faces.size() << " 0\n" << std::setprecision(17);
    for (const auto& point : soup.points) stream << point.x() << ' ' << point.y() << ' ' << point.z() << '\n';
    for (const auto& face : soup.faces) {
      stream << face.size();
      for (const auto index : face) stream << ' ' << index;
      stream << '\n';
    }
    stream.flush();
    if (!stream) throw std::runtime_error("write");
    stream.close();
    commit_output(temporary, destination);
    return destination;
  } catch (...) {
    std::error_code error;
    std::filesystem::remove(temporary, error);
    throw WorkerError("PROTOCOL_ERROR", "OUTPUT_WRITE_FAILED", "Unable to write repair OFF output");
  }
}

std::filesystem::path write_json_output(const Request& request,
                                        const Json& value,
                                        const std::string& filename) {
  const auto root = checked_output_dir(request);
  const auto destination = output_path(root, filename);
  const auto temporary = output_path(root, "." + staging_filename_token(request.request_id) + ".tmp");
  try {
    std::ofstream stream(temporary, std::ios::binary | std::ios::trunc);
    if (!stream) throw std::runtime_error("open");
    stream << value.dump() << '\n';
    stream.flush();
    if (!stream) throw std::runtime_error("write");
    stream.close();
    commit_output(temporary, destination);
    return destination;
  } catch (...) {
    std::error_code error;
    std::filesystem::remove(temporary, error);
    throw WorkerError("PROTOCOL_ERROR", "OUTPUT_WRITE_FAILED", "Unable to write repair validation output");
  }
}

}  // namespace cgal_master::wave_a_repair
