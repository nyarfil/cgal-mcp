"""Deterministic bilingual geometry vocabulary for retrieval, never execution.

The vocabulary describes geometric concepts, not acceptance-query strings or
Operation IDs.  It can enrich registered aliases and pinned reference records;
it cannot make an unregistered capability executable.
"""
from __future__ import annotations

import math
import re
import unicodedata
from functools import lru_cache
from dataclasses import dataclass
from typing import Any, Iterable


STOP_WORDS = frozenset("""
a an and are as at be best by can capability cgal data do does each find fits for
from geometry geometric get have how i in into is it its me method my need of on
or perform please process processing result run should supported than that the
their them these this to use using want what when which with without would you
your available computation compute task input output choose help information
""".split())

# Domain phrases are deliberately shared by reference and Operation retrieval.
# Longer phrases win over their contained forms (e.g. convex decomposition is
# distinct from convex hull). English phrases require token boundaries.
VOCABULARY: dict[str, tuple[str, ...]] = {
    "convex_hull": ("convex hull", "凸包", "外側を包む", "outer envelope",
                    "smallest convex", "convex envelope"),
    "convex_decomposition": ("convex decomposition", "凸分解", "凸部分に分割",
                            "近似凸", "凸部品", "凸成分", "convex parts",
                            "convex components", "approximate convex"),
    "simplification": ("simplify", "simplification", "decimation", "decimate",
                       "simplified", "edge collapse", "edge decimation",
                       "collapse edges", "lighter mesh",
                       "軽量化", "軽量メッシュ", "簡略化", "辺縮約", "辺を縮約",
                       "ポリゴンを減", "面数を減", "辺数を減",
                       "garland", "heckbert", "lindstrom"),
    "repair": ("repair", "修復", "修正"),
    "non_manifold_repair": ("repair non manifold", "repair non-manifold",
                            "non-manifold neighborhoods", "non manifold neighborhoods",
                            "manifold-compatible components", "非多様体を分離", "非多様体修復",
                            "非多様体近傍", "多様体互換"),
    "degenerate_elements": ("degenerate", "zero-area", "zero area", "退化", "面積ゼロ"),
    "hole_filling": ("hole", "holes", "hole filling", "fill holes", "穴", "穴埋め"),
    "stitching": ("stitch", "stitching", "stitched", "weld", "welded", "welding",
                  "縫合", "貼り合わせ"),
    # Triangulating whole faces is distinct from triangulating holes.
    "face_triangulation": ("non-triangular face", "non-triangular faces",
                           "triangulate every supported face", "triangulate faces",
                           "triangulate each face", "非三角形面", "各面を三角形分割"),
    "clipping": ("clip the surface", "clip a surface", "clip a mesh", "clipping plane", "clip mesh", "cut-boundary",
                 "mesh clipping", "メッシュをクリップ", "切断面",
                 "クリップ平面", "クリッピング", "clip plane", "切り詰"),
    # Clipping against a box (or any non-planar region) is not plane clipping.
    "box_clipping": ("against a box", "clip box", "clipping box", "box clipping", "clip to a box",
                     "ボックスでクリップ", "箱でクリップ"),
    "remeshing": ("remesh", "remeshing", "リメッシュ", "再メッシュ", "再メッシュ化"),
    # Surface mesh generation/improvement concepts.  Each is a geometry idea,
    # not an Operation ID; routing still needs a registered operation covering it.
    "mesh_refinement": ("refine", "refinement", "refining", "densify", "denser mesh",
                        "細分", "高密度メッシュ", "リファイン"),
    "mesh_quality": ("mesh quality", "triangle quality", "improve quality", "improved quality",
                     "improved-quality", "high quality mesh", "高品質メッシュ", "品質改善",
                     "メッシュ形状改善"),
    "isotropic": ("isotropic", "isotropically", "uniform edge length",
                  "uniform target edge length", "等方", "均一な辺長", "一様な辺長"),
    "adaptive_sizing": ("adaptive", "adaptively", "adapt element", "adapt the mesh",
                        "sizing field", "graded mesh", "適応", "段階的メッシュ"),
    "split_long_edges": ("split long edges", "split every long edge", "long edge splitting",
                         "split edges longer", "長い辺を分割", "長辺を分割", "長辺分割"),
    "fairing": ("fairing", "fair the", "fair surface", "フェアリング", "フェアリング"),
    "boolean": ("boolean", "ブーリアン", "集合演算", "solid set operation"),
    # These operations may be internal steps of a Boolean algorithm, but their
    # requested outputs are refined/split source surfaces rather than a set
    # operation volume.  They therefore remain distinct routing concepts.
    "common_refinement": ("common refinement", "shared refinement",
                          "co-refine", "co-refinement", "co refinement",
                          "corefinement",
                          "intersection-conforming refinement", "共細分",
                          "対応した細分面", "交差曲線に沿って両表面"),
    "face_splitting": ("split faces", "face splitting", "split surface faces",
                       "split mesh faces", "cutter intersections",
                       "shared-cut provenance", "面を分割", "面分割",
                       "分離メッシュ", "切断由来情報"),
    "union": ("union", "unite", "merge solids", "combine solids", "和集合", "合体", "結合"),
    "intersection": ("intersection", "intersect", "overlap volume", "overlapping volume", "common volume",
                     "交差", "交点", "共通部分", "積集合", "重なった体積"),
    "difference": ("difference", "subtract", "cut away", "carve out", "差集合", "引き算", "くり抜"),
    "surface_intersection": ("intersection test", "intersection tests",
                             "surface intersection",
                             "交差判定", "交線"),
    "self_intersection": ("self intersection", "self-intersection", "self intersecting",
                          "self-intersecting",
                          "self crossing", "crosses itself", "surface crosses itself",
                          "faces cross", "自己交差", "自分自身と交差", "自分自身を貫"),
    "connected_components": ("connected component", "connected components",
                             "連結成分", "分離した成分", "disconnected pieces",
                             "separate shells", "separate pieces", "分離した殻",
                             "connected face components", "disconnected shells",
                             "component ids"),
    "corefinement": ("corefine", "corefinement", "corefining", "コリファイン"),
    "geometric_primitives": ("primitive", "primitives", "プリミティブ"),
    "spatial_tree": ("spatial tree", "kd tree", "kd-tree", "k-d tree", "空間木"),
    "matrix_search": ("matrix search", "matrix-search", "行列探索"),
    "mesh_normals": ("mesh normals", "surface normals", "face normals",
                     "vertex normals", "corner normals", "面法線", "頂点法線",
                     "コーナー法線", "メッシュ法線"),
    "point_normals": ("point normals", "point cloud normals", "normals for points",
                      "点群法線", "点の法線"),
    "normals": ("normal", "normals", "法線"),
    "orientation": ("orient", "orientation", "orienting", "consistent direction",
                    "向き", "方向を揃", "符号を揃"),
    "sharp_features": ("sharp feature", "sharp features", "sharp edge", "sharp edges",
                       "dihedral", "鋭い辺", "特徴辺", "二面角"),
    "measures": ("volume", "area", "centroid", "体積", "面積", "重心"),
    "integrity": ("validity", "valid", "integrity", "inspect", "inspection",
                  "健全性", "検査", "閉鎖性", "水密", "watertight", "manifold", "多様体",
                  "妥当性"),
    "validation": ("validate", "validation", "validator", "verify the result",
                   "check the result", "検証", "結果を確かめ"),
    "distance": ("distance", "distances", "距離", "hausdorff", "ハウスドルフ"),
    "sampling": ("sample points", "point sampling", "surface sampling", "sample the surface",
                 "サンプリング", "表面サンプル"),
    "directed_distance": ("directed hausdorff", "one-sided hausdorff",
                          "one sided hausdorff", "chamfer distance",
                          "片方向ハウスドルフ", "片側ハウスドルフ"),
    "aabb": ("aabb", "bounding box", "bounding boxes", "境界ボックス", "包囲箱",
             "境界箱", "有向境界箱", "軸平行", "バウンディングボックス", "外接直方体",
             "oriented bounding box", "axis aligned", "axis-aligned"),
    "slicing": ("slice", "slicing", "sliced", "cross section", "cross-section",
                "スライス", "断面"),
    "point_location": ("point location", "locate query points", "locate points",
                       "locate point", "containing face", "closest face",
                       "包含面", "最近傍面", "位置特定"),
    "nearest_neighbor": ("nearest neighbor", "nearest neighbour", "nearest-neighbor",
                         "近傍検索", "最近傍", "kd tree", "kd-tree", "kdtree"),
    "outliers": ("outlier", "outliers", "isolated samples", "spurious points",
                 "外れ値", "外れ点", "孤立点", "孤立した測定点"),
    "pointset_simplification": ("point simplification", "point reduction",
                                "point set reduction", "reduce samples",
                                "representative point set", "spatial coverage",
                                "downsample", "downsampling", "thin point cloud",
                                "点群を簡略化", "サンプルを削減", "代表点群",
                                "空間被覆"),
    "denoising": ("remove noise", "noise removal", "denoise", "denoising",
                  "cleanup", "clean up",
                  "clean noisy points", "remove noisy points", "ノイズを除去",
                  "ノイズ除去", "雑音を除去"),
    "grid_simplification": ("grid", "voxel", "グリッド", "ボクセル", "格子"),
    "random_simplification": ("random", "randomly", "ランダム", "無作為"),
    "hierarchy": ("hierarchy", "hierarchical", "階層"),
    "smoothing": ("smooth", "smoothing", "denoise coordinates", "平滑化", "滑らか", "ノイズを減"),
    "jet": ("jet", "ジェット"),
    "pca": ("pca", "principal component", "principal components", "主成分"),
    "mst": ("mst", "minimum spanning tree", "最小全域木"),
    "registration": ("registration", "register", "registering", "icp", "位置合わせ", "位置合せ", "位置合わ"),
    "reconstruction": ("reconstruct", "reconstruction", "surface from points", "再構成", "再構築", "復元"),
    "poisson": ("poisson", "ポアソン"),
    "advancing_front": ("advancing front", "advancing-front", "前進法"),
    "polygon": ("polygon", "polygons", "多角形", "ポリゴン", "輪郭"),
    "arrangement": ("arrangement", "アレンジメント", "曲線配置"),
    "overlay": ("overlay", "オーバーレイ", "重ね合わせ", "重ね合せ", "重畳"),
    "straight_skeleton": ("straight skeleton", "ストレートスケルトン", "直線骨格"),
    "offset": ("offset", "オフセット", "等距離輪郭"),
    "minkowski": ("minkowski", "ミンコフスキー"),
    "triangulation": ("triangulate", "triangulation", "三角形分割", "三角形化", "四面体分割"),
    "delaunay": ("delaunay", "ドロネー"),
    "voronoi": ("voronoi", "ボロノイ"),
    "alpha_shape": ("alpha shape", "alpha shapes", "alpha-shape", "アルファ形状"),
    "alpha_wrap": ("alpha wrap", "alpha wrapping", "アルファラップ", "アルファラッピング"),
    "bounding_volume": ("bounding volume", "bounding sphere", "包囲体", "包囲球", "最小球",
                        "境界体積"),
    "volume_meshing": ("volume mesh", "volume meshing", "tetrahedral mesh",
                       "体積メッシュ", "四面体メッシュ", "ボリュームメッシュ",
                       "四面体ボリューム", "メッシュ生成領域", "3d mesh generation",
                       "tetrahedral volume", "cell quality", "meshing domain"),
    "surface_meshing": ("surface meshing", "surface mesh generation", "曲面メッシュ生成",
                        "conforming surface mesh", "表面メッシュを生成", "表面メッシュ生成",
                        "適合する表面メッシュ"),
    "segmentation": ("segmentation", "segmenting", "segment the shape",
                     "shape diameter field", "セグメンテーション", "領域分割"),
    "skeleton": ("skeleton", "skeletonization", "骨格", "スケルトン"),
    "shortest_path": ("shortest path", "geodesic", "最短経路", "測地線"),
    "parameterization": ("parameterization", "parametrization", "parameterize",
                         "parametrize", "テクスチャ座標", "パラメータ化", "パラメタ化", "uv展開"),
    "subdivision": ("subdivision", "細分割", "サブディビジョン"),
    "barycentric": ("barycentric", "重心座標"),
    "optimization": ("optimization", "optimisation", "最適化", "二次計画", "線形計画"),
    "interpolation": ("interpolation", "補間"),
    "approximation": ("approximation", "approximate", "近似"),
    "predicates": ("predicate", "predicates", "述語", "頑健な判定"),
    "constructions": ("construction", "constructions", "作図", "幾何構成"),
    "kernel": ("kernel", "kernels", "カーネル", "正確な演算"),
    "protected_edges": ("protected edges", "edge constraints", "constrained edges",
                        "retain protected geometry",
                        "保護辺", "拘束辺"),
    "external_envelope": ("strict geometric envelope", "external envelope",
                          "external geometric envelope",
                          "mesh and an envelope", "幾何包絡", "包絡外へ出る"),
    "bounded_normal_change": ("bounded normal rotation", "allowed normal change",
                              "bounded normal change", "法線変化を制限",
                              "許容法線変化", "法線回転を制限", "法線回転が制限"),
    "fast_envelope": ("fast envelope", "fast-envelopes", "fast envelopes"),
    "dimension_2d": ("2d",),
    "planar_meshing": ("quality 2d mesh", "2d mesh", "planar mesh", "2d mesh generation",
                       "2d メッシュ", "2dメッシュ", "平面メッシュ"),
    "ray_casting": ("ray casting", "ray cast", "cast rays", "cast the supplied probe rays",
                    "probe rays", "ray shooting", "first hit", "first-hit",
                    "first ray hit", "ray mesh intersection", "レイキャスト",
                    "レイを", "レイの", "レイと", "多数のレイ", "照射", "光線",
                    "最初の交点"),
}

# Every explicitly requested concept in these sets must be represented by an
# operation's registered id/summary/aliases before automatic routing is safe.
# Broad nouns such as ``mesh`` are intentionally absent.
PRIMARY_CONCEPTS = frozenset(VOCABULARY)
METHOD_CONCEPTS = frozenset({
    "jet", "pca", "mst", "poisson", "advancing_front", "delaunay",
    "voronoi", "alpha_shape", "alpha_wrap", "straight_skeleton",
    "fast_envelope",
})

# Plain bilingual nouns.  They only add English search words (score and FTS
# candidates); they never create concepts, so they cannot make routing stricter.
JA_WORD_LEXICON: tuple[tuple[str, str], ...] = (
    ("三角形メッシュ", "triangle mesh"), ("メッシュ", "mesh"), ("点群", "point cloud"),
    ("平面", "plane"), ("線分", "segment"), ("四面体", "tetrahedral"),
    ("表面", "surface"), ("ソリッド", "solid"), ("重み付き", "weighted"),
    ("正則", "regular"), ("拘束", "constrained"), ("陰関数", "implicit"),
    ("パラメトリック", "parametric"), ("サイト", "site"), ("照会点", "query points"),
    ("領域", "domain"), ("凸", "convex"), ("輪郭", "contour"),
    # General bilingual geometry nouns/verbs (bridge words for Japanese queries).
    ("四角形", "quad quadrilateral"), ("三角形", "triangle"), ("多角形", "polygon"),
    ("頂点", "vertex"), ("面積", "area"), ("体積", "volume"), ("重心", "centroid"),
    ("曲率", "curvature"), ("曲面", "surface"), ("曲線", "curve"), ("直線", "line"),
    ("球面", "sphere"), ("交差", "intersection"), ("干渉", "interference collision intersect"),
    ("衝突", "collision intersect"), ("貫通", "intersect"), ("距離", "distance"),
    ("近傍", "neighbor nearest"), ("最近", "nearest closest"), ("近い", "nearest closest"),
    ("半径", "radius"), ("範囲", "range"), ("検索", "search query"), ("探索", "search"),
    ("厚み", "thickness"), ("肉厚", "thickness"), ("断面", "section slice"),
    ("スライス", "slice"), ("切断", "cut clip"), ("分割", "split divide partition"),
    ("分離", "separate split"), ("結合", "merge union combine"), ("合体", "union merge"),
    ("引く", "subtract difference"), ("差し引", "subtract difference"),
    ("くり抜", "subtract difference"), ("重なり", "overlap intersection"),
    ("共通", "common intersection"), ("穴", "hole"), ("隙間", "gap crack"),
    ("継ぎ目", "seam"), ("修復", "repair fix"), ("補修", "repair fix"),
    ("欠陥", "defect repair inspect"), ("検査", "inspect check"), ("確認", "verify check"),
    ("検証", "validate verify"), ("滑らか", "smooth"), ("平滑", "smooth"),
    ("ノイズ", "noise"), ("外れ値", "outlier"), ("間引", "thin reduce downsample"),
    ("削減", "reduce"), ("減ら", "reduce"), ("軽量", "lightweight simplify"),
    ("軽く", "lightweight reduce"), ("簡略", "simplify"), ("細かく", "refine denser"),
    ("粗く", "coarse"), ("均一", "uniform"), ("再構成", "reconstruct"), ("復元", "reconstruct"),
    ("展開", "unfold parameterize"), ("テクスチャ", "texture parameterize"),
    ("骨格", "skeleton"), ("中心線", "skeleton centerline"), ("外形", "outline hull"),
    ("外周", "boundary outline"), ("内側", "inside inward"), ("外側", "outside outward"),
    ("包含", "contain inside"), ("内外", "inside outside"), ("測定", "measure"),
    ("計測", "measure"), ("計算", "compute"), ("推定", "estimate"), ("整列", "align"),
    ("位置合わせ", "registration align"), ("裏返", "flip orientation"), ("反転", "flip"),
    ("最短", "shortest"), ("経路", "path route"), ("最適", "optimal optimize"),
    ("制約", "constraint"), ("近似", "approximate approximation"), ("クラスタ", "cluster"),
    ("部品", "part component"), ("連結", "connected"), ("成分", "component"),
    ("最大", "maximum largest"), ("最小", "minimum smallest"), ("誤差", "error deviation"),
    ("ずれ", "deviation"), ("偏差", "deviation"), ("光線", "ray"), ("レイ", "ray"),
    ("視線", "ray"), ("包む", "wrap enclose"), ("囲む", "enclose"), ("周期", "periodic"),
    ("重み", "weight"), ("境界", "boundary"), ("生成", "generate"), ("解析", "analysis"),
    ("円形", "circle"), ("円を", "circle"), ("粗い", "coarse"), ("細分", "refine subdivide"),
    # Broader bilingual vocabulary (generic geometry verbs/nouns, kanji and kana variants).
    ("削る", "reduce remove"), ("削除", "remove delete"), ("取り除", "remove"), ("除去", "remove"),
    ("落と", "reduce"), ("少なく", "fewer reduce"), ("少ない", "fewer reduce"), ("半分", "half reduce"),
    ("縮約", "collapse simplify"), ("統合", "merge"), ("頂点数", "vertex count reduce"),
    ("面数", "face count triangle count"), ("三角形数", "triangle count"), ("点数", "point count"),
    ("ポリゴン数", "polygon count simplify"), ("データ量", "size reduce"),
    ("軽い", "lightweight simplify"), ("作り直", "rebuild remesh"),
    ("再構築", "rebuild reconstruct remesh"), ("やり直", "redo rebuild"),
    ("整える", "regularize improve"), ("揃える", "uniform equalize"), ("そろえ", "uniform"),
    ("一定", "constant uniform"), ("一様", "uniform"), ("目標長", "target length"),
    ("辺長", "edge length"), ("長さ", "length"), ("品質", "quality"), ("歪み", "distortion"),
    ("適応", "adaptive"), ("密度", "density"), ("疎", "sparse"), ("細かい", "fine dense"),
    ("穴を塞", "fill hole"), ("塞ぐ", "fill close"), ("埋め", "fill"), ("閉じ", "close closed"),
    ("水密", "watertight closed"), ("開いた", "open boundary"), ("境界ループ", "boundary loop hole"),
    ("縫い", "stitch weld"), ("溶接", "weld"), ("接合", "join stitch"), ("重複", "duplicate"),
    ("面積ゼロ", "zero area degenerate"), ("向きを揃", "orient consistent"),
    ("裏表", "orientation flip"), ("一貫", "consistent"), ("非多様体", "non manifold"),
    ("つまみ", "pinch"), ("くびれ", "pinch"), ("自己交差", "self intersection"),
    ("乖離", "deviation distance"), ("離れ", "distance away"), ("隔たり", "distance"),
    ("最悪", "worst maximum"), ("両方向", "both directions symmetric"),
    ("双方向", "symmetric both directions"), ("対称", "symmetric"), ("片方向", "one sided directed"),
    ("保証", "guaranteed bound"), ("上界", "upper bound"), ("下界", "lower bound"),
    ("許容", "tolerance"), ("公差", "tolerance"), ("精度", "accuracy precision"), ("厳密", "exact"),
    ("正確", "exact"), ("概算", "approximate estimate"), ("サンプル", "sample"), ("標本", "sample"),
    ("ばらま", "scatter sample"), ("最近傍", "nearest neighbor"), ("球内", "ball radius range"),
    ("範囲内", "within range"), ("半径内", "within radius"), ("バウンディング", "bounding"),
    ("包囲", "bounding enclosing"), ("直方体", "box"), ("箱", "box"),
    ("交点", "intersection point hit"), ("当たる", "hit intersect"), ("当たり", "hit"),
    ("最初に", "first"), ("射線", "ray"), ("貫く", "pierce intersect"), ("刺さ", "pierce"),
    ("含まれる", "contained inside"), ("属する", "belong contained"), ("位置", "position location"),
    ("座標", "coordinates"), ("重心座標", "barycentric coordinates"), ("射影", "project closest"),
    ("投影", "project"), ("最も近い", "closest nearest"), ("なめらか", "smooth"), ("外皮", "shell wrap"),
    ("殻", "shell"), ("くるむ", "wrap enclose"), ("包み込", "wrap enclose"), ("包装", "wrap"),
    ("かぶせ", "wrap cover"), ("被せ", "wrap cover"), ("覆う", "cover enclose"),
    ("覆い", "cover enclose"), ("収縮", "shrink"), ("ぐちゃぐちゃ", "messy broken"),
    ("乱れた", "noisy messy"), ("不完全", "incomplete broken"), ("壊れ", "broken defective"),
    ("欠け", "missing"), ("スキャン", "scan point cloud"), ("計測点", "measured points scan"),
    ("測定点", "measured points scan"), ("ばらばら", "scattered unordered"), ("散在", "scattered"),
    ("法線ベクトル", "normal vector"), ("どちらを向", "facing orientation normal"),
    ("表面の向き", "surface normal orientation"), ("面の向き", "face orientation normal"),
    ("水平", "horizontal"), ("垂直", "perpendicular vertical"), ("角度", "angle"), ("鋭い", "sharp"),
    ("尖", "sharp"), ("急な", "steep sharp"), ("折れ線", "polyline"), ("折れ目", "crease sharp edge"),
    ("稜線", "ridge sharp edge"), ("エッジ", "edge"), ("特徴", "feature"), ("輪郭線", "contour outline"),
    ("形状直径", "shape diameter"), ("部位", "part region segment"), ("部分", "part"),
    ("意味のある", "meaningful segment"), ("パーツ", "part"), ("切り分け", "segment split"),
    ("分ける", "split divide"), ("分けて", "split divide"), ("ばらし", "split separate"),
    ("細分化", "subdivide refine"), ("細分割", "subdivision"), ("四つ", "four"),
    ("ループ細分", "loop subdivision"), ("展開図", "unfold flatten parameterization"),
    ("展開", "unfold flatten parameterize"), ("貼る", "map texture"), ("写像", "mapping"),
    ("等角", "conformal angle preserving"), ("角度を保", "angle preserving conformal"),
    ("剛体", "rigid"), ("変換", "transformation"), ("重ね", "overlay align register overlap"),
    ("重ね合", "register align overlay"), ("位置合", "register align"),
    ("アライメント", "alignment registration"), ("平面分割", "planar subdivision arrangement"),
    ("線分群", "segments arrangement"), ("交わる", "cross intersect"), ("交差する", "cross intersect"),
    ("横切", "cross traverse"), ("通過", "pass cross"), ("ゾーン", "zone"), ("畳み込み", "convolution"),
    ("縮約畳み込み", "reduced convolution"), ("掃引", "sweep"), ("スイープ", "sweep"),
    ("移動", "move motion"), ("ロボット", "robot motion"), ("経路計画", "path planning"),
    ("膨張", "dilate offset"), ("内側へ", "inward offset"), ("外側へ", "outward offset"),
    ("包含判定", "containment inside outside test"), ("内部判定", "inside test"), ("凹", "concave"),
    ("単純", "simple"), ("穴あき", "with holes"), ("穴付き", "with holes"), ("最小角", "minimum angle"),
    ("メッシュ生成", "mesh generation"), ("制約線", "constraint edge constrained"),
    ("拘束線", "constraint edge constrained"), ("パワー", "power weighted"),
    ("トーラス", "torus periodic"), ("球面上", "on sphere"), ("最小化", "minimize"), ("最大化", "maximize"),
    ("線形", "linear"), ("二次", "quadratic"), ("制約付き", "constrained"), ("目的関数", "objective"),
    ("不等式", "inequality"), ("上下限", "bounds"), ("散布", "scattered"),
    ("自然近傍", "natural neighbor"), ("中心", "center"), ("被覆", "cover coverage"),
    ("区間", "interval"), ("配置", "placement"), ("ソート済み", "sorted"),
    ("最小包含", "smallest enclosing"), ("外接", "circumscribed bounding enclosing"),
    ("内接", "inscribed"), ("囲う", "enclose"), ("左回り", "left turn orientation"),
    ("右回り", "right turn orientation"), ("左折", "left turn"), ("共線", "collinear"),
    ("一直線", "collinear line"), ("同一平面", "coplanar"), ("同一直線", "collinear"),
    ("同一円周", "cocircular"), ("同一球面", "cospherical"), ("円の内側", "inside circle incircle"),
    ("外接円", "circumcircle incircle"), ("符号", "sign"), ("丸め", "rounding"), ("誤差なし", "exact"),
    ("厳密に", "exact"), ("有理数", "rational exact"), ("基本図形", "primitive geometric objects"),
    ("オブジェクト", "object"), ("作りたい", "construct build"), ("構築", "construct build"),
    ("距離の二乗", "squared distance"), ("二乗", "squared"), ("2乗", "squared"),
    ("どこで交わ", "intersection location"), ("点間隔", "spacing"), ("間隔", "spacing interval"),
    ("平均間隔", "average spacing"), ("孤立", "isolated outlier"), ("外れ", "outlier"),
    ("雑音", "noise"), ("ぶれ", "noise jitter"), ("ガタつ", "noisy jitter"),
    ("尖った特徴", "sharp features"), ("特徴を残", "preserve features"), ("特徴を保", "preserve features"),
    ("種", "seed"), ("乱数", "random"), ("シード", "seed"), ("再現", "reproducible deterministic"),
    ("セル", "cell"), ("クラスタリング", "clustering"), ("代表点", "representative"),
    ("集約", "cluster aggregate"), ("前処理", "preprocess"), ("下処理", "preprocess"),
    ("前提", "prerequisite"), ("診断", "diagnostic inspect"), ("点検", "inspect"),
    ("調べ", "examine check inspect"), ("確かめ", "verify check"), ("チェック", "check"),
    ("健全", "valid health"), ("妥当", "valid"), ("不正", "invalid"), ("レポート", "report"),
    ("報告", "report"), ("表面積", "surface area"), ("容積", "volume"), ("最大の", "largest"),
    ("一番大きい", "largest"), ("最大成分", "largest component"), ("シェル", "shell"),
    ("島", "island component"), ("ばらばらの部分", "disconnected pieces components"),
    ("削り取", "subtract carve difference"), ("切り取", "cut subtract"), ("引き算", "subtract"),
    ("足し合わせ", "union merge"), ("くっつ", "union join"), ("共有", "shared common"),
    ("重なる部分", "overlap intersection"), ("交わり", "intersection overlap"),
    ("残り", "remainder difference"), ("立体", "solid"), ("平面で切", "cut plane clip"),
    ("切り落とし", "chop clip"), ("切り取り", "clip cut"), ("上側", "upper side above"),
    ("片側", "one side"), ("輪切り", "slice section"), ("蓋", "cap"), ("ふた", "cap"),
    ("両側", "both sides"), ("切断線", "cut line"), ("交線", "intersection curve polyline"),
    ("交差曲線", "intersection curve"), ("交差線", "intersection curve"),
    ("交わる線", "intersection curve"),
)

# English thesaurus: everyday wording for geometry tasks mapped to the words the
# documentation uses.  Like the Japanese lexicon it only adds retrieval words.
EN_SYNONYMS: dict[str, str] = {
    "thin": "reduce downsample simplify", "coarsen": "simplify reduce decimate",
    "shrink": "reduce simplify", "fewer": "reduce simplify", "lighter": "simplify reduce",
    "lightweight": "simplify reduce", "compress": "simplify reduce", "decrease": "reduce",
    "chop": "clip cut", "trim": "clip cut remove", "carve": "subtract difference",
    "punch": "subtract difference", "fuse": "union merge", "glue": "stitch weld",
    "seam": "stitch weld", "patch": "fill hole repair", "plug": "fill hole",
    "gap": "hole crack", "crack": "hole gap", "seal": "close fill", "mend": "repair",
    "heal": "repair", "jitter": "noise", "noisy": "noise", "fuzz": "noise",
    "bumpy": "noise smooth", "relax": "smooth", "rebuild": "remesh reconstruct",
    "regenerate": "remesh", "retriangulate": "remesh triangulate", "resample": "remesh sample",
    "tessellate": "triangulate", "subdivide": "refine subdivision", "partition": "segment",
    "decompose": "segment decomposition", "fragment": "component", "island": "component",
    "piece": "component", "flatten": "parameterization unfold",
    "unwrap": "parameterization unfold", "unfold": "parameterization flatten",
    "texture": "parameterization", "envelop": "enclose wrap", "enclose": "wrap hull",
    "wrap": "enclose shell alpha", "shrinkwrap": "wrap alpha shell", "skin": "surface wrap",
    "medial": "skeleton centerline", "centerline": "skeleton", "spine": "skeleton",
    "thickness": "diameter shape", "closest": "nearest", "nearby": "nearest neighbor",
    "proximity": "nearest distance", "within": "range radius", "ball": "range radius",
    "hit": "intersection", "pierce": "intersect", "collide": "intersect collision",
    "clash": "intersect", "overlap": "intersection", "interfere": "intersect", "shoot": "ray",
    "probe": "ray", "beam": "ray", "deviation": "distance", "discrepancy": "distance error",
    "drift": "deviation distance", "worst": "maximum", "farthest": "maximum",
    "both": "symmetric", "mutual": "symmetric", "bidirectional": "symmetric",
    "guarantee": "bound", "guaranteed": "bound", "certified": "bound", "tolerance": "bound",
    "robust": "exact predicate", "rational": "exact", "left": "orientation predicate",
    "turn": "orientation predicate", "collinear": "predicate", "coplanar": "predicate",
    "cocircular": "predicate", "sign": "orientation predicate",
    "superimpose": "register alignment", "align": "register alignment", "scan": "point cloud",
    "scanned": "point cloud", "lidar": "point cloud", "photogrammetry": "point cloud",
    "facing": "normal orientation", "outward": "orientation", "flip": "orientation",
    "consistent": "orientation", "crease": "sharp feature", "ridge": "sharp feature",
    "corner": "sharp feature", "fold": "sharp feature", "dihedral": "angle sharp",
    "inflate": "offset", "dilate": "offset", "erode": "offset", "grow": "offset",
    "buffer": "offset", "inset": "offset interior", "sweep": "minkowski",
    "robot": "minkowski motion", "convolution": "minkowski", "inside": "containment",
    "contain": "containment", "enclosed": "containment", "locate": "location",
    "scattered": "interpolation", "estimate": "approximate", "optimal": "optimization",
    "minimize": "optimization", "minimise": "optimization", "maximize": "optimization",
    "cost": "optimization", "constraint": "constrained", "graded": "adaptive",
    "tetrahedron": "tetrahedral volume", "tetrahedralize": "tetrahedral volume mesh",
    "tetrahedralization": "tetrahedral volume mesh", "facility": "center",
    "cover": "center coverage", "centre": "center", "periodic": "torus", "torus": "periodic",
    "sphere": "spherical", "spherical": "sphere", "unoriented": "orientation",
    "oriented": "orientation", "watertight": "closed", "closed": "watertight",
    "border": "boundary", "boundary": "border", "loop": "boundary", "polyline": "curve",
    "hole": "gap", "noise": "outlier", "outlier": "noise", "spacing": "density",
    "density": "spacing", "average": "mean", "mean": "average", "largest": "maximum",
    "biggest": "largest", "smallest": "minimum",
}

METHOD_PARAMETER_REQUIREMENTS: dict[str, tuple[str, Any]] = {
    "pca": ("method", "pca"),
    "jet": ("method", "jet"),
    "union": ("operation", "union"),
    "intersection": ("operation", "intersection"),
    "difference": ("operation", "difference"),
    "bounded_normal_change": ("bounded_normal_change", True),
}

PARAMETER_FEATURE_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "protected_edges": ("constrained_edges", "nonempty"),
}

# Validator-role operations normally require explicit validation language.
# A registered bounded measurement may be selected directly only when its
# schema proves the complete named measurement contract.
DIRECT_VALIDATOR_CONTRACTS: dict[str, frozenset[str]] = {
    "distance": frozenset({"tolerance", "error_bound"}),
}


def normalize(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold().replace("_", " ")
    value = re.sub(r"(?<![a-z0-9])(?:2\s*[-‐‑–—]?\s*d|2\s*[-‐‑–—]?\s*dimensional|two\s*[-‐‑–—]?\s*dimensional|2\s*次元|二次元)(?![a-z0-9])",
                   " 2d ", value)
    return " ".join(value.split())


def _contains(text: str, phrase: str) -> bool:
    normalized = normalize(phrase)
    if re.search(r"[a-z]", normalized) and not re.search(r"[^\x00-\x7f]", normalized):
        ending = r"s?" if normalized[-1:].isalpha() and not normalized.endswith("s") else ""
        return re.search(r"(?<![a-z0-9])" + re.escape(normalized) + ending + r"(?![a-z0-9])", text) is not None
    return normalized in text


def _stem(word: str) -> str:
    # Small transparent morphology, avoiding arbitrary fuzzy substring matches.
    if word.endswith("ies") and len(word) > 5:
        return word[:-3] + "y"
    if word.endswith("ing") and len(word) > 6:
        return word[:-3]
    if word.endswith(("ated", "ited")) and len(word) > 6:
        return word[:-1]
    if word.endswith("ed") and len(word) > 5:
        return word[:-2]
    if word.endswith("s") and len(word) > 4 and not word.endswith(("ss", "sis")):
        return word[:-1]
    return word


_EN_SYNONYM_LOOKUP = {_stem(key): value for key, value in EN_SYNONYMS.items()}


@dataclass(frozen=True)
class QueryTerms:
    normalized: str
    words: tuple[str, ...]
    concepts: frozenset[str]
    phrases: tuple[str, ...]
    bridge_words: tuple[str, ...] = ()


@dataclass(frozen=True)
class MatchEvidence:
    score: float
    covered_primary_concepts: frozenset[str]
    uncovered_primary_concepts: frozenset[str]
    covered_method_concepts: frozenset[str]
    uncovered_method_concepts: frozenset[str]
    word_matches: frozenset[str]
    alias_matches: tuple[str, ...]
    route_supported: bool
    confidence: str


def parse_query(text: str, *, document: bool = False) -> QueryTerms:
    normalized = normalize(text)
    matches = [(concept, normalize(phrase)) for concept, aliases in VOCABULARY.items()
               for phrase in aliases if _contains(normalized, phrase)]
    # Suppress a broad concept when all its phrases are contained in a more
    # specific matched phrase. Self-intersection, straight skeleton and convex
    # decomposition consequently retain their specific meaning.
    retained = [(concept, phrase) for concept, phrase in matches
                if not any(other != concept and phrase != longer and phrase in longer
                           for other, longer in matches)]
    concepts = {concept for concept, _ in retained}
    if "self_intersection" in concepts or "surface_intersection" in concepts:
        concepts.discard("intersection")
    if "bounded_normal_change" in concepts:
        concepts.discard("normals")
    if not document and "corefinement" in concepts:
        concepts -= {"intersection", "subdivision"}
    if "overlay" in concepts or "arrangement" in concepts:
        # "overlay their subdivisions" names the arrangement, not a mesh subdivision.
        concepts.discard("subdivision")
    if "straight_skeleton" in concepts:
        concepts.discard("skeleton")
    if "convex_decomposition" in concepts:
        concepts.discard("approximation")
    # Barycentric weights "reconstruct" a query position; this is not point
    # cloud surface reconstruction.
    if "barycentric" in concepts and "reconstruction" in concepts and re.search(
            r"weights|重み", normalized):
        concepts.discard("reconstruction")
    # 2D texture coordinates are the output of a parameterization, and
    # "2D or 3D" names both dimensions; neither restricts the input to 2D.
    had_2d = "dimension_2d" in concepts
    if "dimension_2d" in concepts and (
            "parameterization" in concepts
            or re.search(r"2d\s*(?:または|もしくは|か|or|and|及び|および|/)\s*3d", normalized)
            or re.search(r"2d\s*(?:texture|テクスチャ)", normalized)):
        concepts.discard("dimension_2d")
    # Checking a predicate's existence condition is the predicate evaluation;
    # "manifold predicates" in a mesh-health request are mesh properties instead.
    if re.search(r"(?:manifold|mesh|多様体)\s*predicates?", normalized):
        concepts.discard("predicates")
    elif "predicates" in concepts and re.search(r"robust|exact|頑健|厳密|述語で", normalized):
        concepts.discard("integrity")
    # Preparing a point set for reconstruction is point preprocessing, not
    # reconstruction or a generic validation request.
    if re.search(r"prepared for reconstruction|reconstruction prerequisites|再構成前|再構成の前提", normalized):
        concepts -= {"reconstruction", "validation", "integrity"}
    # "geometric primitives" qualifies the operands of another named task.
    if not document and "geometric_primitives" in concepts and len(concepts) > 1:
        concepts.discard("geometric_primitives")
    # "collision-inspection" / "検査用" qualifies the input scene.
    if "integrity" in concepts and re.search(r"衝突検査|検査用の|collision", normalized) and not re.search(
            r"検査して|検査し、|inspect|validate|check", normalized):
        concepts.discard("integrity")
    explicit_mesh_normal = any(_contains(normalized, phrase) for phrase in (
        "face normals", "vertex normals", "corner normals", "mesh normals",
        "頂点法線", "コーナー法線", "メッシュ法線"))
    # Japanese substring matching is intentional for ordinary domain phrases,
    # but ``表面法線`` (surface normal) contains ``面法線`` (face normal).
    # In point-cloud context the former means an estimated point normal; only
    # the standalone face-normal expression requests a mesh entity.
    explicit_mesh_normal = explicit_mesh_normal or (
        "面法線" in normalized and "表面法線" not in normalized)
    if ("point cloud" in normalized or "point set" in normalized
            or "点群" in normalized) and not explicit_mesh_normal:
        if concepts & {"normals", "mesh_normals", "point_normals"}:
            concepts.discard("mesh_normals")
            concepts.add("point_normals")
    # "polygon with holes" / "holed polygon" qualifies the input; it is not a
    # request to fill holes.
    if "hole_filling" in concepts and "polygon" in concepts and re.search(
            r"(?:with|having|containing) holes|holed|穴付き|穴あき|穴を持つ", normalized)             and not re.search(r"fill|穴埋め|塞", normalized):
        concepts.discard("hole_filling")
    # Adjectival input/output qualifications do not request a second action.
    # They remain searchable words, while routing follows the requested verb.
    # A valid/healthy mesh as the stated result of a repair, or "target of
    # inspection" as a noun qualifier, does not request a separate inspection.
    repair_like = {"repair", "degenerate_elements", "hole_filling", "stitching",
                   "non_manifold_repair"}
    if "integrity" in concepts and concepts & repair_like:
        asks_inspection = re.search(
            r"inspect|check|report on|health report|検査して|検査し、|検査を|検査結果|健全性", normalized)
        if not asks_inspection or "検査対象" in normalized and not re.search(
                r"検査して|検査し、|検査を|検査結果|健全性", normalized):
            concepts.discard("integrity")
    # Validating an input property (orientation, polygon) is an integrity
    # check of that input, not a request for a separate validator operation.
    if "validation" in concepts and re.search(
            r"validat\w*\s+(?:the\s+|its\s+|their\s+)?(?:orientation|polygon|input)", normalized):
        concepts.discard("validation")
        concepts.add("integrity")
    # Triangulate/refine/fair are the stages of one hole-filling task; they do
    # not request a separate global refinement or fairing operation.
    if "hole_filling" in concepts:
        concepts.discard("mesh_refinement")
        concepts.discard("fairing")
    # "Smooth and optimize vertex positions" is a single mesh-quality task, and
    # fixed/protected feature edges qualify the input constraints of smoothing;
    # neither requests a separate programming solve or feature detection.
    if "smoothing" in concepts:
        if "optimization" in concepts and not re.search(
                r"二次計画|線形計画|quadratic|linear program", normalized):
            concepts.discard("optimization")
        if "sharp_features" in concepts and re.search(
                r"固定|保護|protected|fixed|constrained", normalized) and not re.search(
                r"detect|検出|抽出|find|extract|識別", normalized):
            concepts.discard("sharp_features")
    if "向き付き" in normalized:
        concepts.discard("orientation")
    if "検証済み" in normalized:
        concepts.discard("validation")
    if ("for downstream remeshing" in normalized
            or "for later remeshing" in normalized
            or re.search(r"再メッシュ(?:処理)?向け", normalized)):
        concepts.discard("remeshing")
    # A nearest-neighbour search reports distances as part of its result; it is
    # not a request for a separate distance measurement.
    if "nearest_neighbor" in concepts and "distance" in concepts and not re.search(
            r"hausdorff|ハウスドルフ|chamfer|squared|二乗|2乗", normalized):
        concepts.discard("distance")
    # "Before constructing intersections, evaluate predicates": the predicate
    # is the requested decision; the construction is its downstream consumer.
    if "predicates" in concepts and "intersection" in concepts and re.search(
            r"construct|構築|作図", normalized):
        concepts.discard("intersection")
    if "validation" in concepts and re.search(
            r"validate (?:the |this |that )?(?:workflow|pipeline|approach|process)", normalized):
        concepts.discard("validation")
    inspects = re.search(r"inspect|check|report on|検査|健全性|妥当性", normalized)
    orients = re.search(r"orient(?:ing)? (?:the|all|every)|reorient|unify|揃|向きを(?:修正|統一|反転)|向き付けし", normalized)
    if "integrity" in concepts and inspects and "orientation" in concepts and not orients:
        concepts.discard("orientation")
    # A watertight/valid input qualifies the task; it does not ask for a
    # separate integrity report when a different transformation is requested.
    transform_like = {"segmentation", "skeleton", "parameterization", "simplification",
                      "remeshing", "subdivision", "reconstruction", "convex_decomposition",
                      "triangulation", "surface_meshing", "volume_meshing", "clipping"}
    if "integrity" in concepts and concepts & transform_like and not re.search(
            r"inspect|check|report on|health report|検査して|検査し、|検査を|検査結果", normalized):
        concepts.discard("integrity")
    if "subdivision" in concepts and "smoothing" in concepts and re.search(
            r"smooth (?:refined|limit|surface)|滑らかな", normalized):
        concepts.discard("smoothing")
    if "overlay" in concepts:
        concepts.discard("mesh_refinement")
    if concepts & {"surface_meshing", "volume_meshing"}:
        concepts.discard("approximation")
    if concepts & {"normals", "point_normals", "mesh_normals"} and (
            "法線付き" in normalized or re.search(
                r"(?:points?|point cloud|point set)s?\s+with\s+(?:oriented\s+)?normals", normalized)
    ) and not re.search(r"estimat|推定|compute normals|法線を(?:計算|求)", normalized):
        concepts -= {"normals", "point_normals", "mesh_normals"}
    concepts = frozenset(concepts)
    word_text = normalized
    if had_2d and "dimension_2d" not in concepts:
        word_text = normalized.replace("2d", " ")
    elif re.search(r"2d\s*(?:または|もしくは|か|or|and|及び|および|/)\s*3d", normalized):
        word_text = normalized.replace("2d", " ", 1)
    extra = " ".join(english for japanese, english in JA_WORD_LEXICON if japanese in normalized)
    words = tuple(dict.fromkeys(_stem(word) for word in re.findall(
        r"[a-z][a-z0-9]*|[23]d", word_text)
                                if word not in STOP_WORDS and (len(word) >= 3 or word in {"2d", "3d"})))
    synonyms = " ".join(_EN_SYNONYM_LOOKUP[word] for word in words if word in _EN_SYNONYM_LOOKUP)
    bridge_words = tuple(dict.fromkeys(
        _stem(word) for word in re.findall(r"[a-z][a-z0-9]*", extra + " " + synonyms)
        if word not in STOP_WORDS and _stem(word) not in words))
    phrases = tuple(dict.fromkeys(phrase for _, phrase in sorted(retained, key=lambda item: (-len(item[1]), item[1]))))
    return QueryTerms(normalized, words, concepts, phrases, bridge_words)


@lru_cache(maxsize=4096)
def document_terms(text: str) -> QueryTerms:
    return parse_query(text.replace(".", " ").replace("/", " ").replace("-", " "), document=True)


def fts_expression(terms: QueryTerms) -> str | None:
    # The caller binds this as a SQL parameter. Quoting also prevents FTS query
    # syntax from becoming operators supplied by the user.
    values = list(terms.words)
    for concept in sorted(terms.concepts):
        values.extend(normalize(alias) for alias in VOCABULARY[concept]
                      if len(normalize(alias)) >= 3)
    values = list(dict.fromkeys(values))[:128]
    return " OR ".join('"' + value.replace('"', '""') + '"' for value in values) or None


def lexical_score(query: QueryTerms, text: str, *, aliases: tuple[str, ...] = ()) -> tuple[float, frozenset[str]]:
    target = document_terms(text)
    shared = query.concepts & target.concepts
    words = set(query.words) & set(target.words)
    score = 12.0 * len(shared) + 2.0 * len(words)
    normalized = normalize(text)
    for alias in aliases:
        alias = normalize(alias)
        if len(alias) >= 3 and _contains(query.normalized, alias):
            score += 8.0 + min(len(alias), 40) / 4.0
    if query.normalized and query.normalized in normalized:
        score += 30.0
    return score, shared


def match_operation(query: QueryTerms, text: str, *,
                    aliases: tuple[str, ...] = (),
                    phrases: tuple[str, ...] = (),
                    phrase_bonus: float = 0.0) -> MatchEvidence:
    """Return explicit routing evidence without consulting acceptance corpora.

    FTS and word overlap may discover a candidate, but they never compensate
    for a named geometry concept or method that the registered operation does
    not cover.  This distinction lets the planner reject a unique but wrong
    broad-text match (for example Poisson reconstruction routed to smoothing).
    """
    target = document_terms(" ".join((text, *aliases)))
    target_concepts = set(target.concepts)
    if phrases:
        # Authored search phrases describe the same registered operation; the
        # geometric concepts they name count as covered, never as new methods.
        target_concepts |= document_terms(" ".join(phrases)).concepts
    if target_concepts & {"mesh_normals", "point_normals"}:
        target_concepts.add("normals")
    # Kernel-level intersection operations (no mesh/surface/solid operands)
    # carry a "do_intersect" test alias, which parses as surface_intersection and
    # would otherwise hide that they compute intersections.
    if target_concepts & {"self_intersection", "surface_intersection"} and not re.search(
            r"mesh|surface|solid|polyhedr", normalize(text)):
        target_concepts.add("intersection")
    requested = frozenset(query.concepts & PRIMARY_CONCEPTS)
    covered = requested & target_concepts
    uncovered = requested - target_concepts
    if "2d" in query.words and "2d" not in target.words:
        uncovered = frozenset((*uncovered, "dimension_2d"))
    # Mirror of the 2D guard: a query that names 3D must not auto-route with high confidence to an
    # operation whose text declares 2D and never mentions 3D (for example a 3D point set sent to a
    # planar triangulation).
    if "3d" in query.words and "2d" in target.words and "3d" not in target.words:
        uncovered = frozenset((*uncovered, "dimension_3d"))
    requested_methods = requested & METHOD_CONCEPTS
    covered_methods = requested_methods & target_concepts
    uncovered_methods = requested_methods - target_concepts
    words = frozenset(set(query.words) & set(target.words))
    alias_matches = tuple(alias for alias in aliases
                          if len(normalize(alias)) >= 3
                          and _contains(query.normalized, alias))
    score = 14.0 * len(covered) + 3.0 * len(words)
    # Translated Japanese nouns are a weak tie-break, not lexical evidence.
    score += 1.0 * len(set(query.bridge_words) & set(target.words))
    score += sum(10.0 + min(len(normalize(alias)), 40) / 4.0
                 for alias in alias_matches)
    exact_text = normalize(text)
    if query.normalized and query.normalized in exact_text:
        score += 30.0
    score += phrase_bonus
    # Concept-bearing goals require complete semantic coverage.  A query with
    # only distinctive registered words/aliases remains discoverable, but is
    # deliberately medium confidence until the planner sees a clear score gap.
    route_supported = bool(requested and covered) and not uncovered
    if route_supported and score >= 14.0:
        confidence = "high"
    elif not requested and (alias_matches or len(words) >= 2 or phrase_bonus >= 6.0):
        route_supported = True
        confidence = "medium"
    else:
        confidence = "low"
    return MatchEvidence(score, covered, uncovered, covered_methods,
                         uncovered_methods, words, alias_matches,
                         route_supported, confidence)


def enriched_text(text: str) -> str:
    """Append stable bilingual concept aliases for FTS candidate generation."""
    terms = document_terms(text)
    aliases = [alias for concept in sorted(terms.concepts)
               for alias in VOCABULARY[concept]]
    return " ".join((text, *aliases))


def requested_parameter_values(concepts: frozenset[str]) -> dict[str, frozenset[Any]]:
    """Map named methods to parameter values for planner conflict checks."""
    result: dict[str, set[Any]] = {}
    for concept in concepts:
        requirement = METHOD_PARAMETER_REQUIREMENTS.get(concept)
        if requirement is not None:
            parameter, value = requirement
            result.setdefault(parameter, set()).add(value)
    return {parameter: frozenset(values) for parameter, values in result.items()}


def requested_parameter_features(concepts: frozenset[str]) -> dict[str, str]:
    """Return structural parameter requirements implied by the goal."""
    return {parameter: requirement
            for concept in concepts
            for parameter, requirement in [PARAMETER_FEATURE_REQUIREMENTS.get(
                concept, ("", ""))]
            if parameter}


# --- Authored search phrases (data, not code) ---------------------------------
# ``search_data.json`` holds concise bilingual phrases written from each
# operation's own documentation.  They add retrieval evidence only: they never
# change an operation's status, parameters, policies or the registry hash.

# Discovery (capabilities_search) evidence-channel weights.  Fitted by 5-fold
# cross-validation over the pooled development corpus and both authored blind
# sets (scripts/tune_search.py); planning never reads them.
DISCOVERY_WEIGHTS: dict[str, float] = {
    "evidence": 1.0, "phrase": 0.8, "fts": 0.5, "identity": 0.0,
    "coverage": 70.0, "penalty": 6.0,
}

# Fail-closed threshold for discovery.  strength = sum(weight * feature) of the top candidate's
# evidence; below the threshold capabilities_search returns no candidate.  Fitted by
# scripts/tune_search.py abstain (target in-scope false-abstain 2%); see
# docs/master/evidence/search-abstain.json.  Feature units: score, covered primary concepts,
# percent of query IDF mass known to the phrase index, number of query primary concepts.
ABSTAIN: dict[str, Any] = {
    "weights": {"score": 1.0, "covered_concepts": 10.0, "known_mass": 0.3, "query_concepts": 6.0},
    "threshold": 56.52,
}


def abstain_strength(top: dict[str, float] | None, query_concepts: int) -> float:
    if top is None:
        return -math.inf
    w = ABSTAIN["weights"]
    return (w["score"] * top["score"] + w["covered_concepts"] * top["covered_concepts"]
            + w["known_mass"] * 100.0 * (1.0 - top["unknown_share"])
            + w["query_concepts"] * query_concepts)

PHRASE_SCALE = 3.0
PHRASE_CAP = 30.0
_JA_RUN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9f]+")
_JA_PARTICLES = frozenset("のをはがにでともやへ")
_CANON_RULES: tuple[tuple[str, str], ...] = (
    ("ification", "if"), ("ify", "if"), ("ation", "at"), ("ions", ""), ("ion", ""),
)


def _canonical_word(word: str) -> str:
    word = _stem(word)
    for suffix, replacement in _CANON_RULES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            word = word[:-len(suffix)] + replacement
            break
    if word.endswith("e") and len(word) > 5:
        word = word[:-1]
    return word


# Japanese request boilerplate (politeness, desire, auxiliary forms).  It carries
# no geometry, so it is removed before character n-grams are formed; otherwise
# every query would share meaningless grams ("したい", "ください") with nothing.
_JA_BOILERPLATE = re.compile(
    r"(?:してください|して下さい|してほしい|してもらいたい|してもらえ|したいです|したい|たいです|"
    r"お願いします|お願い|ください|下さい|ほしい|欲しい|ですか|でしょうか|ます|です|ません|"
    r"できる|でき|について|において|として|という|ような|ように|による|により|ための|ために|"
    r"から|まで|ので|ながら|しながら|する|した|して|され|さ?れる|いる|ある|ない|もの|こと|など)")
_JA_SPLIT = re.compile("[" + "".join(sorted(_JA_PARTICLES)) + "]")


def _ja_segments(run: str) -> list[str]:
    """Content segments of one Japanese run: boilerplate and particles removed."""
    cleaned = _JA_BOILERPLATE.sub(" ", run)
    return [part for part in _JA_SPLIT.sub(" ", cleaned).split() if part]


@lru_cache(maxsize=8192)
def retrieval_tokens(text: str) -> frozenset[str]:
    """English canonical words plus Japanese character bigrams of one text."""
    normalized = normalize(text)
    tokens: set[str] = set()
    for word in re.findall(r"[a-z][a-z0-9]*|[23]d", normalized):
        if word not in STOP_WORDS and (len(word) >= 3 or word in {"2d", "3d"}):
            tokens.add(_canonical_word(word))
    for run in _JA_RUN.findall(normalized):
        for segment in _ja_segments(run):
            if len(segment) == 1:
                if not "぀" <= segment <= "ゟ":
                    tokens.add("ja:" + segment)
                continue
            for index in range(len(segment) - 1):
                tokens.add("ja:" + segment[index:index + 2])
    return frozenset(tokens)


class PhraseIndex:
    """IDF-weighted phrase evidence over every operation's authored phrases."""

    def __init__(self, phrases_by_operation: dict[str, tuple[str, ...]],
                 context_by_operation: dict[str, str] | None = None):
        self.phrases = {key: tuple(value) for key, value in phrases_by_operation.items()}
        self._tokens = {key: tuple(retrieval_tokens(phrase) for phrase in value)
                        for key, value in self.phrases.items()}
        documents: dict[str, frozenset[str]] = {}
        for key in set(self.phrases) | set(context_by_operation or {}):
            merged: set[str] = set()
            for tokens in self._tokens.get(key, ()):
                merged |= tokens
            if context_by_operation and key in context_by_operation:
                merged |= retrieval_tokens(context_by_operation[key])
            documents[key] = frozenset(merged)
        self._documents = documents
        frequency: dict[str, int] = {}
        for tokens in documents.values():
            for token in tokens:
                frequency[token] = frequency.get(token, 0) + 1
        total = max(len(documents), 1)
        self._idf = {token: math.log((total + 1) / (count + 0.5))
                     for token, count in frequency.items()}
        self._default_idf = math.log(total + 1)

    def weight(self, token: str) -> float:
        return self._idf.get(token, self._default_idf)

    def query_tokens(self, query_text: str, extra_tokens: Iterable[str] = ()) -> frozenset[str]:
        return retrieval_tokens(query_text) | frozenset(
            _canonical_word(word) for word in extra_tokens)

    def query_weight(self, query_tokens: frozenset[str]) -> float:
        return sum(self.weight(token) for token in query_tokens)

    def unknown_share(self, query_tokens: frozenset[str]) -> float:
        """Share of the query's IDF mass carried by tokens no operation document contains."""
        total = self.query_weight(query_tokens)
        if total <= 0:
            return 1.0
        return sum(self.weight(token) for token in query_tokens
                   if token not in self._idf) / total

    def document_overlap(self, operation_id: str, query_tokens: frozenset[str]) -> float:
        """IDF mass of the query tokens that the operation's whole search document shares."""
        document = self._documents.get(operation_id)
        if not document:
            return 0.0
        return sum(self.weight(token) for token in query_tokens & document)

    def bonus(self, operation_id: str, query_text: str,
              extra_tokens: Iterable[str] = (),
              query_tokens: frozenset[str] | None = None) -> float:
        tokens_by_phrase = self._tokens.get(operation_id)
        if not tokens_by_phrase:
            return 0.0
        if query_tokens is None:
            query_tokens = self.query_tokens(query_text, extra_tokens)
        credits: list[float] = []
        for tokens in tokens_by_phrase:
            if not tokens:
                continue
            total = sum(self.weight(token) for token in tokens)
            matched = sum(self.weight(token) for token in tokens & query_tokens)
            if total <= 0 or matched < 2.0:
                continue
            # Rare shared tokens carry the evidence; precision (coverage of the
            # phrase) scales it so that long generic phrases do not dominate.
            credits.append(PHRASE_SCALE * min(matched, 8.0) * (0.5 + 0.5 * matched / total))
        if not credits:
            return 0.0
        credits.sort(reverse=True)
        return min(PHRASE_CAP, credits[0] + 0.3 * sum(credits[1:3]))
