// Independent validators for the query / mesh-processing family additions. This file
// includes no CGAL header and calls no CGAL algorithm: every accepted property is
// re-derived from the raw artifacts with GMP rational arithmetic (exact predicates and
// constructions) or, for the subdivision masks and mean value weights, from the textbook
// formulas in long double with an explicit tolerance.

#include "query_common.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <numeric>
#include <set>
#include <unordered_map>

namespace cgal_master::query_ops {
namespace {

// ---- exact 3D helpers ---------------------------------------------------------------

struct Vec {
  Q x, y, z;
};

Vec vec(const V3& v) { return {exact_of(v[0]), exact_of(v[1]), exact_of(v[2])}; }
Vec operator-(const Vec& a, const Vec& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
Vec operator+(const Vec& a, const Vec& b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
Vec operator*(const Q& s, const Vec& a) { return {s * a.x, s * a.y, s * a.z}; }
Q dot(const Vec& a, const Vec& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
Vec cross(const Vec& a, const Vec& b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
bool is_zero(const Vec& a) { return a.x == 0 && a.y == 0 && a.z == 0; }
bool operator==(const Vec& a, const Vec& b) { return a.x == b.x && a.y == b.y && a.z == b.z; }
bool operator<(const Vec& a, const Vec& b) {
  if (a.x != b.x) return a.x < b.x;
  if (a.y != b.y) return a.y < b.y;
  return a.z < b.z;
}

Vec reported_vec(const Json& value, const std::string& context) {
  if (!value.is_array() || value.size() != 3) validation_failure("REPORT_VALUE_INVALID", context + " must be a 3-vector");
  return {reported_rational(value[0], context), reported_rational(value[1], context),
          reported_rational(value[2], context)};
}

Json require_key(const Json& object, const char* key, const std::string& context) {
  if (!object.is_object() || !object.contains(key)) {
    validation_failure("REPORT_SCHEMA_MISMATCH", context + " lacks " + key);
  }
  return object.at(key);
}

// Common frame checks; returns the "results" value.
Json check_frame(const Json& report, const std::string& operation, const Json& parameters,
                 const std::vector<std::pair<const char*, const ArtifactInput*>>& sources, Json& checks) {
  if (report.value("operation", std::string()) != operation) {
    validation_failure("PARAMETER_MISMATCH", "Report is not a " + operation + " report");
  }
  if (require_key(report, "parameters", "report") != parameters) {
    validation_failure("PARAMETER_MISMATCH", "Report parameters differ from the validated request");
  }
  checks["parameters_match"] = true;
  const auto source = require_key(report, "source", "report");
  for (const auto& [key, input] : sources) {
    if (!source.is_object() || source.value(key, std::string()) != input->sha256) {
      validation_failure("SOURCE_MISMATCH", "Report does not describe the validated source artifacts");
    }
  }
  checks["source_matches"] = true;
  return require_key(report, "results", "report");
}

Json conclude(const Request& request, const std::string& validator, Json checks, Json details) {
  details["schema_version"] = 1;
  details["report_type"] = "ValidationReport";
  details["checks"] = std::move(checks);
  return finish_validation(request, validator, std::move(details));
}

std::size_t index_value(const Json& value, std::size_t bound, const std::string& context) {
  if (!value.is_number_integer() || value.is_boolean() || value.get<long long>() < 0 ||
      static_cast<std::size_t>(value.get<long long>()) >= bound) {
    validation_failure("INDEX_OUT_OF_RANGE", context + " is not a valid index");
  }
  return static_cast<std::size_t>(value.get<long long>());
}

void require_triangles(const RawMesh& mesh, const std::string& context) {
  if (mesh.faces.empty()) validation_failure("MESH_EMPTY", context + " has no faces");
  for (const auto& face : mesh.faces) {
    if (face.size() != 3) validation_failure("MESH_NOT_TRIANGULATED", context + " must be triangulated");
  }
}

// ---- 7.13.05 barycentric coordinates ---------------------------------------------------

struct Q2 {
  Q x, y;
};
Q cross2(const Q2& a, const Q2& b) { return a.x * b.y - a.y * b.x; }
Q2 sub2(const Q2& a, const Q2& b) { return {a.x - b.x, a.y - b.y}; }
Q dot2(const Q2& a, const Q2& b) { return a.x * b.x + a.y * b.y; }

bool segments_properly_or_touching(const Q2& a, const Q2& b, const Q2& c, const Q2& d) {
  auto sign = [](const Q& v) { return v > 0 ? 1 : (v < 0 ? -1 : 0); };
  auto on_segment = [&](const Q2& p, const Q2& q, const Q2& r) {  // r collinear with pq
    return std::min(p.x, q.x) <= r.x && r.x <= std::max(p.x, q.x) && std::min(p.y, q.y) <= r.y &&
           r.y <= std::max(p.y, q.y);
  };
  const int o1 = sign(cross2(sub2(b, a), sub2(c, a))), o2 = sign(cross2(sub2(b, a), sub2(d, a)));
  const int o3 = sign(cross2(sub2(d, c), sub2(a, c))), o4 = sign(cross2(sub2(d, c), sub2(b, c)));
  if (o1 != o2 && o3 != o4) return true;
  if (o1 == 0 && on_segment(a, b, c)) return true;
  if (o2 == 0 && on_segment(a, b, d)) return true;
  if (o3 == 0 && on_segment(c, d, a)) return true;
  if (o4 == 0 && on_segment(c, d, b)) return true;
  return false;
}

Json run_barycentric_validator(const Request& request) {
  const std::string validator = "shape.validate.barycentric";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {"method"});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto method = enum_parameter(request, "method", {"wachspress", "mean_value", "discrete_harmonic"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "barycentric_coordinates");
  const auto polygon_raw = read_polygon(request.inputs[1]);
  const auto queries_raw = read_points2(request.inputs[2]);
  Json checks;
  const auto results = check_frame(report, "shape.barycentric", {{"method", method}},
                                   {{"polygon_sha256", &request.inputs[1]}, {"queries_sha256", &request.inputs[2]}}, checks);
  const std::size_t n = polygon_raw.size();
  std::vector<Q2> poly;
  for (const auto& v : polygon_raw) poly.push_back({exact_of(v[0]), exact_of(v[1])});
  // Simple, counterclockwise, (strictly convex) polygon, exactly.
  Q twice_area = 0;
  for (std::size_t i = 0; i < n; ++i) twice_area += cross2(poly[i], poly[(i + 1) % n]);
  if (!(twice_area > 0)) validation_failure("POLYGON_NOT_COUNTERCLOCKWISE", "Polygon must be counterclockwise");
  for (std::size_t i = 0; i < n; ++i) {
    for (std::size_t j = i + 1; j < n; ++j) {
      const bool adjacent = j == i + 1 || (i == 0 && j + 1 == n);
      const auto a = poly[i], b = poly[(i + 1) % n], c = poly[j], d = poly[(j + 1) % n];
      if (adjacent) {
        // Adjacent edges may only share their common vertex.
        const Q2 &shared = (j == i + 1) ? b : a;
        const Q2 &p = (j == i + 1) ? a : b, &q = (j == i + 1) ? d : c;
        if (cross2(sub2(p, shared), sub2(q, shared)) == 0 && dot2(sub2(p, shared), sub2(q, shared)) > 0) {
          validation_failure("POLYGON_NOT_SIMPLE", "Adjacent polygon edges overlap");
        }
      } else if (segments_properly_or_touching(a, b, c, d)) {
        validation_failure("POLYGON_NOT_SIMPLE", "Polygon edges intersect");
      }
    }
  }
  bool convex = true;
  for (std::size_t i = 0; i < n; ++i) {
    const auto turn = cross2(sub2(poly[(i + 1) % n], poly[i]), sub2(poly[(i + 2) % n], poly[(i + 1) % n]));
    if (!(turn > 0)) convex = false;
  }
  if (method != "mean_value" && !convex) {
    validation_failure("POLYGON_NOT_STRICTLY_CONVEX", method + " coordinates need a strictly convex polygon");
  }
  checks["polygon_simple_counterclockwise"] = true;
  if (!results.is_array() || results.size() != queries_raw.size()) {
    validation_failure("RESULT_COUNT_MISMATCH", "Every query needs exactly one result");
  }
  double scale = 1;
  for (const auto& v : polygon_raw) scale = std::max({scale, std::fabs(v[0]), std::fabs(v[1])});
  const double tolerance = 1e-11;
  double worst_formula = 0, worst_sum = 0, worst_linear = 0;
  for (std::size_t k = 0; k < queries_raw.size(); ++k) {
    const Q2 q{exact_of(queries_raw[k][0]), exact_of(queries_raw[k][1])};
    // Strictly inside: not on the boundary and an odd crossing count.
    bool inside = false;
    for (std::size_t i = 0; i < n; ++i) {
      const Q2 &a = poly[i], &b = poly[(i + 1) % n];
      if (cross2(sub2(b, a), sub2(q, a)) == 0 && std::min(a.x, b.x) <= q.x && q.x <= std::max(a.x, b.x) &&
          std::min(a.y, b.y) <= q.y && q.y <= std::max(a.y, b.y)) {
        validation_failure("QUERY_NOT_STRICTLY_INSIDE", "A query lies on the polygon boundary");
      }
      if ((a.y > q.y) != (b.y > q.y)) {
        const Q xc = a.x + (q.y - a.y) * (b.x - a.x) / (b.y - a.y);
        if (q.x < xc) inside = !inside;
      }
    }
    if (!inside) validation_failure("QUERY_NOT_STRICTLY_INSIDE", "A query lies outside the polygon");
    const auto& entry = results[k];
    if (index_value(require_key(entry, "query_index", "result"), queries_raw.size(), "query_index") != k) {
      validation_failure("RESULT_ORDER_MISMATCH", "Results must follow the query order");
    }
    const auto coordinates_json = require_key(entry, "coordinates", "result");
    if (!coordinates_json.is_array() || coordinates_json.size() != n) {
      validation_failure("COORDINATE_COUNT_MISMATCH", "One coordinate per polygon vertex is required");
    }
    std::vector<double> reported(n);
    for (std::size_t i = 0; i < n; ++i) {
      if (!coordinates_json[i].is_number() || !std::isfinite(coordinates_json[i].get<double>())) {
        validation_failure("REPORT_VALUE_INVALID", "Coordinates must be finite numbers");
      }
      reported[i] = coordinates_json[i].get<double>();
    }
    // Independent recomputation of the weights.
    std::vector<long double> weight(n);
    std::vector<Q> exact_area(n);  // twice the signed area of (q, v_i, v_{i+1})
    for (std::size_t i = 0; i < n; ++i) exact_area[i] = cross2(sub2(poly[i], q), sub2(poly[(i + 1) % n], q));
    if (method == "wachspress") {
      std::vector<Q> w(n);
      Q total = 0;
      for (std::size_t i = 0; i < n; ++i) {
        const std::size_t p = (i + n - 1) % n, s = (i + 1) % n;
        const Q c = cross2(sub2(poly[i], poly[p]), sub2(poly[s], poly[i]));
        w[i] = c / (exact_area[p] * exact_area[i]);
        total += w[i];
      }
      for (std::size_t i = 0; i < n; ++i) weight[i] = Q(w[i] / total).get_d();
    } else if (method == "discrete_harmonic") {
      // cot of the angle at v_{i-1} in (q, v_{i-1}, v_i) plus at v_{i+1} in (q, v_i, v_{i+1}).
      auto cot_at = [&](const Q2& a, const Q2& b, const Q2& c) -> Q {  // angle at b between a and c
        const Q2 u = sub2(a, b), v = sub2(c, b);
        Q d = dot2(u, v), c2 = cross2(u, v);
        if (c2 < 0) c2 = -c2;
        return d / c2;
      };
      std::vector<Q> w(n);
      Q total = 0;
      for (std::size_t i = 0; i < n; ++i) {
        const std::size_t p = (i + n - 1) % n, s = (i + 1) % n;
        w[i] = cot_at(q, poly[p], poly[i]) + cot_at(q, poly[s], poly[i]);
        total += w[i];
      }
      for (std::size_t i = 0; i < n; ++i) weight[i] = Q(w[i] / total).get_d();
    } else {
      std::vector<long double> r(n), tan_half(n);
      for (std::size_t i = 0; i < n; ++i) {
        const long double dx = poly[i].x.get_d() - q.x.get_d(), dy = poly[i].y.get_d() - q.y.get_d();
        r[i] = std::sqrt(dx * dx + dy * dy);
      }
      for (std::size_t i = 0; i < n; ++i) {
        const std::size_t s = (i + 1) % n;
        const Q2 a = sub2(poly[i], q), b = sub2(poly[s], q);
        tan_half[i] = static_cast<long double>(cross2(a, b).get_d()) /
                      (r[i] * r[s] + static_cast<long double>(dot2(a, b).get_d()));
      }
      long double total = 0;
      for (std::size_t i = 0; i < n; ++i) {
        weight[i] = (tan_half[(i + n - 1) % n] + tan_half[i]) / r[i];
        total += weight[i];
      }
      for (std::size_t i = 0; i < n; ++i) weight[i] /= total;
    }
    double sum = 0, lx = 0, ly = 0;
    for (std::size_t i = 0; i < n; ++i) {
      worst_formula = std::max(worst_formula, std::fabs(reported[i] - static_cast<double>(weight[i])));
      sum += reported[i];
      lx += reported[i] * polygon_raw[i][0];
      ly += reported[i] * polygon_raw[i][1];
      if (reported[i] < -1e-14 && (method == "wachspress" || (method == "mean_value" && convex))) {
        validation_failure("NEGATIVE_COORDINATE", method + " coordinates are non-negative on a convex polygon");
      }
    }
    worst_sum = std::max(worst_sum, std::fabs(sum - 1));
    worst_linear = std::max({worst_linear, std::fabs(lx - queries_raw[k][0]), std::fabs(ly - queries_raw[k][1])});
  }
  if (!(worst_formula <= tolerance)) {
    validation_failure("COORDINATE_MISMATCH", "Reported coordinates differ from the independent formula");
  }
  if (!(worst_sum <= tolerance)) validation_failure("PARTITION_OF_UNITY_FAILED", "Coordinates do not sum to one");
  if (!(worst_linear <= tolerance * scale)) {
    validation_failure("LINEAR_PRECISION_FAILED", "Coordinates do not reproduce the query point");
  }
  checks["query_strictly_inside"] = true;
  checks["coordinates_match_formula"] = true;
  checks["partition_of_unity"] = true;
  checks["linear_precision"] = true;
  return conclude(request, validator, checks,
                  {{"method", method}, {"vertex_count", n}, {"query_count", queries_raw.size()},
                   {"polygon_convex", convex}, {"tolerance", tolerance},
                   {"maximum_formula_error", worst_formula}, {"maximum_sum_error", worst_sum},
                   {"maximum_linear_precision_error", worst_linear},
                   {"independence", "exact rational weights (Wachspress, discrete harmonic) and long double mean value formula; no CGAL header"}});
}

// ---- 7.2.04 ray / triangle intersection candidates --------------------------------------

bool inside_triangle(const Vec& n, const Vec& a, const Vec& b, const Vec& c, const Vec& p) {
  return dot(n, cross(b - a, p - a)) >= 0 && dot(n, cross(c - b, p - b)) >= 0 && dot(n, cross(a - c, p - c)) >= 0;
}

bool ray_hits_segment(const Vec& o, const Vec& d, const Vec& p, const Vec& q) {
  const Vec e = q - p, w = p - o, c = cross(d, e);
  if (is_zero(c)) {
    if (!is_zero(cross(w, d))) return false;
    return std::max(dot(p - o, d), dot(q - o, d)) >= 0;
  }
  const Q denominator = dot(c, c);
  const Q t = dot(cross(w, e), c) / denominator;
  const Q s = dot(cross(w, d), c) / denominator;
  return t >= 0 && s >= 0 && s <= 1;
}

bool ray_hits_triangle(const Vec& o, const Vec& d, const Vec& a, const Vec& b, const Vec& c) {
  const Vec n = cross(b - a, c - a);
  const Q denominator = dot(n, d);
  if (denominator != 0) {
    const Q t = dot(n, a - o) / denominator;
    if (t < 0) return false;
    return inside_triangle(n, a, b, c, o + t * d);
  }
  if (dot(n, a - o) != 0) return false;
  if (inside_triangle(n, a, b, c, o)) return true;
  return ray_hits_segment(o, d, a, b) || ray_hits_segment(o, d, b, c) || ray_hits_segment(o, d, c, a);
}

Json run_intersections_validator(const Request& request) {
  const std::string validator = "spatial.validate.aabb_intersections";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto report = read_report(request.inputs[0], "SpatialQueryReport", "query_kind", "aabb_ray_intersections");
  const auto mesh = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  require_triangles(mesh, "mesh");
  const auto rays = read_rays(request.inputs[2]);
  if (rays.size() * mesh.faces.size() > 20000000) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED", "Intersection validation exceeds its budget");
  }
  Json checks;
  const auto results = check_frame(report, "spatial.aabb.intersections", Json::object(),
                                   {{"mesh_sha256", &request.inputs[1]}, {"rays_sha256", &request.inputs[2]}}, checks);
  if (!results.is_array() || results.size() != rays.size()) {
    validation_failure("RESULT_COUNT_MISMATCH", "Every ray needs exactly one result");
  }
  std::vector<std::array<Vec, 3>> triangles;
  for (const auto& face : mesh.faces) {
    std::array<Vec, 3> t{vec(mesh.vertices[face[0]]), vec(mesh.vertices[face[1]]), vec(mesh.vertices[face[2]])};
    if (is_zero(cross(t[1] - t[0], t[2] - t[0]))) validation_failure("DEGENERATE_FACE", "Mesh has a zero-area face");
    triangles.push_back(std::move(t));
  }
  std::size_t intersecting = 0, listed = 0;
  for (std::size_t r = 0; r < rays.size(); ++r) {
    const Vec origin = vec(rays[r].origin), direction = vec(rays[r].direction);
    std::vector<std::size_t> expected;
    for (std::size_t f = 0; f < triangles.size(); ++f) {
      if (ray_hits_triangle(origin, direction, triangles[f][0], triangles[f][1], triangles[f][2])) expected.push_back(f);
    }
    const auto& entry = results[r];
    if (index_value(require_key(entry, "ray_index", "result"), rays.size(), "ray_index") != r) {
      validation_failure("RESULT_ORDER_MISMATCH", "Results must follow the ray order");
    }
    const auto flag = require_key(entry, "do_intersect", "result");
    if (!flag.is_boolean() || flag.get<bool>() != !expected.empty()) {
      validation_failure("DO_INTERSECT_MISMATCH", "do_intersect differs from the exact brute-force answer");
    }
    std::vector<std::size_t> reported;
    const auto faces_json = require_key(entry, "faces", "result");
    if (!faces_json.is_array()) validation_failure("REPORT_SCHEMA_MISMATCH", "faces must be an array");
    for (const auto& item : faces_json) reported.push_back(index_value(item, mesh.faces.size(), "face"));
    if (reported != expected) {
      validation_failure("INTERSECTED_PRIMITIVES_MISMATCH",
                         "all_intersected_primitives differs from the exact brute-force set (sorted, unique)");
    }
    const auto any = require_key(entry, "any_face", "result");
    if (expected.empty()) {
      if (!any.is_null()) validation_failure("ANY_PRIMITIVE_MISMATCH", "any_intersected_primitive must be empty");
    } else {
      const auto face = index_value(any, mesh.faces.size(), "any_face");
      if (!std::binary_search(expected.begin(), expected.end(), face)) {
        validation_failure("ANY_PRIMITIVE_MISMATCH", "any_intersected_primitive is not an intersected face");
      }
      ++intersecting;
    }
    listed += expected.size();
  }
  checks["every_ray_answered"] = true;
  checks["do_intersect_exact"] = true;
  checks["all_intersected_primitives_exact"] = true;
  checks["any_intersected_primitive_member"] = true;
  return conclude(request, validator, checks,
                  {{"ray_count", rays.size()}, {"intersecting_ray_count", intersecting},
                   {"intersected_face_total", listed}, {"face_count", mesh.faces.size()},
                   {"independence", "exact rational ray/triangle predicates over every face; no AABB tree"}});
}

// ---- 7.3.02 connected components ------------------------------------------------------------

struct Components {
  std::vector<std::size_t> label;  // dense component number per face (discovery order)
  std::vector<std::size_t> size;
};

Components compute_components(const RawMesh& mesh) {
  const std::size_t faces = mesh.faces.size();
  std::map<std::pair<std::size_t, std::size_t>, std::vector<std::size_t>> edges;
  for (std::size_t f = 0; f < faces; ++f) {
    const auto& face = mesh.faces[f];
    for (std::size_t i = 0; i < face.size(); ++i) {
      const auto a = face[i], b = face[(i + 1) % face.size()];
      edges[{std::min(a, b), std::max(a, b)}].push_back(f);
    }
  }
  std::vector<std::size_t> parent(faces);
  std::iota(parent.begin(), parent.end(), 0);
  auto find = [&](std::size_t x) {
    while (parent[x] != x) x = parent[x] = parent[parent[x]];
    return x;
  };
  for (const auto& [edge, owners] : edges) {
    if (owners.size() > 2) validation_failure("NONMANIFOLD_EDGE", "An edge is shared by more than two faces");
    if (owners.size() == 2) parent[find(owners[0])] = find(owners[1]);
  }
  Components result;
  std::map<std::size_t, std::size_t> dense;
  result.label.resize(faces);
  for (std::size_t f = 0; f < faces; ++f) {
    const auto root = find(f);
    auto found = dense.find(root);
    if (found == dense.end()) {
      found = dense.emplace(root, result.size.size()).first;
      result.size.push_back(0);
    }
    result.label[f] = found->second;
    ++result.size[found->second];
  }
  return result;
}

Json run_label_validator(const Request& request) {
  const std::string validator = "mesh.validate.components_label";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "connected_components");
  const auto mesh = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  require_triangles(mesh, "mesh");
  Json checks;
  const auto results = check_frame(report, "mesh.components.label", Json::object(), {{"mesh_sha256", &request.inputs[1]}}, checks);
  const auto expected = compute_components(mesh);
  const auto count = expected.size.size();
  if (require_key(results, "component_count", "results") != count) {
    validation_failure("COMPONENT_COUNT_MISMATCH", "Reported component count differs from the independent count");
  }
  const auto labels = require_key(results, "face_labels", "results");
  if (!labels.is_array() || labels.size() != mesh.faces.size()) {
    validation_failure("LABEL_COUNT_MISMATCH", "One label per face is required");
  }
  // The reported labelling must be the same partition (labels may be numbered differently).
  std::map<std::size_t, std::size_t> reported_to_expected, expected_to_reported;
  std::vector<std::size_t> reported_sizes(count, 0);
  for (std::size_t f = 0; f < mesh.faces.size(); ++f) {
    const auto label = index_value(labels[f], count, "face label");
    const auto mapped = reported_to_expected.emplace(label, expected.label[f]).first->second;
    const auto back = expected_to_reported.emplace(expected.label[f], label).first->second;
    if (mapped != expected.label[f] || back != label) {
      validation_failure("PARTITION_MISMATCH", "Reported labels do not partition the faces into the independent components");
    }
    ++reported_sizes[label];
  }
  const auto sizes = require_key(results, "component_sizes", "results");
  if (!sizes.is_array() || sizes.size() != count) validation_failure("SIZE_COUNT_MISMATCH", "One size per component is required");
  for (std::size_t c = 0; c < count; ++c) {
    if (index_value(sizes[c], mesh.faces.size() + 1, "component size") != reported_sizes[c]) {
      validation_failure("COMPONENT_SIZE_MISMATCH", "Reported component sizes differ from the labelling");
    }
  }
  checks["component_count_exact"] = true;
  checks["labels_partition_equal"] = true;
  checks["sizes_match"] = true;
  return conclude(request, validator, checks,
                  {{"face_count", mesh.faces.size()}, {"component_count", count},
                   {"independence", "union-find over faces sharing an undirected edge; no CGAL header"}});
}

using Corner = std::array<double, 3>;

std::vector<Corner> canonical_cycle(const RawMesh& mesh, const std::vector<std::size_t>& face) {
  std::vector<Corner> corners;
  for (const auto index : face) corners.push_back(mesh.vertices[index]);
  std::size_t start = 0;
  for (std::size_t i = 1; i < corners.size(); ++i) {
    if (corners[i] < corners[start]) start = i;
  }
  std::rotate(corners.begin(), corners.begin() + start, corners.end());
  return corners;
}

std::multiset<std::vector<Corner>> face_multiset(const RawMesh& mesh, const std::vector<std::size_t>& which) {
  std::multiset<std::vector<Corner>> result;
  for (const auto f : which) result.insert(canonical_cycle(mesh, mesh.faces[f]));
  return result;
}

void compare_selected(const Request& request, const RawMesh& source, const RawMesh& candidate,
                      const std::vector<std::size_t>& selected, Json& checks) {
  require_triangles(candidate, "candidate");
  std::vector<bool> referenced(candidate.vertices.size(), false);
  for (const auto& face : candidate.faces) {
    for (const auto index : face) referenced[index] = true;
  }
  if (std::find(referenced.begin(), referenced.end(), false) != referenced.end()) {
    validation_failure("UNREFERENCED_VERTEX", "Candidate has vertices that no face uses");
  }
  checks["candidate_has_no_unreferenced_vertices"] = true;
  std::vector<std::size_t> all(candidate.faces.size());
  std::iota(all.begin(), all.end(), 0);
  if (face_multiset(candidate, all) != face_multiset(source, selected)) {
    validation_failure("FACE_SET_MISMATCH", "Candidate faces differ from the independently selected source faces");
  }
  checks["faces_equal_selected_source_faces"] = true;
  (void)request;
}

Json run_component_validator(const Request& request) {
  const std::string validator = "mesh.validate.components_component";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"face"});
  const auto source = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  require_triangles(source, "source");
  const auto candidate = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  const auto seed = integer_parameter(request, "face", 0, source.faces.size() - 1);
  const auto components = compute_components(source);
  std::vector<std::size_t> selected;
  for (std::size_t f = 0; f < source.faces.size(); ++f) {
    if (components.label[f] == components.label[seed]) selected.push_back(f);
  }
  Json checks{{"parameters_match", true}, {"source_is_manifold", true}};
  compare_selected(request, source, candidate, selected, checks);
  return conclude(request, validator, checks,
                  {{"seed_face", seed}, {"component_face_count", selected.size()},
                   {"component_count", components.size.size()},
                   {"independence", "union-find over faces sharing an undirected edge; exact vertex coordinate comparison; no CGAL header"}});
}

Json run_keep_largest_validator(const Request& request) {
  const std::string validator = "mesh.validate.components_keep_largest";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"count"});
  const auto source = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  require_triangles(source, "source");
  const auto candidate = read_raw_mesh(request.inputs[0], {"TriangleSurfaceMesh"});
  const auto keep = integer_parameter(request, "count", 1, 1000);
  const auto components = compute_components(source);
  std::vector<std::size_t> order(components.size.size());
  std::iota(order.begin(), order.end(), 0);
  std::stable_sort(order.begin(), order.end(),
                   [&](std::size_t a, std::size_t b) { return components.size[a] > components.size[b]; });
  if (keep < order.size() && components.size[order[keep - 1]] == components.size[order[keep]]) {
    validation_failure("AMBIGUOUS_COMPONENT_TIE", "The kept component set is not unique");
  }
  std::set<std::size_t> kept(order.begin(), order.begin() + std::min(keep, order.size()));
  std::vector<std::size_t> selected;
  for (std::size_t f = 0; f < source.faces.size(); ++f) {
    if (kept.count(components.label[f])) selected.push_back(f);
  }
  Json checks{{"parameters_match", true}, {"source_is_manifold", true}, {"kept_set_unambiguous", true}};
  compare_selected(request, source, candidate, selected, checks);
  return conclude(request, validator, checks,
                  {{"components_requested", keep}, {"component_count", components.size.size()},
                   {"kept_face_count", selected.size()},
                   {"independence", "union-find component sizes and exact vertex coordinate comparison; no CGAL header"}});
}

// ---- 7.3.08 locate -------------------------------------------------------------------------

Vec closest_on_triangle(const Vec& p, const Vec& a, const Vec& b, const Vec& c) {
  const Vec ab = b - a, ac = c - a, ap = p - a;
  const Q d1 = dot(ab, ap), d2 = dot(ac, ap);
  if (d1 <= 0 && d2 <= 0) return a;
  const Vec bp = p - b;
  const Q d3 = dot(ab, bp), d4 = dot(ac, bp);
  if (d3 >= 0 && d4 <= d3) return b;
  const Q vc = d1 * d4 - d3 * d2;
  if (vc <= 0 && d1 >= 0 && d3 <= 0) return a + (d1 / (d1 - d3)) * ab;
  const Vec cp = p - c;
  const Q d5 = dot(ab, cp), d6 = dot(ac, cp);
  if (d6 >= 0 && d5 <= d6) return c;
  const Q vb = d5 * d2 - d1 * d6;
  if (vb <= 0 && d2 >= 0 && d6 <= 0) return a + (d2 / (d2 - d6)) * ac;
  const Q va = d3 * d6 - d5 * d4;
  if (va <= 0 && (d4 - d3) >= 0 && (d5 - d6) >= 0) {
    return b + ((d4 - d3) / ((d4 - d3) + (d5 - d6))) * (c - b);
  }
  const Q denominator = va + vb + vc;
  return a + (vb / denominator) * ab + (vc / denominator) * ac;
}

Json run_location_validator(const Request& request) {
  const std::string validator = "mesh.validate.location";
  require_inputs(request, 3, validator);
  require_parameter_names(request, {"strategy"});
  require_same_unit(request.inputs[1], request.inputs[2]);
  const auto strategy = enum_parameter(request, "strategy", {"locate", "locate_with_AABB_tree"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "mesh_location");
  const auto mesh = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  require_triangles(mesh, "mesh");
  const auto queries = read_points3(request.inputs[2]);
  if (queries.size() * mesh.faces.size() > 400000) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED", "Location validation exceeds its budget");
  }
  Json checks;
  const auto results = check_frame(report, "mesh.location.locate", {{"strategy", strategy}},
                                   {{"mesh_sha256", &request.inputs[1]}, {"queries_sha256", &request.inputs[2]}}, checks);
  if (!results.is_array() || results.size() != queries.size()) {
    validation_failure("RESULT_COUNT_MISMATCH", "Every query needs exactly one result");
  }
  std::vector<std::array<Vec, 3>> triangles;
  for (const auto& face : mesh.faces) {
    std::array<Vec, 3> t{vec(mesh.vertices[face[0]]), vec(mesh.vertices[face[1]]), vec(mesh.vertices[face[2]])};
    if (is_zero(cross(t[1] - t[0], t[2] - t[0]))) validation_failure("DEGENERATE_FACE", "Mesh has a zero-area face");
    triangles.push_back(std::move(t));
  }
  for (std::size_t k = 0; k < queries.size(); ++k) {
    const Vec q = vec(queries[k]);
    Q best;
    bool first = true;
    for (const auto& t : triangles) {
      const Vec d = q - closest_on_triangle(q, t[0], t[1], t[2]);
      const Q squared = dot(d, d);
      if (first || squared < best) {
        best = squared;
        first = false;
      }
    }
    const auto& entry = results[k];
    if (index_value(require_key(entry, "query_index", "result"), queries.size(), "query_index") != k) {
      validation_failure("RESULT_ORDER_MISMATCH", "Results must follow the query order");
    }
    const auto face = index_value(require_key(entry, "face", "result"), mesh.faces.size(), "face");
    const auto bary_json = require_key(entry, "barycentric", "result");
    if (!bary_json.is_array() || bary_json.size() != 3) validation_failure("REPORT_VALUE_INVALID", "barycentric needs three entries");
    Q b[3] = {reported_rational(bary_json[0], "barycentric"), reported_rational(bary_json[1], "barycentric"),
              reported_rational(bary_json[2], "barycentric")};
    if (b[0] + b[1] + b[2] != 1 || b[0] < 0 || b[1] < 0 || b[2] < 0) {
      validation_failure("BARYCENTRIC_INVALID", "Barycentric coordinates must be non-negative and sum to one");
    }
    const auto& t = triangles[face];
    const Vec located = b[0] * t[0] + b[1] * t[1] + b[2] * t[2];
    if (!(reported_vec(require_key(entry, "point", "result"), "point") == located)) {
      validation_failure("POINT_MISMATCH", "Reported point is not the barycentric combination of the face");
    }
    const Vec offset = q - located;
    const Q squared = dot(offset, offset);
    if (reported_rational(require_key(entry, "squared_distance", "result"), "squared_distance") != squared) {
      validation_failure("DISTANCE_MISMATCH", "Reported squared distance differs from the located point");
    }
    if (squared != best) {
      validation_failure("NOT_CLOSEST_LOCATION", "Located point is not a closest point of the mesh (exact brute force)");
    }
  }
  checks["every_query_answered"] = true;
  checks["barycentric_valid"] = true;
  checks["point_is_face_combination"] = true;
  checks["distance_matches_location"] = true;
  checks["location_is_closest_exact"] = true;
  return conclude(request, validator, checks,
                  {{"query_count", queries.size()}, {"face_count", mesh.faces.size()},
                   {"independence", "exact rational closest point on every triangle; no AABB tree"}});
}

// ---- 7.5.05 slicing ---------------------------------------------------------------------------

struct Seg {
  Vec a, b;
};

bool point_on_segment(const Vec& p, const Seg& s) {
  const Vec e = s.b - s.a;
  if (!is_zero(cross(p - s.a, e))) return false;
  const Q t = dot(p - s.a, e);
  return t >= 0 && t <= dot(e, e);
}

Json run_slice_validator(const Request& request) {
  const std::string validator = "mesh.validate.slice";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"normal", "offset"});
  const auto report = read_report(request.inputs[0], "GeometryQueryReport", "report_kind", "mesh_slice");
  const auto mesh = read_raw_mesh(request.inputs[1], {"TriangleSurfaceMesh"});
  require_triangles(mesh, "mesh");
  const auto normal_d = vector_parameter(request, "normal");
  const double offset_d = signed_length_parameter(request, "offset", request.inputs[1].unit);
  const Vec normal = vec(normal_d);
  const Q offset = exact_of(offset_d);
  Json expected_parameters{{"normal", Json::array({normal_d[0], normal_d[1], normal_d[2]})},
                           {"offset", {{"value", offset_d}, {"unit", request.inputs[1].unit}}}};
  Json checks;
  const auto results = check_frame(report, "mesh.slice.compute", expected_parameters,
                                   {{"mesh_sha256", &request.inputs[1]}}, checks);
  // Exact triangle/plane sections.
  std::vector<Seg> sections;
  for (const auto& face : mesh.faces) {
    const Vec v[3] = {vec(mesh.vertices[face[0]]), vec(mesh.vertices[face[1]]), vec(mesh.vertices[face[2]])};
    Q s[3];
    int zero = 0, positive = 0, negative = 0;
    for (int i = 0; i < 3; ++i) {
      s[i] = dot(normal, v[i]) - offset;
      (s[i] == 0 ? zero : (s[i] > 0 ? positive : negative))++;
    }
    if (zero == 3) validation_failure("COPLANAR_FACE", "The slicing plane contains a mesh face");
    if (positive == 0 || negative == 0) {
      if (zero < 2) continue;  // no section, or a single touching vertex
    }
    std::vector<Vec> points;
    for (int i = 0; i < 3; ++i) {
      if (s[i] == 0) points.push_back(v[i]);
      const int j = (i + 1) % 3;
      if ((s[i] > 0 && s[j] < 0) || (s[i] < 0 && s[j] > 0)) {
        points.push_back(v[i] + (s[i] / (s[i] - s[j])) * (v[j] - v[i]));
      }
    }
    std::sort(points.begin(), points.end());
    points.erase(std::unique(points.begin(), points.end(),
                             [](const Vec& x, const Vec& y) { return x == y; }),
                 points.end());
    if (points.size() == 2) sections.push_back({points[0], points[1]});
  }
  const auto polylines = require_key(results, "polylines", "results");
  if (!polylines.is_array()) validation_failure("REPORT_SCHEMA_MISMATCH", "polylines must be an array");
  std::vector<Seg> reported;
  std::size_t closed_count = 0;
  for (const auto& polyline : polylines) {
    const auto points_json = require_key(polyline, "points", "polyline");
    if (!points_json.is_array() || points_json.size() < 2) {
      validation_failure("POLYLINE_TOO_SHORT", "A polyline needs at least two points");
    }
    std::vector<Vec> points;
    for (const auto& item : points_json) {
      points.push_back(reported_vec(item, "polyline point"));
      if (dot(normal, points.back()) != offset) validation_failure("POINT_OFF_PLANE", "A polyline point is not on the plane");
    }
    const bool closed = points.size() > 2 && points.front() == points.back();
    const auto flag = require_key(polyline, "closed", "polyline");
    if (!flag.is_boolean() || flag.get<bool>() != closed) {
      validation_failure("CLOSED_FLAG_MISMATCH", "The closed flag differs from first == last");
    }
    closed_count += closed ? 1 : 0;
    for (std::size_t i = 0; i + 1 < points.size(); ++i) {
      if (points[i] == points[i + 1]) validation_failure("ZERO_LENGTH_SEGMENT", "A polyline repeats a point");
      reported.push_back({points[i], points[i + 1]});
    }
  }
  if (sections.size() * std::max<std::size_t>(reported.size(), 1) > 4000000) {
    throw WorkerError("RESOURCE_LIMIT", "VALIDATION_BUDGET_EXCEEDED", "Slice validation exceeds its budget");
  }
  // Soundness: every reported segment lies inside one triangle/plane section.
  for (const auto& segment : reported) {
    bool inside = false;
    for (const auto& section : sections) {
      if (point_on_segment(segment.a, section) && point_on_segment(segment.b, section)) {
        inside = true;
        break;
      }
    }
    if (!inside) validation_failure("SEGMENT_NOT_ON_MESH", "A reported segment is not part of the mesh/plane intersection");
  }
  checks["points_on_plane"] = true;
  checks["segments_on_mesh_section"] = true;
  // Completeness: the reported segments cover every section.
  for (const auto& section : sections) {
    const Vec e = section.b - section.a;
    const Q length2 = dot(e, e);
    std::vector<std::pair<Q, Q>> intervals;
    for (const auto& segment : reported) {
      if (point_on_segment(segment.a, section) && point_on_segment(segment.b, section)) {
        Q t0 = dot(segment.a - section.a, e) / length2, t1 = dot(segment.b - section.a, e) / length2;
        if (t1 < t0) std::swap(t0, t1);
        intervals.emplace_back(t0, t1);
      }
    }
    std::sort(intervals.begin(), intervals.end());
    Q reach = 0;
    bool started = false;
    for (const auto& interval : intervals) {
      if (!started) {
        if (interval.first > 0) break;
        started = true;
        reach = interval.second;
      } else if (interval.first <= reach) {
        reach = std::max(reach, interval.second);
      } else {
        break;
      }
    }
    if (!started || reach < 1) {
      validation_failure("SECTION_NOT_COVERED", "A triangle/plane section is not covered by the reported polylines");
    }
  }
  checks["sections_fully_covered"] = true;
  // A closed 2-manifold (no boundary edge) is cut along closed curves.
  std::map<std::pair<std::size_t, std::size_t>, int> edge_count;
  for (const auto& face : mesh.faces) {
    for (std::size_t i = 0; i < 3; ++i) {
      const auto a = face[i], b = face[(i + 1) % 3];
      ++edge_count[{std::min(a, b), std::max(a, b)}];
    }
  }
  bool closed_mesh = true;
  for (const auto& [edge, count] : edge_count) closed_mesh = closed_mesh && count == 2;
  if (closed_mesh && closed_count != polylines.size()) {
    validation_failure("OPEN_POLYLINE_ON_CLOSED_MESH", "A closed mesh must be sliced into closed polylines only");
  }
  checks["closed_mesh_gives_closed_polylines"] = true;
  return conclude(request, validator, checks,
                  {{"face_count", mesh.faces.size()}, {"section_count", sections.size()},
                   {"polyline_count", polylines.size()}, {"closed_polyline_count", closed_count},
                   {"mesh_closed", closed_mesh},
                   {"independence", "exact rational triangle/plane sections and interval coverage; no CGAL header"}});
}

// ---- 7.8.06 subdivision ---------------------------------------------------------------------------

using LD = long double;
using P3 = std::array<LD, 3>;
P3 operator+(const P3& a, const P3& b) { return {a[0] + b[0], a[1] + b[1], a[2] + b[2]}; }
P3 operator*(LD s, const P3& a) { return {s * a[0], s * a[1], s * a[2]}; }

struct LMesh {
  std::vector<P3> v;
  std::vector<std::vector<std::size_t>> f;
};

struct EdgeInfo {
  std::vector<std::size_t> faces;
};

using EdgeKey = std::pair<std::size_t, std::size_t>;
EdgeKey key_of(std::size_t a, std::size_t b) { return {std::min(a, b), std::max(a, b)}; }

std::map<EdgeKey, EdgeInfo> edge_table(const LMesh& m) {
  std::map<EdgeKey, EdgeInfo> edges;
  for (std::size_t f = 0; f < m.f.size(); ++f) {
    const auto& face = m.f[f];
    for (std::size_t i = 0; i < face.size(); ++i) edges[key_of(face[i], face[(i + 1) % face.size()])].faces.push_back(f);
  }
  for (const auto& [edge, info] : edges) {
    if (info.faces.size() > 2) validation_failure("NONMANIFOLD_EDGE", "Subdivision needs a manifold mesh");
  }
  return edges;
}

LMesh loop_step(const LMesh& m) {
  const auto edges = edge_table(m);
  const std::size_t V = m.v.size();
  std::map<EdgeKey, std::size_t> edge_vertex;
  LMesh out;
  out.v.resize(V);
  std::vector<std::vector<std::size_t>> neighbours(V);
  std::vector<std::vector<std::size_t>> boundary_neighbours(V);
  for (const auto& [edge, info] : edges) {
    neighbours[edge.first].push_back(edge.second);
    neighbours[edge.second].push_back(edge.first);
    if (info.faces.size() == 1) {
      boundary_neighbours[edge.first].push_back(edge.second);
      boundary_neighbours[edge.second].push_back(edge.first);
    }
  }
  const LD pi = std::acos(static_cast<LD>(-1));
  for (std::size_t i = 0; i < V; ++i) {
    if (neighbours[i].empty()) validation_failure("ISOLATED_VERTEX", "Mesh has an unreferenced vertex");
    if (!boundary_neighbours[i].empty()) {
      if (boundary_neighbours[i].size() != 2) validation_failure("NONMANIFOLD_VERTEX", "Boundary vertex is non-manifold");
      out.v[i] = static_cast<LD>(0.75) * m.v[i] + static_cast<LD>(0.125) * (m.v[boundary_neighbours[i][0]] + m.v[boundary_neighbours[i][1]]);
    } else {
      const LD n = static_cast<LD>(neighbours[i].size());
      const LD inner = static_cast<LD>(0.375) + std::cos(2 * pi / n) / 4;
      const LD beta = (static_cast<LD>(0.625) - inner * inner) / n;
      P3 sum{0, 0, 0};
      for (const auto j : neighbours[i]) sum = sum + m.v[j];
      out.v[i] = (1 - n * beta) * m.v[i] + beta * sum;
    }
  }
  for (const auto& [edge, info] : edges) {
    edge_vertex[edge] = out.v.size();
    if (info.faces.size() == 1) {
      out.v.push_back(static_cast<LD>(0.5) * (m.v[edge.first] + m.v[edge.second]));
    } else {
      P3 far{0, 0, 0};
      for (const auto f : info.faces) {
        for (const auto c : m.f[f]) {
          if (c != edge.first && c != edge.second) far = far + m.v[c];
        }
      }
      out.v.push_back(static_cast<LD>(0.375) * (m.v[edge.first] + m.v[edge.second]) + static_cast<LD>(0.125) * far);
    }
  }
  for (const auto& face : m.f) {
    const std::size_t a = face[0], b = face[1], c = face[2];
    const std::size_t ab = edge_vertex[key_of(a, b)], bc = edge_vertex[key_of(b, c)], ca = edge_vertex[key_of(c, a)];
    out.f.push_back({a, ab, ca});
    out.f.push_back({b, bc, ab});
    out.f.push_back({c, ca, bc});
    out.f.push_back({ab, bc, ca});
  }
  return out;
}

LMesh catmull_clark_step(const LMesh& m) {
  const auto edges = edge_table(m);
  const std::size_t V = m.v.size(), F = m.f.size();
  LMesh out;
  out.v.resize(V);
  std::vector<P3> face_point(F);
  for (std::size_t f = 0; f < F; ++f) {
    P3 sum{0, 0, 0};
    for (const auto c : m.f[f]) sum = sum + m.v[c];
    face_point[f] = (static_cast<LD>(1) / static_cast<LD>(m.f[f].size())) * sum;
  }
  std::vector<std::vector<EdgeKey>> incident(V);
  for (const auto& [edge, info] : edges) {
    incident[edge.first].push_back(edge);
    incident[edge.second].push_back(edge);
  }
  std::vector<std::vector<std::size_t>> incident_faces(V);
  for (std::size_t f = 0; f < F; ++f) {
    for (const auto c : m.f[f]) incident_faces[c].push_back(f);
  }
  for (std::size_t i = 0; i < V; ++i) {
    if (incident[i].empty()) validation_failure("ISOLATED_VERTEX", "Mesh has an unreferenced vertex");
    std::vector<EdgeKey> boundary;
    for (const auto& e : incident[i]) {
      if (edges.at(e).faces.size() == 1) boundary.push_back(e);
    }
    if (!boundary.empty()) {
      if (boundary.size() != 2) validation_failure("NONMANIFOLD_VERTEX", "Boundary vertex is non-manifold");
      const auto other = [&](const EdgeKey& e) { return e.first == i ? e.second : e.first; };
      out.v[i] = static_cast<LD>(0.125) * (m.v[other(boundary[0])] + m.v[other(boundary[1])]) +
                 static_cast<LD>(0.75) * m.v[i];
    } else {
      const LD n = static_cast<LD>(incident[i].size());
      P3 favg{0, 0, 0}, ravg{0, 0, 0};
      for (const auto f : incident_faces[i]) favg = favg + face_point[f];
      favg = (1 / static_cast<LD>(incident_faces[i].size())) * favg;
      for (const auto& e : incident[i]) ravg = ravg + static_cast<LD>(0.5) * (m.v[e.first] + m.v[e.second]);
      ravg = (1 / n) * ravg;
      out.v[i] = (1 / n) * (favg + 2 * ravg + (n - 3) * m.v[i]);
    }
  }
  std::map<EdgeKey, std::size_t> edge_vertex;
  for (const auto& [edge, info] : edges) {
    edge_vertex[edge] = out.v.size();
    if (info.faces.size() == 1) {
      out.v.push_back(static_cast<LD>(0.5) * (m.v[edge.first] + m.v[edge.second]));
    } else {
      out.v.push_back(static_cast<LD>(0.25) * (m.v[edge.first] + m.v[edge.second] + face_point[info.faces[0]] +
                                               face_point[info.faces[1]]));
    }
  }
  std::vector<std::size_t> face_vertex(F);
  for (std::size_t f = 0; f < F; ++f) {
    face_vertex[f] = out.v.size();
    out.v.push_back(face_point[f]);
  }
  for (std::size_t f = 0; f < F; ++f) {
    const auto& face = m.f[f];
    const std::size_t k = face.size();
    for (std::size_t i = 0; i < k; ++i) {
      out.f.push_back({face[i], edge_vertex[key_of(face[i], face[(i + 1) % k])], face_vertex[f],
                       edge_vertex[key_of(face[(i + k - 1) % k], face[i])]});
    }
  }
  return out;
}

Json run_subdivision_validator(const Request& request, bool catmull_clark) {
  const std::string validator = catmull_clark ? "mesh.validate.catmull_clark" : "mesh.validate.loop";
  require_inputs(request, 2, validator);
  require_parameter_names(request, {"steps"});
  const auto steps = integer_parameter(request, "steps", 1, kMaximumSubdivisionSteps);
  const auto source = read_raw_mesh(request.inputs[1], catmull_clark
                                                           ? std::initializer_list<const char*>{"TriangleSurfaceMesh", "PolygonSoup3"}
                                                           : std::initializer_list<const char*>{"TriangleSurfaceMesh"});
  const auto candidate = read_raw_mesh(request.inputs[0], catmull_clark
                                                              ? std::initializer_list<const char*>{"PolygonSoup3"}
                                                              : std::initializer_list<const char*>{"TriangleSurfaceMesh"});
  if (source.faces.size() > kMaximumSubdivisionInputFaces) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", "Source exceeds the subdivision face limit");
  }
  if (!catmull_clark) require_triangles(source, "source");
  LMesh mesh;
  for (const auto& v : source.vertices) mesh.v.push_back({v[0], v[1], v[2]});
  mesh.f = source.faces;
  for (std::size_t s = 0; s < steps; ++s) mesh = catmull_clark ? catmull_clark_step(mesh) : loop_step(mesh);
  Json checks{{"parameters_match", true}};
  if (candidate.faces.size() != mesh.f.size() || candidate.vertices.size() != mesh.v.size()) {
    validation_failure("COUNT_MISMATCH", "Candidate vertex/face counts differ from the independent subdivision");
  }
  checks["counts_match"] = true;
  LD low[3] = {1e300L, 1e300L, 1e300L}, high[3] = {-1e300L, -1e300L, -1e300L};
  for (const auto& v : mesh.v) {
    for (int i = 0; i < 3; ++i) {
      low[i] = std::min(low[i], v[i]);
      high[i] = std::max(high[i], v[i]);
    }
  }
  const LD diagonal = std::sqrt((high[0] - low[0]) * (high[0] - low[0]) + (high[1] - low[1]) * (high[1] - low[1]) +
                                (high[2] - low[2]) * (high[2] - low[2]));
  const LD tolerance = 1e-9L * std::max<LD>(diagonal, 1e-300L);
  const LD cell = std::max<LD>(1e-6L * diagonal, 1e-12L);
  auto centroid_key = [&](const std::vector<P3>& corners) {
    P3 c{0, 0, 0};
    for (const auto& p : corners) c = c + p;
    c = (1 / static_cast<LD>(corners.size())) * c;
    return std::array<long long, 3>{static_cast<long long>(std::floor(c[0] / cell)), static_cast<long long>(std::floor(c[1] / cell)),
                                    static_cast<long long>(std::floor(c[2] / cell))};
  };
  struct KeyHash {
    std::size_t operator()(const std::array<long long, 3>& k) const {
      return static_cast<std::size_t>(k[0] * 73856093LL ^ k[1] * 19349663LL ^ k[2] * 83492791LL);
    }
  };
  std::unordered_map<std::array<long long, 3>, std::vector<std::size_t>, KeyHash> buckets;
  std::vector<std::vector<P3>> candidate_faces(candidate.faces.size());
  for (std::size_t f = 0; f < candidate.faces.size(); ++f) {
    for (const auto c : candidate.faces[f]) {
      candidate_faces[f].push_back({candidate.vertices[c][0], candidate.vertices[c][1], candidate.vertices[c][2]});
    }
    buckets[centroid_key(candidate_faces[f])].push_back(f);
  }
  std::vector<bool> used(candidate.faces.size(), false);
  LD worst = 0;
  for (const auto& face : mesh.f) {
    std::vector<P3> corners;
    for (const auto c : face) corners.push_back(mesh.v[c]);
    const auto key = centroid_key(corners);
    bool matched = false;
    for (long long dx = -1; dx <= 1 && !matched; ++dx) {
      for (long long dy = -1; dy <= 1 && !matched; ++dy) {
        for (long long dz = -1; dz <= 1 && !matched; ++dz) {
          const auto found = buckets.find({key[0] + dx, key[1] + dy, key[2] + dz});
          if (found == buckets.end()) continue;
          for (const auto index : found->second) {
            if (used[index] || candidate_faces[index].size() != corners.size()) continue;
            const auto& other = candidate_faces[index];
            for (std::size_t shift = 0; shift < corners.size() && !matched; ++shift) {
              LD deviation = 0;
              for (std::size_t i = 0; i < corners.size(); ++i) {
                const auto& p = corners[i];
                const auto& q = other[(i + shift) % corners.size()];
                deviation = std::max({deviation, std::fabs(p[0] - q[0]), std::fabs(p[1] - q[1]), std::fabs(p[2] - q[2])});
              }
              if (deviation <= tolerance) {
                matched = true;
                used[index] = true;
                worst = std::max(worst, deviation);
              }
            }
            if (matched) break;
          }
        }
      }
    }
    if (!matched) {
      validation_failure("FACE_NOT_MATCHED", "A face of the independent subdivision has no matching candidate face (geometry or orientation)");
    }
  }
  checks["faces_match_independent_subdivision"] = true;
  checks["orientation_preserved"] = true;
  return conclude(request, validator, checks,
                  {{"steps", steps}, {"source_face_count", source.faces.size()},
                   {"candidate_face_count", candidate.faces.size()},
                   {"candidate_vertex_count", candidate.vertices.size()},
                   {"maximum_vertex_deviation", static_cast<double>(worst)},
                   {"tolerance", static_cast<double>(tolerance)},
                   {"independence", "textbook subdivision masks re-implemented from the raw OFF data; no CGAL header"}});
}

Json run_catmull_clark_validator(const Request& request) { return run_subdivision_validator(request, true); }
Json run_loop_validator(const Request& request) { return run_subdivision_validator(request, false); }

Json vinfo(const std::vector<std::string>& checks, std::vector<std::string> slots, const std::string& independence) {
  return Json{{"checks", checks}, {"input_slots", slots}, {"output_slot", "validation"}, {"independence", independence}};
}

}  // namespace

std::vector<OperationDefinition> validator_operations() {
  std::vector<OperationDefinition> result;
  const char* gmp = "exact:GMP";
  result.push_back(query_definition(
      "shape.validate.barycentric", {"GeometryQueryReport", "Polygon2", "PointSet2"}, "ValidationReport", "validator",
      run_barycentric_validator, {"Barycentric_coordinates_2"}, "exact:GMP",
      vinfo({"parameters_match", "source_matches", "polygon_simple_counterclockwise", "query_strictly_inside",
             "coordinates_match_formula", "partition_of_unity", "linear_precision"},
            {"candidate", "polygon", "queries"}, "exact rational weights and tolerance-checked mean value formula; no CGAL header")));
  result.push_back(query_definition(
      "spatial.validate.aabb_intersections", {"SpatialQueryReport", "TriangleSurfaceMesh", "RayBatch3"}, "ValidationReport",
      "validator", run_intersections_validator, {"AABB_tree"}, gmp,
      vinfo({"parameters_match", "source_matches", "every_ray_answered", "do_intersect_exact",
             "all_intersected_primitives_exact", "any_intersected_primitive_member"},
            {"candidate", "mesh", "rays"}, "exact rational ray/triangle predicates; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.components_label", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      run_label_validator, {"Polygon_mesh_processing"}, gmp,
      vinfo({"parameters_match", "source_matches", "component_count_exact", "labels_partition_equal", "sizes_match"},
            {"candidate", "mesh"}, "union-find over shared edges; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.components_component", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      run_component_validator, {"Polygon_mesh_processing"}, gmp,
      vinfo({"parameters_match", "source_is_manifold", "candidate_has_no_unreferenced_vertices",
             "faces_equal_selected_source_faces"},
            {"candidate", "source"}, "union-find over shared edges; exact coordinate comparison; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.components_keep_largest", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      run_keep_largest_validator, {"Polygon_mesh_processing"}, gmp,
      vinfo({"parameters_match", "source_is_manifold", "kept_set_unambiguous", "candidate_has_no_unreferenced_vertices",
             "faces_equal_selected_source_faces"},
            {"candidate", "source"}, "union-find component sizes; exact coordinate comparison; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.location", {"GeometryQueryReport", "TriangleSurfaceMesh", "PointSet3"}, "ValidationReport", "validator",
      run_location_validator, {"Polygon_mesh_processing"}, gmp,
      vinfo({"parameters_match", "source_matches", "every_query_answered", "barycentric_valid", "point_is_face_combination",
             "distance_matches_location", "location_is_closest_exact"},
            {"candidate", "mesh", "queries"}, "exact rational closest point on every triangle; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.slice", {"GeometryQueryReport", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      run_slice_validator, {"PMP_Boolean_operations"}, gmp,
      vinfo({"parameters_match", "source_matches", "points_on_plane", "segments_on_mesh_section", "sections_fully_covered",
             "closed_mesh_gives_closed_polylines"},
            {"candidate", "mesh"}, "exact triangle/plane sections and interval coverage; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.catmull_clark", {"PolygonSoup3", "TriangleSurfaceMesh", "PolygonSoup3"}, "ValidationReport", "validator",
      run_catmull_clark_validator, {"Subdivision_method_3"}, "float:long_double",
      vinfo({"parameters_match", "counts_match", "faces_match_independent_subdivision", "orientation_preserved"},
            {"candidate", "source"}, "Catmull-Clark masks re-implemented from raw OFF data; no CGAL header")));
  result.push_back(query_definition(
      "mesh.validate.loop", {"TriangleSurfaceMesh", "TriangleSurfaceMesh"}, "ValidationReport", "validator",
      run_loop_validator, {"Subdivision_method_3"}, "float:long_double",
      vinfo({"parameters_match", "counts_match", "faces_match_independent_subdivision", "orientation_preserved"},
            {"candidate", "source"}, "Loop masks re-implemented from raw OFF data; no CGAL header")));
  return result;
}

}  // namespace cgal_master::query_ops
