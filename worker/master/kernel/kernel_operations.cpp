// Geometry kernel family (7.1): CGAL Kernel_23 primitives, predicates,
// constructions, intersections and squared distances evaluated in a kernel
// chosen by parameter (Simple_cartesian<double>, Cartesian<double>, EPICK,
// EPECK). Every result is checked by an independent GMP-rational validator in
// kernel_validators.cpp that never calls a CGAL kernel functor.

#include "kernel_query_set.h"

#include <CGAL/Cartesian.h>
#include <CGAL/Exact_predicates_exact_constructions_kernel.h>
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Simple_cartesian.h>
#include <CGAL/intersections.h>
#include <CGAL/squared_distance_2.h>
#include <CGAL/squared_distance_3.h>

#include <gmp.h>

#include <cstring>
#include <optional>
#include <sstream>
#include <type_traits>
#include <variant>

namespace cgal_master::kernel_ops {
namespace {

using SC = CGAL::Simple_cartesian<double>;
using CC = CGAL::Cartesian<double>;
using Epick = CGAL::Exact_predicates_inexact_constructions_kernel;
using Epeck = CGAL::Exact_predicates_exact_constructions_kernel;

// ---- exact text of a computed scalar ---------------------------------------

std::string canonical_from(mpq_t value) {
  mpq_canonicalize(value);
  char* text = mpq_get_str(nullptr, 10, value);
  std::string result(text);
  void (*release)(void*, std::size_t) = nullptr;
  mp_get_memory_functions(nullptr, nullptr, &release);
  release(text, std::strlen(text) + 1);
  return result;
}

std::string exact_text(double value) {
  if (!std::isfinite(value)) {
    precondition("NONFINITE_RESULT", "A computed value is not finite in the selected kernel");
  }
  mpq_t q;
  mpq_init(q);
  mpq_set_d(q, value);  // exact: every finite binary64 is a dyadic rational
  auto result = canonical_from(q);
  mpq_clear(q);
  return result;
}

std::string exact_text(const Epeck::FT& value) {
  std::ostringstream stream;
  stream << CGAL::exact(value);
  mpq_t q;
  mpq_init(q);
  if (mpq_set_str(q, stream.str().c_str(), 10) != 0) {
    mpq_clear(q);
    throw WorkerError("INTERNAL_ERROR", "EXACT_FORMAT", "Exact value could not be formatted");
  }
  auto result = canonical_from(q);
  mpq_clear(q);
  return result;
}

template <class P>
Json coords2(const P& p) { return Json::array({exact_text(p.x()), exact_text(p.y())}); }

template <class P>
Json coords3(const P& p) {
  return Json::array({exact_text(p.x()), exact_text(p.y()), exact_text(p.z())});
}

// ---- inputs -----------------------------------------------------------------

template <class K>
typename K::FT number(const Rational& r) {
  return typename K::FT(static_cast<double>(r.numerator)) /
         typename K::FT(static_cast<double>(r.denominator));
}

template <class K>
typename K::Point_2 point2(const Coordinates& c) { return {number<K>(c[0]), number<K>(c[1])}; }

template <class K>
typename K::Point_3 point3(const Coordinates& c) {
  return {number<K>(c[0]), number<K>(c[1]), number<K>(c[2])};
}

const char* sign_name(CGAL::Sign sign) {
  return sign == CGAL::POSITIVE ? "positive" : (sign == CGAL::NEGATIVE ? "negative" : "zero");
}

const char* turn_name(CGAL::Orientation o) {
  return o == CGAL::LEFT_TURN ? "left_turn" : (o == CGAL::RIGHT_TURN ? "right_turn" : "collinear");
}

const char* space_name(CGAL::Orientation o) {
  return o == CGAL::POSITIVE ? "positive" : (o == CGAL::NEGATIVE ? "negative" : "coplanar");
}

const char* comparison_name(CGAL::Comparison_result c) {
  return c == CGAL::SMALLER ? "smaller" : (c == CGAL::LARGER ? "larger" : "equal");
}

// Degeneracy decided by exact predicates on the kernel's own input values:
// EPICK on the binary64-rounded inputs, EPECK on the exact rationals.
template <class K>
bool degenerate_in(const Primitive& p) {
  const auto& k = p.kind;
  if (k == "Segment_2" || k == "Line_2" || k == "Ray_2" || k == "Iso_rectangle_2") {
    const auto a = point2<K>(p.points[0]), b = point2<K>(p.points[1]);
    if (k == "Iso_rectangle_2") return a.x() == b.x() || a.y() == b.y();
    return a == b;
  }
  if (k == "Segment_3" || k == "Line_3" || k == "Ray_3" || k == "Iso_cuboid_3") {
    const auto a = point3<K>(p.points[0]), b = point3<K>(p.points[1]);
    if (k == "Iso_cuboid_3") return a.x() == b.x() || a.y() == b.y() || a.z() == b.z();
    return a == b;
  }
  if (k == "Triangle_2") {
    return CGAL::collinear(point2<K>(p.points[0]), point2<K>(p.points[1]), point2<K>(p.points[2]));
  }
  if (k == "Triangle_3" || k == "Plane_3") {
    return CGAL::collinear(point3<K>(p.points[0]), point3<K>(p.points[1]), point3<K>(p.points[2]));
  }
  if (k == "Tetrahedron_3") {
    return CGAL::coplanar(point3<K>(p.points[0]), point3<K>(p.points[1]), point3<K>(p.points[2]),
                          point3<K>(p.points[3]));
  }
  return false;
}

bool exactly_degenerate(const Primitive& p, const std::string& kernel) {
  return kernel_uses_double_input(kernel) ? degenerate_in<Epick>(p) : degenerate_in<Epeck>(p);
}

void require_nondegenerate(const QuerySet& set, const Query& query, const std::string& kernel) {
  for (const auto& name : query.arguments) {
    if (exactly_degenerate(set.at(name), kernel)) {
      precondition("DEGENERATE_PRIMITIVE", "Query " + query.id + " uses degenerate primitive " + name);
    }
  }
}

// ---- report frame -----------------------------------------------------------

Json report_frame(const Request& request, const std::string& kind, const std::string& kernel,
                  Json primitives, Json queries) {
  return Json{{"schema_version", 1},
              {"report_type", "KernelReport"},
              {"report_kind", kind},
              {"operation", request.operation},
              {"kernel", kernel},
              {"kernel_type", kernel_type_name(kernel)},
              {"exact_predicates", kernel_has_exact_predicates(kernel)},
              {"exact_constructions", kernel_has_exact_constructions(kernel)},
              {"input_representation",
               kernel_uses_double_input(kernel) ? "binary64_round_to_nearest" : "exact_rational"},
              {"source", {{"sha256", request.inputs[0].sha256}, {"unit", request.inputs[0].unit}}},
              {"length_unit", request.inputs[0].unit},
              {"results", {{"primitives", std::move(primitives)}, {"queries", std::move(queries)}}}};
}

Json finish(const Request& request, const std::string& kernel, const QuerySet& set,
            const Json& report, const std::string& algorithm) {
  auto output = write_report(request, report);
  Json metrics{{"kernel", kernel},
               {"kernel_type", kernel_type_name(kernel)},
               {"exact_predicates", kernel_has_exact_predicates(kernel)},
               {"exact_constructions", kernel_has_exact_constructions(kernel)},
               {"primitive_count", set.primitives.size()},
               {"query_count", set.queries.size()},
               {"algorithm", algorithm}};
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
}

template <class F>
Json with_kernel(const std::string& kernel, F&& body) {
  if (kernel == kSimpleCartesian) return body(SC{});
  if (kernel == kCartesian) return body(CC{});
  if (kernel == kEpick) return body(Epick{});
  return body(Epeck{});
}

Json query_entry(const Query& query, Json result) {
  return Json{{"id", query.id}, {"query", query.query}, {"arguments", query.arguments},
              {"result", std::move(result)}};
}

// ---- primitives (7.1.02) ----------------------------------------------------

template <class K>
Json describe(const Primitive& p) {
  Json out{{"id", p.id}, {"kind", p.kind}};
  const auto& k = p.kind;
  const auto& pts = p.points;
  if (k == "Point_2") {
    out["coordinates"] = coords2(point2<K>(pts[0]));
  } else if (k == "Vector_2") {
    typename K::Vector_2 v(number<K>(pts[0][0]), number<K>(pts[0][1]));
    out["coordinates"] = coords2(v);
    out["squared_length"] = exact_text(v.squared_length());
  } else if (k == "Segment_2") {
    typename K::Segment_2 s(point2<K>(pts[0]), point2<K>(pts[1]));
    out["source"] = coords2(s.source());
    out["target"] = coords2(s.target());
    out["squared_length"] = exact_text(s.squared_length());
    out["degenerate"] = s.is_degenerate();
  } else if (k == "Line_2") {
    typename K::Line_2 l(point2<K>(pts[0]), point2<K>(pts[1]));
    out["coefficients"] = Json::array({exact_text(l.a()), exact_text(l.b()), exact_text(l.c())});
    out["degenerate"] = l.is_degenerate();
  } else if (k == "Ray_2") {
    typename K::Ray_2 r(point2<K>(pts[0]), point2<K>(pts[1]));
    out["source"] = coords2(r.source());
    out["direction_vector"] = coords2(r.to_vector());
    out["degenerate"] = r.is_degenerate();
  } else if (k == "Triangle_2") {
    typename K::Triangle_2 t(point2<K>(pts[0]), point2<K>(pts[1]), point2<K>(pts[2]));
    out["vertices"] = Json::array({coords2(t.vertex(0)), coords2(t.vertex(1)), coords2(t.vertex(2))});
    out["signed_area"] = exact_text(t.area());
    out["orientation"] = sign_name(t.orientation());
    out["degenerate"] = t.is_degenerate();
  } else if (k == "Circle_2") {
    typename K::Circle_2 c(point2<K>(pts[0]), number<K>(p.squared_radius));
    out["center"] = coords2(c.center());
    out["squared_radius"] = exact_text(c.squared_radius());
    out["orientation"] = sign_name(c.orientation());
    out["degenerate"] = c.is_degenerate();
  } else if (k == "Iso_rectangle_2") {
    typename K::Iso_rectangle_2 r(point2<K>(pts[0]), point2<K>(pts[1]));
    out["min"] = coords2(r.min());
    out["max"] = coords2(r.max());
    out["area"] = exact_text(r.area());
    out["degenerate"] = r.is_degenerate();
  } else if (k == "Aff_transformation_2") {
    const auto& m = p.matrix;
    typename K::Aff_transformation_2 t(number<K>(m[0][0]), number<K>(m[0][1]), number<K>(m[0][2]),
                                       number<K>(m[1][0]), number<K>(m[1][1]), number<K>(m[1][2]));
    Json rows = Json::array();
    for (int i = 0; i < 2; ++i) {
      Json row = Json::array();
      for (int j = 0; j < 3; ++j) row.push_back(exact_text(t.m(i, j)));
      rows.push_back(row);
    }
    out["matrix"] = rows;
    out["is_even"] = t.is_even();
  } else if (k == "Point_3") {
    out["coordinates"] = coords3(point3<K>(pts[0]));
  } else if (k == "Vector_3") {
    typename K::Vector_3 v(number<K>(pts[0][0]), number<K>(pts[0][1]), number<K>(pts[0][2]));
    out["coordinates"] = coords3(v);
    out["squared_length"] = exact_text(v.squared_length());
  } else if (k == "Segment_3") {
    typename K::Segment_3 s(point3<K>(pts[0]), point3<K>(pts[1]));
    out["source"] = coords3(s.source());
    out["target"] = coords3(s.target());
    out["squared_length"] = exact_text(s.squared_length());
    out["degenerate"] = s.is_degenerate();
  } else if (k == "Line_3") {
    typename K::Line_3 l(point3<K>(pts[0]), point3<K>(pts[1]));
    out["point"] = coords3(l.point());
    out["direction_vector"] = coords3(l.to_vector());
    out["degenerate"] = l.is_degenerate();
  } else if (k == "Ray_3") {
    typename K::Ray_3 r(point3<K>(pts[0]), point3<K>(pts[1]));
    out["source"] = coords3(r.source());
    out["direction_vector"] = coords3(r.to_vector());
    out["degenerate"] = r.is_degenerate();
  } else if (k == "Plane_3") {
    typename K::Plane_3 h(point3<K>(pts[0]), point3<K>(pts[1]), point3<K>(pts[2]));
    out["coefficients"] = Json::array({exact_text(h.a()), exact_text(h.b()), exact_text(h.c()),
                                       exact_text(h.d())});
    out["degenerate"] = h.is_degenerate();
  } else if (k == "Triangle_3") {
    typename K::Triangle_3 t(point3<K>(pts[0]), point3<K>(pts[1]), point3<K>(pts[2]));
    out["vertices"] = Json::array({coords3(t.vertex(0)), coords3(t.vertex(1)), coords3(t.vertex(2))});
    out["squared_area"] = exact_text(t.squared_area());
    out["degenerate"] = t.is_degenerate();
  } else if (k == "Tetrahedron_3") {
    typename K::Tetrahedron_3 t(point3<K>(pts[0]), point3<K>(pts[1]), point3<K>(pts[2]),
                                point3<K>(pts[3]));
    out["vertices"] = Json::array({coords3(t.vertex(0)), coords3(t.vertex(1)), coords3(t.vertex(2)),
                                   coords3(t.vertex(3))});
    out["signed_volume"] = exact_text(t.volume());
    out["orientation"] = sign_name(t.orientation());
    out["degenerate"] = t.is_degenerate();
  } else if (k == "Sphere_3") {
    typename K::Sphere_3 s(point3<K>(pts[0]), number<K>(p.squared_radius));
    out["center"] = coords3(s.center());
    out["squared_radius"] = exact_text(s.squared_radius());
    out["orientation"] = sign_name(s.orientation());
    out["degenerate"] = s.is_degenerate();
  } else if (k == "Iso_cuboid_3") {
    typename K::Iso_cuboid_3 c(point3<K>(pts[0]), point3<K>(pts[1]));
    out["min"] = coords3(c.min());
    out["max"] = coords3(c.max());
    out["volume"] = exact_text(c.volume());
    out["degenerate"] = c.is_degenerate();
  } else if (k == "Aff_transformation_3") {
    const auto& m = p.matrix;
    typename K::Aff_transformation_3 t(
        number<K>(m[0][0]), number<K>(m[0][1]), number<K>(m[0][2]), number<K>(m[0][3]),
        number<K>(m[1][0]), number<K>(m[1][1]), number<K>(m[1][2]), number<K>(m[1][3]),
        number<K>(m[2][0]), number<K>(m[2][1]), number<K>(m[2][2]), number<K>(m[2][3]));
    Json rows = Json::array();
    for (int i = 0; i < 3; ++i) {
      Json row = Json::array();
      for (int j = 0; j < 4; ++j) row.push_back(exact_text(t.m(i, j)));
      rows.push_back(row);
    }
    out["matrix"] = rows;
    out["is_even"] = t.is_even();
  }
  return out;
}

template <class K>
Json apply_transformation(const QuerySet& set, const Query& query) {
  if (query.arguments.size() != 2) precondition("ARGUMENT_MISMATCH", "transform needs [transformation, object]");
  const auto& t = set.at(query.arguments[0]);
  const auto& x = set.at(query.arguments[1]);
  const auto& m = t.matrix;
  if (t.kind == "Aff_transformation_2" && (x.kind == "Point_2" || x.kind == "Vector_2")) {
    typename K::Aff_transformation_2 a(number<K>(m[0][0]), number<K>(m[0][1]), number<K>(m[0][2]),
                                       number<K>(m[1][0]), number<K>(m[1][1]), number<K>(m[1][2]));
    if (x.kind == "Point_2") return Json{{"kind", "Point_2"}, {"coordinates", coords2(a(point2<K>(x.points[0])))}};
    typename K::Vector_2 v(number<K>(x.points[0][0]), number<K>(x.points[0][1]));
    return Json{{"kind", "Vector_2"}, {"coordinates", coords2(a(v))}};
  }
  if (t.kind == "Aff_transformation_3" && (x.kind == "Point_3" || x.kind == "Vector_3")) {
    typename K::Aff_transformation_3 a(
        number<K>(m[0][0]), number<K>(m[0][1]), number<K>(m[0][2]), number<K>(m[0][3]),
        number<K>(m[1][0]), number<K>(m[1][1]), number<K>(m[1][2]), number<K>(m[1][3]),
        number<K>(m[2][0]), number<K>(m[2][1]), number<K>(m[2][2]), number<K>(m[2][3]));
    if (x.kind == "Point_3") return Json{{"kind", "Point_3"}, {"coordinates", coords3(a(point3<K>(x.points[0])))}};
    typename K::Vector_3 v(number<K>(x.points[0][0]), number<K>(x.points[0][1]), number<K>(x.points[0][2]));
    return Json{{"kind", "Vector_3"}, {"coordinates", coords3(a(v))}};
  }
  precondition("ARGUMENT_MISMATCH", "transform needs an Aff_transformation and a point/vector of its dimension");
}

Json construct_primitives(const Request& request) {
  require_inputs(request, 1, "kernel.primitives.construct");
  const auto kernel = kernel_parameter(request, true);
  const auto set = read_query_set(request.inputs[0]);
  for (const auto& query : set.queries) {
    if (query.query != "transform") precondition("UNSUPPORTED_QUERY", "Unsupported query " + query.query);
  }
  return with_kernel(kernel, [&](auto tag) {
    using K = decltype(tag);
    Json primitives = Json::array();
    for (const auto& primitive : set.primitives) primitives.push_back(describe<K>(primitive));
    Json queries = Json::array();
    for (const auto& query : set.queries) {
      queries.push_back(query_entry(query, apply_transformation<K>(set, query)));
    }
    return finish(request, kernel, set,
                  report_frame(request, "primitives", kernel, std::move(primitives), std::move(queries)),
                  "CGAL Kernel_23 primitive constructors and Aff_transformation_2/3");
  });
}

// ---- predicates / constructions (7.1.01, 7.1.03) ------------------------------

int point_dimension(const QuerySet& set, const Query& query) {
  int dimension = 0;
  for (const auto& name : query.arguments) {
    const auto& p = set.at(name);
    const int d = p.kind == "Point_2" ? 2 : (p.kind == "Point_3" ? 3 : 0);
    if (d == 0 || (dimension != 0 && d != dimension)) {
      precondition("ARGUMENT_MISMATCH", "Query " + query.id + " needs points of one dimension");
    }
    dimension = d;
  }
  return dimension;
}

template <class K>
bool exact_collinear_inputs(const QuerySet& set, const Query& q, int dimension) {
  if (dimension == 2) {
    return CGAL::collinear(point2<K>(set.at(q.arguments[0]).points[0]),
                           point2<K>(set.at(q.arguments[1]).points[0]),
                           point2<K>(set.at(q.arguments[2]).points[0]));
  }
  return CGAL::collinear(point3<K>(set.at(q.arguments[0]).points[0]),
                         point3<K>(set.at(q.arguments[1]).points[0]),
                         point3<K>(set.at(q.arguments[2]).points[0]));
}

template <class K>
bool exact_coplanar_inputs(const QuerySet& set, const Query& q) {
  return CGAL::coplanar(point3<K>(set.at(q.arguments[0]).points[0]),
                        point3<K>(set.at(q.arguments[1]).points[0]),
                        point3<K>(set.at(q.arguments[2]).points[0]),
                        point3<K>(set.at(q.arguments[3]).points[0]));
}

template <class K>
Json evaluate_predicate(const QuerySet& set, const Query& q, const std::string& kernel) {
  const int d = point_dimension(set, q);
  const auto n = q.arguments.size();
  auto p2 = [&](std::size_t i) { return point2<K>(set.at(q.arguments[i]).points[0]); };
  auto p3 = [&](std::size_t i) { return point3<K>(set.at(q.arguments[i]).points[0]); };
  const auto& name = q.query;
  if (name == "orientation") {
    if (d == 2 && n == 3) return turn_name(CGAL::orientation(p2(0), p2(1), p2(2)));
    if (d == 3 && n == 4) return space_name(CGAL::orientation(p3(0), p3(1), p3(2), p3(3)));
  } else if (name == "collinear" && n == 3) {
    return d == 2 ? CGAL::collinear(p2(0), p2(1), p2(2)) : CGAL::collinear(p3(0), p3(1), p3(2));
  } else if (name == "coplanar" && d == 3 && n == 4) {
    return CGAL::coplanar(p3(0), p3(1), p3(2), p3(3));
  } else if (name == "left_turn" && d == 2 && n == 3) {
    return CGAL::left_turn(p2(0), p2(1), p2(2));
  } else if (name == "right_turn" && d == 2 && n == 3) {
    return CGAL::right_turn(p2(0), p2(1), p2(2));
  } else if (name == "midpoint" && n == 2) {
    return d == 2 ? coords2(CGAL::midpoint(p2(0), p2(1))) : coords3(CGAL::midpoint(p3(0), p3(1)));
  } else if (name == "centroid" && (n == 3 || n == 4)) {
    if (d == 2) {
      return n == 3 ? coords2(CGAL::centroid(p2(0), p2(1), p2(2)))
                    : coords2(CGAL::centroid(p2(0), p2(1), p2(2), p2(3)));
    }
    return n == 3 ? coords3(CGAL::centroid(p3(0), p3(1), p3(2)))
                  : coords3(CGAL::centroid(p3(0), p3(1), p3(2), p3(3)));
  } else if (name == "circumcenter" && (n == 3 || (n == 4 && d == 3))) {
    const bool degenerate =
        n == 4 ? (kernel_uses_double_input(kernel) ? exact_coplanar_inputs<Epick>(set, q)
                                                   : exact_coplanar_inputs<Epeck>(set, q))
               : (kernel_uses_double_input(kernel) ? exact_collinear_inputs<Epick>(set, q, d)
                                                   : exact_collinear_inputs<Epeck>(set, q, d));
    if (degenerate) {
      precondition("DEGENERATE_CONFIGURATION", "circumcenter needs affinely independent points: " + q.id);
    }
    if (d == 2) return coords2(CGAL::circumcenter(p2(0), p2(1), p2(2)));
    return n == 3 ? coords3(CGAL::circumcenter(p3(0), p3(1), p3(2)))
                  : coords3(CGAL::circumcenter(p3(0), p3(1), p3(2), p3(3)));
  }
  precondition("UNSUPPORTED_QUERY", "Unsupported predicate/construction or arity: " + q.id);
}

Json evaluate_predicates(const Request& request) {
  require_inputs(request, 1, "kernel.predicates.evaluate");
  const auto kernel = kernel_parameter(request, true);
  const auto set = read_query_set(request.inputs[0]);
  if (set.queries.empty()) precondition("NO_QUERIES", "KernelQuerySet has no queries");
  return with_kernel(kernel, [&](auto tag) {
    using K = decltype(tag);
    Json queries = Json::array();
    for (const auto& query : set.queries) {
      queries.push_back(query_entry(query, evaluate_predicate<K>(set, query, kernel)));
    }
    return finish(request, kernel, set,
                  report_frame(request, "predicates", kernel, Json::array(), std::move(queries)),
                  "CGAL Kernel_23 global predicates and constructions");
  });
}

// ---- intersections (7.1.04) -------------------------------------------------

template <class K>
struct Describer {
  Json operator()(const typename K::Point_2& p) const { return {{"type", "point"}, {"point", coords2(p)}}; }
  Json operator()(const typename K::Point_3& p) const { return {{"type", "point"}, {"point", coords3(p)}}; }
  Json operator()(const typename K::Segment_2& s) const {
    return {{"type", "segment"}, {"points", Json::array({coords2(s.source()), coords2(s.target())})}};
  }
  Json operator()(const typename K::Segment_3& s) const {
    return {{"type", "segment"}, {"points", Json::array({coords3(s.source()), coords3(s.target())})}};
  }
  Json operator()(const typename K::Line_2& l) const {
    return {{"type", "line"},
            {"coefficients", Json::array({exact_text(l.a()), exact_text(l.b()), exact_text(l.c())})}};
  }
  Json operator()(const typename K::Line_3& l) const {
    return {{"type", "line"}, {"points", Json::array({coords3(l.point(0)), coords3(l.point(1))})}};
  }
  Json operator()(const typename K::Plane_3& h) const {
    return {{"type", "plane"},
            {"coefficients", Json::array({exact_text(h.a()), exact_text(h.b()), exact_text(h.c()),
                                          exact_text(h.d())})}};
  }
  Json operator()(const typename K::Triangle_2& t) const {
    return {{"type", "triangle"},
            {"points", Json::array({coords2(t.vertex(0)), coords2(t.vertex(1)), coords2(t.vertex(2))})}};
  }
  Json operator()(const typename K::Triangle_3& t) const {
    return {{"type", "triangle"},
            {"points", Json::array({coords3(t.vertex(0)), coords3(t.vertex(1)), coords3(t.vertex(2))})}};
  }
  Json operator()(const std::vector<typename K::Point_2>& points) const {
    Json out = Json::array();
    for (const auto& p : points) out.push_back(coords2(p));
    return {{"type", "polygon"}, {"points", out}};
  }
  Json operator()(const std::vector<typename K::Point_3>& points) const {
    Json out = Json::array();
    for (const auto& p : points) out.push_back(coords3(p));
    return {{"type", "polygon"}, {"points", out}};
  }
};

template <class K, class A, class B>
Json intersect(const A& a, const B& b, bool predicate_only) {
  if (predicate_only) return CGAL::do_intersect(a, b);
  const auto result = CGAL::intersection(a, b);
  if (!result) return Json{{"type", "empty"}};
  return std::visit(Describer<K>{}, *result);
}

template <class K>
Json evaluate_intersection(const QuerySet& set, const Query& q) {
  const bool predicate_only = q.query == "do_intersect";
  if ((!predicate_only && q.query != "intersection") || q.arguments.size() != 2) {
    precondition("UNSUPPORTED_QUERY", "Unsupported intersection query or arity: " + q.id);
  }
  const auto& x = set.at(q.arguments[0]);
  const auto& y = set.at(q.arguments[1]);
  auto seg2 = [](const Primitive& p) { return typename K::Segment_2(point2<K>(p.points[0]), point2<K>(p.points[1])); };
  auto line2 = [](const Primitive& p) { return typename K::Line_2(point2<K>(p.points[0]), point2<K>(p.points[1])); };
  auto tri2 = [](const Primitive& p) {
    return typename K::Triangle_2(point2<K>(p.points[0]), point2<K>(p.points[1]), point2<K>(p.points[2]));
  };
  auto seg3 = [](const Primitive& p) { return typename K::Segment_3(point3<K>(p.points[0]), point3<K>(p.points[1])); };
  auto line3 = [](const Primitive& p) { return typename K::Line_3(point3<K>(p.points[0]), point3<K>(p.points[1])); };
  auto ray3 = [](const Primitive& p) { return typename K::Ray_3(point3<K>(p.points[0]), point3<K>(p.points[1])); };
  auto plane3 = [](const Primitive& p) {
    return typename K::Plane_3(point3<K>(p.points[0]), point3<K>(p.points[1]), point3<K>(p.points[2]));
  };
  auto tri3 = [](const Primitive& p) {
    return typename K::Triangle_3(point3<K>(p.points[0]), point3<K>(p.points[1]), point3<K>(p.points[2]));
  };
  const auto pair = x.kind + "|" + y.kind;
  if (pair == "Segment_2|Segment_2") return intersect<K>(seg2(x), seg2(y), predicate_only);
  if (pair == "Line_2|Line_2") return intersect<K>(line2(x), line2(y), predicate_only);
  if (pair == "Triangle_2|Triangle_2") return intersect<K>(tri2(x), tri2(y), predicate_only);
  if (pair == "Line_3|Plane_3") return intersect<K>(line3(x), plane3(y), predicate_only);
  if (pair == "Plane_3|Line_3") return intersect<K>(plane3(x), line3(y), predicate_only);
  if (pair == "Segment_3|Plane_3") return intersect<K>(seg3(x), plane3(y), predicate_only);
  if (pair == "Plane_3|Segment_3") return intersect<K>(plane3(x), seg3(y), predicate_only);
  if (pair == "Plane_3|Plane_3") return intersect<K>(plane3(x), plane3(y), predicate_only);
  if (pair == "Segment_3|Triangle_3") return intersect<K>(seg3(x), tri3(y), predicate_only);
  if (pair == "Triangle_3|Segment_3") return intersect<K>(tri3(x), seg3(y), predicate_only);
  if (pair == "Ray_3|Triangle_3") return intersect<K>(ray3(x), tri3(y), predicate_only);
  if (pair == "Triangle_3|Ray_3") return intersect<K>(tri3(x), ray3(y), predicate_only);
  if (pair == "Line_3|Line_3") return intersect<K>(line3(x), line3(y), predicate_only);
  precondition("UNSUPPORTED_PRIMITIVE_PAIR", "Intersection pair is not supported: " + pair);
}

Json compute_intersections(const Request& request) {
  require_inputs(request, 1, "kernel.intersections.compute");
  const auto kernel = kernel_parameter(request, false);
  const auto set = read_query_set(request.inputs[0]);
  if (set.queries.empty()) precondition("NO_QUERIES", "KernelQuerySet has no queries");
  for (const auto& query : set.queries) require_nondegenerate(set, query, kernel);
  return with_kernel(kernel, [&](auto tag) {
    using K = decltype(tag);
    Json queries = Json::array();
    for (const auto& query : set.queries) queries.push_back(query_entry(query, evaluate_intersection<K>(set, query)));
    return finish(request, kernel, set,
                  report_frame(request, "intersections", kernel, Json::array(), std::move(queries)),
                  "CGAL::intersection and CGAL::do_intersect (Intersections_2/3)");
  });
}

// ---- distances (7.1.05) -----------------------------------------------------

template <class K>
Json evaluate_distance(const QuerySet& set, const Query& q) {
  if (q.query == "compare_distance" || q.query == "compare_distance_to_point") {
    const int d = q.arguments.size() == 3 ? point_dimension(set, q) : 0;
    if (d == 0) precondition("ARGUMENT_MISMATCH", q.query + " needs three points: " + q.id);
    const bool generic = q.query == "compare_distance";
    if (d == 2) {
      const auto p = point2<K>(set.at(q.arguments[0]).points[0]);
      const auto a = point2<K>(set.at(q.arguments[1]).points[0]);
      const auto b = point2<K>(set.at(q.arguments[2]).points[0]);
      return comparison_name(generic ? CGAL::compare_distance(p, a, b) : CGAL::compare_distance_to_point(p, a, b));
    }
    const auto p = point3<K>(set.at(q.arguments[0]).points[0]);
    const auto a = point3<K>(set.at(q.arguments[1]).points[0]);
    const auto b = point3<K>(set.at(q.arguments[2]).points[0]);
    return comparison_name(generic ? CGAL::compare_distance(p, a, b) : CGAL::compare_distance_to_point(p, a, b));
  }
  if (q.query != "squared_distance" || q.arguments.size() != 2) {
    precondition("UNSUPPORTED_QUERY", "Unsupported distance query or arity: " + q.id);
  }
  const auto& x = set.at(q.arguments[0]);
  const auto& y = set.at(q.arguments[1]);
  auto pt2 = [](const Primitive& p) { return point2<K>(p.points[0]); };
  auto pt3 = [](const Primitive& p) { return point3<K>(p.points[0]); };
  auto seg2 = [](const Primitive& p) { return typename K::Segment_2(point2<K>(p.points[0]), point2<K>(p.points[1])); };
  auto line2 = [](const Primitive& p) { return typename K::Line_2(point2<K>(p.points[0]), point2<K>(p.points[1])); };
  auto seg3 = [](const Primitive& p) { return typename K::Segment_3(point3<K>(p.points[0]), point3<K>(p.points[1])); };
  auto line3 = [](const Primitive& p) { return typename K::Line_3(point3<K>(p.points[0]), point3<K>(p.points[1])); };
  auto plane3 = [](const Primitive& p) {
    return typename K::Plane_3(point3<K>(p.points[0]), point3<K>(p.points[1]), point3<K>(p.points[2]));
  };
  auto tri3 = [](const Primitive& p) {
    return typename K::Triangle_3(point3<K>(p.points[0]), point3<K>(p.points[1]), point3<K>(p.points[2]));
  };
  const auto pair = x.kind + "|" + y.kind;
  auto text = [](const auto& value) { return Json(exact_text(value)); };
  if (pair == "Point_2|Point_2") return text(CGAL::squared_distance(pt2(x), pt2(y)));
  if (pair == "Point_2|Line_2") return text(CGAL::squared_distance(pt2(x), line2(y)));
  if (pair == "Point_2|Segment_2") return text(CGAL::squared_distance(pt2(x), seg2(y)));
  if (pair == "Segment_2|Segment_2") return text(CGAL::squared_distance(seg2(x), seg2(y)));
  if (pair == "Point_3|Point_3") return text(CGAL::squared_distance(pt3(x), pt3(y)));
  if (pair == "Point_3|Line_3") return text(CGAL::squared_distance(pt3(x), line3(y)));
  if (pair == "Point_3|Segment_3") return text(CGAL::squared_distance(pt3(x), seg3(y)));
  if (pair == "Point_3|Plane_3") return text(CGAL::squared_distance(pt3(x), plane3(y)));
  if (pair == "Point_3|Triangle_3") return text(CGAL::squared_distance(pt3(x), tri3(y)));
  if (pair == "Segment_3|Segment_3") return text(CGAL::squared_distance(seg3(x), seg3(y)));
  if (pair == "Line_3|Line_3") return text(CGAL::squared_distance(line3(x), line3(y)));
  precondition("UNSUPPORTED_PRIMITIVE_PAIR", "Squared-distance pair is not supported: " + pair);
}

Json compute_distances(const Request& request) {
  require_inputs(request, 1, "kernel.distance.squared");
  const auto kernel = kernel_parameter(request, true);
  const auto set = read_query_set(request.inputs[0]);
  if (set.queries.empty()) precondition("NO_QUERIES", "KernelQuerySet has no queries");
  for (const auto& query : set.queries) require_nondegenerate(set, query, kernel);
  return with_kernel(kernel, [&](auto tag) {
    using K = decltype(tag);
    Json queries = Json::array();
    for (const auto& query : set.queries) queries.push_back(query_entry(query, evaluate_distance<K>(set, query)));
    return finish(request, kernel, set,
                  report_frame(request, "distances", kernel, Json::array(), std::move(queries)),
                  "CGAL::squared_distance, CGAL::compare_distance, CGAL::compare_distance_to_point");
  });
}

Json transform_info(const std::string& validator, const std::vector<std::string>& kernels) {
  return Json{{"input_format", "json"},
              {"output_format", "json"},
              {"kernels", kernels},
              {"maximum_primitives", kMaximumPrimitives},
              {"maximum_queries", kMaximumQueries},
              {"validators", Json::array({validator})},
              {"validator_parameter_bindings", {{validator, {{"kernel", "kernel"}}}}}};
}

}  // namespace

std::vector<OperationDefinition> transform_operations() {
  const std::vector<std::string> all = {kSimpleCartesian, kCartesian, kEpick, kEpeck};
  const std::vector<std::string> exact_predicates = {kEpick, kEpeck};
  auto construct = kernel_definition("kernel.primitives.construct", {"KernelQuerySet"}, "KernelReport",
                                     "analysis", construct_primitives,
                                     transform_info("kernel.validate.primitives_report", all));
  auto predicates = kernel_definition("kernel.predicates.evaluate", {"KernelQuerySet"}, "KernelReport",
                                      "analysis", evaluate_predicates,
                                      transform_info("kernel.validate.predicates_report", all));
  auto intersections = kernel_definition("kernel.intersections.compute", {"KernelQuerySet"}, "KernelReport",
                                         "analysis", compute_intersections,
                                         transform_info("kernel.validate.intersections_report", exact_predicates));
  intersections.dependencies = {"Kernel_23", "Intersections_2", "Intersections_3"};
  auto distances = kernel_definition("kernel.distance.squared", {"KernelQuerySet"}, "KernelReport",
                                     "analysis", compute_distances,
                                     transform_info("kernel.validate.distances_report", all));
  distances.dependencies = {"Kernel_23", "Distance_2", "Distance_3"};
  return {construct, predicates, intersections, distances};
}

}  // namespace cgal_master::kernel_ops
