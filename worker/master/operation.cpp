#include "operation.h"

#include <CGAL/version.h>

#ifndef CGAL_MASTER_SOURCE_KIND
#define CGAL_MASTER_SOURCE_KIND "unspecified"
#endif

#ifndef CGAL_MASTER_SOURCE_SHA256
#define CGAL_MASTER_SOURCE_SHA256 ""
#endif

#define CGAL_MASTER_STRINGIFY_DETAIL(value) #value
#define CGAL_MASTER_STRINGIFY(value) CGAL_MASTER_STRINGIFY_DETAIL(value)

namespace cgal_master {
namespace {

Json compiler_manifest() {
#if defined(_MSC_VER)
  return Json{{"family", "msvc"},
              {"version", _MSC_VER},
              {"full_version", _MSC_FULL_VER}};
#elif defined(__clang__)
  return Json{{"family", "clang"}, {"version", __clang_version__}};
#elif defined(__GNUC__)
  return Json{{"family", "gcc"}, {"version", __VERSION__}};
#else
  return Json{{"family", "unknown"}, {"version", "unknown"}};
#endif
}

}  // namespace

const std::vector<OperationDefinition>& operation_registry() {
  static const std::vector<OperationDefinition> registry = {
      convex_hull_operation(), convex_enclosure_validator_operation()};
  return registry;
}

Json dispatch(const Request& request) {
  for (const auto& operation : operation_registry()) {
    if (operation.id == request.operation) return operation.execute(request);
  }
  throw WorkerError("UNSUPPORTED", "UNKNOWN_OPERATION",
                    "Operation is not registered: " + request.operation);
}

Json manifest() {
  Json operations = Json::array();
  for (const auto& operation : operation_registry()) {
    operations.push_back(
        {{"id", operation.id},
         {"revision", operation.revision},
         {"input_types", operation.input_types},
         {"output_type", operation.output_type},
         {"role", operation.role},
         {"supported_kernels",
          Json::array({"exact_constructions", "package_recommended"})},
         {"effective_kernel", "CGAL::Exact_predicates_exact_constructions_kernel"}});
  }
  const std::string actual_version = CGAL_MASTER_STRINGIFY(CGAL_VERSION);
  const std::string source_kind = CGAL_MASTER_SOURCE_KIND;
  Json build = {{"cgal_version", actual_version},
                {"cgal_version_nr", CGAL_VERSION_NR},
                {"cgal_release_date", CGAL_RELEASE_DATE},
                {"compiler", compiler_manifest()},
                {"source_kind", source_kind},
                {"source_sha256", CGAL_MASTER_SOURCE_SHA256},
                {"source_attestation",
                 source_kind == "official_release"
                     ? "configured_pinned_official_archive"
                     : "configured_unverified"}};
  return Json{{"protocol", 1},
              {"worker", "cgal-master-worker"},
              {"actual_cgal_version", actual_version},
              {"request_model", "one_json_line_per_process"},
              {"resource_enforcement", "parent_supervisor"},
              {"supported_kernels",
               Json::array({"exact_constructions", "package_recommended"})},
              {"build", std::move(build)},
              {"operations", std::move(operations)}};
}

}  // namespace cgal_master
