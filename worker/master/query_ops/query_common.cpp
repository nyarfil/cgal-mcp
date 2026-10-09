#include "query_common.h"

#include "../artifact_io.h"
#include "../optimization/optimization_common.h"
#include "../wave_c/wave_c_common.h"
#include "../wave_d/wave_d_common.h"

#include <cmath>
#include <fstream>

namespace cgal_master::query_ops {

RawMesh read_raw_mesh(const ArtifactInput& input, std::initializer_list<const char*> types) {
  const auto raw = wave_d::read_raw_mesh(input, types);
  RawMesh result;
  for (const auto& vertex : raw.vertices) result.vertices.push_back({vertex[0], vertex[1], vertex[2]});
  result.faces = raw.faces;
  return result;
}

std::vector<V3> read_points3(const ArtifactInput& input) {
  std::vector<V3> result;
  for (const auto& point : wave_c::read_point_set3(input)) result.push_back({point[0], point[1], point[2]});
  return result;
}

std::vector<RayItem> read_rays(const ArtifactInput& input) {
  std::vector<RayItem> result;
  for (const auto& ray : wave_c::read_ray_batch3(input)) {
    result.push_back({{ray.origin[0], ray.origin[1], ray.origin[2]},
                      {ray.direction[0], ray.direction[1], ray.direction[2]}});
  }
  return result;
}

std::vector<V2> read_points2(const ArtifactInput& input) {
  std::vector<V2> result;
  for (const auto& point : wave_c::read_point_set2(input)) result.push_back({point[0], point[1]});
  return result;
}

std::vector<V2> read_polygon(const ArtifactInput& input) {
  std::vector<V2> result;
  for (const auto& point : wave_c::read_polygon2(input)) result.push_back({point[0], point[1]});
  return result;
}

Q exact_of(double value) { return optimization_ops::exact_of_double(value); }
std::string q_text(const Q& value) { return optimization_ops::q_text(value); }
Q reported_rational(const Json& value, const std::string& context) {
  return optimization_ops::reported_rational(value, context);
}

void require_inputs(const Request& request, std::size_t count, const std::string& operation) {
  wave_c::require_input_count(request, count, operation);
}

void require_parameter_names(const Request& request, std::initializer_list<const char*> required,
                             std::initializer_list<const char*> optional) {
  wave_c::require_parameters(request, required, optional);
}

std::size_t integer_parameter(const Request& request, const char* name, std::size_t minimum,
                              std::size_t maximum) {
  return wave_c::integer_parameter(request, name, minimum, maximum);
}

std::string enum_parameter(const Request& request, const char* name,
                           std::initializer_list<const char*> allowed) {
  return wave_c::enum_parameter(request, name, allowed);
}

double signed_length_parameter(const Request& request, const char* name, const std::string& unit) {
  const auto& value = request.parameters.at(name);
  if (!value.is_object() || value.size() != 2 || !value.contains("value") || !value.contains("unit") ||
      !value.at("unit").is_string() || !value.at("value").is_number()) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " must be a TypedLength {value, unit}");
  }
  if (value.at("unit").get<std::string>() != unit) {
    throw WorkerError("TYPE_ERROR", "UNIT_MISMATCH",
                      std::string(name) + " must be normalized to the artifact unit");
  }
  const double result = value.at("value").get<double>();
  if (!std::isfinite(result)) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be finite");
  }
  return result;
}

V3 vector_parameter(const Request& request, const char* name) {
  const auto& value = request.parameters.at(name);
  if (!value.is_array() || value.size() != 3) {
    throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                      std::string(name) + " must be an array of three numbers");
  }
  V3 result{};
  for (std::size_t i = 0; i < 3; ++i) {
    if (!value[i].is_number() || value[i].is_boolean()) {
      throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER",
                        std::string(name) + " must contain only numbers");
    }
    result[i] = value[i].get<double>();
    if (!std::isfinite(result[i])) {
      throw WorkerError("INVALID_REQUEST", "INVALID_PARAMETER", std::string(name) + " must be finite");
    }
  }
  return result;
}

void require_same_unit(const ArtifactInput& first, const ArtifactInput& second) {
  wave_c::require_same_unit(first, second);
}

void precondition(const std::string& code, const std::string& message) {
  throw WorkerError("PRECONDITION_FAILED", code, message);
}

void validation_failure(const std::string& code, const std::string& message) {
  wave_c::fail_validation(code, message);
}

Json write_report(const Request& request, const std::string& type, const Json& report) {
  return wave_c::write_json_output(request, "analysis", type, "none", report);
}

Json read_report(const ArtifactInput& input, const std::string& type, const std::string& kind_key,
                 const std::string& kind) {
  return wave_c::read_report(input, type, kind_key, kind);
}

Json finish_validation(const Request& request, const std::string& validator, Json report) {
  return wave_c::finish_validation(request, validator, std::move(report));
}

Json write_off_output(const Request& request, const std::vector<V3>& vertices,
                      const std::vector<std::vector<std::size_t>>& faces, const std::string& type,
                      const std::string& unit) {
  const auto directory = checked_output_dir(request);
  const auto destination = output_path(directory, "geometry.off");
  const auto temporary =
      directory / ("." + std::string("geometry") + "." + staging_filename_token(request.request_id) + ".tmp.off");
  std::error_code error;
  if (std::filesystem::exists(temporary, error) || error) {
    throw WorkerError("OUTPUT_ERROR", "TEMPORARY_OUTPUT_EXISTS", "Temporary output path is not clean");
  }
  {
    std::ofstream output(temporary, std::ios::binary);
    output.imbue(std::locale::classic());
    output.precision(17);
    output << "OFF\n" << vertices.size() << ' ' << faces.size() << " 0\n";
    for (const auto& vertex : vertices) output << vertex[0] << ' ' << vertex[1] << ' ' << vertex[2] << '\n';
    for (const auto& face : faces) {
      output << face.size();
      for (const auto index : face) output << ' ' << index;
      output << '\n';
    }
    output.close();
    if (!output) {
      std::filesystem::remove(temporary);
      throw WorkerError("OUTPUT_ERROR", "OUTPUT_WRITE_FAILED", "Unable to write OFF output");
    }
  }
  commit_output(temporary, destination);
  return Json{{"slot", "geometry"},
              {"type", type},
              {"unit", unit},
              {"format", "off"},
              {"path", portable_path(destination)}};
}

OperationDefinition query_definition(std::string id, std::vector<std::string> inputs,
                                     std::string output, std::string role,
                                     std::function<Json(const Request&)> execute,
                                     std::vector<std::string> dependencies, std::string kernel,
                                     Json info) {
  OperationDefinition definition{std::move(id),   1, std::move(inputs), std::move(output),
                                 std::move(role), std::move(execute)};
  definition.supported_kernels = {"package_recommended"};
  definition.effective_kernel = std::move(kernel);
  definition.dependencies = std::move(dependencies);
  definition.info = std::move(info);
  return definition;
}

}  // namespace cgal_master::query_ops
