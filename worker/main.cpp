#include <CGAL/Simple_cartesian.h>
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
using K = CGAL::Simple_cartesian<double>;
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
    auto before = mesh.number_of_edges();
    auto constraints = mesh.add_property_map<Mesh::Edge_index, bool>("e:constraints", false).first;
    if(request.value("preserve_border", true))
      for(auto e : mesh.edges()) constraints[e] = CGAL::is_border(e, mesh);
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
    if(!CGAL::IO::write_polygon_mesh(request.at("output").get<std::string>(), mesh,
                                    CGAL::parameters::stream_precision(17)))
      throw std::runtime_error("Output write failed");
    std::cout << Json{{"version",1},{"ok",true},{"cgal","6.2.1"},
      {"edges_before",before},{"edges_after",mesh.number_of_edges()},
      {"edges_removed",removed},{"target_met",double(mesh.number_of_edges())/before < ratio},
      {"hausdorff_verified",false}}.dump() << std::endl;
    return 0;
  } catch(const std::exception& e) {
    std::cout << Json{{"version",1},{"ok",false},{"error",e.what()}}.dump() << std::endl;
    return 1;
  }
}
