"""Bilingual reference vocabulary describing what selected CGAL packages do.

The pinned package catalog records only a package id, its official title and a
few header identifiers, which is too little text to discover a package from a
natural-language geometry task (for example a Japanese request for ray
shooting never mentions "AABB tree").  Each entry below lists generic domain
terms for the package's documented capability (from the CGAL 6.2.1 package
overviews).  Entries are descriptive vocabulary only: they are used to rank
non-executable reference results and can never make an operation executable.
They intentionally contain no acceptance-corpus sentences or Operation IDs.
"""
from __future__ import annotations

import re
import unicodedata

PACKAGE_REFERENCE_TERMS: dict[str, tuple[str, ...]] = {
    "Kernel_23": (
        "primitive", "geometric primitives", "point", "segment", "ray", "line", "plane",
        "sphere", "triangle", "tetrahedron", "incidence", "intersection", "squared distance",
        "predicate", "robust predicate", "bounding box", "oriented bounding", "affine transformation",
        "プリミティブ", "線分", "半直線", "直線", "平面", "三角形", "四面体", "接続関係", "交差",
        "二乗距離", "ユークリッド距離", "述語", "境界箱", "有向境界箱", "アフィン変換", "幾何プリミティブ"),
    "AABB_tree": (
        "ray shooting", "first hit", "first intersection", "acceleration structure",
        "bounding volume hierarchy", "axis-aligned bounding box tree", "intersection query",
        "closest point query", "broad phase", "collision candidate", "broad-phase", "candidate pairs", "probe ray", "ray cast",
        "加速構造", "レイ", "光線", "最初の交点", "広域判定", "交差候補", "最近点", "衝突候補",
        "バウンディングボリューム階層", "射線"),
    "Polygon_mesh_processing": (
        "locate", "closest mesh faces", "query points near", "face ids", "最近傍面", "面id", "位置特定",
        "mesh validity", "mesh health", "mesh inspection", "closed mesh", "manifold", "orientation",
        "point location", "locate point", "containing face", "nearest face", "barycentric coordinates",
        "face normals", "vertex normals", "surface area", "volume", "self intersection",
        "connected components", "sharp edges", "mesh distance", "hausdorff",
        "健全性", "妥当性", "閉性", "多様体", "照会点", "包含面", "最近傍面", "重心座標", "面法線",
        "頂点法線", "面積", "体積", "自己交差", "連結成分", "鋭い辺", "メッシュ検査"),
    "PMP_Mesh_repair": (
        "mesh repair", "repair", "hole filling", "fill holes", "fill hole", "hole", "stitch borders",
        "non-manifold", "nonmanifold", "duplicate vertices", "degenerate faces", "polygon soup",
        "orient polygon soup", "isolate singular vertices", "manifold components",
        "修復", "穴", "穴埋め", "縫合", "非多様体", "重複頂点", "退化", "ポリゴンスープ", "多様体互換"),
    "PMP_Boolean_operations": (
        "split faces", "cutter", "cutter mesh", "intersecting mesh", "contour polyline", "section contour", "輪郭ポリライン", "断面平面", "複数断面", "カッター",
        "boolean", "union", "difference", "intersection volume", "clipping", "clip", "cut plane",
        "slice", "slicing", "cross section", "section plane", "corefinement", "co-refinement",
        "split mesh", "cut mesh",
        "ブーリアン", "和集合", "差集合", "積集合", "クリップ", "切り詰め", "切断", "スライス", "断面",
        "共細分", "切断面"),
    "PMP_Remeshing": (
        "non-triangular faces", "triangulate every", "vertex smoothing", "protected features", "mesh quality optimization", "平滑化して最適化", "高品質メッシュ", "保護特徴", "特徴辺", "頂点位置",
        "remesh", "remeshing", "isotropic remeshing", "triangulate faces", "triangulate polygon faces",
        "triangulate non-triangular faces", "refine", "subdivide", "adaptive density", "graded mesh",
        "target edge length", "edge length field", "curvature adaptive", "local sizing", "mesh refinement",
        "リメッシュ", "再メッシュ", "非三角形面", "各面を三角形分割", "細分", "目標辺長", "辺長",
        "曲率", "要素密度", "局所解像度", "段階的メッシュ", "適応"),
    "Point_set_processing_3": (
        "point set", "point cloud", "normal estimation", "normal orientation", "oriented points",
        "outlier removal", "point simplification", "point smoothing", "reconstruction prerequisites",
        "preprocessing", "normalize point set",
        "点群", "法線推定", "法線の向き", "向き付き点群", "外れ値", "平滑化", "再構成の前提",
        "前処理", "正規化"),
    "Spatial_searching": (
        "kd tree", "spatial tree", "balanced tree", "nearest neighbor", "k nearest", "range search",
        "orthogonal range", "fuzzy sphere", "spatial index", "neighbor query",
        "空間木", "平衡空間木", "近傍点", "近傍検索", "最近傍", "範囲検索", "領域内の点", "索引化"),
    "Bounding_volumes": (
        "bounding volume", "bounding sphere", "minimum enclosing sphere", "smallest enclosing ellipsoid",
        "minimum enclosing ellipse", "enclosing box", "min sphere", "min ellipse",
        "境界体積", "包囲体", "包囲球", "最小包含球", "最小包囲球", "楕円体", "楕円", "包含箱"),
    "Mesh_3": (
        "tetrahedral mesh", "tetrahedral volume mesh", "volume mesh", "3d mesh generation", "subdomain",
        "subdomain label", "feature curve", "feature curves", "cell quality", "facet quality",
        "sizing criteria", "labeled domain", "mesh domain",
        "四面体", "ボリュームメッシュ", "体積メッシュ", "部分領域", "特徴曲線", "セル", "品質条件",
        "メッシュ生成領域"),
    "Mesh_2": (
        "2d mesh generation", "constrained delaunay mesh", "triangle mesh generation", "angle bound",
        "size bound", "planar region mesh", "quality mesh", "bounded planar domain",
        "2dメッシュ", "平面領域", "角度境界", "サイズ境界", "品質保証", "三角形メッシュ生成"),
    "Matrix_search": (
        "matrix search", "monotone matrix", "totally monotone", "row maxima", "extremal element",
        "feasible extremum", "selection index", "geometric matrix search",
        "行列探索", "単調行列", "単調性", "極値", "比較履歴", "選択インデックス"),
    "Convex_decomposition_3": (
        "convex decomposition", "convex parts", "approximately convex", "concave", "convex components",
        "凸成分", "凹形状", "近似凸部品", "凸分解", "凸部品"),
    "Surface_mesh_parameterization": (
        "parameterize", "parameterization", "parametrization", "texture coordinates", "disk-like", "distortion", "planar domain",
        "パラメータ化", "テクスチャ座標", "歪み", "円盤状", "平面領域へ"),
    "Alpha_wrap_3": (
        "alpha wrap", "wrap", "wrapping", "offset", "gap", "watertight envelope",
        "包む", "包絡", "隙間", "オフセット", "アルファラップ"),
    "Surface_mesher": (
        "implicit surface", "parametric surface", "conforming surface mesh", "approximation guarantee", "surface domain",
        "陰関数", "パラメトリック表面", "適合する表面メッシュ", "近似保証", "表面領域"),
    "QP_solver": (
        "quadratic program", "linear program", "constraints", "optimization problem", "feasibility", "optimal value",
        "二次制約", "線形制約", "最適化問題", "実行可能性", "最適値", "二次計画", "線形計画"),
}


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().replace("_", " ").split())


_NORMALIZED = {package: tuple(dict.fromkeys(_normalize(term) for term in terms))
               for package, terms in PACKAGE_REFERENCE_TERMS.items()}
_PATTERNS = {term: re.compile(r"(?<![a-z0-9])" + re.escape(term) + r"s?(?![a-z0-9])")
             for terms in _NORMALIZED.values() for term in terms if term.isascii()}


def package_reference_score(normalized_query: str, package: str) -> float:
    """Score non-executable package relevance from distinct matched terms."""
    matched = 0
    for term in _NORMALIZED.get(package, ()):
        if len(term) < 2:
            continue
        pattern = _PATTERNS.get(term)
        found = (pattern.search(normalized_query) is not None if pattern is not None
                 else term in normalized_query)
        matched += found
    return min(matched, 8) * 9.0
