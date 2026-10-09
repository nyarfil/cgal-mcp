#include "b2_geometry.h"

#include <algorithm>

namespace cgal_master::batch2 {

using query_ops::exact_of;
using query_ops::q_text;
using query_ops::validation_failure;

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
bool operator!=(const Vec& a, const Vec& b) { return !(a == b); }
bool operator<(const Vec& a, const Vec& b) {
  if (a.x != b.x) return a.x < b.x;
  if (a.y != b.y) return a.y < b.y;
  return a.z < b.z;
}
std::string vec_text(const Vec& a) { return "(" + q_text(a.x) + "," + q_text(a.y) + "," + q_text(a.z) + ")"; }

Tri make_tri(const RawMesh& mesh, const std::vector<std::size_t>& face) {
  Tri t;
  for (int i = 0; i < 3; ++i) {
    t.raw[i] = mesh.vertices.at(face.at(i));
    t.v[i] = vec(t.raw[i]);
  }
  return t;
}

Vec tri_normal(const Tri& t) { return cross(t.v[1] - t.v[0], t.v[2] - t.v[0]); }
bool tri_degenerate(const Tri& t) { return is_zero(tri_normal(t)); }
Q tri_weight(const Tri& t, const Vec& n) { return dot(n, tri_normal(t)); }

bool boxes_overlap(const Tri& a, const Tri& b) {
  for (int axis = 0; axis < 3; ++axis) {
    double alo = a.raw[0][axis], ahi = alo, blo = b.raw[0][axis], bhi = blo;
    for (int i = 1; i < 3; ++i) {
      alo = std::min(alo, a.raw[i][axis]);
      ahi = std::max(ahi, a.raw[i][axis]);
      blo = std::min(blo, b.raw[i][axis]);
      bhi = std::max(bhi, b.raw[i][axis]);
    }
    if (ahi < blo || bhi < alo) return false;
  }
  return true;
}

bool point_in_triangle(const Tri& t, const Vec& p) {
  const Vec n = tri_normal(t);
  if (dot(n, p - t.v[0]) != 0) return false;
  for (int i = 0; i < 3; ++i) {
    const Vec& a = t.v[i];
    const Vec& b = t.v[(i + 1) % 3];
    if (dot(n, cross(b - a, p - a)) < 0) return false;
  }
  return true;
}

bool point_on_segment(const Vec& p, const Vec& a, const Vec& b) {
  const Vec e = b - a;
  if (!is_zero(cross(p - a, e))) return false;
  if (is_zero(e)) return p == a;
  const Q s = dot(p - a, e);
  return s >= 0 && s <= dot(e, e);
}

bool segment_triangle(const Vec& s0, const Vec& s1, const Tri& t, Q& t0, Q& t1) {
  const Vec n = tri_normal(t);
  const Vec d = s1 - s0;
  const Q denominator = dot(n, d);
  const Q f0 = dot(n, s0 - t.v[0]);
  if (denominator != 0) {
    const Q s = -f0 / denominator;
    if (s < 0 || s > 1) return false;
    const Vec p = s0 + s * d;
    for (int i = 0; i < 3; ++i) {
      const Vec& a = t.v[i];
      const Vec& b = t.v[(i + 1) % 3];
      if (dot(n, cross(b - a, p - a)) < 0) return false;
    }
    t0 = t1 = s;
    return true;
  }
  if (f0 != 0) return false;
  Q lo = 0, hi = 1;
  for (int i = 0; i < 3; ++i) {
    const Vec& a = t.v[i];
    const Vec& b = t.v[(i + 1) % 3];
    const Q g0 = dot(n, cross(b - a, s0 - a));
    const Q g1 = dot(n, cross(b - a, d));
    if (g1 == 0) {
      if (g0 < 0) return false;
      continue;
    }
    const Q bound = -g0 / g1;
    if (g1 > 0) lo = std::max(lo, bound);
    else hi = std::min(hi, bound);
  }
  if (lo > hi) return false;
  t0 = lo;
  t1 = hi;
  return true;
}

std::vector<Vec> intersection_points(const Tri& a, const Tri& b) {
  std::vector<Vec> points;
  auto collect = [&](const Tri& edges_of, const Tri& target) {
    for (int i = 0; i < 3; ++i) {
      const Vec& s0 = edges_of.v[i];
      const Vec& s1 = edges_of.v[(i + 1) % 3];
      Q t0, t1;
      if (segment_triangle(s0, s1, target, t0, t1)) {
        const Vec d = s1 - s0;
        points.push_back(s0 + t0 * d);
        if (t1 != t0) points.push_back(s0 + t1 * d);
      }
    }
  };
  collect(a, b);
  collect(b, a);
  std::sort(points.begin(), points.end());
  points.erase(std::unique(points.begin(), points.end()), points.end());
  return points;
}

bool interiors_disjoint(const Tri& a, const Tri& b, const Vec& n) {
  auto separated = [&](const Tri& edges_of, const Tri& other) {
    for (int i = 0; i < 3; ++i) {
      const Vec& p = edges_of.v[i];
      const Vec& q = edges_of.v[(i + 1) % 3];
      bool all_outside = true;
      for (int j = 0; j < 3 && all_outside; ++j) {
        if (dot(n, cross(q - p, other.v[j] - p)) > 0) all_outside = false;
      }
      if (all_outside) return true;
    }
    return false;
  };
  return separated(a, b) || separated(b, a);
}

std::vector<Vec> clip_halfspace(const std::vector<Vec>& polygon, const Vec& n, const Q& d) {
  std::vector<Vec> result;
  const std::size_t count = polygon.size();
  for (std::size_t i = 0; i < count; ++i) {
    const Vec& current = polygon[i];
    const Vec& next = polygon[(i + 1) % count];
    const Q sc = dot(n, current) - d;
    const Q sn = dot(n, next) - d;
    if (sc <= 0) result.push_back(current);
    if ((sc < 0 && sn > 0) || (sc > 0 && sn < 0)) {
      const Q s = sc / (sc - sn);
      result.push_back(current + s * (next - current));
    }
  }
  return result;
}

Q polygon_weight(const std::vector<Vec>& polygon, const Vec& n) {
  Q total = 0;
  for (std::size_t i = 1; i + 1 < polygon.size(); ++i) {
    total += dot(n, cross(polygon[i] - polygon[0], polygon[i + 1] - polygon[0]));
  }
  return total;
}

std::vector<std::size_t> canonical_ids(const RawMesh& mesh, std::size_t& distinct) {
  std::map<Vec, std::size_t> ids;
  std::vector<std::size_t> result;
  for (const auto& v : mesh.vertices) {
    const auto key = vec(v);
    const auto inserted = ids.emplace(key, ids.size());
    result.push_back(inserted.first->second);
  }
  distinct = ids.size();
  return result;
}

void require_triangle_faces(const RawMesh& mesh, const std::string& context, std::size_t maximum) {
  if (mesh.faces.empty()) validation_failure("MESH_EMPTY", context + " has no faces");
  if (mesh.faces.size() > maximum) {
    throw WorkerError("RESOURCE_LIMIT", "FACE_LIMIT_EXCEEDED", context + " exceeds the face limit");
  }
  for (const auto& face : mesh.faces) {
    if (face.size() != 3) validation_failure("MESH_NOT_TRIANGULATED", context + " must be triangulated");
    if (face[0] == face[1] || face[1] == face[2] || face[0] == face[2]) {
      validation_failure("DEGENERATE_FACE", context + " has a face repeating a vertex");
    }
  }
}

Json json_checks(std::initializer_list<const char*> names) {
  Json checks = Json::object();
  for (const char* name : names) checks[name] = true;
  return checks;
}

Json concluded(const Request& request, const std::string& validator, Json checks, Json details) {
  details["schema_version"] = 1;
  details["report_type"] = "ValidationReport";
  details["checks"] = std::move(checks);
  return query_ops::finish_validation(request, validator, std::move(details));
}

Json require_member(const Json& object, const char* key, const std::string& context) {
  if (!object.is_object() || !object.contains(key)) {
    validation_failure("REPORT_SCHEMA_MISMATCH", context + " lacks " + key);
  }
  return object.at(key);
}

std::size_t index_of(const Json& value, std::size_t bound, const std::string& context) {
  if (!value.is_number_integer() || value.is_boolean() || value.get<long long>() < 0 ||
      static_cast<std::size_t>(value.get<long long>()) >= bound) {
    validation_failure("INDEX_OUT_OF_RANGE", context + " is not a valid index");
  }
  return static_cast<std::size_t>(value.get<long long>());
}

Json vinfo(const std::vector<std::string>& checks, std::vector<std::string> slots,
           const std::string& independence) {
  return Json{{"checks", checks}, {"input_slots", slots}, {"output_slot", "validation"}, {"independence", independence}};
}

Json pinfo(const std::string& validator, const std::vector<std::string>& parameters,
           std::vector<std::string> slots, Json extra) {
  Json bindings = Json::object();
  for (const auto& name : parameters) bindings[name] = name;
  Json result{{"input_slots", slots},
              {"validators", Json::array({validator})},
              {"validator_parameter_bindings", {{validator, bindings}}}};
  if (parameters.empty()) result.erase("validator_parameter_bindings");
  for (auto& item : extra.items()) result[item.key()] = item.value();
  return result;
}

Json geometry_frame(const Request& request, const std::string& kind, Json parameters, Json source,
                    Json summary, Json results) {
  return Json{{"schema_version", 1},
              {"report_type", "GeometryQueryReport"},
              {"report_kind", kind},
              {"operation", request.operation},
              {"length_unit", request.inputs[0].unit},
              {"parameters", std::move(parameters)},
              {"source", std::move(source)},
              {"summary", std::move(summary)},
              {"results", std::move(results)}};
}

Json check_report_frame(const Json& report, const std::string& operation, const Json& parameters,
                        const std::vector<std::pair<const char*, const ArtifactInput*>>& sources, Json& checks) {
  if (report.value("operation", std::string()) != operation) {
    validation_failure("PARAMETER_MISMATCH", "Report is not a " + operation + " report");
  }
  if (require_member(report, "parameters", "report") != parameters) {
    validation_failure("PARAMETER_MISMATCH", "Report parameters differ from the validated request");
  }
  checks["parameters_match"] = true;
  const auto source = require_member(report, "source", "report");
  for (const auto& [key, input] : sources) {
    if (!source.is_object() || source.value(key, std::string()) != input->sha256) {
      validation_failure("SOURCE_MISMATCH", "Report does not describe the validated source artifacts");
    }
  }
  checks["source_matches"] = true;
  return require_member(report, "results", "report");
}

}  // namespace cgal_master::batch2
