#include "mesh_io.h"
#include "wave_a_operations.h"

#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Bounded_distance_placement.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Bounded_normal_change_filter.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Constrained_placement.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Edge_count_ratio_stop_predicate.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Edge_count_stop_predicate.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Edge_length_cost.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Edge_length_stop_predicate.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Face_count_ratio_stop_predicate.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Face_count_stop_predicate.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/GarlandHeckbert_policies.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/LindstromTurk_cost.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/LindstromTurk_placement.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Midpoint_placement.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Polyhedral_envelope_filter.h>
#include <CGAL/Surface_mesh_simplification/edge_collapse.h>
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Polygon_mesh_processing/shape_predicates.h>
#include <CGAL/boost/graph/helpers.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <memory>
#include <optional>
#include <set>
#include <string>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>

namespace cgal_master::wave_a {
namespace {

namespace SMS = CGAL::Surface_mesh_simplification;

using ConstraintMap =
    Mesh::Property_map<Mesh::Edge_index, bool>;
using StopVariant = std::variant<
    SMS::Edge_count_stop_predicate<Mesh>,
    SMS::Edge_count_ratio_stop_predicate<Mesh>,
    SMS::Face_count_stop_predicate<Mesh>,
    SMS::Face_count_ratio_stop_predicate<Mesh>,
    SMS::Edge_length_stop_predicate<Kernel::FT>>;

class ConfiguredStopPredicate {
 public:
  explicit ConfiguredStopPredicate(StopVariant predicate)
      : predicate_(std::move(predicate)) {}

  template <typename Cost, typename Profile>
  bool operator()(const Cost& cost, const Profile& profile,
                  std::size_t initial_edges,
                  std::size_t current_edges) const {
    return std::visit(
        [&](const auto& predicate) {
          return predicate(cost, profile, initial_edges, current_edges);
        },
        predicate_);
  }

 private:
  StopVariant predicate_;
};

class OptionalNormalFilter {
 public:
  explicit OptionalNormalFilter(bool enabled = false) : enabled_(enabled) {}

  template <typename Profile>
  std::optional<typename Profile::Point> operator()(
      const Profile& profile,
      std::optional<typename Profile::Point> placement) const {
    if (!enabled_) return placement;
    return filter_(profile, std::move(placement));
  }

 private:
  bool enabled_;
  SMS::Bounded_normal_change_filter<> filter_;
};

class ConfiguredFilter {
  using EnvelopeFilter =
      SMS::Polyhedral_envelope_filter<Kernel, OptionalNormalFilter>;

  struct State {
    State(bool bounded_normal_change, bool use_envelope, double envelope)
        : normal(bounded_normal_change),
          envelope_enabled(use_envelope),
          envelope_filter(envelope, normal) {}

    OptionalNormalFilter normal;
    bool envelope_enabled;
    EnvelopeFilter envelope_filter;
  };

 public:
  ConfiguredFilter(bool bounded_normal_change, bool use_envelope,
                   double envelope)
      : state_(std::make_shared<State>(bounded_normal_change, use_envelope,
                                       use_envelope ? envelope : 1.0)) {}

  template <typename Profile>
  std::optional<typename Profile::Point> operator()(
      const Profile& profile,
      std::optional<typename Profile::Point> placement) const {
    if (state_->envelope_enabled) {
      return state_->envelope_filter(profile, std::move(placement));
    }
    return state_->normal(profile, std::move(placement));
  }

 private:
  std::shared_ptr<State> state_;
};

template <typename BasePlacement>
class ConfiguredPlacement {
  using BoundedPlacement =
      SMS::Bounded_distance_placement<BasePlacement, Kernel>;

 public:
  ConfiguredPlacement(const BasePlacement& base, bool bounded,
                      double maximum_distance)
      : base_(base),
        bounded_enabled_(bounded),
        bounded_(std::make_shared<BoundedPlacement>(
            bounded ? maximum_distance : 1.0, base)) {}

  template <typename Profile>
  std::optional<typename Profile::Point> operator()(
      const Profile& profile) const {
    if (bounded_enabled_) return (*bounded_)(profile);
    return base_(profile);
  }

 private:
  BasePlacement base_;
  bool bounded_enabled_;
  std::shared_ptr<BoundedPlacement> bounded_;
};

void require_allowed_parameters(const Json& parameters) {
  static const std::set<std::string> allowed = {
      "stop", "policy", "preserve_border", "constrained_edges",
      "bounded_distance", "polyhedral_envelope", "bounded_normal_change",
      "max_symmetric_deviation", "hausdorff_error_bound",
      "foldover_policy", "max_retry_rounds", "accept_target_shortfall"};
  for (auto iterator = parameters.begin(); iterator != parameters.end();
       ++iterator) {
    if (allowed.find(iterator.key()) == allowed.end()) {
      throw WorkerError("INVALID_REQUEST", "UNSUPPORTED_PARAMETER",
                        "Unsupported mesh.simplify.edge_collapse parameter: " +
                            iterator.key());
    }
  }
}

bool boolean_parameter(const Json& parameters, const char* name,
                       bool default_value) {
  if (!parameters.contains(name)) return default_value;
  if (!parameters.at(name).is_boolean()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " must be boolean");
  }
  return parameters.at(name).get<bool>();
}

std::string policy_parameter(const Json& parameters) {
  if (!parameters.contains("policy") ||
      !parameters.at("policy").is_string()) {
    throw WorkerError("INVALID_REQUEST", "MISSING_OR_INVALID_PARAMETER",
                      "policy must name an edge-collapse policy");
  }
  return parameters.at("policy").get<std::string>();
}

ConfiguredStopPredicate parse_stop(const Json& parameters, const Mesh& mesh,
                                   const std::string& unit,
                                   std::string& kind_out) {
  if (!parameters.contains("stop") || !parameters.at("stop").is_object()) {
    throw WorkerError("INVALID_REQUEST", "MISSING_OR_INVALID_PARAMETER",
                      "stop must be an object with kind and value");
  }
  const auto& stop = parameters.at("stop");
  if (stop.size() != 2 || !stop.contains("kind") ||
      !stop.at("kind").is_string() || !stop.contains("value")) {
    throw WorkerError("INVALID_REQUEST", "INVALID_STOP_POLICY",
                      "stop must contain only kind and value");
  }
  const auto kind = stop.at("kind").get<std::string>();
  kind_out = kind;
  if (kind == "edge_count" || kind == "face_count") {
    if (!stop.at("value").is_number_unsigned()) {
      throw WorkerError("INVALID_REQUEST", "INVALID_STOP_VALUE",
                        kind + " value must be an unsigned integer");
    }
    const auto value = stop.at("value").get<std::size_t>();
    if (kind == "edge_count") {
      return ConfiguredStopPredicate(
          SMS::Edge_count_stop_predicate<Mesh>(value));
    }
    return ConfiguredStopPredicate(
        SMS::Face_count_stop_predicate<Mesh>(value));
  }
  if (kind == "edge_ratio" || kind == "face_ratio") {
    if (!stop.at("value").is_number()) {
      throw WorkerError("INVALID_REQUEST", "INVALID_STOP_VALUE",
                        kind + " value must be numeric");
    }
    const auto value = stop.at("value").get<double>();
    if (!std::isfinite(value) || value <= 0 || value > 1) {
      throw WorkerError("INVALID_REQUEST", "INVALID_STOP_VALUE",
                        kind + " value must be in (0, 1]");
    }
    if (kind == "edge_ratio") {
      return ConfiguredStopPredicate(
          SMS::Edge_count_ratio_stop_predicate<Mesh>(value));
    }
    return ConfiguredStopPredicate(
        SMS::Face_count_ratio_stop_predicate<Mesh>(value, mesh));
  }
  if (kind == "edge_length") {
    const auto value = typed_length(stop.at("value"), unit, "stop.value",
                                    true);
    return ConfiguredStopPredicate(
        SMS::Edge_length_stop_predicate<Kernel::FT>(value));
  }
  throw WorkerError("INVALID_REQUEST", "UNKNOWN_STOP_POLICY",
                    "Unknown edge-collapse stop policy: " + kind);
}

ConstraintMap configure_constraints(Mesh& mesh, const Json& parameters,
                                    bool preserve_border,
                                    std::size_t& constrained_count) {
  auto result = mesh.add_property_map<Mesh::Edge_index, bool>(
      "e:wave_a_constraints", false);
  auto constraints = result.first;
  if (preserve_border) {
    for (const auto edge : mesh.edges()) {
      if (CGAL::is_border(edge, mesh)) constraints[edge] = true;
    }
  }
  if (parameters.contains("constrained_edges")) {
    const auto& pairs = parameters.at("constrained_edges");
    if (!pairs.is_array()) {
      throw WorkerError("INVALID_REQUEST", "INVALID_CONSTRAINTS",
                        "constrained_edges must be an array of vertex pairs");
    }
    for (const auto& pair : pairs) {
      if (!pair.is_array() || pair.size() != 2 ||
          !pair[0].is_number_unsigned() || !pair[1].is_number_unsigned()) {
        throw WorkerError("INVALID_REQUEST", "INVALID_CONSTRAINTS",
                          "Each constrained edge must be [u, v]");
      }
      const auto source_index = pair[0].get<std::size_t>();
      const auto target_index = pair[1].get<std::size_t>();
      if (source_index >= mesh.number_of_vertices() ||
          target_index >= mesh.number_of_vertices() ||
          source_index == target_index) {
        throw WorkerError("INVALID_REQUEST", "INVALID_CONSTRAINT_EDGE",
                          "Constrained edge vertex index is invalid");
      }
      const auto halfedge = mesh.halfedge(Mesh::Vertex_index(source_index),
                                          Mesh::Vertex_index(target_index));
      if (halfedge == Mesh::null_halfedge()) {
        throw WorkerError("INVALID_REQUEST", "CONSTRAINT_EDGE_NOT_FOUND",
                          "Constrained vertex pair is not an input mesh edge");
      }
      constraints[mesh.edge(halfedge)] = true;
    }
  }
  constrained_count = 0;
  for (const auto edge : mesh.edges()) {
    if (constraints[edge]) ++constrained_count;
  }
  return constraints;
}


// Self-intersection control (foldover_policy = protect_and_retry).
struct DefectScan {
  std::size_t intersecting_pairs = 0;
  std::size_t degenerate_faces = 0;
  std::vector<Point> centers;  // centroids of every defective candidate face
};

Point face_centroid(const Mesh& mesh, Mesh::Face_index face) {
  double x = 0, y = 0, z = 0;
  for (const auto vertex : mesh.vertices_around_face(mesh.halfedge(face))) {
    const auto& point = mesh.point(vertex);
    x += point.x();
    y += point.y();
    z += point.z();
  }
  return Point(x / 3.0, y / 3.0, z / 3.0);
}

DefectScan scan_defects(const Mesh& mesh) {
  namespace PMP = CGAL::Polygon_mesh_processing;
  DefectScan scan;
  std::set<Mesh::Face_index> bad;
  for (const auto face : mesh.faces()) {
    if (PMP::is_degenerate_triangle_face(face, mesh)) {
      bad.insert(face);
      ++scan.degenerate_faces;
    }
  }
  if (scan.degenerate_faces == 0) {
    std::vector<std::pair<Mesh::Face_index, Mesh::Face_index>> pairs;
    PMP::self_intersections(mesh, std::back_inserter(pairs));
    scan.intersecting_pairs = pairs.size();
    for (const auto& pair : pairs) {
      bad.insert(pair.first);
      bad.insert(pair.second);
    }
  }
  for (const auto face : bad) scan.centers.push_back(face_centroid(mesh, face));
  return scan;
}

double mean_edge_length(const Mesh& mesh) {
  double total = 0;
  std::size_t count = 0;
  for (const auto edge : mesh.edges()) {
    const auto halfedge = mesh.halfedge(edge);
    total += std::sqrt(CGAL::to_double(CGAL::squared_distance(
        mesh.point(mesh.source(halfedge)), mesh.point(mesh.target(halfedge)))));
    ++count;
  }
  return count == 0 ? 0.0 : total / static_cast<double>(count);
}

// Marks every not yet constrained edge whose midpoint lies within `radius`
// of a defect centre as constrained (it can no longer be collapsed).
std::size_t protect_near(const Mesh& mesh, ConstraintMap& constraints,
                         const std::vector<Point>& centers, double radius) {
  std::size_t added = 0;
  const double squared_radius = radius * radius;
  for (const auto edge : mesh.edges()) {
    if (constraints[edge]) continue;
    const auto halfedge = mesh.halfedge(edge);
    const auto& a = mesh.point(mesh.source(halfedge));
    const auto& b = mesh.point(mesh.target(halfedge));
    const double mx = (a.x() + b.x()) * 0.5, my = (a.y() + b.y()) * 0.5,
                 mz = (a.z() + b.z()) * 0.5;
    for (const auto& center : centers) {
      const double dx = mx - center.x(), dy = my - center.y(),
                   dz = mz - center.z();
      if (dx * dx + dy * dy + dz * dz <= squared_radius) {
        constraints[edge] = true;
        ++added;
        break;
      }
    }
  }
  return added;
}

template <typename Cost, typename Placement>
int collapse_with(Mesh& mesh, const ConfiguredStopPredicate& stop,
                  const Cost& cost, const Placement& placement,
                  const ConstraintMap& constraints,
                  const ConfiguredFilter& filter, bool bounded_distance,
                  double maximum_distance) {
  ConfiguredPlacement<Placement> configured_placement(
      placement, bounded_distance, maximum_distance);
  SMS::Constrained_placement<ConfiguredPlacement<Placement>, ConstraintMap>
      constrained_placement(constraints, configured_placement);
  return SMS::edge_collapse(
      mesh, stop,
      CGAL::parameters::get_cost(cost)
          .get_placement(constrained_placement)
          .edge_is_constrained_map(constraints)
          .filter(filter));
}

template <typename Policies>
int collapse_with_gh(Mesh& mesh, const ConfiguredStopPredicate& stop,
                     const ConstraintMap& constraints,
                     const ConfiguredFilter& filter, bool bounded_distance,
                     double maximum_distance) {
  Policies policies(mesh);
  return collapse_with(mesh, stop, policies.get_cost(),
                       policies.get_placement(), constraints, filter,
                       bounded_distance, maximum_distance);
}

int dispatch_policy(const std::string& policy, Mesh& mesh,
                    const ConfiguredStopPredicate& stop,
                    const ConstraintMap& constraints,
                    const ConfiguredFilter& filter, bool bounded_distance,
                    double maximum_distance) {
  if (policy == "lindstrom_turk") {
    return collapse_with(mesh, stop, SMS::LindstromTurk_cost<Mesh>(),
                         SMS::LindstromTurk_placement<Mesh>(), constraints,
                         filter, bounded_distance, maximum_distance);
  }
  if (policy == "edge_length_midpoint") {
    return collapse_with(mesh, stop, SMS::Edge_length_cost<Mesh>(),
                         SMS::Midpoint_placement<Mesh>(), constraints, filter,
                         bounded_distance, maximum_distance);
  }
  if (policy == "gh_plane") {
    return collapse_with_gh<
        SMS::GarlandHeckbert_plane_policies<Mesh, Kernel>>(
        mesh, stop, constraints, filter, bounded_distance, maximum_distance);
  }
  if (policy == "gh_triangle") {
    return collapse_with_gh<
        SMS::GarlandHeckbert_triangle_policies<Mesh, Kernel>>(
        mesh, stop, constraints, filter, bounded_distance, maximum_distance);
  }
  if (policy == "gh_plane_line") {
    return collapse_with_gh<
        SMS::GarlandHeckbert_plane_and_line_policies<Mesh, Kernel>>(
        mesh, stop, constraints, filter, bounded_distance, maximum_distance);
  }
  if (policy == "gh_probabilistic_plane") {
    return collapse_with_gh<
        SMS::GarlandHeckbert_probabilistic_plane_policies<Mesh, Kernel>>(
        mesh, stop, constraints, filter, bounded_distance, maximum_distance);
  }
  if (policy == "gh_probabilistic_triangle") {
    return collapse_with_gh<
        SMS::GarlandHeckbert_probabilistic_triangle_policies<Mesh, Kernel>>(
        mesh, stop, constraints, filter, bounded_distance, maximum_distance);
  }
  throw WorkerError("INVALID_REQUEST", "UNKNOWN_SIMPLIFICATION_POLICY",
                    "Unknown edge-collapse policy: " + policy);
}

Json run_simplify_edge_collapse(const Request& request) {
  require_wave_a_kernel(request);
  if (request.inputs.size() != 1) {
    throw WorkerError("TYPE_ERROR", "INPUT_COUNT_MISMATCH",
                      "mesh.simplify.edge_collapse requires one mesh input");
  }
  require_allowed_parameters(request.parameters);
  auto mesh = read_triangle_off(request.inputs.front());
  require_healthy_triangle_mesh(mesh, "Simplification input");

  const auto& unit = request.inputs.front().unit;
  const auto policy = policy_parameter(request.parameters);
  std::string stop_kind;
  const auto stop = parse_stop(request.parameters, mesh, unit, stop_kind);
  const bool preserve_border =
      boolean_parameter(request.parameters, "preserve_border", true);
  const bool bounded_normal_change =
      boolean_parameter(request.parameters, "bounded_normal_change", false);

  // These values are consumed by mandatory validator bindings in the parent
  // DAG. Validate them here too so a standalone worker request cannot claim a
  // simplification result without a complete validation contract.
  if (!request.parameters.contains("max_symmetric_deviation") ||
      !request.parameters.contains("hausdorff_error_bound")) {
    throw WorkerError(
        "INVALID_REQUEST", "MISSING_VALIDATION_BOUND",
        "max_symmetric_deviation and hausdorff_error_bound are required");
  }
  typed_length(request.parameters.at("max_symmetric_deviation"), unit,
               "max_symmetric_deviation");
  typed_length(request.parameters.at("hausdorff_error_bound"), unit,
               "hausdorff_error_bound", true);

  bool bounded_distance = request.parameters.contains("bounded_distance");
  double maximum_distance = 0;
  if (bounded_distance) {
    maximum_distance =
        typed_length(request.parameters.at("bounded_distance"), unit,
                     "bounded_distance", true);
  }
  bool use_envelope = request.parameters.contains("polyhedral_envelope");
  double envelope = 0;
  if (use_envelope) {
    envelope = typed_length(request.parameters.at("polyhedral_envelope"), unit,
                            "polyhedral_envelope", true);
  }

  std::string intersection_policy = "reject";
  if (request.parameters.contains("foldover_policy")) {
    const auto& value = request.parameters.at("foldover_policy");
    if (!value.is_string() ||
        (value.get<std::string>() != "reject" &&
         value.get<std::string>() != "protect_and_retry")) {
      throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                        "foldover_policy must be reject or "
                        "protect_and_retry");
    }
    intersection_policy = value.get<std::string>();
  }
  const bool retrying = intersection_policy == "protect_and_retry";
  std::size_t max_rounds = 4;
  if (request.parameters.contains("max_retry_rounds")) {
    const auto& value = request.parameters.at("max_retry_rounds");
    if (!retrying) {
      throw WorkerError("INVALID_REQUEST", "RETRY_ROUNDS_WITHOUT_POLICY",
                        "max_retry_rounds requires foldover_policy "
                        "protect_and_retry");
    }
    if (!value.is_number_unsigned() || value.get<std::size_t>() < 1 ||
        value.get<std::size_t>() > 8) {
      throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                        "max_retry_rounds must be an integer in [1, 8]");
    }
    max_rounds = value.get<std::size_t>();
  }
  const bool accept_shortfall =
      boolean_parameter(request.parameters, "accept_target_shortfall", false);
  if (accept_shortfall && !retrying) {
    throw WorkerError("INVALID_REQUEST", "SHORTFALL_WITHOUT_POLICY",
                      "accept_target_shortfall requires "
                      "foldover_policy protect_and_retry");
  }

  const Mesh source = mesh;
  const auto vertices_before = source.number_of_vertices();
  const auto edges_before = source.number_of_edges();
  const auto faces_before = source.number_of_faces();
  ConfiguredFilter filter(bounded_normal_change, use_envelope, envelope);

  // Count target of the stop rule (for the honest shortfall report).
  const auto& stop_json = request.parameters.at("stop");
  std::optional<double> target_faces, target_edges;
  if (stop_kind == "face_count") {
    target_faces = static_cast<double>(stop_json.at("value").get<std::size_t>());
  } else if (stop_kind == "face_ratio") {
    target_faces = stop_json.at("value").get<double>() *
                   static_cast<double>(faces_before);
  } else if (stop_kind == "edge_count") {
    target_edges = static_cast<double>(stop_json.at("value").get<std::size_t>());
  } else if (stop_kind == "edge_ratio") {
    target_edges = stop_json.at("value").get<double>() *
                   static_cast<double>(edges_before);
  }
  const auto target_reached = [&](const Mesh& candidate) {
    if (target_faces) {
      return static_cast<double>(candidate.number_of_faces()) <= *target_faces;
    }
    if (target_edges) {
      return static_cast<double>(candidate.number_of_edges()) <= *target_edges;
    }
    return true;
  };

  std::size_t constrained_count = 0;
  std::size_t protected_count = 0;
  int removed = 0;
  Json attempts = Json::array();
  std::vector<Point> centers;
  const double base_radius = 3.0 * mean_edge_length(source);
  bool first_round_reached_target = true;
  std::size_t rounds = 0;
  std::size_t final_pairs = 0;
  bool resolved = !retrying;
  const std::size_t round_limit = retrying ? max_rounds + 1 : 1;
  for (std::size_t round = 1; round <= round_limit; ++round) {
    Mesh candidate = source;
    std::size_t user_constrained = 0;
    auto constraints = configure_constraints(candidate, request.parameters,
                                             preserve_border, user_constrained);
    protected_count = 0;
    if (!centers.empty()) {
      protected_count = protect_near(candidate, constraints, centers, base_radius);
    }
    constrained_count = user_constrained + protected_count;
    removed = dispatch_policy(policy, candidate, stop, constraints, filter,
                              bounded_distance, maximum_distance);
    if (!CGAL::is_valid_polygon_mesh(candidate) ||
        !CGAL::is_triangle_mesh(candidate) || candidate.number_of_faces() == 0) {
      throw WorkerError("INTERNAL", "INVALID_SIMPLIFICATION_OUTPUT",
                        "Edge collapse produced an invalid triangle mesh");
    }
    rounds = round;
    if (!retrying) {
      mesh = std::move(candidate);
      break;
    }
    auto scan = scan_defects(candidate);
    final_pairs = scan.intersecting_pairs + scan.degenerate_faces;
    if (round == 1) first_round_reached_target = target_reached(candidate);
    attempts.push_back({{"attempt", round},
                        {"protected_edge_count", protected_count},
                        {"faces_after", candidate.number_of_faces()},
                        {"intersecting_pairs", scan.intersecting_pairs},
                        {"degenerate_faces", scan.degenerate_faces}});
    if (final_pairs == 0) {
      resolved = true;
      mesh = std::move(candidate);
      break;
    }
    centers.insert(centers.end(), scan.centers.begin(), scan.centers.end());
    if (round == round_limit) mesh = std::move(candidate);
  }
  if (!resolved) {
    throw WorkerError(
        "PRECONDITION_FAILED", "SELF_INTERSECTION_UNRESOLVED",
        "protect_and_retry could not remove all self-intersections within " +
            std::to_string(max_rounds) + " retry rounds; the last attempt kept " +
            std::to_string(mesh.number_of_faces()) + " faces with " +
            std::to_string(final_pairs) +
            " defective face pairs (no result is published; use a larger "
            "face target or more retry rounds)");
  }
  const bool reached = target_reached(mesh);
  if (retrying && first_round_reached_target && !reached &&
      !accept_shortfall) {
    throw WorkerError(
        "PRECONDITION_FAILED", "TARGET_NOT_REACHABLE_WITHOUT_SELF_INTERSECTION",
        "The requested size is not reachable without self-intersection: the "
        "best intersection-free result has " +
            std::to_string(mesh.number_of_faces()) + " faces and " +
            std::to_string(mesh.number_of_edges()) +
            " edges (raise the target to this value, or set "
            "accept_target_shortfall to publish it)");
  }

  const auto path = write_mesh_output(request, mesh);
  Json outputs = Json::array({geometry_output(path, unit)});
  Json metrics = {
      {"vertices_before", vertices_before},
      {"vertices_after", mesh.number_of_vertices()},
      {"edges_before", edges_before},
      {"edges_after", mesh.number_of_edges()},
      {"faces_before", faces_before},
      {"faces_after", mesh.number_of_faces()},
      {"edges_removed", removed},
      {"policy", policy},
      {"stop_policy", stop_kind},
      {"constrained_edge_count", constrained_count},
      {"preserve_border", preserve_border},
      {"bounded_distance_enabled", bounded_distance},
      {"bounded_normal_change_enabled", bounded_normal_change},
      {"polyhedral_envelope_enabled", use_envelope},
      {"effective_kernel",
       "CGAL::Exact_predicates_inexact_constructions_kernel"}};
  if (retrying) {
    metrics["foldover_policy"] = intersection_policy;
    metrics["retry_attempts"] = rounds;
    metrics["protected_edge_count"] = protected_count;
    metrics["final_self_intersecting_pairs"] = 0;
    metrics["target_reached"] = reached;
    metrics["attempt_log"] = attempts;
  }
  return success_result(request, std::move(outputs), std::move(metrics));
}

}  // namespace

OperationDefinition simplify_edge_collapse_operation() {
  OperationDefinition definition{
      "mesh.simplify.edge_collapse", 1, {"TriangleSurfaceMesh"},
      "TriangleSurfaceMesh", "transform", run_simplify_edge_collapse};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel =
      "CGAL::Exact_predicates_inexact_constructions_kernel";
  definition.dependencies = {"Surface_mesh_simplification",
                             "Polygon_mesh_processing", "Eigen3"};
  definition.info = {
      {"input_format", "off"},
      {"output_format", "off"},
      {"unit_dimension", "length"},
      {"supported_units", Json::array({"mm", "cm", "m"})},
      {"policy_parameter", "policy"},
      {"policies",
       Json::array({"lindstrom_turk", "edge_length_midpoint", "gh_plane",
                    "gh_triangle", "gh_plane_line",
                    "gh_probabilistic_plane",
                    "gh_probabilistic_triangle"})},
      {"stop_parameter", "stop"},
      {"stop_policies",
       Json::array({"edge_count", "edge_ratio", "face_count", "face_ratio",
                    "edge_length"})},
      {"optional_constraints",
       Json::array({"preserve_border", "constrained_edges",
                    "bounded_distance", "bounded_normal_change",
                    "polyhedral_envelope"})},
      {"foldover_policies",
       Json::array({"reject", "protect_and_retry"})},
      {"validator_parameter_bindings",
       {{"mesh.validate.simplification_integrity",
         {{"preserve_border", "preserve_border"},
          {"constrained_edges", "constrained_edges"}}},
        {"mesh.distance.symmetric_hausdorff",
         {{"tolerance", "max_symmetric_deviation"},
          {"error_bound", "hausdorff_error_bound"}}}}}};
  return definition;
}

}  // namespace cgal_master::wave_a
