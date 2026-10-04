#include <CGAL/Exact_predicates_inexact_constructions_kernel.h>
#include <CGAL/Surface_mesh.h>
#include <CGAL/IO/polygon_mesh_io.h>
#include <CGAL/Surface_mesh_simplification/edge_collapse.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Edge_count_ratio_stop_predicate.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/GarlandHeckbert_policies.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Constrained_placement.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Polyhedral_envelope_filter.h>
#include <CGAL/Surface_mesh_simplification/Policies/Edge_collapse/Bounded_normal_change_filter.h>
#include <nlohmann/json.hpp>
#include <iostream>
#include <cmath>
#include <type_traits>
#include <vector>
#include "preflight.h"
using K = CGAL::Exact_predicates_inexact_constructions_kernel;
using Mesh = CGAL::Surface_mesh<K::Point_3>;
using Json = nlohmann::json;
namespace SMS = CGAL::Surface_mesh_simplification;
// Internal CLI: one JSON request on stdin; paths supplied only by trusted job manager.
int main() {
  try {
    Json request; std::cin >> request;
    if(request.at("version") != 1 || request.at("operation") != "simplify")
      throw std::runtime_error("Unsupported request");
    double ratio = request.at("edge_ratio").get<double>();
    if(!std::isfinite(ratio) || ratio <= 0 || ratio >= 1)
      throw std::runtime_error("edge_ratio must be in (0,1)");
    Mesh mesh;
    if(!CGAL::IO::read_polygon_mesh(request.at("input").get<std::string>(), mesh)
       || mesh.number_of_faces() == 0 || !CGAL::is_valid_polygon_mesh(mesh)
       || !CGAL::is_triangle_mesh(mesh))
      throw std::runtime_error("Input must be a nonempty valid triangle mesh");
    for(auto v : mesh.vertices()) {
      auto p = mesh.point(v);
      if(!std::isfinite(p.x()) || !std::isfinite(p.y()) || !std::isfinite(p.z()))
        throw std::runtime_error("Nonfinite coordinate");
    }
    preflight(mesh);
    auto before = mesh.number_of_edges();
    auto constraints = mesh.add_property_map<Mesh::Edge_index, bool>("e:constraints", false).first;
    if(request.value("preserve_border", true))
      for(auto e : mesh.edges()) constraints[e] = CGAL::is_border(e, mesh);
    if(request.contains("constrained_edges")) {
      for(const auto& pair : request["constrained_edges"]) {
        if(!pair.is_array() || pair.size()!=2) throw std::runtime_error("Invalid constraint pair");
        int a=pair[0].get<int>(),b=pair[1].get<int>();
        bool found=false;
        for(auto e:mesh.edges()) {
          auto h=mesh.halfedge(e);
          int s=int(mesh.source(h).idx()),t=int(mesh.target(h).idx());
          if((s==a&&t==b)||(s==b&&t==a)) { constraints[e]=true;found=true;break; }
        }
        if(!found) throw std::runtime_error("Constraint edge does not exist");
      }
    }
    std::vector<std::pair<K::Point_3,K::Point_3>> protected_segments;
    for(auto e:mesh.edges()) if(constraints[e]) {
      auto h=mesh.halfedge(e);
      protected_segments.emplace_back(mesh.point(mesh.source(h)),mesh.point(mesh.target(h)));
    }
    SMS::GarlandHeckbert_plane_and_line_policies<Mesh,K> policies(mesh);
    // Strip reference from placement type so the wrapper owns a policy value.
    using Base = std::decay_t<decltype(policies.get_placement())>;
    SMS::Constrained_placement<Base,decltype(constraints)> placement(constraints, policies.get_placement());
    SMS::Edge_count_ratio_stop_predicate<Mesh> stop(ratio);
    double epsilon = request.value("envelope", 0.0);
    if(!std::isfinite(epsilon) || epsilon < 0) throw std::runtime_error("Invalid envelope");
    int removed;
    if(epsilon > 0) {
      SMS::Polyhedral_envelope_filter<K,SMS::Bounded_normal_change_filter<>> filter(epsilon);
      removed = SMS::edge_collapse(mesh, stop, CGAL::parameters::get_cost(policies.get_cost())
        .get_placement(placement).edge_is_constrained_map(constraints).filter(filter));
    } else {
      removed = SMS::edge_collapse(mesh, stop, CGAL::parameters::get_cost(policies.get_cost())
        .get_placement(placement).edge_is_constrained_map(constraints));
    }
    if(!CGAL::is_valid_polygon_mesh(mesh) || !CGAL::is_triangle_mesh(mesh))
      throw std::runtime_error("Invalid output mesh");
    preflight(mesh);
    for(const auto& segment:protected_segments) {
      bool found=false;
      for(auto e:mesh.edges()) {
        auto h=mesh.halfedge(e);
        const auto& a=mesh.point(mesh.source(h));const auto& b=mesh.point(mesh.target(h));
        if((a==segment.first&&b==segment.second)||(b==segment.first&&a==segment.second))
          {found=true;break;}
      }
      if(!found) throw std::runtime_error("Protected segment changed");
    }
    if(!CGAL::IO::write_polygon_mesh(request.at("output").get<std::string>(), mesh,
                                    CGAL::parameters::stream_precision(17)))
      throw std::runtime_error("Output write failed");
    std::cout << Json{{"version",1},{"ok",true},{"cgal","6.2.1"},
      {"edges_before",before},{"edges_after",mesh.number_of_edges()},
      {"edges_removed",removed},{"target_met",double(mesh.number_of_edges())/before < ratio},
      {"constraints_preserved",true},{"hausdorff_verified",false}}.dump() << std::endl;
    return 0;
  } catch(const std::exception& e) {
    std::cout << Json{{"version",1},{"ok",false},{"error",e.what()}}.dump() << std::endl;
    return 1;
  }
}
