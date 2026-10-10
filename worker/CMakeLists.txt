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
  master/wave_a_repair/repair_common.cpp
  master/wave_a_repair/repair_operations.cpp
  master/wave_a_repair/repair_validators.cpp
  master/wave_c/wave_c_common.cpp
  master/wave_c/planar.cpp
  master/wave_c/triangulation.cpp
  master/wave_c/spatial.cpp
  master/wave_d/wave_d_common.cpp
  master/wave_d/remesh_operations.cpp
  master/wave_d/remesh_validators.cpp
  master/wave_e/mesh2.cpp
  master/wave_e/surface_mesh.cpp
  master/wave_e/tet_mesh.cpp
  master/wave_e/volume_mesh.cpp
  master/kernel/kernel_query_set.cpp
  master/kernel/kernel_operations.cpp
  master/kernel/kernel_validators.cpp
  master/optimization/optimization_common.cpp
  master/optimization/optimization_operations.cpp
  master/optimization/optimization_validators.cpp
  master/reconstruction/reconstruction_common.cpp
  master/reconstruction/reconstruction_operations.cpp
  master/reconstruction/reconstruction_validators.cpp
  master/query_ops/query_common.cpp
  master/query_ops/query_operations.cpp
  master/query_ops/query_validators.cpp
  master/batch2/b2_geometry.cpp
  master/batch2/b2_validators_mesh.cpp
  master/batch2/b2_validators_points.cpp
  master/batch2/b2_validators_polygon.cpp
  master/batch2/b2_ops_points.cpp
  master/batch2/b2_ops_mesh.cpp
  master/batch2/b2_ops_polygon.cpp
  master/batch2/b2_registry.cpp
  master/batch3/b3_registry.cpp
  master/batch3/b3_triangulation.cpp
  master/batch3/b3_validators_triangulation.cpp
  master/batch3/b3_planar.cpp
  master/batch3/b3_validators_planar.cpp
  master/batch4/b4_registry.cpp
  master/batch4/b4_mesh_ops.cpp
  master/batch4/b4_validators_mesh.cpp
  master/batch4/b4_alpha_ops.cpp
  master/batch4/b4_validators_alpha.cpp
  master/batch5/b5_registry.cpp
  master/batch5/b5_common.cpp
  master/batch5/b5_intersect_ops.cpp
  master/batch5/b5_intersect_validators.cpp
  master/batch5/b5_distance_ops.cpp
  master/batch5/b5_distance_validators.cpp
  master/batch5/b5_skeleton_ops.cpp
  master/batch5/b5_skeleton_validators.cpp
  master/batch6/b6_registry.cpp
  master/batch6/b6_registration_ops.cpp
  master/batch6/b6_registration_validators.cpp
  master/batch6/b6_polyfit_ops.cpp
  master/batch6/b6_polyfit_validators.cpp
  master/batch6/b6_kinetic_ops.cpp
  master/batch7/b7_registry.cpp
  master/batch7/b7_bilateral_ops.cpp
  master/batch7/b7_smoothing_validators.cpp
  master/batch8/b8_common.cpp
  master/batch8/b8_registry.cpp
  master/batch8/b8_ops.cpp
  master/batch8/b8_validators_decomp_skeleton.cpp
  master/batch8/b8_validators_param.cpp
  master/batch9/b9_registry.cpp
  master/batch9/b9_ops_sdf.cpp
  master/batch9/b9_ops_triangulation.cpp
  master/batch9/b9_validators_sdf.cpp
  master/batch9/b9_validators_triangulation.cpp
)
# smooth_shape needs CGAL's Eigen sparse solver; enable it only where used.
set_source_files_properties(master/wave_d/remesh_operations.cpp PROPERTIES
  COMPILE_DEFINITIONS CGAL_EIGEN3_ENABLED)
# Surface_mesh_approximation (VSA) needs CGAL's Eigen linear algebra.
set_source_files_properties(master/optimization/optimization_operations.cpp PROPERTIES
  COMPILE_DEFINITIONS CGAL_EIGEN3_ENABLED)
# Poisson (implicit function solver) and scale-space jet smoothing need CGAL's Eigen support.
set_source_files_properties(master/reconstruction/reconstruction_operations.cpp PROPERTIES
  COMPILE_DEFINITIONS CGAL_EIGEN3_ENABLED)
# Hole fairing (triangulate_refine_and_fair_hole) needs CGAL's Eigen sparse solver.
set_source_files_properties(master/wave_a_repair/repair_common.cpp PROPERTIES
  COMPILE_DEFINITIONS CGAL_EIGEN3_ENABLED)
# Mean curvature flow skeletonization and ARAP / discrete conformal map parameterization need CGAL's Eigen support.
set_source_files_properties(master/batch8/b8_ops.cpp PROPERTIES
  COMPILE_DEFINITIONS CGAL_EIGEN3_ENABLED)
# Optional third-party dependencies (docs/master/THIRD_PARTY_DEPENDENCIES_JA.md). Without them the
# worker still builds and declares the same operations, which then report UNSUPPORTED /
# OPTIONAL_DEPENDENCY_NOT_BUILT. Configure with -DCMAKE_PREFIX_PATH=<soplex>;<scip>;<opengr>
# (SoPlex is needed because SCIP's config overwrites SOPLEX_DIR) and, if needed, -DOpenGR_DIR / -DSCIP_DIR.
# The CGAL support modules are applied per source file so the other translation units stay unchanged.
set(CGAL_MASTER_OPTIONAL_DEPENDENCIES "")
find_package(OpenGR CONFIG QUIET)
if(OpenGR_FOUND)
  include(CGAL_Eigen3_support)
  include(CGAL_OpenGR_support)
  set_source_files_properties(master/batch6/b6_registration_ops.cpp PROPERTIES
    COMPILE_DEFINITIONS "CGAL_EIGEN3_ENABLED;CGAL_LINKED_WITH_OPENGR;CGAL_MASTER_HAVE_OPENGR"
    INCLUDE_DIRECTORIES "${OpenGR_INCLUDE_DIR}")
  target_link_libraries(cgal-master-worker PRIVATE ${OpenGR_LIBRARIES})
  list(APPEND CGAL_MASTER_OPTIONAL_DEPENDENCIES "OpenGR")
  message(STATUS "Optional dependency OpenGR found: ${OpenGR_INCLUDE_DIR}")
else()
  message(STATUS "Optional dependency OpenGR not found: registration operations report UNSUPPORTED")
endif()
find_package(SCIP CONFIG QUIET)
if(SCIP_FOUND)
  set_source_files_properties(master/batch6/b6_polyfit_ops.cpp PROPERTIES
    COMPILE_DEFINITIONS "CGAL_EIGEN3_ENABLED;CGAL_USE_SCIP;CGAL_MASTER_HAVE_SCIP"
    INCLUDE_DIRECTORIES "${SCIP_INCLUDE_DIRS}")
  target_link_libraries(cgal-master-worker PRIVATE ${SCIP_LIBRARIES})
  list(APPEND CGAL_MASTER_OPTIONAL_DEPENDENCIES "SCIP")
  message(STATUS "Optional dependency SCIP found: ${SCIP_INCLUDE_DIRS}")
else()
  message(STATUS "Optional dependency SCIP not found: polygonal surface reconstruction reports UNSUPPORTED")
endif()
string(REPLACE ";" "," CGAL_MASTER_OPTIONAL_DEPENDENCIES_TEXT "${CGAL_MASTER_OPTIONAL_DEPENDENCIES}")
set_property(SOURCE master/operation.cpp APPEND PROPERTY COMPILE_DEFINITIONS
  "CGAL_MASTER_OPTIONAL_DEPENDENCIES=\"${CGAL_MASTER_OPTIONAL_DEPENDENCIES_TEXT}\"")
# Loop/Catmull-Clark subdivision and Polygon_mesh_slicer need no Eigen; query_operations is plain CGAL.
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
