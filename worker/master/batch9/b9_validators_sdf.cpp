// Independent validators for the shape-diameter-function producers (7.8.01): mesh.segment.sdf_values
// (CGAL::sdf_values) and mesh.segment.sdf (CGAL::segmentation_from_sdf_values). No CGAL header is included.
//
// Thickness check. CGAL's raw SDF value of a facet is a weighted mean of a subset of the lengths of rays cast
// from the facet centroid inside the cone of half-angle cone_angle/2 around the inward facet normal, each length
// measured to the first exit through the surface. Such a mean lies between the smallest and the largest
// first-hit distance over the cone. The validator casts its own deterministic rays (the axis plus 4 rings of 16
// directions reaching the cone boundary; long double Moller-Trumbore against every other facet) and requires
// every raw value to lie in [L_min (1 - tolerance), L_max (1 + tolerance)] where tolerance is the declared
// thickness_tolerance parameter. The tolerance absorbs the sampling gap between the validator's rays and
// CGAL's Vogel-disk rays; it is a declared bound, not a CGAL guarantee. Segmentation consistency (cluster ids,
// segment ids equal to the edge-connected components of the cluster partition, full facet coverage) is exact.

#include "b9_common.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <numeric>
#include <set>

namespace cgal_master::batch9 {
namespace {

using batch2::concluded;
using batch2::require_member;
using batch2::vinfo;
using query_ops::read_raw_mesh;
using query_ops::read_report;
using query_ops::require_inputs;
using query_ops::require_parameter_names;
using query_ops::validation_failure;

using LD = long double;
constexpr int kRings = 4;
constexpr int kAzimuths = 16;

struct P3 {
  LD x, y, z;
};
P3 operator-(const P3& a, const P3& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
P3 operator+(const P3& a, const P3& b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
P3 operator*(LD s, const P3& a) { return {s * a.x, s * a.y, s * a.z}; }
LD dot(const P3& a, const P3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
P3 cross(const P3& a, const P3& b) { return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x}; }
LD norm(const P3& a) { return std::sqrt(dot(a, a)); }

struct Loaded {
  RawMesh mesh;
  std::vector<double> raw;
  Json results;
  Json checks;
  LD diagonal = 0;
};

std::vector<double> read_values(const Json& value, std::size_t count, const std::string& context) {
  if (!value.is_array() || value.size() != count) {
    validation_failure("SDF_COUNT_MISMATCH", context + " must hold one value per facet");
  }
  std::vector<double> result;
  for (const auto& item : value) {
    if (!item.is_number() || item.is_boolean() || !std::isfinite(item.get<double>())) {
      validation_failure("REPORT_VALUE_INVALID", context + " entries must be finite numbers");
    }
    result.push_back(item.get<double>());
  }
  return result;
}

Loaded load(const Request& request, const std::string& operation, const std::string& kind) {
  require_inputs(request, 2, operation);
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", kind);
  Loaded c;
  c.mesh = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  batch2::require_triangle_faces(c.mesh, "The mesh", kMaximumSegmentationFaces);
  const auto topology = batch8::analyze_topology(c.mesh);
  if (topology.unreferenced_vertex || !topology.closed || batch8::signed_volume(c.mesh) <= 0) {
    validation_failure("MESH_NOT_CLOSED_OUTWARD", "The mesh must be a closed outward oriented 2-manifold");
  }
  for (const auto& face : c.mesh.faces) {
    if (batch2::tri_degenerate(batch2::make_tri(c.mesh, face))) {
      validation_failure("DEGENERATE_FACET", "The mesh has a degenerate facet");
    }
  }
  c.checks["mesh_closed_outward"] = true;
  const std::string producer = kind == "sdf_values" ? "mesh.segment.sdf_values" : "mesh.segment.sdf";
  c.results = batch2::check_report_frame(report, producer, request.parameters, {{"mesh_sha256", &request.inputs[1]}},
                                         c.checks);
  if (require_member(c.results, "distance_unit", "results") != request.inputs[1].unit) {
    validation_failure("UNIT_MISMATCH", "The report distance unit differs from the mesh unit");
  }
  c.checks["distance_unit_matches_mesh"] = true;
  c.raw = read_values(require_member(c.results, "raw_sdf", "results"), c.mesh.faces.size(), "raw_sdf");
  c.checks["one_value_per_facet"] = true;
  P3 lo{INFINITY, INFINITY, INFINITY}, hi{-INFINITY, -INFINITY, -INFINITY};
  for (const auto& v : c.mesh.vertices) {
    lo = {std::min<LD>(lo.x, v[0]), std::min<LD>(lo.y, v[1]), std::min<LD>(lo.z, v[2])};
    hi = {std::max<LD>(hi.x, v[0]), std::max<LD>(hi.y, v[1]), std::max<LD>(hi.z, v[2])};
  }
  c.diagonal = norm(hi - lo);
  return c;
}

P3 point(const RawMesh& mesh, std::size_t index) {
  const auto& v = mesh.vertices.at(index);
  return {v[0], v[1], v[2]};
}

// First positive hit distance of the ray origin + t * direction (|direction| = 1) against every facet but `own`.
LD first_hit(const RawMesh& mesh, std::size_t own, const P3& origin, const P3& direction) {
  LD best = INFINITY;
  constexpr LD eps = 1e-12L;
  for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
    if (f == own) continue;
    const P3 a = point(mesh, mesh.faces[f][0]), b = point(mesh, mesh.faces[f][1]), c = point(mesh, mesh.faces[f][2]);
    const P3 e1 = b - a, e2 = c - a;
    const P3 h = cross(direction, e2);
    const LD det = dot(e1, h);
    if (std::fabs(det) < 1e-30L) continue;
    const LD inv = 1 / det;
    const P3 s = origin - a;
    const LD u = inv * dot(s, h);
    if (u < -eps || u > 1 + eps) continue;
    const P3 q = cross(s, e1);
    const LD v = inv * dot(direction, q);
    if (v < -eps || u + v > 1 + eps) continue;
    const LD t = inv * dot(e2, q);
    if (t > eps && t < best) best = t;
  }
  return best;
}

struct Range {
  LD minimum, maximum;
};

Range cone_range(const RawMesh& mesh, std::size_t f, LD half_angle) {
  const P3 a = point(mesh, mesh.faces[f][0]), b = point(mesh, mesh.faces[f][1]), c = point(mesh, mesh.faces[f][2]);
  const P3 centre = (1.0L / 3.0L) * (a + b + c);
  P3 n = cross(b - a, c - a);
  n = (-1 / norm(n)) * n;  // inward
  P3 e1 = std::fabs(n.x) < 0.9L ? cross(n, P3{1, 0, 0}) : cross(n, P3{0, 1, 0});
  e1 = (1 / norm(e1)) * e1;
  const P3 e2 = cross(n, e1);
  const LD spread = std::tan(half_angle);
  Range r{INFINITY, -INFINITY};
  auto cast = [&](LD radius, LD phi) {
    P3 d = n + (spread * radius * std::cos(phi)) * e1 + (spread * radius * std::sin(phi)) * e2;
    d = (1 / norm(d)) * d;
    const LD hit = first_hit(mesh, f, centre, d);
    if (!std::isfinite(hit)) return;
    r.minimum = std::min(r.minimum, hit);
    r.maximum = std::max(r.maximum, hit);
  };
  const LD pi = std::acos(-1.0L);
  cast(0, 0);
  for (int ring = 1; ring <= kRings; ++ring) {
    for (int k = 0; k < kAzimuths; ++k) {
      cast(static_cast<LD>(ring) / kRings, 2 * pi * (k + (ring % 2 ? 0.5L : 0.0L)) / kAzimuths);
    }
  }
  return r;
}

// Raw values: positive, bounded by the bounding-box diagonal, and inside the declared band around the
// independently cast cone thickness.
Json thickness_check(const Request& request, Loaded& c) {
  const LD half_angle = finite_number(request.parameters, "cone_angle", 0.0, 3.0, true) / 2;
  const LD tolerance = finite_number(request.parameters, "thickness_tolerance", 0.0, 0.5, false);
  for (const double value : c.raw) {
    if (value == -1.0) {
      validation_failure("MISSING_SDF_VALUE",
                         "A facet has no SDF value although every cone ray of a closed outward mesh exits the solid");
    }
    if (!(value > 0) || value > c.diagonal * (1 + 1e-12L)) {
      validation_failure("SDF_VALUE_OUT_OF_BOUNDS", "A raw SDF value is not in (0, bounding-box diagonal]");
    }
  }
  c.checks["values_positive_and_bounded"] = true;
  LD worst_low = 0, worst_high = 0;
  for (std::size_t f = 0; f < c.mesh.faces.size(); ++f) {
    const auto range = cone_range(c.mesh, f, half_angle);
    if (!std::isfinite(range.minimum)) {
      validation_failure("THICKNESS_UNDEFINED", "No validator ray from a facet centroid meets the surface");
    }
    const LD value = c.raw[f];
    worst_low = std::max(worst_low, (range.minimum - value) / range.minimum);
    worst_high = std::max(worst_high, (value - range.maximum) / range.maximum);
    if (value < range.minimum * (1 - tolerance) || value > range.maximum * (1 + tolerance)) {
      validation_failure("SDF_THICKNESS_MISMATCH",
                         "Raw SDF value of facet " + std::to_string(f) +
                             " lies outside the declared band around the independently cast cone thickness");
    }
  }
  c.checks["thickness_within_declared_tolerance"] = true;
  return Json{{"maximum_relative_shortfall_below_cone_minimum", static_cast<double>(worst_low)},
              {"maximum_relative_excess_above_cone_maximum", static_cast<double>(worst_high)},
              {"thickness_tolerance", static_cast<double>(tolerance)},
              {"validator_rays_per_facet", 1 + kRings * kAzimuths},
              {"bounding_box_diagonal", static_cast<double>(c.diagonal)}};
}

constexpr const char* kTolerances =
    "raw SDF in [L_min (1 - thickness_tolerance), L_max (1 + thickness_tolerance)], L over 65 validator rays in the "
    "declared cone (long double); raw SDF in (0, bounding-box diagonal]; segmentation checks are exact";
constexpr const char* kIndependence =
    "own long double ray casting against the raw OFF facets; exact union-find for the segment partition; no CGAL header";

Json validate_sdf_values(const Request& request) {
  const std::string validator = "mesh.validate.sdf_values";
  require_parameter_names(request, {"cone_angle", "number_of_rays", "thickness_tolerance"});
  // A band wider than 0.5 would make the thickness check vacuous: reject it before reading the report.
  (void)finite_number(request.parameters, "thickness_tolerance", 0.0, 0.5, false);
  auto c = load(request, validator, "sdf_values");
  Json details = thickness_check(request, c);
  details["tolerances"] = kTolerances;
  details["independence"] = kIndependence;
  return concluded(request, validator, c.checks, details);
}

std::size_t find_root(std::vector<std::size_t>& parent, std::size_t x) {
  while (parent[x] != x) x = parent[x] = parent[parent[x]];
  return x;
}

std::vector<std::size_t> read_ids(const Json& value, std::size_t count, const std::string& context) {
  if (!value.is_array() || value.size() != count) {
    validation_failure("FACET_COVERAGE_MISMATCH", context + " must hold one id per facet");
  }
  std::vector<std::size_t> result;
  for (const auto& item : value) {
    if (!item.is_number_integer() || item.is_boolean() || item.get<long long>() < 0) {
      validation_failure("REPORT_VALUE_INVALID", context + " entries must be non-negative integers");
    }
    result.push_back(static_cast<std::size_t>(item.get<long long>()));
  }
  return result;
}

Json validate_segmentation(const Request& request) {
  const std::string validator = "mesh.validate.sdf_segmentation";
  require_parameter_names(request, {"cone_angle", "number_of_rays", "number_of_clusters", "smoothing_lambda",
                                    "thickness_tolerance"});
  const auto clusters_requested = query_ops::integer_parameter(request, "number_of_clusters", 1, 16);
  (void)finite_number(request.parameters, "thickness_tolerance", 0.0, 0.5, false);
  auto c = load(request, validator, "sdf_segmentation");
  Json details = thickness_check(request, c);
  const std::size_t faces = c.mesh.faces.size();

  // Post-processed values: bilateral smoothing keeps them inside the raw range; linear normalization maps the
  // smoothed minimum to exactly 0 and the maximum to exactly 1.
  const auto sdf = read_values(require_member(c.results, "sdf", "results"), faces, "sdf");
  const auto& range = require_member(c.results, "postprocessed_range", "results");
  if (!range.is_array() || range.size() != 2 || !range[0].is_number() || !range[1].is_number()) {
    validation_failure("REPORT_VALUE_INVALID", "postprocessed_range must be two numbers");
  }
  const double lo = range[0].get<double>(), hi = range[1].get<double>();
  const double raw_min = *std::min_element(c.raw.begin(), c.raw.end());
  const double raw_max = *std::max_element(c.raw.begin(), c.raw.end());
  const double slack = 1e-12 * raw_max;
  if (!(lo < hi) || lo < raw_min - slack || hi > raw_max + slack) {
    validation_failure("POSTPROCESSED_RANGE_INVALID", "The smoothed SDF range must be a proper sub-range of the raw range");
  }
  bool has_zero = false, has_one = false;
  for (const double s : sdf) {
    if (s < 0 || s > 1) validation_failure("NORMALIZED_SDF_OUT_OF_RANGE", "A normalized SDF value is outside [0, 1]");
    has_zero = has_zero || s == 0.0;
    has_one = has_one || s == 1.0;
  }
  if (!has_zero || !has_one) {
    validation_failure("NORMALIZED_SDF_OUT_OF_RANGE", "Linear normalization must reach exactly 0 and exactly 1");
  }
  c.checks["normalized_values_in_unit_interval"] = true;

  const auto cluster = read_ids(require_member(c.results, "cluster_ids", "results"), faces, "cluster_ids");
  const auto segment = read_ids(require_member(c.results, "segment_ids", "results"), faces, "segment_ids");
  c.checks["facets_covered"] = true;
  for (const auto id : cluster) {
    if (id >= clusters_requested) validation_failure("CLUSTER_ID_OUT_OF_RANGE", "A cluster id is >= number_of_clusters");
  }
  c.checks["cluster_ids_in_range"] = true;
  std::set<std::size_t> segment_set(segment.begin(), segment.end());
  const std::size_t segment_count = segment_set.size();
  if (*segment_set.rbegin() + 1 != segment_count) {
    validation_failure("SEGMENT_IDS_NOT_CONTIGUOUS", "Segment ids must be exactly 0 .. segment_count - 1");
  }
  c.checks["segment_ids_contiguous"] = true;

  // Segments must be exactly the edge-connected components of the cluster partition.
  std::map<std::pair<std::size_t, std::size_t>, std::vector<std::size_t>> edge_faces;
  for (std::size_t f = 0; f < faces; ++f) {
    for (std::size_t k = 0; k < 3; ++k) {
      const auto a = c.mesh.faces[f][k], b = c.mesh.faces[f][(k + 1) % 3];
      edge_faces[{std::min(a, b), std::max(a, b)}].push_back(f);
    }
  }
  std::vector<std::size_t> parent(faces);
  std::iota(parent.begin(), parent.end(), 0);
  for (const auto& [edge, incident] : edge_faces) {
    if (incident.size() != 2) validation_failure("MESH_NOT_CLOSED_OUTWARD", "An edge does not have two facets");
    const auto f = incident[0], g = incident[1];
    if ((cluster[f] == cluster[g]) != (segment[f] == segment[g])) {
      validation_failure("SEGMENTS_NOT_CLUSTER_COMPONENTS",
                         "Adjacent facets must share a segment exactly when they share a cluster");
    }
    if (cluster[f] == cluster[g]) parent[find_root(parent, f)] = find_root(parent, g);
  }
  std::map<std::size_t, std::size_t> root_of_segment;
  for (std::size_t f = 0; f < faces; ++f) {
    const auto root = find_root(parent, f);
    const auto [it, inserted] = root_of_segment.insert({segment[f], root});
    if (!inserted && it->second != root) {
      validation_failure("SEGMENTS_NOT_CLUSTER_COMPONENTS", "A segment is not edge-connected");
    }
  }
  c.checks["segments_are_connected_cluster_components"] = true;
  details["segment_count"] = segment_count;
  details["clusters_used"] = std::set<std::size_t>(cluster.begin(), cluster.end()).size();
  details["tolerances"] = kTolerances;
  details["independence"] = kIndependence;
  return concluded(request, validator, c.checks, details);
}

}  // namespace

std::vector<OperationDefinition> sdf_validators() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "mesh.validate.sdf_values", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      validate_sdf_values, {"Surface_mesh_segmentation"}, "long double ray casting (no CGAL header)",
      vinfo({"mesh_closed_outward", "parameters_match", "source_matches", "distance_unit_matches_mesh",
             "one_value_per_facet", "values_positive_and_bounded", "thickness_within_declared_tolerance"},
            {"candidate", "mesh"}, kIndependence)));
  result.push_back(query_definition(
      "mesh.validate.sdf_segmentation", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      validate_segmentation, {"Surface_mesh_segmentation"}, "long double ray casting and exact union-find (no CGAL header)",
      vinfo({"mesh_closed_outward", "parameters_match", "source_matches", "distance_unit_matches_mesh",
             "one_value_per_facet", "values_positive_and_bounded", "thickness_within_declared_tolerance",
             "normalized_values_in_unit_interval", "facets_covered", "cluster_ids_in_range", "segment_ids_contiguous",
             "segments_are_connected_cluster_components"},
            {"candidate", "mesh"}, kIndependence)));
  return result;
}

}  // namespace cgal_master::batch9
