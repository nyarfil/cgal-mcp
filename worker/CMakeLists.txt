cmake_minimum_required(VERSION 3.22)
project(cgal_mcp_worker LANGUAGES CXX)
find_package(CGAL 6.2.1 EXACT REQUIRED)
find_package(Eigen3 REQUIRED NO_MODULE)
if(Eigen3_VERSION VERSION_LESS 3.1)
  message(FATAL_ERROR "Eigen3 3.1 or newer is required")
endif()
find_package(nlohmann_json 3.10 REQUIRED)
add_executable(cgal-worker main.cpp)
target_compile_features(cgal-worker PRIVATE cxx_std_17)
target_link_libraries(cgal-worker PRIVATE CGAL::CGAL Eigen3::Eigen nlohmann_json::nlohmann_json)

add_executable(cgal-distance distance.cpp)
target_compile_features(cgal-distance PRIVATE cxx_std_17)
target_link_libraries(cgal-distance PRIVATE CGAL::CGAL Eigen3::Eigen nlohmann_json::nlohmann_json)

set(CGAL_MASTER_SOURCE_KIND "unspecified" CACHE STRING
    "Provenance label for the CGAL source used to build cgal-master-worker")
set(CGAL_MASTER_SOURCE_SHA256 "" CACHE STRING
    "SHA-256 of the CGAL source archive used to build cgal-master-worker")
set(CGAL_6_2_1_OFFICIAL_SOURCE_SHA256
    "b6be77c60765a8456335de991eeaf6ffec55256984e4a9ecc6a97c37bbfe85bf")
if(CGAL_MASTER_SOURCE_KIND STREQUAL "official_release" AND
   NOT CGAL_MASTER_SOURCE_SHA256 STREQUAL CGAL_6_2_1_OFFICIAL_SOURCE_SHA256)
  message(FATAL_ERROR
    "official_release requires the pinned CGAL 6.2.1 source archive SHA-256")
endif()
string(LENGTH "${CGAL_MASTER_SOURCE_SHA256}" CGAL_MASTER_SOURCE_SHA256_LENGTH)
if(CGAL_MASTER_SOURCE_SHA256 AND
   (NOT CGAL_MASTER_SOURCE_SHA256 MATCHES "^[0-9a-f]+$" OR
    NOT CGAL_MASTER_SOURCE_SHA256_LENGTH EQUAL 64))
  message(FATAL_ERROR "CGAL_MASTER_SOURCE_SHA256 must be lowercase SHA-256")
endif()

add_executable(cgal-master-worker
  master/main.cpp
  master/protocol.cpp
  master/sha256.cpp
  master/artifact_io.cpp
  master/operation.cpp
  master/convex_hull_3.cpp
  master/validate_convex_enclosure.cpp
  master/wave_a/mesh_io.cpp
  master/wave_a/simplify_edge_collapse.cpp
  master/wave_a/validate_simplification_integrity.cpp
  master/wave_a/symmetric_hausdorff.cpp
  master/wave_b/pointset_processing.cpp
  master/wave_a_mesh/mesh_analysis.cpp
  master/wave_a_mesh/report_validators.cpp
  master/wave_a_boolean/boolean_common.cpp
  master/wave_a_boolean/pmp_boolean.cpp
  master/wave_a_boolean/validate_boolean.cpp
)
target_compile_features(cgal-master-worker PRIVATE cxx_std_17)
target_compile_definitions(cgal-master-worker PRIVATE
  CGAL_MASTER_SOURCE_KIND="${CGAL_MASTER_SOURCE_KIND}"
  CGAL_MASTER_SOURCE_SHA256="${CGAL_MASTER_SOURCE_SHA256}"
)
target_link_libraries(cgal-master-worker PRIVATE
  CGAL::CGAL Eigen3::Eigen nlohmann_json::nlohmann_json)

if(MSVC)
  target_compile_options(cgal-worker PRIVATE /bigobj)
  target_compile_options(cgal-distance PRIVATE /bigobj)
  target_compile_options(cgal-master-worker PRIVATE /bigobj)
endif()
