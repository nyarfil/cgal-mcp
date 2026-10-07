// Wave D independent validators. They parse the candidate and source OFF files
// with the Wave D parser, derive topology/orientation/metrics with their own
// combinatorics, and bound the geometric deviation with a certified sampled
// two-sided Hausdorff estimate over a validator-owned uniform grid. None of
// them calls the PMP triangulation, refinement, remeshing, sizing or smoothing
// function under test.
#include "wave_d_common.h"

#include "../wave_c/wave_c_common.h"

#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>

#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <string>
#include <unordered_map>
#include <vector>

namespace cgal_master::wave_d {
namespace {

using wave_c::boolean_parameter;
using wave_c::enum_parameter;
using wave_c::fail_validation;
using wave_c::finish_validation;
using wave_c::require_input_count;
using wave_c::require_parameters;
using wave_c::require_same_unit;
using wave_c::typed_length_parameter;

// Contracted tolerances (documented in the operation catalog).
constexpr double kRelativeEps = 1e-9;            // exact-surface checks, relative to bbox diagonal
constexpr double kIsotropicMeanLow = 0.8;        // mean edge / target lower bound
constexpr double kIsotropicMeanHigh = 4.0 / 3.0; // mean edge / target upper bound
constexpr double kIsotropicMaxRatio = 2.0;       // longest edge / target
constexpr double kIsotropicMinRatio = 0.2;       // shortest edge / target
constexpr double kAdaptiveMaxRatio = 2.0;        // longest edge / max_edge_length
constexpr double kAdaptiveMinRatio = 0.2;        // shortest edge / min_edge_length

struct Inputs {
  RawMesh candidate;
  RawMesh source;
  MeshFacts candidate_facts;
  MeshFacts source_facts;
};

Inputs read_inputs(const Request& request, const std::string& validator,
                   std::initializer_list<const char*> source_types) {
  require_kernel(request);
  require_input_count(request, 2, validator);
  require_same_unit(request.inputs[0], request.inputs[1]);
  Inputs inputs;
  inputs.candidate = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  inputs.source = read_raw_mesh(request.inputs[1], source_types);
  inputs.candidate_facts = analyze(inputs.candidate);
  inputs.source_facts = analyze(inputs.source);
  return inputs;
}

double positive_length(const Request& request, const char* name, const std::string& unit) {
  const double value = typed_length_parameter(request, name, unit);
  if (!(value > 0)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be positive");
  }
  return value;
}

bool valid_triangle_mesh(const MeshFacts& facts) {
  return facts.all_triangles && facts.manifold_edges && facts.manifold_vertices &&
         facts.consistently_oriented && facts.degenerate_face_count == 0 &&
         facts.unreferenced_vertex_count == 0;
}

bool topology_preserved(const MeshFacts& source, const MeshFacts& candidate) {
  return source.euler_characteristic == candidate.euler_characteristic &&
         source.component_count == candidate.component_count &&
         source.boundary_loop_count == candidate.boundary_loop_count &&
         source.closed == candidate.closed;
}

struct TwoSided {
  Deviation forward;   // candidate -> source
  Deviation backward;  // source -> candidate
  double certified() const {
    return std::max(forward.certified_upper_bound, backward.certified_upper_bound);
  }
  Json json(double limit) const {
    return Json{{"method", "validator-owned barycentric lattice + uniform grid point-triangle "
                           "distance; certified bound = sampled maximum + lattice covering radius"},
                {"candidate_to_source_sampled", forward.sampled_maximum},
                {"candidate_to_source_certified", forward.certified_upper_bound},
                {"source_to_candidate_sampled", backward.sampled_maximum},
                {"source_to_candidate_certified", backward.certified_upper_bound},
                {"hausdorff_certified_upper_bound", certified()},
                {"sample_count", forward.sample_count + backward.sample_count},
                {"orientation_disagreements", forward.orientation_disagreements},
                {"max_deviation", limit}};
  }
};

TwoSided two_sided(const Inputs& inputs, double max_deviation) {
  const double resolution = max_deviation;
  return TwoSided{one_sided_deviation(inputs.candidate, inputs.source, resolution, true),
                  one_sided_deviation(inputs.source, inputs.candidate, resolution, false)};
}

bool orientation_preserved(const Inputs& inputs, const TwoSided& deviation) {
  if (inputs.source_facts.closed) {
    return inputs.candidate_facts.closed &&
           (inputs.source_facts.signed_volume > 0) == (inputs.candidate_facts.signed_volume > 0) &&
           inputs.candidate_facts.signed_volume != 0;
  }
  return deviation.forward.orientation_agrees;
}

// Same connectivity: compare per-face normals of the source cycles evaluated
// with source and candidate coordinates.
bool no_face_inverted(const Inputs& inputs) {
  RawMesh moved{inputs.candidate.vertices, inputs.source.faces};
  for (std::size_t face = 0; face < inputs.source.faces.size(); ++face) {
    const V3 before = face_normal(inputs.source, face);
    const V3 after = face_normal(moved, face);
    if (!(before[0] * after[0] + before[1] * after[1] + before[2] * after[2] > 0)) return false;
  }
  return true;
}

double boundary_distance(const RawMesh& from, const RawMesh& to) {
  const auto to_edges = boundary_edges(to);
  double result = 0;
  for (const auto vertex : boundary_vertices(from)) {
    double best = std::numeric_limits<double>::infinity();
    for (const auto& edge : to_edges) {
      best = std::min(best, point_segment_distance(from.vertices[vertex], to.vertices[edge[0]],
                                                   to.vertices[edge[1]]));
    }
    result = std::max(result, best);
  }
  return result;
}

std::string upper(std::string text) {
  for (auto& character : text) character = static_cast<char>(std::toupper(character));
  return text;
}

Json conclude(const Request& request, const std::string& validator, const std::string& validates,
              Json checks, Json details) {
  std::vector<std::string> failed;
  for (const auto& item : checks.items()) {
    if (item.value() != true) failed.push_back(item.key());
  }
  if (!failed.empty()) {
    std::string message = validator + " rejected the candidate:";
    for (const auto& name : failed) message += " " + name;
    message += " | " + details.dump();
    fail_validation(upper(failed.front()) + "_FAILED", message);
  }
  Json report = std::move(details);
  report["schema_version"] = 1;
  report["report_type"] = "ValidationReport";
  report["validates"] = validates;
  report["checks"] = std::move(checks);
  report["independence"] =
      "validator does not call the CGAL meshing/remeshing/smoothing function under test";
  return finish_validation(request, validator, std::move(report));
}

// ------------------------------------------------------------ triangulation --

Json run_triangulated_faces_validator(const Request& request) {
  const std::string validator = "mesh.validate.triangulated_faces";
  require_parameters(request, {}, {"method"});
  const auto inputs = read_inputs(request, validator, {"PolygonSoup3"});
  const auto& source = inputs.source;
  const auto& candidate = inputs.candidate;
  const bool vertices_identical = source.vertices == candidate.vertices;
  // Source incidence: vertex -> faces.
  std::vector<std::vector<std::size_t>> incident(source.vertices.size());
  for (std::size_t face = 0; face < source.faces.size(); ++face) {
    for (const auto vertex : source.faces[face]) incident[vertex].push_back(face);
  }
  bool assigned_uniquely = vertices_identical;
  std::vector<std::vector<std::size_t>> triangles_of(source.faces.size());
  for (std::size_t triangle = 0; vertices_identical && triangle < candidate.faces.size(); ++triangle) {
    const auto& corners = candidate.faces[triangle];
    std::vector<std::size_t> hosts = incident[corners[0]];
    for (std::size_t corner = 1; corner < corners.size(); ++corner) {
      std::vector<std::size_t> next;
      std::set_intersection(hosts.begin(), hosts.end(), incident[corners[corner]].begin(),
                            incident[corners[corner]].end(), std::back_inserter(next));
      hosts = std::move(next);
    }
    if (hosts.size() != 1) {
      assigned_uniquely = false;
      break;
    }
    triangles_of[hosts.front()].push_back(triangle);
  }
  bool counts_match = assigned_uniquely;
  bool cycles_reproduced = assigned_uniquely;
  bool oriented = assigned_uniquely;
  std::size_t polygon_faces = 0;
  for (std::size_t face = 0; assigned_uniquely && face < source.faces.size(); ++face) {
    const auto& polygon = source.faces[face];
    polygon_faces += polygon.size() > 3 ? 1 : 0;
    if (triangles_of[face].size() != polygon.size() - 2) counts_match = false;
    // Interior diagonals cancel; the remaining directed edges are the polygon cycle.
    std::multiset<std::pair<std::size_t, std::size_t>> directed;
    for (const auto triangle : triangles_of[face]) {
      const auto& corners = candidate.faces[triangle];
      for (std::size_t corner = 0; corner < 3; ++corner) {
        const std::pair<std::size_t, std::size_t> edge{corners[corner], corners[(corner + 1) % 3]};
        const auto reverse = directed.find({edge.second, edge.first});
        if (reverse != directed.end()) {
          directed.erase(reverse);
        } else {
          directed.insert(edge);
        }
      }
    }
    std::multiset<std::pair<std::size_t, std::size_t>> cycle;
    for (std::size_t corner = 0; corner < polygon.size(); ++corner) {
      cycle.insert({polygon[corner], polygon[(corner + 1) % polygon.size()]});
    }
    if (directed != cycle) cycles_reproduced = false;
    // Exact orientation of every triangle in the polygon's dominant projection.
    const V3 normal = face_normal(source, face);
    int axis = 0;
    for (int candidate_axis = 1; candidate_axis < 3; ++candidate_axis) {
      if (std::fabs(normal[candidate_axis]) > std::fabs(normal[axis])) axis = candidate_axis;
    }
    const int u = (axis + 1) % 3;
    const int v = (axis + 2) % 3;
    const auto expected = normal[axis] > 0 ? CGAL::LEFT_TURN : CGAL::RIGHT_TURN;
    for (const auto triangle : triangles_of[face]) {
      const auto& corners = candidate.faces[triangle];
      std::array<Epick::Point_2, 3> projected;
      for (int corner = 0; corner < 3; ++corner) {
        const auto& point = candidate.vertices[corners[corner]];
        projected[corner] = Epick::Point_2(point[u], point[v]);
      }
      if (CGAL::orientation(projected[0], projected[1], projected[2]) != expected) oriented = false;
    }
  }
  const auto source_boundary = boundary_edges(source);
  const auto candidate_boundary = boundary_edges(candidate);
  Json checks{{"candidate_valid_triangle_mesh", valid_triangle_mesh(inputs.candidate_facts)},
              {"vertices_identical_to_source", vertices_identical},
              {"every_triangle_in_exactly_one_source_face", assigned_uniquely},
              {"triangle_count_per_face_is_degree_minus_two", counts_match},
              {"face_boundary_cycles_reproduced", cycles_reproduced},
              {"triangles_consistently_oriented_with_face", oriented},
              {"boundary_edges_preserved", source_boundary == candidate_boundary},
              {"topology_preserved", topology_preserved(inputs.source_facts, inputs.candidate_facts)}};
  Json details{{"source", facts_json(inputs.source_facts)},
               {"candidate", facts_json(inputs.candidate_facts)},
               {"source_polygon_faces", polygon_faces}};
  return conclude(request, validator, "mesh.triangulate.faces", std::move(checks), std::move(details));
}

// --------------------------------------------------------------- refinement --

Json run_refinement_validator(const Request& request) {
  const std::string validator = "mesh.validate.refinement";
  require_parameters(request, {"max_deviation"});
  const auto inputs = read_inputs(request, validator, {"TriangleSurfaceMesh"});
  const double max_deviation = positive_length(request, "max_deviation", request.inputs[0].unit);
  const auto deviation = two_sided(inputs, max_deviation);
  const auto& s = inputs.source_facts;
  const auto& c = inputs.candidate_facts;
  const long long added_vertices =
      static_cast<long long>(c.vertex_count) - static_cast<long long>(s.vertex_count);
  const long long added_faces =
      static_cast<long long>(c.face_count) - static_cast<long long>(s.face_count);
  Json checks{{"candidate_valid_triangle_mesh", valid_triangle_mesh(c)},
              {"source_vertices_preserved", vertices_prefix_identical(inputs.source, inputs.candidate)},
              {"boundary_edges_preserved", boundary_edges(inputs.source) == boundary_edges(inputs.candidate)},
              {"interior_insertion_count_relation", added_vertices >= 0 && added_faces == 2 * added_vertices},
              {"topology_preserved", topology_preserved(s, c)},
              {"orientation_preserved", orientation_preserved(inputs, deviation)},
              {"hausdorff_within_max_deviation", deviation.certified() <= max_deviation},
              {"no_self_intersections", no_self_intersections(inputs.candidate)}};
  Json details{{"source", facts_json(s)},
               {"candidate", facts_json(c)},
               {"inserted_vertices", added_vertices},
               {"deviation", deviation.json(max_deviation)}};
  return conclude(request, validator, "mesh.refine.local", std::move(checks), std::move(details));
}

// ------------------------------------------------------- isotropic remeshing --

Json run_isotropic_validator(const Request& request) {
  const std::string validator = "mesh.validate.isotropic_remesh";
  require_parameters(request, {"target_edge_length", "max_deviation"});
  const auto inputs = read_inputs(request, validator, {"TriangleSurfaceMesh"});
  const double target = positive_length(request, "target_edge_length", request.inputs[0].unit);
  const double max_deviation = positive_length(request, "max_deviation", request.inputs[0].unit);
  const auto deviation = two_sided(inputs, max_deviation);
  const auto& s = inputs.source_facts;
  const auto& c = inputs.candidate_facts;
  const double boundary_gap = s.closed ? 0.0
                                       : std::max(boundary_distance(inputs.candidate, inputs.source),
                                                  boundary_distance(inputs.source, inputs.candidate));
  const bool band = c.mean_edge_length >= kIsotropicMeanLow * target &&
                    c.mean_edge_length <= kIsotropicMeanHigh * target &&
                    c.max_edge_length <= kIsotropicMaxRatio * target &&
                    c.min_edge_length >= kIsotropicMinRatio * target;
  Json checks{{"candidate_valid_triangle_mesh", valid_triangle_mesh(c)},
              {"topology_preserved", topology_preserved(s, c)},
              {"orientation_preserved", orientation_preserved(inputs, deviation)},
              {"boundary_on_source_boundary", boundary_gap <= max_deviation},
              {"edge_lengths_within_target_band", band},
              {"hausdorff_within_max_deviation", deviation.certified() <= max_deviation},
              {"no_self_intersections", no_self_intersections(inputs.candidate)}};
  Json details{{"source", facts_json(s)},
               {"candidate", facts_json(c)},
               {"target_edge_length", target},
               {"edge_length_band",
                {{"mean_ratio_range", {kIsotropicMeanLow, kIsotropicMeanHigh}},
                 {"max_ratio", kIsotropicMaxRatio},
                 {"min_ratio", kIsotropicMinRatio},
                 {"mean_ratio", c.mean_edge_length / target},
                 {"max_ratio_observed", c.max_edge_length / target},
                 {"min_ratio_observed", c.min_edge_length / target}}},
               {"boundary_gap", boundary_gap},
               {"deviation", deviation.json(max_deviation)}};
  return conclude(request, validator, "mesh.remesh.isotropic", std::move(checks), std::move(details));
}

// ----------------------------------------------------------- split long edges --

struct SplitCheck {
  bool new_vertices_on_source_edges = true;
  bool source_edges_fully_subdivided = true;
  bool pieces_within_max_length = true;
  double longest_piece = 0;
};

SplitCheck subdivided_edges(const RawMesh& source, const RawMesh& candidate, double max_length,
                            double eps) {
  SplitCheck result;
  const auto source_count = source.vertices.size();
  std::map<std::pair<std::size_t, std::size_t>, std::size_t> edge_ids;
  std::vector<std::array<std::size_t, 2>> source_edges;
  for (const auto& face : source.faces) {
    for (std::size_t corner = 0; corner < face.size(); ++corner) {
      auto a = face[corner];
      auto b = face[(corner + 1) % face.size()];
      if (a > b) std::swap(a, b);
      if (edge_ids.emplace(std::make_pair(a, b), source_edges.size()).second) {
        source_edges.push_back({a, b});
      }
    }
  }
  if ((candidate.vertices.size() - std::min(candidate.vertices.size(), source_count)) *
          source_edges.size() > 200000000ull) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED",
                      "Edge subdivision check exceeds the Wave D validator budget");
  }
  std::vector<std::set<std::size_t>> on_edge(candidate.vertices.size());
  for (std::size_t edge = 0; edge < source_edges.size(); ++edge) {
    on_edge[source_edges[edge][0]].insert(edge);
    on_edge[source_edges[edge][1]].insert(edge);
  }
  for (std::size_t vertex = source_count; vertex < candidate.vertices.size(); ++vertex) {
    for (std::size_t edge = 0; edge < source_edges.size(); ++edge) {
      const auto& a = source.vertices[source_edges[edge][0]];
      const auto& b = source.vertices[source_edges[edge][1]];
      if (point_segment_distance(candidate.vertices[vertex], a, b) <= eps) on_edge[vertex].insert(edge);
    }
    if (on_edge[vertex].size() != 1) result.new_vertices_on_source_edges = false;
  }
  std::vector<double> covered(source_edges.size(), 0);
  std::set<std::pair<std::size_t, std::size_t>> seen;
  for (const auto& face : candidate.faces) {
    for (std::size_t corner = 0; corner < face.size(); ++corner) {
      auto a = face[corner];
      auto b = face[(corner + 1) % face.size()];
      if (a > b) std::swap(a, b);
      if (!seen.insert({a, b}).second) continue;
      std::vector<std::size_t> common;
      std::set_intersection(on_edge[a].begin(), on_edge[a].end(), on_edge[b].begin(),
                            on_edge[b].end(), std::back_inserter(common));
      if (common.empty()) continue;
      const double length = distance(candidate.vertices[a], candidate.vertices[b]);
      for (const auto edge : common) covered[edge] += length;
      result.longest_piece = std::max(result.longest_piece, length);
      if (length > max_length * (1 + kRelativeEps)) result.pieces_within_max_length = false;
    }
  }
  for (std::size_t edge = 0; edge < source_edges.size(); ++edge) {
    const double length =
        distance(source.vertices[source_edges[edge][0]], source.vertices[source_edges[edge][1]]);
    if (std::fabs(covered[edge] - length) > kRelativeEps * std::max(1.0, length)) {
      result.source_edges_fully_subdivided = false;
    }
  }
  return result;
}

Json run_split_validator(const Request& request) {
  const std::string validator = "mesh.validate.split_long_edges";
  require_parameters(request, {"max_length"});
  const auto inputs = read_inputs(request, validator, {"TriangleSurfaceMesh"});
  const double max_length = positive_length(request, "max_length", request.inputs[0].unit);
  const auto& s = inputs.source_facts;
  const auto& c = inputs.candidate_facts;
  const double eps = kRelativeEps * std::max(s.bbox_diagonal, 1e-300);
  const bool prefix = vertices_prefix_identical(inputs.source, inputs.candidate);
  const auto partition = surface_partition(inputs.source, inputs.candidate, eps);
  const auto split = prefix ? subdivided_edges(inputs.source, inputs.candidate, max_length, eps)
                            : SplitCheck{false, false, false, 0};
  Json checks{{"candidate_valid_triangle_mesh", valid_triangle_mesh(c)},
              {"source_vertices_preserved", prefix},
              {"new_vertices_on_source_edges", split.new_vertices_on_source_edges},
              {"source_edges_fully_subdivided", split.source_edges_fully_subdivided},
              {"subdivided_pieces_within_max_length", split.pieces_within_max_length},
              {"every_triangle_inside_one_source_face", partition.every_triangle_inside_one_source_face},
              {"per_face_area_preserved", partition.per_face_area_preserved},
              {"every_source_face_covered", partition.every_source_face_covered},
              {"topology_preserved", topology_preserved(s, c)}};
  Json details{{"source", facts_json(s)},
               {"candidate", facts_json(c)},
               {"max_length", max_length},
               {"longest_subdivided_piece", split.longest_piece},
               {"maximum_relative_area_error", partition.maximum_relative_area_error},
               {"surface_tolerance", eps}};
  return conclude(request, validator, "mesh.remesh.split_long_edges", std::move(checks),
                  std::move(details));
}

// ---------------------------------------------------------------- smoothing --

Json run_tangential_validator(const Request& request) {
  const std::string validator = "mesh.validate.tangential_relaxation";
  require_parameters(request, {"max_deviation"});
  const auto inputs = read_inputs(request, validator, {"TriangleSurfaceMesh"});
  const double max_deviation = positive_length(request, "max_deviation", request.inputs[0].unit);
  const bool connectivity = inputs.source.vertices.size() == inputs.candidate.vertices.size() &&
                            same_faces(inputs.source, inputs.candidate);
  const auto deviation = two_sided(inputs, max_deviation);
  const auto& s = inputs.source_facts;
  const auto& c = inputs.candidate_facts;
  std::size_t moved = 0;
  if (connectivity) {
    for (std::size_t vertex = 0; vertex < inputs.source.vertices.size(); ++vertex) {
      moved += inputs.source.vertices[vertex] != inputs.candidate.vertices[vertex] ? 1 : 0;
    }
  }
  Json checks{{"candidate_valid_triangle_mesh", valid_triangle_mesh(c)},
              {"connectivity_identical", connectivity},
              {"boundary_vertices_fixed", connectivity && boundary_vertices_fixed(inputs.source, inputs.candidate)},
              {"no_face_inverted", connectivity && no_face_inverted(inputs)},
              {"min_angle_not_decreased", c.min_angle_degrees >= s.min_angle_degrees},
              {"hausdorff_within_max_deviation", deviation.certified() <= max_deviation},
              {"no_self_intersections", no_self_intersections(inputs.candidate)}};
  Json details{{"source", facts_json(s)},
               {"candidate", facts_json(c)},
               {"moved_vertices", moved},
               {"deviation", deviation.json(max_deviation)}};
  return conclude(request, validator, "mesh.smooth.tangential_relaxation", std::move(checks),
                  std::move(details));
}

Json run_shape_smoothing_validator(const Request& request) {
  const std::string validator = "mesh.validate.shape_smoothing";
  require_parameters(request, {"max_deviation", "preserve_volume"});
  const auto inputs = read_inputs(request, validator, {"TriangleSurfaceMesh"});
  const double max_deviation = positive_length(request, "max_deviation", request.inputs[0].unit);
  const bool preserve_volume = boolean_parameter(request, "preserve_volume");
  const bool connectivity = inputs.source.vertices.size() == inputs.candidate.vertices.size() &&
                            same_faces(inputs.source, inputs.candidate);
  const auto deviation = two_sided(inputs, max_deviation);
  const auto& s = inputs.source_facts;
  const auto& c = inputs.candidate_facts;
  const double roughness_before = umbrella_roughness(inputs.source);
  const double roughness_after = umbrella_roughness(inputs.candidate);
  Json checks{{"candidate_valid_triangle_mesh", valid_triangle_mesh(c)},
              {"connectivity_identical", connectivity},
              {"boundary_vertices_fixed", connectivity && boundary_vertices_fixed(inputs.source, inputs.candidate)},
              {"no_face_inverted", connectivity && no_face_inverted(inputs)},
              {"roughness_reduced", roughness_after < roughness_before},
              {"hausdorff_within_max_deviation", deviation.certified() <= max_deviation},
              {"no_self_intersections", no_self_intersections(inputs.candidate)}};
  if (preserve_volume) {
    checks["volume_preserved"] =
        s.closed && std::fabs(c.signed_volume - s.signed_volume) <= 1e-9 * std::fabs(s.signed_volume);
  }
  Json details{{"source", facts_json(s)},
               {"candidate", facts_json(c)},
               {"umbrella_roughness", {{"source", roughness_before}, {"candidate", roughness_after}}},
               {"preserve_volume", preserve_volume},
               {"deviation", deviation.json(max_deviation)}};
  return conclude(request, validator, "mesh.smooth.shape", std::move(checks), std::move(details));
}

// -------------------------------------------------------- adaptive remeshing --

Json run_adaptive_validator(const Request& request) {
  const std::string validator = "mesh.validate.adaptive_remesh";
  require_parameters(request, {"min_edge_length", "max_edge_length", "mode", "max_deviation"});
  const auto inputs = read_inputs(request, validator, {"TriangleSurfaceMesh"});
  const auto& unit = request.inputs[0].unit;
  const double minimum = positive_length(request, "min_edge_length", unit);
  const double maximum = positive_length(request, "max_edge_length", unit);
  const double max_deviation = positive_length(request, "max_deviation", unit);
  const auto mode = enum_parameter(request, "mode", {"isotropic_remeshing", "split_long_edges"});
  if (!(minimum < maximum)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      "min_edge_length must be smaller than max_edge_length");
  }
  const auto deviation = two_sided(inputs, max_deviation);
  const auto& s = inputs.source_facts;
  const auto& c = inputs.candidate_facts;
  Json checks{{"candidate_valid_triangle_mesh", valid_triangle_mesh(c)},
              {"topology_preserved", topology_preserved(s, c)},
              {"orientation_preserved", orientation_preserved(inputs, deviation)},
              {"hausdorff_within_max_deviation", deviation.certified() <= max_deviation},
              {"no_self_intersections", no_self_intersections(inputs.candidate)}};
  Json details{{"source", facts_json(s)},
               {"candidate", facts_json(c)},
               {"mode", mode},
               {"edge_length_range", {minimum, maximum}},
               {"deviation", deviation.json(max_deviation)}};
  if (mode == "isotropic_remeshing") {
    checks["edge_lengths_within_sizing_range"] =
        c.max_edge_length <= kAdaptiveMaxRatio * maximum &&
        c.min_edge_length >= kAdaptiveMinRatio * minimum;
    details["edge_length_band"] = {{"max_ratio", kAdaptiveMaxRatio},
                                   {"min_ratio", kAdaptiveMinRatio},
                                   {"max_ratio_observed", c.max_edge_length / maximum},
                                   {"min_ratio_observed", c.min_edge_length / minimum}};
  } else {
    const double eps = kRelativeEps * std::max(s.bbox_diagonal, 1e-300);
    const bool prefix = vertices_prefix_identical(inputs.source, inputs.candidate);
    const auto partition = surface_partition(inputs.source, inputs.candidate, eps);
    const auto split = prefix ? subdivided_edges(inputs.source, inputs.candidate,
                                                 kAdaptiveMaxRatio * maximum, eps)
                              : SplitCheck{false, false, false, 0};
    checks["source_vertices_preserved"] = prefix;
    checks["new_vertices_on_source_edges"] = split.new_vertices_on_source_edges;
    checks["source_edges_fully_subdivided"] = split.source_edges_fully_subdivided;
    checks["subdivided_pieces_within_sizing_range"] = split.pieces_within_max_length;
    checks["every_triangle_inside_one_source_face"] = partition.every_triangle_inside_one_source_face;
    checks["per_face_area_preserved"] = partition.per_face_area_preserved;
    details["longest_subdivided_piece"] = split.longest_piece;
    details["maximum_relative_area_error"] = partition.maximum_relative_area_error;
  }
  return conclude(request, validator, "mesh.remesh.adaptive", std::move(checks), std::move(details));
}

Json validator_info(std::initializer_list<const char*> checks,
                    std::initializer_list<const char*> parameters) {
  Json info{{"input_slots", {"candidate", "source"}},
            {"output_slot", "validation"},
            {"checks", Json::array()}};
  for (const char* check : checks) info["checks"].push_back(check);
  if (parameters.size() != 0) {
    info["bound_parameters"] = Json::array();
    for (const char* parameter : parameters) info["bound_parameters"].push_back(parameter);
  }
  return info;
}

}  // namespace

std::vector<OperationDefinition> remesh_validators() {
  std::vector<OperationDefinition> result;
  result.push_back(make_definition(
      "mesh.validate.triangulated_faces", {"TriangleSurfaceMesh", "PolygonSoup3"},
      "ValidationReport", "validator", run_triangulated_faces_validator, {"PMP_Remeshing"},
      validator_info({"candidate_valid_triangle_mesh", "vertices_identical_to_source",
                      "every_triangle_in_exactly_one_source_face",
                      "triangle_count_per_face_is_degree_minus_two",
                      "face_boundary_cycles_reproduced",
                      "triangles_consistently_oriented_with_face", "boundary_edges_preserved",
                      "topology_preserved"},
                     {})));
  result.push_back(make_definition(
      "mesh.validate.refinement", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "ValidationReport", "validator", run_refinement_validator, {"PMP_Remeshing"},
      validator_info({"candidate_valid_triangle_mesh", "source_vertices_preserved",
                      "boundary_edges_preserved", "interior_insertion_count_relation",
                      "topology_preserved", "orientation_preserved",
                      "hausdorff_within_max_deviation", "no_self_intersections"},
                     {"max_deviation"})));
  result.push_back(make_definition(
      "mesh.validate.isotropic_remesh", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "ValidationReport", "validator", run_isotropic_validator, {"PMP_Remeshing"},
      validator_info({"candidate_valid_triangle_mesh", "topology_preserved",
                      "orientation_preserved", "boundary_on_source_boundary",
                      "edge_lengths_within_target_band", "hausdorff_within_max_deviation",
                      "no_self_intersections"},
                     {"target_edge_length", "max_deviation"})));
  result.push_back(make_definition(
      "mesh.validate.split_long_edges", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "ValidationReport", "validator", run_split_validator, {"PMP_Remeshing"},
      validator_info({"candidate_valid_triangle_mesh", "source_vertices_preserved",
                      "new_vertices_on_source_edges", "source_edges_fully_subdivided",
                      "subdivided_pieces_within_max_length",
                      "every_triangle_inside_one_source_face", "per_face_area_preserved",
                      "every_source_face_covered", "topology_preserved"},
                     {"max_length"})));
  result.push_back(make_definition(
      "mesh.validate.tangential_relaxation", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "ValidationReport", "validator", run_tangential_validator, {"PMP_Remeshing"},
      validator_info({"candidate_valid_triangle_mesh", "connectivity_identical",
                      "boundary_vertices_fixed", "no_face_inverted", "min_angle_not_decreased",
                      "hausdorff_within_max_deviation", "no_self_intersections"},
                     {"max_deviation"})));
  result.push_back(make_definition(
      "mesh.validate.shape_smoothing", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "ValidationReport", "validator", run_shape_smoothing_validator, {"PMP_Remeshing"},
      validator_info({"candidate_valid_triangle_mesh", "connectivity_identical",
                      "boundary_vertices_fixed", "no_face_inverted", "roughness_reduced",
                      "hausdorff_within_max_deviation", "no_self_intersections"},
                     {"max_deviation", "preserve_volume"})));
  result.push_back(make_definition(
      "mesh.validate.adaptive_remesh", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"},
      "ValidationReport", "validator", run_adaptive_validator, {"PMP_Remeshing"},
      validator_info({"candidate_valid_triangle_mesh", "topology_preserved",
                      "orientation_preserved", "hausdorff_within_max_deviation",
                      "no_self_intersections"},
                     {"min_edge_length", "max_edge_length", "mode", "max_deviation"})));
  return result;
}

}  // namespace cgal_master::wave_d
