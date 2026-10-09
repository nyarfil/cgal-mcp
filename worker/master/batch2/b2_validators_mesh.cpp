// Independent validators for the mesh-processing operations of batch 2: sharp-edge
// detection / segmentation (7.3.05), self-intersection (7.3.07), plane clipping (7.5.03)
// and plane splitting / corefinement (7.5.04). This file includes no CGAL header and calls
// no CGAL algorithm. Every accepted property is re-derived from the raw OFF data and the
// producer report with GMP rational arithmetic; the only floating-point decision (the
// dihedral-angle bound of the feature detector, whose cosine is irrational) is rejected
// when it falls inside a stated relative margin instead of being guessed.

#include "b2_geometry.h"

#include <algorithm>
#include <cmath>
#include <functional>
#include <numeric>

namespace cgal_master::batch2 {
namespace {

using query_ops::exact_of;
using query_ops::integer_parameter;
using query_ops::read_raw_mesh;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::signed_length_parameter;
using query_ops::validation_failure;
using query_ops::vector_parameter;

struct Mesh {
  RawMesh raw;
  std::vector<Tri> tris;
  std::vector<std::size_t> canonical;
};

Mesh load_mesh(const ArtifactInput& input, std::initializer_list<const char*> types, const std::string& context,
               std::size_t maximum) {
  Mesh mesh;
  mesh.raw = read_raw_mesh(input, types);
  require_triangle_faces(mesh.raw, context, maximum);
  for (const auto& face : mesh.raw.faces) {
    mesh.tris.push_back(make_tri(mesh.raw, face));
    if (tri_degenerate(mesh.tris.back())) {
      validation_failure("DEGENERATE_TRIANGLE", context + " has a zero-area triangle");
    }
  }
  std::size_t distinct = 0;
  mesh.canonical = canonical_ids(mesh.raw, distinct);
  return mesh;
}

// Every directed edge (by canonical vertex coordinates) occurs once and so does its reverse.
bool closed_oriented_manifold(const Mesh& mesh) {
  std::map<std::pair<std::size_t, std::size_t>, int> directed;
  for (const auto& face : mesh.raw.faces) {
    for (int i = 0; i < 3; ++i) {
      const auto a = mesh.canonical[face[i]];
      const auto b = mesh.canonical[face[(i + 1) % 3]];
      if (a == b) return false;
      ++directed[{a, b}];
    }
  }
  for (const auto& [edge, count] : directed) {
    if (count != 1) return false;
    const auto opposite = directed.find({edge.second, edge.first});
    if (opposite == directed.end() || opposite->second != 1) return false;
  }
  return true;
}

// ---- 7.3.05 feature detection ------------------------------------------------------------

constexpr double kPi = 3.14159265358979323846;

struct EdgeFaces {
  std::vector<std::size_t> faces;  // incident faces
};

Json run_features_validator(const Request& request) {
  const std::string validator = "mesh.validate.features";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"angle_degrees"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "mesh_features");
  const auto mesh = load_mesh(request.inputs[1], {"TriangleSurfaceMesh"}, "mesh", kMaximumFaces);
  const auto& angle_value = request.parameters.at("angle_degrees");
  if (!angle_value.is_number() || angle_value.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "angle_degrees must be a number");
  }
  const double angle = angle_value.get<double>();
  if (!std::isfinite(angle) || angle < 0 || angle > 180) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "angle_degrees must be in [0,180]");
  }
  Json checks;
  const auto results = check_report_frame(report, "mesh.features.detect", Json{{"angle_degrees", angle}},
                                          {{"mesh_sha256", &request.inputs[1]}}, checks);

  const std::size_t vertex_count = mesh.raw.vertices.size();
  const std::size_t face_count = mesh.raw.faces.size();
  // Undirected edges: key (min,max) of vertex indices -> incident faces and directed usage.
  std::map<std::pair<std::size_t, std::size_t>, EdgeFaces> edges;
  std::map<std::pair<std::size_t, std::size_t>, int> directed;
  for (std::size_t f = 0; f < face_count; ++f) {
    const auto& face = mesh.raw.faces[f];
    for (int i = 0; i < 3; ++i) {
      const auto a = face[i], b = face[(i + 1) % 3];
      if (++directed[{a, b}] > 1) validation_failure("MESH_NOT_ORIENTED_MANIFOLD", "A directed edge is used twice");
      edges[{std::min(a, b), std::max(a, b)}].faces.push_back(f);
    }
  }
  for (const auto& [key, info] : edges) {
    if (info.faces.size() > 2) validation_failure("MESH_NOT_ORIENTED_MANIFOLD", "An edge has more than two faces");
  }
  checks["mesh_is_oriented_edge_manifold"] = true;

  // Exact sharp-edge decision; the cosine of the bound is the only irrational quantity.
  const double cos_angle = std::cos(angle * kPi / 180.0);
  const long double sq_cos = static_cast<long double>(cos_angle) * static_cast<long double>(cos_angle);
  std::set<std::pair<std::size_t, std::size_t>> sharp;
  for (const auto& [key, info] : edges) {
    bool is_sharp = false;
    if (info.faces.size() == 1 || angle == 0.0) {
      is_sharp = true;
    } else if (angle != 180.0) {
      const Vec n1 = tri_normal(mesh.tris[info.faces[0]]);
      const Vec n2 = tri_normal(mesh.tris[info.faces[1]]);
      const Q sp = dot(n1, n2);
      const Q norms = dot(n1, n1) * dot(n2, n2);
      const long double lhs = static_cast<long double>(sp.get_d()) * static_cast<long double>(sp.get_d());
      const long double rhs = sq_cos * static_cast<long double>(norms.get_d());
      const long double scale = std::max(lhs, rhs);
      if (scale > 0 && std::fabs(static_cast<double>(lhs - rhs)) <= 1e-9 * static_cast<double>(scale)) {
        validation_failure("AMBIGUOUS_ANGLE_MARGIN",
                           "An edge dihedral lies within 1e-9 relative of the bound; the decision is not certified");
      }
      if (cos_angle < 0) is_sharp = sp < 0 && lhs >= rhs;
      else is_sharp = sp < 0 || lhs <= rhs;
    }
    if (is_sharp) sharp.insert(key);
  }

  auto read_edge_list = [&](const Json& value, const std::string& context) {
    if (!value.is_array()) validation_failure("REPORT_VALUE_INVALID", context + " must be an array");
    std::set<std::pair<std::size_t, std::size_t>> result;
    for (const auto& item : value) {
      if (!item.is_array() || item.size() != 2) validation_failure("REPORT_VALUE_INVALID", context + " item is not a pair");
      const auto a = index_of(item[0], vertex_count, context), b = index_of(item[1], vertex_count, context);
      if (a >= b) validation_failure("REPORT_VALUE_INVALID", context + " pairs must be ordered a<b");
      if (!result.insert({a, b}).second) validation_failure("REPORT_VALUE_INVALID", context + " repeats an edge");
    }
    return result;
  };
  const auto reported_sharp = read_edge_list(require_member(results, "sharp_edges", "results"), "sharp_edges");
  if (reported_sharp != sharp) {
    validation_failure("SHARP_EDGES_MISMATCH", "Reported sharp edges differ from the exact dihedral decision");
  }
  checks["sharp_edges_exact"] = true;

  std::vector<int> degree(vertex_count, 0);
  for (const auto& [a, b] : sharp) {
    ++degree[a];
    ++degree[b];
  }
  const auto reported_degree = require_member(results, "vertex_feature_degree", "results");
  if (!reported_degree.is_array() || reported_degree.size() != vertex_count) {
    validation_failure("REPORT_VALUE_INVALID", "vertex_feature_degree must list every vertex");
  }
  for (std::size_t v = 0; v < vertex_count; ++v) {
    if (!reported_degree[v].is_number_integer() || reported_degree[v].get<long long>() != degree[v]) {
      validation_failure("VERTEX_DEGREE_MISMATCH", "A vertex feature degree differs from the incident sharp edge count");
    }
  }
  checks["vertex_feature_degree_exact"] = true;

  // Patches: connected components of faces across interior non-sharp edges.
  std::vector<std::size_t> parent(face_count);
  std::iota(parent.begin(), parent.end(), 0);
  std::function<std::size_t(std::size_t)> find = [&](std::size_t x) {
    while (parent[x] != x) x = parent[x] = parent[parent[x]];
    return x;
  };
  for (const auto& [key, info] : edges) {
    if (info.faces.size() == 2 && !sharp.count(key)) {
      parent[find(info.faces[0])] = find(info.faces[1]);
    }
  }
  std::set<std::size_t> roots;
  for (std::size_t f = 0; f < face_count; ++f) roots.insert(find(f));

  const auto segmentation = require_member(results, "segmentation", "results");
  const auto seg_sharp = read_edge_list(require_member(segmentation, "sharp_edges", "segmentation"),
                                        "segmentation.sharp_edges");
  if (seg_sharp != sharp) {
    validation_failure("SHARP_EDGES_MISMATCH", "The segmentation used a different sharp edge set");
  }
  const auto patch_count = require_member(segmentation, "patch_count", "segmentation");
  if (!patch_count.is_number_integer() || patch_count.get<long long>() != static_cast<long long>(roots.size())) {
    validation_failure("PATCH_COUNT_MISMATCH", "Reported patch count differs from the exact face components");
  }
  const auto patch_ids = require_member(segmentation, "patch_ids", "segmentation");
  if (!patch_ids.is_array() || patch_ids.size() != face_count) {
    validation_failure("REPORT_VALUE_INVALID", "patch_ids must list every face");
  }
  std::map<long long, std::size_t> id_to_root;
  std::map<std::size_t, long long> root_to_id;
  for (std::size_t f = 0; f < face_count; ++f) {
    if (!patch_ids[f].is_number_integer()) validation_failure("REPORT_VALUE_INVALID", "patch id is not an integer");
    const long long id = patch_ids[f].get<long long>();
    const std::size_t root = find(f);
    const auto a = id_to_root.emplace(id, root);
    const auto b = root_to_id.emplace(root, id);
    if (a.first->second != root || b.first->second != id) {
      validation_failure("PATCH_PARTITION_MISMATCH", "Reported patch ids do not match the exact face components");
    }
  }
  checks["patch_partition_exact"] = true;

  const auto incident = require_member(segmentation, "vertex_incident_patches", "segmentation");
  if (!incident.is_array() || incident.size() != vertex_count) {
    validation_failure("REPORT_VALUE_INVALID", "vertex_incident_patches must list every vertex");
  }
  std::vector<std::set<long long>> expected(vertex_count);
  // Only feature vertices (at least one incident sharp edge) carry a patch set; a vertex inside a
  // smooth patch has an empty set (documented behaviour of detect_vertex_incident_patches).
  for (std::size_t f = 0; f < face_count; ++f) {
    for (const auto v : mesh.raw.faces[f]) {
      if (degree[v] > 0) expected[v].insert(patch_ids[f].get<long long>());
    }
  }
  for (std::size_t v = 0; v < vertex_count; ++v) {
    std::set<long long> got;
    if (!incident[v].is_array()) validation_failure("REPORT_VALUE_INVALID", "incident patches must be arrays");
    for (const auto& id : incident[v]) {
      if (!id.is_number_integer()) validation_failure("REPORT_VALUE_INVALID", "patch id is not an integer");
      got.insert(id.get<long long>());
    }
    if (got != expected[v]) validation_failure("INCIDENT_PATCHES_MISMATCH", "A vertex incident patch set is wrong");
  }
  checks["vertex_incident_patches_exact"] = true;
  return concluded(request, validator, checks,
                   {{"angle_degrees", angle}, {"cosine_of_bound", cos_angle},
                    {"face_count", face_count}, {"sharp_edge_count", sharp.size()},
                    {"patch_count", roots.size()}, {"relative_margin", 1e-9},
                    {"independence", "exact rational face normals; only the irrational cosine of the bound is floating point and ambiguous edges are rejected"}});
}

// ---- 7.5.03 / 7.5.04 shared tiling of a source surface -----------------------------------

Vec plane_normal_parameter(const Request& request, V3& raw) {
  raw = vector_parameter(request, "normal");
  if (raw[0] == 0 && raw[1] == 0 && raw[2] == 0) {
    validation_failure("ZERO_NORMAL", "The plane normal must be nonzero");
  }
  return vec(raw);
}

void reject_coplanar_faces(const Mesh& source, const Vec& n, const Q& d) {
  for (const auto& t : source.tris) {
    if (dot(n, t.v[0]) - d == 0 && dot(n, t.v[1]) - d == 0 && dot(n, t.v[2]) - d == 0) {
      validation_failure("COPLANAR_FACE", "The plane contains a source face");
    }
  }
}

// Assigns every candidate triangle to a source face containing it and checks, per source face,
// orientation, disjointness and that the exact weighted area equals the reference region.
// reference(p) is the weighted area (along the source normal) that the candidate must cover.
void check_tiling(const Mesh& source, const Mesh& candidate, const std::vector<std::size_t>& subset,
                  const std::function<Q(std::size_t)>& reference) {
  std::vector<std::vector<std::size_t>> by_parent(source.tris.size());
  for (const auto c : subset) {
    const Tri& sub = candidate.tris[c];
    bool placed = false;
    for (std::size_t p = 0; p < source.tris.size() && !placed; ++p) {
      const Tri& parent = source.tris[p];
      bool inside = true;
      for (int i = 0; i < 3 && inside; ++i) {
        for (int axis = 0; axis < 3 && inside; ++axis) {
          double lo = parent.raw[0][axis], hi = lo;
          for (int j = 1; j < 3; ++j) {
            lo = std::min(lo, parent.raw[j][axis]);
            hi = std::max(hi, parent.raw[j][axis]);
          }
          inside = sub.raw[i][axis] >= lo && sub.raw[i][axis] <= hi;
        }
      }
      for (int i = 0; i < 3 && inside; ++i) inside = point_in_triangle(parent, sub.v[i]);
      if (!inside) continue;
      if (tri_weight(sub, tri_normal(parent)) <= 0) {
        validation_failure("ORIENTATION_REVERSED", "A candidate triangle is oriented against its source face");
      }
      by_parent[p].push_back(c);
      placed = true;
    }
    if (!placed) {
      validation_failure("TRIANGLE_NOT_IN_SOURCE_FACE", "A candidate triangle does not lie inside any source face");
    }
  }
  for (std::size_t p = 0; p < by_parent.size(); ++p) {
    const Vec n = tri_normal(source.tris[p]);
    Q total = 0;
    for (const auto c : by_parent[p]) total += tri_weight(candidate.tris[c], n);
    if (total != reference(p)) {
      validation_failure("REGION_NOT_COVERED_EXACTLY",
                         "The candidate triangles of a source face do not cover its reference region exactly");
    }
    for (std::size_t i = 0; i < by_parent[p].size(); ++i) {
      for (std::size_t j = i + 1; j < by_parent[p].size(); ++j) {
        if (!interiors_disjoint(candidate.tris[by_parent[p][i]], candidate.tris[by_parent[p][j]], n)) {
          validation_failure("SUB_TRIANGLES_OVERLAP", "Two candidate triangles of a source face overlap");
        }
      }
    }
  }
}

bool boolean_parameter_of(const Request& request, const char* name) {
  const auto& value = request.parameters.at(name);
  if (!value.is_boolean()) throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be boolean");
  return value.get<bool>();
}

// ---- 7.5.03 clip ---------------------------------------------------------------------------

Json run_clip_validator(const Request& request) {
  const std::string validator = "mesh.validate.clip";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"normal", "offset", "clip_volume"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  V3 raw_normal{};
  const Vec n = plane_normal_parameter(request, raw_normal);
  const Q d = exact_of(signed_length_parameter(request, "offset", request.inputs[1].unit));
  const bool clip_volume = boolean_parameter_of(request, "clip_volume");
  const auto source = load_mesh(request.inputs[1], {"TriangleSurfaceMesh"}, "source", kMaximumFaces);
  const auto candidate = load_mesh(request.inputs[0], {"TriangleSurfaceMesh"}, "candidate", kMaximumOutputFaces);
  Json checks = json_checks({"source_triangles_nondegenerate"});
  reject_coplanar_faces(source, n, d);
  checks["plane_avoids_source_faces"] = true;
  for (const auto& t : candidate.tris) {
    for (int i = 0; i < 3; ++i) {
      if (dot(n, t.v[i]) - d > 0) validation_failure("VERTEX_ON_REMOVED_SIDE", "A candidate vertex is on the positive side of the plane");
    }
  }
  checks["candidate_on_negative_side"] = true;
  const bool source_closed = closed_oriented_manifold(source);
  const bool effective_volume = clip_volume && source_closed;
  std::vector<std::size_t> side, cap;
  for (std::size_t c = 0; c < candidate.tris.size(); ++c) {
    const auto& t = candidate.tris[c];
    const bool on_plane = dot(n, t.v[0]) - d == 0 && dot(n, t.v[1]) - d == 0 && dot(n, t.v[2]) - d == 0;
    (on_plane ? cap : side).push_back(c);
  }
  check_tiling(source, candidate, side, [&](std::size_t p) {
    const Tri& parent = source.tris[p];
    return polygon_weight(clip_halfspace({parent.v[0], parent.v[1], parent.v[2]}, n, d), tri_normal(parent));
  });
  checks["triangles_inside_source_faces"] = true;
  checks["orientation_preserved"] = true;
  checks["no_overlap_within_source_face"] = true;
  checks["clipped_region_covered_exactly"] = true;
  if (!effective_volume) {
    if (!cap.empty()) validation_failure("UNEXPECTED_CAP", "Surface clipping must not create triangles in the plane");
  } else {
    if (cap.empty()) validation_failure("CAP_MISSING", "Volume clipping of a closed mesh must close the cut with a cap");
    for (const auto c : cap) {
      if (dot(n, tri_normal(candidate.tris[c])) <= 0) {
        validation_failure("CAP_ORIENTATION", "A cap triangle is not oriented outward (along the plane normal)");
      }
    }
    for (std::size_t i = 0; i < cap.size(); ++i) {
      for (std::size_t j = i + 1; j < cap.size(); ++j) {
        if (!interiors_disjoint(candidate.tris[cap[i]], candidate.tris[cap[j]], n)) {
          validation_failure("CAP_OVERLAP", "Two cap triangles overlap");
        }
      }
    }
    if (!closed_oriented_manifold(candidate)) {
      validation_failure("CANDIDATE_NOT_CLOSED", "Volume clipping must give a closed, consistently oriented mesh");
    }
  }
  checks["cap_consistent"] = true;
  return concluded(request, validator, checks,
                   {{"clip_volume", clip_volume}, {"effective_clip_volume", effective_volume},
                    {"source_closed", source_closed}, {"source_face_count", source.tris.size()},
                    {"candidate_face_count", candidate.tris.size()}, {"cap_triangle_count", cap.size()},
                    {"independence", "Sutherland-Hodgman polygon clipping and exact weighted-area tiling per source face; no CGAL header"}});
}

// ---- 7.5.04 split by plane ------------------------------------------------------------------

Json run_split_validator(const Request& request) {
  const std::string validator = "mesh.validate.split";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"normal", "offset"});
  require_same_unit(request.inputs[0], request.inputs[1]);
  V3 raw_normal{};
  const Vec n = plane_normal_parameter(request, raw_normal);
  const Q d = exact_of(signed_length_parameter(request, "offset", request.inputs[1].unit));
  const auto source = load_mesh(request.inputs[1], {"TriangleSurfaceMesh"}, "source", kMaximumFaces);
  const auto candidate = load_mesh(request.inputs[0], {"PolygonSoup3"}, "candidate", kMaximumOutputFaces);
  Json checks = json_checks({"source_triangles_nondegenerate"});
  reject_coplanar_faces(source, n, d);
  checks["plane_avoids_source_faces"] = true;
  std::vector<std::size_t> all(candidate.tris.size());
  std::iota(all.begin(), all.end(), 0);
  check_tiling(source, candidate, all, [&](std::size_t p) { return tri_weight(source.tris[p], tri_normal(source.tris[p])); });
  checks["triangles_inside_source_faces"] = true;
  checks["orientation_preserved"] = true;
  checks["no_overlap_within_source_face"] = true;
  checks["surface_covered_exactly"] = true;

  // Side of every candidate triangle: -1 / +1, and none may straddle the plane.
  std::vector<int> side(candidate.tris.size(), 0);
  for (std::size_t c = 0; c < candidate.tris.size(); ++c) {
    bool positive = false, negative = false;
    for (int i = 0; i < 3; ++i) {
      const Q s = dot(n, candidate.tris[c].v[i]) - d;
      positive = positive || s > 0;
      negative = negative || s < 0;
    }
    if (positive && negative) validation_failure("TRIANGLE_STRADDLES_PLANE", "A candidate triangle crosses the plane");
    side[c] = positive ? 1 : (negative ? -1 : 0);
  }
  checks["no_triangle_crosses_plane"] = true;

  // Components in index space (faces joined through shared vertex-index edges) never mix sides.
  std::vector<std::size_t> parent(candidate.tris.size());
  std::iota(parent.begin(), parent.end(), 0);
  std::function<std::size_t(std::size_t)> find = [&](std::size_t x) {
    while (parent[x] != x) x = parent[x] = parent[parent[x]];
    return x;
  };
  std::map<std::pair<std::size_t, std::size_t>, std::vector<std::size_t>> edge_faces;
  for (std::size_t c = 0; c < candidate.raw.faces.size(); ++c) {
    const auto& face = candidate.raw.faces[c];
    for (int i = 0; i < 3; ++i) {
      const auto a = face[i], b = face[(i + 1) % 3];
      edge_faces[{std::min(a, b), std::max(a, b)}].push_back(c);
    }
  }
  for (const auto& [edge, faces] : edge_faces) {
    for (std::size_t k = 1; k < faces.size(); ++k) parent[find(faces[0])] = find(faces[k]);
  }
  std::map<std::size_t, std::set<int>> sides_of_component;
  for (std::size_t c = 0; c < candidate.tris.size(); ++c) {
    if (side[c] != 0) sides_of_component[find(c)].insert(side[c]);
  }
  bool negative_present = false, positive_present = false;
  for (const auto& [root, sides] : sides_of_component) {
    if (sides.size() > 1) {
      validation_failure("SIDES_NOT_SEPARATED", "A connected component of the split mesh contains both sides of the plane");
    }
    negative_present = negative_present || sides.count(-1) > 0;
    positive_present = positive_present || sides.count(1) > 0;
  }
  if (!negative_present || !positive_present) {
    validation_failure("PLANE_DOES_NOT_SPLIT", "The plane does not separate the source into two sides");
  }
  checks["sides_separated_into_components"] = true;
  return concluded(request, validator, checks,
                   {{"source_face_count", source.tris.size()}, {"candidate_face_count", candidate.tris.size()},
                    {"component_count", sides_of_component.size()},
                    {"independence", "exact weighted-area tiling of each source face, per-triangle plane side and index-space connected components; no CGAL header"}});
}

// ---- 7.5.04 corefine ---------------------------------------------------------------------------

Json run_corefine_validator(const Request& request) {
  const std::string validator = "mesh.validate.corefine";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto candidate = load_mesh(request.inputs[0], {"TriangleSurfaceMesh"}, "candidate", kMaximumOutputFaces);
  const auto source = load_mesh(request.inputs[1], {"TriangleSurfaceMesh"}, "source", kMaximumFaces);
  const auto other = load_mesh(request.inputs[2], {"TriangleSurfaceMesh"}, "other", kMaximumFaces);
  Json checks = json_checks({"source_triangles_nondegenerate"});
  std::vector<std::size_t> all(candidate.tris.size());
  std::iota(all.begin(), all.end(), 0);
  check_tiling(source, candidate, all, [&](std::size_t p) { return tri_weight(source.tris[p], tri_normal(source.tris[p])); });
  checks["triangles_inside_source_faces"] = true;
  checks["orientation_preserved"] = true;
  checks["no_overlap_within_source_face"] = true;
  checks["surface_covered_exactly"] = true;

  std::size_t touching_pairs = 0;
  for (const auto& t : candidate.tris) {
    for (const auto& u : other.tris) {
      if (!boxes_overlap(t, u)) continue;
      const auto points = intersection_points(t, u);
      if (points.empty()) continue;
      ++touching_pairs;
      bool on_one_edge = false;
      for (int e = 0; e < 3 && !on_one_edge; ++e) {
        bool all_on = true;
        for (const auto& p : points) all_on = all_on && point_on_segment(p, t.v[e], t.v[(e + 1) % 3]);
        on_one_edge = all_on;
      }
      if (!on_one_edge) {
        validation_failure("TRIANGLE_CROSSED_BY_OTHER_SURFACE",
                           "A candidate triangle meets the other surface in more than a single edge of its own boundary");
      }
    }
  }
  checks["intersection_is_in_candidate_edges"] = true;
  return concluded(request, validator, checks,
                   {{"source_face_count", source.tris.size()}, {"candidate_face_count", candidate.tris.size()},
                    {"other_face_count", other.tris.size()}, {"touching_pair_count", touching_pairs},
                    {"independence", "exact weighted-area tiling and exact triangle/triangle intersection polygon vertices; no CGAL header"}});
}

}  // namespace

std::vector<OperationDefinition> mesh_validator_operations() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  const char* gmp = "exact:GMP";
  result.push_back(query_definition(
      "mesh.validate.features", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      run_features_validator, {"Polygon_mesh_processing"}, "float:long_double",
      vinfo({"parameters_match", "source_matches", "mesh_is_oriented_edge_manifold", "sharp_edges_exact",
             "vertex_feature_degree_exact", "patch_partition_exact", "vertex_incident_patches_exact"},
            {"candidate", "mesh"},
            "exact rational face normals; the irrational cosine of the bound is long double and ambiguous edges are rejected; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.clip", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      run_clip_validator, {"PMP_Boolean_operations"}, gmp,
      vinfo({"source_triangles_nondegenerate", "plane_avoids_source_faces", "candidate_on_negative_side",
             "triangles_inside_source_faces", "orientation_preserved", "no_overlap_within_source_face",
             "clipped_region_covered_exactly", "cap_consistent"},
            {"candidate", "source"}, "Sutherland-Hodgman polygon clipping and exact weighted-area tiling per source face; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.split", {"PolygonSoup3", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      run_split_validator, {"PMP_Boolean_operations"}, gmp,
      vinfo({"source_triangles_nondegenerate", "plane_avoids_source_faces", "triangles_inside_source_faces",
             "orientation_preserved", "no_overlap_within_source_face", "surface_covered_exactly",
             "no_triangle_crosses_plane", "sides_separated_into_components"},
            {"candidate", "source"}, "exact weighted-area tiling of each source face, per-triangle plane side and index-space connected components; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.corefine", {"TriangleSurfaceMesh", "TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "ValidationReport",
      "validator", run_corefine_validator, {"PMP_Boolean_operations"}, gmp,
      vinfo({"source_triangles_nondegenerate", "triangles_inside_source_faces", "orientation_preserved",
             "no_overlap_within_source_face", "surface_covered_exactly", "intersection_is_in_candidate_edges"},
            {"candidate", "source", "other"}, "exact weighted-area tiling and exact triangle/triangle intersection polygon vertices; no CGAL header")));
  return result;
}

}  // namespace cgal_master::batch2
