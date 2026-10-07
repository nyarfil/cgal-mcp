cmake_minimum_required(VERSION 3.22)
project(cgal_wave_a_repair_harness LANGUAGES CXX)

find_package(CGAL 6.2.1 EXACT REQUIRED)
find_package(Eigen3 REQUIRED NO_MODULE)
find_package(nlohmann_json 3.10 REQUIRED)

set(MASTER_DIR "${CMAKE_CURRENT_LIST_DIR}/..")
add_executable(cgal-wave-a-repair-harness
  harness.cpp
  repair_common.cpp
  repair_operations.cpp
  repair_validators.cpp
  "${MASTER_DIR}/protocol.cpp"
  "${MASTER_DIR}/sha256.cpp"
  "${MASTER_DIR}/artifact_io.cpp"
)
target_compile_features(cgal-wave-a-repair-harness PRIVATE cxx_std_17)
target_link_libraries(cgal-wave-a-repair-harness PRIVATE
  CGAL::CGAL Eigen3::Eigen nlohmann_json::nlohmann_json)
if(MSVC)
  target_compile_options(cgal-wave-a-repair-harness PRIVATE /bigobj)
endif()
