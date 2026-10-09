"""Data-declared replay case sets for original major-capability families.

One replay mechanism (``scripts/replay_master_capabilities.py``) executes every
family. Each family below declares, as data only:

* the requirements it binds, with the validated operations and the inventory
  subcapability symbols each bound requirement is held to;
* the requirements it deliberately leaves unbound, with the precise gap;
* positive cases (fixture, operation, parameters, behavioural assertions);
* paired-case checks and expected-rejection negative controls.

Mandatory validators are never listed here: they are derived from the
operation registry (``validation.validators`` and ``validation.bindings``) so a
case cannot skip or substitute a validator. Assertions use a closed vocabulary
of selectors/measures implemented below; no case can name code to execute.

Wave A simplification (7.7) keeps its bespoke contract in
``scripts/master_acceptance.py`` and is registered as a family by the replay
runner.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import math
from typing import Any

FIXTURE_ROOT = "tests/fixtures/master"
FAMILY_HARNESS_PATH = "tests/master_family_replay_cases.py"
FAMILY_CONTRACT_PATH = "scripts/master_replay_families.py"
STANDALONE_UNMET_GATES = (
    "remaining_major_capability_requirements",
    "search_and_retrieval_acceptance",
    "multi_operation_workflow_acceptance",
    "host_compatibility_matrix",
    "performance_resource_and_robustness_acceptance",
)
BINDING_RULE = (
    "A requirement is bound only when replayed cases exercise every enumerated "
    "variant in its original description and every subcapability symbol listed for "
    "it in catalog/major_capability_inventory.json, each through a VALIDATED "
    "operation whose registry-mandated validators pass."
)

TETRA = {"fixture": "wave_a_repair/tetra_outward.off",
         "sha256": "9713f92b295f8c4769d2cb8a1ea793ffff044e0689b1a760556daca497ff8c70"}
OPEN_TETRA = {"fixture": "wave_a_repair/open_tetra_hole.off",
              "sha256": "efb1b639be9862e629614ec53e3dabf3b2f8c6829746f0598755f1e5ae82cbd3"}
QUAD_CUBE = {"fixture": "replay/quad_cube.off",
             "sha256": "3eb508791f4ae9b98a6435b01e7e7d336283ff3b683c1158a0a46ef612049720"}
INTERSECTING = {"fixture": "replay/intersecting_tetrahedra.off",
                "sha256": "088c0fb78e5c559dfa809c899cb0b4a51be6034fe1bfe3cd380e652963203287"}
CUBE_A = {"fixture": "wave_a_boolean/cube_a.off",
          "sha256": "727bedd5d13712e7506e15aeb1ea35b5da660bf2143bf28e8f257b0aa7eb2164"}
CUBE_OVERLAP = {"fixture": "wave_a_boolean/cube_overlap.off",
                "sha256": "76773013b165e44ba4f7668144a74ea31cb43fc61bd102d3d368f16ca4adc7c9"}
CUBE_CONTAINED = {"fixture": "wave_a_boolean/cube_contained.off",
                  "sha256": "857398dc1af0ff7c938c08c2ebdb7e00352f73a571d6f6fbaa3ad4913c01a5fa"}
CUBE_DISJOINT = {"fixture": "wave_a_boolean/cube_disjoint.off",
                 "sha256": "6663ab0ca3e8b2cbf6965eb22f29b84ef47fa2114a180283720d73cebda9fdce"}
OPEN_CUBE = {"fixture": "wave_a_boolean/open_cube.off",
             "sha256": "8d4361aaa4b58509192dd35df2ddc7f0a735f84339825532f2c0ba22be0bc242"}
INWARD_CUBE = {"fixture": "wave_a_boolean/inward_cube.off",
               "sha256": "b61488ba67892f3859b0f6180b096182c626149e7ba435215286cb2c2dba62ea"}
FLIPPED_SOUP = {"fixture": "wave_a_repair/tetra_flipped_soup.off",
                "sha256": "c363f3006ae2317b0dd94ee94fcdf31d2307588ea8d267e9dd2266b17413eed3"}
SEAM = {"fixture": "wave_a_repair/duplicated_seam.off",
        "sha256": "38ac49cb0fbd26449c1da56a4c40ce87a48480cc2b0a724f2c49af1c774e8eb1"}
DEGENERATE_FACE = {"fixture": "wave_a_repair/degenerate_face.off",
                   "sha256": "3976347b4e7744f4de6d41c7475eeda7198e5973dd6cbc881e0fb9c7b9c603f3"}
ZERO_EDGE = {"fixture": "replay/zero_length_edge_soup.off",
             "sha256": "c2006933f1f2dfc036143728701adf7b7422b28e7acbafe44fe6e110db37ae25"}
DIRTY_SOUP = {"fixture": "wave_a_repair/dirty_polygon_soup.off",
              "sha256": "9f246dfd058ef36fe5bf0a3371513dbbfa130f36ae42ace4850362ecea155211"}
DUPLICATE_FACES = {"fixture": "wave_a_repair/duplicate_faces.off",
                   "sha256": "7491fcba50478cd654dd8f291379ddfae26e5f14532b17d51367ca8bad16b1ea"}
NONMANIFOLD = {"fixture": "wave_a_repair/nonmanifold_vertex.off",
               "sha256": "699a11b36d882ee67a5e7efd90eb1149aed8431d8719c5bccadc6a6cb7cea409"}
PLANE = {"fixture": "replay/noisy_plane_without_outlier.xyz",
         "sha256": "57913bba9ace858b3c8925f7abf7b5c2009dea1faca0a204eeba477edd0653be"}
NOISY_PLANE = {"fixture": "wave_b/noisy_plane_with_outlier.xyz",
               "sha256": "5ce0758c1f9d9c0d59c80b567982ccf93f8c5df7f75cb6dc4f85430f75adc452"}
ALTERNATING = {"fixture": "wave_b/plane_normals_alternating.ply",
               "sha256": "19a42b0881ce6a9d437026a0858302da91602a2296c5cd93149056d44670691e"}


def _mesh(fixture: dict, type_: str = "TriangleSurfaceMesh") -> dict:
    return {**fixture, "type": type_, "format": "off", "unit": "mm"}


def _points(fixture: dict, type_: str = "PointSet3", format_: str = "xyz") -> dict:
    return {**fixture, "type": type_, "format": format_, "unit": "mm"}


def _case(case_id: str, operation: str, inputs: list[dict], parameters: dict,
          assertions: list[list]) -> dict:
    return {"id": case_id, "operation": operation, "inputs": inputs,
            "parameters": parameters, "assertions": assertions}



# --- Query / mesh-processing additions (7.2.04, 7.3.02, 7.3.08, 7.5.05, 7.8.06, 7.13.05) -----
QUERY_FIXTURES = {
    "bary_queries.json": "52585029f6d0f347eca611d7837ef2e7cd31c06984937949621ac215048bd10d",
    "bary_queries_l.json": "47f72e8372f235c2a83e171bbd81e596acd416e9ceb576bc533bce95ecd79201",
    "bary_query_boundary.json": "5f986b90fee661ae27863225ea756e48214b68afa3fab6d04281fa7f0e43ae1e",
    "bary_query_outside.json": "0588c391ca59db7b5eb1eaa15d8d4c520e719aefc62645a89d84a55d840989a6",
    "cube12.off": "7e053da364bc195cb7d8f0550dc113810b70892027b2cf4e199c128171fda717",
    "hexagon.json": "7e2fe8c42252f65f6a8ecbb7b6cabfd6f71d57d48f0b13c31bce027ec3d5ee60",
    "locate_queries.xyz": "dc0a946d759f2911c71742bf35833a46e7c6522c6ac68fa65a034fcd5a019a14",
    "polygon_bowtie.json": "56d19bb3a00f04b5f2ea006f925f19065ea8a0cf828cc37871931952adf227a5",
    "polygon_clockwise.json": "592be3a3d7bd365ac826bcb3275bcebf7661b69d88c004f8d8fce63d06ac520e",
    "polygon_l.json": "327f3b76bc632fb0beae639a53b903628afc85fa77131bdbe936201d3d038069",
    "quad_box.off": "a3cc071e3e8b3b3a14a2b7ea1ae050ab59395203edab8fe17bb865fe6e97078c",
    "rays.json": "c347890d1bde5d206c57c30b4bfc58da7139a55c524c042a46e92e77041d7718",
    "square4.json": "d8bbb3b924f4aeaec6007f10e4fe4f601bf0980dcf9c33ec7dc8eabf6b8d09c6",
    "square_open.off": "688a3e7048000ecbebcd7dee98e53f07f9a4013aa76d56ddc5fe7f8dd74d82bc",
    "square_queries.json": "2e6aa8a14c723361fcc1f9910f59b3751727858a0f19e34e63ce2e8a155b63f1",
    "tampered_barycentric_report.json": "4a8abfcc6c8bcd1782d252b3a7cd1af259f219a2bd74e8609abddf28d4f53005",
    "tampered_catmull.off": "9f034dcc4ddff7fe5b93744f121839a4a665c82b6aec8b9da213578a92508ce6",
    "tampered_components_report.json": "a1d1ecd3c4fec51dd84b8e0c7c008e6e8b6cdfeae7c64c0e03f3200dceb10327",
    "tampered_intersections_report.json": "466ae5d45e60a5384893aa681b540b4972dde1da139dd797733092698106e794",
    "tampered_location_report.json": "b9620781aed6ebdf8f5230cb60399e8697ddcf07f9feb6fcca6f7a933cd4d005",
    "tampered_loop.off": "98341549b293aa36a17fb74aa8107909722f6aa2bb558c6702cd6130dd9c239c",
    "tampered_slice_report.json": "b8f9f0e34bfb8a42c6e78ebbb54669baa806d820e0fe634d759eb12320776e54",
    "tetra.off": "1b76c83fce531d9d5b2a33cd741fe18905d6bb08c9fd109de5c39621e61eabb5",
    "three_components.off": "c98f03478077634b71edd11af710d32ddc155739caa59ee900e0ce9356691eb5",
}


def _qfx(name: str) -> dict:
    return {"fixture": f"query/{name}", "sha256": QUERY_FIXTURES[name]}


def _qmesh(name: str, type_: str = "TriangleSurfaceMesh") -> dict:
    return {**_qfx(name), "type": type_, "format": "off", "unit": "mm"}


def _qjson(name: str, type_: str, unit: str = "mm") -> dict:
    return {**_qfx(name), "type": type_, "format": "json", "unit": unit}


def _qpoints(name: str) -> dict:
    return {**_qfx(name), "type": "PointSet3", "format": "xyz", "unit": "mm"}


Q_CUBE = _qmesh("cube12.off")
Q_TETRA = _qmesh("tetra.off")
Q_THREE = _qmesh("three_components.off")
Q_OPEN_SQUARE = _qmesh("square_open.off")
Q_QUAD_BOX = _qmesh("quad_box.off", "PolygonSoup3")
Q_HEXAGON = _qjson("hexagon.json", "Polygon2")
Q_SQUARE = _qjson("square4.json", "Polygon2")
Q_POLYGON_L = _qjson("polygon_l.json", "Polygon2")
Q_BARY = _qjson("bary_queries.json", "PointSet2")
Q_BARY_L = _qjson("bary_queries_l.json", "PointSet2")
Q_SQUARE_QUERIES = _qjson("square_queries.json", "PointSet2")
Q_RAYS = _qjson("rays.json", "RayBatch3")
Q_LOCATE_POINTS = _qpoints("locate_queries.xyz")
Q_PLANE_Z1 = {"normal": [0, 0, 1], "offset": {"value": 1, "unit": "mm"}}
Q_PLANE_DIAGONAL = {"normal": [1, 1, 1], "offset": {"value": 3, "unit": "mm"}}
Q_BARY_ALGORITHM = {
    "wachspress": "CGAL::Barycentric_coordinates::wachspress_coordinates_2",
    "mean_value": "CGAL::Barycentric_coordinates::mean_value_coordinates_2",
    "discrete_harmonic": "CGAL::Barycentric_coordinates::discrete_harmonic_coordinates_2",
}


def _bary_case(case_id: str, method: str, extra: list[list]) -> dict:
    return _case(case_id, "shape.barycentric", [Q_SQUARE, Q_SQUARE_QUERIES], {"method": method}, [
        ["metrics.vertex_count", "==", 4],
        ["metrics.query_count", "==", 2],
        ["metrics.method", "==", method],
        ["metrics.algorithm", "==", Q_BARY_ALGORITHM[method]],
        ["output:analysis:json:report_kind", "==", "barycentric_coordinates"],
        ["output:analysis:json:results[*].query_index", "==", [0, 1]],
        # The square's centre has the four equal weights 1/4 for every coordinate family.
        ["output:analysis:json:results.0.coordinates", "approx", [[0.25, 0.25, 0.25, 0.25], 1e-12]],
    ] + extra)


def _locate_case(case_id: str, strategy: str, algorithm: str) -> dict:
    return _case(case_id, "mesh.location.locate", [Q_CUBE, Q_LOCATE_POINTS], {"strategy": strategy}, [
        ["metrics.face_count", "==", 12],
        ["metrics.query_count", "==", 7],
        ["metrics.strategy", "==", strategy],
        ["metrics.algorithm", "==", algorithm],
        ["output:analysis:json:report_kind", "==", "mesh_location"],
        # Hand-derived on the 0..2 cube: (1,1,5) is 3 above the top face, (0.5,0.25,-1) 1 below the
        # bottom face, (1,1,1) is 1 from every face, (3,3,3) is sqrt(3) from the corner (2,2,2),
        # (2,1,1) lies on the x=2 face and (-1,-1,-1) is sqrt(3) from the origin corner.
        ["output:analysis:json:results[*].squared_distance", "==", ["9", "1", "1", "3", "0", "3", "0"]],
        ["output:analysis:json:results.0.point", "==", ["1", "1", "2"]],
        ["output:analysis:json:results.1.point", "==", ["1/2", "1/4", "0"]],
        ["output:analysis:json:results.3.point", "==", ["2", "2", "2"]],
        ["output:analysis:json:results.4.point", "==", ["2", "1", "1"]],
        ["output:analysis:json:results.5.point", "==", ["0", "0", "0"]],
        ["output:analysis:json:results.6.point", "==", ["0", "0", "0"]],
    ])


def _subdivision_case(case_id: str, operation: str, source: dict, steps: int, vertices: int, faces: int,
                      extra: list[list]) -> dict:
    algorithm = ("CGAL::Subdivision_method_3::CatmullClark_subdivision" if operation.endswith("catmull_clark")
                 else "CGAL::Subdivision_method_3::Loop_subdivision")
    return _case(case_id, operation, [source], {"steps": steps}, [
        ["metrics.steps", "==", steps],
        ["metrics.algorithm", "==", algorithm],
        ["metrics.output_face_count", "==", faces],
        ["metrics.output_vertex_count", "==", vertices],
        ["output:geometry:measure:off.vertex_count", "==", vertices],
        ["output:geometry:measure:off.face_count", "==", faces],
    ] + extra)


SQRT3_HALF = math.sqrt(3.0) / 2.0

SQRT3_INV = 1.0 / math.sqrt(3.0)
# Hand-derived from the cube_a.off geometry (0..2 axis-aligned cube, outward winding):
# per-face outward axis normals in file order, and vertex normals along the corner diagonals.
CUBE_FACE_NORMALS = [
    [0.0, 0.0, -1.0],
    [0.0, 0.0, -1.0],
    [0.0, 0.0, 1.0],
    [0.0, 0.0, 1.0],
    [0.0, -1.0, 0.0],
    [0.0, -1.0, 0.0],
    [1.0, 0.0, 0.0],
    [1.0, 0.0, 0.0],
    [0.0, 1.0, 0.0],
    [0.0, 1.0, 0.0],
    [-1.0, 0.0, 0.0],
    [-1.0, 0.0, 0.0],
]
CUBE_VERTEX_NORMALS = [[c * SQRT3_INV for c in corner] for corner in [
    [-1.0, -1.0, -1.0],
    [1.0, -1.0, -1.0],
    [1.0, 1.0, -1.0],
    [-1.0, 1.0, -1.0],
    [-1.0, -1.0, 1.0],
    [1.0, -1.0, 1.0],
    [1.0, 1.0, 1.0],
    [-1.0, 1.0, 1.0],
]]
INWARD_FACE_NORMALS = [[-c if c else 0.0 for c in normal] for normal in CUBE_FACE_NORMALS]
INWARD_VERTEX_NORMALS = [[-c if c else 0.0 for c in normal] for normal in CUBE_VERTEX_NORMALS]

# --- Batch 2 (7.3.05, 7.3.07, 7.5.03, 7.5.04, 7.9.02, 7.9.06, 7.12.04, 7.13.04) -------------------
B2_FIXTURES = {
    "bent_plate.off": "301cd43811e30698b235dbfae581f808c3f1ea9be881f2c98db7b7055b727865",
    "circle_points.json": "16d3d1c519f73353877166417d81c196f6439f612212f477b47adc89eed4e92e",
    "circle_two.json": "6b4dd51c0dc755182ad00542dae4788a2b64433e6d507153808506f8e3384750",
    "clip_tampered_strip.off": "2d634c608120ad27364b856c51045b13a897d3152658067c9ec2fbc95fc0c205",
    "cluster_outlier.xyz": "362d924e2dff51f4da699158ada35c2be08868df85f44cc89826f15e9cf715c5",
    "cube_corners.xyz": "2a71cbe76f2ab94766500168f571a5bd664a4e9a8fc5050e5d620addeef271bf",
    "line10.xyz": "7d6e08867be12f61ccb63a6755de0b0f8f128d1f90277fbfa8ded3129cda34d6",
    "square_far.json": "716a2b1b82b0e8986975e02b75a52c05238ccd86147ec074a023a1a6faa50380",
    "square_inner.json": "5ef7a06ca3138e7340374704b5ebc268a7cfbe6bffe6422a3210bef81c7190b8",
    "square_shift.json": "a718366e13788d486a70dcf7e871bf323a529cc2ee5fde6354d338deca7c6191",
    "tampered_circle_report.json": "a0ada6198ec8817c47144dc12b04e7834d455ca333611b8201427b54d19a9921",
    "tampered_features_report.json": "fb1fb0121c2f3242a1e033a9eb901216051bd3e32273ca58829e418d37e2c92d",
    "tampered_outliers.xyz": "76c43c76a7181019cece42a534455d5c6a1ec5527621965f7430306d8d10dc21",
    "tampered_polygon_report.json": "df1ab315d40d581e81d226ec738b2845caea99e21baa300f78ec442c7efc7135",
    "tampered_spacing_report.json": "c648a26cbec864f42b42d921d7aab32ac9ac0afa64418f85114688b58a1977ef",
    "tampered_sphere_report.json": "d8b87b6f0bde1ee5f2844b6c56e01edb4e689c9c7646e6674c2233255fff077d",
    "tetra_b.off": "a71b52c4299519944398644e065224c526aa4d61f03b76e04b5578d8b7ce4433",
}


def _bfx(name: str) -> dict:
    return {"fixture": f"batch2/{name}", "sha256": B2_FIXTURES[name]}


def _bmesh(name: str, type_: str = "TriangleSurfaceMesh") -> dict:
    return {**_bfx(name), "type": type_, "format": "off", "unit": "mm"}


def _bpoints(name: str) -> dict:
    return {**_bfx(name), "type": "PointSet3", "format": "xyz", "unit": "mm"}


def _bjson(name: str, type_: str) -> dict:
    return {**_bfx(name), "type": type_, "format": "json", "unit": "mm"}


def _breport(name: str) -> dict:
    return {**_bfx(name), "type": "GeometryQueryReport", "format": "json", "unit": "none"}


def _mm_length(value: float) -> dict:
    return {"value": value, "unit": "mm"}


B_BENT = _bmesh("bent_plate.off")
B_TETRA_B = _bmesh("tetra_b.off")
B_LINE = _bpoints("line10.xyz")
B_CLUSTER = _bpoints("cluster_outlier.xyz")
B_CUBE_CORNERS = _bpoints("cube_corners.xyz")
B_CIRCLE = _bjson("circle_points.json", "PointSet2")
B_CIRCLE_TWO = _bjson("circle_two.json", "PointSet2")
B_SQUARE_SHIFT = _bjson("square_shift.json", "Polygon2")
B_SQUARE_INNER = _bjson("square_inner.json", "Polygon2")
B_SQUARE_FAR = _bjson("square_far.json", "Polygon2")
B_HEXAGON_CW = _qjson("polygon_clockwise.json", "Polygon2")
B_BOWTIE = _qjson("polygon_bowtie.json", "Polygon2")
B_PLANE_X1 = {"normal": [1, 0, 0], "offset": _mm_length(1)}
B_PLANE_DIAGONAL = {"normal": [1, 1, 1], "offset": _mm_length(3)}
SQRT3 = math.sqrt(3.0)

B2_CASES_7_3 = [
    _case("features-cube-30", "mesh.features.detect", [Q_CUBE], {"angle_degrees": 30}, [
        ["metrics.face_count", "==", 12],
        ["metrics.sharp_edge_count", "==", 12],
        ["metrics.patch_count", "==", 6],
        ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::sharp_edges_segmentation"],
        ["output:analysis:json:report_kind", "==", "mesh_features"],
        # The 12 cube edges (90 degrees between face normals) are sharp, the 6 face diagonals are flat:
        # every cube corner is on exactly three sharp edges and the cube falls into its six faces.
        ["output:analysis:json:results.vertex_feature_degree", "==", [3, 3, 3, 3, 3, 3, 3, 3]],
        ["output:analysis:json:results.segmentation.patch_count", "==", 6],
    ]),
    _case("features-cube-100", "mesh.features.detect", [Q_CUBE], {"angle_degrees": 100}, [
        ["metrics.sharp_edge_count", "==", 0],
        ["metrics.patch_count", "==", 1],
        ["output:analysis:json:results.sharp_edges", "==", []],
        ["output:analysis:json:results.vertex_feature_degree", "==", [0, 0, 0, 0, 0, 0, 0, 0]],
        # Only feature vertices carry an incident patch set (CGAL detect_vertex_incident_patches).
        ["output:analysis:json:results.segmentation.vertex_incident_patches", "==",
         [[], [], [], [], [], [], [], []]],
    ]),
    _case("features-bent-30", "mesh.features.detect", [B_BENT], {"angle_degrees": 30}, [
        # Two quads folded by 45 degrees along the edge (1,4): bound 30 splits them, with the six
        # border edges always being feature edges.
        ["metrics.sharp_edge_count", "==", 7],
        ["metrics.patch_count", "==", 2],
        ["output:analysis:json:results.sharp_edges", "==",
         [[0, 1], [0, 3], [1, 2], [1, 4], [2, 5], [3, 4], [4, 5]]],
        ["output:analysis:json:results.vertex_feature_degree", "==", [2, 3, 2, 2, 3, 2]],
    ]),
    _case("features-bent-60", "mesh.features.detect", [B_BENT], {"angle_degrees": 60}, [
        # The 45 degree fold is below the bound: only the border edges remain and the plate is one patch.
        ["metrics.sharp_edge_count", "==", 6],
        ["metrics.patch_count", "==", 1],
        ["output:analysis:json:results.sharp_edges", "==",
         [[0, 1], [0, 3], [1, 2], [2, 5], [3, 4], [4, 5]]],
        ["output:analysis:json:results.vertex_feature_degree", "==", [2, 2, 2, 2, 2, 2]],
    ]),
    _case("features-open-square", "mesh.features.detect", [Q_OPEN_SQUARE], {"angle_degrees": 10}, [
        ["metrics.sharp_edge_count", "==", 4],
        ["metrics.patch_count", "==", 1],
    ]),

]
B2_NEG_7_3 = [
    {"id": "features-angle-out-of-range-rejected", "operation": "mesh.features.detect", "inputs": [Q_CUBE],
     "parameters": {"angle_degrees": 200}, "expect_error_class": "INVALID_REQUEST",
     "expect_error_code": "INVALID_PARAMETER"},
    {"id": "features-tampered-missing-sharp-edge-rejected", "operation": "mesh.validate.features",
     "inputs": [_breport("tampered_features_report.json"), B_BENT], "parameters": {"angle_degrees": 30},
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SHARP_EDGES_MISMATCH"},
]

B2_CASES_7_5 = [
    _case("clip-cube-volume-x1", "mesh.clip.plane", [Q_CUBE], {**B_PLANE_X1, "clip_volume": True}, [
        # The half x <= 1 of the 0..2 cube is a closed box of volume 4 (cap in the plane x=1).
        ["metrics.input_face_count", "==", 12],
        ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::clip"],
        ["output:geometry:measure:off.boundary_edge_count", "==", 0],
        ["output:geometry:measure:off.signed_volume", "approx", [4.0, 1e-9]],
        ["output:geometry:measure:off.area", "approx", [16.0, 1e-9]],
    ]),
    _case("clip-cube-surface-x1", "mesh.clip.plane", [Q_CUBE], {**B_PLANE_X1, "clip_volume": False}, [
        # Surface clipping leaves the cube surface at x <= 1 open: 4 + 4 * 2 = 12 square units.
        ["output:geometry:measure:off.area", "approx", [12.0, 1e-9]],
        ["output:geometry:measure:off.boundary_edge_count", ">", 0],
    ]),
    _case("clip-cube-volume-diagonal", "mesh.clip.plane", [Q_CUBE], {**B_PLANE_DIAGONAL, "clip_volume": True}, [
        # x+y+z <= 3 passes through the cube centre: exactly half of the volume 8 remains.
        ["output:geometry:measure:off.boundary_edge_count", "==", 0],
        ["output:geometry:measure:off.signed_volume", "approx", [4.0, 1e-9]],
    ]),
    _case("clip-open-square-surface", "mesh.clip.plane", [Q_OPEN_SQUARE], {**B_PLANE_X1, "clip_volume": True}, [
        # An open mesh is clipped as a surface even when volume clipping is requested: half of 2x2.
        ["output:geometry:measure:off.area", "approx", [2.0, 1e-9]],
        ["output:geometry:measure:off.boundary_edge_count", ">", 0],
    ]),
    _case("split-cube-x1", "mesh.split.plane", [Q_CUBE], B_PLANE_X1, [
        # Splitting only refines and separates: the surface area 6 * 4 is preserved.
        ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::split"],
        ["output:geometry:measure:off.area", "approx", [24.0, 1e-9]],
    ]),
    _case("split-cube-diagonal", "mesh.split.plane", [Q_CUBE], B_PLANE_DIAGONAL, [
        ["output:geometry:measure:off.area", "approx", [24.0, 1e-9]],
    ]),
    _case("corefine-tetrahedra", "mesh.corefine", [Q_TETRA, B_TETRA_B], {}, [
        # Corefinement only refines the first tetrahedron (legs 2): area 6 + 2 sqrt(3), volume 4/3.
        ["metrics.input_face_count", "==", 4],
        ["metrics.output_face_count", ">", 4],
        ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::corefine"],
        ["output:geometry:measure:off.area", "approx", [6.0 + 2.0 * SQRT3, 1e-9]],
        ["output:geometry:measure:off.signed_volume", "approx", [4.0 / 3.0, 1e-9]],
        ["output:geometry:measure:off.boundary_edge_count", "==", 0],
    ]),
]
B2_NEG_7_5 = [
    {"id": "clip-coplanar-face-rejected", "operation": "mesh.clip.plane", "inputs": [Q_CUBE],
     "parameters": {"normal": [0, 0, 1], "offset": _mm_length(0), "clip_volume": True},
     "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "COPLANAR_FACE"},
    {"id": "clip-zero-normal-rejected", "operation": "mesh.clip.plane", "inputs": [Q_CUBE],
     "parameters": {"normal": [0, 0, 0], "offset": _mm_length(1), "clip_volume": True},
     "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "ZERO_NORMAL"},
    {"id": "split-coplanar-face-rejected", "operation": "mesh.split.plane", "inputs": [Q_CUBE],
     "parameters": {"normal": [0, 0, 1], "offset": _mm_length(0)},
     "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "COPLANAR_FACE"},
    {"id": "clip-uncut-candidate-rejected", "operation": "mesh.validate.clip", "inputs": [Q_CUBE, Q_CUBE],
     "parameters": {**B_PLANE_X1, "clip_volume": True}, "expect_error_class": "VALIDATION_FAILED",
     "expect_error_code": "VERTEX_ON_REMOVED_SIDE"},
    {"id": "clip-missing-region-rejected", "operation": "mesh.validate.clip",
     "inputs": [_bmesh("clip_tampered_strip.off"), Q_OPEN_SQUARE],
     "parameters": {**B_PLANE_X1, "clip_volume": False}, "expect_error_class": "VALIDATION_FAILED",
     "expect_error_code": "REGION_NOT_COVERED_EXACTLY"},
    {"id": "split-straddling-candidate-rejected", "operation": "mesh.validate.split",
     "inputs": [_qmesh("cube12.off", "PolygonSoup3"), Q_CUBE], "parameters": B_PLANE_X1,
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "TRIANGLE_STRADDLES_PLANE"},
    {"id": "corefine-unrefined-candidate-rejected", "operation": "mesh.validate.corefine",
     "inputs": [Q_TETRA, Q_TETRA, B_TETRA_B], "parameters": {},
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "TRIANGLE_CROSSED_BY_OTHER_SURFACE"},
]

B2_CASES_7_9 = [
    _case("spacing-line10", "pointset.spacing.average", [B_LINE], {"neighbors": 2}, [
        # Ten collinear points at unit spacing, k=2 (k+1 nearest including the point itself): the two
        # end points average (0+1+2)/3, the eight inner points (0+1+1)/3, so (2*3+8*2)/(3*10) = 11/15.
        ["metrics.point_count", "==", 10],
        ["metrics.neighbors", "==", 2],
        ["metrics.algorithm", "==", "CGAL::compute_average_spacing"],
        ["metrics.average_spacing", "approx", [11.0 / 15.0, 1e-12]],
        ["output:analysis:json:report_kind", "==", "average_spacing"],
        ["output:analysis:json:results.average_spacing.value", "approx", [11.0 / 15.0, 1e-12]],
        ["output:analysis:json:results.average_spacing.unit", "==", "mm"],
    ]),
    _case("outliers-remove-far-point", "pointset.remove_outliers", [B_CLUSTER],
          {"neighbors": 3, "threshold_percent": 10, "threshold_distance": _mm_length(3)}, [
        # A 3x3 unit grid and one point at (10,10,10): the far point exceeds the distance bound and is
        # the single removable point (10 percent of 10), the nine grid points stay.
        ["metrics.input_point_count", "==", 10],
        ["metrics.output_point_count", "==", 9],
        ["metrics.removed_point_count", "==", 1],
        ["input:points:measure:points.count", "==", 10],
        ["output:points:measure:points.count", "==", 9],
    ]),
    _case("outliers-quota-zero-percent", "pointset.remove_outliers", [B_CLUSTER],
          {"neighbors": 3, "threshold_percent": 0, "threshold_distance": _mm_length(3)}, [
        # At most 0 percent may be removed: every point is kept even though one exceeds the bound.
        ["metrics.output_point_count", "==", 10],
        ["metrics.removed_point_count", "==", 0],
    ]),
    _case("outliers-quota-half", "pointset.remove_outliers", [B_CLUSTER],
          {"neighbors": 3, "threshold_percent": 50, "threshold_distance": _mm_length(0)}, [
        # Distance 0 declares no point good, so CGAL keeps floor(10 * (100-50) / 100) = 5 points.
        ["metrics.output_point_count", "==", 5],
        ["metrics.removed_point_count", "==", 5],
        ["output:points:measure:points.count", "==", 5],
    ]),
    _case("spacing-cluster-k3", "pointset.spacing.average", [B_CLUSTER], {"neighbors": 3}, [
        # Chain step 1: the measured scale of the 3x3 grid plus the far point (brute-force k+1 nearest
        # average, point included; re-derived by the validator, pinned here to 1e-9).
        ["metrics.point_count", "==", 10],
        ["metrics.average_spacing", "approx", [1.8765368701257734, 1e-9]],
    ]),
    _case("outliers-threshold-from-spacing", "pointset.remove_outliers", [B_CLUSTER],
          {"neighbors": 3, "threshold_percent": 30, "threshold_distance": _mm_length(1.8765368701257734)}, [
        # Chain step 2: the measured spacing used as the distance bound, 30 percent removable: the far
        # point is the single removal although three could go.
        ["metrics.input_point_count", "==", 10],
        ["metrics.output_point_count", "==", 9],
        ["metrics.removed_point_count", "==", 1],
    ]),
]
B2_PAIRS_7_9 = [
    {"kind": "different_outputs", "cases": ["outliers-remove-far-point", "outliers-quota-zero-percent"]},
]
B2_NEG_7_9 = [
    {"id": "spacing-neighborhood-too-large-rejected", "operation": "pointset.spacing.average", "inputs": [B_LINE],
     "parameters": {"neighbors": 10}, "expect_error_class": "PRECONDITION_FAILED",
     "expect_error_code": "NEIGHBORHOOD_TOO_LARGE"},
    {"id": "spacing-tampered-value-rejected", "operation": "pointset.validate.average_spacing",
     "inputs": [_breport("tampered_spacing_report.json"), B_LINE], "parameters": {"neighbors": 2},
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "AVERAGE_SPACING_MISMATCH"},
    {"id": "outliers-good-point-removed-rejected", "operation": "pointset.validate.outliers_removed",
     "inputs": [_bpoints("tampered_outliers.xyz"), B_CLUSTER],
     "parameters": {"neighbors": 3, "threshold_percent": 10, "threshold_distance": _mm_length(3)},
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "REMOVED_POINT_LESS_OUTLYING"},
]

B2_CASES_7_12 = [
    _case("polygon-join-overlap", "polygon.boolean", [Q_SQUARE, B_SQUARE_SHIFT], {"operation": "join"}, [
        # [0,4]^2 joined with [2,6]^2: one octagon of area 28.
        ["metrics.polygon_count", "==", 1],
        ["metrics.hole_count", "==", 0],
        ["metrics.algorithm", "==", "CGAL::Polygon_set_2"],
        ["output:analysis:json:report_kind", "==", "polygon_boolean"],
        ["output:analysis:json:results.polygons.0.outer", "==",
         [["2", "6"], ["2", "4"], ["0", "4"], ["0", "0"], ["4", "0"], ["4", "2"], ["6", "2"], ["6", "6"]]],
    ]),
    _case("polygon-intersection-overlap", "polygon.boolean", [Q_SQUARE, B_SQUARE_SHIFT],
          {"operation": "intersection"}, [
        ["metrics.polygon_count", "==", 1],
        ["output:analysis:json:results.polygons.0.outer", "==", [["2", "2"], ["4", "2"], ["4", "4"], ["2", "4"]]],
    ]),
    _case("polygon-difference-overlap", "polygon.boolean", [Q_SQUARE, B_SQUARE_SHIFT],
          {"operation": "difference"}, [
        # [0,4]^2 minus [2,6]^2 is the hexagonal L of area 12.
        ["metrics.polygon_count", "==", 1],
        ["metrics.hole_count", "==", 0],
        ["output:analysis:json:results.polygons.0.outer", "==",
         [["0", "0"], ["4", "0"], ["4", "2"], ["2", "2"], ["2", "4"], ["0", "4"]]],
    ]),
    _case("polygon-difference-hole", "polygon.boolean", [Q_SQUARE, B_SQUARE_INNER], {"operation": "difference"}, [
        # [0,4]^2 minus the inner square [1,3]^2: one polygon with one clockwise hole.
        ["metrics.polygon_count", "==", 1],
        ["metrics.hole_count", "==", 1],
        ["output:analysis:json:results.polygons.0.outer", "==", [["0", "0"], ["4", "0"], ["4", "4"], ["0", "4"]]],
        ["output:analysis:json:results.polygons.0.holes", "==", [[["3", "3"], ["3", "1"], ["1", "1"], ["1", "3"]]]],
    ]),
    _case("polygon-join-disjoint", "polygon.boolean", [Q_SQUARE, B_SQUARE_FAR], {"operation": "join"}, [
        ["metrics.polygon_count", "==", 2],
        ["metrics.hole_count", "==", 0],
    ]),
    _case("polygon-intersection-disjoint", "polygon.boolean", [Q_SQUARE, B_SQUARE_FAR],
          {"operation": "intersection"}, [
        ["metrics.polygon_count", "==", 0],
        ["output:analysis:json:results.polygons", "==", []],
    ]),
    _case("polygon-intersection-clockwise-hexagon", "polygon.boolean", [B_HEXAGON_CW, Q_SQUARE],
          {"operation": "intersection"}, [
        # A clockwise operand is reversed. The hexagon (+-4, 0), (+-2, +-3.5) meets [0,4]^2 in the
        # quadrilateral (0,0), (4,0), (2,7/2), (0,7/2), one corner of which is a hexagon vertex.
        ["metrics.polygon_count", "==", 1],
        ["output:analysis:json:results.polygons.0.outer", "==",
         [["0", "0"], ["4", "0"], ["2", "7/2"], ["0", "7/2"]]],
    ]),
]
B2_NEG_7_12 = [
    {"id": "polygon-bowtie-operand-rejected", "operation": "polygon.boolean", "inputs": [B_BOWTIE, Q_SQUARE],
     "parameters": {"operation": "join"}, "expect_error_class": "PRECONDITION_FAILED",
     "expect_error_code": "POLYGON_NOT_SIMPLE"},
    {"id": "polygon-tampered-vertex-dropped-rejected", "operation": "polygon.validate.boolean",
     "inputs": [_breport("tampered_polygon_report.json"), Q_SQUARE, B_SQUARE_SHIFT],
     "parameters": {"operation": "join"}, "expect_error_class": "VALIDATION_FAILED",
     "expect_error_code": "BOUNDARY_CHAIN_MISMATCH"},
]

B2_CASES_7_13 = [
    _case("circle-right-triangle", "shape.bounding.circle", [B_CIRCLE], {}, [
        # (0,0), (4,0), (0,3) and the interior point (1,1): the hypotenuse (4,0)-(0,3) is a diameter,
        # so the circle has centre (2, 3/2) and radius 5/2.
        ["metrics.point_count", "==", 4],
        ["metrics.algorithm", "==", "CGAL::Min_circle_2"],
        ["metrics.radius", "approx", [2.5, 1e-12]],
        ["output:analysis:json:report_kind", "==", "minimum_bounding_ball"],
        ["output:analysis:json:results.center", "approx", [[2.0, 1.5], 1e-12]],
        ["output:analysis:json:results.radius.value", "approx", [2.5, 1e-12]],
    ]),
    _case("circle-two-points", "shape.bounding.circle", [B_CIRCLE_TWO], {}, [
        # Two points (0,0), (6,8) at distance 10: the diameter circle, centre (3,4), radius 5.
        ["metrics.radius", "approx", [5.0, 1e-12]],
        ["output:analysis:json:results.center", "approx", [[3.0, 4.0], 1e-12]],
    ]),
    _case("sphere-cube-corners", "shape.bounding.sphere", [B_CUBE_CORNERS], {"radius": _mm_length(0)}, [
        # The eight corners of the 0..2 cube: circumscribed sphere, centre (1,1,1), radius sqrt(3).
        ["metrics.point_count", "==", 8],
        ["metrics.algorithm", "==", "CGAL::Min_sphere_of_spheres_d"],
        ["metrics.radius", "approx", [SQRT3, 1e-12]],
        ["output:analysis:json:results.center", "approx", [[1.0, 1.0, 1.0], 1e-12]],
        ["output:analysis:json:results.radius.value", "approx", [SQRT3, 1e-12]],
    ]),
    _case("sphere-cube-corners-radius-half", "shape.bounding.sphere", [B_CUBE_CORNERS],
          {"radius": _mm_length(0.5)}, [
        # Balls of radius 1/2 around the same corners: the enclosing radius grows by exactly 1/2.
        ["metrics.radius", "approx", [SQRT3 + 0.5, 1e-12]],
        ["output:analysis:json:results.center", "approx", [[1.0, 1.0, 1.0], 1e-12]],
    ]),
]
B2_NEG_7_13 = [
    {"id": "sphere-negative-radius-rejected", "operation": "shape.bounding.sphere", "inputs": [B_CUBE_CORNERS],
     "parameters": {"radius": _mm_length(-1)}, "expect_error_class": "INVALID_REQUEST",
     "expect_error_code": "INVALID_PARAMETER"},
    {"id": "circle-tampered-radius-rejected", "operation": "shape.validate.min_circle",
     "inputs": [_breport("tampered_circle_report.json"), B_CIRCLE], "parameters": {},
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "RADIUS_MISMATCH"},
    {"id": "sphere-tampered-radius-rejected", "operation": "shape.validate.min_sphere",
     "inputs": [_breport("tampered_sphere_report.json"), B_CUBE_CORNERS], "parameters": {"radius": _mm_length(0)},
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "RADIUS_MISMATCH"},
]


FAMILY_7_3 = {
    "family": "7.3",
    "scope": "family_7_3_polygon_mesh_processing_core_partial",
    "evidence_path": "docs/master/evidence/family-7.3-capabilities.json",
    "test_id": "family-7.3-replay-cases",
    "requirements": {
        "major.7.3.05": {
            "operation_ids": ["mesh.features.detect"],
            "symbols": ["detect_sharp_edges", "sharp_edges_segmentation"],
            "symbol_notes": "CGAL::Polygon_mesh_processing::detect_sharp_edges and sharp_edges_segmentation run on the "
                            "0..2 cube (bound 30: the 12 cube edges are sharp, every corner has feature degree 3 and "
                            "the cube splits into its six faces; bound 100: no sharp edge, one patch), on a two-quad "
                            "plate folded by 45 degrees (bound 30 splits it into two patches along the fold edge, "
                            "bound 60 leaves one patch; the six border edges are always feature edges) and on an open "
                            "square. detect_sharp_edges and the segmentation must agree on the feature set. The "
                            "independent validator recomputes each edge decision from exact rational face normals "
                            "(only the irrational cosine of the bound is long double; edges within 1e-9 relative of "
                            "the bound are rejected as ambiguous, not guessed), the vertex feature degrees, the face "
                            "components across non-sharp interior edges and the per-vertex incident patch sets "
                            "(defined only at feature vertices, as in CGAL detect_vertex_incident_patches).",
            "case_ids": ["features-cube-30", "features-cube-100", "features-bent-30", "features-bent-60",
                         "features-open-square"],
        },
        "major.7.3.01": {
            "operation_ids": ["mesh.inspect.pmp", "mesh.analysis.self_intersections"],
            "symbols": ["does_self_intersect", "is_closed", "is_triangle_mesh"],
            "case_ids": ["inspect-closed-tetra", "inspect-open-tetra", "inspect-quad-cube",
                         "self-intersection-free-tetra", "self-intersecting-tetrahedra"],
        },
        "major.7.3.02": {
            "operation_ids": ["mesh.components.label", "mesh.components.component", "mesh.components.keep_largest"],
            "symbols": ["connected_components", "connected_component", "keep_largest_connected_components"],
            "symbol_notes": "three_components.off holds two outward tetrahedra (volume 4/3 each) and one lone "
                            "triangle (9 faces). connected_components labels the faces 0..2 and reports "
                            "component_count 3; connected_component from seed face 4 extracts the second tetrahedron "
                            "(4 vertices, 4 faces, volume 4/3) and from seed face 8 the lone triangle; "
                            "keep_largest_connected_components keeps the two tetrahedra (8 faces, volume 8/3), while "
                            "keeping one is a tie and is rejected. Independent validators recompute the components by "
                            "union-find over shared undirected edges and compare face sets by exact vertex "
                            "coordinates.",
            "case_ids": ["components-label-three", "components-extract-second-tetra", "components-extract-lone-triangle",
                         "components-keep-two-largest"],
        },
        "major.7.3.03": {
            "operation_ids": ["mesh.analysis.normals"],
            "symbols": ["compute_face_normals", "compute_vertex_normals", "compute_normals"],
            "symbol_notes": "CGAL 6.2.1 compute_normal.h compute_normals() calls "
                            "compute_face_normals() and compute_vertex_normals(); counts and the "
                            "exact per-face/per-vertex values on the axis-aligned cube (and the "
                            "negated values on its inward-wound twin) are asserted by the replay "
                            "harness against hand-derived constants. The mandatory validator "
                            "re-runs the same worker code and is a consistency check only, not "
                            "an independent oracle.",
            "case_ids": ["normals-tetra", "normals-cube", "normals-inward-cube"],
        },
        "major.7.3.04": {
            "operation_ids": ["mesh.analysis.measures"],
            "symbols": ["area", "volume", "centroid"],
            "case_ids": ["measures-tetra", "measures-cube"],
        },
        "major.7.3.08": {
            "operation_ids": ["mesh.location.locate"],
            "symbols": ["locate", "locate_with_AABB_tree"],
            "symbol_notes": "PMP::locate and PMP::locate_with_AABB_tree (prebuilt AABB tree) locate seven hand-placed "
                            "queries on the 0..2 cube in EPECK; barycentric coordinates are reported in the face's "
                            "input vertex order as exact rationals. The independent validator checks that the "
                            "barycentric combination reproduces the reported point and that it is an exact closest "
                            "point of the whole mesh (brute force over every triangle in GMP rationals). Queries "
                            "equidistant from several faces are asserted by distance only.",
            "case_ids": ["location-brute-force", "location-aabb-tree"],
        },
    },
    "unbound": {
        "major.7.3.07": "Self-intersection (self_intersections, does_self_intersect) is replayed through "
                        "mesh.analysis.self_intersections, but intersections between two meshes "
                        "(do_intersect/surface_intersection) are not an executable operation.",
        "major.7.3.06": "Only bounded_error_symmetric_Hausdorff_distance is executable, as the "
                        "simplification validator; sample_triangle_mesh, max_distance_to_triangle_mesh, "
                        "approximate/one-sided Hausdorff and approximate_max_distance_to_point_set "
                        "are not exposed.",
    },
    "cases": [
        *B2_CASES_7_3,
        _case("inspect-closed-tetra", "mesh.inspect.pmp", [_mesh(TETRA)], {}, [
            ["output:analysis:json:mesh_summary.closed", "==", True],
            ["output:analysis:json:mesh_summary.triangulated", "==", True],
            ["output:analysis:json:results.polygon_mesh_valid", "==", True],
        ]),
        _case("inspect-open-tetra", "mesh.inspect.pmp", [_mesh(OPEN_TETRA)], {}, [
            ["output:analysis:json:mesh_summary.closed", "==", False],
            ["output:analysis:json:mesh_summary.triangulated", "==", True],
            ["input:mesh:measure:off.boundary_edge_count", "==", 3],
        ]),
        _case("inspect-quad-cube", "mesh.inspect.pmp", [_mesh(QUAD_CUBE, "PolygonSoup3")], {}, [
            ["output:analysis:json:mesh_summary.closed", "==", True],
            ["output:analysis:json:mesh_summary.triangulated", "==", False],
            ["input:mesh:measure:off.max_face_degree", "==", 4],
        ]),
        _case("self-intersection-free-tetra", "mesh.analysis.self_intersections",
              [_mesh(TETRA)], {}, [
            ["output:analysis:json:results.does_self_intersect", "==", False],
            ["output:analysis:json:results.intersection_pair_count", "==", 0],
        ]),
        _case("self-intersecting-tetrahedra", "mesh.analysis.self_intersections",
              [_mesh(INTERSECTING)], {}, [
            ["output:analysis:json:results.does_self_intersect", "==", True],
            ["output:analysis:json:results.intersection_pair_count", ">", 0],
            ["output:analysis:json:mesh_summary.closed", "==", True],
        ]),
        _case("normals-tetra", "mesh.analysis.normals", [_mesh(TETRA)], {}, [
            ["metrics.face_normal_count", "==", 4],
            ["metrics.vertex_normal_count", "==", 4],
            ["metrics.zero_face_normal_count", "==", 0],
            ["metrics.zero_vertex_normal_count", "==", 0],
        ]),
        _case("normals-cube", "mesh.analysis.normals", [_mesh(CUBE_A)], {}, [
            ["metrics.face_normal_count", "==", 12],
            ["metrics.vertex_normal_count", "==", 8],
            ["metrics.zero_face_normal_count", "==", 0],
            ["metrics.zero_vertex_normal_count", "==", 0],
            ["output:analysis:json:results.face_normals[*].normal.value", "approx",
             [CUBE_FACE_NORMALS, 1e-9]],
            ["output:analysis:json:results.vertex_normals[*].normal.value", "approx",
             [CUBE_VERTEX_NORMALS, 1e-9]],
            ["input:mesh:measure:off.signed_volume", "approx", [8.0, 1e-12]],
        ]),
        # Orientation negative control: the same cube with inward winding must report the
        # exactly negated normals, so flipped or sign-wrong normals cannot satisfy both cases.
        _case("normals-inward-cube", "mesh.analysis.normals", [_mesh(INWARD_CUBE)], {}, [
            ["input:mesh:measure:off.signed_volume", "approx", [-8.0, 1e-12]],
            ["output:analysis:json:results.face_normals[*].normal.value", "approx",
             [INWARD_FACE_NORMALS, 1e-9]],
            ["output:analysis:json:results.vertex_normals[*].normal.value", "approx",
             [INWARD_VERTEX_NORMALS, 1e-9]],
        ]),
        _case("measures-tetra", "mesh.analysis.measures", [_mesh(TETRA)], {}, [
            ["output:analysis:json:results.surface_area.value", "approx", [1.5 + SQRT3_HALF, 1e-12]],
            ["output:analysis:json:results.surface_area.unit", "==", "mm^2"],
            ["output:analysis:json:results.signed_volume.value", "approx", [1.0 / 6.0, 1e-12]],
            ["output:analysis:json:results.signed_volume.unit", "==", "mm^3"],
            ["output:analysis:json:results.volume_centroid.value", "approx", [[0.25, 0.25, 0.25], 1e-12]],
            ["input:mesh:measure:off.signed_volume", "approx", [1.0 / 6.0, 1e-12]],
        ]),
        _case("measures-cube", "mesh.analysis.measures", [_mesh(CUBE_A)], {}, [
            ["output:analysis:json:results.surface_area.value", "approx", [24.0, 1e-12]],
            ["output:analysis:json:results.signed_volume.value", "approx", [8.0, 1e-12]],
            ["output:analysis:json:results.volume_centroid.value", "approx", [[1.0, 1.0, 1.0], 1e-12]],
            ["output:analysis:json:results.volume_centroid.unit", "==", "mm"],
        ]),
        _case("components-label-three", "mesh.components.label", [Q_THREE], {}, [
            ["metrics.face_count", "==", 9],
            ["metrics.component_count", "==", 3],
            ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::connected_components"],
            ["output:analysis:json:report_kind", "==", "connected_components"],
            ["output:analysis:json:results.component_count", "==", 3],
            ["output:analysis:json:results.face_labels", "==", [0, 0, 0, 0, 1, 1, 1, 1, 2]],
            ["output:analysis:json:results.component_sizes", "==", [4, 4, 1]],
        ]),
        _case("components-extract-second-tetra", "mesh.components.component", [Q_THREE], {"face": 4}, [
            ["output:geometry:measure:off.vertex_count", "==", 4],
            ["output:geometry:measure:off.face_count", "==", 4],
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.signed_volume", "approx", [4.0 / 3.0, 1e-12]],
            ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::connected_component"],
        ]),
        _case("components-extract-lone-triangle", "mesh.components.component", [Q_THREE], {"face": 8}, [
            ["output:geometry:measure:off.vertex_count", "==", 3],
            ["output:geometry:measure:off.face_count", "==", 1],
            ["output:geometry:measure:off.boundary_edge_count", "==", 3],
        ]),
        _case("components-keep-two-largest", "mesh.components.keep_largest", [Q_THREE], {"count": 2}, [
            ["output:geometry:measure:off.vertex_count", "==", 8],
            ["output:geometry:measure:off.face_count", "==", 8],
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.signed_volume", "approx", [8.0 / 3.0, 1e-12]],
            ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::keep_largest_connected_components"],
        ]),
        _locate_case("location-brute-force", "locate", "CGAL::Polygon_mesh_processing::locate"),
        _locate_case("location-aabb-tree", "locate_with_AABB_tree",
                     "CGAL::Polygon_mesh_processing::locate_with_AABB_tree"),
    ],
    "pairs": [],
    "negative_controls": [
        *B2_NEG_7_3,
        {"id": "components-keep-one-tie-rejected", "operation": "mesh.components.keep_largest",
         "inputs": [Q_THREE], "parameters": {"count": 1},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "AMBIGUOUS_COMPONENT_TIE"},
        {"id": "components-seed-face-out-of-range-rejected", "operation": "mesh.components.component",
         "inputs": [Q_THREE], "parameters": {"face": 9},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "components-tampered-partition-rejected", "operation": "mesh.validate.components_label",
         "inputs": [_qjson("tampered_components_report.json", "GeometryQueryReport", "none"), Q_THREE],
         "parameters": {}, "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "PARTITION_MISMATCH"},
        {"id": "location-tampered-distance-rejected", "operation": "mesh.validate.location",
         "inputs": [_qjson("tampered_location_report.json", "GeometryQueryReport", "none"), Q_CUBE, Q_LOCATE_POINTS],
         "parameters": {"strategy": "locate"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "DISTANCE_MISMATCH"},
    ],
}

_REPAIR_UNCHANGED_UNIT = ["output:geometry:sha256", "!=", {"path": "input:source:sha256"}]

FAMILY_7_4 = {
    "family": "7.4",
    "scope": "family_7_4_mesh_repair_partial",
    "evidence_path": "docs/master/evidence/family-7.4-capabilities.json",
    "test_id": "family-7.4-replay-cases",
    "requirements": {
        "major.7.4.01": {
            "operation_ids": ["mesh.repair.orient"],
            "symbols": ["orient_to_bound_a_volume", "orient_polygon_soup"],
            "case_ids": ["orient-flipped-soup", "orient-inward-cube"],
        },
        "major.7.4.02": {
            "operation_ids": ["mesh.repair.stitch_borders"],
            "symbols": ["stitch_borders"],
            "case_ids": ["stitch-duplicated-seam"],
        },
        "major.7.4.03": {
            "operation_ids": ["mesh.repair.remove_degenerate"],
            "symbols": ["remove_degenerate_faces", "remove_degenerate_edges"],
            "case_ids": ["degenerate-collinear-face", "degenerate-zero-length-edge"],
        },
        "major.7.4.05": {
            "operation_ids": ["mesh.repair.polygon_soup"],
            "symbols": ["repair_polygon_soup"],
            "case_ids": ["soup-dirty-keep-one", "soup-duplicates-keep-one",
                         "soup-duplicates-erase-all"],
        },
        "major.7.4.06": {
            "operation_ids": ["mesh.repair.manifold_preprocess"],
            "symbols": ["duplicate_non_manifold_vertices", "non_manifold_vertices"],
            "symbol_notes": "CGAL 6.2.1 manifoldness.h duplicate_non_manifold_vertices() collects "
                            "cones through non_manifold_vertices(); the case asserts one repaired "
                            "non-manifold group and a manifold closed candidate.",
            "case_ids": ["manifold-pinched-vertex"],
        },
    },
    "unbound": {},
    "cases": [
        _case("orient-flipped-soup", "mesh.repair.orient", [_mesh(FLIPPED_SOUP, "PolygonSoup3")], {}, [
            ["metrics.orientation_changed", "==", True],
            ["metrics.candidate.mesh.closed", "==", True],
            ["metrics.candidate.mesh.outward_oriented", "==", True],
            ["metrics.source.polygon_mesh_constructible", "==", False],
            ["output:geometry:measure:off.signed_volume", "approx", [1.0 / 6.0, 1e-12]],
            _REPAIR_UNCHANGED_UNIT,
        ]),
        _case("orient-inward-cube", "mesh.repair.orient", [_mesh(INWARD_CUBE, "PolygonSoup3")], {}, [
            ["metrics.orientation_changed", "==", True],
            ["metrics.source.mesh.outward_oriented", "==", False],
            ["metrics.candidate.mesh.outward_oriented", "==", True],
            ["input:source:measure:off.signed_volume", "approx", [-8.0, 1e-12]],
            ["output:geometry:measure:off.signed_volume", "approx", [8.0, 1e-12]],
        ]),
        _case("stitch-duplicated-seam", "mesh.repair.stitch_borders", [_mesh(SEAM)], {}, [
            ["metrics.stitched_pair_count", ">=", 1],
            ["input:source:measure:off.vertex_count", "==", 6],
            ["output:geometry:measure:off.vertex_count", "==", 4],
            ["output:geometry:measure:off.boundary_edge_count", "==", 4],
            ["input:source:measure:off.boundary_edge_count", "==", 6],
        ]),
        _case("degenerate-collinear-face", "mesh.repair.remove_degenerate",
              [_mesh(DEGENERATE_FACE, "PolygonSoup3")], {}, [
            ["metrics.source.degenerate_face_count", "==", 1],
            ["metrics.candidate.degenerate_face_count", "==", 0],
            ["metrics.remove_degenerate_faces_complete", "==", True],
            ["metrics.remove_degenerate_edges_complete", "==", True],
            ["output:geometry:measure:off.face_count", "==", 4],
        ]),
        _case("degenerate-zero-length-edge", "mesh.repair.remove_degenerate",
              [_mesh(ZERO_EDGE, "PolygonSoup3")], {}, [
            ["input:source:measure:off.min_edge_length", "==", 0.0],
            ["metrics.source.degenerate_face_count", "==", 2],
            ["metrics.source.duplicate_point_count", "==", 1],
            ["metrics.candidate.degenerate_face_count", "==", 0],
            ["metrics.candidate.mesh.closed", "==", True],
            ["metrics.remove_degenerate_edges_complete", "==", True],
            ["output:geometry:measure:off.min_edge_length", ">", 0.0],
            ["output:geometry:measure:off.vertex_count", "==", 4],
            ["output:geometry:measure:off.signed_volume", "approx", [1.0 / 6.0, 1e-12]],
        ]),
        _case("soup-dirty-keep-one", "mesh.repair.polygon_soup",
              [_mesh(DIRTY_SOUP, "PolygonSoup3")],
              {"duplicate_polygon_policy": "keep_one", "require_same_orientation": False}, [
            ["metrics.source.duplicate_point_count", ">", 0],
            ["metrics.source.degenerate_face_count", ">", 0],
            ["metrics.candidate.duplicate_point_count", "==", 0],
            ["metrics.candidate.degenerate_face_count", "==", 0],
            ["metrics.candidate.duplicate_face_count", "==", 0],
            ["metrics.candidate.unused_point_count", "==", 0],
        ]),
        _case("soup-duplicates-keep-one", "mesh.repair.polygon_soup",
              [_mesh(DUPLICATE_FACES, "PolygonSoup3")],
              {"duplicate_polygon_policy": "keep_one", "require_same_orientation": False}, [
            ["metrics.source.face_count", "==", 3],
            ["metrics.candidate.duplicate_face_count", "==", 0],
            ["metrics.candidate.face_count", "==", 2],
        ]),
        _case("soup-duplicates-erase-all", "mesh.repair.polygon_soup",
              [_mesh(DUPLICATE_FACES, "PolygonSoup3")],
              {"duplicate_polygon_policy": "erase_all", "require_same_orientation": False}, [
            ["metrics.candidate.duplicate_face_count", "==", 0],
            ["metrics.candidate.face_count", "==", 1],
        ]),
        _case("manifold-pinched-vertex", "mesh.repair.manifold_preprocess", [_mesh(NONMANIFOLD)], {}, [
            ["metrics.source.polygon_mesh_constructible", "==", False],
            ["metrics.repaired_vertex_group_count", "==", 1],
            ["metrics.candidate.mesh.closed", "==", True],
            ["metrics.candidate.mesh.non_manifold_vertex_count", "==", 0],
            ["metrics.duplicated_vertex_count", "==", 1],
            ["input:source:measure:off.vertex_count", "==", 7],
            ["output:geometry:measure:off.vertex_count", "==", 8],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["soup-duplicates-keep-one", "soup-duplicates-erase-all"]},
    ],
    "negative_controls": [],
}

# --- Batch 3 (7.5.01, 7.11.03, 7.11.05, 7.12.02, 7.12.03, 7.12.07) ---------------------------------
B3_FIXTURES = {
    "arr_boxes.json": "4ceaaa7786a26f05486c3bee9bd97bbf25c991895c6612f22aa6190505aff9cf",
    "arr_cross.json": "e59422011904d8245ed2a40c3f4298b715e4cd475b5c8e478ca9771f1bae12d7",
    "arr_zero_length.json": "11764ac634ad2147568ade5d65e25c3b7244e16768c1da8244e18a583a8de81f",
    "points_collinear.json": "b5b85285e14b084dedd29f808458516f3966e1534391d0fe362b54418e3a261d",
    "points_duplicate.json": "264ea9c9dc5e248f0b01452a8db698080089c954393ffe4dc4462b2517dc7e6a",
    "polygon_c.json": "d7d90a73371c60a39ec29dc11aa3e1a3e6183395671582596675e61ed785e5ae",
    "polygon_u.json": "7f2d2024c3f835edd181cac2b5fa1543540bf8e8e25fb665d2e9938de7eb8583",
    "reg2_points.json": "ce5194b8022b68aee33f6d234db2c74237296505d609d587df103f6e014dc006",
    "reg3_points.xyz": "75353c9b58e92145e7d8085532c9b54a1931317569ec8944a3abe08508ae89ed",
    "square_three.json": "143fd300fcb208bd8b4eb0945faabb63247ce11083f4f341b98c3efa24476785",
    "square_two.json": "49a6184ffd1841d9edf22ee626a806a37b7d1272341bc958471873b813b2e5d2",
    "square_unit.json": "fce05e7de4410ba2a05128b7a83dba333db7caa23803fd0abfed555bc7ce8b50",
    "tampered_arrangement_edge_dropped_report.json": "5e0090d2cfba6f663372e335deb472beab08d3b7bda28ae7f46bfc2a94e34c66",
    "tampered_arrangement_face_dropped_report.json": "e3faafefb1cb12075a703ac716f5c661d17af1a2685021edaac1ba9cb01b498a",
    "tampered_minkowski_hole_dropped_report.json": "f27890a4f94998cab474a28a42f04ae2d0a0016d2a4975b5226e4ff18871aad5",
    "tampered_minkowski_vertex_moved_report.json": "6d1912484de152e1a617ca21e816da384e82f6dc7b58ba57dae3fd52bcc97825",
    "tampered_overlay_label_report.json": "5989b8becabbb9d326db0d2dc379922650f216b4818f363a392420dbcbbd046e",
    "tampered_regular2_hidden_report.json": "bfaa7e3fe01102caa8f287efe1fc61b6aaf232cae37180e6e1e48e9c6dc35488",
    "tampered_regular2_nonregular_report.json": "ed18b90810ffcaef347cb30978ebfe43e0350397fa7fae4d467761dd93254e9a",
    "tampered_regular3_hidden_report.json": "1815f9e028b1d285c0d5b64e1a929351dc38317f68c0982174439f3a38fff6d4",
    "tampered_regular3_missing_cell_report.json": "2bc90fdc2ccbb82e364a9fb44b608b5547dd583172a25cff0cdd99b74df97629",
    "tampered_voronoi_edge_report.json": "b200d38aa6f2b2857c84f3114741533b130adfcaf69e2477b6a27902f25e4fc2",
    "tampered_voronoi_vertex_report.json": "5a0f853561d34e73acad75e39b88f42060d973500135cf5ed7d28263a9df66ed",
    "tampered_zone_vertex_dropped_report.json": "24b0ef8343e497d9c12868c00986f241b3abc6d207ff64114989f86ceccca4d7",
    "triangle_a.json": "caa42122c3456b7b903003cb0df40c95c39dc34d90b8a719ef4e1cfef5d91e8b",
    "voronoi_scatter.json": "e796215dced20c143fbb39e930768783140122769ac94de476e4c3bc235ff569",
    "voronoi_square_center.json": "e0b44a0f257656629ffac21700fe3e79ff2452cf474689e71ea5ce37f1de3d62",
    "zone_diagonal.json": "0558b76fe198eebc05869b7d0e693e70db95dbb4a7814f5c95e463beed6fdcc2",
    "zone_horizontal.json": "150679b0a495a99e2ee4c94eedc13bdcfe0f994ae61d211ac3f67127988a9764",
    "zone_outside.json": "3e780cbdfbffa7facf49b7bd88c3e9ec03fafb4de00feb5dea5f3da002eae3e9",
    "zone_two_segments.json": "c7402a9b10dd5b3554c0fd1168e730f9fc201fd104a70982ed3dcd1d313d46b5",
}


def _b3fx(name: str) -> dict:
    return {"fixture": f"batch3/{name}", "sha256": B3_FIXTURES[name]}


def _b3json(name: str, type_: str) -> dict:
    return {**_b3fx(name), "type": type_, "format": "json", "unit": "mm"}


def _b3report(name: str) -> dict:
    return {**_b3fx(name), "type": "GeometryQueryReport", "format": "json", "unit": "none"}


B3_REG2 = _b3json("reg2_points.json", "PointSet2")
B3_REG3 = {**_b3fx("reg3_points.xyz"), "type": "PointSet3", "format": "xyz", "unit": "mm"}
B3_VORONOI_SQUARE = _b3json("voronoi_square_center.json", "PointSet2")
B3_VORONOI_SCATTER = _b3json("voronoi_scatter.json", "PointSet2")
B3_ARR_CROSS = _b3json("arr_cross.json", "SegmentGraph2")
B3_ARR_BOXES = _b3json("arr_boxes.json", "SegmentGraph2")
B3_ZONE_HORIZONTAL = _b3json("zone_horizontal.json", "SegmentGraph2")
B3_ZONE_DIAGONAL = _b3json("zone_diagonal.json", "SegmentGraph2")
B3_ZONE_OUTSIDE = _b3json("zone_outside.json", "SegmentGraph2")
B3_SQUARE_TWO = _b3json("square_two.json", "Polygon2")
B3_SQUARE_UNIT = _b3json("square_unit.json", "Polygon2")
B3_TRIANGLE = _b3json("triangle_a.json", "Polygon2")
B3_POLYGON_C = _b3json("polygon_c.json", "Polygon2")
B3_POLYGON_U = _b3json("polygon_u.json", "Polygon2")
B3_SQUARE_THREE = _b3json("square_three.json", "Polygon2")
B3_W2_ZERO = [0, 0, 0, 0, 0, 0]
B3_W2_HIDDEN = [0, 0, 0, 0, -10, 0]
B3_W2_HEAVY = [0, 0, 0, 0, 50, 0]
B3_W3_ZERO = [0] * 10
B3_W3_HIDDEN = [0] * 8 + [-10, 0]
B3_MINKOWSKI_ALGORITHMS = {
    "polygon.minkowski_sum": "CGAL::minkowski_sum_2",
    "polygon.minkowski_sum_reduced_convolution": "CGAL::minkowski_sum_by_reduced_convolution_2",
}

B3_CASES_7_11 = [
    _case("regular2-zero-weights", "triangulation.regular_2", [B3_REG2], {"weights": B3_W2_ZERO}, [
        ["metrics.algorithm", "==", "CGAL::Regular_triangulation_2"],
        ["metrics.input_point_count", "==", 6],
        ["metrics.hidden_count", "==", 0],
        ["output:analysis:json:report_kind", "==", "regular_triangulation_2"],
        ["output:analysis:json:results.hidden", "==", []],
        ["output:analysis:json:results.weight_unit", "==", "mm^2"],
    ]),
    _case("regular2-hidden-point", "triangulation.regular_2", [B3_REG2], {"weights": B3_W2_HIDDEN}, [
        ["metrics.hidden_count", "==", 1],
        ["output:analysis:json:results.hidden", "==", [4]],
    ]),
    _case("regular3-zero-weights", "triangulation.regular_3", [B3_REG3], {"weights": B3_W3_ZERO}, [
        ["metrics.algorithm", "==", "CGAL::Regular_triangulation_3"],
        ["metrics.input_point_count", "==", 10],
        ["metrics.hidden_count", "==", 0],
        ["output:analysis:json:report_kind", "==", "regular_triangulation_3"],
    ]),
    _case("regular3-hidden-point", "triangulation.regular_3", [B3_REG3], {"weights": B3_W3_HIDDEN}, [
        ["metrics.hidden_count", "==", 1],
        ["output:analysis:json:results.weight_unit", "==", "mm^2"],
    ]),
    _case("voronoi-square-centre", "triangulation.voronoi_dual", [B3_VORONOI_SQUARE], {}, [
        ["metrics.algorithm", "==", "CGAL::Voronoi_diagram_2"],
        ["metrics.site_count", "==", 5],
        ["output:analysis:json:report_kind", "==", "voronoi_diagram_2"],
    ]),
    _case("voronoi-scatter", "triangulation.voronoi_dual", [B3_VORONOI_SCATTER], {}, [
        ["metrics.site_count", "==", 6],
    ]),
]
B3_NEG_7_11 = [
    {"id": "regular2-weight-count-rejected", "operation": "triangulation.regular_2", "inputs": [B3_REG2],
     "parameters": {"weights": [0, 0, 0]}, "expect_error_class": "INVALID_REQUEST"},
    {"id": "regular2-duplicate-point-rejected", "operation": "triangulation.regular_2",
     "inputs": [_b3json("points_duplicate.json", "PointSet2")], "parameters": {"weights": [0, 0, 0, 0]},
     "expect_error_class": "PRECONDITION_FAILED"},
    {"id": "regular2-collinear-rejected", "operation": "triangulation.regular_2",
     "inputs": [_b3json("points_collinear.json", "PointSet2")], "parameters": {"weights": [0, 0, 0, 0]},
     "expect_error_class": "PRECONDITION_FAILED"},
    {"id": "voronoi-collinear-rejected", "operation": "triangulation.voronoi_dual",
     "inputs": [_b3json("points_collinear.json", "PointSet2")], "parameters": {},
     "expect_error_class": "PRECONDITION_FAILED"},
    {"id": "regular2-tampered-hidden-rejected", "operation": "triangulation.validate.regular_2",
     "inputs": [_b3report("tampered_regular2_hidden_report.json"), B3_REG2], "parameters": {"weights": B3_W2_ZERO},
     "expect_error_class": "VALIDATION_FAILED"},
    {"id": "regular2-tampered-nonregular-rejected", "operation": "triangulation.validate.regular_2",
     "inputs": [_b3report("tampered_regular2_nonregular_report.json"), B3_REG2],
     "parameters": {"weights": B3_W2_HEAVY}, "expect_error_class": "VALIDATION_FAILED"},
    {"id": "regular3-tampered-hidden-rejected", "operation": "triangulation.validate.regular_3",
     "inputs": [_b3report("tampered_regular3_hidden_report.json"), B3_REG3], "parameters": {"weights": B3_W3_ZERO},
     "expect_error_class": "VALIDATION_FAILED"},
    {"id": "regular3-tampered-missing-cell-rejected", "operation": "triangulation.validate.regular_3",
     "inputs": [_b3report("tampered_regular3_missing_cell_report.json"), B3_REG3],
     "parameters": {"weights": B3_W3_ZERO}, "expect_error_class": "VALIDATION_FAILED"},
    {"id": "voronoi-tampered-edge-rejected", "operation": "triangulation.validate.voronoi_dual",
     "inputs": [_b3report("tampered_voronoi_edge_report.json"), B3_VORONOI_SCATTER], "parameters": {},
     "expect_error_class": "VALIDATION_FAILED"},
    {"id": "voronoi-tampered-vertex-rejected", "operation": "triangulation.validate.voronoi_dual",
     "inputs": [_b3report("tampered_voronoi_vertex_report.json"), B3_VORONOI_SCATTER], "parameters": {},
     "expect_error_class": "VALIDATION_FAILED"},
]


def _minkowski_cases(operation: str, tag: str) -> list[dict]:
    algorithm = B3_MINKOWSKI_ALGORITHMS[operation]
    return [
        _case(f"{tag}-square-triangle", operation, [B3_SQUARE_TWO, B3_TRIANGLE], {}, [
            ["metrics.algorithm", "==", algorithm],
            ["metrics.hole_count", "==", 0],
            ["output:analysis:json:report_kind", "==", "minkowski_sum_2"],
        ]),
        _case(f"{tag}-closed-gap-hole", operation, [B3_POLYGON_U, B3_SQUARE_THREE], {}, [
            ["metrics.hole_count", "==", 1],
        ]),
        _case(f"{tag}-nonconvex-no-hole", operation, [B3_POLYGON_C, B3_SQUARE_TWO], {}, [
            ["metrics.hole_count", "==", 0],
        ]),
    ]


B3_CASES_7_12 = [
    *_minkowski_cases("polygon.minkowski_sum", "minkowski"),
    *_minkowski_cases("polygon.minkowski_sum_reduced_convolution", "minkowski-reduced"),
    _case("arrangement-concurrent-segments", "arrangement.build", [B3_ARR_CROSS], {}, [
        ["metrics.algorithm", "==", "CGAL::Arrangement_2"],
        ["output:analysis:json:report_kind", "==", "arrangement_2"],
    ]),
    _case("arrangement-nested-components", "arrangement.build", [B3_ARR_BOXES], {}, [
        ["metrics.face_count", "==", 3],
    ]),
    _case("zone-through-vertices", "arrangement.zone", [B3_ARR_CROSS, B3_ZONE_DIAGONAL], {}, [
        ["metrics.algorithm", "==", "CGAL::zone"],
        ["output:analysis:json:report_kind", "==", "arrangement_zone"],
    ]),
    _case("zone-crossing-edges", "arrangement.zone", [B3_ARR_BOXES, B3_ZONE_HORIZONTAL], {}, [
        ["metrics.vertex_count", "==", 0],
    ]),
    _case("zone-diagonal-vertices-faces", "arrangement.zone", [B3_ARR_BOXES, B3_ZONE_DIAGONAL], {}, [
        ["metrics.edge_count", "==", 0],
    ]),
    _case("zone-outside", "arrangement.zone", [B3_ARR_BOXES, B3_ZONE_OUTSIDE], {}, [
        ["metrics.face_count", "==", 1],
    ]),
    _case("overlay-square-corner", "arrangement.overlay", [B3_SQUARE_TWO, B3_SQUARE_UNIT], {}, [
        ["metrics.algorithm", "==", "CGAL::overlay"],
        ["output:analysis:json:report_kind", "==", "arrangement_overlay"],
    ]),
    _case("overlay-inscribed-triangle", "arrangement.overlay", [B3_SQUARE_TWO, B3_TRIANGLE], {}, [
        ["metrics.face_count", "==", 4],
    ]),
    _case("overlay-nonconvex", "arrangement.overlay", [B3_POLYGON_U, B3_SQUARE_THREE], {}, [
        ["metrics.face_count", ">", 2],
    ]),
]
B3_NEG_7_12 = [
    {"id": "minkowski-bowtie-operand-rejected", "operation": "polygon.minkowski_sum",
     "inputs": [B_BOWTIE, B3_SQUARE_TWO], "parameters": {}, "expect_error_class": "PRECONDITION_FAILED"},
    {"id": "minkowski-tampered-hole-dropped-rejected", "operation": "polygon.validate.minkowski_sum",
     "inputs": [_b3report("tampered_minkowski_hole_dropped_report.json"), B3_POLYGON_U, B3_SQUARE_THREE],
     "parameters": {}, "expect_error_class": "VALIDATION_FAILED"},
    {"id": "minkowski-tampered-vertex-moved-rejected", "operation": "polygon.validate.minkowski_sum",
     "inputs": [_b3report("tampered_minkowski_vertex_moved_report.json"), B3_SQUARE_TWO, B3_TRIANGLE],
     "parameters": {}, "expect_error_class": "VALIDATION_FAILED"},
    {"id": "arrangement-zero-length-segment-rejected", "operation": "arrangement.build",
     "inputs": [_b3json("arr_zero_length.json", "SegmentGraph2")], "parameters": {},
     "expect_error_class": "PRECONDITION_FAILED"},
    {"id": "zone-two-segment-query-rejected", "operation": "arrangement.zone",
     "inputs": [B3_ARR_BOXES, _b3json("zone_two_segments.json", "SegmentGraph2")], "parameters": {},
     "expect_error_class": "PRECONDITION_FAILED"},
    {"id": "overlay-bowtie-operand-rejected", "operation": "arrangement.overlay",
     "inputs": [B_BOWTIE, B3_SQUARE_TWO], "parameters": {}, "expect_error_class": "PRECONDITION_FAILED"},
    {"id": "arrangement-tampered-face-dropped-rejected", "operation": "arrangement.validate.build",
     "inputs": [_b3report("tampered_arrangement_face_dropped_report.json"), B3_ARR_BOXES], "parameters": {},
     "expect_error_class": "VALIDATION_FAILED"},
    {"id": "arrangement-tampered-edge-dropped-rejected", "operation": "arrangement.validate.build",
     "inputs": [_b3report("tampered_arrangement_edge_dropped_report.json"), B3_ARR_BOXES], "parameters": {},
     "expect_error_class": "VALIDATION_FAILED"},
    {"id": "zone-tampered-vertex-dropped-rejected", "operation": "arrangement.validate.zone",
     "inputs": [_b3report("tampered_zone_vertex_dropped_report.json"), B3_ARR_BOXES, B3_ZONE_DIAGONAL],
     "parameters": {}, "expect_error_class": "VALIDATION_FAILED"},
    {"id": "overlay-tampered-label-rejected", "operation": "arrangement.validate.overlay",
     "inputs": [_b3report("tampered_overlay_label_report.json"), B3_SQUARE_TWO, B3_SQUARE_UNIT], "parameters": {},
     "expect_error_class": "VALIDATION_FAILED"},
]

B3_CASES_7_5 = [
    _case("autorefine-intersecting-tetrahedra", "mesh.autorefine", [_mesh(INTERSECTING)], {}, [
        ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::autorefine"],
        ["metrics.input_face_count", "==", 8],
        ["metrics.output_face_count", ">", 8],
        ["output:geometry:measure:off.area", "approx", [3.0 + SQRT3, 1e-9]],
    ]),
    _case("autorefine-cube-unchanged", "mesh.autorefine", [Q_CUBE], {}, [
        ["metrics.input_face_count", "==", 12],
        ["metrics.output_face_count", "==", 12],
        ["output:geometry:measure:off.area", "approx", [24.0, 1e-9]],
    ]),
]
B3_NEG_7_5 = [
    {"id": "autorefine-unrefined-candidate-rejected", "operation": "mesh.validate.autorefine",
     "inputs": [_mesh(INTERSECTING), _mesh(INTERSECTING)], "parameters": {},
     "expect_error_class": "VALIDATION_FAILED"},
]

FAMILY_7_5 = {
    "family": "7.5",
    "scope": "family_7_5_boolean_operations_partial",
    "evidence_path": "docs/master/evidence/family-7.5-capabilities.json",
    "test_id": "family-7.5-replay-cases",
    "requirements": {
        "major.7.5.03": {
            "operation_ids": ["mesh.boolean.intersection", "mesh.clip.plane"],
            "symbols": ["clip", "corefine_and_compute_intersection"],
            "symbol_notes": "PMP::clip cuts the 0..2 cube with x=1 (volume 4, a closed half box of area 16) and with "
                            "x+y+z=3 through the centre (volume 4), as a surface (area 12, open) and, for an open "
                            "square, as a surface even with volume clipping requested (area 2). Its independent "
                            "validator tiles the negative side of every source face exactly (Sutherland-Hodgman "
                            "clipping, weighted areas in GMP rationals), requires every candidate vertex on the "
                            "negative side and, for a volume clip of a closed mesh, an outward cap and a closed "
                            "oriented candidate. corefine_and_compute_intersection is exercised by the validated "
                            "mesh.boolean.intersection cases. Planes containing a face or with a zero normal are "
                            "rejected.",
            "case_ids": ["intersection-overlap", "intersection-contained", "clip-cube-volume-x1",
                         "clip-cube-surface-x1", "clip-cube-volume-diagonal", "clip-open-square-surface"],
        },
        "major.7.5.01": {
            "operation_ids": ["mesh.corefine", "mesh.autorefine"],
            "symbols": ["corefine", "autorefine"],
            "symbol_notes": "PMP::corefine refines one tetrahedron along its intersection with a second one "
                            "(corefine-tetrahedra, validated by the exact tiling validator of mesh.corefine) and "
                            "PMP::autorefine refines a self-intersecting pair of tetrahedra (a closed surface whose "
                            "faces are split along the intersection polylines, tiling validated exactly and "
                            "re-checked for remaining self-intersection) and leaves a cube without "
                            "self-intersection unchanged. An unrefined self-intersecting candidate is rejected.",
            "case_ids": ["corefine-tetrahedra", "autorefine-intersecting-tetrahedra", "autorefine-cube-unchanged"],
        },
        "major.7.5.04": {
            "operation_ids": ["mesh.split.plane", "mesh.corefine"],
            "symbols": ["split", "corefine"],
            "symbol_notes": "PMP::split(mesh, plane) refines the cube along x=1 and along x+y+z=3 and separates the "
                            "two sides (area 24 preserved); PMP::corefine refines one tetrahedron along its "
                            "intersection with a second one that is left unchanged (area 6 + 2 sqrt(3) and "
                            "volume 4/3 preserved). The independent validators tile every source face exactly "
                            "(GMP rationals), require that no triangle crosses the plane or the other surface "
                            "and, for a split, that the two sides form separate connected components. Output "
                            "coordinates must be exactly representable as binary64 or the operation fails.",
            "case_ids": ["split-cube-x1", "split-cube-diagonal", "corefine-tetrahedra"],
        },
        "major.7.5.02": {
            "operation_ids": ["mesh.boolean.union", "mesh.boolean.intersection",
                              "mesh.boolean.difference"],
            "symbols": ["corefine_and_compute_union", "corefine_and_compute_intersection",
                        "corefine_and_compute_difference"],
            "case_ids": ["union-overlap", "intersection-overlap", "difference-overlap",
                         "union-disjoint", "intersection-contained", "difference-contained"],
        },
        "major.7.5.05": {
            "operation_ids": ["mesh.slice.compute"],
            "symbols": ["Polygon_mesh_slicer"],
            "symbol_notes": "CGAL::Polygon_mesh_slicer cuts the 0..2 triangulated cube with z=1 (one closed square "
                            "of side 2: the four corners plus the four edge midpoints where the face diagonals "
                            "cross, 8 distinct points) and with x+y+z=3 (the regular hexagon through the six edge "
                            "midpoints plus the six points where face diagonals cross it, 12 distinct points), and "
                            "the open two-triangle square at x=1 (an open polyline through the diagonal "
                            "crossing). The independent validator recomputes every triangle/plane section in exact "
                            "rationals and requires the polylines to lie on the plane, inside the sections and to "
                            "cover them; a closed mesh must give closed polylines only. Planes containing a face "
                            "or with a zero normal are rejected, not sliced.",
            "case_ids": ["slice-cube-mid", "slice-cube-diagonal", "slice-open-square"],
        },
    },
    "unbound": {},
    "cases": [
        *B2_CASES_7_5,
        *B3_CASES_7_5,
        _case("union-overlap", "mesh.boolean.union",
              [_mesh(CUBE_A), _mesh(CUBE_OVERLAP)], {"operation": "union"}, [
            ["metrics.exact_volume", "==", "12"], ["metrics.result_status", "==", "volume"],
            ["output:geometry:measure:off.signed_volume", "approx", [12.0, 1e-9]],
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
        ]),
        _case("intersection-overlap", "mesh.boolean.intersection",
              [_mesh(CUBE_A), _mesh(CUBE_OVERLAP)], {"operation": "intersection"}, [
            ["metrics.exact_volume", "==", "4"], ["metrics.result_status", "==", "volume"],
            ["output:geometry:measure:off.signed_volume", "approx", [4.0, 1e-9]],
        ]),
        _case("difference-overlap", "mesh.boolean.difference",
              [_mesh(CUBE_A), _mesh(CUBE_OVERLAP)], {"operation": "difference"}, [
            ["metrics.exact_volume", "==", "4"], ["metrics.result_status", "==", "volume"],
            ["output:geometry:measure:off.signed_volume", "approx", [4.0, 1e-9]],
        ]),
        _case("union-disjoint", "mesh.boolean.union",
              [_mesh(CUBE_A), _mesh(CUBE_DISJOINT)], {"operation": "union"}, [
            ["metrics.exact_volume", "==", "16"],
            ["output:geometry:measure:off.signed_volume", "approx", [16.0, 1e-9]],
        ]),
        _case("intersection-contained", "mesh.boolean.intersection",
              [_mesh(CUBE_A), _mesh(CUBE_CONTAINED)], {"operation": "intersection"}, [
            ["metrics.exact_volume", "==", "1"],
            ["output:geometry:measure:off.signed_volume", "approx", [1.0, 1e-9]],
        ]),
        _case("difference-contained", "mesh.boolean.difference",
              [_mesh(CUBE_A), _mesh(CUBE_CONTAINED)], {"operation": "difference"}, [
            ["metrics.exact_volume", "==", "7"],
            ["output:geometry:measure:off.signed_volume", "approx", [7.0, 1e-9]],
        ]),
        _case("slice-cube-mid", "mesh.slice.compute", [Q_CUBE], Q_PLANE_Z1, [
            ["metrics.polyline_count", "==", 1],
            ["metrics.closed_polyline_count", "==", 1],
            ["metrics.algorithm", "==", "CGAL::Polygon_mesh_slicer"],
            ["output:analysis:json:report_kind", "==", "mesh_slice"],
            ["output:analysis:json:results.polylines[*].closed", "==", [True]],
            ["output:analysis:json:results.polylines.0.points", "==", [
                ["0", "0", "1"], ["1", "0", "1"], ["2", "0", "1"], ["2", "1", "1"], ["2", "2", "1"],
                ["1", "2", "1"], ["0", "2", "1"], ["0", "1", "1"], ["0", "0", "1"]]],
        ]),
        _case("slice-cube-diagonal", "mesh.slice.compute", [Q_CUBE], Q_PLANE_DIAGONAL, [
            ["metrics.polyline_count", "==", 1],
            ["metrics.closed_polyline_count", "==", 1],
            ["output:analysis:json:results.polylines[*].closed", "==", [True]],
            ["output:analysis:json:results.polylines.0.points", "==", [
                ["0", "1", "2"], ["1/2", "1/2", "2"], ["1", "0", "2"], ["3/2", "0", "3/2"], ["2", "0", "1"],
                ["2", "1/2", "1/2"], ["2", "1", "0"], ["3/2", "3/2", "0"], ["1", "2", "0"], ["1/2", "2", "1/2"],
                ["0", "2", "1"], ["0", "3/2", "3/2"], ["0", "1", "2"]]],
        ]),
        _case("slice-open-square", "mesh.slice.compute", [Q_OPEN_SQUARE],
              {"normal": [1, 0, 0], "offset": {"value": 1, "unit": "mm"}}, [
            ["metrics.polyline_count", "==", 1],
            ["metrics.closed_polyline_count", "==", 0],
            ["output:analysis:json:results.polylines[*].closed", "==", [False]],
        ]),
    ],
    "pairs": [],
    "negative_controls": [
        *B2_NEG_7_5,
        {"id": "union-open-input-rejected", "operation": "mesh.boolean.union",
         "inputs": [_mesh(OPEN_CUBE), _mesh(CUBE_OVERLAP)], "parameters": {"operation": "union"},
         "expect_error_class": "PRECONDITION_FAILED"},
        {"id": "slice-coplanar-face-rejected", "operation": "mesh.slice.compute", "inputs": [Q_CUBE],
         "parameters": {"normal": [0, 0, 1], "offset": {"value": 0, "unit": "mm"}},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "COPLANAR_FACE"},
        {"id": "slice-zero-normal-rejected", "operation": "mesh.slice.compute", "inputs": [Q_CUBE],
         "parameters": {"normal": [0, 0, 0], "offset": {"value": 1, "unit": "mm"}},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "ZERO_NORMAL"},
        {"id": "slice-tampered-missing-polyline-rejected", "operation": "mesh.validate.slice",
         "inputs": [_qjson("tampered_slice_report.json", "GeometryQueryReport", "none"), Q_CUBE],
         "parameters": Q_PLANE_Z1, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "SECTION_NOT_COVERED"},
    ],
}

FAMILY_7_9 = {
    "family": "7.9",
    "scope": "family_7_9_point_set_processing_partial",
    "evidence_path": "docs/master/evidence/family-7.9-capabilities.json",
    "test_id": "family-7.9-replay-cases",
    "requirements": {
        "major.7.9.02": {
            "operation_ids": ["pointset.remove_outliers", "pointset.spacing.average"],
            "symbols": ["remove_outliers", "compute_average_spacing"],
            "symbol_notes": "CGAL::remove_outliers on a 3x3 unit grid plus a far point (10,10,10): the far point is "
                            "removed under 10 percent, nothing is removed under 0 percent, and distance 0 with "
                            "50 percent keeps floor(10*50/100)=5 points. CGAL::compute_average_spacing on ten "
                            "collinear unit-spaced points with k=2 is hand-derived as 11/15. The independent "
                            "validators recompute the k+1 nearest distances by brute force (point itself "
                            "included, as the CGAL neighbour query) in long double and compare within a 1e-9 "
                            "relative tolerance; points whose measure is within that tolerance of the bound are "
                            "rejected as ambiguous.",
            "case_ids": ["spacing-line10", "outliers-remove-far-point", "outliers-quota-zero-percent",
                         "outliers-quota-half", "spacing-cluster-k3", "outliers-threshold-from-spacing"],
        },
        "major.7.9.06": {
            "operation_ids": ["pointset.remove_outliers", "pointset.spacing.average"],
            "symbols": ["compute_average_spacing", "remove_outliers"],
            "symbol_notes": "The reconstruction-preprocessing subcapabilities listed in the ledger are "
                            "compute_average_spacing and remove_outliers (the scale estimate and the outlier "
                            "filter that precede surface reconstruction); both are replayed with their "
                            "independent validators, with the same cases as the outlier-removal requirement, plus the "
                            "preprocessing sequence on the grid-and-far-point cloud: the measured average spacing "
                            "(k=3) is then used as the distance bound of the outlier filter (the harness replays "
                            "the two steps as separate cases; it cannot pipe one output into the next input). "
                            "Normal estimation and orientation are separate requirements (7.9.01).",
            "case_ids": ["spacing-line10", "outliers-remove-far-point", "outliers-quota-zero-percent",
                         "outliers-quota-half", "spacing-cluster-k3", "outliers-threshold-from-spacing"],
        },
        "major.7.9.01": {
            "operation_ids": ["pointset.normals.estimate", "pointset.normals.orient_mst"],
            "symbols": ["jet_estimate_normals", "pca_estimate_normals"],
            "case_ids": ["normals-pca-plane", "normals-jet-plane", "normals-orient-mst"],
        },
        "major.7.9.04": {
            "operation_ids": ["pointset.simplify.grid", "pointset.simplify.random",
                              "pointset.simplify.hierarchy"],
            "symbols": ["grid_simplify_point_set", "random_simplify_point_set"],
            "case_ids": ["simplify-grid", "simplify-random-seed-a", "simplify-random-seed-a-repeat",
                         "simplify-random-seed-b", "simplify-hierarchy"],
        },
    },
    "unbound": {
        "major.7.9.03": "pointset.smooth.jet exposes jet_smooth_point_set only; "
                        "bilateral_smooth_point_set is not exposed.",
        "major.7.9.05": "No validated registration operation (register_point_sets, "
                        "compute_registration_transformation).",
    },
    "cases": [
        *B2_CASES_7_9,
        _case("normals-pca-plane", "pointset.normals.estimate", [_points(PLANE)],
              {"method": "pca", "neighbors": 8}, [
            ["metrics.method", "==", "pca"],
            ["output:points:measure:points.count", "==", 25],
            ["output:points:measure:points.min_abs_normal_z", ">", 0.99],
        ]),
        _case("normals-jet-plane", "pointset.normals.estimate", [_points(PLANE)],
              {"method": "jet", "neighbors": 8, "degree_fitting": 2}, [
            ["metrics.method", "==", "jet"],
            ["output:points:measure:points.count", "==", 25],
            ["output:points:measure:points.min_abs_normal_z", ">", 0.99],
        ]),
        _case("normals-orient-mst", "pointset.normals.orient_mst",
              [_points(ALTERNATING, "PointSet3Normals", "ply")],
              {"neighbors": 4, "drop_unoriented": False}, [
            ["metrics.unoriented_point_count", "==", 0],
            ["input:points:measure:points.normal_z_sign_consistent", "==", False],
            ["output:points:measure:points.normal_z_sign_consistent", "==", True],
            ["output:points:measure:points.count", "==", 9],
        ]),
        _case("simplify-grid", "pointset.simplify.grid", [_points(NOISY_PLANE)],
              {"cell_size": {"value": 1.5, "unit": "mm"}, "min_points_per_cell": 1}, [
            ["input:points:measure:points.count", "==", 26],
            ["output:points:measure:points.count", "<", {"path": "input:points:measure:points.count"}],
            ["output:points:measure:points.count", ">", 0],
        ]),
        _case("simplify-random-seed-a", "pointset.simplify.random", [_points(NOISY_PLANE)],
              {"removed_percentage": 50.0, "seed": 12345}, [
            ["output:points:measure:points.count", "==", 13],
        ]),
        _case("simplify-random-seed-a-repeat", "pointset.simplify.random", [_points(NOISY_PLANE)],
              {"removed_percentage": 50.0, "seed": 12345}, [
            ["output:points:measure:points.count", "==", 13],
        ]),
        _case("simplify-random-seed-b", "pointset.simplify.random", [_points(NOISY_PLANE)],
              {"removed_percentage": 50.0, "seed": 99999}, [
            ["output:points:measure:points.count", "==", 13],
        ]),
        _case("simplify-hierarchy", "pointset.simplify.hierarchy", [_points(NOISY_PLANE)],
              {"cluster_size": 4, "maximum_variation": 0.2}, [
            ["output:points:measure:points.count", "<", {"path": "input:points:measure:points.count"}],
            ["output:points:measure:points.count", ">", 0],
        ]),
    ],
    "pairs": [
        *B2_PAIRS_7_9,
        {"kind": "equal_outputs", "cases": ["simplify-random-seed-a", "simplify-random-seed-a-repeat"]},
        {"kind": "different_outputs", "cases": ["simplify-random-seed-a", "simplify-random-seed-b"]},
        {"kind": "different_outputs", "cases": ["normals-pca-plane", "normals-jet-plane"]},
    ],
    "negative_controls": [*B2_NEG_7_9],
}

# ---- Wave C families (fixtures under tests/fixtures/master/wave_c) ----------
PLANAR = {"fixture": "wave_c/planar_points.json", "sha256": "2edb3017cdb0e39e041a75284cf208f42b847c91ad938fab0eaafcfca219fbae"}
COLLINEAR = {"fixture": "wave_c/collinear_points.json", "sha256": "087f7019a38d090185c7819a8218e88b0d5be18c4636bf558534818186ae14f5"}
POLYGON_HOLE = {"fixture": "wave_c/polygon_with_hole.json", "sha256": "b88fd8eeacddaa021697227ce5caa3a2fe22bd026592f9676a97bf17963d7959"}
POLYGON_L = {"fixture": "wave_c/polygon_l_shape.json", "sha256": "dec71795a9fc825548732ea647003420ad0b4fd1419443f4440308bdbe7f4b4d"}
POLYGON_BOWTIE = {"fixture": "wave_c/polygon_bowtie.json", "sha256": "44351418b0b2c4af582cf01a32eda634860b502b0026459e767f0924ba4cc71f"}
CONTAINMENT_QUERIES = {"fixture": "wave_c/containment_queries.json",
                       "sha256": "d01fce2f49091c170b8a6da5b10c44a374dc9f89d4e6ac9647e88c167fced48b"}
CONSTRAINT_GRAPH = {"fixture": "wave_c/constraint_graph.json", "sha256": "ddfd2a733ff2bddc32857ba5cf1ed8d5ebed2cf6c89ea63ae9fd7b92256c49fb"}
CONSTRAINT_CROSSING = {"fixture": "wave_c/constraint_crossing.json",
                       "sha256": "2b9d0ae7e96b5b1bc6702ae78f6cfac0bf825ac57cc768dc1d876144fc942059"}
CLOUD = {"fixture": "wave_c/cloud_points.xyz", "sha256": "6eefbc923c71e53120312cdbdd30e283ae07850e5fb650ecb958f16b7c1e0dae"}
QUERY_POINTS = {"fixture": "wave_c/query_points.xyz", "sha256": "49d0b7c67d716f111f324a49918d9561d46e5b2d3bf03ec1c934c071f5ee1070"}
MESH_QUERIES = {"fixture": "wave_c/mesh_queries.xyz", "sha256": "6c4bc044e35ca94f3c9dd5f91cea6282a85aaf3818420222dbc8c8b819925277"}
CUBE_RAYS = {"fixture": "wave_c/cube_rays.json", "sha256": "1c9d3a1e32f7100ac8ce54f14a2b27016543ab2f52d7f8d98444c69c8dd5d523"}
HULL_INNER = {"fixture": "wave_c/hull_inner_points.xyz", "sha256": "c668facce23117d1339896b004d624f7188fdc8104b3fe7b695308bc07d02b19"}
CUBE_WITH_INTERIOR = {"fixture": "cube_with_interior.xyz", "sha256": "299fc3e1e6363388d7fa80fcc86a297dde4740fd59f7d2fc628bdb0d27ae7a39"}


def _json_input(fixture: dict, type_: str, unit: str = "mm") -> dict:
    return {**fixture, "type": type_, "format": "json", "unit": unit}


SQRT2 = math.sqrt(2.0)
SQRT3 = math.sqrt(3.0)

FAMILY_7_13 = {
    "family": "7.13",
    "scope": "family_7_13_hulls_partial",
    "evidence_path": "docs/master/evidence/family-7.13-capabilities.json",
    "test_id": "family-7.13-replay-cases",
    "requirements": {
        "major.7.13.04": {
            "operation_ids": ["shape.bounding.circle", "shape.bounding.sphere"],
            "symbols": ["Min_sphere_of_spheres_d", "Min_circle_2", "Min_sphere_of_spheres_d_traits_3"],
            "symbol_notes": "CGAL::Min_circle_2 (Min_circle_2_traits_2) gives the circle (2, 3/2) radius 5/2 for a "
                            "right triangle with an interior point and the diameter circle (3,4) radius 5 for two "
                            "points; CGAL::Min_sphere_of_spheres_d with Min_sphere_of_spheres_d_traits_3 gives the "
                            "sphere (1,1,1) radius sqrt(3) for the cube corners, and sqrt(3)+1/2 for balls of radius "
                            "1/2. The independent validators enumerate every support set exactly in GMP rationals "
                            "and require the unique minimum ball; the radius is a square root, so centre and "
                            "radius are compared within a stated relative tolerance and every input ball must be "
                            "enclosed.",
            "case_ids": ["circle-right-triangle", "circle-two-points", "sphere-cube-corners",
                         "sphere-cube-corners-radius-half"],
        },
        "major.7.13.01": {
            "operation_ids": ["hull.convex_2", "hull.convex_3"],
            "symbols": ["convex_hull_2", "convex_hull_3"],
            "symbol_notes": "The 2D case is a 21-point set with interior points whose hull is the "
                            "hand-derived 3x3 square (area 9); the 3D case is the cube corners plus "
                            "the centre, whose hull is the cube of volume 8 with 8 vertices and 12 "
                            "triangles. Each hull is also checked by its independent enclosure "
                            "validator.",
            "case_ids": ["hull2-grid", "hull3-cube"],
        },
        "major.7.13.05": {
            "operation_ids": ["shape.barycentric"],
            "symbols": ["mean_value_coordinates_2", "wachspress_coordinates_2", "discrete_harmonic_coordinates_2"],
            "symbol_notes": "The three CGAL::Barycentric_coordinates families run on the square [0,4]^2 and "
                            "its centre, whose weights are the four equal values 1/4 for every family; the query "
                            "(1,2) additionally has the hand-derived bilinear Wachspress weights 3/8, 1/8, 1/8, 3/8. "
                            "Mean value is also replayed on the non-convex L-shaped polygon. The independent "
                            "validator recomputes the weights (exact rational Wachspress and discrete harmonic "
                            "formulas; tolerance-checked mean value), partition of unity and linear precision, "
                            "after re-checking that the polygon is simple and counterclockwise (strictly convex "
                            "for the two convex-only families) and that every query is strictly inside. "
                            "CGAL's default policy PRECISE_WITH_EDGE_CASES is not exposed: boundary queries are "
                            "rejected.",
            "case_ids": ["bary-square-wachspress", "bary-square-mean-value", "bary-square-discrete-harmonic",
                         "bary-l-mean-value"],
        },
    },
    "unbound": {
        "major.7.13.02": "No alpha shape operation (Alpha_shape_2, Alpha_shape_3).",
    },
    "cases": [
        *B2_CASES_7_13,
        _case("hull2-grid", "hull.convex_2", [_json_input(PLANAR, "PointSet2")], {}, [
            ["output:polygon:json:points", "==", [[0.0, 0.0], [3.0, 0.0], [3.0, 3.0], [0.0, 3.0]]],
            ["metrics.hull_vertex_count", "==", 4],
            ["metrics.input_point_count", "==", 21],
            ["metrics.orientation", "==", "counterclockwise"],
            ["metrics.area.exact", "==", "9"],
            ["metrics.algorithm", "==", "CGAL::convex_hull_2"],
        ]),
        _case("hull3-cube", "hull.convex_3", [_points(CUBE_WITH_INTERIOR)], {}, [
            ["input:points:measure:points.count", "==", 9],
            ["output:geometry:measure:off.vertex_count", "==", 8],
            ["output:geometry:measure:off.face_count", "==", 12],
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.signed_volume", "approx", [8.0, 1e-12]],
        ]),
        _bary_case("bary-square-wachspress", "wachspress", [
            ["output:analysis:json:results.1.coordinates", "approx", [[0.375, 0.125, 0.125, 0.375], 1e-12]],
        ]),
        _bary_case("bary-square-mean-value", "mean_value", []),
        _bary_case("bary-square-discrete-harmonic", "discrete_harmonic", []),
        _case("bary-l-mean-value", "shape.barycentric", [Q_POLYGON_L, Q_BARY_L], {"method": "mean_value"}, [
            ["metrics.vertex_count", "==", 6],
            ["metrics.query_count", "==", 4],
            ["output:analysis:json:results[*].query_index", "==", [0, 1, 2, 3]],
        ]),
    ],
    "pairs": [],
    "negative_controls": [
        *B2_NEG_7_13,
        {"id": "hull2-collinear-rejected", "operation": "hull.convex_2",
         "inputs": [_json_input(COLLINEAR, "PointSet2")], "parameters": {},
         "expect_error_class": "PRECONDITION_FAILED"},
        {"id": "hull3-oversized-shell-rejected", "operation": "hull.validate.convex_enclosure",
         "inputs": [_mesh(CUBE_A), _points(HULL_INNER)], "parameters": {},
         "expect_error_class": "VALIDATION_FAILED"},
        {"id": "bary-clockwise-polygon-rejected", "operation": "shape.barycentric",
         "inputs": [_qjson("polygon_clockwise.json", "Polygon2"), Q_BARY], "parameters": {"method": "wachspress"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "POLYGON_NOT_COUNTERCLOCKWISE"},
        {"id": "bary-bowtie-polygon-rejected", "operation": "shape.barycentric",
         "inputs": [_qjson("polygon_bowtie.json", "Polygon2"), Q_BARY], "parameters": {"method": "mean_value"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "POLYGON_NOT_SIMPLE"},
        {"id": "bary-nonconvex-wachspress-rejected", "operation": "shape.barycentric",
         "inputs": [Q_POLYGON_L, Q_BARY_L], "parameters": {"method": "wachspress"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "POLYGON_NOT_STRICTLY_CONVEX"},
        {"id": "bary-query-outside-rejected", "operation": "shape.barycentric",
         "inputs": [Q_HEXAGON, _qjson("bary_query_outside.json", "PointSet2")], "parameters": {"method": "wachspress"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "QUERY_NOT_STRICTLY_INSIDE"},
        {"id": "bary-query-on-boundary-rejected", "operation": "shape.barycentric",
         "inputs": [Q_HEXAGON, _qjson("bary_query_boundary.json", "PointSet2")], "parameters": {"method": "wachspress"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "QUERY_NOT_STRICTLY_INSIDE"},
        {"id": "bary-tampered-coordinates-rejected", "operation": "shape.validate.barycentric",
         "inputs": [_qjson("tampered_barycentric_report.json", "GeometryQueryReport", "none"), Q_HEXAGON, Q_BARY],
         "parameters": {"method": "wachspress"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "COORDINATE_MISMATCH"},
    ],
}

FAMILY_7_11 = {
    "family": "7.11",
    "scope": "family_7_11_triangulations_partial",
    "evidence_path": "docs/master/evidence/family-7.11-capabilities.json",
    "test_id": "family-7.11-replay-cases",
    "requirements": {
        "major.7.11.01": {
            "operation_ids": ["triangulation.delaunay_2", "triangulation.delaunay_3"],
            "symbols": ["Delaunay_triangulation_2", "Delaunay_triangulation_3"],
            "symbol_notes": "dt2-grid: 20 distinct vertices (one duplicate input merged) with 13 hull "
                            "vertices give 2n-2-h = 25 triangles by Euler's relation; dt3-cube: every "
                            "Delaunay tetrahedron of the cube corners plus centre contains the centre, "
                            "giving 12 tetrahedra. The dt3-cloud tetrahedron count is a regression pin "
                            "checked by the exact independent validator, not a hand-derived value.",
            "case_ids": ["dt2-grid", "dt3-cube", "dt3-cloud"],
        },
        "major.7.11.03": {
            "operation_ids": ["triangulation.regular_2", "triangulation.regular_3"],
            "symbols": ["Regular_triangulation_2", "Regular_triangulation_3"],
            "symbol_notes": "Weighted points (squared-length weights with the artifact unit squared) in the plane "
                            "and in space: with zero weights the triangulation is Delaunay; a strongly negative "
                            "weight makes a point hidden. The independent validators lift the points exactly "
                            "(GMP rationals), require every reported cell to be regular (no other lifted point "
                            "below its lifted plane or sphere), the boundary to be the lower convex hull and "
                            "every hidden point to be dominated. Duplicate or collinear points are rejected.",
            "case_ids": ["regular2-zero-weights", "regular2-hidden-point", "regular3-zero-weights",
                         "regular3-hidden-point"],
        },
        "major.7.11.05": {
            "operation_ids": ["triangulation.voronoi_dual"],
            "symbols": ["Voronoi_diagram_2"],
            "symbol_notes": "CGAL::Voronoi_diagram_2 over a Delaunay triangulation: five sites (square plus centre) "
                            "and six scattered sites. The independent validator recomputes all circumcentres and "
                            "dual edges (finite and unbounded) in exact rationals and rejects altered vertices or "
                            "edges; fewer than three non-collinear sites are rejected.",
            "case_ids": ["voronoi-square-centre", "voronoi-scatter"],
        },
        "major.7.11.02": {
            "operation_ids": ["triangulation.constrained_2"],
            "symbols": ["Constrained_Delaunay_triangulation_2", "Constrained_triangulation_2"],
            "symbol_notes": "delaunay=true runs Constrained_Delaunay_triangulation_2 and delaunay=false "
                            "runs Constrained_triangulation_2 (asserted through the reported algorithm); "
                            "both preserve the three input constraints.",
            "case_ids": ["cdt-delaunay", "ct-plain"],
        },
    },
    "unbound": {
        "major.7.11.04": "No periodic or on-sphere triangulation operation.",
    },
    "cases": [
        *B3_CASES_7_11,
        _case("dt2-grid", "triangulation.delaunay_2", [_json_input(PLANAR, "PointSet2")], {}, [
            ["metrics.algorithm", "==", "CGAL::Delaunay_triangulation_2"],
            ["metrics.input_point_count", "==", 21],
            ["metrics.duplicate_points_merged", "==", 1],
            ["metrics.vertex_count", "==", 20],
            ["metrics.triangle_count", "==", 25],
            ["output:triangulation:json:constrained_edges", "==", []],
        ]),
        _case("dt3-cube", "triangulation.delaunay_3", [_points(CUBE_WITH_INTERIOR)], {}, [
            ["metrics.algorithm", "==", "CGAL::Delaunay_triangulation_3"],
            ["metrics.vertex_count", "==", 9],
            ["metrics.tetrahedron_count", "==", 12],
        ]),
        _case("dt3-cloud", "triangulation.delaunay_3", [_points(CLOUD)], {}, [
            ["metrics.algorithm", "==", "CGAL::Delaunay_triangulation_3"],
            ["metrics.input_point_count", "==", 168],
            ["metrics.vertex_count", "==", 168],
        ]),
        _case("cdt-delaunay", "triangulation.constrained_2",
              [_json_input(CONSTRAINT_GRAPH, "SegmentGraph2")], {"delaunay": True}, [
            ["metrics.algorithm", "==", "CGAL::Constrained_Delaunay_triangulation_2"],
            ["metrics.vertex_count", "==", 10],
            ["output:triangulation:json:constrained_edges", "==", [[0, 6], [3, 7], [4, 5]]],
        ]),
        _case("ct-plain", "triangulation.constrained_2",
              [_json_input(CONSTRAINT_GRAPH, "SegmentGraph2")], {"delaunay": False}, [
            ["metrics.algorithm", "==", "CGAL::Constrained_triangulation_2"],
            ["metrics.vertex_count", "==", 10],
            ["output:triangulation:json:constrained_edges", "==", [[0, 6], [3, 7], [4, 5]]],
        ]),
    ],
    "pairs": [],
    "negative_controls": [
        *B3_NEG_7_11,
        {"id": "dt2-collinear-rejected", "operation": "triangulation.delaunay_2",
         "inputs": [_json_input(COLLINEAR, "PointSet2")], "parameters": {},
         "expect_error_class": "PRECONDITION_FAILED"},
        {"id": "cdt-crossing-constraints-rejected", "operation": "triangulation.constrained_2",
         "inputs": [_json_input(CONSTRAINT_CROSSING, "SegmentGraph2")], "parameters": {"delaunay": True},
         "expect_error_class": "PRECONDITION_FAILED"},
    ],
}

FAMILY_7_12 = {
    "family": "7.12",
    "scope": "family_7_12_polygons_partial",
    "evidence_path": "docs/master/evidence/family-7.12-capabilities.json",
    "test_id": "family-7.12-replay-cases",
    "requirements": {
        "major.7.12.04": {
            "operation_ids": ["polygon.boolean"],
            "symbols": ["Polygon_set_2", "join", "difference"],
            "symbol_notes": "CGAL::Polygon_set_2 (EPECK) joins, intersects and subtracts simple polygons: [0,4]^2 and "
                            "[2,6]^2 give an octagon (join), the square [2,4]^2 (intersection) and a hexagonal L "
                            "(difference); subtracting the inner square [1,3]^2 gives one polygon with a clockwise "
                            "hole; disjoint operands give two polygons (join) or none (intersection); a clockwise "
                            "hexagon is accepted after reversal. The independent validator rebuilds the boundary "
                            "chain of the set operation in GMP rationals by edge splitting and point "
                            "classification and compares it with the reported counter-clockwise outer and clockwise "
                            "hole rings. Operands must be simple with non-zero area.",
            "case_ids": ["polygon-join-overlap", "polygon-intersection-overlap", "polygon-difference-overlap",
                         "polygon-difference-hole", "polygon-join-disjoint", "polygon-intersection-disjoint",
                         "polygon-intersection-clockwise-hexagon"],
        },
        "major.7.12.02": {
            "operation_ids": ["arrangement.build", "arrangement.zone"],
            "symbols": ["Arrangement_2", "insert", "zone"],
            "symbol_notes": "CGAL::Arrangement_2 is built by insert() from segment graphs (concurrent segments; nested "
                            "squares with free segments) and CGAL::zone reports the vertices, edges and faces a "
                            "query segment passes through. The independent validators split segments, trace faces "
                            "and nest cycles in GMP rationals and reject altered vertex, edge or face sets.",
            "case_ids": ["arrangement-concurrent-segments", "arrangement-nested-components",
                         "zone-through-vertices", "zone-crossing-edges", "zone-diagonal-vertices-faces",
                         "zone-outside"],
        },
        "major.7.12.03": {
            "operation_ids": ["arrangement.overlay"],
            "symbols": ["overlay", "Overlay_traits"],
            "symbol_notes": "CGAL::overlay with Arr_face_overlay_traits (face labels summed) overlays the arrangements "
                            "of two simple polygons; the independent validator rebuilds the overlay arrangement "
                            "and face labels exactly and rejects a changed label.",
            "case_ids": ["overlay-square-corner", "overlay-inscribed-triangle", "overlay-nonconvex"],
        },
        "major.7.12.07": {
            "operation_ids": ["polygon.minkowski_sum", "polygon.minkowski_sum_reduced_convolution"],
            "symbols": ["minkowski_sum_2", "minkowski_sum_by_reduced_convolution_2"],
            "symbol_notes": "Both CGAL Minkowski sum algorithms are replayed on a square plus triangle, on a U-shaped "
                            "ring plus a square that closes its opening (one hole) and on a C shape (no hole). The "
                            "independent validator checks the boundary against the exact convolution pieces and "
                            "rejects a dropped hole or moved vertex.",
            "case_ids": ["minkowski-square-triangle", "minkowski-closed-gap-hole", "minkowski-nonconvex-no-hole",
                         "minkowski-reduced-square-triangle", "minkowski-reduced-closed-gap-hole",
                         "minkowski-reduced-nonconvex-no-hole"],
        },
        "major.7.12.01": {
            "operation_ids": ["polygon.analysis.properties", "polygon.query.containment"],
            "symbols": ["Polygon_2", "Polygon_with_holes_2", "is_simple"],
            "symbol_notes": "Replayed 2D polygon operations are ring orientation, simplicity "
                            "(Polygon_2::is_simple), convexity, exact area and centroid, bounding box, "
                            "polygon-with-holes validity and exact point location, asserted against "
                            "hand-derived values (100-9=91, centroid 919/182, L-shape 7 and 19/14). "
                            "Boolean, offset, skeleton and Minkowski operations are separate "
                            "requirements and stay unbound.",
            "case_ids": ["polygon-with-hole", "polygon-l-shape", "polygon-bowtie", "containment-with-hole"],
        },
    },
    "unbound": {
        "major.7.12.05": "No straight-skeleton operation.",
        "major.7.12.06": "No skeleton-offset operation.",
    },
    "cases": [
        *B2_CASES_7_12,
        *B3_CASES_7_12,
        _case("polygon-with-hole", "polygon.analysis.properties",
              [_json_input(POLYGON_HOLE, "PolygonWithHoles2")], {}, [
            ["output:analysis:json:results.valid_polygon_with_holes", "==", True],
            ["output:analysis:json:results.hole_count", "==", 1],
            ["output:analysis:json:results.area.exact", "==", "91"],
            ["output:analysis:json:results.centroid.exact", "==", ["919/182", "919/182"]],
            ["output:analysis:json:results.bbox.min", "approx", [[0.0, 0.0], 1e-12]],
            ["output:analysis:json:results.bbox.max", "approx", [[10.0, 10.0], 1e-12]],
            ["output:analysis:json:results.rings[*].role", "==", ["outer", "hole"]],
            ["output:analysis:json:results.rings[*].orientation", "==", ["counterclockwise", "clockwise"]],
            ["output:analysis:json:results.rings[*].simple", "==", [True, True]],
            ["output:analysis:json:results.rings[*].convex", "==", [True, True]],
            ["output:analysis:json:results.rings[*].signed_area.exact", "==", ["100", "-9"]],
        ]),
        _case("polygon-l-shape", "polygon.analysis.properties",
              [_json_input(POLYGON_L, "PolygonWithHoles2")], {}, [
            ["output:analysis:json:results.valid_polygon_with_holes", "==", True],
            ["output:analysis:json:results.area.exact", "==", "7"],
            ["output:analysis:json:results.centroid.exact", "==", ["19/14", "19/14"]],
            ["output:analysis:json:results.rings[*].simple", "==", [True]],
            ["output:analysis:json:results.rings[*].convex", "==", [False]],
            ["output:analysis:json:results.rings[*].orientation", "==", ["counterclockwise"]],
        ]),
        _case("polygon-bowtie", "polygon.analysis.properties",
              [_json_input(POLYGON_BOWTIE, "PolygonWithHoles2")], {}, [
            ["output:analysis:json:results.valid_polygon_with_holes", "==", False],
            ["output:analysis:json:results.rings[*].simple", "==", [False]],
        ]),
        _case("containment-with-hole", "polygon.query.containment",
              [_json_input(POLYGON_HOLE, "PolygonWithHoles2"),
               _json_input(CONTAINMENT_QUERIES, "PointSet2")], {}, [
            ["output:analysis:json:results[*].location", "==",
             ["inside", "outside", "boundary", "boundary", "outside", "boundary", "boundary", "inside"]],
            ["output:analysis:json:summary.inside", "==", 2],
            ["output:analysis:json:summary.outside", "==", 2],
            ["output:analysis:json:summary.boundary", "==", 4],
        ]),
    ],
    "pairs": [],
    "negative_controls": [
        *B2_NEG_7_12,
        {"id": "containment-bowtie-rejected", "operation": "polygon.query.containment",
         "inputs": [_json_input(POLYGON_BOWTIE, "PolygonWithHoles2"),
                    _json_input(CONTAINMENT_QUERIES, "PointSet2")], "parameters": {},
         "expect_error_class": "PRECONDITION_FAILED"},
    ],
}

# Query 1 coincides with cloud point 167 (1,1,1); query 5 is (3,3,3), 2*sqrt(3) away from it.
_KNN_COMMON = [
    ["metrics.tree", "==", "CGAL::Kd_tree"],
    ["metrics.query_count", "==", 6],
    ["output:analysis:json:results.1.neighbors.0.index", "==", 167],
    ["output:analysis:json:results.1.neighbors.0.distance", "==", 0.0],
    ["output:analysis:json:results.5.neighbors.0.index", "==", 167],
    ["output:analysis:json:results.5.neighbors.0.distance", "approx", [2.0 * SQRT3, 1e-12]],
]

FAMILY_7_2 = {
    "family": "7.2",
    "scope": "family_7_2_spatial_queries_partial",
    "evidence_path": "docs/master/evidence/family-7.2-capabilities.json",
    "test_id": "family-7.2-replay-cases",
    "requirements": {
        "major.7.2.01": {
            "operation_ids": ["spatial.aabb.closest_points", "spatial.aabb.ray_first_hits"],
            "symbols": ["AABB_tree", "AABB_traits", "AABB_face_graph_triangle_primitive"],
            "symbol_notes": "The worker uses AABB_tree with AABB_face_graph_triangle_primitive and the "
                            "AABB_traits_3 traits class (the CGAL 6.x name of the inventory's "
                            "AABB_traits). Closest-point distances and ray hits on the axis-aligned "
                            "cube are hand-derived; closest points are asserted only where the nearest "
                            "face is unique. Intersection-candidate queries are 7.2.04.",
            "case_ids": ["aabb-closest-cube", "aabb-rays-cube"],
        },
        "major.7.2.02": {
            "operation_ids": ["spatial.knn_3", "spatial.range_search_3"],
            "symbols": ["Kd_tree", "Search_traits_3"],
            "symbol_notes": "Both operations build a CGAL::Kd_tree over Search_traits_3 (through "
                            "Search_traits_adapter). Radius search is replayed with radius 0 (exactly "
                            "the coincident point 167) and radius 0.5 (total confirmed by the exact "
                            "brute-force validator; queries 2 and 5 are empty because their nearest "
                            "neighbours are 1.60 and 3.46 away).",
            "case_ids": ["knn-orthogonal", "knn-general", "range-zero-radius", "range-half-radius"],
        },
        "major.7.2.03": {
            "operation_ids": ["spatial.knn_3"],
            "symbols": ["K_neighbor_search", "Orthogonal_k_neighbor_search"],
            "case_ids": ["knn-orthogonal", "knn-general", "knn-nearest-single"],
        },
        "major.7.2.05": {
            "operation_ids": ["spatial.bbox_2", "spatial.bbox_3"],
            "symbols": ["Bbox_2", "Bbox_3", "bbox_2", "bbox_3"],
            "symbol_notes": "Boxes of a planar point set, a triangle mesh and a 3D point set are "
                            "asserted against hand-derived extrema.",
            "case_ids": ["bbox-planar", "bbox-cube-mesh", "bbox-point-set"],
        },
        "major.7.2.04": {
            "operation_ids": ["spatial.aabb.intersections"],
            "symbols": ["do_intersect", "any_intersected_primitive", "all_intersected_primitives"],
            "symbol_notes": "Seven rays against the 0..2 triangulated cube, every answer hand-derived: the ray "
                            "from (1,1,-1) along +z crosses both bottom and both top triangles (it runs through "
                            "the shared diagonals), (5,5,5) along +x misses, the interior ray from (1,1,1) exits "
                            "through the single triangle 10, the ray from (-1,1,1) along +x crosses the "
                            "diagonals of the x=0 and x=2 faces (triangles 8..11), (-1,-1,-1) along (1,1,1) runs "
                            "through the corners (0,0,0) and (2,2,2) and so touches all 12 triangles, and the "
                            "ray along the edge x=y=0 touches the triangles incident to its two corners. The "
                            "reported set is the sorted unique all_intersected_primitives result and any_face "
                            "must be a member of it. The independent validator intersects every ray with every "
                            "triangle using exact rational predicates (including degenerate touching and "
                            "coplanar cases).",
            "case_ids": ["aabb-intersections-cube"],
        },
    },
    "unbound": {
    },
    "cases": [
        _case("aabb-closest-cube", "spatial.aabb.closest_points",
              [_mesh(CUBE_A), _points(MESH_QUERIES)], {}, [
            ["metrics.algorithm", "==", "CGAL::AABB_tree::closest_point_and_primitive"],
            ["metrics.face_count", "==", 12],
            ["metrics.query_count", "==", 6],
            ["output:analysis:json:results[*].distance", "approx",
             [[1.0, 1.0, 2.0, SQRT3 / 2.0, 0.25, SQRT2], 1e-12]],
            ["output:analysis:json:results.1.point", "approx", [[2.0, 1.0, 1.0], 1e-12]],
            ["output:analysis:json:results.2.point", "approx", [[1.0, 1.0, 0.0], 1e-12]],
            ["output:analysis:json:results.3.point", "approx", [[2.0, 2.0, 2.0], 1e-12]],
            ["output:analysis:json:results.4.point", "approx", [[1.0, 0.5, 0.0], 1e-12]],
            ["output:analysis:json:results.5.point", "approx", [[0.0, 2.0, 1.0], 1e-12]],
        ]),
        _case("aabb-rays-cube", "spatial.aabb.ray_first_hits",
              [_mesh(CUBE_A), _json_input(CUBE_RAYS, "RayBatch3")], {}, [
            ["metrics.algorithm", "==", "CGAL::AABB_tree::first_intersection"],
            ["metrics.ray_count", "==", 6],
            ["metrics.hit_count", "==", 5],
            ["output:analysis:json:results[*].hit", "==", [True, False, True, True, True, True]],
            ["output:analysis:json:results.0.distance", "approx", [1.0, 1e-12]],
            ["output:analysis:json:results.0.point", "approx", [[1.0, 1.0, 0.0], 1e-12]],
            ["output:analysis:json:results.2.distance", "approx", [math.sqrt(1.13), 1e-12]],
            ["output:analysis:json:results.2.point", "approx", [[2.0, 1.3, 1.2], 1e-12]],
            ["output:analysis:json:results.3.distance", "approx", [1.0, 1e-12]],
            ["output:analysis:json:results.3.point", "approx", [[0.0, 0.5, 0.0], 1e-12]],
            ["output:analysis:json:results.4.distance", "approx", [SQRT3, 1e-12]],
            ["output:analysis:json:results.4.point", "approx", [[0.0, 0.0, 0.0], 1e-12]],
            ["output:analysis:json:results.5.distance", "approx", [1.0, 1e-12]],
            ["output:analysis:json:results.5.point", "approx", [[0.5, 0.5, 2.0], 1e-12]],
        ]),
        _case("knn-orthogonal", "spatial.knn_3", [_points(CLOUD), _points(QUERY_POINTS)],
              {"k": 5, "search": "orthogonal"}, [
            ["metrics.algorithm", "==", "CGAL::Orthogonal_k_neighbor_search"],
            ["metrics.k", "==", 5],
            *_KNN_COMMON,
        ]),
        _case("knn-general", "spatial.knn_3", [_points(CLOUD), _points(QUERY_POINTS)],
              {"k": 5, "search": "general"}, [
            ["metrics.algorithm", "==", "CGAL::K_neighbor_search"],
            ["metrics.k", "==", 5],
            *_KNN_COMMON,
        ]),
        _case("knn-nearest-single", "spatial.knn_3", [_points(CLOUD), _points(QUERY_POINTS)],
              {"k": 1, "search": "orthogonal"}, [
            ["metrics.k", "==", 1],
            ["output:analysis:json:results.1.neighbors.0.index", "==", 167],
            ["output:analysis:json:results.5.neighbors.0.index", "==", 167],
        ]),
        _case("range-zero-radius", "spatial.range_search_3", [_points(CLOUD), _points(QUERY_POINTS)],
              {"radius": {"value": 0.0, "unit": "mm"}}, [
            ["output:analysis:json:results.1.neighbors.0.index", "==", 167],
            ["output:analysis:json:results.1.neighbors.0.distance", "==", 0.0],
            ["output:analysis:json:results.0.neighbors", "==", []],
        ]),
        _case("range-half-radius", "spatial.range_search_3", [_points(CLOUD), _points(QUERY_POINTS)],
              {"radius": {"value": 0.5, "unit": "mm"}}, [
            ["output:analysis:json:results.2.neighbors", "==", []],
            ["output:analysis:json:results.5.neighbors", "==", []],
        ]),
        _case("bbox-planar", "spatial.bbox_2", [_json_input(PLANAR, "PointSet2")], {}, [
            ["output:analysis:json:results.dimension", "==", 2],
            ["output:analysis:json:results.min", "approx", [[0.0, 0.0], 1e-12]],
            ["output:analysis:json:results.max", "approx", [[3.0, 3.0], 1e-12]],
            ["output:analysis:json:summary.point_count", "==", 21],
        ]),
        _case("bbox-cube-mesh", "spatial.bbox_3", [_mesh(CUBE_A)], {}, [
            ["output:analysis:json:source.geometry_type", "==", "TriangleSurfaceMesh"],
            ["output:analysis:json:results.dimension", "==", 3],
            ["output:analysis:json:results.min", "approx", [[0.0, 0.0, 0.0], 1e-12]],
            ["output:analysis:json:results.max", "approx", [[2.0, 2.0, 2.0], 1e-12]],
        ]),
        _case("bbox-point-set", "spatial.bbox_3", [_points(QUERY_POINTS)], {}, [
            ["output:analysis:json:source.geometry_type", "==", "PointSet3"],
            ["output:analysis:json:results.min", "approx", [[-0.3, -0.5, -0.9], 1e-12]],
            ["output:analysis:json:results.max", "approx", [[3.0, 3.0, 3.0], 1e-12]],
            ["output:analysis:json:summary.point_count", "==", 6],
        ]),
        _case("aabb-intersections-cube", "spatial.aabb.intersections", [Q_CUBE, Q_RAYS], {}, [
            ["metrics.ray_count", "==", 7],
            ["metrics.intersecting_ray_count", "==", 6],
            ["metrics.face_count", "==", 12],
            ["output:analysis:json:query_kind", "==", "aabb_ray_intersections"],
            ["output:analysis:json:results[*].do_intersect", "==", [True, False, True, True, True, True, True]],
            ["output:analysis:json:results.0.faces", "==", [0, 1, 2, 3]],
            ["output:analysis:json:results.1.faces", "==", []],
            ["output:analysis:json:results.2.faces", "==", [10]],
            ["output:analysis:json:results.3.faces", "==", [8, 9, 10, 11]],
            ["output:analysis:json:results.4.faces", "==", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]],
            ["output:analysis:json:results.5.faces", "==", [0, 1, 2, 3]],
            ["output:analysis:json:results.6.faces", "==", [0, 1, 2, 3, 4, 5, 8, 9]],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["range-zero-radius", "range-half-radius"]},
        {"kind": "different_outputs", "cases": ["knn-orthogonal", "knn-nearest-single"]},
    ],
    "negative_controls": [
        {"id": "knn-zero-k-rejected", "operation": "spatial.knn_3",
         "inputs": [_points(CLOUD), _points(QUERY_POINTS)],
         "parameters": {"k": 0, "search": "general"}, "expect_error_class": "INVALID_REQUEST"},
        {"id": "range-unit-mismatch-rejected", "operation": "spatial.range_search_3",
         "inputs": [_points(CLOUD), _points(QUERY_POINTS)],
         "parameters": {"radius": {"value": 0.5, "unit": "cm"}}, "expect_error_class": "TYPE_ERROR"},
        {"id": "rays-unit-mismatch-rejected", "operation": "spatial.aabb.ray_first_hits",
         "inputs": [_mesh(CUBE_A), {**_json_input(CUBE_RAYS, "RayBatch3"), "unit": "cm"}],
         "parameters": {}, "expect_error_class": "TYPE_ERROR"},
        {"id": "bbox2-rejects-3d-points", "operation": "spatial.bbox_2",
         "inputs": [_points(CLOUD)], "parameters": {}, "expect_error_class": "TYPE_ERROR"},
        {"id": "aabb-intersections-tampered-flag-rejected", "operation": "spatial.validate.aabb_intersections",
         "inputs": [_qjson("tampered_intersections_report.json", "SpatialQueryReport", "none"), Q_CUBE, Q_RAYS],
         "parameters": {}, "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "DO_INTERSECT_MISMATCH"},
    ],
}

L_PRISM = {"fixture": "wave_d/l_prism.off",
           "sha256": "72215189b66d423386e6b9d35dddf6081a96c01a521aaea239e9e3cd77a75305"}
HEXADECAGON_FAN = {"fixture": "wave_d/hexadecagon_fan.off",
                   "sha256": "58e93f910dcc1912da7a336fa485d5145efb3b02a99e8cab3495cdf347543a3d"}
SQUARE_FAN = {"fixture": "wave_d/square_fan.off",
              "sha256": "71b10da73091276930a2263e652dc9246ec98aa3ebb3d0287f460e4a14fe9089"}
SQUARE_TWO_TRIANGLES = {"fixture": "wave_d/square_two_triangles.off",
                        "sha256": "61893beb05b4264903232dd6a2acf21d19fd2c65bfc4daef30454839cc743f8e"}
GRID3_DISPLACED = {"fixture": "wave_d/grid3_displaced.off",
                   "sha256": "5bc59a14bc8fbf0a180714daedaf24decb45dabe7e47f071210dae8f48191722"}
GRID5_BUMP = {"fixture": "wave_d/grid5_bump.off",
              "sha256": "45509bdb7622ee34019183abff1eaeec63b6fe2b34101af5c937e67371481c63"}
ICOSPHERE2 = {"fixture": "wave_d/icosphere2.off",
              "sha256": "cce1858c5c297f8827cfe3a31bf95bd1e9dc7935e8386f44bd3f0a22f1697558"}
ICOSPHERE2_NOISY = {"fixture": "wave_d/icosphere2_noisy.off",
                    "sha256": "38d5ccc26c72a6a96f3b2ad053e320758bfd0f2b4360a6074bdf9f48052c1cb0"}
OBLATE = {"fixture": "wave_d/oblate_spheroid.off",
          "sha256": "5bb797ddfdd0aa47c3c2ca61768910d16a16ab48a93176754d18a4238fc8f49e"}


def _mm(value: float) -> dict:
    return {"value": value, "unit": "mm"}


HEXADECAGON_AREA = 32.0 * math.sin(math.pi / 8.0)
GRID3_RELAXED_MEAN_EDGE = (12.0 + 4.0 * SQRT2) / 16.0
NOISY_SPHERE_VOLUME = 4.0426073283768496
OBLATE_VOLUME = 6.644385307347405
# Uniform isotropic remesh (target 0.1) of OBLATE: a valid, close, but curvature-blind candidate.
OBLATE_UNIFORM = {"fixture": "wave_d/oblate_uniform_0p1.off", "sha256": "de7e7f8a43b86b0afdb2fe32751a0c28d17773844eaded75ac26c663324e2eab"}
_ADAPTIVE = {"tolerance": _mm(0.01), "min_edge_length": _mm(0.1), "max_edge_length": _mm(0.8),
             "number_of_iterations": 3, "max_deviation": _mm(0.05)}

FAMILY_7_6 = {
    "family": "7.6",
    "scope": "family_7_6_meshing_remeshing_partial",
    "evidence_path": "docs/master/evidence/family-7.6-capabilities.json",
    "test_id": "family-7.6-replay-cases",
    "requirements": {
        "major.7.6.01": {
            "operation_ids": ["mesh.triangulate.faces"],
            "symbols": ["triangulate_faces", "triangulate_face"],
            "symbol_notes": "triangulate_faces (whole mesh) and triangulate_face (per face) are both "
                            "selected through the method parameter. The L-shaped prism with "
                            "non-convex hexagon caps becomes 20 triangles enclosing volume 3 and area "
                            "14; the quad cube becomes 12 triangles of volume 1. The independent "
                            "validator checks each triangle lies in exactly one source face with exact "
                            "per-face orientation.",
            "case_ids": ["tri-lprism-faces", "tri-lprism-face", "tri-quadcube"],
        },
        "major.7.6.02": {
            "operation_ids": ["mesh.refine.local"],
            "symbols": ["refine"],
            "symbol_notes": "refine inserts 13 interior vertices into a 14-triangle fan of a regular "
                            "16-gon (29 vertices, 40 faces, area 32 sin(pi/8)), and more at a higher "
                            "density control factor; the validator checks preserved source vertices "
                            "and boundary, the 2:1 face/vertex insertion relation and a certified "
                            "Hausdorff bound. fair is not listed in the inventory of this requirement.",
            "case_ids": ["refine-hexadecagon", "refine-hexadecagon-dense"],
        },
        "major.7.6.03": {
            "operation_ids": ["mesh.remesh.isotropic", "mesh.remesh.split_long_edges"],
            "symbols": ["isotropic_remeshing", "split_long_edges"],
            "symbol_notes": "Uniform isotropic_remeshing of an open planar square (area 16 kept, "
                            "mean edge within the target band), a closed sphere and an oblate "
                            "spheroid; split_long_edges of a two-triangle 4x4 square yields exactly "
                            "23 vertices and 28 faces with every source edge cut into pieces <= 1.",
            "case_ids": ["iso-square", "iso-sphere", "iso-oblate-uniform", "split-square"],
        },
        "major.7.6.04": {
            "operation_ids": ["mesh.smooth.tangential_relaxation", "mesh.smooth.shape"],
            "symbols": ["smooth_shape", "tangential_relaxation"],
            "symbol_notes": "tangential_relaxation moves the displaced centre of a 3x3 grid back to "
                            "the regular position (edges exactly 1 and sqrt 2); smooth_shape flattens a "
                            "bumped grid with a fixed boundary and smooths a noisy closed sphere while "
                            "preserving its volume to 1e-9. Validators check identical connectivity, "
                            "fixed boundary, quality/roughness improvement and a Hausdorff bound.",
            "case_ids": ["relax-grid3", "smooth-grid5", "smooth-sphere-volume"],
        },
        "major.7.6.05": {
            "operation_ids": ["mesh.remesh.adaptive"],
            "symbols": ["split_long_edges", "isotropic_remeshing"],
            "symbol_notes": "Adaptive_sizing_field drives both isotropic_remeshing and "
                            "split_long_edges on an oblate spheroid whose curvature ranges from about "
                            "0.1 to 12.5: the adaptive remesh spans an edge-length ratio above 5 "
                            "while staying within a certified 0.05 Hausdorff bound, whereas uniform "
                            "remeshing of the same input stays below ratio 3 and needs a 0.3 bound; the adaptive split preserves the exact "
                            "geometry while only refining long edges. The adaptive validator recomputes a curvature-driven "
                            "target from the raw source and rejects a uniform 0.1 remesh of the same input.",
            "case_ids": ["adaptive-oblate-isotropic", "adaptive-oblate-split"],
        },
    },
    "unbound": {},
    "cases": [
        _case("tri-lprism-faces", "mesh.triangulate.faces", [_mesh(L_PRISM, "PolygonSoup3")],
              {"method": "triangulate_faces"}, [
            ["input:source:measure:off.max_face_degree", "==", 6],
            ["output:geometry:measure:off.max_face_degree", "==", 3],
            ["output:geometry:measure:off.vertex_count", "==", 12],
            ["output:geometry:measure:off.face_count", "==", 20],
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.signed_volume", "approx", [3.0, 1e-12]],
            ["output:geometry:measure:off.area", "approx", [14.0, 1e-12]],
        ]),
        _case("tri-lprism-face", "mesh.triangulate.faces", [_mesh(L_PRISM, "PolygonSoup3")],
              {"method": "triangulate_face"}, [
            ["output:geometry:measure:off.max_face_degree", "==", 3],
            ["output:geometry:measure:off.face_count", "==", 20],
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.signed_volume", "approx", [3.0, 1e-12]],
            ["output:geometry:measure:off.area", "approx", [14.0, 1e-12]],
            ["metrics.method", "==", "triangulate_face"],
        ]),
        _case("tri-quadcube", "mesh.triangulate.faces", [_mesh(QUAD_CUBE, "PolygonSoup3")],
              {"method": "triangulate_faces"}, [
            ["input:source:measure:off.max_face_degree", "==", 4],
            ["output:geometry:measure:off.face_count", "==", 12],
            ["output:geometry:measure:off.vertex_count", "==", 8],
            ["output:geometry:measure:off.signed_volume", "approx", [1.0, 1e-12]],
        ]),
        _case("refine-hexadecagon", "mesh.refine.local", [_mesh(HEXADECAGON_FAN)],
              {"density_control_factor": SQRT2, "max_deviation": _mm(0.01)}, [
            ["input:source:measure:off.vertex_count", "==", 16],
            ["metrics.inserted_vertices", "==", 13],
            ["metrics.new_faces", "==", 26],
            ["output:geometry:measure:off.vertex_count", "==", 29],
            ["output:geometry:measure:off.face_count", "==", 40],
            ["output:geometry:measure:off.boundary_edge_count", "==", 16],
            ["output:geometry:measure:off.area", "approx", [HEXADECAGON_AREA, 1e-9]],
        ]),
        _case("refine-hexadecagon-dense", "mesh.refine.local", [_mesh(HEXADECAGON_FAN)],
              {"density_control_factor": 3.0, "max_deviation": _mm(0.01)}, [
            ["metrics.inserted_vertices", ">", 13],
            ["output:geometry:measure:off.boundary_edge_count", "==", 16],
            ["output:geometry:measure:off.area", "approx", [HEXADECAGON_AREA, 1e-9]],
        ]),
        _case("iso-square", "mesh.remesh.isotropic", [_mesh(SQUARE_FAN)],
              {"target_edge_length": _mm(0.5), "number_of_iterations": 3,
               "number_of_relaxation_steps": 1, "max_deviation": _mm(0.01)}, [
            ["output:geometry:measure:off.area", "approx", [16.0, 1e-9]],
            ["output:geometry:measure:off.mean_edge_length", ">=", 0.4],
            ["output:geometry:measure:off.mean_edge_length", "<=", 2.0 / 3.0],
            ["output:geometry:measure:off.face_count", ">",
             {"path": "input:source:measure:off.face_count"}],
            ["metrics.target_edge_length", "==", 0.5],
        ]),
        _case("iso-sphere", "mesh.remesh.isotropic", [_mesh(ICOSPHERE2)],
              {"target_edge_length": _mm(0.2), "number_of_iterations": 3,
               "number_of_relaxation_steps": 1, "max_deviation": _mm(0.05)}, [
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.mean_edge_length", ">=", 0.16],
            ["output:geometry:measure:off.mean_edge_length", "<=", 0.8 / 3.0],
            ["output:geometry:measure:off.signed_volume", ">", 3.95],
            ["output:geometry:measure:off.signed_volume", "<", 4.19],
        ]),
        _case("iso-oblate-uniform", "mesh.remesh.isotropic", [_mesh(OBLATE)],
              {"target_edge_length": _mm(0.3), "number_of_iterations": 3,
               "number_of_relaxation_steps": 1, "max_deviation": _mm(0.3)}, [
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.edge_length_ratio", "<", 3.0],
        ]),
        _case("split-square", "mesh.remesh.split_long_edges", [_mesh(SQUARE_TWO_TRIANGLES)],
              {"max_length": _mm(1.0)}, [
            ["output:geometry:measure:off.vertex_count", "==", 23],
            ["output:geometry:measure:off.face_count", "==", 28],
            ["output:geometry:measure:off.boundary_edge_count", "==", 16],
            ["output:geometry:measure:off.area", "approx", [16.0, 1e-12]],
        ]),
        _case("relax-grid3", "mesh.smooth.tangential_relaxation", [_mesh(GRID3_DISPLACED)],
              {"number_of_iterations": 1, "max_deviation": _mm(0.01)}, [
            ["output:geometry:measure:off.min_edge_length", "approx", [1.0, 1e-9]],
            ["output:geometry:measure:off.max_edge_length", "approx", [SQRT2, 1e-9]],
            ["output:geometry:measure:off.mean_edge_length", "approx",
             [GRID3_RELAXED_MEAN_EDGE, 1e-9]],
            ["output:geometry:measure:off.area", "approx", [4.0, 1e-12]],
        ]),
        _case("smooth-grid5", "mesh.smooth.shape", [_mesh(GRID5_BUMP)],
              {"time_step": 0.01, "number_of_iterations": 1, "preserve_volume": False,
               "max_deviation": _mm(1.0)}, [
            ["output:geometry:measure:off.vertex_count", "==", 25],
            ["output:geometry:measure:off.boundary_edge_count", "==", 16],
            ["output:geometry:measure:off.bbox_diagonal", "<",
             {"path": "input:source:measure:off.bbox_diagonal"}],
        ]),
        _case("smooth-sphere-volume", "mesh.smooth.shape", [_mesh(ICOSPHERE2_NOISY)],
              {"time_step": 0.01, "number_of_iterations": 1, "preserve_volume": True,
               "max_deviation": _mm(0.2)}, [
            ["input:source:measure:off.signed_volume", "approx", [NOISY_SPHERE_VOLUME, 1e-12]],
            ["output:geometry:measure:off.signed_volume", "approx", [NOISY_SPHERE_VOLUME, 1e-9]],
            ["output:geometry:measure:off.edge_length_ratio", "<",
             {"path": "input:source:measure:off.edge_length_ratio"}],
        ]),
        _case("adaptive-oblate-isotropic", "mesh.remesh.adaptive", [_mesh(OBLATE)],
              {**_ADAPTIVE, "mode": "isotropic_remeshing"}, [
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.edge_length_ratio", ">", 5.0],
            ["output:geometry:measure:off.max_edge_length", ">", 0.5],
            ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::isotropic_remeshing"],
        ]),
        _case("adaptive-oblate-split", "mesh.remesh.adaptive", [_mesh(OBLATE)],
              {**_ADAPTIVE, "mode": "split_long_edges"}, [
            ["output:geometry:measure:off.vertex_count", ">",
             {"path": "input:source:measure:off.vertex_count"}],
            ["output:geometry:measure:off.signed_volume", "approx", [OBLATE_VOLUME, 1e-9]],
            ["output:geometry:measure:off.max_edge_length", "<=",
             {"path": "input:source:measure:off.max_edge_length"}],
            ["metrics.algorithm", "==", "CGAL::Polygon_mesh_processing::split_long_edges"],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["refine-hexadecagon", "refine-hexadecagon-dense"]},
        {"kind": "different_outputs", "cases": ["iso-oblate-uniform", "adaptive-oblate-isotropic"]},
    ],
    "negative_controls": [
        {"id": "tri-wrong-vertices-rejected", "operation": "mesh.validate.triangulated_faces",
         "inputs": [_mesh(CUBE_A), _mesh(QUAD_CUBE, "PolygonSoup3")], "parameters": {},
         "expect_error_class": "VALIDATION_FAILED"},
        {"id": "refine-nonmanifold-rejected", "operation": "mesh.refine.local",
         "inputs": [_mesh(NONMANIFOLD)],
         "parameters": {"density_control_factor": SQRT2, "max_deviation": _mm(0.01)},
         "expect_error_class": "PRECONDITION_FAILED"},
        {"id": "iso-unremeshed-rejected", "operation": "mesh.validate.isotropic_remesh",
         "inputs": [_mesh(SQUARE_FAN), _mesh(SQUARE_FAN)],
         "parameters": {"target_edge_length": _mm(0.5), "max_deviation": _mm(0.01)},
         "expect_error_class": "VALIDATION_FAILED"},
        {"id": "iso-nonpositive-length-rejected", "operation": "mesh.remesh.isotropic",
         "inputs": [_mesh(SQUARE_FAN)],
         "parameters": {"target_edge_length": _mm(0.0), "number_of_iterations": 1,
                        "number_of_relaxation_steps": 1, "max_deviation": _mm(0.01)},
         "expect_error_class": "INVALID_REQUEST"},
        {"id": "split-unsplit-rejected", "operation": "mesh.validate.split_long_edges",
         "inputs": [_mesh(SQUARE_TWO_TRIANGLES), _mesh(SQUARE_TWO_TRIANGLES)],
         "parameters": {"max_length": _mm(1.0)}, "expect_error_class": "VALIDATION_FAILED"},
        {"id": "relax-changed-connectivity-rejected",
         "operation": "mesh.validate.tangential_relaxation",
         "inputs": [_mesh(GRID5_BUMP), _mesh(GRID3_DISPLACED)],
         "parameters": {"max_deviation": _mm(0.01)}, "expect_error_class": "VALIDATION_FAILED"},
        {"id": "smooth-unsmoothed-rejected", "operation": "mesh.validate.shape_smoothing",
         "inputs": [_mesh(GRID5_BUMP), _mesh(GRID5_BUMP)],
         "parameters": {"max_deviation": _mm(1.0), "preserve_volume": False},
         "expect_error_class": "VALIDATION_FAILED"},
        {"id": "smooth-open-volume-rejected", "operation": "mesh.smooth.shape",
         "inputs": [_mesh(GRID5_BUMP)],
         "parameters": {"time_step": 0.01, "number_of_iterations": 1, "preserve_volume": True,
                        "max_deviation": _mm(1.0)},
         "expect_error_class": "PRECONDITION_FAILED"},
        {"id": "adaptive-uniform-remesh-rejected", "operation": "mesh.validate.adaptive_remesh",
         "inputs": [_mesh(OBLATE_UNIFORM), _mesh(OBLATE)],
         "parameters": {**{k: v for k, v in _ADAPTIVE.items() if k != "number_of_iterations"},
                        "mode": "isotropic_remeshing"},
         "expect_error_class": "VALIDATION_FAILED"},
        {"id": "adaptive-inverted-range-rejected", "operation": "mesh.remesh.adaptive",
         "inputs": [_mesh(OBLATE)],
         "parameters": {**_ADAPTIVE, "min_edge_length": _mm(0.8), "max_edge_length": _mm(0.1),
                        "mode": "isotropic_remeshing"},
         "expect_error_class": "INVALID_REQUEST"},
    ],
}

RECT_10X1 = {"fixture": "wave_e/rect_10x1.json",
             "sha256": "340646ffe0cf50adc5194dc15b16e7b739fb4b041ef5310e21ff491211a4fc5f"}
SQUARE_10 = {"fixture": "wave_e/square10.json",
             "sha256": "ffb231e94b4521e4a08334a7514aef2d82acd7c2af6f3899dee5abbfa519300c"}
TWO_HOLES = {"fixture": "wave_e/two_holes.json",
             "sha256": "cf06284fc29f97fb5e147d92529bd2adbd85716c846a4f4754debf3104c51643"}
HOLE_SQUARE = {"fixture": "wave_c/polygon_with_hole.json",
               "sha256": "b88fd8eeacddaa021697227ce5caa3a2fe22bd026592f9676a97bf17963d7959"}
L_SHAPE = {"fixture": "wave_c/polygon_l_shape.json",
           "sha256": "dec71795a9fc825548732ea647003420ad0b4fd1419443f4440308bdbe7f4b4d"}
BOWTIE = {"fixture": "wave_c/polygon_bowtie.json",
          "sha256": "44351418b0b2c4af582cf01a32eda634860b502b0026459e767f0924ba4cc71f"}
HOLE_OUTSIDE = {"fixture": "wave_e/hole_outside.json",
                "sha256": "9753d01982dac2231a1bdacb012e870e896bc4aae168b8a9a0bd404ec38d1578"}
HOLE_TOUCHING = {"fixture": "wave_e/hole_touching.json",
                 "sha256": "7f1dfcdd608fa14933e24ac36379fa0ac273a5a732a5b407cbaa97dc3a6e9ecd"}
HOLE_NESTED = {"fixture": "wave_e/hole_nested.json",
               "sha256": "608ce22a5a9e152c5f03b4e03de5c40204d81c3e4d5221a0b71fef29db2bc94a"}
HOLE_FAR_OUTSIDE = {"fixture": "wave_e/hole_far_outside.json",
                    "sha256": "0744fdb999d26df7f76317dee550d9584500a5b773da84ede58b61643a7e949e"}
SQUARE_MESH = {"fixture": "wave_e/square10_mesh.json",
               "sha256": "831c615cff3f9204c3c25ec5a575c10215d3e1f5da20b4800dc846355e3f2389"}
SQUARE_MESH_MISSING = {"fixture": "wave_e/square10_mesh_missing_triangle.json",
                       "sha256": "16eec39c116bf3b5574504f252394d44142de0431d3f9a250e6335c03b4a1fc9"}
SQUARE_MESH_SHIFTED = {"fixture": "wave_e/square10_mesh_shifted_boundary.json",
                       "sha256": "1b2a5e0ef565e0f723abd7f6a935349ed1780799e262dd5de3ed974c2a0de4a9"}
HOLED_MESH_FLIPPED = {"fixture": "wave_e/holed_mesh_flipped_diagonal.json",
                      "sha256": "ce1055676afa581be4b77529ed817f127fdb297dc757e9fc6c761802e25533dd"}

# Shape bound 0.125 = sin^2 of the smallest angle: asin(sqrt(0.125)) = 20.7048 degrees.
MESH2_MIN_ANGLE = math.degrees(math.asin(math.sqrt(0.125)))
MESH2_LOOSE_MIN_ANGLE = math.degrees(math.asin(0.25))


def _mesh2(aspect: float, size: float) -> dict:
    return {"aspect_bound": aspect, "size_bound": _mm(size)}


def _domain(fixture: dict) -> dict:
    return _json_input(fixture, "PolygonWithHoles2")


def _fx(name: str, sha: str, folder: str = "wave_e") -> dict:
    return {"fixture": f"{folder}/{name}", "sha256": sha}


DOM_SPHERE = _fx("domain_sphere.json", "bc34d6ea177e51f89badee9a56c54929a18a0cab280ecd095eea4d5439df1ed6")
DOM_SPHERE_R25 = _fx("domain_sphere_r25.json", "9b15c56b66cf83fb18c9e878f01ab5c5589e7ecb6227ccf94d98e0b79b962ae4")
DOM_ELLIPSOID = _fx("domain_ellipsoid.json", "bb3b0067560f83b79c9372ebf47b5d1c2ef75277286e150d43e2b94165afe269")
DOM_TORUS = _fx("domain_torus.json", "6822f541ac8f34998be9ef12aa51cb0e8988de34a685a5872d9982f0eeba0b9e")
DOM_EXPRESSION = _fx("domain_expression.json", "be8b9c7977654d9326afed6001eb9db463b82034a90ab5e37d5366043c317ebd")
DOM_UNKNOWN_KIND = _fx("domain_unknown_kind.json", "a646cf9a2c48e3d1269eff355ef3c73d496535106de86569e848a877fbffaf00")
DOM_NEGATIVE_RADIUS = _fx("domain_negative_radius.json", "40ef4479ff98b887c0279587718b32308c8c619e4603d5a6983cadb5d03623e0")
DOM_EXTRA_PARAMETER = _fx("domain_extra_parameter.json", "5b01da327554bd849b695d003e3a0d6b20bef63ca4b1708da1c809a2e188fa42")
DOM_THICK_TORUS = _fx("domain_thick_torus.json", "1c93cbf031ad545809fbd9ba43073e83f23d1be3a27cc753f5074a1a4d8cdebb")
DOM_NEEDLE_ELLIPSOID = _fx("domain_needle_ellipsoid.json", "14561aba29339e7d769642cce1c5e82d79db217de0a6cd577c15612b5defa180")
SURF_SPHERE_MESH = _fx("surface_sphere_r2_mesh.off", "128b742b0aea3c0da348cbe856bb5a611aba590743cc718edfeee7121542f750")
SURF_MISSING = _fx("surface_sphere_missing_triangle.off", "2f89f887201ed532235528999a624b5b76a0293fd6a491ceb0c72568fdc1532f")
SURF_FLIPPED_ALL = _fx("surface_sphere_flipped_all.off", "326b7a0e0c0ae264cd474619b0216bcaf4e0fccc1f919e2f2cf42ab1060a64b2")
SURF_FLIPPED_ONE = _fx("surface_sphere_flipped_one.off", "0efe1df86efcd3a70565ca731afb87e6ec7a31652606b11b83b0327f42adad5f")
SURF_DUPLICATE = _fx("surface_sphere_duplicate_face.off", "a18539731c0aaaf41edeb6e7d9c8422b71080043214854e4d1acdd26b8deb4cd")
SURF_SCALED = _fx("surface_sphere_scaled.off", "31c68fac197cf56d032b2fa5e28547de5e96211bffb85f1efdba72a81fd4e883")
SURF_OCTAHEDRON = _fx("surface_octahedron_r2.off", "61089e4b1f1f2475529b65641a4a0fa7f3f67534391cf5d950b94208918d2555")
SURF_TORUS_MESH = _fx("surface_torus_mesh.off", "8a5e1dc8db3e21e561eca23e8d26891850c5dead694fdf3734f176bab3e1a56d")
SURF_ELLIPSOID_MESH = _fx("surface_ellipsoid_mesh.off", "fb02c088721b20ac3c828dea43e62e564687da5bd6b3515c518421f905f10b9f")

VOL_SPHERE_MESH = _fx("volume_sphere_r2_mesh.json", "d153848e5d3fcff06fba3a9345bd6ce1825d714d6ab02cdf61d073ae3b8bca0a")
VOL_ELLIPSOID_MESH = _fx("volume_ellipsoid_mesh.json", "9490fd102d47883165355fd14f74b2a9b66b7d8bcfe29aa7190312fe22657e52")
VOL_TORUS_MESH = _fx("volume_torus_mesh.json", "9595cc950410e7b00e7c70b38899a5ac05b88344aab6c68a301db876f56d4572")
VOL_MISSING_INTERIOR = _fx("volume_sphere_missing_interior_cell.json", "ca92a6c8b3b0d7541da662c5f979fb329812b064daf619653ccc0dcf6bfdf484")
VOL_MISSING_BOUNDARY = _fx("volume_sphere_missing_boundary_cell.json", "bb1c0f466f82b70d08d6541420b0eaa09ae4b510951a3c2c6af68e4ae45decf9")
VOL_FLIPPED = _fx("volume_sphere_flipped_cell.json", "6dd6ac3303ad12e1e1a81834e8c9f5169be60cf5641f83dcc1bb5ebe4ae0f691")
VOL_DUPLICATE = _fx("volume_sphere_duplicate_cell.json", "cea461efb035d26d51d1ddc715bc4ef15df8f71955111b4fa46bf82e5fb0ed44")
VOL_SCALED = _fx("volume_sphere_scaled.json", "16e4a1f1d21a838c3af902eaa4d788bb260830c1d34ade88b4169a030aeb7a0d")
VOL_TWO_SUBDOMAINS = _fx("volume_sphere_two_subdomains.json", "98cb02dfa2ad5026d88d83118ffc57b0a59ee1413202235b69dd0304c2273665")
VOL_OCTAHEDRON = _fx("volume_sphere_octahedron_r2.json", "774ac96291ff9e2d0c5eb11c3fd8abb0b81fd32d8849408e00ab9bf258bc0931")

POLY_CUBE = _fx("poly_cube.off", "7c6caa2b4ca6ceb1ddcfb09bdd6764fbf9311763e99b3f0e716064c8164e28ac")
POLY_L_PRISM = _fx("poly_l_prism.off", "ff474d287097017c7ef598c85696efa92a11b7d6b7a1bd16dd96c471c4a650bb")
POLY_STAIR_PRISM = _fx("poly_stair_prism.off", "dc7f8a1e59f99c4d0f0fae2baf292ef91bdb70e3b0bc1f0aa4390fd66d2c9569")
POLY_TILTED_BOX = _fx("poly_tilted_box.off", "eac37c93d9ecb251360f0070544e5f9eb4f710c3dd8ab55ddfcf67fb24adc991")
POLY_CUBE_OPEN = _fx("poly_cube_open.off", "0446fa9718591641b6f2c066e98dd4f64068b14bb6ebbf53f884452c9ea4872a")
POLY_CUBE_INVERTED = _fx("poly_cube_inverted.off", "351c7f2977d911fbcd75c7df03ce1e163cef0bb92a32c4d0b0d9176296c3087b")
POLY_CUBE_INCONSISTENT = _fx("poly_cube_inconsistent.off", "f5979445dbaad5a9ddbb050c3ccb257c169fec7382e690cc8e17f3a690a18e9b")
POLY_CUBE_SELF_INTERSECTING = _fx("poly_cube_self_intersecting.off", "54645a9fd72fb8f16efe43cff9c5ca2c5084a5f76de6e59d70fadcb4aa066d61")
POLY_CUBE_NONMANIFOLD = _fx("poly_cube_nonmanifold.off", "42af0e10714897a1129e1ef2acc815fe95501ae40b3f19c48d712deab375ae7b")
POLY_TWO_CUBES = _fx("poly_two_cubes.off", "7d2e06074561d742d2743d87c19ec287ae4fbfe45b41e76f02aba4c3d65aa305")
POLY_ICOSPHERE = _fx("poly_icosphere.off", "53b740bfd5bb10c0ba6b583e2b9853f6f4b6cd60a38aa5230845aa8b36bc4c9f")
POLY_CUBE_FEATURES_MESH = _fx("poly_cube_features_mesh.json", "1cdef17597beb6e1876bbecd415732d1b855cc047134843573b14f7fdedd24fd")
POLY_CUBE_MESH = _fx("poly_cube_mesh.json", "a634d1ad14ac59e768c6c00e7959739c90b1ee46e7742081a5fc8d6e0d747717")
POLY_L_MESH = _fx("poly_l_prism_mesh.json", "157e6ae4f2a3a96b6ba0e90a4663d26f487ed6fef15ea1ac59c69a6ec9c595f8")
POLY_BOX_IN_L_MESH = _fx("poly_box_in_l_prism_mesh.json", "3e93ece081fd80f8abd2d72fc9e9f31cfcaff24c7849e24c043321f29bbd440c")
POLY_MISSING_INTERIOR = _fx("poly_cube_missing_interior_cell.json", "52b17bcaebaa67000d42ad46f8a30c96b504d2f088485eb82e889668c3ccb2b1")
POLY_MISSING_BOUNDARY = _fx("poly_cube_missing_boundary_cell.json", "4a4f5afc9509252640a9fd78bbf41eaeac235d450f6341bd329708cb305e8439")
POLY_FLIPPED = _fx("poly_cube_flipped_cell.json", "6c815354d6407623a8a43fa4acc8d501335040f4f4aadae163c46ed2d4b0562c")
POLY_DUPLICATE = _fx("poly_cube_duplicate_cell.json", "8387ec688a11e0283b8cda8c7d0d0b1b4f1f1867f51f2b07a8d72f9f85d37c6f")
POLY_SHIFTED = _fx("poly_cube_shifted.json", "71cb8f7ac36a89027acb07cb784d15e23efd21cf5487a6d04fd932ad3f2a1638")
POLY_SCALED = _fx("poly_cube_scaled.json", "30587f6995545aeee9563080c5b23fd4b2a7deabbd3a869c925a5f08b743404e")
POLY_BUMPED = _fx("poly_cube_bumped_vertex.json", "2ad85ea3a6532c27e05adf7eaffa54ed8774723080f1375ac945442e8ca306b0")
POLY_TWO_SUBDOMAINS = _fx("poly_cube_two_subdomains.json", "102457603f2f90b74ddf4b3fa3502828754d69310c58f63742ab880aa6bc8923")

VOL_GEN = "mesh.volume.generate"
VOL_VAL = "mesh.validate.volume_mesh"


def _vol(angle: float, size: float, distance: float, ratio: float, cell: float) -> dict:
    return {"facet_angle": angle, "facet_size": _mm(size), "facet_distance": _mm(distance),
            "cell_radius_edge_ratio": ratio, "cell_size": _mm(cell)}


def _regions(*boxes) -> list:
    """Typed cell_size_regions entries: (low corner, high corner, cell size)."""
    return [{"box_min": {a: _mm(low[i]) for i, a in enumerate("xyz")},
             "box_max": {a: _mm(high[i]) for i, a in enumerate("xyz")}, "cell_size": _mm(size)}
            for low, high, size in boxes]


def _box_name(prefix: str, low, high) -> str:
    return f"{prefix}({','.join(str(c) for c in (*low, *high))})"


SPHERE_BOX = ((0.0, 0.0, 0.0), (2.5, 2.5, 2.5))


def _tet(fixture: dict) -> dict:
    return _json_input(fixture, "TetrahedralMesh")


def _volume_checks(domain: str = "CGAL::Labeled_mesh_domain_3") -> list[list]:
    return [
        ["metrics.algorithm", "==", "CGAL::make_mesh_3"],
        ["metrics.criteria", "==", "CGAL::Mesh_criteria_3"],
        ["metrics.domain", "==", domain],
        ["metrics.perturbation", "==", False],
        ["metrics.exudation", "==", False],
        ["output:geometry:measure:tet.tetrahedron_count", "==", {"path": "metrics.tetrahedron_count"}],
        ["output:geometry:measure:tet.vertex_count", "==", {"path": "metrics.vertex_count"}],
        ["output:geometry:measure:tet.boundary_face_count", "==", {"path": "metrics.boundary_facet_count"}],
        ["output:geometry:measure:tet.max_face_use", "<=", 2],
        ["output:geometry:measure:tet.subdomain_count", "==", 1],
        ["output:geometry:measure:tet.min_tetrahedron_volume", ">", 0.0],
    ]


def _poly(fixture: dict) -> dict:
    return _mesh(fixture)


def _poly_checks(name: str, volume: float, area: float, volume_tolerance: float, size: float,
                 distance: float, angle: float, ratio: float, cell: float) -> list[list]:
    """Assertions on a polyhedral Mesh_3 output, re-measured against the raw OFF source."""
    off = f"({name})"
    return [
        *_volume_checks("CGAL::Polyhedral_mesh_domain_3"),
        ["metrics.domain_kind", "==", "polyhedral"],
        ["metrics.feature_protection", "==", False],
        ["metrics.source_volume", "approx", [volume, 1e-9]],
        ["metrics.source_area", "approx", [area, 1e-9]],
        ["output:geometry:measure:tet.euler_characteristic", "==", 1],
        ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
        ["output:geometry:measure:tet.volume", "approx", [volume, volume_tolerance * volume]],
        ["output:geometry:measure:tet.volume", "<=", volume + 1e-9],
        ["output:geometry:measure:tet.boundary_area", "approx", [area, 0.06 * area]],
        ["output:geometry:measure:tet.max_boundary_vertex_distance_to_off" + off, "<=", 1e-9],
        ["output:geometry:measure:tet.max_boundary_sample_distance_to_off" + off, "<=", size],
        ["output:geometry:measure:tet.max_off_sample_distance_to_boundary" + off, "<=", 2.0 * size],
        ["output:geometry:measure:tet.max_boundary_facet_center_distance_to_off" + off, "<=", distance + 1e-9],
        ["output:geometry:measure:tet.min_boundary_facet_angle", ">=", angle],
        ["output:geometry:measure:tet.max_boundary_facet_circumradius", "<=", size + 1e-9],
        ["output:geometry:measure:tet.max_circumradius", "<=", cell + 1e-9],
        ["output:geometry:measure:tet.max_radius_edge", "<=", ratio + 1e-9],
    ]


SURF_GEN = "mesh.surface.generate"
SURF_VAL = "mesh.validate.surface_mesh"
PI = math.pi
ELLIPSOID_AREA = 4.0 * PI * (((3.0 * 2.0) ** 1.6075 + (3.0 * 1.5) ** 1.6075 +
                              (2.0 * 1.5) ** 1.6075) / 3.0) ** (1 / 1.6075)


def _surf(angle: float, size: float, distance: float) -> dict:
    return {"angle_bound": angle, "size_bound": _mm(size), "distance_bound": _mm(distance)}


def _surface(fixture: dict) -> dict:
    return _json_input(fixture, "ImplicitSurfaceDomain")


def _surface_checks() -> list[list]:
    return [
        ["metrics.algorithm", "==", "CGAL::make_surface_mesh"],
        ["metrics.criteria", "==", "CGAL::Surface_mesh_default_criteria_3"],
        ["output:geometry:measure:off.boundary_edge_count", "==", 0],
        ["output:geometry:measure:off.max_face_degree", "==", 3],
        ["output:geometry:measure:off.face_count", "==", {"path": "metrics.facet_count"}],
        ["output:geometry:measure:off.vertex_count", "==", {"path": "metrics.vertex_count"}],
        ["output:geometry:measure:off.euler_characteristic", "==", {"path": "metrics.euler_characteristic"}],
    ]


FAMILY_7_14 = {
    "family": "7.14",
    "scope": "family_7_14_mesh_generation_partial",
    "evidence_path": "docs/master/evidence/family-7.14-capabilities.json",
    "test_id": "family-7.14-replay-cases",
    "requirements": {
        "major.7.14.01": {
            "operation_ids": ["mesh2.refine.delaunay"],
            "symbols": ["refine_Delaunay_mesh_2", "Delaunay_mesh_size_criteria_2"],
            "symbol_notes": "refine_Delaunay_mesh_2 with Delaunay_mesh_size_criteria_2 meshes a 10x10 "
                            "square (area 100), the same square with a 3x3 hole (91), an L-shape (7) "
                            "and a square with two holes (92). Output area is recomputed exactly "
                            "from the produced mesh; triangles are counterclockwise and meet the "
                            "aspect bound (smallest angle >= asin(sqrt(B))) and the maximum edge "
                            "length; boundary edges equal the refined constraints. A 10x1 "
                            "rectangle with a loose aspect bound stays the two input triangles "
                            "(smallest angle atan(1/10)); the default bound forces refinement. "
                            "The independent validator re-derives constraint preservation, "
                            "coverage, criteria and the constrained Delaunay property.",
            "case_ids": ["mesh2-square-size2", "mesh2-square-size1", "mesh2-square-loose-angle",
                         "mesh2-hole", "mesh2-lshape", "mesh2-two-holes", "mesh2-rect-unrefined",
                         "mesh2-rect-refined"],
        },
        "major.7.14.02": {
            "operation_ids": [SURF_GEN],
            "symbols": ["make_surface_mesh", "Implicit_surface_3", "Surface_mesh_default_criteria_3"],
            "symbol_notes": "CGAL::make_surface_mesh (Surface_mesher, deprecated in CGAL 6.2.1) with "
                            "Implicit_surface_3 meshes a fixed enumerated set of typed implicit "
                            "domains (sphere, ellipsoid, torus; no free-form expressions) under angle, "
                            "size and distance criteria. Checks are recomputed from the OFF output: "
                            "closed 2-manifold (no boundary), Euler characteristic 2 for sphere and "
                            "ellipsoid and 0 for the torus, every vertex on the analytic surface "
                            "(radius 2; ellipsoid 3x2x1.5; torus R=3 r=1), smallest facet angle >= "
                            "the angle bound, facet circumradius <= the size bound, and area and "
                            "volume within sampling error of 16 pi and 32 pi / 3 (sphere), "
                            "4 pi^2 R r and 2 pi^2 R r^2 (torus), 4 pi abc / 3 (ellipsoid). Finer "
                            "criteria give more facets and another radius gives another mesh. The "
                            "independent validator recomputes topology, orientation, analytic "
                            "distance, criteria and analytic area and volume.",
            "case_ids": ["surface-sphere", "surface-sphere-fine", "surface-sphere-r25",
                         "surface-ellipsoid", "surface-torus"],
        },
        "major.7.14.03": {
            "operation_ids": [VOL_GEN],
            "symbols": ["make_mesh_3", "Labeled_mesh_domain_3", "Polyhedral_mesh_domain_3",
                        "Mesh_criteria_3"],
            "symbol_notes": "CGAL::make_mesh_3 (Mesh_3) over a Polyhedral_mesh_domain_3 built from a "
                            "validated closed, outward oriented, single-component, intersection-free "
                            "TriangleSurfaceMesh (no feature protection) meshes the solid with typed "
                            "criteria: a unit cube (volume 1), an L-shaped prism (3), a staircase prism "
                            "(6) and a tilted 1x2x3 box (6). Every output is re-measured here from the "
                            "raw OFF source: boundary vertices lie on the source triangles, boundary "
                            "facet samples are within facet_size of the source and source samples "
                            "within twice facet_size of the boundary facets, facet circumcentres are "
                            "within facet_distance, the cell volume is within the stated bound of the "
                            "divergence-theorem volume, Euler characteristics are 1 and 2, and the "
                            "facet and cell criteria hold. Open, non-manifold, self-intersecting, "
                            "inconsistently oriented, inverted or multi-component sources are refused; "
                            "tampered, shifted, scaled, wrong-source and too-coarse meshes are "
                            "rejected by the validator. Image domains, polyhedral feature protection, "
                            "perturbation and exudation are not implemented. Implicit domains: "
                            "CGAL::make_mesh_3 (Mesh_3) over a Labeled_mesh_domain_3 built from a fixed "
                            "enumerated set of typed implicit domains (sphere radius 2 and 2.5, ellipsoid "
                            "3x2x1.5, torus R=3 r=1; no free-form expressions) meshes the solid with "
                            "typed facet angle/size/distance and cell radius-edge/size criteria. The "
                            "TetrahedralMesh output is re-measured here: every interior face is shared "
                            "by two cells, cells are positive, V-E+F-C is 1 for the balls and 0 for the "
                            "solid torus, the boundary is a closed surface with Euler characteristic 2 "
                            "or 0, boundary vertices lie on the analytic surface and interior vertices "
                            "strictly inside, the cell volume sums to 32 pi / 3, 4 pi abc / 3 and "
                            "2 pi^2 R r^2 within the sampling bound, the boundary area to 16 pi and "
                            "4 pi^2 R r, and the facet angle, facet radius, cell circumradius and "
                            "radius-edge criteria hold. Finer criteria give more cells. The independent "
                            "validator recomputes topology, exact orientation, the analytic domain "
                            "relation and every criterion without calling Mesh_3.",
            "case_ids": ["volume-sphere", "volume-sphere-fine", "volume-sphere-r25", "volume-ellipsoid",
                         "volume-torus", "volume-poly-cube", "volume-poly-cube-fine", "volume-poly-l-prism",
                         "volume-poly-stair-prism", "volume-poly-tilted-box"],
        },
        "major.7.14.04": {
            "operation_ids": [VOL_GEN],
            "symbols": ["Mesh_criteria_3", "Mesh_cell_criteria_3", "Mesh_facet_criteria_3",
                        "Polyhedral_mesh_domain_with_features_3"],
            "symbol_notes": "Typed MeshCriteria3 parameters (facet_angle, facet_size, facet_distance, "
                            "cell_radius_edge_ratio, cell_size, cell_size_regions, facet_topology, edge_size; "
                            "units checked, ranges checked, unknown keys rejected, no free-form expressions) "
                            "are passed to CGAL::Mesh_criteria_3 by mesh.volume.generate and re-checked one "
                            "criterion at a time by mesh.validate.volume_mesh. Each criterion has a "
                            "measurable effect re-derived here from the raw output: cell_size_regions (a "
                            "sizing field of up to four enumerated boxes, evaluated at the cell "
                            "circumcentre) bounds the circumradius of the cells inside the box by 0.3 while "
                            "the global 0.6 still holds outside and the plain mesh exceeds 0.3 there; "
                            "edge_size on the polyhedral unit cube (12 sharp edges, normal angle above 60 "
                            "degrees, protected through Polyhedral_mesh_domain_with_features_3) bounds the "
                            "gaps between consecutive mesh vertices on each cube edge and the mesh edge "
                            "lengths there by 0.5 and 0.25 (36 and 48 segments); facet_topology is carried "
                            "through and checked (every boundary facet vertex on the single-patch domain "
                            "surface). The negative controls tighten each criterion against a pinned genuine "
                            "mesh and expect that criterion's own code. Not covered: image domains, "
                            "multi-patch facet topology, sizing fields other than the enumerated boxes, "
                            "mesh.surface.generate (Surface_mesher criteria are not Mesh_criteria_3), and "
                            "facet and cell criteria on facets and cells that touch a protected feature "
                            "when edge_size is given.",
            "case_ids": ["volume-sphere-baseline-box", "volume-sphere-regions", "volume-sphere-topology-surface",
                         "volume-sphere-topology-patch", "volume-poly-cube-edge-size-half",
                         "volume-poly-cube-edge-size-quarter"],
        },
    },
    "unbound": {},
    "cases": [
        _case("mesh2-square-size2", "mesh2.refine.delaunay", [_domain(SQUARE_10)], _mesh2(0.125, 2.0), [
            ["metrics.algorithm", "==", "CGAL::refine_Delaunay_mesh_2"],
            ["metrics.criteria", "==", "CGAL::Delaunay_mesh_size_criteria_2"],
            ["metrics.input_vertex_count", "==", 4],
            ["metrics.ring_count", "==", 1],
            ["metrics.triangle_count", ">=", 58],
            ["metrics.triangle_count", "<", 231],
            ["output:mesh:measure:tri2.area", "approx", [100.0, 1e-9]],
            ["output:mesh:measure:tri2.max_edge_length", "<=", 2.0],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.max_edge_use", "<=", 2],
            ["output:mesh:measure:tri2.boundary_edge_count", ">=", 20],
            ["output:mesh:measure:tri2.boundary_edge_count", "==", {"path": "metrics.constrained_edge_count"}],
            ["output:mesh:measure:tri2.triangle_count", "==", {"path": "metrics.triangle_count"}],
        ]),
        _case("mesh2-square-size1", "mesh2.refine.delaunay", [_domain(SQUARE_10)], _mesh2(0.125, 1.0), [
            ["output:mesh:measure:tri2.area", "approx", [100.0, 1e-9]],
            ["output:mesh:measure:tri2.max_edge_length", "<=", 1.0],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.boundary_edge_count", ">=", 40],
            ["metrics.triangle_count", ">=", 231],
        ]),
        _case("mesh2-square-loose-angle", "mesh2.refine.delaunay", [_domain(SQUARE_10)],
              _mesh2(0.0625, 2.0), [
            ["output:mesh:measure:tri2.area", "approx", [100.0, 1e-9]],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_LOOSE_MIN_ANGLE],
            ["output:mesh:measure:tri2.max_edge_length", "<=", 2.0],
        ]),
        _case("mesh2-hole", "mesh2.refine.delaunay", [_domain(HOLE_SQUARE)], _mesh2(0.125, 2.0), [
            ["metrics.input_vertex_count", "==", 8],
            ["metrics.ring_count", "==", 2],
            ["output:mesh:measure:tri2.area", "approx", [91.0, 1e-9]],
            ["output:mesh:measure:tri2.max_edge_length", "<=", 2.0],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.boundary_edge_count", "==", {"path": "metrics.constrained_edge_count"}],
            ["output:mesh:measure:tri2.max_edge_use", "<=", 2],
        ]),
        _case("mesh2-lshape", "mesh2.refine.delaunay", [_domain(L_SHAPE)], _mesh2(0.125, 2.0), [
            ["metrics.input_vertex_count", "==", 6],
            ["output:mesh:measure:tri2.area", "approx", [7.0, 1e-9]],
            ["output:mesh:measure:tri2.max_edge_length", "<=", 2.0],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.boundary_edge_count", ">=", 10],
        ]),
        _case("mesh2-two-holes", "mesh2.refine.delaunay", [_domain(TWO_HOLES)], _mesh2(0.125, 2.0), [
            ["metrics.input_vertex_count", "==", 12],
            ["metrics.ring_count", "==", 3],
            ["output:mesh:measure:tri2.area", "approx", [92.0, 1e-9]],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.boundary_edge_count", "==", {"path": "metrics.constrained_edge_count"}],
        ]),
        _case("mesh2-rect-unrefined", "mesh2.refine.delaunay", [_domain(RECT_10X1)],
              _mesh2(0.001, 100.0), [
            ["metrics.triangle_count", "==", 2],
            ["metrics.vertex_count", "==", 4],
            ["metrics.steiner_vertex_count", "==", 0],
            ["output:mesh:measure:tri2.area", "approx", [10.0, 1e-12]],
            ["output:mesh:measure:tri2.min_angle_degrees", "approx", [math.degrees(math.atan(0.1)), 1e-9]],
        ]),
        _case("mesh2-rect-refined", "mesh2.refine.delaunay", [_domain(RECT_10X1)],
              _mesh2(0.125, 100.0), [
            ["metrics.triangle_count", ">", 2],
            ["metrics.steiner_vertex_count", ">", 0],
            ["output:mesh:measure:tri2.area", "approx", [10.0, 1e-9]],
            ["output:mesh:measure:tri2.min_angle_degrees", ">=", MESH2_MIN_ANGLE],
            ["output:mesh:measure:tri2.boundary_edge_count", "==", {"path": "metrics.constrained_edge_count"}],
        ]),
        _case("surface-sphere", SURF_GEN, [_surface(DOM_SPHERE)], _surf(25.0, 0.5, 0.05), [
            *_surface_checks(),
            ["metrics.domain_kind", "==", "sphere"],
            ["metrics.euler_characteristic", "==", 2],
            ["metrics.facet_count", ">=", 260],
            ["output:geometry:measure:off.min_vertex_radius", "approx", [2.0, 1e-5]],
            ["output:geometry:measure:off.max_vertex_radius", "approx", [2.0, 1e-5]],
            ["output:geometry:measure:off.area", "approx", [16.0 * PI, 0.03 * 16.0 * PI]],
            ["output:geometry:measure:off.signed_volume", "approx", [32.0 * PI / 3.0, 0.06 * 32.0 * PI / 3.0]],
            ["output:geometry:measure:off.min_angle_degrees", ">=", 25.0],
            ["output:geometry:measure:off.max_circumradius", "<=", 0.5 + 1e-9],
        ]),
        _case("surface-sphere-fine", SURF_GEN, [_surface(DOM_SPHERE)], _surf(25.0, 0.3, 0.02), [
            *_surface_checks(),
            ["metrics.euler_characteristic", "==", 2],
            ["metrics.facet_count", ">", 600],
            ["output:geometry:measure:off.min_vertex_radius", "approx", [2.0, 1e-5]],
            ["output:geometry:measure:off.max_vertex_radius", "approx", [2.0, 1e-5]],
            ["output:geometry:measure:off.area", "approx", [16.0 * PI, 0.01 * 16.0 * PI]],
            ["output:geometry:measure:off.min_angle_degrees", ">=", 25.0],
            ["output:geometry:measure:off.max_circumradius", "<=", 0.3 + 1e-9],
        ]),
        _case("surface-sphere-r25", SURF_GEN, [_surface(DOM_SPHERE_R25)], _surf(25.0, 0.5, 0.05), [
            *_surface_checks(),
            ["metrics.euler_characteristic", "==", 2],
            ["output:geometry:measure:off.min_vertex_radius", "approx", [2.5, 1e-5]],
            ["output:geometry:measure:off.max_vertex_radius", "approx", [2.5, 1e-5]],
            ["output:geometry:measure:off.area", "approx", [25.0 * PI, 0.03 * 25.0 * PI]],
            ["output:geometry:measure:off.signed_volume", "approx", [4.0 / 3.0 * PI * 15.625,
                                                                  0.06 * 4.0 / 3.0 * PI * 15.625]],
        ]),
        _case("surface-ellipsoid", SURF_GEN, [_surface(DOM_ELLIPSOID)], _surf(25.0, 0.6, 0.04), [
            *_surface_checks(),
            ["metrics.domain_kind", "==", "ellipsoid"],
            ["metrics.euler_characteristic", "==", 2],
            ["output:geometry:measure:off.max_ellipsoid_residual(3,2,1.5)", "approx", [0.0, 1e-5]],
            # Knud Thomsen's approximation of the ellipsoid area (error <= 1.1 percent) plus the
            # inscribed-facet sampling loss gives a 4 percent bound.
            ["output:geometry:measure:off.area", "approx", [ELLIPSOID_AREA, 0.04 * ELLIPSOID_AREA]],
            ["output:geometry:measure:off.signed_volume", "approx", [4.0 / 3.0 * PI * 9.0,
                                                                  0.06 * 4.0 / 3.0 * PI * 9.0]],
            ["output:geometry:measure:off.min_angle_degrees", ">=", 25.0],
            ["output:geometry:measure:off.max_circumradius", "<=", 0.6 + 1e-9],
        ]),
        _case("surface-torus", SURF_GEN, [_surface(DOM_TORUS)], _surf(25.0, 0.5, 0.03), [
            *_surface_checks(),
            ["metrics.domain_kind", "==", "torus"],
            ["metrics.euler_characteristic", "==", 0],
            ["output:geometry:measure:off.max_torus_residual(3,1)", "approx", [0.0, 1e-5]],
            ["output:geometry:measure:off.area", "approx", [12.0 * PI * PI, 0.03 * 12.0 * PI * PI]],
            ["output:geometry:measure:off.signed_volume", "approx", [6.0 * PI * PI, 0.06 * 6.0 * PI * PI]],
            ["output:geometry:measure:off.min_angle_degrees", ">=", 25.0],
            ["output:geometry:measure:off.max_circumradius", "<=", 0.5 + 1e-9],
        ]),
        _case("volume-sphere", VOL_GEN, [_surface(DOM_SPHERE)], _vol(25.0, 0.5, 0.05, 3.0, 0.6), [
            *_volume_checks(),
            ["metrics.domain_kind", "==", "sphere"],
            ["metrics.tetrahedron_count", ">=", 280],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.min_boundary_vertex_radius", "approx", [2.0, 1e-6]],
            ["output:geometry:measure:tet.max_boundary_vertex_radius", "approx", [2.0, 1e-6]],
            ["output:geometry:measure:tet.max_interior_vertex_radius", "<", 2.0 - 1e-6],
            ["output:geometry:measure:tet.volume", "approx", [32.0 * PI / 3.0, 0.08 * 32.0 * PI / 3.0]],
            ["output:geometry:measure:tet.boundary_area", "approx", [16.0 * PI, 0.04 * 16.0 * PI]],
            ["output:geometry:measure:tet.min_boundary_facet_angle", ">=", 25.0],
            ["output:geometry:measure:tet.max_boundary_facet_circumradius", "<=", 0.5 + 1e-9],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.6 + 1e-9],
            ["output:geometry:measure:tet.max_radius_edge", "<=", 3.0 + 1e-9],
        ]),
        _case("volume-sphere-fine", VOL_GEN, [_surface(DOM_SPHERE)], _vol(25.0, 0.3, 0.02, 2.5, 0.3), [
            *_volume_checks(),
            ["metrics.tetrahedron_count", ">=", 2000],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.volume", "approx", [32.0 * PI / 3.0, 0.04 * 32.0 * PI / 3.0]],
            ["output:geometry:measure:tet.boundary_area", "approx", [16.0 * PI, 0.02 * 16.0 * PI]],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.3 + 1e-9],
            ["output:geometry:measure:tet.max_radius_edge", "<=", 2.5 + 1e-9],
            ["output:geometry:measure:tet.max_boundary_facet_circumradius", "<=", 0.3 + 1e-9],
        ]),
        _case("volume-sphere-r25", VOL_GEN, [_surface(DOM_SPHERE_R25)], _vol(25.0, 0.5, 0.05, 3.0, 0.6), [
            *_volume_checks(),
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.min_boundary_vertex_radius", "approx", [2.5, 1e-6]],
            ["output:geometry:measure:tet.max_boundary_vertex_radius", "approx", [2.5, 1e-6]],
            ["output:geometry:measure:tet.volume", "approx", [4.0 / 3.0 * PI * 15.625,
                                                             0.08 * 4.0 / 3.0 * PI * 15.625]],
        ]),
        _case("volume-ellipsoid", VOL_GEN, [_surface(DOM_ELLIPSOID)], _vol(25.0, 0.6, 0.04, 3.0, 0.8), [
            *_volume_checks(),
            ["metrics.domain_kind", "==", "ellipsoid"],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.max_boundary_ellipsoid_residual(3,2,1.5)", "approx", [0.0, 1e-6]],
            ["output:geometry:measure:tet.volume", "approx", [4.0 / 3.0 * PI * 9.0, 0.08 * 4.0 / 3.0 * PI * 9.0]],
            ["output:geometry:measure:tet.boundary_area", "approx", [ELLIPSOID_AREA, 0.04 * ELLIPSOID_AREA]],
            ["output:geometry:measure:tet.min_boundary_facet_angle", ">=", 25.0],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.8 + 1e-9],
            ["output:geometry:measure:tet.max_radius_edge", "<=", 3.0 + 1e-9],
        ]),
        _case("volume-torus", VOL_GEN, [_surface(DOM_TORUS)], _vol(25.0, 0.5, 0.03, 3.0, 0.6), [
            *_volume_checks(),
            ["metrics.domain_kind", "==", "torus"],
            ["output:geometry:measure:tet.euler_characteristic", "==", 0],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 0],
            ["output:geometry:measure:tet.max_boundary_torus_residual(3,1)", "approx", [0.0, 1e-6]],
            ["output:geometry:measure:tet.volume", "approx", [6.0 * PI * PI, 0.08 * 6.0 * PI * PI]],
            ["output:geometry:measure:tet.boundary_area", "approx", [12.0 * PI * PI, 0.04 * 12.0 * PI * PI]],
            ["output:geometry:measure:tet.min_boundary_facet_angle", ">=", 25.0],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.6 + 1e-9],
            ["output:geometry:measure:tet.max_radius_edge", "<=", 3.0 + 1e-9],
        ]),
        _case("volume-poly-cube", VOL_GEN, [_poly(POLY_CUBE)], _vol(25.0, 0.25, 0.02, 3.0, 0.3),
              _poly_checks("poly_cube.off", 1.0, 6.0, 0.02, 0.25, 0.02, 25.0, 3.0, 0.3)),
        _case("volume-poly-cube-fine", VOL_GEN, [_poly(POLY_CUBE)], _vol(25.0, 0.15, 0.01, 2.5, 0.15), [
            *_poly_checks("poly_cube.off", 1.0, 6.0, 0.01, 0.15, 0.01, 25.0, 2.5, 0.15),
            ["metrics.tetrahedron_count", ">=", 2000],
        ]),
        _case("volume-poly-l-prism", VOL_GEN, [_poly(POLY_L_PRISM)], _vol(25.0, 0.4, 0.03, 3.0, 0.5),
              _poly_checks("poly_l_prism.off", 3.0, 14.0, 0.02, 0.4, 0.03, 25.0, 3.0, 0.5)),
        _case("volume-poly-stair-prism", VOL_GEN, [_poly(POLY_STAIR_PRISM)], _vol(25.0, 0.4, 0.03, 3.0, 0.5),
              _poly_checks("poly_stair_prism.off", 6.0, 24.0, 0.02, 0.4, 0.03, 25.0, 3.0, 0.5)),
        _case("volume-poly-tilted-box", VOL_GEN, [_poly(POLY_TILTED_BOX)], _vol(25.0, 0.5, 0.04, 3.0, 0.6),
              _poly_checks("poly_tilted_box.off", 6.0, 22.0, 0.02, 0.5, 0.04, 25.0, 3.0, 0.6)),
        _case("volume-sphere-baseline-box", VOL_GEN, [_surface(DOM_SPHERE)], _vol(25.0, 0.5, 0.05, 3.0, 0.6), [
            *_volume_checks(),
            ["metrics.cell_size_region_count", "==", 0],
            ["output:geometry:measure:tet." + _box_name("max_circumradius_in_box", *SPHERE_BOX), ">", 0.3 + 1e-6],
            ["output:geometry:measure:tet.tetrahedron_count", "<=", 1000],
        ]),
        _case("volume-sphere-regions", VOL_GEN, [_surface(DOM_SPHERE)],
              {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions((*SPHERE_BOX, 0.3))}, [
            *_volume_checks(),
            ["metrics.domain_kind", "==", "sphere"],
            ["metrics.cell_size_region_count", "==", 1],
            ["output:geometry:measure:tet." + _box_name("max_circumradius_in_box", *SPHERE_BOX), "<=", 0.3 + 1e-9],
            ["output:geometry:measure:tet." + _box_name("max_circumradius_outside_box", *SPHERE_BOX), ">", 0.3],
            ["output:geometry:measure:tet." + _box_name("cell_count_in_box", *SPHERE_BOX), ">=", 400],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.6 + 1e-9],
            ["output:geometry:measure:tet.max_radius_edge", "<=", 3.0 + 1e-9],
            ["output:geometry:measure:tet.tetrahedron_count", ">=", 1200],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.volume", "approx", [32.0 * PI / 3.0, 0.08 * 32.0 * PI / 3.0]],
        ]),
        *[_case(f"volume-sphere-topology-{tag}", VOL_GEN, [_surface(DOM_SPHERE)],
                {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "facet_topology": topology}, [
            *_volume_checks(),
            ["metrics.facet_topology", "==", topology],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.max_boundary_vertex_radius", "approx", [2.0, 1e-6]],
            ["output:geometry:measure:tet.min_boundary_vertex_radius", "approx", [2.0, 1e-6]],
            ["output:geometry:measure:tet.max_circumradius", "<=", 0.6 + 1e-9],
        ]) for tag, topology in (("surface", "FACET_VERTICES_ON_SURFACE"),
                                 ("patch", "FACET_VERTICES_ON_SAME_SURFACE_PATCH"))],
        _case("volume-poly-cube-edge-size-half", VOL_GEN, [_poly(POLY_CUBE)],
              {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.5)}, [
            *_volume_checks("CGAL::Polyhedral_mesh_domain_with_features_3"),
            ["metrics.domain_kind", "==", "polyhedral"],
            ["metrics.feature_protection", "==", True],
            ["metrics.sharp_edge_count", "==", 12],
            ["metrics.edge_size", "==", 0.5],
            ["metrics.source_volume", "approx", [1.0, 1e-9]],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.volume", "approx", [1.0, 0.02]],
            ["output:geometry:measure:tet.boundary_area", "approx", [6.0, 0.36]],
            ["output:geometry:measure:tet.max_boundary_vertex_distance_to_off(poly_cube.off)", "<=", 1e-9],
            ["output:geometry:measure:tet.max_boundary_sample_distance_to_off(poly_cube.off)", "<=", 0.25],
            ["output:geometry:measure:tet.max_off_sample_distance_to_boundary(poly_cube.off)", "<=", 0.5],
            ["output:geometry:measure:tet.max_cube_edge_vertex_gap", "<=", 0.5 + 1e-9],
            ["output:geometry:measure:tet.max_cube_edge_vertex_gap", ">", 0.25],
            ["output:geometry:measure:tet.max_cube_edge_mesh_segment", "<=", 0.5 + 1e-9],
            ["output:geometry:measure:tet.cube_edge_mesh_segment_count", "==", 36],
        ]),
        _case("volume-poly-cube-edge-size-quarter", VOL_GEN, [_poly(POLY_CUBE)],
              {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.25)}, [
            *_volume_checks("CGAL::Polyhedral_mesh_domain_with_features_3"),
            ["metrics.domain_kind", "==", "polyhedral"],
            ["metrics.feature_protection", "==", True],
            ["metrics.sharp_edge_count", "==", 12],
            ["metrics.edge_size", "==", 0.25],
            ["metrics.source_volume", "approx", [1.0, 1e-9]],
            ["output:geometry:measure:tet.euler_characteristic", "==", 1],
            ["output:geometry:measure:tet.boundary_euler_characteristic", "==", 2],
            ["output:geometry:measure:tet.volume", "approx", [1.0, 0.02]],
            ["output:geometry:measure:tet.boundary_area", "approx", [6.0, 0.36]],
            ["output:geometry:measure:tet.max_boundary_vertex_distance_to_off(poly_cube.off)", "<=", 1e-9],
            ["output:geometry:measure:tet.max_boundary_sample_distance_to_off(poly_cube.off)", "<=", 0.25],
            ["output:geometry:measure:tet.max_off_sample_distance_to_boundary(poly_cube.off)", "<=", 0.5],
            ["output:geometry:measure:tet.max_cube_edge_vertex_gap", "<=", 0.25 + 1e-9],
            ["output:geometry:measure:tet.max_cube_edge_vertex_gap", ">", 0.125],
            ["output:geometry:measure:tet.max_cube_edge_mesh_segment", "<=", 0.25 + 1e-9],
            ["output:geometry:measure:tet.cube_edge_mesh_segment_count", "==", 48],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["volume-sphere", "volume-sphere-regions"]},
        {"kind": "different_outputs", "cases": ["volume-poly-cube", "volume-poly-cube-edge-size-half"]},
        {"kind": "different_outputs", "cases": ["volume-poly-cube-edge-size-half", "volume-poly-cube-edge-size-quarter"]},
        {"kind": "different_outputs", "cases": ["volume-poly-cube", "volume-poly-cube-fine"]},
        {"kind": "different_outputs", "cases": ["surface-sphere", "surface-sphere-fine"]},
        {"kind": "different_outputs", "cases": ["volume-sphere", "volume-sphere-fine"]},
        {"kind": "different_outputs", "cases": ["mesh2-square-size2", "mesh2-square-size1"]},
        {"kind": "different_outputs", "cases": ["mesh2-rect-unrefined", "mesh2-rect-refined"]},
    ],
    "negative_controls": [
        {"id": "surface-expression-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_EXPRESSION)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "UNSUPPORTED_DOMAIN_KIND"},
        {"id": "surface-unknown-kind-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_UNKNOWN_KIND)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "UNSUPPORTED_DOMAIN_KIND"},
        {"id": "surface-negative-radius-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_NEGATIVE_RADIUS)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "surface-extra-parameter-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_EXTRA_PARAMETER)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "SCHEMA_MISMATCH"},
        {"id": "surface-thick-torus-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_THICK_TORUS)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "surface-needle-ellipsoid-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_NEEDLE_ELLIPSOID)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "surface-angle-above-guarantee-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _surf(31.0, 0.5, 0.05),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "surface-distance-too-coarse-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.5),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "surface-unit-mismatch-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_SPHERE)],
         "parameters": {"angle_bound": 25.0, "size_bound": {"value": 0.5, "unit": "cm"},
                        "distance_bound": _mm(0.05)},
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "UNIT_MISMATCH"},
        {"id": "surface-size-budget-rejected", "operation": SURF_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.01, 0.0001),
         "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "surface-missing-triangle-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_MISSING), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SURFACE_NOT_CLOSED"},
        {"id": "surface-flipped-one-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_FLIPPED_ONE), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "INCONSISTENT_ORIENTATION"},
        {"id": "surface-flipped-all-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_FLIPPED_ALL), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "ORIENTATION_NOT_OUTWARD"},
        {"id": "surface-duplicate-face-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_DUPLICATE), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "NON_MANIFOLD_EDGE"},
        {"id": "surface-scaled-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SCALED), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "surface-wrong-radius-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_SPHERE_R25)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "surface-sphere-vs-ellipsoid-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_ELLIPSOID)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "surface-sphere-vs-torus-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_TORUS)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "EULER_CHARACTERISTIC_MISMATCH"},
        {"id": "surface-torus-vs-sphere-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_TORUS_MESH), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "EULER_CHARACTERISTIC_MISMATCH"},
        {"id": "surface-ellipsoid-vs-sphere-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_ELLIPSOID_MESH), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.6, 0.04),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "surface-stricter-angle-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _surf(35.0, 0.5, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "ANGLE_CRITERION_VIOLATED"},
        {"id": "surface-stricter-size-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.2, 0.05),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SIZE_CRITERION_VIOLATED"},
        {"id": "surface-stricter-distance-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _surf(25.0, 0.5, 0.02),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "DISTANCE_CRITERION_VIOLATED"},
        {"id": "surface-coarse-octahedron-rejected", "operation": SURF_VAL,
         "inputs": [_mesh(SURF_OCTAHEDRON), _surface(DOM_SPHERE)], "parameters": _surf(30.0, 5.0, 5.0),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "AREA_MISMATCH"},
        {"id": "volume-expression-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_EXPRESSION)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "UNSUPPORTED_DOMAIN_KIND"},
        {"id": "volume-unknown-kind-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_UNKNOWN_KIND)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "UNSUPPORTED_DOMAIN_KIND"},
        {"id": "volume-negative-radius-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_NEGATIVE_RADIUS)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "volume-extra-parameter-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_EXTRA_PARAMETER)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "SCHEMA_MISMATCH"},
        {"id": "volume-thick-torus-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_THICK_TORUS)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "volume-needle-ellipsoid-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_NEEDLE_ELLIPSOID)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INPUT_ERROR", "expect_error_code": "INVALID_DOMAIN"},
        {"id": "volume-angle-above-guarantee-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _vol(31.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-radius-edge-below-guarantee-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 1.99, 0.6),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-distance-too-coarse-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.5, 3.0, 0.6),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-size-budget-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.05),
         "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "volume-unit-mismatch-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size": {"value": 0.6, "unit": "cm"}},
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "UNIT_MISMATCH"},
        {"id": "volume-missing-interior-cell-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_MISSING_INTERIOR), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "MULTIPLE_BOUNDARY_SURFACES"},
        {"id": "volume-missing-boundary-cell-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_MISSING_BOUNDARY), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-flipped-cell-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_FLIPPED), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "INVERTED_TETRAHEDRON"},
        {"id": "volume-duplicate-cell-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_DUPLICATE), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "NON_MANIFOLD_FACE"},
        {"id": "volume-scaled-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SCALED), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OUTSIDE_DOMAIN"},
        {"id": "volume-two-subdomains-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_TWO_SUBDOMAINS), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SUBDOMAIN_INDEX_INVALID"},
        {"id": "volume-wrong-radius-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE_R25)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-sphere-vs-ellipsoid-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_ELLIPSOID)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OUTSIDE_DOMAIN"},
        {"id": "volume-sphere-vs-torus-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_TORUS)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "EULER_CHARACTERISTIC_MISMATCH"},
        {"id": "volume-torus-vs-sphere-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_TORUS_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "EULER_CHARACTERISTIC_MISMATCH"},
        {"id": "volume-ellipsoid-vs-sphere-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_ELLIPSOID_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.6, 0.04, 3.0, 0.8),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OUTSIDE_DOMAIN"},
        {"id": "volume-stricter-facet-angle-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _vol(35.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_ANGLE_VIOLATED"},
        {"id": "volume-stricter-facet-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.3, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_SIZE_VIOLATED"},
        {"id": "volume-stricter-facet-distance-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.02, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_DISTANCE_VIOLATED"},
        {"id": "volume-stricter-cell-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.4),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "CELL_SIZE_VIOLATED"},
        {"id": "volume-stricter-radius-edge-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 1.5, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "RADIUS_EDGE_VIOLATED"},
        {"id": "volume-coarse-octahedron-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_OCTAHEDRON), _surface(DOM_SPHERE)], "parameters": _vol(25.0, 0.5, 0.05, 3.0, 0.6),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_SIZE_VIOLATED"},
        {"id": "volume-coarse-octahedron-area-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_OCTAHEDRON), _surface(DOM_SPHERE)], "parameters": _vol(30.0, 5.0, 5.0, 100.0, 50.0),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "AREA_MISMATCH"},
        {"id": "volume-poly-open-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE_OPEN)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "MESH_NOT_CLOSED"},
        {"id": "volume-poly-open-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE_OPEN)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_MESH_NOT_CLOSED"},
        {"id": "volume-poly-inverted-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE_INVERTED)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "INWARD_ORIENTED_INPUT"},
        {"id": "volume-poly-inverted-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE_INVERTED)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_INWARD_ORIENTED_INPUT"},
        {"id": "volume-poly-inconsistent-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE_INCONSISTENT)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "INCONSISTENT_ORIENTATION"},
        {"id": "volume-poly-inconsistent-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE_INCONSISTENT)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_INCONSISTENT_ORIENTATION"},
        {"id": "volume-poly-self-intersecting-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE_SELF_INTERSECTING)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "SELF_INTERSECTING_INPUT"},
        {"id": "volume-poly-self-intersecting-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE_SELF_INTERSECTING)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_SELF_INTERSECTING_INPUT"},
        {"id": "volume-poly-two-components-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_TWO_CUBES)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "MULTIPLE_COMPONENTS"},
        {"id": "volume-poly-two-components-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_TWO_CUBES)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_MULTIPLE_COMPONENTS"},
        {"id": "volume-poly-non-manifold-source-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE_NONMANIFOLD)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "NON_MANIFOLD_INPUT"},
        {"id": "volume-poly-non-manifold-source-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE_NONMANIFOLD)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_NON_MANIFOLD_INPUT"},
        {"id": "volume-poly-missing-interior-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_MISSING_INTERIOR), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "BOUNDARY_NOT_CLOSED"},
        {"id": "volume-poly-missing-boundary-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_MISSING_BOUNDARY), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_DISTANCE_VIOLATED"},
        {"id": "volume-poly-flipped-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_FLIPPED), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "INVERTED_TETRAHEDRON"},
        {"id": "volume-poly-duplicate-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_DUPLICATE), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "NON_MANIFOLD_FACE"},
        {"id": "volume-poly-shifted-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_SHIFTED), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-scaled-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_SCALED), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-bumped-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_BUMPED), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-two-subdomains-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_TWO_SUBDOMAINS), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SUBDOMAIN_INDEX_INVALID"},
        {"id": "volume-poly-cube-vs-l-prism-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_L_PRISM)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-cube-vs-tilted-box-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_TILTED_BOX)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-l-prism-vs-cube-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_L_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.4, 0.03, 3.0, 0.5),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_OFF_SURFACE"},
        {"id": "volume-poly-partial-fill-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_BOX_IN_L_MESH), _poly(POLY_L_PRISM)], "parameters": _vol(25.0, 0.4, 0.03, 3.0, 0.5),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "ORIENTATION_NOT_OUTWARD"},
        {"id": "volume-poly-stricter-angle-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": _vol(35.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_ANGLE_VIOLATED"},
        {"id": "volume-poly-stricter-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.15, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_SIZE_VIOLATED"},
        {"id": "volume-poly-stricter-distance-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.005, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_DISTANCE_VIOLATED"},
        {"id": "volume-poly-stricter-cell-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.2),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "CELL_SIZE_VIOLATED"},
        {"id": "volume-poly-stricter-radius-edge-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 1.5, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "RADIUS_EDGE_VIOLATED"},
        {"id": "volume-poly-size-budget-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.0001, 3.0, 0.3),
         "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "volume-poly-angle-above-guarantee-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE)], "parameters": _vol(31.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-poly-unit-mismatch-rejected", "operation": VOL_GEN,
         "inputs": [{**_poly(POLY_CUBE), "unit": "cm"}], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "UNIT_MISMATCH"},
        {"id": "volume-region-unrefined-mesh-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions((*SPHERE_BOX, 0.3))},
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "CELL_SIZE_REGION_VIOLATED"},
        {"id": "volume-poly-region-unrefined-mesh-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "cell_size_regions": _regions(((0.0, 0.0, 0.0), (0.5, 0.5, 0.5), 0.1))},
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "CELL_SIZE_REGION_VIOLATED"},
        {"id": "volume-poly-edge-size-unprotected-mesh-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_MESH), _poly(POLY_CUBE)], "parameters": {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.5)},
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FEATURE_EDGE_NOT_PROTECTED"},
        {"id": "volume-poly-edge-size-tightened-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_FEATURES_MESH), _poly(POLY_CUBE)], "parameters": {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.25)},
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "EDGE_SIZE_VIOLATED"},
        {"id": "volume-poly-features-mesh-without-edge-size-rejected", "operation": VOL_VAL,
         "inputs": [_tet(POLY_CUBE_FEATURES_MESH), _poly(POLY_CUBE)], "parameters": _vol(25.0, 0.25, 0.02, 3.0, 0.3),
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACET_ANGLE_VIOLATED"},
        {"id": "volume-edge-size-implicit-validator-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "edge_size": _mm(0.3)},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "CRITERION_NOT_APPLICABLE"},
        {"id": "volume-edge-size-implicit-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "edge_size": _mm(0.3)},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "CRITERION_NOT_APPLICABLE"},
        {"id": "volume-poly-edge-size-no-sharp-edges-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_ICOSPHERE)], "parameters": {**_vol(25.0, 0.3, 0.02, 3.0, 0.4), "edge_size": _mm(0.3)},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "CRITERION_NOT_APPLICABLE"},
        {"id": "volume-poly-edge-size-patch-topology-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE)], "parameters": {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.5), "facet_topology": "FACET_VERTICES_ON_SAME_SURFACE_PATCH"},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "CRITERION_NOT_APPLICABLE"},
        {"id": "volume-poly-edge-size-budget-rejected", "operation": VOL_GEN,
         "inputs": [_poly(POLY_CUBE)], "parameters": {**_vol(25.0, 0.25, 0.02, 3.0, 0.3), "edge_size": _mm(0.0005)},
         "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "volume-region-outside-domain-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions(((5.0, 5.0, 5.0), (6.0, 6.0, 6.0), 0.3))},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "REGION_OUTSIDE_DOMAIN"},
        {"id": "volume-region-not-smaller-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions((*SPHERE_BOX, 0.6))},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-region-inverted-box-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions((SPHERE_BOX[1], SPHERE_BOX[0], 0.3))},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-region-too-many-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": _regions(*[(*SPHERE_BOX, 0.3)] * 5)},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-region-empty-list-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": []},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-region-unit-mismatch-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": [{**_regions((*SPHERE_BOX, 0.3))[0], "cell_size": {"value": 0.3, "unit": "cm"}}]},
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "UNIT_MISMATCH"},
        {"id": "volume-region-free-form-key-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": [{**_regions((*SPHERE_BOX, 0.3))[0], "expression": "x*x"}]},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-topology-unknown-value-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "facet_topology": "FACET_VERTICES_ANYWHERE"},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "volume-unknown-criterion-rejected", "operation": VOL_GEN,
         "inputs": [_surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "mystery_criterion": 1},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "UNSUPPORTED_PARAMETER"},
        {"id": "volume-region-validator-unit-mismatch-rejected", "operation": VOL_VAL,
         "inputs": [_tet(VOL_SPHERE_MESH), _surface(DOM_SPHERE)], "parameters": {**_vol(25.0, 0.5, 0.05, 3.0, 0.6), "cell_size_regions": [{**_regions((*SPHERE_BOX, 0.3))[0], "cell_size": {"value": 0.3, "unit": "cm"}}]},
         "expect_error_class": "TYPE_ERROR", "expect_error_code": "UNIT_MISMATCH"},
        {"id": "mesh2-bowtie-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(BOWTIE)], "parameters": _mesh2(0.125, 2.0),
         "expect_error_class": "PRECONDITION_FAILED",
         "expect_error_code": "SELF_INTERSECTING_DOMAIN"},
        {"id": "mesh2-hole-outside-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(HOLE_OUTSIDE)], "parameters": _mesh2(0.125, 2.0),
         "expect_error_class": "PRECONDITION_FAILED",
         "expect_error_code": "SELF_INTERSECTING_DOMAIN"},
        {"id": "mesh2-hole-touching-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(HOLE_TOUCHING)], "parameters": _mesh2(0.125, 2.0),
         "expect_error_class": "PRECONDITION_FAILED",
         "expect_error_code": "SELF_INTERSECTING_DOMAIN"},
        {"id": "mesh2-hole-far-outside-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(HOLE_FAR_OUTSIDE)], "parameters": _mesh2(0.125, 2.0),
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "HOLE_OUTSIDE_DOMAIN"},
        {"id": "mesh2-nested-hole-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(HOLE_NESTED)], "parameters": _mesh2(0.125, 2.0),
         "expect_error_class": "PRECONDITION_FAILED",
         "expect_error_code": "NESTED_HOLE"},
        {"id": "mesh2-aspect-above-guarantee-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(SQUARE_10)], "parameters": _mesh2(0.5, 2.0),
         "expect_error_class": "INVALID_REQUEST",
         "expect_error_code": "INVALID_PARAMETER"},
        {"id": "mesh2-zero-size-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(SQUARE_10)], "parameters": _mesh2(0.125, 0.0),
         "expect_error_class": "INVALID_REQUEST",
         "expect_error_code": "INVALID_PARAMETER"},
        {"id": "mesh2-unit-mismatch-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(SQUARE_10)],
         "parameters": {"aspect_bound": 0.125, "size_bound": {"value": 2.0, "unit": "cm"}},
         "expect_error_class": "TYPE_ERROR",
         "expect_error_code": "UNIT_MISMATCH"},
        {"id": "mesh2-size-budget-rejected", "operation": "mesh2.refine.delaunay",
         "inputs": [_domain(SQUARE_10)], "parameters": _mesh2(0.125, 0.01),
         "expect_error_class": "RESOURCE_LIMIT",
         "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "mesh2-missing-triangle-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(SQUARE_MESH_MISSING, "Triangulation2"), _domain(SQUARE_10)],
         "parameters": _mesh2(0.125, 2.0), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "EULER_CHARACTERISTIC_MISMATCH"},
        {"id": "mesh2-shifted-boundary-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(SQUARE_MESH_SHIFTED, "Triangulation2"), _domain(SQUARE_10)],
         "parameters": _mesh2(0.125, 2.0), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "CONSTRAINT_NOT_PRESERVED"},
        {"id": "mesh2-flipped-diagonal-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(HOLED_MESH_FLIPPED, "Triangulation2"), _domain(HOLE_SQUARE)],
         "parameters": _mesh2(0.001, 50.0), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "NOT_LOCALLY_DELAUNAY"},
        {"id": "mesh2-stricter-size-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(SQUARE_MESH, "Triangulation2"), _domain(SQUARE_10)],
         "parameters": _mesh2(0.125, 0.5), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "SIZE_CRITERION_VIOLATED"},
        {"id": "mesh2-stricter-aspect-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(SQUARE_MESH, "Triangulation2"), _domain(SQUARE_10)],
         "parameters": _mesh2(0.6, 2.0), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "SHAPE_CRITERION_VIOLATED"},
        {"id": "mesh2-wrong-domain-rejected", "operation": "mesh.validate.delaunay_refinement_2",
         "inputs": [_json_input(SQUARE_MESH, "Triangulation2"), _domain(L_SHAPE)],
         "parameters": _mesh2(0.125, 2.0), "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "DOMAIN_VERTEX_MISSING"},
    ],
}

def _kfx(name: str, sha: str) -> dict:
    return {"fixture": f"kernel/{name}", "sha256": sha}


K_PRIMITIVES = _kfx("primitives.json", "1a9f4ab76ebd3a4e9d2c7a5c32d1e8a3cba4ec495c11810674d515e79715809d")
K_PREDICATES = _kfx("predicates.json", "d7539b43cb71ebc3763be3f82d219627f294e9d19b10baa7921ed9336c66f635")
K_ROBUSTNESS = _kfx("robustness.json", "7a3993562218161ee1e3bced2486e5713b8665ddbac8dcc76d2bd185a57e8cae")
K_INTERSECTIONS = _kfx("intersections.json", "31ffe025532815c5b7e52c3f586d029fcf90085145384766afb1a3cf312243e0")
K_DISTANCES = _kfx("distances.json", "9d1537895b4990cc0c9ceecc4b4f6c57f21f38a3f335c20928e3794e0ad5e18d")
K_COLLINEAR = _kfx("collinear_circumcenter.json", "df062464e9594d835b828197044d7e7a697505a730814b75a432701994e568d8")
K_UNSUPPORTED = _kfx("unsupported_pair.json", "b93850e03b83b9f065b77914843f9124e289b4d9e68580b34d09fedb25d9e081")
K_TAMPERED = {
    "primitives": _kfx("tampered_primitives_report.json",
                       "235cc74fc24a0dedcb2d70092cd0c83caa7a5cb2807e30ae974989cd93f9f320"),
    "predicates": _kfx("tampered_predicates_report.json",
                       "d90b72a2956772070d4fd6c42edeeb170899ffc3ba5599c306caf4fd643f300d"),
    "robustness": _kfx("tampered_robustness_report.json",
                       "de707aaf94f58019557de540896bb2e374554b83fabf64683e22afd6415cd214"),
    "intersections": _kfx("tampered_intersections_report.json",
                          "eaf43580fd50be9004ab4dcdb692004f2b30744a70b80c09ea4444a0a3497c43"),
    "distances": _kfx("tampered_distances_report.json",
                      "d5c6031be8eafca4898cea1a79ede060df93d381e606d7a69a338a04a091445f"),
}
KERNEL_TYPES = {
    "simple_cartesian_double": "CGAL::Simple_cartesian<double>",
    "cartesian_double": "CGAL::Cartesian<double>",
    "epick": "CGAL::Exact_predicates_inexact_constructions_kernel",
    "epeck": "CGAL::Exact_predicates_exact_constructions_kernel",
}
# Double nearest to 1/3 (the centroid of (0,0),(1,0),(0,1) in every binary64-based kernel).
THIRD_BINARY64 = "6004799503160661/18014398509481984"
PRIMITIVE_KINDS = ["Point_2", "Vector_2", "Segment_2", "Line_2", "Ray_2", "Triangle_2", "Circle_2",
                   "Iso_rectangle_2", "Aff_transformation_2", "Point_3", "Vector_3", "Segment_3", "Line_3",
                   "Ray_3", "Plane_3", "Triangle_3", "Tetrahedron_3", "Sphere_3", "Iso_cuboid_3",
                   "Aff_transformation_3"]
PREDICATE_RESULTS = ["left_turn", "right_turn", "collinear", "positive", "negative", "coplanar",
                     True, False, True, False, True, False, True, False]
PREDICATE_CONSTRUCTIONS_EXACT = [["2", "0"], ["0", "0", "1"], ["4/3", "4/3"], ["1/2", "1/2", "1/2"],
                                 ["2", "2"], ["1", "1", "0"], ["1", "1", "1"]]
INTERSECTION_RESULTS = [
    {"point": ["2", "2"], "type": "point"}, {"points": [["1", "0"], ["2", "0"]], "type": "segment"},
    {"type": "empty"}, True, False,
    {"point": ["1", "1"], "type": "point"}, {"type": "empty"},
    {"coefficients": ["-1", "1", "0"], "type": "line"}, False,
    {"points": [["1", "3"], ["1", "1"], ["3", "1"]], "type": "triangle"},
    {"points": [["0", "3"], ["3/2", "0"], ["3", "0"], ["7/2", "1/2"], ["0", "4"]], "type": "polygon"},
    {"point": ["4", "0"], "type": "point"}, {"points": [["0", "4"], ["4", "0"]], "type": "segment"},
    {"type": "empty"}, True,
    {"point": ["1", "1", "0"], "type": "point"}, {"point": ["1", "1", "0"], "type": "point"},
    {"points": [["0", "0", "0"], ["1", "1", "0"]], "type": "line"}, {"type": "empty"}, False,
    {"point": ["1", "1", "0"], "type": "point"}, {"type": "empty"},
    {"points": [["-1", "1", "0"], ["5", "1", "0"]], "type": "segment"}, True,
    {"points": [["0", "0", "0"], ["0", "-1", "0"]], "type": "line"}, {"type": "empty"},
    {"coefficients": ["0", "0", "1", "0"], "type": "plane"}, False,
    {"point": ["1", "1", "0"], "type": "point"}, {"type": "empty"},
    {"points": [["0", "1", "0"], ["3", "1", "0"]], "type": "segment"}, False,
    {"point": ["1", "1", "0"], "type": "point"}, {"type": "empty"}, True,
    {"point": ["0", "0", "0"], "type": "point"}, {"type": "empty"}, {"type": "empty"},
    {"points": [["0", "0", "0"], ["1", "0", "0"]], "type": "line"}, False,
]
DISTANCE_RESULTS = ["25", "1", "1/2", "2", "4", "0", "9", "2", "3", "9", "9", "18", "1", "2", "4", "1",
                    "smaller", "equal", "larger", "larger"]


def _kq(fixture: dict) -> dict:
    return _json_input(fixture, "KernelQuerySet")


def _kernel_checks(kernel: str, queries: int) -> list[list]:
    exact_predicates = kernel in ("epick", "epeck")
    return [
        ["metrics.kernel", "==", kernel],
        ["metrics.kernel_type", "==", KERNEL_TYPES[kernel]],
        ["metrics.exact_predicates", "==", exact_predicates],
        ["metrics.exact_constructions", "==", kernel == "epeck"],
        ["metrics.query_count", "==", queries],
        ["output:analysis:json:input_representation", "==",
         "exact_rational" if kernel == "epeck" else "binary64_round_to_nearest"],
    ]


def _robustness_case(kernel: str) -> dict:
    exact_predicates = kernel in ("epick", "epeck")
    third = "1/3" if kernel == "epeck" else THIRD_BINARY64
    return _case(f"kernel-robustness-{kernel}", "kernel.predicates.evaluate", [_kq(K_ROBUSTNESS)],
                 {"kernel": kernel}, _kernel_checks(kernel, 3) + [
                     ["output:analysis:json:results.queries[*].result", "==",
                      ["left_turn" if exact_predicates else "right_turn", exact_predicates, [third, third]]],
                 ])


FAMILY_7_1 = {
    "family": "7.1",
    "scope": "family_7_1_geometry_kernel",
    "evidence_path": "docs/master/evidence/family-7.1-capabilities.json",
    "test_id": "family-7.1-replay-cases",
    "requirements": {
        "major.7.1.01": {
            "operation_ids": ["kernel.predicates.evaluate"],
            "symbols": ["Simple_cartesian", "Cartesian", "Exact_predicates_inexact_constructions_kernel",
                        "Exact_predicates_exact_constructions_kernel"],
            "symbol_notes": "The same exact-dyadic input (p = ((2^51+21)/2^52, (2^51+24)/2^52), q = (12,12), "
                            "r = (24,24); exact orientation is a left turn) is evaluated in all four kernels. "
                            "Simple_cartesian<double> and Cartesian<double> return the floating-point answer "
                            "right_turn; EPICK and EPECK return the exact left_turn. The centroid of (0,0),(1,0),"
                            "(0,1) is the binary64 value nearest 1/3 in the three double-based kernels and exactly "
                            "1/3 only in EPECK. Each report is checked by an independent GMP-rational validator; a "
                            "report that claims the floating-point answer for EPICK is rejected.",
            "case_ids": [f"kernel-robustness-{k}" for k in KERNEL_TYPES],
        },
        "major.7.1.02": {
            "operation_ids": ["kernel.primitives.construct"],
            "symbols": ["Point_2", "Point_3", "Vector_2", "Vector_3", "Line_2", "Line_3", "Ray_2", "Ray_3",
                        "Segment_2", "Segment_3", "Plane_3", "Circle_2", "Sphere_3", "Triangle_2", "Triangle_3",
                        "Tetrahedron_3", "Iso_rectangle_2", "Iso_cuboid_3", "Aff_transformation_2",
                        "Aff_transformation_3"],
            "symbol_notes": "One fixture holds one primitive of each of the 20 kinds plus affine images of 2D/3D "
                            "points and vectors. Hand-derived exact values are pinned in EPECK (tetrahedron volume "
                            "1/6, plane z=1, iso-cuboid volume 18, transformed point (5/2,-5/3)); the "
                            "Simple_cartesian case shows the same kinds and integer results in binary64. Every "
                            "derived property is recomputed by the independent rational validator.",
            "case_ids": ["kernel-primitives-epeck", "kernel-primitives-simple-cartesian"],
        },
        "major.7.1.03": {
            "operation_ids": ["kernel.predicates.evaluate"],
            "symbols": ["orientation", "collinear", "coplanar", "left_turn", "right_turn", "midpoint",
                        "centroid", "circumcenter"],
            "symbol_notes": "2D/3D orientation (all three signs), collinear, coplanar, left_turn and right_turn "
                            "with true and false answers, and midpoint, centroid and circumcenter (2D, 3D from 3 "
                            "and from 4 points) with hand-derived exact results.",
            "case_ids": ["kernel-predicates-epeck", "kernel-predicates-epick"],
        },
        "major.7.1.04": {
            "operation_ids": ["kernel.intersections.compute"],
            "symbols": ["intersection", "do_intersect"],
            "symbol_notes": "Segment/segment, line/line and triangle/triangle in 2D and line/plane, segment/"
                            "plane, plane/plane, segment/triangle, ray/triangle and line/line in 3D, covering "
                            "point, segment, line, plane, triangle, polygon and empty results plus do_intersect "
                            "true/false. Results are re-derived by exact parametric and half-plane clipping "
                            "formulas in the validator.",
            "case_ids": ["kernel-intersections-epeck", "kernel-intersections-epick"],
        },
        "major.7.1.05": {
            "operation_ids": ["kernel.distance.squared"],
            "symbols": ["squared_distance", "compare_distance", "compare_distance_to_point"],
            "symbol_notes": "squared_distance for point/point, point/line, point/segment and segment/segment in "
                            "2D and point/point, point/line, point/segment, point/plane, point/triangle (interior "
                            "and edge region), segment/segment (interior and endpoint) and line/line (skew and "
                            "parallel) in 3D, plus compare_distance and compare_distance_to_point with smaller/"
                            "equal/larger outcomes; hand-derived values are pinned.",
            "case_ids": ["kernel-distances-epeck", "kernel-distances-simple-cartesian"],
        },
    },
    "unbound": {},
    "cases": [
        *[_robustness_case(kernel) for kernel in KERNEL_TYPES],
        _case("kernel-primitives-epeck", "kernel.primitives.construct", [_kq(K_PRIMITIVES)], {"kernel": "epeck"},
              _kernel_checks("epeck", 4) + [
                  ["metrics.primitive_count", "==", 20],
                  ["output:analysis:json:results.primitives[*].kind", "==", PRIMITIVE_KINDS],
                  ["output:analysis:json:results.primitives.16.signed_volume", "==", "1/6"],
                  ["output:analysis:json:results.primitives.16.orientation", "==", "positive"],
                  ["output:analysis:json:results.primitives.14.coefficients", "==", ["0", "0", "1", "-1"]],
                  ["output:analysis:json:results.primitives.18.volume", "==", "18"],
                  ["output:analysis:json:results.primitives.5.signed_area", "==", "6"],
                  ["output:analysis:json:results.primitives.15.squared_area", "==", "4"],
                  ["output:analysis:json:results.primitives.17.squared_radius", "==", "9/4"],
                  ["output:analysis:json:results.primitives.0.coordinates", "==", ["1/3", "5/2"]],
                  ["output:analysis:json:results.queries[*].result", "==", [
                      {"coordinates": ["5/2", "-5/3"], "kind": "Point_2"},
                      {"coordinates": ["4", "3"], "kind": "Vector_2"},
                      {"coordinates": ["3", "4", "5"], "kind": "Point_3"},
                      {"coordinates": ["2", "-4", "4"], "kind": "Vector_3"}]],
              ]),
        _case("kernel-primitives-simple-cartesian", "kernel.primitives.construct", [_kq(K_PRIMITIVES)],
              {"kernel": "simple_cartesian_double"}, _kernel_checks("simple_cartesian_double", 4) + [
                  ["output:analysis:json:results.primitives[*].kind", "==", PRIMITIVE_KINDS],
                  ["output:analysis:json:results.primitives.14.coefficients", "==", ["0", "0", "1", "-1"]],
                  ["output:analysis:json:results.primitives.18.volume", "==", "18"],
                  ["output:analysis:json:results.queries.2.result.coordinates", "==", ["3", "4", "5"]],
              ]),
        _case("kernel-predicates-epeck", "kernel.predicates.evaluate", [_kq(K_PREDICATES)], {"kernel": "epeck"},
              _kernel_checks("epeck", 21) + [
                  ["output:analysis:json:results.queries[*].result", "==",
                   PREDICATE_RESULTS + PREDICATE_CONSTRUCTIONS_EXACT],
              ]),
        _case("kernel-predicates-epick", "kernel.predicates.evaluate", [_kq(K_PREDICATES)], {"kernel": "epick"},
              _kernel_checks("epick", 21) + [
                  *[[f"output:analysis:json:results.queries.{index}.result", "==", value]
                    for index, value in enumerate(PREDICATE_RESULTS)],
                  ["output:analysis:json:results.queries.18.result", "==", ["2", "2"]],
                  ["output:analysis:json:results.queries.20.result", "==", ["1", "1", "1"]],
              ]),
        _case("kernel-intersections-epeck", "kernel.intersections.compute", [_kq(K_INTERSECTIONS)],
              {"kernel": "epeck"}, _kernel_checks("epeck", 40) + [
                  ["output:analysis:json:results.queries[*].result", "==", INTERSECTION_RESULTS],
              ]),
        _case("kernel-intersections-epick", "kernel.intersections.compute", [_kq(K_INTERSECTIONS)],
              {"kernel": "epick"}, _kernel_checks("epick", 40) + [
                  ["output:analysis:json:results.queries[*].result", "==", INTERSECTION_RESULTS],
              ]),
        _case("kernel-distances-epeck", "kernel.distance.squared", [_kq(K_DISTANCES)], {"kernel": "epeck"},
              _kernel_checks("epeck", 20) + [
                  ["output:analysis:json:results.queries[*].result", "==", DISTANCE_RESULTS],
              ]),
        _case("kernel-distances-simple-cartesian", "kernel.distance.squared", [_kq(K_DISTANCES)],
              {"kernel": "simple_cartesian_double"}, _kernel_checks("simple_cartesian_double", 20) + [
                  ["output:analysis:json:results.queries[*].result", "==", DISTANCE_RESULTS],
              ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["kernel-robustness-simple_cartesian_double",
                                                "kernel-robustness-epick"]},
        {"kind": "different_outputs", "cases": ["kernel-robustness-epick", "kernel-robustness-epeck"]},
    ],
    "negative_controls": [
        {"id": "kernel-circumcenter-collinear-rejected", "operation": "kernel.predicates.evaluate",
         "inputs": [_kq(K_COLLINEAR)], "parameters": {"kernel": "epeck"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "DEGENERATE_CONFIGURATION"},
        {"id": "kernel-intersection-unsupported-pair-rejected", "operation": "kernel.intersections.compute",
         "inputs": [_kq(K_UNSUPPORTED)], "parameters": {"kernel": "epeck"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "UNSUPPORTED_PRIMITIVE_PAIR"},
        {"id": "kernel-intersection-inexact-kernel-rejected", "operation": "kernel.intersections.compute",
         "inputs": [_kq(K_INTERSECTIONS)], "parameters": {"kernel": "simple_cartesian_double"},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "kernel-primitives-tampered-volume-rejected", "operation": "kernel.validate.primitives_report",
         "inputs": [_json_input(K_TAMPERED["primitives"], "KernelReport", "none"), _kq(K_PRIMITIVES)],
         "parameters": {"kernel": "epeck"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "CONSTRUCTION_MISMATCH"},
        {"id": "kernel-predicates-tampered-circumcenter-rejected",
         "operation": "kernel.validate.predicates_report",
         "inputs": [_json_input(K_TAMPERED["predicates"], "KernelReport", "none"), _kq(K_PREDICATES)],
         "parameters": {"kernel": "epeck"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "CONSTRUCTION_MISMATCH"},
        {"id": "kernel-epick-floating-orientation-rejected", "operation": "kernel.validate.predicates_report",
         "inputs": [_json_input(K_TAMPERED["robustness"], "KernelReport", "none"), _kq(K_ROBUSTNESS)],
         "parameters": {"kernel": "epick"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "PREDICATE_MISMATCH"},
        {"id": "kernel-intersections-tampered-vertex-rejected",
         "operation": "kernel.validate.intersections_report",
         "inputs": [_json_input(K_TAMPERED["intersections"], "KernelReport", "none"), _kq(K_INTERSECTIONS)],
         "parameters": {"kernel": "epeck"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "INTERSECTION_MISMATCH"},
        {"id": "kernel-distances-tampered-value-rejected", "operation": "kernel.validate.distances_report",
         "inputs": [_json_input(K_TAMPERED["distances"], "KernelReport", "none"), _kq(K_DISTANCES)],
         "parameters": {"kernel": "epeck"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "CONSTRUCTION_MISMATCH"},
    ],
}

def _ofx(name: str, sha: str) -> dict:
    return {"fixture": f"optimization/{name}", "sha256": sha}


O_LP_OPTIMAL = _ofx("lp_optimal.json", "39f216d1cb4b671dcfc907fdc2f75238522b2e7f13ff0e6fb49937ddd8f56f3f")
O_LP_INFEASIBLE = _ofx("lp_infeasible.json", "06ea282e24c6a0ddacb787b0f25b705ccadca9fd3bd3fd5993687c73e548c3ff")
O_LP_UNBOUNDED = _ofx("lp_unbounded.json", "e0c7aedf77ab751f2a89dbf663bba48d2e15a569afb1bdc2b8c6fd7531524bd9")
O_QP_OPTIMAL = _ofx("qp_optimal.json", "44c0aa115176621890a8ac784ae1bdc7970f46f6d9dc2ba52d413a7fcf520cae")
O_QP_UNBOUNDED = _ofx("qp_unbounded.json", "44f43f1a37b14952dde7ab5ed2f5f84b5b3a450178fc6a4a9c5d959102d487ac")
O_QP_NONCONVEX = _ofx("qp_nonconvex.json", "fd67140fb8d6d5981ac39427d97203b8df1a83621505099ba3c5c3f883758a17")
O_LINEAR_FIELD = _ofx("interp_linear_field.json", "fcd79ed29c102c4170174b4adbc5247d3ee50be7a9bacad4b121fcff3e2f7054")
O_SPHERICAL_FIELD = _ofx("interp_spherical_field.json",
                         "db1c08c7ccbdb4576df5505edfffbdee8c58a9ddc60bc8995a704292d5f610bc")
O_QUERY_OUTSIDE = _ofx("interp_query_outside.json", "251976708b5c66e9d346b78d4038e40e2344728d67f906c7b15b950983b34e35")
O_COLLINEAR_SITES = _ofx("interp_collinear_sites.json",
                         "2a68c7406297ee269f1ab51d12676b8cd71af1af12d56a5b4b2eafd936cd3f13")
O_LINE_POINTS = _ofx("line_points.json", "d8acf54ec688ae6f8a01532eb79526c1ee0cf503501f6cc8583823c7525e2005")
O_CUBE = _ofx("cube_subdivided.off", "57afc11a0b7d545762e74d8c5fc417dc4d34489829b1b2835a16281879900c79")
O_TAMPERED = {
    "lp": _ofx("tampered_lp_report.json", "863221837d76cb39bedb9f769480719c03512e92a90df11fa7e1c21dd23ea830"),
    "interpolation": _ofx("tampered_interpolation_report.json",
                          "d48fa2eccd939e10aa4783ddbc46aefd5a3474680cb66f0753cca5cb27df0665"),
    "approximation": _ofx("tampered_approximation_report.json",
                          "e53254224cc276d883f7a90ffc819008b4979c3f95686e909a9e40fd7b8e1a76"),
    "matrix_search": _ofx("tampered_matrix_search_report.json",
                          "9013236ae6abf263451c793c47a9a0cfea4f365cacad7230c702c407d9b238fd"),
}
QP_SOLVER_GMPQ = "CGAL::solve_{}_program on CGAL::Quadratic_program<CGAL::Gmpq>"
VSA_FINE = {"max_number_of_proxies": 12, "number_of_iterations": 20, "seeding": "hierarchical"}
VSA_COARSE = {"max_number_of_proxies": 3, "number_of_iterations": 20, "seeding": "incremental"}


def _qp(fixture: dict) -> dict:
    return _json_input(fixture, "QuadraticProgram", "none")


def _program_case(case_id: str, fixture: dict, solver: str, status: str, extra: list[list]) -> dict:
    return _case(case_id, "optimization.quadratic_program", [_qp(fixture)], {"solver": solver}, [
        ["metrics.solver", "==", solver],
        ["metrics.algorithm", "==", QP_SOLVER_GMPQ.format(solver)],
        ["metrics.exact_number_type", "==", "CGAL::Gmpq"],
        ["metrics.status", "==", status],
        ["output:analysis:json:report_kind", "==", "quadratic_program"],
        ["output:analysis:json:results.status", "==", status],
        ["output:analysis:json:results.certificate.kind", "==",
         {"optimal": "optimality", "infeasible": "infeasibility", "unbounded": "unboundedness"}[status]],
    ] + extra)


def _interpolation_case(case_id: str, fixture: dict, method: str, values: list[str]) -> dict:
    kernel = ("CGAL::Exact_predicates_exact_constructions_kernel" if method == "linear"
              else "CGAL::Exact_predicates_inexact_constructions_kernel")
    function = "linear_interpolation" if method == "linear" else "sibson_c1_interpolation"
    return _case(case_id, "optimization.interpolate", [_json_input(fixture, "InterpolationData2")],
                 {"method": method}, [
                     ["metrics.method", "==", method],
                     ["metrics.kernel", "==", kernel],
                     ["metrics.algorithm", "==", f"CGAL::natural_neighbor_coordinates_2 + CGAL::{function}"],
                     ["metrics.site_count", "==", 13],
                     ["metrics.query_count", "==", 5],
                     ["output:analysis:json:results.input_representation", "==",
                      "exact_rational" if method == "linear" else "binary64_round_to_nearest"],
                     ["output:analysis:json:results.queries[*].value", "==", values],
                     ["output:analysis:json:results.queries.4.neighbors", "==", [{"coordinate": "1", "site": 10}]],
                 ])


FAMILY_7_15 = {
    "family": "7.15",
    "scope": "family_7_15_optimization_numerical_geometry",
    "evidence_path": "docs/master/evidence/family-7.15-capabilities.json",
    "test_id": "family-7.15-replay-cases",
    "requirements": {
        "major.7.15.01": {
            "operation_ids": ["optimization.quadratic_program"],
            "symbols": ["Quadratic_program", "solve_linear_program", "solve_quadratic_program"],
            "symbol_notes": "Programs are built as CGAL::Quadratic_program<CGAL::Gmpq> (A, b, relations, finite "
                            "and infinite bounds, c, c0, 2D) and solved exactly. solve_linear_program yields an "
                            "optimal LP (x = (8/5, 6/5, 8/5), objective -14/5, an equality row and a free "
                            "variable), an infeasible LP and an unbounded LP; solve_quadratic_program yields the "
                            "manual's first_qp optimum (2, 3) with objective 8 and an unbounded convex QP. The "
                            "independent GMP validator checks primal feasibility, convexity (exact LDL^T) and the "
                            "solver's optimality/Farkas/unboundedness certificate against the QP_solver manual's "
                            "lemmas; a non-PSD D and a quadratic program sent to the LP solver are rejected.",
            "case_ids": ["optimization-lp-optimal", "optimization-lp-infeasible", "optimization-lp-unbounded",
                         "optimization-qp-optimal", "optimization-qp-unbounded"],
        },
        "major.7.15.02": {
            "operation_ids": ["optimization.interpolate"],
            "symbols": ["natural_neighbor_coordinates_2", "linear_interpolation", "sibson_c1_interpolation"],
            "symbol_notes": "13 scattered sites with values and gradients; natural_neighbor_coordinates_2 on a "
                            "Delaunay_triangulation_2 feeds linear_interpolation (EPECK, exact rationals: it "
                            "reproduces the linear field 2 + 3x - y exactly) and sibson_c1_interpolation (EPICK, "
                            "with gradients: it reproduces the spherical quadratic 1/4 + 1.3x - 0.7y + 0.2(x^2+y^2) "
                            "to rounding, which linear interpolation does not). The validator recomputes every "
                            "natural-neighbour coordinate as an exact Voronoi-area ratio and re-evaluates both "
                            "interpolants; queries outside the hull and collinear sites are rejected.",
            "case_ids": ["optimization-interpolation-linear-exact", "optimization-interpolation-sibson-c1",
                         "optimization-interpolation-linear-on-quadratic"],
        },
        "major.7.15.03": {
            "operation_ids": ["optimization.approximate_mesh"],
            "symbols": ["approximate_triangle_mesh"],
            "symbol_notes": "Surface_mesh_approximation::approximate_triangle_mesh (Variational Shape "
                            "Approximation, L21 metric) on a subdivided 48-face cube: 12 hierarchical proxies fit "
                            "the six planes with zero L21 error and an anchor mesh lying on the source, while 3 "
                            "incremental proxies leave a positive squared L21 error (unit mm2). The validator "
                            "recomputes the partition, patch connectivity, area-weighted proxy normals, the "
                            "squared error, output-mesh validity and anchor deviation; too many proxies and a "
                            "tampered proxy are rejected.",
            "case_ids": ["optimization-vsa-fine", "optimization-vsa-coarse"],
        },
        "major.7.15.04": {
            "operation_ids": ["optimization.matrix_search"],
            "symbols": ["sorted_matrix_search"],
            "symbol_notes": "The 1D interval p-center problem is solved by sorted_matrix_search over a "
                            "Cartesian_matrix of exact pairwise gaps (row- and column-sorted) with a greedy cover "
                            "feasibility predicate: 12 points need diameter 9 for p = 3 and 7 for p = 4. The "
                            "validator scans every candidate gap exactly to confirm feasibility and minimality "
                            "and checks the reported centers cover every point; p >= n and a tampered optimum "
                            "are rejected.",
            "case_ids": ["optimization-p-center-3", "optimization-p-center-4"],
        },
    },
    "unbound": {},
    "cases": [
        _program_case("optimization-lp-optimal", O_LP_OPTIMAL, "linear", "optimal", [
            ["metrics.objective_value", "==", "-14/5"],
            ["output:analysis:json:results.variable_values", "==", ["8/5", "6/5", "8/5"]],
            ["output:analysis:json:results.objective_value", "==", "-14/5"],
        ]),
        _program_case("optimization-lp-infeasible", O_LP_INFEASIBLE, "linear", "infeasible", [
            ["output:analysis:json:results.variable_values", "==", None],
            ["output:analysis:json:results.objective_value", "==", None],
        ]),
        _program_case("optimization-lp-unbounded", O_LP_UNBOUNDED, "linear", "unbounded", [
            ["output:analysis:json:results.objective_value", "==", None],
        ]),
        _program_case("optimization-qp-optimal", O_QP_OPTIMAL, "quadratic", "optimal", [
            ["output:analysis:json:results.variable_values", "==", ["2", "3"]],
            ["output:analysis:json:results.objective_value", "==", "8"],
        ]),
        _program_case("optimization-qp-unbounded", O_QP_UNBOUNDED, "quadratic", "unbounded", [
            ["output:analysis:json:results.objective_value", "==", None],
        ]),
        _interpolation_case("optimization-interpolation-linear-exact", O_LINEAR_FIELD, "linear",
                            ["51/10", "1", "32/5", "10", "25/4"]),
        _interpolation_case("optimization-interpolation-sibson-c1", O_SPHERICAL_FIELD, "sibson_c1",
                            ["4643211215818981/2251799813685248", "950759921333771/9007199254740992",
                             "2534400690302747/562949953421312", "6136154492292299/1125899906842624",
                             "6839841934068941/2251799813685248"]),
        _interpolation_case("optimization-interpolation-linear-on-quadratic", O_SPHERICAL_FIELD, "linear",
                            ["10777359153449/4860199956600", "4545973641103/17660716152000",
                             "189707811510337/41238365474800", "135747/24280", "243/80"]),
        _case("optimization-vsa-fine", "optimization.approximate_mesh", [_mesh(O_CUBE)], VSA_FINE, [
            ["metrics.proxy_count", "==", 12],
            ["metrics.is_manifold", "==", True],
            ["metrics.l21_error", "approx", [0.0, 1e-12]],
            ["output:analysis:json:results.face_count", "==", 48],
            ["output:analysis:json:results.l21_error.unit", "==", "mm2"],
            ["output:analysis:json:results.l21_error.squared_length", "==", True],
            ["output:analysis:json:results.anchor_max_distance_to_source.value", "approx", [0.0, 1e-12]],
        ]),
        _case("optimization-vsa-coarse", "optimization.approximate_mesh", [_mesh(O_CUBE)], VSA_COARSE, [
            ["metrics.proxy_count", "==", 3],
            ["metrics.l21_error", ">", 1.0],
            ["output:analysis:json:results.face_count", "==", 48],
            ["output:analysis:json:results.l21_error.unit", "==", "mm2"],
        ]),
        _case("optimization-p-center-3", "optimization.matrix_search", [_json_input(O_LINE_POINTS, "PointSet1")],
              {"centers": 3}, [
                  ["metrics.point_count", "==", 12],
                  ["metrics.matrix_dimension", "==", 12],
                  ["output:analysis:json:results.optimal_diameter", "==", "9"],
                  ["output:analysis:json:results.optimal_radius", "==", "9/2"],
                  ["output:analysis:json:results.centers", "==", ["9/2", "17", "53/2"]],
              ]),
        _case("optimization-p-center-4", "optimization.matrix_search", [_json_input(O_LINE_POINTS, "PointSet1")],
              {"centers": 4}, [
                  ["metrics.point_count", "==", 12],
                  ["output:analysis:json:results.optimal_diameter", "==", "7"],
                  ["output:analysis:json:results.optimal_radius", "==", "7/2"],
                  ["output:analysis:json:results.centers", "==", ["7/2", "23/2", "39/2", "67/2"]],
              ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["optimization-interpolation-sibson-c1",
                                                "optimization-interpolation-linear-on-quadratic"]},
        {"kind": "different_outputs", "cases": ["optimization-vsa-fine", "optimization-vsa-coarse"]},
        {"kind": "different_outputs", "cases": ["optimization-p-center-3", "optimization-p-center-4"]},
    ],
    "negative_controls": [
        {"id": "optimization-qp-nonconvex-rejected", "operation": "optimization.quadratic_program",
         "inputs": [_qp(O_QP_NONCONVEX)], "parameters": {"solver": "quadratic"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "NOT_POSITIVE_SEMIDEFINITE"},
        {"id": "optimization-lp-quadratic-term-rejected", "operation": "optimization.quadratic_program",
         "inputs": [_qp(O_QP_OPTIMAL)], "parameters": {"solver": "linear"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "NONZERO_QUADRATIC_TERM"},
        {"id": "optimization-lp-tampered-objective-rejected", "operation": "optimization.validate.quadratic_program",
         "inputs": [_json_input(O_TAMPERED["lp"], "OptimizationReport", "none"), _qp(O_LP_OPTIMAL)],
         "parameters": {"solver": "linear"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "OBJECTIVE_MISMATCH"},
        {"id": "optimization-interpolation-outside-hull-rejected", "operation": "optimization.interpolate",
         "inputs": [_json_input(O_QUERY_OUTSIDE, "InterpolationData2")], "parameters": {"method": "linear"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "QUERY_OUTSIDE_HULL"},
        {"id": "optimization-interpolation-collinear-rejected", "operation": "optimization.interpolate",
         "inputs": [_json_input(O_COLLINEAR_SITES, "InterpolationData2")], "parameters": {"method": "linear"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "DEGENERATE_SITES"},
        {"id": "optimization-interpolation-tampered-value-rejected",
         "operation": "optimization.validate.interpolation",
         "inputs": [_json_input(O_TAMPERED["interpolation"], "OptimizationReport", "none"),
                    _json_input(O_LINEAR_FIELD, "InterpolationData2")],
         "parameters": {"method": "linear"}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "INTERPOLATION_MISMATCH"},
        {"id": "optimization-vsa-too-many-proxies-rejected", "operation": "optimization.approximate_mesh",
         "inputs": [_mesh(O_CUBE)], "parameters": {"max_number_of_proxies": 49, "number_of_iterations": 5,
                                                    "seeding": "hierarchical"},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "TOO_MANY_PROXIES"},
        {"id": "optimization-vsa-tampered-proxy-rejected", "operation": "optimization.validate.mesh_approximation",
         "inputs": [_json_input(O_TAMPERED["approximation"], "OptimizationReport", "none"), _mesh(O_CUBE)],
         "parameters": VSA_FINE, "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "PROXY_MISMATCH"},
        {"id": "optimization-p-center-trivial-rejected", "operation": "optimization.matrix_search",
         "inputs": [_json_input(O_LINE_POINTS, "PointSet1")], "parameters": {"centers": 12},
         "expect_error_class": "PRECONDITION_FAILED", "expect_error_code": "TRIVIAL_CENTER_COUNT"},
        {"id": "optimization-p-center-tampered-optimum-rejected", "operation": "optimization.validate.matrix_search",
         "inputs": [_json_input(O_TAMPERED["matrix_search"], "OptimizationReport", "none"),
                    _json_input(O_LINE_POINTS, "PointSet1")],
         "parameters": {"centers": 3}, "expect_error_class": "VALIDATION_FAILED",
         "expect_error_code": "OPTIMUM_MISMATCH"},
    ],
}


def _rfx(name: str, sha: str) -> dict:
    return {"fixture": f"reconstruction/{name}", "sha256": sha}


R_SPHERE_DENSE = _rfx("sphere_dense_normals.ply", "95f3480275a8d98f7ac71a3ead6dc015ea8cf7090f85e31759e309edbedae873")
R_TORUS_NORMALS = _rfx("torus_normals.ply", "105a7aec80dc4270226d68f1e03ca21de00c10ab8f2ce7f859ffe40120b2dd0c")
R_SPHERE_ZERO = _rfx("sphere_zero_normal.ply", "42a4b031f696ca314abc6a694add71096009ed99272a2fbf2c8e73b8847e1b7c")
R_SPHERE_XYZ = _rfx("sphere_points.xyz", "eec51f63b0fd681275fb2cb2039b36f5908d814253d4f0963019e36cd05b6db0")
R_TORUS_XYZ = _rfx("torus_points.xyz", "1b431b05d6b8c211119a08793b2c330ed4982cddb648d1c0751b8dfb3582a4f5")
R_TAMPERED = {
    "poisson_flipped": _rfx("tampered_poisson_flipped.off",
                            "00ace823ccd9ae18dc81058043ab5f40ec1fa338d0be911540af5430728127c8"),
    "poisson_shrunk": _rfx("tampered_poisson_shrunk.off",
                           "9955446bffdb0c7722e0ead7aab7af8ea7f440078417609b3ac42c37fb36cf57"),
    "wrap_shrunk": _rfx("tampered_wrap_shrunk.off",
                        "7b847cabf11a419700223a603cd06b979cb5750865a43007c67f12241036bf7c"),
    "wrap_grown": _rfx("tampered_wrap_grown.off",
                       "557f1674b859cea6ad08842168d3de6befd75e365cd09851b5a2933b208118d3"),
    "wrap_vertex_inside": _rfx("tampered_wrap_vertex_inside.off",
                               "7504c4c5c66f4292d74cf46e05ebdd58fbc9b8c9b6445b988b10bd738f12ad6c"),
}
R_POISSON_SPHERE = {"sm_angle": 20, "sm_radius": 2, "sm_distance": 0.375, "max_deviation": _mm(3.0)}
R_POISSON_TORUS = {"sm_angle": 20, "sm_radius": 2, "sm_distance": 0.375, "max_deviation": _mm(4.0)}
R_POISSON_TORUS_FINE = {"sm_angle": 20, "sm_radius": 1.5, "sm_distance": 0.25, "max_deviation": _mm(4.0)}
R_WRAP_SPHERE = {"alpha": _mm(3.0), "offset": _mm(0.5)}
R_WRAP_TORUS_FINE = {"alpha": _mm(2.5), "offset": _mm(0.5)}
R_WRAP_TORUS_COARSE = {"alpha": _mm(15.0), "offset": _mm(0.5)}
R_SPHERE_VOLUME = 4.0 / 3.0 * math.pi * 1000.0
R_SPHERE_AREA = 4.0 * math.pi * 100.0
R_TORUS_VOLUME = 2.0 * math.pi ** 2 * 10.0 * 16.0
R_TORUS_AREA = 4.0 * math.pi ** 2 * 10.0 * 4.0
R_POISSON_ALGORITHM = "CGAL::Poisson_reconstruction_function + CGAL::make_mesh_3"


def _closed_mesh_checks(euler: int) -> list[list]:
    return [
        ["output:geometry:measure:off.boundary_edge_count", "==", 0],
        ["output:geometry:measure:off.max_face_degree", "==", 3],
        ["output:geometry:measure:off.euler_characteristic", "==", euler],
        ["output:geometry:measure:off.face_count", "==", {"path": "metrics.facet_count"}],
        ["output:geometry:measure:off.vertex_count", "==", {"path": "metrics.vertex_count"}],
        ["metrics.boundary_edge_count", "==", 0],
        ["metrics.euler_characteristic", "==", euler],
    ]


def _wrap_case(case_id: str, fixture: dict, parameters: dict, euler: int, points: int, extra: list[list]) -> dict:
    return _case(case_id, "reconstruction.alpha_wrap", [_points(fixture)], parameters, [
        ["metrics.algorithm", "==", "CGAL::alpha_wrap_3"],
        ["metrics.alpha", "==", parameters["alpha"]["value"]],
        ["metrics.offset", "==", 0.5],
        ["metrics.point_count", "==", points],
        ["input:points:measure:points.count", "==", points],
    ] + _closed_mesh_checks(euler) + extra)


FAMILY_7_10 = {
    "family": "7.10",
    "scope": "family_7_10_surface_reconstruction_partial",
    "evidence_path": "docs/master/evidence/family-7.10-capabilities.json",
    "test_id": "family-7.10-replay-cases",
    "requirements": {
        "major.7.10.03": {
            "operation_ids": ["reconstruction.alpha_wrap"],
            "symbols": ["alpha_wrap_3"],
            "symbol_notes": "alpha_wrap_3 wraps unoriented point sets (the same sphere and torus samples, "
                            "320 and 640 points) with typed alpha and offset. The independent validator checks a "
                            "closed outward oriented 2-manifold, every input point strictly enclosed (exact "
                            "axis-ray parity), every wrap vertex in the offset band of the input (exact "
                            "distances), and a certified surface-to-source bound of alpha plus offset. Replay "
                            "asserts hand-derived Euler characteristics: the sphere wrap is 2; with alpha 2.5 "
                            "the torus wrap keeps its hole (0) while alpha 15 exceeds the 6 mm hole and fills "
                            "it (2); wrap vertices lie within offset of the radius-10 sphere and the torus. "
                            "Only the point-set oracle is replayed; mesh and soup oracles, the 2D wrap, "
                            "alpha_wrap_3 with a Surface_mesh input and the pause-and-resume API are not exposed.",
            "case_ids": ["reconstruction-wrap-sphere", "reconstruction-wrap-torus-fine",
                         "reconstruction-wrap-torus-coarse"],
        },
    },
    "unbound": {
        "major.7.10.01": "reconstruction.poisson is implemented and independently validated (Poisson_reconstruction_function, "
                         "Poisson_mesh_domain_3, surface-only make_mesh_3, compute_average_spacing; sphere and torus "
                         "cases in tests/master_reconstruction_cases.py), but the ledger also lists the one-call "
                         "wrapper poisson_surface_reconstruction_delaunay, which is not exercised: in CGAL 6.2.1 "
                         "(poisson_surface_reconstruction.h) it appends manifold_with_boundary() after the caller's "
                         "tag and measurably leaves 24 to 214 boundary edges on the closed sphere and torus "
                         "fixtures, so its output cannot satisfy the closed-surface validator. The requirement stays "
                         "unbound until that symbol is exercised.",
        "major.7.10.02": "Advancing_front_surface_reconstruction (advancing_front_surface_reconstruction) and "
                         "Scale_space_reconstruction_3 (Jet_smoother plus Advancing_front_mesher) are implemented "
                         "with independent validators and covered by tests/master_reconstruction_cases.py, but the "
                         "ledger family also names Polygonal_surface_reconstruction, which needs a mixed-integer "
                         "program solver (SCIP or GLPK; neither is part of this build), and "
                         "Kinetic_surface_reconstruction, which has no operation. The requirement stays unbound "
                         "until every named family is replayed.",
    },
    "cases": [
        _wrap_case("reconstruction-wrap-sphere", R_SPHERE_XYZ, R_WRAP_SPHERE, 2, 320, [
            ["output:geometry:measure:off.min_vertex_radius", ">", 9.49],
            ["output:geometry:measure:off.max_vertex_radius", "<", 10.51],
            ["output:geometry:measure:off.signed_volume", ">", 4000.0],
            ["output:geometry:measure:off.signed_volume", "<", 4.0 / 3.0 * math.pi * 10.5 ** 3],
        ]),
        _wrap_case("reconstruction-wrap-torus-fine", R_TORUS_XYZ, R_WRAP_TORUS_FINE, 0, 640, [
            ["output:geometry:measure:off.max_torus_residual(10,4)", "<=", 0.500001],
            ["output:geometry:measure:off.signed_volume", ">", R_TORUS_VOLUME * 0.9],
        ]),
        _wrap_case("reconstruction-wrap-torus-coarse", R_TORUS_XYZ, R_WRAP_TORUS_COARSE, 2, 640, [
            ["output:geometry:measure:off.max_torus_residual(10,4)", "<=", 0.500001],
            ["output:geometry:measure:off.signed_volume", ">", R_TORUS_VOLUME],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["reconstruction-wrap-torus-fine", "reconstruction-wrap-torus-coarse"]},
    ],
    "negative_controls": [
        {"id": "reconstruction-wrap-too-fine-rejected", "operation": "reconstruction.alpha_wrap",
         "inputs": [_points(R_TORUS_XYZ)], "parameters": {"alpha": _mm(0.1), "offset": _mm(0.5)},
         "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
        {"id": "reconstruction-wrap-shrunk-not-enclosing-rejected", "operation": "reconstruction.validate.alpha_wrap",
         "inputs": [_mesh(R_TAMPERED["wrap_shrunk"]), _points(R_SPHERE_XYZ)], "parameters": R_WRAP_SPHERE,
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_NOT_ENCLOSED"},
        {"id": "reconstruction-wrap-grown-surface-rejected", "operation": "reconstruction.validate.alpha_wrap",
         "inputs": [_mesh(R_TAMPERED["wrap_grown"]), _points(R_SPHERE_XYZ)], "parameters": R_WRAP_SPHERE,
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SURFACE_TO_SOURCE_BOUND_EXCEEDED"},
        {"id": "reconstruction-wrap-vertex-inside-band-rejected", "operation": "reconstruction.validate.alpha_wrap",
         "inputs": [_mesh(R_TAMPERED["wrap_vertex_inside"]), _points(R_SPHERE_XYZ)], "parameters": R_WRAP_SPHERE,
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "VERTEX_INSIDE_OFFSET_BAND"},
    ],
}

FAMILY_7_8 = {
    "family": "7.8",
    "scope": "family_7_8_mesh_analysis_decomposition_partial",
    "evidence_path": "docs/master/evidence/family-7.8-capabilities.json",
    "test_id": "family-7.8-replay-cases",
    "requirements": {
        "major.7.8.06": {
            "operation_ids": ["mesh.subdivide.catmull_clark", "mesh.subdivide.loop"],
            "symbols": ["CatmullClark_subdivision", "Loop_subdivision"],
            "symbol_notes": "Loop subdivision of the 4-face tetrahedron gives 16 faces and 10 vertices after one "
                            "step and 64 faces and 34 vertices after two (V+E per step, 4F), and of the two-triangle "
                            "open square 32 faces, 25 vertices and a doubled boundary (16 boundary edges) after "
                            "two steps. Catmull-Clark of the quad cube gives 24 quads and V+E+F = 26 vertices after "
                            "one step (96 quads and 98 vertices after two) and of the tetrahedron 12 quads and 14 "
                            "vertices. The independent validators re-implement the Loop (interior beta mask, "
                            "boundary 3/4+1/8+1/8, edge 3/8+3/8+1/8+1/8) and Catmull-Clark (face/edge/vertex "
                            "points, boundary rules) masks from the raw OFF data and match every output face, "
                            "including orientation, within a stated tolerance of 1e-9 times the bounding diagonal. "
                            "Only the plain subdivision entry points with the number-of-iterations parameter are "
                            "exposed; Doo-Sabin, Sqrt3 and custom masks are not.",
            "case_ids": ["subdivide-loop-tetra-1", "subdivide-loop-tetra-2", "subdivide-loop-open-square",
                         "subdivide-catmull-quad-cube-1", "subdivide-catmull-quad-cube-2",
                         "subdivide-catmull-tetra"],
        },
    },
    "unbound": {
        "major.7.8.01": "No SDF segmentation operation (Surface_mesh_segmentation).",
        "major.7.8.02": "No approximate convex decomposition operation.",
        "major.7.8.03": "No skeletonization operation (Surface_mesh_skeletonization / mean curvature flow).",
        "major.7.8.05": "No parameterization operation (Surface_mesh_parameterization).",
    },
    "cases": [
        _subdivision_case("subdivide-loop-tetra-1", "mesh.subdivide.loop", Q_TETRA, 1, 10, 16, [
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.euler_characteristic", "==", 2],
            ["output:geometry:measure:off.signed_volume", ">", 0.0],
            ["output:geometry:measure:off.signed_volume", "<", 4.0 / 3.0],
        ]),
        _subdivision_case("subdivide-loop-tetra-2", "mesh.subdivide.loop", Q_TETRA, 2, 34, 64, [
            ["output:geometry:measure:off.boundary_edge_count", "==", 0],
            ["output:geometry:measure:off.euler_characteristic", "==", 2],
            ["output:geometry:measure:off.signed_volume", ">", 0.0],
            ["output:geometry:measure:off.signed_volume", "<", 4.0 / 3.0],
        ]),
        _subdivision_case("subdivide-loop-open-square", "mesh.subdivide.loop", Q_OPEN_SQUARE, 2, 25, 32, [
            ["output:geometry:measure:off.boundary_edge_count", "==", 16],
        ]),
        _subdivision_case("subdivide-catmull-quad-cube-1", "mesh.subdivide.catmull_clark", Q_QUAD_BOX, 1, 26, 24, [
            ["output:geometry:measure:off.max_face_degree", "==", 4],
            ["output:geometry:measure:off.euler_characteristic", "==", 2],
        ]),
        _subdivision_case("subdivide-catmull-quad-cube-2", "mesh.subdivide.catmull_clark", Q_QUAD_BOX, 2, 98, 96, [
            ["output:geometry:measure:off.max_face_degree", "==", 4],
            ["output:geometry:measure:off.euler_characteristic", "==", 2],
        ]),
        _subdivision_case("subdivide-catmull-tetra", "mesh.subdivide.catmull_clark", Q_TETRA, 1, 14, 12, [
            ["output:geometry:measure:off.max_face_degree", "==", 4],
            ["output:geometry:measure:off.euler_characteristic", "==", 2],
        ]),
    ],
    "pairs": [
        {"kind": "different_outputs", "cases": ["subdivide-loop-tetra-1", "subdivide-loop-tetra-2"]},
        {"kind": "different_outputs", "cases": ["subdivide-catmull-quad-cube-1", "subdivide-catmull-quad-cube-2"]},
    ],
    "negative_controls": [
        {"id": "subdivide-loop-quad-input-rejected", "operation": "mesh.subdivide.loop",
         "inputs": [Q_QUAD_BOX], "parameters": {"steps": 1}, "expect_error_class": "TYPE_ERROR"},
        {"id": "subdivide-steps-over-limit-rejected", "operation": "mesh.subdivide.loop",
         "inputs": [Q_TETRA], "parameters": {"steps": 9},
         "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
        {"id": "subdivide-loop-moved-vertex-rejected", "operation": "mesh.validate.loop",
         "inputs": [_qmesh("tampered_loop.off"), Q_TETRA], "parameters": {"steps": 2},
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACE_NOT_MATCHED"},
        {"id": "subdivide-catmull-moved-vertex-rejected", "operation": "mesh.validate.catmull_clark",
         "inputs": [_qmesh("tampered_catmull.off", "PolygonSoup3"), Q_QUAD_BOX], "parameters": {"steps": 1},
         "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "FACE_NOT_MATCHED"},
    ],
}


# --- Batch 4 additions --------------------------------------------------------------------
# 7.13.03 reuses the validated reconstruction.alpha_wrap operation (one operation per CGAL
# function): its replay cases are declared in the 7.13 family so the requirement carries its own
# evidence instead of borrowing the 7.10.03 cases.
FAMILY_7_13["requirements"]["major.7.13.03"] = {
    "operation_ids": ["reconstruction.alpha_wrap"],
    "symbols": ["alpha_wrap_3"],
    "symbol_notes": "CGAL::alpha_wrap_3 wraps the unoriented 320-point sphere sample (radius 10 mm) and the "
                    "640-point torus sample (R=10, r=4) with typed alpha and offset. The independent "
                    "validator checks a closed outward-oriented 2-manifold, exact strict enclosure of every "
                    "input point (exact axis-ray parity), wrap vertices inside the offset band of the input "
                    "(exact distances) and a certified surface-to-source bound of alpha plus offset. Replay "
                    "asserts hand-derived topology: the sphere wrap has Euler characteristic 2, the torus "
                    "wrap with alpha 2.5 keeps its hole (0) and with alpha 15 (above the 6 mm hole) fills "
                    "it (2). Only the point-set oracle is exposed; mesh and soup oracles are not.",
    "case_ids": ["alphawrap-sphere", "alphawrap-torus-open", "alphawrap-torus-filled"],
}
FAMILY_7_13["cases"].extend([
    _wrap_case("alphawrap-sphere", R_SPHERE_XYZ, R_WRAP_SPHERE, 2, 320, [
        ["output:geometry:measure:off.min_vertex_radius", ">", 9.49],
        ["output:geometry:measure:off.max_vertex_radius", "<", 10.51],
        ["output:geometry:measure:off.signed_volume", ">", 4000.0],
        ["output:geometry:measure:off.signed_volume", "<", 4.0 / 3.0 * math.pi * 10.5 ** 3],
    ]),
    _wrap_case("alphawrap-torus-open", R_TORUS_XYZ, R_WRAP_TORUS_FINE, 0, 640, [
        ["output:geometry:measure:off.max_torus_residual(10,4)", "<=", 0.500001],
    ]),
    _wrap_case("alphawrap-torus-filled", R_TORUS_XYZ, R_WRAP_TORUS_COARSE, 2, 640, [
        ["output:geometry:measure:off.max_torus_residual(10,4)", "<=", 0.500001],
    ]),
])
FAMILY_7_13["pairs"].append({"kind": "different_outputs", "cases": ["alphawrap-torus-open", "alphawrap-torus-filled"]})
FAMILY_7_13["negative_controls"].extend([
    {"id": "alphawrap-too-fine-rejected", "operation": "reconstruction.alpha_wrap",
     "inputs": [_points(R_TORUS_XYZ)], "parameters": {"alpha": _mm(0.1), "offset": _mm(0.5)},
     "expect_error_class": "RESOURCE_LIMIT", "expect_error_code": "MESH_SIZE_LIMIT_EXCEEDED"},
    {"id": "alphawrap-tampered-shrunk-rejected", "operation": "reconstruction.validate.alpha_wrap",
     "inputs": [_mesh(R_TAMPERED["wrap_shrunk"]), _points(R_SPHERE_XYZ)], "parameters": R_WRAP_SPHERE,
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_NOT_ENCLOSED"},
])

B4_FIXTURES = {
    "dome_hole12.off": "340016d7e2a9e98a9ccbffd27cef66b94613ae74af9bbcbc99e0bbb0200d3cee",
    "tampered_fair_vertex_moved.off": "a27098c20061cb8402ea25b404489769b183914cfc3ecffd5e16712316e90950",
    "cube_geodesic.off": "8582ba758a2a781e75be1c3c1a36a84704ef1c712e01dbe87117e7c1d37d40bb",
    "lshape.off": "9f4f86dc1d7c71dbe94c6354ce73cce3ef3b7edc9d35bd962d881483f8aad9ab",
    "tampered_sp_distance_short.json": "a0c2fed2a7534ceb34a9d5d6d7fead69170746396916a3b23ba28cbe1609febb",
    "tampered_sp_path_off_surface.json": "2c44ca38184bcc7dd1741ce5a35c5d4901cc775553377347456ece633ec3ee5f",
    "tampered_sp_wrong_source.json": "9ca1a1dd7c725f9c2c50aad0113a351303848cdceb8272a720094689457a7faf",
}


def _b4fx(name: str) -> dict:
    return {"fixture": f"batch4/{name}", "sha256": B4_FIXTURES[name]}


def _b4mesh(name: str, type_: str = "TriangleSurfaceMesh") -> dict:
    return {**_b4fx(name), "type": type_, "format": "off", "unit": "mm"}


def _b4json(name: str, type_: str) -> dict:
    return {**_b4fx(name), "type": type_, "format": "json", "unit": "mm"}


def _b4report(name: str) -> dict:
    return {**_b4fx(name), "type": "GeometryQueryReport", "format": "json", "unit": "none"}


# 7.4.04: a UV unit sphere (12 meridians, rings every 30 degrees, south pole fan) without its
# 30-degree north cap leaves one 12-edge hole on a radius-0.5 ring. The flat 12-gon cap closes the
# inscribed polyhedron of volume V_FLAT (summed over exact tetrahedra by an independent script).
B4_DOME = _b4mesh("dome_hole12.off")
B4_V_FLAT = 3.698557158511964
B4_FAIR_C1 = {"max_hole_edges": 20, "density_control_factor": 1.41, "fairing_continuity": 1}
B4_FAIR_C2 = {"max_hole_edges": 20, "density_control_factor": 2.5, "fairing_continuity": 2}
B4_FAIR_PLAIN = {"max_hole_edges": 20, "density_control_factor": 1.0, "fairing_continuity": 0}
B4_CLOSED_SPHERE = [
    ["output:geometry:measure:off.boundary_edge_count", "==", 0],
    ["output:geometry:measure:off.euler_characteristic", "==", 2],
    ["metrics.candidate.mesh.closed", "==", True],
    ["metrics.candidate.mesh.outward_oriented", "==", True],
]
FAMILY_7_4["requirements"]["major.7.4.04"] = {
    "operation_ids": ["mesh.repair.fill_holes", "mesh.repair.fill_holes_refine_fair"],
    "symbols": ["triangulate_hole", "triangulate_refine_and_fair_hole"],
    "symbol_notes": "PMP::triangulate_hole closes the 3-edge hole of the open tetrahedron (1 face, volume 1/6) "
                    "and the 12-edge hole of the UV-dome (10 = n-2 faces, no new vertex, closed sphere of "
                    "Euler characteristic 2, volume equal to the inscribed polyhedron with a flat cap). "
                    "PMP::triangulate_refine_and_fair_hole closes the same dome with density_control_factor "
                    "1.41 / C1 fairing (1 new vertex), 2.5 / C2 (7 new vertices) and 1.0 / C0 (no new "
                    "vertex): the faired patches bulge outward to the dome (volume above the flat cap "
                    "polyhedron, every vertex within the unit sphere up to 0.5 percent), the closed result "
                    "stays outward oriented and every source face is preserved. The validator replays the "
                    "official CGAL call, so the floating-point fairing solve itself is not re-derived "
                    "independently; the independent checks are topology, source-face preservation, exact "
                    "non-degeneracy of every new face and a bounding-box sanity bound. Holes above "
                    "max_hole_edges are skipped and an all-skipped request is rejected.",
    "case_ids": ["fill-plain-open-tetra", "fill-plain-dome", "fair-dome-c1", "fair-dome-c2", "fair-dome-plain"],
}
FAMILY_7_4["cases"].extend([
    _case("fill-plain-open-tetra", "mesh.repair.fill_holes", [_mesh(OPEN_TETRA)], {"max_hole_edges": 8}, [
        ["metrics.filled_hole_count", "==", 1], ["metrics.added_face_count", "==", 1],
        ["output:geometry:measure:off.face_count", "==", 4],
        ["output:geometry:measure:off.boundary_edge_count", "==", 0],
        ["output:geometry:measure:off.signed_volume", "approx", [1.0 / 6.0, 1e-12]],
    ]),
    _case("fill-plain-dome", "mesh.repair.fill_holes", [B4_DOME], {"max_hole_edges": 20}, [
        ["metrics.filled_hole_count", "==", 1], ["metrics.added_face_count", "==", 10],
        ["output:geometry:measure:off.vertex_count", "==", 61],
        ["output:geometry:measure:off.face_count", "==", 118],
        ["output:geometry:measure:off.signed_volume", "approx", [B4_V_FLAT, 1e-9]],
        *B4_CLOSED_SPHERE,
    ]),
    _case("fair-dome-c1", "mesh.repair.fill_holes_refine_fair", [B4_DOME], B4_FAIR_C1, [
        ["metrics.operation", "==", "mesh.repair.fill_holes_refine_fair"],
        ["metrics.added_vertex_count", "==", 1], ["metrics.fairing_continuity", "==", 1],
        ["output:geometry:measure:off.vertex_count", "==", 62],
        ["output:geometry:measure:off.signed_volume", ">", B4_V_FLAT + 0.02],
        ["output:geometry:measure:off.max_vertex_radius", "<=", 1.000001],
        *B4_CLOSED_SPHERE,
    ]),
    _case("fair-dome-c2", "mesh.repair.fill_holes_refine_fair", [B4_DOME], B4_FAIR_C2, [
        ["metrics.added_vertex_count", "==", 7], ["metrics.fairing_continuity", "==", 2],
        ["output:geometry:measure:off.vertex_count", "==", 68],
        ["output:geometry:measure:off.face_count", "==", 132],
        ["output:geometry:measure:off.signed_volume", ">", B4_V_FLAT + 0.04],
        ["output:geometry:measure:off.max_vertex_radius", "<", 1.005],
        *B4_CLOSED_SPHERE,
    ]),
    _case("fair-dome-plain", "mesh.repair.fill_holes_refine_fair", [B4_DOME], B4_FAIR_PLAIN, [
        ["metrics.added_vertex_count", "==", 0], ["metrics.added_face_count", "==", 10],
        ["output:geometry:measure:off.signed_volume", "approx", [B4_V_FLAT, 1e-9]],
        *B4_CLOSED_SPHERE,
    ]),
])
FAMILY_7_4["pairs"].append({"kind": "different_outputs", "cases": ["fair-dome-c1", "fair-dome-c2"]})
FAMILY_7_4["negative_controls"].extend([
    {"id": "fill-plain-hole-too-large-rejected", "operation": "mesh.repair.fill_holes", "inputs": [B4_DOME],
     "parameters": {"max_hole_edges": 8}, "expect_error_class": "PRECONDITION_FAILED",
     "expect_error_code": "NO_ELIGIBLE_HOLES"},
    {"id": "fair-hole-too-large-rejected", "operation": "mesh.repair.fill_holes_refine_fair", "inputs": [B4_DOME],
     "parameters": {**B4_FAIR_C1, "max_hole_edges": 8}, "expect_error_class": "PRECONDITION_FAILED",
     "expect_error_code": "NO_ELIGIBLE_HOLES"},
    {"id": "fair-density-below-one-rejected", "operation": "mesh.repair.fill_holes_refine_fair",
     "inputs": [B4_DOME], "parameters": {**B4_FAIR_C1, "density_control_factor": 0.5},
     "expect_error_class": "INVALID_INPUT", "expect_error_code": "INVALID_DENSITY_CONTROL_FACTOR"},
    {"id": "fair-continuity-three-rejected", "operation": "mesh.repair.fill_holes_refine_fair",
     "inputs": [B4_DOME], "parameters": {**B4_FAIR_C1, "fairing_continuity": 3},
     "expect_error_class": "INVALID_INPUT", "expect_error_code": "INVALID_FAIRING_CONTINUITY"},
    {"id": "fair-tampered-vertex-moved-rejected", "operation": "mesh.validate.repair_fill_holes_refine_fair",
     "inputs": [_b4mesh("tampered_fair_vertex_moved.off"), B4_DOME], "parameters": B4_FAIR_C1,
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "REPAIR_VALIDATION_FAILED"},
    {"id": "fair-unfilled-candidate-rejected", "operation": "mesh.validate.repair_fill_holes_refine_fair",
     "inputs": [B4_DOME, B4_DOME], "parameters": B4_FAIR_C1,
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "REPAIR_VALIDATION_FAILED"},
])

# 7.8.04 Surface_mesh_shortest_path on a side-2 cube (12 triangles) and a flat L-shaped region.
B4_CUBE = _b4mesh("cube_geodesic.off")
B4_LSHAPE = _b4mesh("lshape.off")
B4_SP_CORNERS = {"sources": [{"vertex": 0}], "targets": [{"vertex": 6}, {"vertex": 2}, {"vertex": 1}]}
B4_SP_L = {"sources": [{"vertex": 6}], "targets": [{"vertex": 3}, {"vertex": 2}]}
B4_SP_POINTS = {"sources": [{"face": 0, "barycentric": [0.5, 0.25, 0.25]}, {"vertex": 6}],
                "targets": [{"face": 2, "barycentric": [0.25, 0.5, 0.25]}, {"vertex": 4}]}
B4_SP_CORNER_TARGETS = {"sources": [{"vertex": 0}], "targets": [{"vertex": 6}, {"vertex": 2}]}
FAMILY_7_8["requirements"]["major.7.8.04"] = {
    "operation_ids": ["mesh.path.shortest"],
    "symbols": ["Surface_mesh_shortest_path"],
    "symbol_notes": "Surface_mesh_shortest_path computes exact geodesic distances on triangle meshes of at most "
                    "64 faces from up to 8 source points (vertex or face barycentric) to up to 32 targets, with "
                    "the unfolded path. Hand-derived on the side-2 cube: the opposite corner is 2*sqrt(5) away "
                    "(unfold two faces), a face diagonal 2*sqrt(2) and an edge 2. On the flat L-shaped region "
                    "the corner (0,2) to the corner (2,1) must bend at the reflex vertex (1,1), length "
                    "sqrt(2)+1, and (0,2) to (2,0) is the straight 2*sqrt(2). With two sources each target "
                    "reports its nearest source (face point to top-face point 1.58 from the corner source, "
                    "vertex 4 at 2.69 from the face point). The independent validator unfolds face sequences "
                    "with visibility windows and runs Dijkstra over mesh vertices in long double (tolerance "
                    "1e-9 relative to the diagonal, declared because square roots are involved); it checks "
                    "path points, shared faces, endpoints, path length, the optimum and the nearest source. "
                    "Face barycentric coordinates are given in OFF corner order and permuted internally to "
                    "the CGAL halfedge order.",
    "case_ids": ["shortest-cube-corners", "shortest-lshape-reflex", "shortest-cube-two-sources"],
}
FAMILY_7_8["cases"].extend([
    _case("shortest-cube-corners", "mesh.path.shortest", [B4_CUBE], B4_SP_CORNERS, [
        ["metrics.algorithm", "==", "CGAL::Surface_mesh_shortest_path"],
        ["output:analysis:json:report_kind", "==", "shortest_paths"],
        ["output:analysis:json:results.targets.0.distance", "approx", [4.47213595499958, 1e-9]],
        ["output:analysis:json:results.targets.1.distance", "approx", [2.8284271247461903, 1e-9]],
        ["output:analysis:json:results.targets.2.distance", "approx", [2.0, 1e-9]],
    ]),
    _case("shortest-lshape-reflex", "mesh.path.shortest", [B4_LSHAPE], B4_SP_L, [
        ["output:analysis:json:results.targets.0.distance", "approx", [2.414213562373095, 1e-9]],
        ["output:analysis:json:results.targets.1.distance", "approx", [2.8284271247461903, 1e-9]],
    ]),
    _case("shortest-cube-two-sources", "mesh.path.shortest", [B4_CUBE], B4_SP_POINTS, [
        ["output:analysis:json:results.targets.0.distance", "approx", [1.5811388300841898, 1e-9]],
        ["output:analysis:json:results.targets.0.source_index", "==", 1],
        ["output:analysis:json:results.targets.1.distance", "approx", [2.6925824035672523, 1e-9]],
        ["output:analysis:json:results.targets.1.source_index", "==", 0],
    ]),
])
FAMILY_7_8["negative_controls"].extend([
    {"id": "shortest-tampered-distance-rejected", "operation": "mesh.validate.shortest_path",
     "inputs": [_b4report("tampered_sp_distance_short.json"), B4_CUBE], "parameters": B4_SP_CORNER_TARGETS,
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "DISTANCE_MISMATCH"},
    {"id": "shortest-tampered-path-off-surface-rejected", "operation": "mesh.validate.shortest_path",
     "inputs": [_b4report("tampered_sp_path_off_surface.json"), B4_CUBE], "parameters": B4_SP_CORNER_TARGETS,
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "PATH_LEAVES_SURFACE"},
    {"id": "shortest-tampered-wrong-source-rejected", "operation": "mesh.validate.shortest_path",
     "inputs": [_b4report("tampered_sp_wrong_source.json"), B4_CUBE], "parameters": B4_SP_POINTS,
     "expect_error_class": "VALIDATION_FAILED", "expect_error_code": "SOURCE_NOT_NEAREST"},
    {"id": "shortest-source-out-of-range-rejected", "operation": "mesh.path.shortest", "inputs": [B4_CUBE],
     "parameters": {"sources": [{"vertex": 99}], "targets": [{"vertex": 6}]},
     "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
    {"id": "shortest-barycentric-sum-rejected", "operation": "mesh.path.shortest", "inputs": [B4_CUBE],
     "parameters": {"sources": [{"vertex": 0}], "targets": [{"face": 0, "barycentric": [0.5, 0.5, 0.5]}]},
     "expect_error_class": "INVALID_REQUEST", "expect_error_code": "INVALID_PARAMETER"},
])

GENERIC_FAMILIES: dict[str, dict] = {
    family["family"]: family for family in (FAMILY_7_1, FAMILY_7_2, FAMILY_7_3, FAMILY_7_4, FAMILY_7_5, FAMILY_7_6,
                   FAMILY_7_9, FAMILY_7_11, FAMILY_7_12, FAMILY_7_13, FAMILY_7_14, FAMILY_7_15, FAMILY_7_10, FAMILY_7_8)
}


def canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def contract_digest(family: dict) -> str:
    return canonical_hash(family)


def requirement_coverage(family: dict) -> dict[str, dict]:
    return {
        requirement_id: {
            "case_ids": sorted(binding["case_ids"]),
            "operation_ids": list(binding["operation_ids"]),
            "symbols": list(binding["symbols"]),
        }
        for requirement_id, binding in family["requirements"].items()
    }


def validate_contract(family: dict) -> None:
    """Static self-consistency of one family contract (no execution)."""
    case_ids = [case["id"] for case in family["cases"]]
    negative_ids = [case["id"] for case in family["negative_controls"]]
    if len(set(case_ids + negative_ids)) != len(case_ids) + len(negative_ids):
        raise ValueError(f"Family {family['family']} has duplicate case ids")
    covered: set[str] = set()
    prefix = f"major.{family['family']}."
    for requirement_id, binding in family["requirements"].items():
        if not requirement_id.startswith(prefix) or requirement_id in family["unbound"]:
            raise ValueError(f"Invalid family requirement binding: {requirement_id}")
        if not binding["case_ids"] or not binding["operation_ids"] or not binding["symbols"]:
            raise ValueError(f"Empty family requirement binding: {requirement_id}")
        for case_id in binding["case_ids"]:
            if case_id not in case_ids:
                raise ValueError(f"Requirement names an unknown case: {requirement_id}/{case_id}")
            operation = next(case["operation"] for case in family["cases"] if case["id"] == case_id)
            if operation not in binding["operation_ids"]:
                raise ValueError(f"Case operation is outside the bound operations: {case_id}")
        operations_used = {case["operation"] for case in family["cases"]
                           if case["id"] in binding["case_ids"]}
        if operations_used != set(binding["operation_ids"]):
            raise ValueError(f"Bound operation lacks a replay case: {requirement_id}")
        covered.update(binding["case_ids"])
    for pair in family["pairs"]:
        if (pair["kind"] not in {"equal_outputs", "different_outputs"} or len(pair["cases"]) != 2 or
                not set(pair["cases"]) <= set(case_ids)):
            raise ValueError(f"Invalid pair check in family {family['family']}")
    if covered != set(case_ids):
        raise ValueError(f"Family {family['family']} has a case outside every bound requirement")
    for case in family["cases"] + family["negative_controls"]:
        for item in case["inputs"]:
            if not item["fixture"] or ".." in item["fixture"].split("/"):
                raise ValueError(f"Invalid fixture path: {item['fixture']}")
        for assertion in case.get("assertions", []):
            if len(assertion) != 3 or assertion[1] not in _OPERATORS:
                raise ValueError(f"Invalid assertion in case {case['id']}")


# --- Validator derivation and report checks (registry-driven) -------------

def registry_index(operations: list[dict]) -> dict[str, dict]:
    return {item.get("id"): item for item in operations if isinstance(item, dict)}


def mandatory_validators(operation: dict) -> list[str]:
    validation = operation.get("validation", {})
    validators = validation.get("validators")
    if validation.get("required") is not True or not isinstance(validators, list) or not validators:
        raise ValueError(f"Operation has no mandatory validator chain: {operation.get('id')}")
    return list(validators)


def derive_validator_plan(operation: dict, validator: dict, transform_parameters: dict) -> tuple[
        list[tuple[str, str]], dict]:
    """Return ([(kind, slot)...] in validator input order, parameters) from bindings."""
    binding = operation["validation"].get("bindings", {}).get(validator["id"])
    # Legacy bindings (hull.convex_3) list the slot references directly, without an "artifacts" wrapper.
    artifacts = binding.get("artifacts") if isinstance(binding, dict) and "artifacts" in binding else binding
    if not isinstance(binding, dict) or not isinstance(artifacts, dict):
        raise ValueError(f"Registry lacks a validator binding: {operation['id']}/{validator['id']}")
    plan = []
    for slot in validator["io"]["inputs"]:
        reference = artifacts.get(slot["slot"])
        if not isinstance(reference, dict) or len(reference) != 1:
            raise ValueError(f"Validator slot is not bound: {validator['id']}/{slot['slot']}")
        (kind, source_slot), = reference.items()
        if kind not in {"input", "output"}:
            raise ValueError(f"Validator slot binding kind is unknown: {kind}")
        plan.append((kind, source_slot))
    if set(artifacts) != {slot["slot"] for slot in validator["io"]["inputs"]}:
        raise ValueError(f"Validator binding names unknown slots: {validator['id']}")
    parameters = {}
    for name, reference in binding.get("parameters", {}).items():
        source = reference.get("parameter") if isinstance(reference, dict) else None
        if source in transform_parameters:
            parameters[name] = copy.deepcopy(transform_parameters[source])
        elif not reference.get("optional"):
            raise ValueError(f"Required validator parameter is unbound: {validator['id']}/{name}")
    return plan, parameters


def _report_value(report: object, dotted: str) -> tuple[bool, object]:
    value = report
    parts = dotted.split(".")
    for position, part in enumerate(parts):
        if part.endswith("[*]"):
            # Closed projection: map the remaining path over every element of a list.
            head = part[:-3]
            if not (isinstance(value, dict) and head in value and isinstance(value[head], list)):
                return False, None
            projected = []
            for element in value[head]:
                found, item = _report_value(element, ".".join(parts[position + 1:]))                     if position + 1 < len(parts) else (True, element)
                if not found:
                    return False, None
                projected.append(item)
            return True, projected
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return False, None
    return True, value


def validator_report_failures(validator: dict, report: object, transform_id: str) -> list[str]:
    if not isinstance(report, dict):
        return ["report is not an object"]
    failures = []
    validation = validator.get("validation", {})
    if report.get("status") != "pass":
        failures.append("status")
    if "passed" in report and report.get("passed") is not True:
        failures.append("passed")
    if "validates" in report and report.get("validates") != transform_id:
        failures.append("validates")
    # A feature-scoped report (criteria_scope.scoped) must carry the scoped keys instead of the full
    # ones; the full key must then be absent so a scoped pass cannot read as a full pass.
    scoped = isinstance(report.get("criteria_scope"), dict) and report["criteria_scope"].get("scoped") is True
    scoped_keys = validation.get("scoped_report_checks", {})
    for key, expected in validation.get("required_report_checks", {}).items():
        if scoped and key in scoped_keys:
            if _report_value(report, key)[0] or _report_value(report, scoped_keys[key]) != (True, expected):
                failures.append(key)
            continue
        if _report_value(report, key) != (True, expected):
            failures.append(key)
    for key in validation.get("required_report_fields", []):
        if not _report_value(report, key)[0]:
            failures.append(key)
    for key, minimum in validation.get("required_report_minimum", {}).items():
        _, value = _report_value(report, key)
        if (not isinstance(value, (int, float)) or isinstance(value, bool) or
                not math.isfinite(float(value)) or value < minimum):
            failures.append(key)
    return failures


# --- Closed assertion vocabulary ------------------------------------------

def _decode_text(content: bytes) -> str:
    return content.decode("ascii")


def _parse_off(content: bytes) -> tuple[list[tuple[float, ...]], list[list[int]]]:
    tokens = _decode_text(content).split()
    if not tokens or tokens[0] != "OFF":
        raise ValueError("not OFF")
    vertex_count, face_count = int(tokens[1]), int(tokens[2])
    cursor = 4
    vertices = []
    for _ in range(vertex_count):
        vertices.append(tuple(float(tokens[cursor + axis]) for axis in range(3)))
        cursor += 3
    faces = []
    for _ in range(face_count):
        size = int(tokens[cursor])
        faces.append([int(tokens[cursor + 1 + offset]) for offset in range(size)])
        cursor += size + 1
    return vertices, faces


def _off_measure(name: str, content: bytes) -> object:
    vertices, faces = _parse_off(content)
    if name == "vertex_count":
        return len(vertices)
    if name == "face_count":
        return len(faces)
    if name == "max_face_degree":
        return max(len(face) for face in faces)
    edges: dict[tuple[int, int], int] = {}
    for face in faces:
        for offset, first in enumerate(face):
            key = tuple(sorted((first, face[(offset + 1) % len(face)])))
            edges[key] = edges.get(key, 0) + 1
    if name == "euler_characteristic":
        return len(vertices) - len(edges) + len(faces)
    if name in {"min_vertex_radius", "max_vertex_radius"}:
        radii = [math.sqrt(sum(c * c for c in vertex)) for vertex in vertices]
        return min(radii) if name == "min_vertex_radius" else max(radii)
    if name.startswith("max_ellipsoid_residual(") or name.startswith("max_torus_residual("):
        # Largest first-order distance of any vertex from the analytic surface.
        numbers = [float(item) for item in name[name.index("(") + 1:-1].split(",")]
        worst = 0.0
        for x, y, z in vertices:
            if name.startswith("max_torus_residual("):
                worst = max(worst, abs(math.hypot(math.hypot(x, y) - numbers[0], z) - numbers[1]))
            else:
                a, b, c = numbers
                value = x * x / (a * a) + y * y / (b * b) + z * z / (c * c) - 1.0
                gradient = math.sqrt((2 * x / (a * a)) ** 2 + (2 * y / (b * b)) ** 2 + (2 * z / (c * c)) ** 2)
                worst = max(worst, abs(value) / gradient)
        return worst
    if name in {"min_angle_degrees", "max_circumradius"}:
        smallest, widest = 180.0, 0.0
        for face in faces:
            a, b, c = (vertices[index] for index in face[:3])
            sides = [math.dist(a, b), math.dist(b, c), math.dist(c, a)]
            u = [b[k] - a[k] for k in range(3)]
            w = [c[k] - a[k] for k in range(3)]
            twice = math.hypot(u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2],
                               u[0] * w[1] - u[1] * w[0])
            widest = max(widest, sides[0] * sides[1] * sides[2] / (2.0 * twice))
            for first, second, third in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
                # Law of cosines on the side opposite each corner.
                cosine = (sides[first] ** 2 + sides[third] ** 2 - sides[second] ** 2) / \
                         (2.0 * sides[first] * sides[third])
                smallest = min(smallest, math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
        return smallest if name == "min_angle_degrees" else widest
    if name == "boundary_edge_count":
        return sum(1 for count in edges.values() if count == 1)
    lengths = [math.dist(vertices[a], vertices[b]) for a, b in edges]
    if name == "min_edge_length":
        return min(lengths)
    if name == "max_edge_length":
        return max(lengths)
    if name == "mean_edge_length":
        return sum(lengths) / len(lengths)
    if name == "edge_length_ratio":
        return max(lengths) / min(lengths)
    if name == "bbox_diagonal":
        return math.dist([min(v[axis] for v in vertices) for axis in range(3)],
                         [max(v[axis] for v in vertices) for axis in range(3)])
    if name == "area":
        total = 0.0
        for face in faces:
            a = vertices[face[0]]
            for index in range(1, len(face) - 1):
                b, c = vertices[face[index]], vertices[face[index + 1]]
                u = [b[k] - a[k] for k in range(3)]
                w = [c[k] - a[k] for k in range(3)]
                total += 0.5 * math.hypot(u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2],
                                          u[0] * w[1] - u[1] * w[0])
        return total
    if name == "signed_volume":
        total = 0.0
        for face in faces:
            a = vertices[face[0]]
            for index in range(1, len(face) - 1):
                b, c = vertices[face[index]], vertices[face[index + 1]]
                total += (a[0] * (b[1] * c[2] - b[2] * c[1]) -
                          a[1] * (b[0] * c[2] - b[2] * c[0]) +
                          a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
        return total
    raise ValueError(f"unknown OFF measure {name}")


def _parse_points(content: bytes) -> tuple[list[tuple[float, ...]], list[tuple[float, ...]] | None]:
    lines = _decode_text(content).splitlines()
    if lines and lines[0].strip() == "ply":
        properties: list[str] = []
        count = None
        cursor = 1
        while lines[cursor].strip() != "end_header":
            parts = lines[cursor].split()
            if parts[:2] == ["element", "vertex"]:
                count = int(parts[2])
            elif parts[:1] == ["property"]:
                properties.append(parts[-1])
            elif parts[:2] == ["element", "face"]:
                raise ValueError("unexpected PLY face element")
            cursor += 1
        rows = [list(map(float, line.split())) for line in lines[cursor + 1:cursor + 1 + count]]
        index = {name: position for position, name in enumerate(properties)}
        points = [tuple(row[index[axis]] for axis in ("x", "y", "z")) for row in rows]
        normals = ([tuple(row[index[axis]] for axis in ("nx", "ny", "nz")) for row in rows]
                   if {"nx", "ny", "nz"} <= index.keys() else None)
        return points, normals
    rows = [list(map(float, line.split())) for line in lines if line.strip()]
    points = [tuple(row[:3]) for row in rows]
    normals = [tuple(row[3:6]) for row in rows] if rows and all(len(row) >= 6 for row in rows) else None
    return points, normals


def _points_measure(name: str, content: bytes) -> object:
    points, normals = _parse_points(content)
    if name == "count":
        return len(points)
    if normals is None:
        raise ValueError("point set has no normals")
    if name == "min_abs_normal_z":
        return min(abs(normal[2]) / math.sqrt(sum(value * value for value in normal))
                   for normal in normals)
    if name == "normal_z_sign_consistent":
        signs = {normal[2] > 0 for normal in normals if normal[2] != 0}
        return len(signs) == 1 and all(normal[2] != 0 for normal in normals)
    raise ValueError(f"unknown point measure {name}")


def _tri2_measure(name: str, content: bytes) -> object:
    """Independent facts of a Triangulation2 JSON artifact (exact rational area)."""
    from fractions import Fraction
    mesh = json.loads(content.decode("utf-8"))
    vertices = [(Fraction(x), Fraction(y)) for x, y in mesh["vertices"]]
    triangles = mesh["triangles"]
    if name == "vertex_count":
        return len(vertices)
    if name == "triangle_count":
        return len(triangles)
    edges: dict[tuple[int, int], int] = {}
    twice = Fraction(0)
    smallest = 180.0
    longest = 0.0
    for a, b, c in triangles:
        (ax, ay), (bx, by), (cx, cy) = vertices[a], vertices[b], vertices[c]
        twice += (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        corners = [(float(x), float(y)) for x, y in (vertices[a], vertices[b], vertices[c])]
        for index in range(3):
            p, q, r = corners[index], corners[(index + 1) % 3], corners[(index + 2) % 3]
            u, v = (q[0] - p[0], q[1] - p[1]), (r[0] - p[0], r[1] - p[1])
            cosine = (u[0] * v[0] + u[1] * v[1]) / (math.hypot(*u) * math.hypot(*v))
            smallest = min(smallest, math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
            longest = max(longest, math.dist(p, q))
        for first, second in ((a, b), (b, c), (c, a)):
            key = (min(first, second), max(first, second))
            edges[key] = edges.get(key, 0) + 1
    if name == "area":
        return float(twice / 2)
    if name == "min_angle_degrees":
        return smallest
    if name == "max_edge_length":
        return longest
    if name == "boundary_edge_count":
        return sum(1 for count in edges.values() if count == 1)
    if name == "max_edge_use":
        return max(edges.values())
    raise ValueError(f"unknown triangulation measure {name}")


def _point_triangle_distance(p, a, b, c) -> float:
    """Closest-point distance by barycentric region tests (Ericson), independent of the worker."""
    def sub(u, v): return [u[k] - v[k] for k in range(3)]
    def dot(u, v): return sum(x * y for x, y in zip(u, v))
    ab, ac, ap = sub(b, a), sub(c, a), sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return math.dist(p, a)
    bp = sub(p, b)
    d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return math.dist(p, b)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        return math.dist(p, [a[k] + v * ab[k] for k in range(3)])
    cp = sub(p, c)
    d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return math.dist(p, c)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        return math.dist(p, [a[k] + w * ac[k] for k in range(3)])
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return math.dist(p, [b[k] + w * (c[k] - b[k]) for k in range(3)])
    denominator = 1.0 / (va + vb + vc)
    v, w = vb * denominator, vc * denominator
    return math.dist(p, [a[k] + ab[k] * v + ac[k] * w for k in range(3)])


def _lattice(a, b, c, divisions: int):
    for i in range(divisions + 1):
        for j in range(divisions + 1 - i):
            s, t = i / divisions, j / divisions
            yield [a[k] * (1 - s - t) + b[k] * s + c[k] * t for k in range(3)]


def _tet_off_measure(name: str, source: str, vertices, boundary, boundary_vertices) -> float:
    """Distances between a TetrahedralMesh boundary and a raw OFF source fixture (pinned by the
    input artifact hash of the same file)."""
    from pathlib import Path
    lines = (Path(__file__).resolve().parents[1] / FIXTURE_ROOT / "wave_e" / source).read_text("utf-8").split("\n")
    count, face_count = (int(x) for x in lines[1].split()[:2])
    points = [[float(x) for x in line.split()] for line in lines[2:2 + count]]
    triangles = [[points[int(i)] for i in line.split()[1:4]] for line in lines[2 + count:2 + count + face_count]]
    facets = [[vertices[i] for i in face] for face in boundary]

    def to_source(point):
        return min(_point_triangle_distance(point, *t) for t in triangles)

    def to_boundary(point):
        return min(_point_triangle_distance(point, *f) for f in facets)

    if name == "max_boundary_vertex_distance_to_off":
        return max(to_source(vertices[i]) for i in boundary_vertices)
    if name == "max_boundary_sample_distance_to_off":
        return max(to_source(p) for f in facets for p in _lattice(*f, 4))
    if name == "max_off_sample_distance_to_boundary":
        return max(to_boundary(p) for t in triangles for p in _lattice(*t, 8))
    if name == "max_boundary_facet_center_distance_to_off":
        worst = 0.0
        for a, b, c in facets:
            sides = [math.dist(b, c), math.dist(c, a), math.dist(a, b)]
            weights = [s * s * (sides[(i + 1) % 3] ** 2 + sides[(i + 2) % 3] ** 2 - s * s) for i, s in enumerate(sides)]
            total = sum(weights)
            centre = [(weights[0] * a[k] + weights[1] * b[k] + weights[2] * c[k]) / total for k in range(3)]
            worst = max(worst, to_source(centre))
        return worst
    raise ValueError(f"unknown tetrahedral-versus-OFF measure {name}")


def _tet_measure(name: str, content: bytes) -> object:
    """Independent facts of a TetrahedralMesh JSON artifact (exact rational volume)."""
    from fractions import Fraction
    mesh = json.loads(content.decode("utf-8"))
    vertices = mesh["vertices"]
    cells = mesh["tetrahedra"]
    if name == "vertex_count":
        return len(vertices)
    if name == "tetrahedron_count":
        return len(cells)
    if name == "subdomain_count":
        return len(set(mesh["subdomains"]))

    def determinant(p):
        a, b, c = ([Fraction(p[i][k]) - Fraction(p[0][k]) for k in range(3)] for i in (1, 2, 3))
        return (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0])
                + a[2] * (b[0] * c[1] - b[1] * c[0]))

    face_use: dict[tuple, int] = {}
    boundary_candidates: dict[tuple, tuple] = {}
    edges = set()
    smallest_volume = None
    volume = Fraction(0)
    radius_edge = widest = 0.0
    spheres = []
    for cell in cells:
        points = [vertices[i] for i in cell]
        signed = determinant(points) / 6
        volume += signed
        smallest_volume = signed if smallest_volume is None else min(smallest_volume, signed)
        for slot in ((1, 2, 3), (0, 3, 2), (0, 1, 3), (0, 2, 1)):
            key = tuple(sorted(cell[i] for i in slot))
            face_use[key] = face_use.get(key, 0) + 1
            boundary_candidates[key] = tuple(cell[i] for i in slot)
        for i in range(4):
            for j in range(i + 1, 4):
                edges.add(tuple(sorted((cell[i], cell[j]))))
        a, b, c = ([points[i][k] - points[0][k] for k in range(3)] for i in (1, 2, 3))
        rows = [[2 * x for x in v] for v in (a, b, c)]
        rhs = [sum(x * x for x in v) for v in (a, b, c)]

        def det3(m):
            return (m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
                    - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
                    + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]))

        def column(index):
            m = [r[:] for r in rows]
            for r in range(3):
                m[r][index] = rhs[r]
            return det3(m)
        d = det3(rows)
        radius = math.hypot(column(0) / d, column(1) / d, column(2) / d)
        spheres.append(([points[0][k] + column(k) / d for k in range(3)], radius))
        widest = max(widest, radius)
        shortest = min(math.dist(points[i], points[j]) for i in range(4) for j in range(i + 1, 4))
        radius_edge = max(radius_edge, radius / shortest)
    if name.startswith(("max_circumradius_in_box(", "max_circumradius_outside_box(", "cell_count_in_box(")):
        low_high = [float(x) for x in name[name.index("(") + 1:-1].split(",")]
        low, high = low_high[:3], low_high[3:]
        inside = [r for c, r in spheres if all(low[k] <= c[k] <= high[k] for k in range(3))]
        outside = [r for c, r in spheres if not all(low[k] <= c[k] <= high[k] for k in range(3))]
        if name.startswith("cell_count_in_box("):
            return len(inside)
        chosen = inside if name.startswith("max_circumradius_in_box(") else outside
        return max(chosen) if chosen else 0.0
    if name in {"max_cube_edge_vertex_gap", "max_cube_edge_mesh_segment", "cube_edge_mesh_segment_count"}:
        tolerance = 1e-9
        gaps, segment_lengths = [], []
        for axis in range(3):
            first, second = [k for k in range(3) if k != axis]
            for a in (0.0, 1.0):
                for b in (0.0, 1.0):
                    on = [i for i, v in enumerate(vertices)
                          if abs(v[first] - a) <= tolerance and abs(v[second] - b) <= tolerance
                          and -tolerance <= v[axis] <= 1.0 + tolerance]
                    ts = sorted([0.0, 1.0] + [vertices[i][axis] for i in on])
                    gaps.append(max(y - x for x, y in zip(ts, ts[1:])))
                    members = set(on)
                    segment_lengths += [math.dist(vertices[i], vertices[j]) for i, j in edges
                                        if i in members and j in members]
        if name == "max_cube_edge_vertex_gap":
            return max(gaps)
        if name == "max_cube_edge_mesh_segment":
            return max(segment_lengths) if segment_lengths else float("inf")
        return len(segment_lengths)
    if name == "volume":
        return float(volume)
    if name == "min_tetrahedron_volume":
        return float(smallest_volume)
    if name == "max_circumradius":
        return widest
    if name == "max_radius_edge":
        return radius_edge
    if name == "max_face_use":
        return max(face_use.values())
    boundary = [boundary_candidates[key] for key, count in face_use.items() if count == 1]
    boundary_vertices = {v for face in boundary for v in face}
    if name == "euler_characteristic":
        return len(vertices) - len(edges) + len(face_use) - len(cells)
    if name == "boundary_face_count":
        return len(boundary)
    boundary_edges: dict[tuple, int] = {}
    for face in boundary:
        for i in range(3):
            key = tuple(sorted((face[i], face[(i + 1) % 3])))
            boundary_edges[key] = boundary_edges.get(key, 0) + 1
    if name == "boundary_euler_characteristic":
        if any(count != 2 for count in boundary_edges.values()):
            raise ValueError("tetrahedral boundary is not a closed surface")
        return len(boundary_vertices) - len(boundary_edges) + len(boundary)
    if name in {"min_boundary_vertex_radius", "max_boundary_vertex_radius"}:
        radii = [math.sqrt(sum(c * c for c in vertices[i])) for i in boundary_vertices]
        return min(radii) if name.startswith("min") else max(radii)
    if name == "max_interior_vertex_radius":
        return max(math.sqrt(sum(c * c for c in vertices[i])) for i in range(len(vertices))
                   if i not in boundary_vertices)
    if name.startswith("max_boundary_ellipsoid_residual(") or name.startswith("max_boundary_torus_residual("):
        numbers = [float(item) for item in name[name.index("(") + 1:-1].split(",")]
        worst = 0.0
        for i in boundary_vertices:
            x, y, z = vertices[i]
            if name.startswith("max_boundary_torus_residual("):
                worst = max(worst, abs(math.hypot(math.hypot(x, y) - numbers[0], z) - numbers[1]))
            else:
                a, b, c = numbers
                value = x * x / (a * a) + y * y / (b * b) + z * z / (c * c) - 1.0
                gradient = math.sqrt((2 * x / (a * a)) ** 2 + (2 * y / (b * b)) ** 2 + (2 * z / (c * c)) ** 2)
                worst = max(worst, abs(value) / gradient)
        return worst
    if name in {"boundary_area", "min_boundary_facet_angle", "max_boundary_facet_circumradius"}:
        area, smallest, widest_facet = 0.0, 180.0, 0.0
        for face in boundary:
            pa, pb, pc = (vertices[i] for i in face)
            sides = [math.dist(pb, pc), math.dist(pc, pa), math.dist(pa, pb)]
            u = [pb[k] - pa[k] for k in range(3)]
            w = [pc[k] - pa[k] for k in range(3)]
            twice = math.hypot(u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2],
                               u[0] * w[1] - u[1] * w[0])
            area += twice / 2
            widest_facet = max(widest_facet, sides[0] * sides[1] * sides[2] / (2.0 * twice))
            for i in range(3):
                s1, s2 = sides[(i + 1) % 3], sides[(i + 2) % 3]
                cosine = (s1 * s1 + s2 * s2 - sides[i] * sides[i]) / (2.0 * s1 * s2)
                smallest = min(smallest, math.degrees(math.acos(max(-1.0, min(1.0, cosine)))))
        return {"boundary_area": area, "min_boundary_facet_angle": smallest,
                "max_boundary_facet_circumradius": widest_facet}[name]
    if "(" in name and name.endswith(".off)"):
        return _tet_off_measure(name[:name.index("(")], name[name.index("(") + 1:-1], vertices, boundary,
                                boundary_vertices)
    raise ValueError(f"unknown tetrahedral measure {name}")


def measure(name: str, content: bytes) -> object:
    kind, _, field = name.partition(".")
    if kind == "off":
        return _off_measure(field, content)
    if kind == "tri2":
        return _tri2_measure(field, content)
    if kind == "tet":
        return _tet_measure(field, content)
    if kind == "points":
        return _points_measure(field, content)
    raise ValueError(f"unknown measure {name}")


def _approx(actual: object, expected: object, tolerance: float) -> bool:
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(actual) == len(expected) and
                all(_approx(a, e, tolerance) for a, e in zip(actual, expected)))
    return (isinstance(actual, (int, float)) and not isinstance(actual, bool) and
            math.isfinite(float(actual)) and abs(float(actual) - float(expected)) <= tolerance)


def _compare(actual: object, operator: str, expected: object) -> bool:
    if operator == "==":
        return type(actual) is type(expected) and actual == expected if isinstance(expected, bool) \
            else (not isinstance(actual, bool) and actual == expected)
    if operator == "!=":
        return actual != expected
    if operator == "approx":
        value, tolerance = expected
        return _approx(actual, value, tolerance)
    numeric = (isinstance(actual, (int, float)) and not isinstance(actual, bool) and
               isinstance(expected, (int, float)) and not isinstance(expected, bool))
    if not numeric:
        return False
    return {"<": actual < expected, "<=": actual <= expected,
            ">": actual > expected, ">=": actual >= expected}[operator]


_OPERATORS = {"==", "!=", "<", "<=", ">", ">=", "approx"}


class CaseView:
    """Resolve selectors against one traced transform exchange and its blobs."""

    def __init__(self, operation: dict, request: dict, response: dict,
                 blob_content: dict[str, bytes]):
        self.response = response
        self.inputs = {slot["slot"]: item for slot, item in
                       zip(operation["io"]["inputs"], request.get("inputs", []))}
        self.outputs = {item.get("slot"): item for item in response.get("outputs", [])
                        if isinstance(item, dict)}
        self.blob_content = blob_content

    def resolve(self, selector: str) -> object:
        if selector.startswith("metrics."):
            found, value = _report_value(self.response.get("metrics", {}), selector[len("metrics."):])
            if not found:
                raise KeyError(selector)
            return value
        side, slot, kind, *rest = selector.split(":", 3)
        table = {"input": self.inputs, "output": self.outputs}.get(side)
        if table is None or slot not in table:
            raise KeyError(selector)
        digest = table[slot].get("blob_sha256")
        if kind == "sha256":
            return digest
        content = self.blob_content[digest]
        if kind == "json":
            found, value = _report_value(json.loads(content.decode("utf-8")), rest[0])
            if not found:
                raise KeyError(selector)
            return value
        if kind == "measure":
            return measure(rest[0], content)
        raise KeyError(selector)


def assertion_failures(case: dict, view: CaseView) -> list[str]:
    failures = []
    for selector, operator, expected in case["assertions"]:
        try:
            actual = view.resolve(selector)
            if isinstance(expected, dict):
                expected = view.resolve(expected["path"])
            passed = _compare(actual, operator, expected)
        except (KeyError, ValueError, TypeError, IndexError, UnicodeError, ZeroDivisionError):
            passed = False
        if not passed:
            failures.append(f"{case['id']}: {selector} {operator} {expected!r}")
    return failures


def blob_bytes(blobs: dict[str, dict]) -> dict[str, bytes]:
    return {digest: base64.b64decode(value["content"], validate=True)
            for digest, value in blobs.items()}


for _family in GENERIC_FAMILIES.values():
    validate_contract(_family)
