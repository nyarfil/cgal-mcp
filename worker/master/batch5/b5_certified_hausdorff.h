#pragma once
// Scalable certified symmetric Hausdorff bracket used by mesh.validate.hausdorff_symmetric_report in
// validation_mode "certified_bvh". No CGAL header (see b5_certified_hausdorff.cpp for what is certified).

#include "b5_common.h"

namespace cgal_master::batch5 {

using query_ops::RawMesh;

inline constexpr std::size_t kMaximumCertifiedDistanceFaces = 2000000;
inline constexpr std::size_t kCertifiedNodeBudget = 60000000;

struct CertifiedHausdorff {
  double lower = 0, upper = 0;  // bracket of the exact symmetric Hausdorff distance (before the margin)
  double vertex_lower = 0;      // max over all face corners of both meshes of the distance to the other mesh
  double forward_lower = 0, forward_upper = 0;    // reference -> candidate
  double backward_lower = 0, backward_upper = 0;  // candidate -> reference
  double exact_forward_witness = 0, exact_backward_witness = 0;  // GMP recheck of the witness points
  double width = 0, rounding_margin = 0;
  std::size_t nodes = 0, distance_evaluations = 0, crosscheck_points = 0;
  std::size_t forward_roots = 0, backward_roots = 0;
  double crosscheck_max_deviation = 0;
};

CertifiedHausdorff certified_symmetric_hausdorff(const RawMesh& reference, const RawMesh& candidate,
                                                 double error_bound, double relative_tolerance,
                                                 double relative_width, std::size_t node_budget);

}  // namespace cgal_master::batch5
