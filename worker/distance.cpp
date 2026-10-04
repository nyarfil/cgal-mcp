#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/IO/polygon_mesh_io.h>
#include <CGAL/Polygon_mesh_processing/distance.h>
#include <nlohmann/json.hpp>
#include <iostream>
#include <cmath>
#include "preflight.h"
using K=CGAL::Exact_predicates_inexact_constructions_kernel;
using Mesh=CGAL::Surface_mesh<K::Point_3>;
using Json=nlohmann::json;
int main() {
  try {
    Json r; std::cin >> r;
    if(r.at("version")!=1 || r.at("operation")!="hausdorff")
      throw std::runtime_error("Unsupported request");
    double error=r.at("error_bound").get<double>();
    double tolerance=r.at("tolerance").get<double>();
    if(!std::isfinite(error)||error<=0||!std::isfinite(tolerance)||tolerance<0)
      throw std::runtime_error("Invalid error_bound or tolerance");
    Mesh a,b;
    auto read=[](const std::string& path,Mesh& mesh) {
      if(!CGAL::IO::read_polygon_mesh(path,mesh)||mesh.number_of_faces()==0
         ||!CGAL::is_valid_polygon_mesh(mesh)||!CGAL::is_triangle_mesh(mesh))
        throw std::runtime_error("Nonempty valid triangle meshes required");
      for(auto v:mesh.vertices()) {
        const auto& p=mesh.point(v);
        if(!std::isfinite(CGAL::to_double(p.x()))||!std::isfinite(CGAL::to_double(p.y()))
           ||!std::isfinite(CGAL::to_double(p.z()))) throw std::runtime_error("Nonfinite coordinate");
      }
    };
    read(r.at("input_a").get<std::string>(),a); read(r.at("input_b").get<std::string>(),b);
    preflight(a);preflight(b);
    double d=CGAL::Polygon_mesh_processing::bounded_error_symmetric_Hausdorff_distance<CGAL::Sequential_tag>(a,b,error);
    if(!std::isfinite(d)) throw std::runtime_error("Nonfinite distance");
    double lower=std::max(0.0,d-error),upper=d+error;
    std::string verdict=upper<=tolerance ? "pass" : lower>tolerance ? "fail" : "indeterminate";
    std::cout<<Json{{"version",1},{"ok",true},{"method","bounded_error_symmetric"},
      {"distance",d},{"error_bound",error},{"lower",lower},{"upper",upper},
      {"tolerance",tolerance},{"verdict",verdict}}.dump()<<std::endl;
    return 0;
  } catch(const std::exception& e) {
    std::cout<<Json{{"version",1},{"ok",false},{"error",e.what()}}.dump()<<std::endl;
    return 1;
  }
}
