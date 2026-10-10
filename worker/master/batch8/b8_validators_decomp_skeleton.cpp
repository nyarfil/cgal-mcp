// Independent validators for mesh.decompose.approx_convex (7.8.02) and the two mean curvature flow
// skeleton operations (7.8.03). No CGAL header is included: convexity, containment, volumes, the
// inside-the-mesh parity test and the graph invariants are all evaluated with GMP rationals on the
// raw binary64 data.

#include "b8_common.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>

namespace cgal_master::batch8 {
namespace {

using batch2::concluded;
using batch2::cross;
using batch2::dot;
using batch2::index_of;
using batch2::require_member;
using batch2::vec;
using batch2::vinfo;
using query_ops::read_raw_mesh;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;

constexpr const char* kAcdTolerance =
    "covering slack: a sampled surface point of the input (vertex or face centroid) may lie outside a part by at "
    "most one voxel edge (longest bounding-box side / (floor(cbrt(maximum_number_of_voxels)) - 3)) measured "
    "perpendicular to the violated face planes of that part";

std::size_t integer_cube_root(std::size_t n) {
  std::size_t r = 0;
  while ((r + 1) * (r + 1) * (r + 1) <= n) ++r;
  return r;
}

RawMesh read_part(const Json& part, std::size_t index) {
  const std::string context = "part " + std::to_string(index);
  if (!part.is_object()) validation_failure("REPORT_VALUE_INVALID", context + " must be an object");
  RawMesh mesh;
  mesh.vertices = read_vertex_array(require_member(part, "vertices", context), context + " vertices");
  const auto& faces = require_member(part, "faces", context);
  if (!faces.is_array() || faces.size() < 4) {
    validation_failure("PART_NOT_CLOSED_POLYHEDRON", context + " needs at least four triangles");
  }
  for (const auto& face : faces) {
    if (!face.is_array() || face.size() != 3) {
      validation_failure("REPORT_VALUE_INVALID", context + " faces must be index triples");
    }
    mesh.faces.push_back({index_of(face[0], mesh.vertices.size(), context), index_of(face[1], mesh.vertices.size(), context),
                          index_of(face[2], mesh.vertices.size(), context)});
  }
  return mesh;
}

struct Plane {
  Vec normal;  // (b - a) x (c - a), outward for a positively oriented part
  Vec anchor;
};

// ---- 7.8.02 ---------------------------------------------------------------------------------------
Json validate_decomposition(const Request& request) {
  const std::string validator = "mesh.validate.approx_convex";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"maximum_number_of_convex_volumes", "maximum_number_of_voxels", "maximum_depth",
                                    "volume_error", "refitting", "split_at_concavity"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "approximate_convex_decomposition");
  const auto raw = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  batch2::require_triangle_faces(raw, "The mesh", kMaximumDecompositionFaces);
  const auto topology = analyze_topology(raw);
  if (topology.unreferenced_vertex || !topology.oriented_manifold || !topology.closed) {
    validation_failure("MESH_NOT_CLOSED", "The mesh must be a closed oriented 2-manifold");
  }
  const Q mesh_volume = signed_volume(raw);
  if (mesh_volume <= 0) validation_failure("MESH_NOT_OUTWARD", "The mesh faces must be oriented outward");
  Json checks;
  const auto results = batch2::check_report_frame(report, "mesh.decompose.approx_convex", request.parameters,
                                                  {{"mesh_sha256", &request.inputs[1]}}, checks);
  if (require_member(results, "distance_unit", "results") != request.inputs[1].unit) {
    validation_failure("UNIT_MISMATCH", "The report distance unit differs from the mesh unit");
  }
  checks["distance_unit_matches_mesh"] = true;
  const auto& parts_json = require_member(results, "parts", "results");
  const std::size_t limit = request.parameters.at("maximum_number_of_convex_volumes").get<std::size_t>();
  if (!parts_json.is_array() || parts_json.empty()) validation_failure("PART_COUNT", "The decomposition has no part");
  if (parts_json.size() > limit) {
    validation_failure("PART_COUNT_EXCEEDS_LIMIT", "More parts than maximum_number_of_convex_volumes");
  }
  checks["part_count_within_limit"] = true;

  // Mesh bounding box and the declared covering tolerance (one voxel edge).
  Q low[3], high[3];
  for (std::size_t k = 0; k < 3; ++k) {
    low[k] = high[k] = query_ops::exact_of(raw.vertices[0][k]);
    for (const auto& v : raw.vertices) {
      const Q c = query_ops::exact_of(v[k]);
      if (c < low[k]) low[k] = c;
      if (c > high[k]) high[k] = c;
    }
  }
  Q longest = high[0] - low[0];
  for (std::size_t k = 1; k < 3; ++k) {
    if (high[k] - low[k] > longest) longest = high[k] - low[k];
  }
  const std::size_t axis_cells = integer_cube_root(request.parameters.at("maximum_number_of_voxels").get<std::size_t>());
  if (axis_cells <= 3) validation_failure("INVALID_PARAMETER", "maximum_number_of_voxels is too small");
  const Q tolerance = longest / Q(static_cast<unsigned long>(axis_cells - 3));

  std::vector<std::vector<Plane>> parts;
  Q total_volume;
  for (std::size_t index = 0; index < parts_json.size(); ++index) {
    const auto part = read_part(parts_json[index], index);
    const auto topo = analyze_topology(part);
    if (topo.unreferenced_vertex || !topo.closed || topo.components != 1 || topo.euler() != 2) {
      validation_failure("PART_NOT_CLOSED_POLYHEDRON", "A part must be a closed oriented sphere-like triangle mesh");
    }
    std::vector<Plane> planes;
    for (const auto& face : part.faces) {
      const Vec a = vec(part.vertices[face[0]]), b = vec(part.vertices[face[1]]), c = vec(part.vertices[face[2]]);
      const Vec n = cross(b - a, c - a);
      if (batch2::is_zero(n)) validation_failure("DEGENERATE_PART_FACE", "A part has a zero-area face");
      planes.push_back({n, a});
    }
    const Q volume = signed_volume(part);
    if (volume <= 0) validation_failure("PART_NOT_OUTWARD", "A part must be positively oriented with positive volume");
    for (const auto& plane : planes) {
      for (const auto& v : part.vertices) {
        if (dot(plane.normal, vec(v) - plane.anchor) > 0) {
          validation_failure("PART_NOT_CONVEX", "A part vertex lies outside a face plane of the same part");
        }
      }
    }
    for (const auto& v : part.vertices) {
      for (std::size_t k = 0; k < 3; ++k) {
        const Q c = query_ops::exact_of(v[k]);
        if (c < low[k] - tolerance || c > high[k] + tolerance) {
          validation_failure("PART_OUTSIDE_BOUNDING_BOX", "A part leaves the input bounding box by more than the tolerance");
        }
      }
    }
    total_volume += volume;
    parts.push_back(std::move(planes));
  }
  checks["parts_are_closed_outward_triangle_meshes"] = true;
  checks["parts_are_convex"] = true;
  checks["parts_stay_in_expanded_bounding_box"] = true;

  // Covering: every sampled surface point of the input is within the declared slack of some part.
  const Q tolerance_squared = tolerance * tolerance;
  long double worst = 0;
  std::size_t samples = 0;
  auto covered = [&](const Vec& p) {
    long double best = 1e300L;
    bool any = false;
    for (const auto& planes : parts) {
      bool inside = true;
      long double slack = 0;
      for (const auto& plane : planes) {
        const Q s = dot(plane.normal, p - plane.anchor);
        if (s > 0) {
          const Q nn = dot(plane.normal, plane.normal);
          if (s * s > tolerance_squared * nn) {
            inside = false;
          }
          slack = std::max(slack, std::sqrt(static_cast<long double>(mpq_class(s * s / nn).get_d())));
        }
      }
      if (inside) {
        any = true;
        best = std::min(best, slack);
      }
    }
    if (any) worst = std::max(worst, best);
    return any;
  };
  for (const auto& v : raw.vertices) {
    ++samples;
    if (!covered(vec(v))) validation_failure("VERTEX_NOT_COVERED", "An input vertex lies outside every part by more than the tolerance");
  }
  Q shell_area;
  for (const auto& face : raw.faces) {
    const Vec a = vec(raw.vertices[face[0]]), b = vec(raw.vertices[face[1]]), c = vec(raw.vertices[face[2]]);
    const Vec n = cross(b - a, c - a);
    const Vec centroid = (Q(1) / 3) * (a + b + c);
    ++samples;
    if (!covered(centroid)) {
      validation_failure("SURFACE_POINT_NOT_COVERED", "A face centroid lies outside every part by more than the tolerance");
    }
    for (const Q* c3 : {&n.x, &n.y, &n.z}) shell_area += (*c3 < 0 ? Q(-*c3) : *c3) / 2;
  }
  checks["input_surface_points_covered_within_tolerance"] = true;

  // Volume accounting (exact): the parts together cannot hold less than the input volume minus a boundary
  // shell of the declared tolerance, nor more than the expanded bounding box.
  if (total_volume < mesh_volume - tolerance * shell_area) {
    validation_failure("VOLUME_TOO_SMALL", "The parts hold less volume than the input minus the tolerance shell");
  }
  checks["total_volume_covers_mesh_volume_up_to_boundary_shell"] = true;
  Q box = 1;
  for (std::size_t k = 0; k < 3; ++k) box *= (high[k] - low[k] + 2 * tolerance);
  if (total_volume > box) validation_failure("VOLUME_TOO_LARGE", "The parts hold more volume than the expanded bounding box");
  checks["total_volume_within_expanded_bounding_box"] = true;

  return concluded(request, validator, checks,
                   {{"part_count", parts.size()},
                    {"mesh_volume", mesh_volume.get_d()},
                    {"total_part_volume", total_volume.get_d()},
                    {"excess_volume_ratio", Q(total_volume / mesh_volume - 1).get_d()},
                    {"covering_tolerance", tolerance.get_d()},
                    {"covering_tolerance_definition", kAcdTolerance},
                    {"largest_covering_slack_of_best_part", static_cast<double>(worst)},
                    {"sampled_surface_points", samples},
                    {"independence", "exact GMP rationals on the raw binary64 data: face-plane convexity, closed-polyhedron "
                                     "topology, signed volumes and plane-slack covering; no CGAL header"}});
}

// ---- 7.8.03 ---------------------------------------------------------------------------------------
std::size_t root_of(std::vector<std::size_t>& parent, std::size_t x) {
  while (parent[x] != x) {
    parent[x] = parent[parent[x]];
    x = parent[x];
  }
  return x;
}

Json validate_skeleton(const Request& request) {
  const std::string validator = "mesh.validate.skeleton";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {}, {"quality_speed_tradeoff", "medially_centered_speed_tradeoff",
                                        "is_medially_centered", "max_iterations"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "mean_curvature_flow_skeleton");
  const auto raw = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  batch2::require_triangle_faces(raw, "The mesh", kMaximumSkeletonFaces);
  const auto topology = analyze_topology(raw);
  if (topology.unreferenced_vertex || !topology.oriented_manifold || !topology.closed) {
    validation_failure("MESH_NOT_CLOSED", "The mesh must be a closed oriented 2-manifold");
  }
  if (signed_volume(raw) <= 0) validation_failure("MESH_NOT_OUTWARD", "The mesh faces must be oriented outward");
  const std::string operation = report.value("operation", std::string());
  if (operation != "mesh.skeletonize.mean_curvature" && operation != "mesh.skeletonize.mean_curvature_flow") {
    validation_failure("PARAMETER_MISMATCH", "Report is not a mean curvature flow skeleton report");
  }
  Json checks;
  const auto results = batch2::check_report_frame(report, operation, request.parameters,
                                                  {{"mesh_sha256", &request.inputs[1]}}, checks);
  if (require_member(results, "distance_unit", "results") != request.inputs[1].unit) {
    validation_failure("UNIT_MISMATCH", "The report distance unit differs from the mesh unit");
  }
  checks["distance_unit_matches_mesh"] = true;
  const auto& vertices_json = require_member(results, "vertices", "results");
  const auto& edges_json = require_member(results, "edges", "results");
  if (!vertices_json.is_array() || vertices_json.empty() || !edges_json.is_array()) {
    validation_failure("REPORT_VALUE_INVALID", "A skeleton needs vertices and an edge list");
  }
  std::vector<V3> points;
  std::vector<std::vector<std::size_t>> surface;
  Json point_array = Json::array();
  for (const auto& vertex : vertices_json) {
    point_array.push_back(require_member(vertex, "point", "skeleton vertex"));
    const auto& ids = require_member(vertex, "surface_vertices", "skeleton vertex");
    if (!ids.is_array()) validation_failure("REPORT_VALUE_INVALID", "surface_vertices must be an array");
    std::vector<std::size_t> row;
    for (const auto& id : ids) row.push_back(index_of(id, raw.vertices.size(), "surface vertex"));
    surface.push_back(std::move(row));
  }
  points = read_vertex_array(point_array, "skeleton points");

  // Inside the input mesh (strictly), by an exact parity test.
  for (std::size_t i = 0; i < points.size(); ++i) {
    const auto location = locate_point(raw, vec(points[i]));
    if (location == Location::Outside) validation_failure("SKELETON_POINT_OUTSIDE", "A skeleton point lies outside the mesh");
    if (location == Location::OnSurface) validation_failure("SKELETON_POINT_ON_SURFACE", "A skeleton point lies on the mesh surface");
    if (location == Location::Ambiguous) validation_failure("POINT_LOCATION_AMBIGUOUS", "The parity test of a skeleton point is ambiguous");
  }
  checks["skeleton_points_inside_mesh"] = true;

  std::set<std::pair<std::size_t, std::size_t>> edges;
  for (const auto& edge : edges_json) {
    if (!edge.is_array() || edge.size() != 2) validation_failure("REPORT_VALUE_INVALID", "An edge must be [a,b]");
    const auto a = index_of(edge[0], points.size(), "edge"), b = index_of(edge[1], points.size(), "edge");
    if (a == b) validation_failure("EDGE_INVALID", "A skeleton edge joins a vertex to itself");
    if (!edges.insert({std::min(a, b), std::max(a, b)}).second) {
      validation_failure("EDGE_INVALID", "A skeleton edge is listed twice");
    }
  }
  checks["skeleton_edges_are_simple"] = true;
  for (const auto& edge : edges) {
    const Vec midpoint = (Q(1) / 2) * (vec(points[edge.first]) + vec(points[edge.second]));
    const auto location = locate_point(raw, midpoint);
    if (location != Location::Inside) {
      validation_failure("SKELETON_EDGE_OUTSIDE", "A skeleton edge midpoint does not lie strictly inside the mesh");
    }
  }
  checks["skeleton_edge_midpoints_inside_mesh"] = true;

  // Connectivity: as many skeleton components as mesh components.
  std::vector<std::size_t> parent(points.size());
  for (std::size_t i = 0; i < parent.size(); ++i) parent[i] = i;
  for (const auto& edge : edges) parent[root_of(parent, edge.first)] = root_of(parent, edge.second);
  std::set<std::size_t> roots;
  for (std::size_t i = 0; i < points.size(); ++i) roots.insert(root_of(parent, i));
  if (roots.size() != topology.components) {
    validation_failure("SKELETON_COMPONENTS_MISMATCH", "The skeleton does not have one connected component per mesh component");
  }
  checks["skeleton_connected_per_mesh_component"] = true;

  // First Betti number of the skeleton graph equals the total genus of the closed mesh.
  std::vector<std::set<std::pair<std::size_t, std::size_t>>> component_edges(topology.components);
  std::vector<std::size_t> component_vertices(topology.components, 0), component_faces(topology.components, 0);
  for (std::size_t v = 0; v < raw.vertices.size(); ++v) ++component_vertices[topology.vertex_component[v]];
  for (const auto& face : raw.faces) {
    const auto c = topology.vertex_component[face[0]];
    ++component_faces[c];
    for (std::size_t k = 0; k < 3; ++k) {
      const auto a = face[k], b = face[(k + 1) % 3];
      component_edges[c].insert({std::min(a, b), std::max(a, b)});
    }
  }
  long long genus = 0;
  for (std::size_t c = 0; c < topology.components; ++c) {
    const long long chi = static_cast<long long>(component_vertices[c]) - static_cast<long long>(component_edges[c].size()) +
                          static_cast<long long>(component_faces[c]);
    if (chi % 2 != 0 || chi > 2) validation_failure("MESH_NOT_CLOSED", "The mesh is not a closed orientable surface");
    genus += (2 - chi) / 2;
  }
  const long long cycles = static_cast<long long>(edges.size()) - static_cast<long long>(points.size()) +
                           static_cast<long long>(roots.size());
  if (cycles != genus) {
    validation_failure("CYCLE_COUNT_MISMATCH", "The number of independent skeleton cycles differs from the mesh genus");
  }
  checks["skeleton_cycle_count_equals_mesh_genus"] = true;

  // The surface vertices of the skeleton vertices form a family of disjoint non-empty sets (CGAL does not
  // promise that every surface vertex is assigned, so only the assigned count is reported).
  std::vector<bool> assigned(raw.vertices.size(), false);
  std::size_t assigned_count = 0;
  for (const auto& row : surface) {
    if (row.empty()) validation_failure("SURFACE_VERTICES_INVALID", "A skeleton vertex has no surface vertex");
    for (const auto id : row) {
      if (assigned[id]) validation_failure("SURFACE_VERTICES_INVALID", "A surface vertex belongs to two skeleton vertices");
      assigned[id] = true;
      ++assigned_count;
    }
  }
  checks["surface_vertex_sets_are_disjoint_and_non_empty"] = true;

  return concluded(request, validator, checks,
                   {{"skeleton_vertex_count", points.size()}, {"skeleton_edge_count", edges.size()},
                    {"skeleton_component_count", roots.size()}, {"mesh_component_count", topology.components},
                    {"skeleton_cycle_count", cycles}, {"mesh_genus", genus}, {"assigned_surface_vertex_count", assigned_count},
                    {"independence", "exact GMP rational ray-parity inside test, union-find components and Euler "
                                     "characteristic of the raw OFF data; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> decomposition_skeleton_validators() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.validate.approx_convex", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      validate_decomposition, {"Convex_decomposition_3"}, "GMP rationals (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "distance_unit_matches_mesh", "part_count_within_limit",
             "parts_are_closed_outward_triangle_meshes", "parts_are_convex", "parts_stay_in_expanded_bounding_box",
             "input_surface_points_covered_within_tolerance", "total_volume_covers_mesh_volume_up_to_boundary_shell",
             "total_volume_within_expanded_bounding_box"},
            {"candidate", "mesh"},
            "exact GMP rationals on the raw binary64 data: face-plane convexity, closed-polyhedron topology, signed "
            "volumes and plane-slack covering; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.skeleton", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      validate_skeleton, {"Surface_mesh_skeletonization"}, "GMP rationals (no CGAL header)",
      vinfo({"parameters_match", "source_matches", "distance_unit_matches_mesh", "skeleton_points_inside_mesh",
             "skeleton_edges_are_simple", "skeleton_edge_midpoints_inside_mesh",
             "skeleton_connected_per_mesh_component", "skeleton_cycle_count_equals_mesh_genus",
             "surface_vertex_sets_are_disjoint_and_non_empty"},
            {"candidate", "mesh"},
            "exact GMP rational ray-parity inside test, union-find components and Euler characteristic of the raw OFF "
            "data; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch8
