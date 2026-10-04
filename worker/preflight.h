#pragma once
#include <CGAL/Polygon_mesh_processing/self_intersections.h>
#include <CGAL/Polygon_mesh_processing/repair_degeneracies.h>
#include <stdexcept>
template<class Mesh> void preflight(const Mesh& mesh) {
  if(mesh.number_of_faces()==0 || !CGAL::is_valid_polygon_mesh(mesh) || !CGAL::is_triangle_mesh(mesh))
    throw std::runtime_error("A valid nonempty triangle mesh is required");
  for(auto face:mesh.faces())
    if(CGAL::Polygon_mesh_processing::is_degenerate_triangle_face(face,mesh))
      throw std::runtime_error("Degenerate triangle");
  if(CGAL::Polygon_mesh_processing::does_self_intersect(mesh))
    throw std::runtime_error("Self intersecting mesh");
}
