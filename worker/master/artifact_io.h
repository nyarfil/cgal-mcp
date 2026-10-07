#pragma once

#include "geometry.h"
#include "protocol.h"

#include <filesystem>
#include <string>
#include <vector>

namespace cgal_master {

void require_input_shape(const ArtifactInput& input,
                         const std::string& expected_type,
                         const std::string& expected_format);
// Reads the artifact bytes and verifies the request sha256 and size limit.
std::string read_verified_input_bytes(const ArtifactInput& input);
std::vector<Point> read_xyz_points(const ArtifactInput& input);
Mesh read_off_mesh(const ArtifactInput& input);
std::filesystem::path checked_output_dir(const Request& request);
std::filesystem::path output_path(const std::filesystem::path& output_dir,
                                  const std::string& filename);
void commit_output(const std::filesystem::path& temporary,
                   const std::filesystem::path& destination);
std::string portable_path(const std::filesystem::path& path);
std::string staging_filename_token(const std::string& identifier);
Json volume_metric(const Kernel::FT& volume, const std::string& length_unit);

}  // namespace cgal_master
