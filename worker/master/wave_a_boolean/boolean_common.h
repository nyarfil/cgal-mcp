#pragma once

#include "../geometry.h"
#include "../protocol.h"

#include <filesystem>
#include <string>

namespace cgal_master::wave_a_boolean {

enum class BooleanKind { kUnion, kIntersection, kDifference };

struct BooleanResult {
  Mesh mesh;
  bool empty = false;
  bool surfaces_contact = false;
  std::string empty_reason;
  Kernel::FT volume = Kernel::FT(0);
};

std::string operation_name(BooleanKind kind);
std::string operation_id(BooleanKind kind);
std::string validator_id(BooleanKind kind);

void require_boolean_request(const Request& request, BooleanKind kind,
                             bool validator);
Mesh read_boolean_source(const ArtifactInput& input,
                         const std::string& subject);
Mesh read_boolean_candidate(const ArtifactInput& input);
BooleanResult compute_boolean(const Mesh& source_a, const Mesh& source_b,
                              BooleanKind kind);
Kernel::FT mesh_volume(const Mesh& mesh);
std::string exact_number(const Kernel::FT& value);

std::filesystem::path write_boolean_mesh(const Request& request,
                                         const Mesh& mesh);
std::filesystem::path write_boolean_validation(const Request& request,
                                               const Json& report);

Json validate_boolean_semantics(const Mesh& source_a, const Mesh& source_b,
                                const Mesh& candidate, BooleanKind kind,
                                const BooleanResult& reference);

// Rounded output (mesh.boolean.rounded). The exact result keeps its combinatorics and every
// coordinate is replaced by a binary64 value next to the exact one; the rounded mesh must
// still be a healthy volume boundary or NUMERIC_FAILURE/ROUNDING_INVALIDATED_RESULT is thrown.
Mesh round_boolean_mesh(const Mesh& exact);
// Absolute tolerance of the rounded contract: 2^-40 times the power of two above the largest
// absolute source coordinate (a binary64 value, so the comparison is exact).
double rounded_tolerance(const Mesh& source_a, const Mesh& source_b);
// Tolerance-based comparison of a binary64 candidate with the exact replay: same status and
// element counts, volume within tolerance * reference area, and every vertex of either mesh
// within the tolerance of the other surface (exact distance to a witness triangle).
Json validate_boolean_rounded(const Mesh& source_a, const Mesh& source_b,
                              const Mesh& candidate, BooleanKind kind,
                              const BooleanResult& reference);

}  // namespace cgal_master::wave_a_boolean
