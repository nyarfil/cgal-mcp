// Independent validators for the geometry kernel family (7.1).
//
// This translation unit includes no CGAL header. Every expected value is
// recomputed from the KernelQuerySet with GMP rational arithmetic (mpq_class)
// and hand-written formulas (determinants, Cramer's rule, closed-form
// projections, half-plane clipping). Policy:
//   * input echo and arithmetic-free results must match exactly in every kernel;
//   * predicates must match exactly for EPICK/EPECK; for the double kernels a
//     mismatch is tolerated only when the exact decisive value is within
//     1e-9 * S^degree of zero (ill-conditioned), and is counted;
//   * constructions must match exactly for EPECK; for the other kernels within
//     1e-9 * S^degree (S = max(1, max |input value|)); anything else fails closed.
// For EPICK and the double kernels the expected values are computed from the
// binary64 round-to-nearest inputs, i.e. the values the kernel actually received.

#include "kernel_query_set.h"

#include <gmpxx.h>

#include <algorithm>
#include <array>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

namespace cgal_master::kernel_ops {
namespace {

using Q = mpq_class;
struct V2 { Q x, y; };
struct V3 { Q x, y, z; };

V2 operator-(const V2& a, const V2& b) { return {a.x - b.x, a.y - b.y}; }
V2 operator+(const V2& a, const V2& b) { return {a.x + b.x, a.y + b.y}; }
V2 operator*(const Q& s, const V2& a) { return {s * a.x, s * a.y}; }
Q dot(const V2& a, const V2& b) { return a.x * b.x + a.y * b.y; }
Q cross(const V2& a, const V2& b) { return a.x * b.y - a.y * b.x; }
bool same(const V2& a, const V2& b) { return a.x == b.x && a.y == b.y; }

V3 operator-(const V3& a, const V3& b) { return {a.x - b.x, a.y - b.y, a.z - b.z}; }
V3 operator+(const V3& a, const V3& b) { return {a.x + b.x, a.y + b.y, a.z + b.z}; }
V3 operator*(const Q& s, const V3& a) { return {s * a.x, s * a.y, s * a.z}; }
Q dot(const V3& a, const V3& b) { return a.x * b.x + a.y * b.y + a.z * b.z; }
V3 cross(const V3& a, const V3& b) {
  return {a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x};
}
bool is_zero(const V3& a) { return a.x == 0 && a.y == 0 && a.z == 0; }
bool same(const V3& a, const V3& b) { return a.x == b.x && a.y == b.y && a.z == b.z; }
Q max_abs(const V3& a) { return std::max({Q(abs(a.x)), Q(abs(a.y)), Q(abs(a.z))}); }

int sign(const Q& v) { return sgn(v); }

std::string int_text(std::int64_t value) { return std::to_string(value); }

class Checker {
 public:
  Checker(std::string kernel, const QuerySet& set) : kernel_(std::move(kernel)), set_(set) {
    exact_predicates_ = kernel_has_exact_predicates(kernel_);
    exact_constructions_ = kernel_has_exact_constructions(kernel_);
    double_input_ = kernel_uses_double_input(kernel_);
    scale_ = 1;
    for (const auto& p : set_.primitives) {
      for (const auto& point : p.points) for (const auto& c : point) scale_ = std::max(scale_, Q(abs(value(c))));
      for (const auto& row : p.matrix) for (const auto& c : row) scale_ = std::max(scale_, Q(abs(value(c))));
      scale_ = std::max(scale_, Q(abs(value(p.squared_radius))));
    }
  }

  // Input value as received by the kernel.
  Q value(const Rational& r) const {
    if (double_input_) {
      const double rounded = static_cast<double>(r.numerator) / static_cast<double>(r.denominator);
      return Q(rounded);
    }
    Q q(int_text(r.numerator) + "/" + int_text(r.denominator));
    q.canonicalize();
    return q;
  }
  V2 p2(const Coordinates& c) const { return {value(c[0]), value(c[1])}; }
  V3 p3(const Coordinates& c) const { return {value(c[0]), value(c[1]), value(c[2])}; }

  Q tolerance(int degree) const {
    Q t(1, 1000000000);
    for (int i = 0; i < degree; ++i) t *= scale_;
    return t;
  }

  // Reported exact scalar: a canonical decimal rational string.
  static Q reported(const Json& value, const std::string& where) {
    if (!value.is_string()) validation_failure("REPORT_VALUE_INVALID", where + " is not an exact string");
    const auto text = value.get<std::string>();
    Q q;
    if (text.empty() || q.set_str(text, 10) != 0 || q.get_den() == 0) {
      validation_failure("REPORT_VALUE_INVALID", where + " is not a rational string");
    }
    q.canonicalize();
    if (q.get_str(10) != text) validation_failure("REPORT_VALUE_NONCANONICAL", where + " is not canonical");
    return q;
  }
  static V2 reported2(const Json& v, const std::string& where) {
    if (!v.is_array() || v.size() != 2) validation_failure("REPORT_VALUE_INVALID", where + " is not a 2D point");
    return {reported(v[0], where), reported(v[1], where)};
  }
  static V3 reported3(const Json& v, const std::string& where) {
    if (!v.is_array() || v.size() != 3) validation_failure("REPORT_VALUE_INVALID", where + " is not a 3D point");
    return {reported(v[0], where), reported(v[1], where), reported(v[2], where)};
  }

  // Exact echo (no arithmetic involved in any kernel).
  void echo(const Q& got, const Q& expected, const std::string& where) {
    ++exact_comparisons;
    if (got != expected) validation_failure("INPUT_ECHO_MISMATCH", where + " differs from the input");
  }
  void echo2(const Json& v, const V2& e, const std::string& w) {
    const auto g = reported2(v, w);
    echo(g.x, e.x, w);
    echo(g.y, e.y, w);
  }
  void echo3(const Json& v, const V3& e, const std::string& w) {
    const auto g = reported3(v, w);
    echo(g.x, e.x, w);
    echo(g.y, e.y, w);
    echo(g.z, e.z, w);
  }

  bool close(const Q& got, const Q& expected, int degree) {
    if (exact_constructions_) {
      ++exact_comparisons;
      return got == expected;
    }
    ++tolerance_comparisons;
    return abs(got - expected) <= tolerance(degree);
  }
  void construction(const Q& got, const Q& expected, int degree, const std::string& where) {
    if (!close(got, expected, degree)) {
      validation_failure("CONSTRUCTION_MISMATCH", where + " differs from the exact recomputation");
    }
  }
  void construction2(const Json& v, const V2& e, int d, const std::string& w) {
    const auto g = reported2(v, w);
    construction(g.x, e.x, d, w);
    construction(g.y, e.y, d, w);
  }
  void construction3(const Json& v, const V3& e, int d, const std::string& w) {
    const auto g = reported3(v, w);
    construction(g.x, e.x, d, w);
    construction(g.y, e.y, d, w);
    construction(g.z, e.z, d, w);
  }

  // A predicate decided by the exact value `decisive`.
  void predicate(bool match, const Q& decisive, int degree, const std::string& where) {
    if (match) {
      ++exact_comparisons;
      return;
    }
    if (exact_predicates_ || abs(decisive) > tolerance(degree)) {
      validation_failure("PREDICATE_MISMATCH", where + " differs from the exact predicate");
    }
    ++ill_conditioned_predicates;
  }

  // Residual that must vanish; for inexact constructions relative to `magnitude`.
  bool vanishes(const Q& residual, const Q& magnitude) {
    if (exact_constructions_) {
      ++exact_comparisons;
      return residual == 0;
    }
    ++tolerance_comparisons;
    return abs(residual) <= Q(1, 1000000000) * magnitude;
  }

  const std::string& kernel() const { return kernel_; }
  bool exact_constructions() const { return exact_constructions_; }
  const QuerySet& set() const { return set_; }
  const Q& scale() const { return scale_; }

  std::size_t exact_comparisons = 0;
  std::size_t tolerance_comparisons = 0;
  std::size_t ill_conditioned_predicates = 0;

 private:
  std::string kernel_;
  const QuerySet& set_;
  bool exact_predicates_ = false;
  bool exact_constructions_ = false;
  bool double_input_ = false;
  Q scale_;
};

const char* sign_name(int s) { return s > 0 ? "positive" : (s < 0 ? "negative" : "zero"); }

void require_keys(const Json& value, std::set<std::string> keys, const std::string& where) {
  std::set<std::string> actual;
  if (!value.is_object()) validation_failure("REPORT_SCHEMA_MISMATCH", where + " is not an object");
  for (const auto& item : value.items()) actual.insert(item.key());
  if (actual != keys) validation_failure("REPORT_SCHEMA_MISMATCH", where + " has missing or unexpected keys");
}

// ---- shared report frame ------------------------------------------------------

struct Frame {
  Json primitives;
  Json queries;
};

Frame check_frame(const Request& request, const Json& report, const std::string& kind,
                  const std::string& kernel, const std::string& operation, Json& checks) {
  require_keys(report, {"schema_version", "report_type", "report_kind", "operation", "kernel", "kernel_type",
                        "exact_predicates", "exact_constructions", "input_representation", "source",
                        "length_unit", "results"},
               "KernelReport");
  const auto& source = request.inputs[1];
  if (report.at("operation") != operation || report.at("kernel") != kernel ||
      report.at("kernel_type") != kernel_type_name(kernel) ||
      report.at("exact_predicates") != kernel_has_exact_predicates(kernel) ||
      report.at("exact_constructions") != kernel_has_exact_constructions(kernel) ||
      report.at("input_representation") !=
          (kernel_uses_double_input(kernel) ? "binary64_round_to_nearest" : "exact_rational")) {
    validation_failure("KERNEL_MISMATCH", "Report kernel declaration differs from the requested kernel");
  }
  checks["kernel_matches"] = true;
  if (report.at("source") != Json{{"sha256", source.sha256}, {"unit", source.unit}} ||
      report.at("length_unit") != source.unit) {
    validation_failure("SOURCE_MISMATCH", "Report does not describe the validated source artifact");
  }
  checks["source_matches"] = true;
  const auto& results = report.at("results");
  require_keys(results, {"primitives", "queries"}, "results");
  if (!results.at("primitives").is_array() || !results.at("queries").is_array()) {
    validation_failure("REPORT_SCHEMA_MISMATCH", "results entries must be arrays");
  }
  (void)kind;
  return {results.at("primitives"), results.at("queries")};
}

void check_query_identity(const QuerySet& set, const Json& queries) {
  if (queries.size() != set.queries.size()) {
    validation_failure("RESULT_SET_INCOMPLETE", "Report query count differs from the source");
  }
  for (std::size_t i = 0; i < queries.size(); ++i) {
    const auto& entry = queries[i];
    const auto& query = set.queries[i];
    require_keys(entry, {"id", "query", "arguments", "result"}, "query " + query.id);
    if (entry.at("id") != query.id || entry.at("query") != query.query ||
        entry.at("arguments") != Json(query.arguments)) {
      validation_failure("RESULT_SET_INCOMPLETE", "Report query " + std::to_string(i) + " differs from the source");
    }
  }
}

Json finish(const Request& request, const std::string& validator, const std::string& validates,
            const Checker& checker, Json checks) {
  checks["result_set_complete"] = true;
  Json report{{"schema_version", 1},
              {"validates", validates},
              {"kernel", checker.kernel()},
              {"checks", std::move(checks)},
              {"exact_comparisons", checker.exact_comparisons},
              {"tolerance_comparisons", checker.tolerance_comparisons},
              {"ill_conditioned_predicates", checker.ill_conditioned_predicates},
              {"query_count", checker.set().queries.size()},
              {"primitive_count", checker.set().primitives.size()},
              {"comparison_policy",
               "independent GMP rational recomputation; exact match for input echoes, for predicates in "
               "EPICK/EPECK and for EPECK constructions; inexact constructions within 1e-9*S^degree; "
               "double-kernel predicate mismatches only when the exact decisive value is within "
               "1e-9*S^degree of zero"},
              {"scale", checker.scale().get_str(10)},
              {"independence", "no CGAL header or kernel functor is used by this validator"}};
  return finish_kernel_validation(request, validator, std::move(report));
}

struct Context {
  QuerySet set;
  std::string kernel;
  Json report;
};

Context load(const Request& request, const std::string& kind, const std::string& operation,
             bool allow_inexact_predicates) {
  require_inputs(request, 2, operation);
  Context context;
  context.kernel = kernel_parameter(request, allow_inexact_predicates);
  context.report = read_kernel_report(request.inputs[0], kind);
  context.set = read_query_set(request.inputs[1]);
  return context;
}

// ---- primitives -----------------------------------------------------------------

void check_line2_through(Checker& c, const Json& coefficients, const V2& p, const V2& q,
                         bool oriented, const std::string& w) {
  if (!coefficients.is_array() || coefficients.size() != 3) {
    validation_failure("REPORT_VALUE_INVALID", w + " coefficients must have 3 entries");
  }
  const Q a = Checker::reported(coefficients[0], w), b = Checker::reported(coefficients[1], w),
          cc = Checker::reported(coefficients[2], w);
  if (a == 0 && b == 0) validation_failure("CONSTRUCTION_MISMATCH", w + " has a zero normal");
  for (const auto& x : {p, q}) {
    const Q residual = a * x.x + b * x.y + cc;
    const Q magnitude = abs(a * x.x) + abs(b * x.y) + abs(cc);
    if (!c.vanishes(residual, magnitude)) {
      validation_failure("CONSTRUCTION_MISMATCH", w + " does not pass through its defining points");
    }
  }
  if (oriented && dot(V2{b, -a}, q - p) <= 0) {
    validation_failure("CONSTRUCTION_MISMATCH", w + " has the wrong orientation");
  }
}

void check_affine(Checker& c, const Primitive& p, const Json& entry, const std::string& w) {
  const int d = p.dimension;
  const auto& rows = entry.at("matrix");
  if (!rows.is_array() || rows.size() != static_cast<std::size_t>(d)) {
    validation_failure("REPORT_VALUE_INVALID", w + " matrix shape");
  }
  for (int i = 0; i < d; ++i) {
    if (!rows[i].is_array() || rows[i].size() != static_cast<std::size_t>(d + 1)) {
      validation_failure("REPORT_VALUE_INVALID", w + " matrix shape");
    }
    for (int j = 0; j <= d; ++j) c.echo(Checker::reported(rows[i][j], w), c.value(p.matrix[i][j]), w + " matrix");
  }
  auto m = [&](int i, int j) { return c.value(p.matrix[i][j]); };
  const Q det = d == 2 ? Q(m(0, 0) * m(1, 1) - m(0, 1) * m(1, 0))
                       : Q(m(0, 0) * (m(1, 1) * m(2, 2) - m(1, 2) * m(2, 1)) -
                             m(0, 1) * (m(1, 0) * m(2, 2) - m(1, 2) * m(2, 0)) +
                             m(0, 2) * (m(1, 0) * m(2, 1) - m(1, 1) * m(2, 0)));
  if (!entry.at("is_even").is_boolean()) validation_failure("REPORT_VALUE_INVALID", w + " is_even");
  c.predicate(entry.at("is_even").get<bool>() == (det > 0), det, d, w + " is_even");
}

void check_primitive(Checker& c, const Primitive& p, const Json& entry) {
  const std::string w = "primitive " + p.id;
  const auto& k = p.kind;
  const auto& pts = p.points;
  auto keys = [&](std::set<std::string> extra) {
    extra.insert("id");
    extra.insert("kind");
    require_keys(entry, extra, w);
    if (entry.at("id") != p.id || entry.at("kind") != k) validation_failure("RESULT_SET_INCOMPLETE", w);
  };
  auto flag = [&](const char* key) {
    if (!entry.at(key).is_boolean()) validation_failure("REPORT_VALUE_INVALID", w + " " + key);
    return entry.at(key).get<bool>();
  };
  if (k == "Point_2") {
    keys({"coordinates"});
    c.echo2(entry.at("coordinates"), c.p2(pts[0]), w);
  } else if (k == "Point_3") {
    keys({"coordinates"});
    c.echo3(entry.at("coordinates"), c.p3(pts[0]), w);
  } else if (k == "Vector_2") {
    keys({"coordinates", "squared_length"});
    const auto v = c.p2(pts[0]);
    c.echo2(entry.at("coordinates"), v, w);
    c.construction(Checker::reported(entry.at("squared_length"), w), dot(v, v), 2, w + " squared_length");
  } else if (k == "Vector_3") {
    keys({"coordinates", "squared_length"});
    const auto v = c.p3(pts[0]);
    c.echo3(entry.at("coordinates"), v, w);
    c.construction(Checker::reported(entry.at("squared_length"), w), dot(v, v), 2, w + " squared_length");
  } else if (k == "Segment_2" || k == "Segment_3") {
    keys({"source", "target", "squared_length", "degenerate"});
    Q length;
    bool degenerate;
    if (k == "Segment_2") {
      const auto a = c.p2(pts[0]), b = c.p2(pts[1]);
      c.echo2(entry.at("source"), a, w);
      c.echo2(entry.at("target"), b, w);
      length = dot(b - a, b - a);
      degenerate = same(a, b);
    } else {
      const auto a = c.p3(pts[0]), b = c.p3(pts[1]);
      c.echo3(entry.at("source"), a, w);
      c.echo3(entry.at("target"), b, w);
      length = dot(b - a, b - a);
      degenerate = same(a, b);
    }
    c.construction(Checker::reported(entry.at("squared_length"), w), length, 2, w + " squared_length");
    if (flag("degenerate") != degenerate) validation_failure("PREDICATE_MISMATCH", w + " degenerate");
    ++c.exact_comparisons;
  } else if (k == "Line_2") {
    keys({"coefficients", "degenerate"});
    const auto a = c.p2(pts[0]), b = c.p2(pts[1]);
    const bool degenerate = same(a, b);
    if (flag("degenerate") != degenerate) validation_failure("PREDICATE_MISMATCH", w + " degenerate");
    if (degenerate) {
      for (const auto& value : entry.at("coefficients")) c.echo(Checker::reported(value, w), 0, w);
    } else {
      check_line2_through(c, entry.at("coefficients"), a, b, true, w);
    }
  } else if (k == "Ray_2") {
    keys({"source", "direction_vector", "degenerate"});
    const auto a = c.p2(pts[0]), b = c.p2(pts[1]);
    c.echo2(entry.at("source"), a, w);
    c.construction2(entry.at("direction_vector"), b - a, 1, w + " direction_vector");
    if (flag("degenerate") != same(a, b)) validation_failure("PREDICATE_MISMATCH", w + " degenerate");
  } else if (k == "Line_3" || k == "Ray_3") {
    keys({k == "Line_3" ? "point" : "source", "direction_vector", "degenerate"});
    const auto a = c.p3(pts[0]), b = c.p3(pts[1]);
    c.echo3(entry.at(k == "Line_3" ? "point" : "source"), a, w);
    c.construction3(entry.at("direction_vector"), b - a, 1, w + " direction_vector");
    if (flag("degenerate") != same(a, b)) validation_failure("PREDICATE_MISMATCH", w + " degenerate");
  } else if (k == "Triangle_2") {
    keys({"vertices", "signed_area", "orientation", "degenerate"});
    const auto a = c.p2(pts[0]), b = c.p2(pts[1]), d = c.p2(pts[2]);
    const auto& vertices = entry.at("vertices");
    if (!vertices.is_array() || vertices.size() != 3) validation_failure("REPORT_VALUE_INVALID", w);
    c.echo2(vertices[0], a, w);
    c.echo2(vertices[1], b, w);
    c.echo2(vertices[2], d, w);
    const Q twice = cross(b - a, d - a);
    c.construction(Checker::reported(entry.at("signed_area"), w), twice / 2, 2, w + " signed_area");
    c.predicate(entry.at("orientation") == sign_name(sign(twice)), twice, 2, w + " orientation");
    c.predicate(flag("degenerate") == (twice == 0), twice, 2, w + " degenerate");
  } else if (k == "Circle_2" || k == "Sphere_3") {
    keys({"center", "squared_radius", "orientation", "degenerate"});
    if (k == "Circle_2") c.echo2(entry.at("center"), c.p2(pts[0]), w);
    else c.echo3(entry.at("center"), c.p3(pts[0]), w);
    const Q r = c.value(p.squared_radius);
    c.echo(Checker::reported(entry.at("squared_radius"), w), r, w + " squared_radius");
    if (entry.at("orientation") != "positive") validation_failure("PREDICATE_MISMATCH", w + " orientation");
    if (flag("degenerate") != (r == 0)) validation_failure("PREDICATE_MISMATCH", w + " degenerate");
  } else if (k == "Iso_rectangle_2") {
    keys({"min", "max", "area", "degenerate"});
    const auto a = c.p2(pts[0]), b = c.p2(pts[1]);
    const V2 lo{std::min(a.x, b.x), std::min(a.y, b.y)}, hi{std::max(a.x, b.x), std::max(a.y, b.y)};
    c.echo2(entry.at("min"), lo, w);
    c.echo2(entry.at("max"), hi, w);
    c.construction(Checker::reported(entry.at("area"), w), (hi.x - lo.x) * (hi.y - lo.y), 2, w + " area");
    if (flag("degenerate") != (lo.x == hi.x || lo.y == hi.y)) validation_failure("PREDICATE_MISMATCH", w);
  } else if (k == "Iso_cuboid_3") {
    keys({"min", "max", "volume", "degenerate"});
    const auto a = c.p3(pts[0]), b = c.p3(pts[1]);
    const V3 lo{std::min(a.x, b.x), std::min(a.y, b.y), std::min(a.z, b.z)};
    const V3 hi{std::max(a.x, b.x), std::max(a.y, b.y), std::max(a.z, b.z)};
    c.echo3(entry.at("min"), lo, w);
    c.echo3(entry.at("max"), hi, w);
    c.construction(Checker::reported(entry.at("volume"), w), (hi.x - lo.x) * (hi.y - lo.y) * (hi.z - lo.z), 3,
                   w + " volume");
    if (flag("degenerate") != (lo.x == hi.x || lo.y == hi.y || lo.z == hi.z)) {
      validation_failure("PREDICATE_MISMATCH", w);
    }
  } else if (k == "Plane_3") {
    keys({"coefficients", "degenerate"});
    const auto a = c.p3(pts[0]), b = c.p3(pts[1]), d = c.p3(pts[2]);
    const V3 n = cross(b - a, d - a);
    const Q offset = -dot(n, a);
    const auto& co = entry.at("coefficients");
    if (!co.is_array() || co.size() != 4) validation_failure("REPORT_VALUE_INVALID", w);
    c.construction(Checker::reported(co[0], w), n.x, 2, w + " a");
    c.construction(Checker::reported(co[1], w), n.y, 2, w + " b");
    c.construction(Checker::reported(co[2], w), n.z, 2, w + " c");
    c.construction(Checker::reported(co[3], w), offset, 3, w + " d");
    c.predicate(flag("degenerate") == is_zero(n), max_abs(n), 2, w + " degenerate");
  } else if (k == "Triangle_3") {
    keys({"vertices", "squared_area", "degenerate"});
    const auto a = c.p3(pts[0]), b = c.p3(pts[1]), d = c.p3(pts[2]);
    const auto& vertices = entry.at("vertices");
    if (!vertices.is_array() || vertices.size() != 3) validation_failure("REPORT_VALUE_INVALID", w);
    c.echo3(vertices[0], a, w);
    c.echo3(vertices[1], b, w);
    c.echo3(vertices[2], d, w);
    const V3 n = cross(b - a, d - a);
    c.construction(Checker::reported(entry.at("squared_area"), w), dot(n, n) / 4, 4, w + " squared_area");
    c.predicate(flag("degenerate") == is_zero(n), max_abs(n), 2, w + " degenerate");
  } else if (k == "Tetrahedron_3") {
    keys({"vertices", "signed_volume", "orientation", "degenerate"});
    std::array<V3, 4> v;
    const auto& vertices = entry.at("vertices");
    if (!vertices.is_array() || vertices.size() != 4) validation_failure("REPORT_VALUE_INVALID", w);
    for (int i = 0; i < 4; ++i) {
      v[i] = c.p3(pts[i]);
      c.echo3(vertices[i], v[i], w);
    }
    const Q det = dot(v[1] - v[0], cross(v[2] - v[0], v[3] - v[0]));
    c.construction(Checker::reported(entry.at("signed_volume"), w), det / 6, 3, w + " signed_volume");
    c.predicate(entry.at("orientation") == sign_name(sign(det)), det, 3, w + " orientation");
    c.predicate(flag("degenerate") == (det == 0), det, 3, w + " degenerate");
  } else if (k == "Aff_transformation_2" || k == "Aff_transformation_3") {
    keys({"matrix", "is_even"});
    check_affine(c, p, entry, w);
  } else {
    validation_failure("REPORT_SCHEMA_MISMATCH", w + " has an unknown kind");
  }
}

void check_transform(Checker& c, const Query& q, const Json& result) {
  const auto& t = c.set().at(q.arguments.at(0));
  const auto& x = c.set().at(q.arguments.at(1));
  const std::string w = "query " + q.id;
  const int d = t.dimension;
  const bool vector = x.kind == "Vector_2" || x.kind == "Vector_3";
  if (x.dimension != d || (x.kind != "Point_" + std::to_string(d) && x.kind != "Vector_" + std::to_string(d)) ||
      t.kind != "Aff_transformation_" + std::to_string(d)) {
    validation_failure("RESULT_SET_INCOMPLETE", w + " arguments are not a transformation and point/vector");
  }
  require_keys(result, {"kind", "coordinates"}, w);
  if (result.at("kind") != x.kind) validation_failure("CONSTRUCTION_MISMATCH", w + " result kind");
  std::vector<Q> in;
  for (const auto& coordinate : x.points[0]) in.push_back(c.value(coordinate));
  std::vector<Q> out;
  for (int i = 0; i < d; ++i) {
    Q sum = vector ? Q(0) : c.value(t.matrix[i][d]);
    for (int j = 0; j < d; ++j) sum += c.value(t.matrix[i][j]) * in[j];
    out.push_back(sum);
  }
  if (d == 2) c.construction2(result.at("coordinates"), {out[0], out[1]}, 2, w);
  else c.construction3(result.at("coordinates"), {out[0], out[1], out[2]}, 2, w);
}

Json validate_primitives(const Request& request) {
  auto context = load(request, "primitives", "kernel.validate.primitives_report", true);
  Json checks = Json::object();
  const auto frame = check_frame(request, context.report, "primitives", context.kernel,
                                 "kernel.primitives.construct", checks);
  Checker checker(context.kernel, context.set);
  if (frame.primitives.size() != context.set.primitives.size()) {
    validation_failure("RESULT_SET_INCOMPLETE", "Report primitive count differs from the source");
  }
  for (std::size_t i = 0; i < frame.primitives.size(); ++i) {
    check_primitive(checker, context.set.primitives[i], frame.primitives[i]);
  }
  checks["primitive_properties_match"] = true;
  check_query_identity(context.set, frame.queries);
  for (std::size_t i = 0; i < frame.queries.size(); ++i) {
    if (context.set.queries[i].query != "transform") validation_failure("RESULT_SET_INCOMPLETE", "unknown query");
    check_transform(checker, context.set.queries[i], frame.queries[i].at("result"));
  }
  checks["transformations_match"] = true;
  return finish(request, "kernel.validate.primitives_report", "kernel.primitives.construct", checker,
                std::move(checks));
}

// ---- predicates and constructions -----------------------------------------------

V3 circumcenter3(const V3& p, const V3& q, const V3& r) {
  const V3 u = q - p, v = r - p, w = cross(u, v);
  const V3 numerator = cross(dot(u, u) * v - dot(v, v) * u, w);
  return p + (Q(1) / (2 * dot(w, w))) * numerator;
}

V3 circumcenter4(const V3& p, const V3& q, const V3& r, const V3& s) {
  const V3 u = q - p, v = r - p, w = s - p;
  // 2 [u; v; w] x = [|u|^2; |v|^2; |w|^2], solved by Cramer's rule.
  const Q bu = dot(u, u), bv = dot(v, v), bw = dot(w, w);
  auto det3 = [](const V3& a, const V3& b, const V3& c) { return dot(a, cross(b, c)); };
  const Q den = 2 * det3(u, v, w);
  const V3 cu{bu, u.y, u.z}, cv{bv, v.y, v.z}, cw{bw, w.y, w.z};
  const V3 du{u.x, bu, u.z}, dv{v.x, bv, v.z}, dw{w.x, bw, w.z};
  const V3 eu{u.x, u.y, bu}, ev{v.x, v.y, bv}, ew{w.x, w.y, bw};
  return p + V3{det3(cu, cv, cw) / den, det3(du, dv, dw) / den, det3(eu, ev, ew) / den};
}

void check_predicate_query(Checker& c, const Query& q, const Json& result) {
  const std::string w = "query " + q.id;
  const auto n = q.arguments.size();
  int d = 0;
  for (const auto& name : q.arguments) {
    const auto& p = c.set().at(name);
    const int pd = p.kind == "Point_2" ? 2 : (p.kind == "Point_3" ? 3 : 0);
    if (pd == 0 || (d != 0 && pd != d)) validation_failure("RESULT_SET_INCOMPLETE", w + " arguments");
    d = pd;
  }
  auto a2 = [&](std::size_t i) { return c.p2(c.set().at(q.arguments[i]).points[0]); };
  auto a3 = [&](std::size_t i) { return c.p3(c.set().at(q.arguments[i]).points[0]); };
  auto boolean = [&]() {
    if (!result.is_boolean()) validation_failure("REPORT_VALUE_INVALID", w + " result is not boolean");
    return result.get<bool>();
  };
  const auto& name = q.query;
  if (name == "orientation" && d == 2 && n == 3) {
    const Q det = cross(a2(1) - a2(0), a2(2) - a2(0));
    const char* expected = det > 0 ? "left_turn" : (det < 0 ? "right_turn" : "collinear");
    c.predicate(result == expected, det, 2, w);
  } else if (name == "orientation" && d == 3 && n == 4) {
    const Q det = dot(a3(1) - a3(0), cross(a3(2) - a3(0), a3(3) - a3(0)));
    const char* expected = det > 0 ? "positive" : (det < 0 ? "negative" : "coplanar");
    c.predicate(result == expected, det, 3, w);
  } else if (name == "collinear" && n == 3) {
    if (d == 2) {
      const Q det = cross(a2(1) - a2(0), a2(2) - a2(0));
      c.predicate(boolean() == (det == 0), det, 2, w);
    } else {
      const V3 n3 = cross(a3(1) - a3(0), a3(2) - a3(0));
      c.predicate(boolean() == is_zero(n3), max_abs(n3), 2, w);
    }
  } else if (name == "coplanar" && d == 3 && n == 4) {
    const Q det = dot(a3(1) - a3(0), cross(a3(2) - a3(0), a3(3) - a3(0)));
    c.predicate(boolean() == (det == 0), det, 3, w);
  } else if ((name == "left_turn" || name == "right_turn") && d == 2 && n == 3) {
    const Q det = cross(a2(1) - a2(0), a2(2) - a2(0));
    c.predicate(boolean() == (name == "left_turn" ? det > 0 : det < 0), det, 2, w);
  } else if (name == "midpoint" && n == 2) {
    if (d == 2) c.construction2(result, Q(1, 2) * (a2(0) + a2(1)), 1, w);
    else c.construction3(result, Q(1, 2) * (a3(0) + a3(1)), 1, w);
  } else if (name == "centroid" && (n == 3 || n == 4)) {
    const Q inverse(1, static_cast<unsigned long>(n));
    if (d == 2) {
      V2 sum = a2(0);
      for (std::size_t i = 1; i < n; ++i) sum = sum + a2(i);
      c.construction2(result, inverse * sum, 1, w);
    } else {
      V3 sum = a3(0);
      for (std::size_t i = 1; i < n; ++i) sum = sum + a3(i);
      c.construction3(result, inverse * sum, 1, w);
    }
  } else if (name == "circumcenter" && d == 2 && n == 3) {
    const V2 b = a2(1) - a2(0), e = a2(2) - a2(0);
    const Q den = 2 * cross(b, e);
    if (den == 0) validation_failure("DEGENERATE_CONFIGURATION", w + " collinear circumcenter was reported");
    const V2 offset{(e.y * dot(b, b) - b.y * dot(e, e)) / den, (b.x * dot(e, e) - e.x * dot(b, b)) / den};
    c.construction2(result, a2(0) + offset, 1, w);
  } else if (name == "circumcenter" && d == 3 && n == 3) {
    if (is_zero(cross(a3(1) - a3(0), a3(2) - a3(0)))) {
      validation_failure("DEGENERATE_CONFIGURATION", w + " collinear circumcenter was reported");
    }
    c.construction3(result, circumcenter3(a3(0), a3(1), a3(2)), 1, w);
  } else if (name == "circumcenter" && d == 3 && n == 4) {
    if (dot(a3(1) - a3(0), cross(a3(2) - a3(0), a3(3) - a3(0))) == 0) {
      validation_failure("DEGENERATE_CONFIGURATION", w + " coplanar circumcenter was reported");
    }
    c.construction3(result, circumcenter4(a3(0), a3(1), a3(2), a3(3)), 1, w);
  } else {
    validation_failure("RESULT_SET_INCOMPLETE", w + " is not a supported predicate/construction");
  }
}

Json validate_predicates(const Request& request) {
  auto context = load(request, "predicates", "kernel.validate.predicates_report", true);
  Json checks = Json::object();
  const auto frame = check_frame(request, context.report, "predicates", context.kernel,
                                 "kernel.predicates.evaluate", checks);
  if (!frame.primitives.empty()) validation_failure("REPORT_SCHEMA_MISMATCH", "Predicate reports list no primitives");
  Checker checker(context.kernel, context.set);
  if (context.set.queries.empty()) validation_failure("RESULT_SET_INCOMPLETE", "Source has no queries");
  check_query_identity(context.set, frame.queries);
  for (std::size_t i = 0; i < frame.queries.size(); ++i) {
    check_predicate_query(checker, context.set.queries[i], frame.queries[i].at("result"));
  }
  checks["predicates_match"] = true;
  checks["constructions_match"] = true;
  return finish(request, "kernel.validate.predicates_report", "kernel.predicates.evaluate", checker,
                std::move(checks));
}

// ---- intersections -----------------------------------------------------------------

// Exact expected intersection: kind plus the defining points (for line/plane
// results the source primitive points that span it).
struct Expected {
  std::string type = "empty";
  std::vector<V2> points2;
  std::vector<V3> points3;
};

// Linear parameter interval [lo, hi] with optional bounds.
struct Interval {
  std::optional<Q> lo, hi;
  bool empty = false;
  // Constrain alpha + beta * t >= 0.
  void at_least(const Q& alpha, const Q& beta) {
    if (empty) return;
    if (beta == 0) {
      if (alpha < 0) empty = true;
      return;
    }
    const Q t = -alpha / beta;
    if (beta > 0) {
      if (!lo || t > *lo) lo = t;
    } else if (!hi || t < *hi) {
      hi = t;
    }
    if (lo && hi && *lo > *hi) empty = true;
  }
};

Expected segment_segment2(const V2& a, const V2& b, const V2& p, const V2& q) {
  Expected e;
  const V2 d = b - a;
  const Q o1 = cross(d, p - a), o2 = cross(d, q - a);
  const Q o3 = cross(q - p, a - p), o4 = cross(q - p, b - p);
  if (o1 == 0 && o2 == 0) {
    const Q len = dot(d, d);
    const Q tp = dot(p - a, d) / len, tq = dot(q - a, d) / len;
    const Q lo = std::max(Q(0), std::min(tp, tq)), hi = std::min(Q(1), std::max(tp, tq));
    if (lo > hi) return e;
    e.points2.push_back(a + lo * d);
    if (lo == hi) {
      e.type = "point";
    } else {
      e.type = "segment";
      e.points2.push_back(a + hi * d);
    }
    return e;
  }
  if (sgn(o1) * sgn(o2) <= 0 && sgn(o3) * sgn(o4) <= 0) {
    const Q t = cross(p - a, q - p) / cross(d, q - p);
    e.type = "point";
    e.points2.push_back(a + t * d);
  }
  return e;
}

Expected line_line2(const V2& a, const V2& b, const V2& p, const V2& q) {
  Expected e;
  const V2 d1 = b - a, d2 = q - p;
  const Q den = cross(d1, d2);
  if (den != 0) {
    e.type = "point";
    e.points2.push_back(a + (cross(p - a, d2) / den) * d1);
  } else if (cross(d1, p - a) == 0) {
    e.type = "line";
    e.points2 = {a, b};
  }
  return e;
}

// Clip convex polygon `poly` by the closed half-planes left of each ccw edge of `clip`.
std::vector<V2> clip_polygon(std::vector<V2> poly, std::vector<V2> clip) {
  if (cross(clip[1] - clip[0], clip[2] - clip[0]) < 0) std::swap(clip[1], clip[2]);
  for (std::size_t i = 0; i < 3 && !poly.empty(); ++i) {
    const V2 e0 = clip[i], e1 = clip[(i + 1) % 3];
    auto side = [&](const V2& x) { return cross(e1 - e0, x - e0); };
    std::vector<V2> out;
    for (std::size_t j = 0; j < poly.size(); ++j) {
      const V2 cur = poly[j], next = poly[(j + 1) % poly.size()];
      const Q sc = side(cur), sn = side(next);
      if (sc >= 0) out.push_back(cur);
      if ((sc > 0 && sn < 0) || (sc < 0 && sn > 0)) out.push_back(cur + (sc / (sc - sn)) * (next - cur));
    }
    poly = std::move(out);
  }
  return poly;
}

// Distinct vertices of a convex point set, dropping points interior to hull edges.
std::vector<V2> hull_vertices(const std::vector<V2>& points) {
  std::vector<V2> unique;
  for (const auto& p : points) {
    if (std::none_of(unique.begin(), unique.end(), [&](const V2& u) { return same(u, p); })) unique.push_back(p);
  }
  if (unique.size() < 3) return unique;
  std::sort(unique.begin(), unique.end(), [](const V2& a, const V2& b) {
    return a.x < b.x || (a.x == b.x && a.y < b.y);
  });
  std::vector<V2> hull;
  for (int pass = 0; pass < 2; ++pass) {
    const std::size_t start = hull.size();
    for (const auto& p : unique) {
      while (hull.size() >= start + 2 && cross(hull[hull.size() - 1] - hull[hull.size() - 2], p - hull[hull.size() - 2]) <= 0) {
        hull.pop_back();
      }
      hull.push_back(p);
    }
    hull.pop_back();
    std::reverse(unique.begin(), unique.end());
  }
  return hull;
}

Expected triangle_triangle2(const std::vector<V2>& t1, const std::vector<V2>& t2) {
  std::vector<V2> poly = t1;
  if (cross(poly[1] - poly[0], poly[2] - poly[0]) < 0) std::swap(poly[1], poly[2]);
  const auto vertices = hull_vertices(clip_polygon(poly, t2));
  Expected e;
  e.points2 = vertices;
  e.type = vertices.empty() ? "empty"
                            : vertices.size() == 1 ? "point"
                                                   : vertices.size() == 2 ? "segment"
                                                                          : vertices.size() == 3 ? "triangle" : "polygon";
  return e;
}

// Line a + t d (t restricted by `range`) against plane through p0 with normal n.
Expected linear_plane(const V3& a, const V3& dvec, Interval range, const V3& p0, const V3& n) {
  Expected e;
  const Q den = dot(n, dvec), num = dot(n, p0 - a);
  if (den != 0) {
    const Q t = num / den;
    if ((range.lo && t < *range.lo) || (range.hi && t > *range.hi)) return e;
    e.type = "point";
    e.points3.push_back(a + t * dvec);
    return e;
  }
  if (num != 0) return e;
  if (!range.lo && !range.hi) {
    e.type = "line";
    e.points3 = {a, a + dvec};
  } else {
    e.type = "segment";
    e.points3 = {a + *range.lo * dvec, a + *range.hi * dvec};
  }
  return e;
}

Expected linear_triangle(const V3& a, const V3& dvec, Interval range, const V3& t0, const V3& t1, const V3& t2) {
  Expected e;
  const V3 n = cross(t1 - t0, t2 - t0);
  const Q den = dot(n, dvec), num = dot(n, t0 - a);
  const std::array<V3, 3> v{t0, t1, t2};
  if (den != 0) {
    const Q t = num / den;
    if ((range.lo && t < *range.lo) || (range.hi && t > *range.hi)) return e;
    const V3 x = a + t * dvec;
    for (int i = 0; i < 3; ++i) {
      if (dot(n, cross(v[(i + 1) % 3] - v[i], x - v[i])) < 0) return e;
    }
    e.type = "point";
    e.points3.push_back(x);
    return e;
  }
  if (num != 0) return e;
  for (int i = 0; i < 3; ++i) {
    const V3 edge = v[(i + 1) % 3] - v[i];
    range.at_least(dot(n, cross(edge, a - v[i])), dot(n, cross(edge, dvec)));
  }
  if (range.empty || !range.lo || !range.hi) return e;
  e.points3.push_back(a + *range.lo * dvec);
  if (*range.lo == *range.hi) {
    e.type = "point";
  } else {
    e.type = "segment";
    e.points3.push_back(a + *range.hi * dvec);
  }
  return e;
}

Expected plane_plane(const V3& p0, const V3& n0, const std::array<V3, 3>& first, const V3& p1, const V3& n1) {
  Expected e;
  const V3 direction = cross(n0, n1);
  if (!is_zero(direction)) {
    e.type = "line";  // checked semantically: points on both planes, distinct
    return e;
  }
  if (dot(n0, p1 - p0) == 0) {
    e.type = "plane";
    e.points3 = {first[0], first[1], first[2]};
  }
  (void)n1;
  return e;
}

Expected line_line3(const V3& a, const V3& b, const V3& p, const V3& q) {
  Expected e;
  const V3 d1 = b - a, d2 = q - p, n = cross(d1, d2);
  if (!is_zero(n)) {
    if (dot(p - a, n) != 0) return e;
    const Q t = dot(cross(p - a, d2), n) / dot(n, n);
    e.type = "point";
    e.points3.push_back(a + t * d1);
  } else if (is_zero(cross(p - a, d1))) {
    e.type = "line";
    e.points3 = {a, b};
  }
  return e;
}

void match_points2(Checker& c, const Json& reported, const std::vector<V2>& expected, const std::string& w) {
  if (!reported.is_array() || reported.size() != expected.size()) {
    validation_failure("INTERSECTION_MISMATCH", w + " vertex count differs");
  }
  std::vector<bool> used(expected.size(), false);
  for (const auto& item : reported) {
    const V2 got = Checker::reported2(item, w);
    bool found = false;
    for (std::size_t i = 0; i < expected.size() && !found; ++i) {
      if (!used[i] && c.close(got.x, expected[i].x, 1) && c.close(got.y, expected[i].y, 1)) used[i] = found = true;
    }
    if (!found) validation_failure("INTERSECTION_MISMATCH", w + " vertex differs from the exact intersection");
  }
}

void match_points3(Checker& c, const Json& reported, const std::vector<V3>& expected, const std::string& w) {
  if (!reported.is_array() || reported.size() != expected.size()) {
    validation_failure("INTERSECTION_MISMATCH", w + " vertex count differs");
  }
  std::vector<bool> used(expected.size(), false);
  for (const auto& item : reported) {
    const V3 got = Checker::reported3(item, w);
    bool found = false;
    for (std::size_t i = 0; i < expected.size() && !found; ++i) {
      if (!used[i] && c.close(got.x, expected[i].x, 1) && c.close(got.y, expected[i].y, 1) &&
          c.close(got.z, expected[i].z, 1)) {
        used[i] = found = true;
      }
    }
    if (!found) validation_failure("INTERSECTION_MISMATCH", w + " vertex differs from the exact intersection");
  }
}

bool on_plane(Checker& c, const V3& x, const V3& p0, const V3& n) {
  return c.vanishes(dot(n, x - p0), abs(n.x * (x.x - p0.x)) + abs(n.y * (x.y - p0.y)) + abs(n.z * (x.z - p0.z)) +
                                        c.tolerance(3));
}

bool on_line3(Checker& c, const V3& x, const V3& a, const V3& d) {
  const V3 r = cross(x - a, d);
  const Q magnitude = (max_abs(x - a) + 1) * max_abs(d) * 2;
  return c.vanishes(r.x, magnitude) && c.vanishes(r.y, magnitude) && c.vanishes(r.z, magnitude);
}

void check_intersection_query(Checker& c, const Query& q, const Json& result) {
  const std::string w = "query " + q.id;
  if (q.arguments.size() != 2) validation_failure("RESULT_SET_INCOMPLETE", w);
  const Primitive* x = &c.set().at(q.arguments[0]);
  const Primitive* y = &c.set().at(q.arguments[1]);
  // Canonical order for the asymmetric pairs; intersection is symmetric.
  if (y->kind == "Line_3" && x->kind == "Plane_3") std::swap(x, y);
  if (y->kind == "Segment_3" && (x->kind == "Plane_3" || x->kind == "Triangle_3")) std::swap(x, y);
  if (y->kind == "Ray_3" && x->kind == "Triangle_3") std::swap(x, y);
  const auto pair = x->kind + "|" + y->kind;
  auto P2 = [&](const Primitive* p, int i) { return c.p2(p->points[i]); };
  auto P3 = [&](const Primitive* p, int i) { return c.p3(p->points[i]); };
  auto normal = [&](const Primitive* p) { return cross(P3(p, 1) - P3(p, 0), P3(p, 2) - P3(p, 0)); };
  Expected e;
  Interval unit;
  unit.lo = Q(0);
  unit.hi = Q(1);
  Interval ray;
  ray.lo = Q(0);
  if (pair == "Segment_2|Segment_2") e = segment_segment2(P2(x, 0), P2(x, 1), P2(y, 0), P2(y, 1));
  else if (pair == "Line_2|Line_2") e = line_line2(P2(x, 0), P2(x, 1), P2(y, 0), P2(y, 1));
  else if (pair == "Triangle_2|Triangle_2")
    e = triangle_triangle2({P2(x, 0), P2(x, 1), P2(x, 2)}, {P2(y, 0), P2(y, 1), P2(y, 2)});
  else if (pair == "Line_3|Plane_3") e = linear_plane(P3(x, 0), P3(x, 1) - P3(x, 0), Interval{}, P3(y, 0), normal(y));
  else if (pair == "Segment_3|Plane_3") e = linear_plane(P3(x, 0), P3(x, 1) - P3(x, 0), unit, P3(y, 0), normal(y));
  else if (pair == "Plane_3|Plane_3")
    e = plane_plane(P3(x, 0), normal(x), {P3(x, 0), P3(x, 1), P3(x, 2)}, P3(y, 0), normal(y));
  else if (pair == "Segment_3|Triangle_3")
    e = linear_triangle(P3(x, 0), P3(x, 1) - P3(x, 0), unit, P3(y, 0), P3(y, 1), P3(y, 2));
  else if (pair == "Ray_3|Triangle_3")
    e = linear_triangle(P3(x, 0), P3(x, 1) - P3(x, 0), ray, P3(y, 0), P3(y, 1), P3(y, 2));
  else if (pair == "Line_3|Line_3") e = line_line3(P3(x, 0), P3(x, 1), P3(y, 0), P3(y, 1));
  else validation_failure("RESULT_SET_INCOMPLETE", w + " pair is not supported: " + pair);

  if (q.query == "do_intersect") {
    if (!result.is_boolean()) validation_failure("REPORT_VALUE_INVALID", w + " result is not boolean");
    if (result.get<bool>() != (e.type != "empty")) {
      validation_failure("INTERSECTION_MISMATCH", w + " do_intersect differs from the exact predicate");
    }
    ++c.exact_comparisons;
    return;
  }
  if (q.query != "intersection") validation_failure("RESULT_SET_INCOMPLETE", w + " query");
  if (!result.is_object() || !result.contains("type") || result.at("type") != e.type) {
    validation_failure("INTERSECTION_MISMATCH", w + " result type differs from exact type " + e.type);
  }
  ++c.exact_comparisons;
  const bool two_d = x->dimension == 2;
  if (e.type == "empty") {
    require_keys(result, {"type"}, w);
  } else if (e.type == "point") {
    require_keys(result, {"type", "point"}, w);
    if (two_d) c.construction2(result.at("point"), e.points2[0], 1, w);
    else c.construction3(result.at("point"), e.points3[0], 1, w);
  } else if (e.type == "line" && two_d) {
    require_keys(result, {"type", "coefficients"}, w);
    check_line2_through(c, result.at("coefficients"), e.points2[0], e.points2[1], false, w);
  } else if (e.type == "line") {
    require_keys(result, {"type", "points"}, w);
    const auto& pts = result.at("points");
    if (!pts.is_array() || pts.size() != 2) validation_failure("REPORT_VALUE_INVALID", w);
    const V3 r0 = Checker::reported3(pts[0], w), r1 = Checker::reported3(pts[1], w);
    if (same(r0, r1)) validation_failure("INTERSECTION_MISMATCH", w + " line points coincide");
    for (const auto& r : {r0, r1}) {
      bool inside = true;
      if (pair == "Plane_3|Plane_3") {
        inside = on_plane(c, r, P3(x, 0), normal(x)) && on_plane(c, r, P3(y, 0), normal(y));
      } else {
        inside = on_line3(c, r, P3(x, 0), P3(x, 1) - P3(x, 0)) &&
                 (pair == "Line_3|Plane_3" ? on_plane(c, r, P3(y, 0), normal(y))
                                           : on_line3(c, r, P3(y, 0), P3(y, 1) - P3(y, 0)));
      }
      if (!inside) validation_failure("INTERSECTION_MISMATCH", w + " line point is not on both primitives");
    }
  } else if (e.type == "plane") {
    require_keys(result, {"type", "coefficients"}, w);
    const auto& co = result.at("coefficients");
    if (!co.is_array() || co.size() != 4) validation_failure("REPORT_VALUE_INVALID", w);
    const V3 n{Checker::reported(co[0], w), Checker::reported(co[1], w), Checker::reported(co[2], w)};
    const Q d = Checker::reported(co[3], w);
    if (is_zero(n)) validation_failure("INTERSECTION_MISMATCH", w + " plane has a zero normal");
    for (const auto& point : e.points3) {
      const Q residual = dot(n, point) + d;
      const Q magnitude = abs(n.x * point.x) + abs(n.y * point.y) + abs(n.z * point.z) + abs(d);
      if (!c.vanishes(residual, magnitude)) validation_failure("INTERSECTION_MISMATCH", w + " plane differs");
    }
  } else {
    require_keys(result, {"type", "points"}, w);
    if (two_d) match_points2(c, result.at("points"), e.points2, w);
    else match_points3(c, result.at("points"), e.points3, w);
  }
}

Json validate_intersections(const Request& request) {
  auto context = load(request, "intersections", "kernel.validate.intersections_report", false);
  Json checks = Json::object();
  const auto frame = check_frame(request, context.report, "intersections", context.kernel,
                                 "kernel.intersections.compute", checks);
  if (!frame.primitives.empty()) validation_failure("REPORT_SCHEMA_MISMATCH", "Intersection reports list no primitives");
  Checker checker(context.kernel, context.set);
  if (context.set.queries.empty()) validation_failure("RESULT_SET_INCOMPLETE", "Source has no queries");
  check_query_identity(context.set, frame.queries);
  for (std::size_t i = 0; i < frame.queries.size(); ++i) {
    check_intersection_query(checker, context.set.queries[i], frame.queries[i].at("result"));
  }
  checks["intersection_types_match"] = true;
  checks["intersection_geometry_matches"] = true;
  return finish(request, "kernel.validate.intersections_report", "kernel.intersections.compute", checker,
                std::move(checks));
}

// ---- squared distances -------------------------------------------------------------

template <class V>
Q point_segment(const V& p, const V& a, const V& b) {
  const V d = b - a;
  Q t = dot(p - a, d) / dot(d, d);
  if (t < 0) t = 0;
  if (t > 1) t = 1;
  const V r = p - (a + t * d);
  return dot(r, r);
}

template <class V>
Q point_line(const V& p, const V& a, const V& b) {
  const V d = b - a;
  const Q along = dot(p - a, d);
  return dot(p - a, p - a) - along * along / dot(d, d);
}

Q segment_segment2_distance(const V2& a, const V2& b, const V2& p, const V2& q) {
  if (segment_segment2(a, b, p, q).type != "empty") return 0;
  return std::min({point_segment(a, p, q), point_segment(b, p, q), point_segment(p, a, b), point_segment(q, a, b)});
}

Q point_triangle3(const V3& p, const V3& a, const V3& b, const V3& c) {
  const V3 n = cross(b - a, c - a);
  const Q offset = dot(p - a, n) / dot(n, n);
  const V3 x = p - offset * n;
  const std::array<V3, 3> v{a, b, c};
  bool inside = true;
  for (int i = 0; i < 3; ++i) inside = inside && dot(n, cross(v[(i + 1) % 3] - v[i], x - v[i])) >= 0;
  if (inside) return offset * offset * dot(n, n);
  return std::min({point_segment(p, a, b), point_segment(p, b, c), point_segment(p, c, a)});
}

Q segment_segment3(const V3& a, const V3& b, const V3& c, const V3& d) {
  Q best = std::min({point_segment(a, c, d), point_segment(b, c, d), point_segment(c, a, b), point_segment(d, a, b)});
  const V3 d1 = b - a, d2 = d - c, r = a - c;
  const Q A = dot(d1, d1), B = dot(d1, d2), C = dot(d1, r), E = dot(d2, d2), F = dot(d2, r);
  const Q den = A * E - B * B;
  if (den != 0) {
    const Q s = (B * F - C * E) / den, t = (A * F - B * C) / den;
    if (s >= 0 && s <= 1 && t >= 0 && t <= 1) {
      const V3 gap = r + s * d1 - t * d2;
      best = std::min(best, dot(gap, gap));
    }
  }
  return best;
}

Q line_line3_distance(const V3& a, const V3& b, const V3& c, const V3& d) {
  const V3 n = cross(b - a, d - c);
  if (is_zero(n)) return point_line(c, a, b);
  const Q along = dot(c - a, n);
  return along * along / dot(n, n);
}

void check_distance_query(Checker& c, const Query& q, const Json& result) {
  const std::string w = "query " + q.id;
  if (q.query == "compare_distance" || q.query == "compare_distance_to_point") {
    if (q.arguments.size() != 3) validation_failure("RESULT_SET_INCOMPLETE", w);
    const auto& p = c.set().at(q.arguments[0]);
    const auto& a = c.set().at(q.arguments[1]);
    const auto& b = c.set().at(q.arguments[2]);
    Q difference;
    if (p.kind == "Point_2" && a.kind == "Point_2" && b.kind == "Point_2") {
      const V2 x = c.p2(p.points[0]);
      difference = dot(c.p2(a.points[0]) - x, c.p2(a.points[0]) - x) - dot(c.p2(b.points[0]) - x, c.p2(b.points[0]) - x);
    } else if (p.kind == "Point_3" && a.kind == "Point_3" && b.kind == "Point_3") {
      const V3 x = c.p3(p.points[0]);
      difference = dot(c.p3(a.points[0]) - x, c.p3(a.points[0]) - x) - dot(c.p3(b.points[0]) - x, c.p3(b.points[0]) - x);
    } else {
      validation_failure("RESULT_SET_INCOMPLETE", w + " arguments");
    }
    const char* expected = difference < 0 ? "smaller" : (difference > 0 ? "larger" : "equal");
    c.predicate(result == expected, difference, 2, w);
    return;
  }
  if (q.query != "squared_distance" || q.arguments.size() != 2) validation_failure("RESULT_SET_INCOMPLETE", w);
  const auto& x = c.set().at(q.arguments[0]);
  const auto& y = c.set().at(q.arguments[1]);
  auto P2 = [&](const Primitive& p, int i) { return c.p2(p.points[i]); };
  auto P3 = [&](const Primitive& p, int i) { return c.p3(p.points[i]); };
  const auto pair = x.kind + "|" + y.kind;
  Q expected;
  if (pair == "Point_2|Point_2") expected = dot(P2(x, 0) - P2(y, 0), P2(x, 0) - P2(y, 0));
  else if (pair == "Point_2|Line_2") expected = point_line(P2(x, 0), P2(y, 0), P2(y, 1));
  else if (pair == "Point_2|Segment_2") expected = point_segment(P2(x, 0), P2(y, 0), P2(y, 1));
  else if (pair == "Segment_2|Segment_2") expected = segment_segment2_distance(P2(x, 0), P2(x, 1), P2(y, 0), P2(y, 1));
  else if (pair == "Point_3|Point_3") expected = dot(P3(x, 0) - P3(y, 0), P3(x, 0) - P3(y, 0));
  else if (pair == "Point_3|Line_3") expected = point_line(P3(x, 0), P3(y, 0), P3(y, 1));
  else if (pair == "Point_3|Segment_3") expected = point_segment(P3(x, 0), P3(y, 0), P3(y, 1));
  else if (pair == "Point_3|Plane_3") {
    const V3 n = cross(P3(y, 1) - P3(y, 0), P3(y, 2) - P3(y, 0));
    const Q along = dot(P3(x, 0) - P3(y, 0), n);
    expected = along * along / dot(n, n);
  } else if (pair == "Point_3|Triangle_3") expected = point_triangle3(P3(x, 0), P3(y, 0), P3(y, 1), P3(y, 2));
  else if (pair == "Segment_3|Segment_3") expected = segment_segment3(P3(x, 0), P3(x, 1), P3(y, 0), P3(y, 1));
  else if (pair == "Line_3|Line_3") expected = line_line3_distance(P3(x, 0), P3(x, 1), P3(y, 0), P3(y, 1));
  else validation_failure("RESULT_SET_INCOMPLETE", w + " pair is not supported: " + pair);
  c.construction(Checker::reported(result, w), expected, 2, w);
}

Json validate_distances(const Request& request) {
  auto context = load(request, "distances", "kernel.validate.distances_report", true);
  Json checks = Json::object();
  const auto frame = check_frame(request, context.report, "distances", context.kernel,
                                 "kernel.distance.squared", checks);
  if (!frame.primitives.empty()) validation_failure("REPORT_SCHEMA_MISMATCH", "Distance reports list no primitives");
  Checker checker(context.kernel, context.set);
  if (context.set.queries.empty()) validation_failure("RESULT_SET_INCOMPLETE", "Source has no queries");
  check_query_identity(context.set, frame.queries);
  for (std::size_t i = 0; i < frame.queries.size(); ++i) {
    check_distance_query(checker, context.set.queries[i], frame.queries[i].at("result"));
  }
  checks["squared_distances_match"] = true;
  checks["distance_comparisons_match"] = true;
  return finish(request, "kernel.validate.distances_report", "kernel.distance.squared", checker,
                std::move(checks));
}

Json validator_info(const std::vector<std::string>& checks) {
  return Json{{"checks", checks}, {"input_slots", Json::array({"candidate", "source"})},
              {"output_slot", "validation"}, {"independence", "GMP rationals; no CGAL kernel functor"}};
}

}  // namespace

std::vector<OperationDefinition> validator_operations() {
  const std::vector<std::string> common = {"kernel_matches", "source_matches", "result_set_complete"};
  auto with = [&](std::vector<std::string> extra) {
    auto all = common;
    all.insert(all.end(), extra.begin(), extra.end());
    return validator_info(all);
  };
  auto primitives = kernel_definition("kernel.validate.primitives_report", {"KernelReport", "KernelQuerySet"},
                                      "ValidationReport", "validator", validate_primitives,
                                      with({"primitive_properties_match", "transformations_match"}));
  auto predicates = kernel_definition("kernel.validate.predicates_report", {"KernelReport", "KernelQuerySet"},
                                      "ValidationReport", "validator", validate_predicates,
                                      with({"predicates_match", "constructions_match"}));
  auto intersections = kernel_definition(
      "kernel.validate.intersections_report", {"KernelReport", "KernelQuerySet"}, "ValidationReport",
      "validator", validate_intersections, with({"intersection_types_match", "intersection_geometry_matches"}));
  intersections.dependencies = {"Kernel_23", "Intersections_2", "Intersections_3"};
  auto distances = kernel_definition("kernel.validate.distances_report", {"KernelReport", "KernelQuerySet"},
                                     "ValidationReport", "validator", validate_distances,
                                     with({"squared_distances_match", "distance_comparisons_match"}));
  distances.dependencies = {"Kernel_23", "Distance_2", "Distance_3"};
  return {primitives, predicates, intersections, distances};
}

}  // namespace cgal_master::kernel_ops
