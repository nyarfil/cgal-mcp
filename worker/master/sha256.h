#pragma once

#include <filesystem>
#include <string>
#include <string_view>

namespace cgal_master {

std::string sha256_file(const std::filesystem::path& path);
std::string sha256_bytes(std::string_view bytes);

}  // namespace cgal_master
