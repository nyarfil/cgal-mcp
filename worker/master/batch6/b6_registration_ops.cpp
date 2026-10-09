// Point-set registration producers (7.9.05): CGAL::OpenGR::compute_registration_transformation and
// CGAL::OpenGR::register_point_sets (Super4PCS through OpenGR v2023.11, optional dependency).
//   pointset.registration.compute_transformation  -> GeometryQueryReport with the 3x4 transformation
//   pointset.registration.register                -> PointSet3 (the moving set transformed in place)
// Both are checked by independent validators (b6_registration_validators.cpp, no CGAL header) that
// apply the recovered motion in exact rationals. Super4PCS stops on a wall-clock limit; any run that
// reaches that limit is rejected (fail closed) because its result would depend on machine speed.
// OpenGR's random seed is its compile-time default (std::mt19937::default_seed) and is not exposed
// by the CGAL API; it is therefore constant and recorded in the metrics.

#include "b6_common.h"

#include "../artifact_io.h"

#ifdef CGAL_MASTER_HAVE_OPENGR
#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/OpenGR/compute_registration_transformation.h>
#include <CGAL/OpenGR/register_point_sets.h>
#include <CGAL/property_map.h>
#endif

#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <locale>
#include <streambuf>

namespace cgal_master::batch6 {
namespace {

using query_ops::precondition;
using query_ops::require_inputs;
using query_ops::require_parameter_names;

constexpr const char* kEpickName = "CGAL::Exact_predicates_inexact_constructions_kernel";
[[maybe_unused]] constexpr const char* kOpenGrVersion = "OpenGR v2023.11";

struct RegistrationSettings {
  std::size_t samples = 0;
  double accuracy = 0;
  double overlap = 0;
  int max_seconds = 0;
  Json echo;
};

[[maybe_unused]] RegistrationSettings read_settings(const Request& request, const std::string& operation) {
  require_inputs(request, 2, operation);
  require_parameter_names(request, {"number_of_samples", "accuracy", "overlap", "maximum_running_time", "max_rms",
                                    "inlier_distance", "min_inlier_fraction"});
  const auto& reference = request.inputs[0];
  const auto& moving = request.inputs[1];
  if (reference.unit != moving.unit) {
    throw WorkerError("INVALID_REQUEST", "UNIT_MISMATCH", "Both point sets must use the same length unit");
  }
  RegistrationSettings settings;
  settings.samples = reconstruction_ops::integer_parameter(request, "number_of_samples", 8, 1000);
  settings.accuracy = reconstruction_ops::length_parameter(request, "accuracy", reference.unit);
  settings.overlap = reconstruction_ops::number_parameter(request, "overlap", 0.0, 1.0);
  settings.max_seconds = static_cast<int>(reconstruction_ops::integer_parameter(request, "maximum_running_time", 1, 120));
  // Validator-bound tolerances are parsed here for typing; the mandatory validator enforces them.
  reconstruction_ops::length_parameter(request, "max_rms", reference.unit);
  reconstruction_ops::length_parameter(request, "inlier_distance", reference.unit);
  reconstruction_ops::number_parameter(request, "min_inlier_fraction", 0.0, 1.0);
  settings.echo = request.parameters;
  return settings;
}

[[maybe_unused]] std::vector<V3> read_registration_points(const ArtifactInput& input) {
  const auto cloud = reconstruction_ops::read_points(input);
  if (cloud.points.size() < reconstruction_ops::kMinimumPoints) {
    precondition("TOO_FEW_POINTS", "Registration needs at least ten points per set");
  }
  if (cloud.points.size() > kMaximumRegistrationPoints) {
    throw WorkerError("RESOURCE_LIMIT", "POINT_LIMIT_EXCEEDED", "The point set exceeds the registration point limit");
  }
  if (reconstruction_ops::affine_rank(cloud.points) < 3) {
    precondition("DEGENERATE_POINT_SET", "Registration needs point sets that span space (affine rank 3)");
  }
  return cloud.points;
}

// OpenGR writes diagnostics to std::cout / std::cerr; the worker protocol owns stdout (one JSON line)
// and requires an empty stderr, so both streams are muted while the library runs.
class StreamSilencer {
 public:
  StreamSilencer() : out_(std::cout.rdbuf(&sink_)), err_(std::cerr.rdbuf(&sink_)) {}
  ~StreamSilencer() {
    std::cout.rdbuf(out_);
    std::cerr.rdbuf(err_);
  }
  StreamSilencer(const StreamSilencer&) = delete;
  StreamSilencer& operator=(const StreamSilencer&) = delete;

 private:
  struct NullBuffer : std::streambuf {
    int overflow(int c) override { return c; }
  } sink_;
  std::streambuf* out_;
  std::streambuf* err_;
};

#ifdef CGAL_MASTER_HAVE_OPENGR
using Kernel = CGAL::Exact_predicates_inexact_constructions_kernel;
using Point = Kernel::Point_3;
using Vector = Kernel::Vector_3;
using PointNormal = std::pair<Point, Vector>;

// OpenGR needs a normal per point; zero normals switch its normal-pair filter off (PointPairFilter.h
// skips pairs whose normals have zero norm), so the registration depends on positions only.
std::vector<PointNormal> cgal_points(const std::vector<V3>& points) {
  std::vector<PointNormal> result;
  result.reserve(points.size());
  for (const auto& p : points) result.emplace_back(Point(p[0], p[1], p[2]), Vector(0, 0, 0));
  return result;
}

auto reference_parameters(const RegistrationSettings& s) {
  return CGAL::parameters::point_map(CGAL::First_of_pair_property_map<PointNormal>())
      .normal_map(CGAL::Second_of_pair_property_map<PointNormal>())
      .number_of_samples(static_cast<unsigned int>(s.samples))
      .accuracy(s.accuracy)
      .overlap(s.overlap)
      .maximum_running_time(s.max_seconds);
}

auto moving_parameters() {
  return CGAL::parameters::point_map(CGAL::First_of_pair_property_map<PointNormal>())
      .normal_map(CGAL::Second_of_pair_property_map<PointNormal>());
}

void reject_time_limited(const RegistrationSettings& s, double elapsed_seconds) {
  if (elapsed_seconds >= static_cast<double>(s.max_seconds) - 0.5) {
    precondition("REGISTRATION_TIME_LIMIT_REACHED",
                 "Super4PCS stopped on its wall-clock limit; the result would depend on machine speed");
  }
}

Json settings_metrics(const RegistrationSettings& s) {
  return Json{{"number_of_samples", s.samples},
              {"accuracy", s.accuracy},
              {"overlap", s.overlap},
              {"normal_filter", "inactive (zero normals)"},
              {"maximum_running_time", s.max_seconds},
              {"random_seed", "OpenGR default std::mt19937::default_seed (not settable through the CGAL API)"},
              {"opengr", kOpenGrVersion},
              {"effective_kernel", kEpickName}};
}
#endif

Json run_compute_transformation(const Request& request) {
  const std::string operation = "pointset.registration.compute_transformation";
#ifdef CGAL_MASTER_HAVE_OPENGR
  const auto settings = read_settings(request, operation);
  const auto reference = read_registration_points(request.inputs[0]);
  const auto moving = read_registration_points(request.inputs[1]);
  const auto reference_points = cgal_points(reference);
  const auto moving_points = cgal_points(moving);
  const auto begin = std::chrono::steady_clock::now();
  std::pair<Kernel::Aff_transformation_3, double> result = [&] {
    StreamSilencer silence;
    return CGAL::OpenGR::compute_registration_transformation(reference_points, moving_points,
                                                             reference_parameters(settings), moving_parameters());
  }();
  const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
  reject_time_limited(settings, elapsed);
  const auto& t = result.first;
  Json matrix = Json::array();
  for (int row = 0; row < 3; ++row) {
    for (int column = 0; column < 4; ++column) {
      const double value = CGAL::to_double(t.cartesian(row, column));
      if (!std::isfinite(value)) precondition("REGISTRATION_FAILED", "The transformation is not finite");
      matrix.push_back(value);
    }
  }
  const double score = result.second;
  Json report{{"schema_version", 1},
              {"report_type", "GeometryQueryReport"},
              {"report_kind", "registration_transformation"},
              {"operation", operation},
              {"length_unit", request.inputs[0].unit},
              {"parameters", settings.echo},
              {"source", {{"reference_sha256", request.inputs[0].sha256}, {"moving_sha256", request.inputs[1].sha256}}},
              {"summary", {{"reference_count", reference.size()}, {"moving_count", moving.size()}}},
              {"results", {{"transformation_row_major_3x4", matrix}, {"score", score}}}};
  auto output = query_ops::write_report(request, "GeometryQueryReport", report);
  auto metrics = settings_metrics(settings);
  metrics["algorithm"] = "CGAL::OpenGR::compute_registration_transformation";
  metrics["score"] = score;
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
#else
  (void)request;
  optional_dependency_missing("OpenGR", operation);
#endif
}

Json run_register(const Request& request) {
  const std::string operation = "pointset.registration.register";
#ifdef CGAL_MASTER_HAVE_OPENGR
  const auto settings = read_settings(request, operation);
  const auto reference = read_registration_points(request.inputs[0]);
  const auto moving = read_registration_points(request.inputs[1]);
  const auto reference_points = cgal_points(reference);
  auto moving_points = cgal_points(moving);
  const auto begin = std::chrono::steady_clock::now();
  const double score = [&] {
    StreamSilencer silence;
    return CGAL::OpenGR::register_point_sets(reference_points, moving_points, reference_parameters(settings),
                                             moving_parameters());
  }();
  const double elapsed = std::chrono::duration<double>(std::chrono::steady_clock::now() - begin).count();
  reject_time_limited(settings, elapsed);
  std::vector<V3> registered;
  for (const auto& entry : moving_points) {
    const auto& p = entry.first;
    registered.push_back({CGAL::to_double(p.x()), CGAL::to_double(p.y()), CGAL::to_double(p.z())});
    for (const double c : registered.back()) {
      if (!std::isfinite(c)) precondition("REGISTRATION_FAILED", "A registered point is not finite");
    }
  }
  auto output = write_xyz_output(request, registered, request.inputs[1].unit);
  auto metrics = settings_metrics(settings);
  metrics["algorithm"] = "CGAL::OpenGR::register_point_sets";
  metrics["score"] = score;
  metrics["point_count"] = registered.size();
  return success_result(request, Json::array({std::move(output)}), std::move(metrics));
#else
  (void)request;
  optional_dependency_missing("OpenGR", operation);
#endif
}

Json registration_info(const char* header, const char* validator) {
  Json bindings = {{"max_rms", "max_rms"}, {"inlier_distance", "inlier_distance"},
                   {"min_inlier_fraction", "min_inlier_fraction"}};
#ifdef CGAL_MASTER_HAVE_OPENGR
  const bool built = true;
#else
  const bool built = false;
#endif
  return Json{{"source_header", header},
              {"input_slots", {"reference", "moving"}},
              {"maximum_input_points", kMaximumRegistrationPoints},
              {"optional_dependency", "OpenGR"},
              {"optional_dependency_built", built},
              {"validators", {validator}},
              {"validator_parameter_bindings", {{validator, bindings}}}};
}

}  // namespace

Json write_xyz_output(const Request& request, const std::vector<V3>& points, const std::string& unit) {
  const auto directory = checked_output_dir(request);
  const auto destination = output_path(directory, "points.xyz");
  const auto temporary =
      directory / ("." + std::string("points") + "." + staging_filename_token(request.request_id) + ".tmp.xyz");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("OUTPUT_ERROR", "TEMPORARY_OUTPUT_EXISTS", "Temporary output path is not clean");
  }
  {
    std::ofstream output(temporary, std::ios::binary);
    output.imbue(std::locale::classic());
    output.precision(17);
    for (const auto& p : points) output << p[0] << ' ' << p[1] << ' ' << p[2] << '\n';
    output.close();
    if (!output) {
      std::filesystem::remove(temporary);
      throw WorkerError("OUTPUT_ERROR", "OUTPUT_WRITE_FAILED", "Unable to write XYZ output");
    }
  }
  commit_output(temporary, destination);
  return Json{{"slot", "points"}, {"type", "PointSet3"}, {"unit", unit}, {"format", "xyz"},
              {"path", portable_path(destination)}};
}

std::vector<OperationDefinition> registration_producers() {
  using query_ops::query_definition;
  std::vector<OperationDefinition> result;
  result.push_back(query_definition(
      "pointset.registration.compute_transformation", {"PointSet3", "PointSet3"}, "GeometryQueryReport", "analysis",
      run_compute_transformation, {"Point_set_processing_3", "OpenGR"}, kEpickName,
      registration_info("CGAL/OpenGR/compute_registration_transformation.h",
                        "pointset.validate.registration_transformation")));
  result.push_back(query_definition(
      "pointset.registration.register", {"PointSet3", "PointSet3"}, "PointSet3", "transform", run_register,
      {"Point_set_processing_3", "OpenGR"}, kEpickName,
      registration_info("CGAL/OpenGR/register_point_sets.h", "pointset.validate.registered_points")));
  return result;
}

}  // namespace cgal_master::batch6
