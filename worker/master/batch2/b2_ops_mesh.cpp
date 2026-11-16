// Producers wrapping official CGAL 6.2.1 Polygon_mesh_processing APIs: detect_sharp_edges /
// sharp_edges_segmentation (7.3.05), self_intersections / does_self_intersect (7.3.07),
// clip (7.5.03), split and corefine (7.5.04). Every result is checked by an independent
// validator in b2_validators_mesh.cpp that includes no CGAL header. Output meshes are OFF
// files of binary64 coordinates, so a result is accepted only when every Epeck output
// coordinate is exactly representable as a double.

#include "b2_geometry.h"
#include "b2_registry.h"

#include "../rounded_proximity.h"

#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Polygon_mesh_processing/clip.h>
#include <CGAL/Polygon_mesh_processing/autorefinement.h>
#include <CGAL/Polygon_mesh_processing/corefinement.h>
#include <CGAL/Polygon_mesh_processing/detect_features.h>
#include <CGAL/Polygon_mesh_processing/intersection.h>
#include <CGAL/Polygon_mesh_processing/measure.h>
#include <CGAL/Polygon_mesh_processing/shape_predicates.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Surface_mesh.h>

#include <boost/container/flat_set.hpp>

#include <algorithm>
#include <cmath>
#include <iterator>
#include <map>
#include <set>

namespace cgal_master::batch2 {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;
using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using Epeck = CGAL::Exact_predicates_exact_constructions_kernel;
using EpickMesh = CGAL::Surface_mesh<Epick::Point_3>;
using EpeckMesh = CGAL::Surface_mesh<Epeck::Point_3>;
constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";
constexpr const char* kEpeckName = "CGAL::Exact_predicates_exact_constructions_kernel";

using query_ops::precondition;
using query_ops::read_raw_mesh;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::require_same_unit;
using query_ops::signed_length_parameter;
using query_ops::vector_parameter;
using query_ops::write_off_output;
using query_ops::write_report;

RawMesh load_input(const ArtifactInput& input) {
  auto raw = read_raw_mesh(input, {"TriangleSurfaceMesh"}, kMaximumFaces);
  if (raw.faces.size() > kMaximumFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "Input mesh exceeds the face limit");
  }
  for (const auto& face : raw.faces) {
    if (face.size() != 3) {
      throw WorkerError("PRECONDITION_FAILED", "MESH_NOT_TRIANGULATED", "Input mesh must be triangulated");
    }
  }
  return raw;
}

template <typename Mesh, typename Point>
Mesh build_mesh(const RawMesh& raw) {
  Mesh mesh;
  std::vector<typename Mesh::Vertex_index> handles;
  for (const auto& v : raw.vertices) handles.push_back(mesh.add_vertex(Point(v[0], v[1], v[2])));
  std::size_t expected = 0;
  for (const auto& face : raw.faces) {
    std::set<std::size_t> distinct(face.begin(), face.end());
    if (distinct.size() != face.size()) {
      throw WorkerError("PRECONDITION_FAILED", "DEGENERATE_FACE", "Input face repeats a vertex");
    }
    std::vector<typename Mesh::Vertex_index> cycle;
    for (const auto index : face) cycle.push_back(handles[index]);
    const auto added = mesh.add_face(cycle);
    if (added == Mesh::null_face() || static_cast<std::size_t>(added.idx()) != expected) {
      throw WorkerError("PRECONDITION_FAILED", "INVALID_POLYGON_MESH",
                        "Faces are not a manifold, consistently oriented mesh indexable in file order");
    }
    ++expected;
  }
  return mesh;
}

double exact_double(const Epeck::FT& value) {
  const double d = CGAL::to_double(value);
  if (!std::isfinite(d) || Epeck::FT(d) != value) {
    precondition("OUTPUT_NOT_REPRESENTABLE",
                 "An exact output coordinate is not representable as a binary64 value");
  }
  return d;
}

Json write_epeck_mesh(const Request& request, const EpeckMesh& mesh, const std::string& type, const std::string& unit) {
  if (mesh.number_of_faces() == 0) precondition("EMPTY_RESULT", "The operation produced no faces");
  if (mesh.number_of_faces() > kMaximumOutputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "Output mesh exceeds the face limit");
  }
  std::vector<V3> vertices;
  std::map<EpeckMesh::Vertex_index, std::size_t> ids;
  std::vector<std::vector<std::size_t>> faces;
  for (const auto face : mesh.faces()) {
    std::vector<std::size_t> cycle;
    for (const auto v : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      auto it = ids.find(v);
      if (it == ids.end()) {
        const auto& p = mesh.point(v);
        try {
          vertices.push_back({exact_double(p.x()), exact_double(p.y()), exact_double(p.z())});
        } catch (const WorkerError& error) {
          // The rounded variant of the same operation publishes this result within a stated tolerance.
          throw WorkerError(error.error_class, error.code,
                            std::string(error.what()) + "; " + request.operation +
                                "_rounded rounds the exact result and validates it within a stated tolerance",
                            error.recoverable, {request.operation + "_rounded"});
        }
        it = ids.emplace(v, vertices.size() - 1).first;
      }
      cycle.push_back(it->second);
    }
    faces.push_back(std::move(cycle));
  }
  return write_off_output(request, vertices, faces, type, unit);
}

Epeck::Plane_3 plane_parameters(const Request& request, V3& normal, double& offset) {
  normal = vector_parameter(request, "normal");
  offset = signed_length_parameter(request, "offset", request.inputs[0].unit);
  if (normal[0] == 0 && normal[1] == 0 && normal[2] == 0) {
    precondition("ZERO_NORMAL", "The plane normal must be nonzero");
  }
  return Epeck::Plane_3(normal[0], normal[1], normal[2], -offset);
}

void reject_coplanar_faces(const EpeckMesh& mesh, const Epeck::Plane_3& plane) {
  for (const auto face : mesh.faces()) {
    bool coplanar = true;
    for (const auto v : CGAL::vertices_around_face(mesh.halfedge(face), mesh)) {
      coplanar = coplanar && plane.oriented_side(mesh.point(v)) == CGAL::ON_ORIENTED_BOUNDARY;
    }
    if (coplanar) precondition("COPLANAR_FACE", "The plane contains a mesh face");
  }
}

Json plane_parameter_json(const V3& normal, double offset, const std::string& unit) {
  return {{"normal", Json::array({normal[0], normal[1], normal[2]})}, {"offset", {{"value", offset}, {"unit", unit}}}};
}

// ---- 7.3.05 -----------------------------------------------------------------------------

Json edge_list_json(const std::set<std::pair<std::size_t, std::size_t>>& edges) {
  Json result = Json::array();
  for (const auto& [a, b] : edges) result.push_back(Json::array({a, b}));
  return result;
}

Json detect_features(const Request& request) {
  require_inputs(request, 1, "mesh.features.detect");
  require_parameter_names(request, {"angle_degrees"});
  const auto raw = load_input(request.inputs[0]);
  const auto& angle_value = request.parameters.at("angle_degrees");
  if (!angle_value.is_number() || angle_value.is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "angle_degrees must be a number");
  }
  const double angle = angle_value.get<double>();
  if (!std::isfinite(angle) || angle < 0 || angle > 180) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "angle_degrees must be in [0,180]");
  }
  auto mesh = build_mesh<EpickMesh, Epick::Point_3>(raw);
  auto edge_feature = mesh.add_property_map<EpickMesh::Edge_index, bool>("e:feature", false).first;
  auto patch_id = mesh.add_property_map<EpickMesh::Face_index, std::size_t>("f:patch", 0).first;
  auto feature_degree = mesh.add_property_map<EpickMesh::Vertex_index, std::size_t>("v:degree", 0).first;
  auto incident_patches =
      mesh.add_property_map<EpickMesh::Vertex_index, boost::container::flat_set<std::size_t>>("v:patches").first;

  auto collect = [&]() {
    std::set<std::pair<std::size_t, std::size_t>> edges;
    for (const auto e : mesh.edges()) {
      if (!get(edge_feature, e)) continue;
      const std::size_t a = mesh.source(mesh.halfedge(e)).idx(), b = mesh.target(mesh.halfedge(e)).idx();
      edges.insert({std::min(a, b), std::max(a, b)});
    }
    return edges;
  };
  PMP::detect_sharp_edges(mesh, angle, edge_feature);
  const auto sharp = collect();
  for (const auto e : mesh.edges()) put(edge_feature, e, false);
  const std::size_t patch_count = PMP::sharp_edges_segmentation(
      mesh, angle, edge_feature, patch_id,
      CGAL::parameters::vertex_incident_patches_map(incident_patches).vertex_feature_degree_map(feature_degree));
  const auto segmentation_sharp = collect();
  if (sharp != segmentation_sharp) {
    throw WorkerError("INTERNAL_ERROR", "FEATURE_SETS_DIFFER", "detect_sharp_edges and sharp_edges_segmentation disagree");
  }
  Json degrees = Json::array(), ids = Json::array(), patches = Json::array();
  for (const auto v : mesh.vertices()) {
    degrees.push_back(get(feature_degree, v));
    Json list = Json::array();
    for (const auto id : get(incident_patches, v)) list.push_back(id);
    patches.push_back(std::move(list));
  }
  for (const auto f : mesh.faces()) ids.push_back(get(patch_id, f));
  Json report = geometry_frame(
      request, "mesh_features", {{"angle_degrees", angle}}, {{"mesh_sha256", request.inputs[0].sha256}},
      {{"face_count", raw.faces.size()}, {"sharp_edge_count", sharp.size()}, {"patch_count", patch_count}},
      {{"sharp_edges", edge_list_json(sharp)},
       {"vertex_feature_degree", degrees},
       {"segmentation", {{"sharp_edges", edge_list_json(segmentation_sharp)},
                         {"patch_count", patch_count},
                         {"patch_ids", ids},
                         {"vertex_incident_patches", patches}}}});
  auto output = write_report(request, "GeometryQueryReport", report);
  Json metrics{{"face_count", raw.faces.size()}, {"sharp_edge_count", sharp.size()}, {"patch_count", patch_count},
               {"algorithm", "CGAL::Polygon_mesh_processing::sharp_edges_segmentation"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- 7.5.03 / 7.5.04 --------------------------------------------------------------------

Json clip_plane(const Request& request) {
  require_inputs(request, 1, "mesh.clip.plane");
  require_parameter_names(request, {"normal", "offset", "clip_volume"});
  const auto raw = load_input(request.inputs[0]);
  V3 normal{};
  double offset = 0;
  const auto plane = plane_parameters(request, normal, offset);
  const auto& flag = request.parameters.at("clip_volume");
  if (!flag.is_boolean()) throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "clip_volume must be boolean");
  const bool clip_volume = flag.get<bool>();
  auto mesh = build_mesh<EpeckMesh, Epeck::Point_3>(raw);
  reject_coplanar_faces(mesh, plane);
  PMP::clip(mesh, plane, CGAL::parameters::clip_volume(clip_volume));
  mesh.collect_garbage();
  auto output = write_epeck_mesh(request, mesh, "TriangleSurfaceMesh", request.inputs[0].unit);
  Json metrics{{"input_face_count", raw.faces.size()}, {"output_face_count", mesh.number_of_faces()},
               {"clip_volume", clip_volume}, {"algorithm", "CGAL::Polygon_mesh_processing::clip"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json split_plane(const Request& request) {
  require_inputs(request, 1, "mesh.split.plane");
  require_parameter_names(request, {"normal", "offset"});
  const auto raw = load_input(request.inputs[0]);
  V3 normal{};
  double offset = 0;
  const auto plane = plane_parameters(request, normal, offset);
  auto mesh = build_mesh<EpeckMesh, Epeck::Point_3>(raw);
  reject_coplanar_faces(mesh, plane);
  PMP::split(mesh, plane);
  mesh.collect_garbage();
  auto output = write_epeck_mesh(request, mesh, "TriangleSurfaceMesh", request.inputs[0].unit);
  Json metrics{{"input_face_count", raw.faces.size()}, {"output_face_count", mesh.number_of_faces()},
               {"algorithm", "CGAL::Polygon_mesh_processing::split"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json corefine_meshes(const Request& request) {
  require_inputs(request, 2, "mesh.corefine");
  require_parameter_names(request, {});
  require_same_unit(request.inputs[0], request.inputs[1]);
  const auto first = load_input(request.inputs[0]);
  const auto second = load_input(request.inputs[1]);
  auto mesh = build_mesh<EpeckMesh, Epeck::Point_3>(first);
  auto other = build_mesh<EpeckMesh, Epeck::Point_3>(second);
  PMP::corefine(mesh, other, CGAL::parameters::default_values(), CGAL::parameters::do_not_modify(true));
  mesh.collect_garbage();
  auto output = write_epeck_mesh(request, mesh, "TriangleSurfaceMesh", request.inputs[0].unit);
  Json metrics{{"input_face_count", first.faces.size()}, {"other_face_count", second.faces.size()},
               {"output_face_count", mesh.number_of_faces()},
               {"algorithm", "CGAL::Polygon_mesh_processing::corefine"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json autorefine_mesh(const Request& request) {
  require_inputs(request, 1, "mesh.autorefine");
  require_parameter_names(request, {});
  const auto raw = load_input(request.inputs[0]);
  auto mesh = build_mesh<EpeckMesh, Epeck::Point_3>(raw);
  PMP::autorefine(mesh);
  mesh.collect_garbage();
  auto output = write_epeck_mesh(request, mesh, "TriangleSurfaceMesh", request.inputs[0].unit);
  Json metrics{{"input_face_count", raw.faces.size()}, {"output_face_count", mesh.number_of_faces()},
               {"algorithm", "CGAL::Polygon_mesh_processing::autorefine"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

// ---- rounded variants (general-position input) --------------------------------------------
//
// clip, split, corefine and autorefine above publish a result only when every exact coordinate
// is a binary64 value. That holds for dyadic axis-aligned input and almost never for a general
// mesh (a plane through a sphere already fails). The *_rounded operations run the same exact
// EPECK algorithm, replace each coordinate by a neighbouring binary64 value and refuse the result
// if rounding broke the mesh. Their validators replay the exact operation and accept the candidate
// only within a stated absolute tolerance (rounded_proximity.h). They certify closeness to the
// exact result, not the exact tiling that the non-rounded validators prove, and they are replay
// checks, not CGAL-free oracles.

enum class RoundedKind { kClip, kSplit, kCorefine, kAutorefine };

struct RoundedSpec {
  RoundedKind kind;
  const char* operation;
  const char* validator;
  const char* exact_operation;
  const char* algorithm;
  const char* header;
  std::size_t source_count;
};

const RoundedSpec kRoundedSpecs[] = {
    {RoundedKind::kClip, "mesh.clip.plane_rounded", "mesh.validate.clip_rounded", "mesh.clip.plane",
     "CGAL::Polygon_mesh_processing::clip", "CGAL/Polygon_mesh_processing/clip.h", 1},
    {RoundedKind::kSplit, "mesh.split.plane_rounded", "mesh.validate.split_rounded", "mesh.split.plane",
     "CGAL::Polygon_mesh_processing::split", "CGAL/Polygon_mesh_processing/clip.h", 1},
    {RoundedKind::kCorefine, "mesh.corefine_rounded", "mesh.validate.corefine_rounded", "mesh.corefine",
     "CGAL::Polygon_mesh_processing::corefine", "CGAL/Polygon_mesh_processing/corefinement.h", 2},
    {RoundedKind::kAutorefine, "mesh.autorefine_rounded", "mesh.validate.autorefine_rounded", "mesh.autorefine",
     "CGAL::Polygon_mesh_processing::autorefine", "CGAL/Polygon_mesh_processing/autorefinement.h", 1},
};

std::vector<std::string> rounded_parameters(RoundedKind kind) {
  if (kind == RoundedKind::kClip) return {"normal", "offset", "clip_volume"};
  if (kind == RoundedKind::kSplit) return {"normal", "offset"};
  return {};
}

void require_rounded_parameters(const Request& request, RoundedKind kind) {
  if (kind == RoundedKind::kClip) require_parameter_names(request, {"normal", "offset", "clip_volume"});
  else if (kind == RoundedKind::kSplit) require_parameter_names(request, {"normal", "offset"});
  else require_parameter_names(request, {});
}

double largest_raw_coordinate(const RawMesh& raw, double largest) {
  for (const auto& v : raw.vertices) {
    largest = std::max({largest, std::fabs(v[0]), std::fabs(v[1]), std::fabs(v[2])});
  }
  return largest;
}

// The exact EPECK result of the operation on the sources that start at request.inputs[first].
EpeckMesh exact_rounded_source(const Request& request, RoundedKind kind, std::size_t first, double& largest) {
  const auto raw = load_input(request.inputs[first]);
  largest = largest_raw_coordinate(raw, largest);
  auto mesh = build_mesh<EpeckMesh, Epeck::Point_3>(raw);
  if (kind == RoundedKind::kClip || kind == RoundedKind::kSplit) {
    V3 normal{};
    double offset = 0;
    const auto plane = plane_parameters(request, normal, offset);
    if (kind == RoundedKind::kClip) {
      const auto& flag = request.parameters.at("clip_volume");
      if (!flag.is_boolean()) throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", "clip_volume must be boolean");
      PMP::clip(mesh, plane, CGAL::parameters::clip_volume(flag.get<bool>()));
    } else {
      PMP::split(mesh, plane);
    }
  } else if (kind == RoundedKind::kCorefine) {
    const auto second = load_input(request.inputs[first + 1]);
    largest = largest_raw_coordinate(second, largest);
    auto other = build_mesh<EpeckMesh, Epeck::Point_3>(second);
    PMP::corefine(mesh, other, CGAL::parameters::default_values(), CGAL::parameters::do_not_modify(true));
  } else {
    PMP::autorefine(mesh);
  }
  mesh.collect_garbage();
  if (mesh.number_of_faces() == 0) precondition("EMPTY_RESULT", "The operation produced no faces");
  if (mesh.number_of_faces() > kMaximumOutputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "Output mesh exceeds the face limit");
  }
  return mesh;
}

std::size_t border_halfedge_count(const EpeckMesh& mesh) {
  std::size_t count = 0;
  for (const auto h : mesh.halfedges()) count += mesh.is_border(h) ? 1 : 0;
  return count;
}

bool has_degenerate_face(const EpeckMesh& mesh) {
  for (const auto face : mesh.faces()) {
    if (PMP::is_degenerate_triangle_face(face, mesh)) return true;
  }
  return false;
}

struct RoundedMesh {
  std::vector<V3> vertices;
  std::vector<std::vector<std::size_t>> faces;
};

// Binary64 copy of an exact mesh with the same combinatorics; `mesh` receives the same geometry
// as an EPECK mesh so that exact predicates can inspect what was actually written.
RoundedMesh round_exact_mesh(const EpeckMesh& exact, EpeckMesh& mesh) {
  RoundedMesh rounded;
  std::vector<std::size_t> index(exact.number_of_vertices() + exact.number_of_removed_vertices());
  std::vector<EpeckMesh::Vertex_index> handles;
  for (const auto v : exact.vertices()) {
    const auto& p = exact.point(v);
    const V3 value{CGAL::to_double(CGAL::exact(p.x())), CGAL::to_double(CGAL::exact(p.y())),
                   CGAL::to_double(CGAL::exact(p.z()))};
    if (!std::isfinite(value[0]) || !std::isfinite(value[1]) || !std::isfinite(value[2])) {
      throw WorkerError("NUMERIC_FAILURE", "ROUNDING_INVALIDATED_RESULT", "A coordinate has no finite binary64 value");
    }
    index[v.idx()] = rounded.vertices.size();
    rounded.vertices.push_back(value);
    handles.push_back(mesh.add_vertex(Epeck::Point_3(value[0], value[1], value[2])));
  }
  for (const auto face : exact.faces()) {
    std::vector<std::size_t> cycle;
    std::vector<EpeckMesh::Vertex_index> corners;
    for (const auto v : CGAL::vertices_around_face(exact.halfedge(face), exact)) {
      cycle.push_back(index[v.idx()]);
      corners.push_back(handles[index[v.idx()]]);
    }
    if (mesh.add_face(corners) == EpeckMesh::null_face()) {
      throw WorkerError("NUMERIC_FAILURE", "ROUNDING_INVALIDATED_RESULT", "The rounded result is not a manifold mesh");
    }
    rounded.faces.push_back(std::move(cycle));
  }
  return rounded;
}

Json run_rounded(const Request& request, const RoundedSpec& spec) {
  require_inputs(request, spec.source_count, spec.operation);
  require_rounded_parameters(request, spec.kind);
  if (spec.source_count == 2) require_same_unit(request.inputs[0], request.inputs[1]);
  double largest = 0;
  const auto exact = exact_rounded_source(request, spec.kind, 0, largest);
  EpeckMesh mesh;
  const auto rounded = round_exact_mesh(exact, mesh);
  if (has_degenerate_face(mesh)) {
    throw WorkerError("NUMERIC_FAILURE", "ROUNDING_INVALIDATED_RESULT",
                      "Rounding to binary64 produced a degenerate triangle; nothing is published");
  }
  const bool exact_self_intersects = PMP::does_self_intersect(exact);
  if (!exact_self_intersects && PMP::does_self_intersect(mesh)) {
    throw WorkerError("NUMERIC_FAILURE", "ROUNDING_INVALIDATED_RESULT",
                      "Rounding to binary64 produced a self-intersection; nothing is published");
  }
  auto output = write_off_output(request, rounded.vertices, rounded.faces, "TriangleSurfaceMesh", request.inputs[0].unit);
  Json metrics{{"output_face_count", rounded.faces.size()},
               {"output_vertex_count", rounded.vertices.size()},
               {"border_halfedge_count", border_halfedge_count(mesh)},
               {"exact_result_self_intersects", exact_self_intersects},
               {"tolerance", rounded::tolerance_for_scale(largest)},
               {"algorithm", spec.algorithm},
               {"output_coordinate_storage", "IEEE-754 binary64, rounded from exact coordinates"}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

Json run_rounded_validator(const Request& request, const RoundedSpec& spec) {
  require_inputs(request, spec.source_count + 1, spec.validator);
  require_rounded_parameters(request, spec.kind);
  for (std::size_t i = 1; i < request.inputs.size(); ++i) require_same_unit(request.inputs[0], request.inputs[i]);
  const auto candidate_raw = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"}, kMaximumOutputFaces);
  for (const auto& face : candidate_raw.faces) {
    if (face.size() != 3) query_ops::validation_failure("CANDIDATE_INVALID", "The candidate is not triangulated");
  }
  EpeckMesh candidate;
  try {
    candidate = build_mesh<EpeckMesh, Epeck::Point_3>(candidate_raw);
  } catch (const WorkerError& error) {
    query_ops::validation_failure("CANDIDATE_INVALID", std::string("The candidate is not a valid mesh: ") + error.what());
  }
  Json checks = json_checks({"candidate_is_valid_mesh"});
  double largest = 0;
  const auto reference = exact_rounded_source(request, spec.kind, 1, largest);
  const double tolerance = rounded::tolerance_for_scale(largest);
  if (candidate.number_of_vertices() != reference.number_of_vertices() ||
      candidate.number_of_faces() != reference.number_of_faces()) {
    query_ops::validation_failure("ROUNDED_COUNT_MISMATCH", "Candidate vertex or face count differs from the exact replay");
  }
  checks["element_counts_match_reference"] = true;
  if (border_halfedge_count(candidate) != border_halfedge_count(reference)) {
    query_ops::validation_failure("ROUNDED_BORDER_MISMATCH", "Candidate border differs from the exact replay");
  }
  checks["border_matches_reference"] = true;
  if (has_degenerate_face(candidate)) {
    query_ops::validation_failure("ROUNDED_DEGENERATE_FACE", "The candidate has a degenerate triangle");
  }
  checks["no_degenerate_face"] = true;
  const bool reference_self_intersects = PMP::does_self_intersect(reference);
  if (!reference_self_intersects && PMP::does_self_intersect(candidate)) {
    query_ops::validation_failure("ROUNDED_SELF_INTERSECTION", "The candidate self-intersects although the exact result does not");
  }
  checks["self_intersection_free_like_reference"] = true;
  const Epeck::FT epsilon(tolerance);
  const Epeck::FT epsilon_squared = epsilon * epsilon;
  const rounded::SurfaceProximity reference_surface(reference);
  const rounded::SurfaceProximity candidate_surface(candidate);
  const auto candidate_distance = rounded::max_vertex_squared_distance(candidate, reference_surface);
  if (candidate_distance > epsilon_squared) {
    query_ops::validation_failure("ROUNDED_CANDIDATE_OFF_REFERENCE",
                                  "A candidate vertex is farther than the tolerance from the exact result surface");
  }
  checks["candidate_vertices_within_tolerance_of_reference_surface"] = true;
  const auto reference_distance = rounded::max_vertex_squared_distance(reference, candidate_surface);
  if (reference_distance > epsilon_squared) {
    query_ops::validation_failure("ROUNDED_REFERENCE_OFF_CANDIDATE",
                                  "A vertex of the exact result is farther than the tolerance from the candidate surface");
  }
  checks["reference_vertices_within_tolerance_of_candidate_surface"] = true;
  const bool closed = border_halfedge_count(reference) == 0;
  double volume_bound = 0;
  if (closed) {
    // Moving every vertex by at most the tolerance changes the volume by at most tolerance * area
    // to first order; 1.01 covers the binary64 evaluation of the area.
    const Epeck::FT bound = epsilon * Epeck::FT(1.01 * rounded::approximate_area(reference));
    if (CGAL::abs(PMP::volume(candidate) - PMP::volume(reference)) > bound) {
      query_ops::validation_failure("ROUNDED_VOLUME_MISMATCH",
                                    "Candidate volume differs from the exact replay by more than tolerance * area");
    }
    volume_bound = CGAL::to_double(bound);
  }
  checks["volume_within_tolerance_when_closed"] = true;
  return concluded(request, spec.validator, checks,
                   {{"comparison", "tolerance"},
                    {"validates", spec.operation},
                    {"tolerance", tolerance},
                    {"tolerance_rule", "2^-40 times the power of two above the largest absolute source coordinate"},
                    {"reference_closed", closed},
                    {"volume_bound", volume_bound},
                    {"reference_self_intersects", reference_self_intersects},
                    {"max_candidate_vertex_distance", std::sqrt(CGAL::to_double(candidate_distance))},
                    {"max_reference_vertex_distance", std::sqrt(CGAL::to_double(reference_distance))},
                    {"candidate_face_count", candidate.number_of_faces()},
                    {"independence",
                     "exact EPECK replay of the same CGAL operation; the candidate is compared by element counts, border, exact predicates and exact vertex-to-witness-triangle distances against a stated tolerance. A replay check, not a CGAL-free oracle; it does not prove the exact tiling"}});
}

}  // namespace

std::vector<OperationDefinition> mesh_rounded_operations() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  for (const auto& spec : kRoundedSpecs) {
    std::vector<std::string> slots = spec.source_count == 2 ? std::vector<std::string>{"source", "other"}
                                                            : std::vector<std::string>{"source"};
    std::vector<std::string> source_types(spec.source_count, "TriangleSurfaceMesh");
    const RoundedSpec* captured = &spec;
    result.push_back(query_definition(
        spec.operation, source_types, "TriangleSurfaceMesh", "transform",
        [captured](const Request& request) { return run_rounded(request, *captured); },
        {"Polygon_mesh_processing", "Surface_mesh", "AABB_tree"}, kEpeckName,
        pinfo(spec.validator, rounded_parameters(spec.kind), slots,
              {{"source_header", spec.header},
               {"maximum_input_faces", kMaximumFaces},
               {"maximum_output_faces", kMaximumOutputFaces},
               {"rounds_exact_result_of", spec.exact_operation},
               {"tolerance_rule", "2^-40 times the power of two above the largest absolute source coordinate"}})));
    std::vector<std::string> validator_types(spec.source_count + 1, "TriangleSurfaceMesh");
    std::vector<std::string> validator_slots = {"candidate"};
    validator_slots.insert(validator_slots.end(), slots.begin(), slots.end());
    result.push_back(query_definition(
        spec.validator, validator_types, "ValidationReport", "validator",
        [captured](const Request& request) { return run_rounded_validator(request, *captured); },
        {"Polygon_mesh_processing", "Surface_mesh", "AABB_tree"}, kEpeckName,
        vinfo({"candidate_is_valid_mesh", "element_counts_match_reference", "border_matches_reference",
               "no_degenerate_face", "self_intersection_free_like_reference",
               "candidate_vertices_within_tolerance_of_reference_surface",
               "reference_vertices_within_tolerance_of_candidate_surface", "volume_within_tolerance_when_closed"},
              validator_slots,
              "exact EPECK replay of the same CGAL operation compared within a stated tolerance; not a CGAL-free oracle")));
  }
  return result;
}

std::vector<OperationDefinition> mesh_producer_operations() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.features.detect", {"TriangleSurfaceMesh"}, "GeometryQueryReport", "analysis", detect_features,
      {"Polygon_mesh_processing"}, kEpickName,
      pinfo("mesh.validate.features", {"angle_degrees"}, {"mesh"},
            {{"source_header", "CGAL/Polygon_mesh_processing/detect_features.h"}, {"maximum_input_faces", kMaximumFaces}})));
  result.push_back(query_definition(
      "mesh.clip.plane", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform", clip_plane,
      {"PMP_Boolean_operations"}, kEpeckName,
      pinfo("mesh.validate.clip", {"normal", "offset", "clip_volume"}, {"source"},
            {{"source_header", "CGAL/Polygon_mesh_processing/clip.h"}, {"maximum_input_faces", kMaximumFaces},
             {"maximum_output_faces", kMaximumOutputFaces}})));
  result.push_back(query_definition(
      "mesh.split.plane", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform", split_plane,
      {"PMP_Boolean_operations"}, kEpeckName,
      pinfo("mesh.validate.split", {"normal", "offset"}, {"source"},
            {{"source_header", "CGAL/Polygon_mesh_processing/clip.h"}, {"maximum_input_faces", kMaximumFaces},
             {"maximum_output_faces", kMaximumOutputFaces}})));
  result.push_back(query_definition(
      "mesh.corefine", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform",
      corefine_meshes, {"PMP_Boolean_operations"}, kEpeckName,
      pinfo("mesh.validate.corefine", {}, {"source", "other"},
            {{"source_header", "CGAL/Polygon_mesh_processing/corefinement.h"}, {"maximum_input_faces", kMaximumFaces},
             {"maximum_output_faces", kMaximumOutputFaces}})));
  result.push_back(query_definition(
      "mesh.autorefine", {"TriangleSurfaceMesh"}, "TriangleSurfaceMesh", "transform", autorefine_mesh,
      {"PMP_Boolean_operations"}, kEpeckName,
      pinfo("mesh.validate.autorefine", {}, {"source"},
            {{"source_header", "CGAL/Polygon_mesh_processing/autorefinement.h"}, {"maximum_input_faces", kMaximumFaces},
             {"maximum_output_faces", kMaximumOutputFaces}})));
  return result;
}

}  // namespace cgal_master::batch2
