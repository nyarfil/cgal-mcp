#include "mesh_io.h"
#include "wave_a_operations.h"

#include <CGAL/AABB_face_graph_triangle_primitive.h>
#include <CGAL/AABB_traits_3.h>
#include <CGAL/AABB_tree.h>
#include <CGAL/Cartesian_converter.h>
#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Polygon_mesh_processing/connected_components.h>
#include <CGAL/Polygon_mesh_processing/manifoldness.h>
#include <CGAL/Polygon_mesh_processing/orientation.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Polygon_mesh_processing/shape_predicates.h>
#include <CGAL/boost/graph/border.h>
#include <CGAL/boost/graph/copy_face_graph.h>
#include <CGAL/boost/graph/helpers.h>
#include <CGAL/number_utils.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <functional>
#include <iterator>
#include <set>
#include <string>
#include <tuple>
#include <utility>
#include <vector>

namespace cgal_master::wave_a {
namespace {

namespace PMP = CGAL::Polygon_mesh_processing;
using Segment = std::pair<Point, Point>;
using ExactKernel = CGAL::Exact_predicates_exact_constructions_kernel;

bool has_nonzero_exact_signed_volume(const Mesh& mesh) {
  CGAL::Cartesian_converter<Kernel, ExactKernel> to_exact;
  ExactKernel::FT signed_six_volume = 0;
  for (const auto face : mesh.faces()) {
    const auto first = mesh.halfedge(face);
    const auto second = mesh.next(first);
    const auto third = mesh.next(second);
    const auto a = to_exact(mesh.point(mesh.target(first)));
    const auto b = to_exact(mesh.point(mesh.target(second)));
    const auto c = to_exact(mesh.point(mesh.target(third)));
    const auto a_vector = a - CGAL::ORIGIN;
    const auto b_vector = b - CGAL::ORIGIN;
    const auto c_vector = c - CGAL::ORIGIN;
    signed_six_volume += a_vector * CGAL::cross_product(b_vector, c_vector);
  }
  return signed_six_volume != 0;
}

void require_allowed_parameters(const Json& parameters) {
  static const std::set<std::string> allowed = {"preserve_border",
                                                 "constrained_edges"};
  for (auto iterator = parameters.begin(); iterator != parameters.end();
       ++iterator) {
    if (allowed.find(iterator.key()) == allowed.end()) {
      throw WorkerError(
          "INVALID_REQUEST", "UNSUPPORTED_PARAMETER",
          "Unsupported simplification integrity parameter: " +
              iterator.key());
    }
  }
}

bool preserve_border_parameter(const Json& parameters) {
  if (!parameters.contains("preserve_border")) return true;
  if (!parameters.at("preserve_border").is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "preserve_border must be boolean");
  }
  return parameters.at("preserve_border").get<bool>();
}

Segment edge_segment(const Mesh& mesh, Mesh::Edge_index edge) {
  const auto halfedge = mesh.halfedge(edge);
  return {mesh.point(mesh.source(halfedge)),
          mesh.point(mesh.target(halfedge))};
}

bool contains_segment(const Mesh& mesh, const Segment& expected) {
  for (const auto edge : mesh.edges()) {
    const auto candidate = edge_segment(mesh, edge);
    if ((candidate.first == expected.first &&
         candidate.second == expected.second) ||
        (candidate.first == expected.second &&
         candidate.second == expected.first)) {
      return true;
    }
  }
  return false;
}

std::vector<Segment> protected_segments(const Mesh& source,
                                        const Json& parameters,
                                        bool preserve_border) {
  std::vector<Segment> segments;
  if (preserve_border) {
    for (const auto edge : source.edges()) {
      if (CGAL::is_border(edge, source)) {
        segments.push_back(edge_segment(source, edge));
      }
    }
  }
  if (!parameters.contains("constrained_edges")) return segments;
  const auto& constraints = parameters.at("constrained_edges");
  if (!constraints.is_array()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_CONSTRAINTS",
                      "constrained_edges must be an array of vertex pairs");
  }
  for (const auto& pair : constraints) {
    if (!pair.is_array() || pair.size() != 2 ||
        !pair[0].is_number_unsigned() || !pair[1].is_number_unsigned()) {
      throw WorkerError("INVALID_REQUEST", "INVALID_CONSTRAINTS",
                        "Each constrained edge must be [u, v]");
    }
    const auto source_index = pair[0].get<std::size_t>();
    const auto target_index = pair[1].get<std::size_t>();
    if (source_index >= source.number_of_vertices() ||
        target_index >= source.number_of_vertices() ||
        source_index == target_index) {
      throw WorkerError("INVALID_REQUEST", "INVALID_CONSTRAINT_EDGE",
                        "Constrained edge vertex index is invalid");
    }
    const auto halfedge = source.halfedge(Mesh::Vertex_index(source_index),
                                          Mesh::Vertex_index(target_index));
    if (halfedge == Mesh::null_halfedge()) {
      throw WorkerError("INVALID_REQUEST", "CONSTRAINT_EDGE_NOT_FOUND",
                        "Constrained vertex pair is not a source mesh edge");
    }
    segments.push_back(edge_segment(source, source.edge(halfedge)));
  }
  return segments;
}

void validate_mesh_health(const Mesh& mesh) {
  for (const auto face : mesh.faces()) {
    if (PMP::is_degenerate_triangle_face(face, mesh)) {
      throw WorkerError("VALIDATION_FAILED", "DEGENERATE_FACE",
                        "Simplified mesh contains a degenerate triangle");
    }
  }
  std::vector<Mesh::Halfedge_index> non_manifold;
  PMP::non_manifold_vertices(mesh, std::back_inserter(non_manifold));
  if (!non_manifold.empty()) {
    throw WorkerError("VALIDATION_FAILED", "NON_MANIFOLD_VERTEX",
                      "Simplified mesh contains a non-manifold vertex");
  }
  if (PMP::does_self_intersect(mesh)) {
    throw WorkerError("VALIDATION_FAILED", "SELF_INTERSECTION",
                      "Simplified mesh self-intersects");
  }
}

struct ComponentTopology {
  std::int64_t euler_characteristic;
  std::size_t border_count;
  bool closed;
  // 1 is outward, -1 inward, and 0 means orientation is not applicable to
  // an open component. Inward closed components are legal cavity shells.
  int orientation;
  // For an entirely closed mesh, zero identifies an outer shell and each
  // increment crosses another containing shell. Open or mixed meshes use -1.
  std::int64_t nesting_level;

  auto key() const {
    return std::tie(euler_characteristic, border_count, closed, orientation,
                    nesting_level);
  }
};

bool operator<(const ComponentTopology& first,
               const ComponentTopology& second) {
  return first.key() < second.key();
}

bool operator==(const ComponentTopology& first,
                const ComponentTopology& second) {
  return first.key() == second.key();
}

std::vector<ComponentTopology> component_topology(
    Mesh& mesh, bool source_precondition) {
  std::vector<Mesh> components;
  PMP::split_connected_components(mesh, components);

  Mesh closed_components;
  std::vector<std::size_t> closed_component_indices;
  for (std::size_t component_index = 0;
       component_index < components.size(); ++component_index) {
    if (CGAL::is_closed(components[component_index])) {
      closed_component_indices.push_back(component_index);
      CGAL::copy_face_graph(components[component_index], closed_components);
    }
  }

  std::vector<std::int64_t> nesting_by_component(components.size(), -1);
  std::vector<bool> outward_by_component(components.size(), false);
  if (!closed_component_indices.empty()) {
    std::vector<std::size_t> nesting_levels;
    std::vector<bool> component_outward_oriented;
    auto volume_id_map =
        closed_components.add_property_map<Mesh::Face_index, std::size_t>(
                "f:wave-a-volume-id", 0)
            .first;
    PMP::volume_connected_components(
        closed_components, volume_id_map,
        CGAL::parameters::nesting_levels(std::ref(nesting_levels))
            .is_cc_outward_oriented(
                std::ref(component_outward_oriented)));
    if (nesting_levels.size() != closed_component_indices.size() ||
        component_outward_oriented.size() !=
            closed_component_indices.size()) {
      throw WorkerError("INTERNAL_ERROR", "COMPONENT_ANALYSIS_FAILED",
                        "CGAL component containment analysis was incomplete");
    }
    for (std::size_t closed_index = 0;
         closed_index < closed_component_indices.size(); ++closed_index) {
      const auto component_index = closed_component_indices[closed_index];
      nesting_by_component[component_index] =
          static_cast<std::int64_t>(nesting_levels[closed_index]);
      outward_by_component[component_index] =
          component_outward_oriented[closed_index];
    }
  }
  std::vector<ComponentTopology> result;
  result.reserve(components.size());
  for (std::size_t component_index = 0;
       component_index < components.size(); ++component_index) {
    const auto& component = components[component_index];
    const auto vertices = static_cast<std::int64_t>(component.number_of_vertices());
    const auto edges = static_cast<std::int64_t>(component.number_of_edges());
    const auto faces = static_cast<std::int64_t>(component.number_of_faces());
    const bool closed = CGAL::is_closed(component);
    int orientation = 0;
    if (closed) {
      if (!has_nonzero_exact_signed_volume(component)) {
        throw WorkerError(
            source_precondition ? "PRECONDITION_FAILED" : "VALIDATION_FAILED",
            source_precondition ? "SOURCE_ZERO_VOLUME_COMPONENT"
                                : "CANDIDATE_ZERO_VOLUME_COMPONENT",
            source_precondition
                ? "Every closed source component must have nonzero exact signed volume"
                : "Every closed candidate component must have nonzero exact signed volume");
      }
      orientation = PMP::is_outward_oriented(component) ? 1 : -1;
    }
    const std::int64_t nesting_level =
        nesting_by_component[component_index];
    if (closed) {
      const bool expected_outward = (nesting_level % 2) == 0;
      const bool actual_outward = outward_by_component[component_index];
      if (actual_outward != expected_outward ||
          orientation != (actual_outward ? 1 : -1)) {
        throw WorkerError(
            source_precondition ? "PRECONDITION_FAILED"
                                : "VALIDATION_FAILED",
            source_precondition ? "SOURCE_INVALID_NESTED_ORIENTATION"
                                : "CANDIDATE_INVALID_NESTED_ORIENTATION",
            source_precondition
                ? "Closed source component orientations must alternate with containment nesting, starting outward"
                : "Closed candidate component orientations must alternate with containment nesting, starting outward");
      }
    }
    result.push_back(ComponentTopology{vertices - edges + faces,
                                       CGAL::number_of_borders(component),
                                       closed, orientation, nesting_level});
  }
  std::sort(result.begin(), result.end());
  return result;
}

Mesh open_component_mesh(const Mesh& mesh) {
  std::vector<Mesh> components;
  PMP::split_connected_components(mesh, components);
  Mesh result;
  for (const auto& component : components) {
    if (!CGAL::is_closed(component)) {
      CGAL::copy_face_graph(component, result);
    }
  }
  return result;
}

Point face_centroid(const Mesh& mesh, Mesh::Face_index face) {
  const auto first = mesh.halfedge(face);
  const auto second = mesh.next(first);
  const auto third = mesh.next(second);
  const auto& a = mesh.point(mesh.target(first));
  const auto& b = mesh.point(mesh.target(second));
  const auto& c = mesh.point(mesh.target(third));
  return Point(a.x() / 3.0 + b.x() / 3.0 + c.x() / 3.0,
               a.y() / 3.0 + b.y() / 3.0 + c.y() / 3.0,
               a.z() / 3.0 + b.z() / 3.0 + c.z() / 3.0);
}

ExactKernel::Vector_3 exact_face_normal(const Mesh& mesh,
                                        Mesh::Face_index face) {
  CGAL::Cartesian_converter<Kernel, ExactKernel> to_exact;
  const auto first = mesh.halfedge(face);
  const auto second = mesh.next(first);
  const auto third = mesh.next(second);
  const auto a = to_exact(mesh.point(mesh.target(first)));
  const auto b = to_exact(mesh.point(mesh.target(second)));
  const auto c = to_exact(mesh.point(mesh.target(third)));
  const auto normal = CGAL::cross_product(b - a, c - a);
  if (normal.squared_length() == ExactKernel::FT(0)) {
    throw WorkerError("VALIDATION_FAILED", "OPEN_SURFACE_NORMAL_UNDEFINED",
                      "Open surface normal cannot be determined");
  }
  return normal;
}

void require_matching_face_winding(const Mesh& query_mesh,
                                    const Mesh& reference_mesh) {
  using Primitive = CGAL::AABB_face_graph_triangle_primitive<Mesh>;
  using Traits = CGAL::AABB_traits_3<Kernel, Primitive>;
  using Tree = CGAL::AABB_tree<Traits>;
  Tree reference_tree(reference_mesh.faces().begin(),
                      reference_mesh.faces().end(), reference_mesh);
  reference_tree.accelerate_distance_queries();
  for (const auto query_face : query_mesh.faces()) {
    const auto closest =
        reference_tree.closest_point_and_primitive(
            face_centroid(query_mesh, query_face));
    const auto query_normal = exact_face_normal(query_mesh, query_face);
    const auto reference_normal =
        exact_face_normal(reference_mesh, closest.second);
    if (!(query_normal * reference_normal > ExactKernel::FT(0))) {
      throw WorkerError(
          "VALIDATION_FAILED", "OPEN_SURFACE_WINDING_CHANGED",
          "Open candidate surface winding disagrees with the source surface");
    }
  }
}

void validate_open_surface_winding(const Mesh& candidate,
                                   const Mesh& source) {
  const auto candidate_open = open_component_mesh(candidate);
  const auto source_open = open_component_mesh(source);
  if (candidate_open.number_of_faces() == 0 &&
      source_open.number_of_faces() == 0) {
    return;
  }
  if (candidate_open.number_of_faces() == 0 ||
      source_open.number_of_faces() == 0) {
    throw WorkerError("VALIDATION_FAILED", "OPEN_COMPONENTS_CHANGED",
                      "Candidate and source open components do not match");
  }
  require_matching_face_winding(candidate_open, source_open);
  require_matching_face_winding(source_open, candidate_open);
}

Json topology_json(const std::vector<ComponentTopology>& topology) {
  Json result = Json::array();
  for (const auto& component : topology) {
    Json item = {{"euler_characteristic", component.euler_characteristic},
                 {"border_count", component.border_count},
                 {"closed", component.closed},
                 {"orientation",
                  component.orientation == 1
                      ? "outward"
                      : (component.orientation == -1 ? "inward" : "open")}};
    item["nesting_level"] = component.nesting_level >= 0
                                ? Json(component.nesting_level)
                                : Json(nullptr);
    result.push_back(std::move(item));
  }
  return result;
}

Json run_integrity_validator(const Request& request) {
  require_wave_a_kernel(request);
  if (request.inputs.size() != 2) {
    throw WorkerError(
        "TYPE_ERROR", "INPUT_COUNT_MISMATCH",
        "mesh.validate.simplification_integrity requires candidate then source");
  }
  require_allowed_parameters(request.parameters);
  require_same_unit(request.inputs[0], request.inputs[1]);
  auto candidate = read_triangle_off(request.inputs[0]);
  auto source = read_triangle_off(request.inputs[1]);

  require_healthy_triangle_mesh(source, "Integrity source");
  validate_mesh_health(candidate);
  const auto source_topology = component_topology(source, true);
  const auto candidate_topology = component_topology(candidate, false);
  const auto source_components = source_topology.size();
  const auto candidate_components = candidate_topology.size();
  if (candidate_components != source_components) {
    throw WorkerError("VALIDATION_FAILED", "COMPONENT_COUNT_CHANGED",
                      "Simplification changed the connected component count");
  }

  const auto source_borders = CGAL::number_of_borders(source);
  const auto candidate_borders = CGAL::number_of_borders(candidate);
  const bool source_closed = CGAL::is_closed(source);
  const bool candidate_closed = CGAL::is_closed(candidate);
  if (source_closed != candidate_closed) {
    throw WorkerError("VALIDATION_FAILED", "CLOSEDNESS_CHANGED",
                      "Simplification changed mesh closedness");
  }
  if (source_borders != candidate_borders) {
    throw WorkerError("VALIDATION_FAILED", "BORDER_COUNT_CHANGED",
                      "Simplification changed the border cycle count");
  }
  if (!(source_topology == candidate_topology)) {
    throw WorkerError(
        "VALIDATION_FAILED", "COMPONENT_TOPOLOGY_CHANGED",
        "Simplification changed per-component Euler characteristic, border count, closedness, or orientation");
  }
  validate_open_surface_winding(candidate, source);
  if (source_closed) {
    // This whole-mesh predicate handles disjoint solids and nested cavity
    // shells. It accepts the cavity's required inward shell orientation and
    // rejects incompatible component orientations without modifying geometry.
    if (!PMP::does_bound_a_volume(source)) {
      throw WorkerError(
          "PRECONDITION_FAILED", "SOURCE_DOES_NOT_BOUND_VOLUME",
          "Closed source components must have mutually compatible orientations that bound a volume");
    }
    if (!PMP::does_bound_a_volume(candidate)) {
      throw WorkerError(
          "VALIDATION_FAILED", "CANDIDATE_DOES_NOT_BOUND_VOLUME",
          "Closed candidate components do not have compatible orientations that bound a volume");
    }
  }

  const bool preserve_border = preserve_border_parameter(request.parameters);
  const auto protected_edges =
      protected_segments(source, request.parameters, preserve_border);
  for (const auto& segment : protected_edges) {
    if (!contains_segment(candidate, segment)) {
      throw WorkerError("VALIDATION_FAILED", "PROTECTED_EDGE_CHANGED",
                        "A protected source edge is absent from the candidate");
    }
  }

  Json report = {
      {"status", "pass"},
      {"valid", true},
      {"triangulated", true},
      {"degenerate_face_count", 0},
      {"non_manifold_vertex_count", 0},
      {"self_intersection", false},
      {"source_component_count", source_components},
      {"candidate_component_count", candidate_components},
      {"source_border_count", source_borders},
      {"candidate_border_count", candidate_borders},
      {"closedness_preserved", true},
      {"component_topology_preserved", true},
      {"open_surface_winding_preserved", true},
      {"source_component_topology", topology_json(source_topology)},
      {"candidate_component_topology", topology_json(candidate_topology)},
      {"bounds_volume", source_closed ? Json(true) : Json(nullptr)},
      {"protected_edge_count", protected_edges.size()},
      {"protected_edges_preserved", true},
      {"effective_kernel",
       "CGAL::Exact_predicates_inexact_constructions_kernel"}};
  const auto path = write_validation_output(request, report);
  return success_result(request,
                        Json::array({validation_output(path)}), report);
}

}  // namespace

OperationDefinition simplification_integrity_validator_operation() {
  OperationDefinition definition{
      "mesh.validate.simplification_integrity", 1,
      {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "ValidationReport",
      "validator", run_integrity_validator};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel =
      "CGAL::Exact_predicates_inexact_constructions_kernel";
  definition.dependencies = {"Polygon_mesh_processing", "AABB_tree"};
  definition.info = {
      {"input_slots", Json::array({"candidate", "source"})},
      {"input_format", "off"},
      {"output_slot", "validation"},
      {"output_format", "json"},
      {"checks",
       Json::array({"valid_triangle_mesh", "no_degenerate_faces",
                    "manifold_vertices", "no_self_intersection",
                    "component_count", "per_component_euler_characteristic",
                    "per_component_border_count", "closedness",
                    "per_component_orientation_and_signed_volume",
                    "per_component_nesting_level_orientation",
                    "open_surface_winding",
                    "whole_mesh_bounds_volume_with_cavity_support",
                    "protected_edges"})},
      {"closed_component_orientation_policy",
       "orientation follows containment nesting parity (even outward, odd inward); inward nested cavity shells are legal"}};
  return definition;
}

}  // namespace cgal_master::wave_a
