#pragma once
// Exact rational geometry shared by the batch-2 independent validators (7.3.05, 7.3.07,
// 7.5.03, 7.5.04, 7.9.02, 7.9.06, 7.12.04, 7.13.04). No CGAL header is included: every
// predicate and construction is evaluated with GMP rationals on the raw binary64 input.

#include "../query_ops/query_common.h"

#include <array>
#include <map>
#include <set>
#include <string>
#include <vector>

namespace cgal_master::batch2 {

using query_ops::Q;
using query_ops::RawMesh;
using query_ops::V2;
using query_ops::V3;

struct Vec {
  Q x, y, z;
};

Vec vec(const V3& v);
Vec operator-(const Vec& a, const Vec& b);
Vec operator+(const Vec& a, const Vec& b);
Vec operator*(const Q& s, const Vec& a);
Q dot(const Vec& a, const Vec& b);
Vec cross(const Vec& a, const Vec& b);
bool is_zero(const Vec& a);
bool operator==(const Vec& a, const Vec& b);
bool operator!=(const Vec& a, const Vec& b);
bool operator<(const Vec& a, const Vec& b);
std::string vec_text(const Vec& a);

struct Tri {
  Vec v[3];
  V3 raw[3];
};

Tri make_tri(const RawMesh& mesh, const std::vector<std::size_t>& face);
Vec tri_normal(const Tri& t);  // (b-a) x (c-a)
bool tri_degenerate(const Tri& t);
// n . cross(b-a, c-a): positive for the same orientation as n.
Q tri_weight(const Tri& t, const Vec& n);
bool boxes_overlap(const Tri& a, const Tri& b);
// Closed containment of p in the plane and inside of t.
bool point_in_triangle(const Tri& t, const Vec& p);
bool point_on_segment(const Vec& p, const Vec& a, const Vec& b);
// Parametric interval [t0,t1] of the closed segment s0 + t (s1-s0), t in [0,1], inside the
// closed non-degenerate triangle. Returns false when empty.
bool segment_triangle(const Vec& s0, const Vec& s1, const Tri& t, Q& t0, Q& t1);
// Vertices of the convex polygon (T1 intersect T2): all endpoints of edge/triangle intervals.
// Empty when the closed triangles are disjoint.
std::vector<Vec> intersection_points(const Tri& a, const Tri& b);
// Two coplanar triangles with a common orientation along n have disjoint interiors.
bool interiors_disjoint(const Tri& a, const Tri& b, const Vec& n);
// Sutherland-Hodgman clip of a convex polygon to dot(n,x) <= d.
std::vector<Vec> clip_halfspace(const std::vector<Vec>& polygon, const Vec& n, const Q& d);
// n . (sum of fan cross products); 0 for fewer than three vertices.
Q polygon_weight(const std::vector<Vec>& polygon, const Vec& n);

// Canonical id of each distinct coordinate triple of a mesh.
std::vector<std::size_t> canonical_ids(const RawMesh& mesh, std::size_t& distinct);

// Common helpers.
void require_triangle_faces(const RawMesh& mesh, const std::string& context, std::size_t maximum);
Json json_checks(std::initializer_list<const char*> names);
Json concluded(const Request& request, const std::string& validator, Json checks, Json details);
Json require_member(const Json& object, const char* key, const std::string& context);
std::size_t index_of(const Json& value, std::size_t bound, const std::string& context);
Json vinfo(const std::vector<std::string>& checks, std::vector<std::string> slots,
           const std::string& independence);
Json pinfo(const std::string& validator, const std::vector<std::string>& parameters,
           std::vector<std::string> slots, Json extra);
Json geometry_frame(const Request& request, const std::string& kind, Json parameters, Json source,
                    Json summary, Json results);
// Verifies operation/parameters/source hashes of a producer report and returns "results".
Json check_report_frame(const Json& report, const std::string& operation, const Json& parameters,
                        const std::vector<std::pair<const char*, const ArtifactInput*>>& sources, Json& checks);

inline constexpr std::size_t kMaximumFaces = 600;
inline constexpr std::size_t kMaximumOutputFaces = 4000;

}  // namespace cgal_master::batch2
