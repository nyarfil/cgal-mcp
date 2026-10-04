"""Deterministic bilingual geometry vocabulary for retrieval, never execution.

The vocabulary describes geometric concepts, not acceptance-query strings or
Operation IDs.  It can enrich registered aliases and pinned reference records;
it cannot make an unregistered capability executable.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


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
    "convex_decomposition": ("convex decomposition", "凸分解", "凸部分に分割"),
    "simplification": ("simplify", "simplification", "decimation", "decimate",
                       "simplified", "edge collapse", "edge decimation",
                       "軽量化", "軽量メッシュ", "簡略化", "辺縮約", "辺を縮約",
                       "ポリゴンを減", "面数を減", "辺数を減"),
    "repair": ("repair", "修復", "修正", "穴埋め", "hole filling", "fill holes"),
    "non_manifold_repair": ("repair non manifold", "repair non-manifold",
                            "non-manifold neighborhoods", "non manifold neighborhoods",
                            "manifold-compatible components", "非多様体を分離", "非多様体修復"),
    "clipping": ("clip the surface", "clipping plane", "clip mesh", "cut-boundary",
                 "mesh clipping", "メッシュをクリップ", "切断面"),
    "remeshing": ("remesh", "remeshing", "リメッシュ", "再メッシュ", "再メッシュ化"),
    "boolean": ("boolean", "ブーリアン", "集合演算", "solid set operation"),
    "union": ("union", "unite", "merge solids", "combine solids", "和集合", "合体", "結合"),
    "intersection": ("intersection", "intersect", "overlap volume", "overlapping volume", "common volume",
                     "交差", "共通部分", "積集合", "重なった体積"),
    "difference": ("difference", "subtract", "cut away", "carve out", "差集合", "引き算", "くり抜"),
    "self_intersection": ("self intersection", "self-intersection", "self intersecting",
                          "self crossing", "crosses itself", "surface crosses itself",
                          "faces cross", "自己交差", "自分自身と交差", "自分自身を貫"),
    "connected_components": ("connected component", "connected components",
                             "連結成分", "分離した成分", "disconnected pieces",
                             "separate shells", "separate pieces", "分離した殻"),
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
                  "健全性", "検査", "閉鎖性", "水密", "watertight", "manifold", "多様体"),
    "validation": ("validate", "validation", "validator", "verify the result",
                   "check the result", "検証", "結果を確かめ"),
    "distance": ("distance", "distances", "距離", "hausdorff", "ハウスドルフ"),
    "aabb": ("aabb", "bounding box", "bounding boxes", "境界ボックス", "包囲箱"),
    "nearest_neighbor": ("nearest neighbor", "nearest neighbour", "nearest-neighbor",
                         "nearest point", "closest point", "nearest point on mesh",
                         "近傍検索", "最近傍", "最近点", "kd tree", "kd-tree", "kdtree"),
    "range_search": ("range search", "radius search", "within radius", "inside radius",
                     "fuzzy sphere", "sphere range", "範囲検索", "半径検索", "半径内"),
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
    "registration": ("registration", "icp", "位置合わせ", "位置合せ", "位置合わ"),
    "reconstruction": ("reconstruct", "reconstruction", "surface from points", "再構成", "再構築", "復元"),
    "poisson": ("poisson", "ポアソン"),
    "advancing_front": ("advancing front", "advancing-front", "前進法"),
    "polygon": ("polygon", "polygons", "多角形", "ポリゴン", "輪郭"),
    "arrangement": ("arrangement", "アレンジメント", "曲線配置"),
    "overlay": ("overlay", "オーバーレイ"),
    "straight_skeleton": ("straight skeleton", "ストレートスケルトン", "直線骨格"),
    "offset": ("offset", "オフセット", "等距離輪郭"),
    "minkowski": ("minkowski", "ミンコフスキー"),
    "triangulation": ("triangulate", "triangulation", "三角形分割", "三角形化", "四面体分割"),
    "delaunay": ("delaunay", "ドロネー"),
    "voronoi": ("voronoi", "ボロノイ"),
    "alpha_shape": ("alpha shape", "alpha shapes", "alpha-shape", "アルファ形状"),
    "alpha_wrap": ("alpha wrap", "alpha wrapping", "アルファラップ", "アルファラッピング"),
    "bounding_volume": ("bounding volume", "bounding sphere", "包囲体", "包囲球", "最小球"),
    "volume_meshing": ("volume mesh", "volume meshing", "tetrahedral mesh",
                       "体積メッシュ", "四面体メッシュ"),
    "surface_meshing": ("surface meshing", "surface mesh generation", "曲面メッシュ生成"),
    "segmentation": ("segmentation", "segmenting", "segment the shape",
                     "shape diameter field", "セグメンテーション", "領域分割"),
    "skeleton": ("skeleton", "skeletonization", "骨格", "スケルトン"),
    "shortest_path": ("shortest path", "geodesic", "最短経路", "測地線"),
    "parameterization": ("parameterization", "parametrization", "パラメータ化", "パラメタ化", "uv展開"),
    "subdivision": ("subdivision", "細分割", "サブディビジョン"),
    "barycentric": ("barycentric", "重心座標"),
    "optimization": ("optimization", "optimisation", "最適化", "二次計画", "線形計画"),
    "interpolation": ("interpolation", "補間"),
    "approximation": ("approximation", "approximate", "近似"),
    "predicates": ("predicate", "predicates", "述語", "頑健な判定"),
    "constructions": ("construction", "constructions", "作図", "幾何構成"),
    "kernel": ("kernel", "kernels", "カーネル", "正確な演算"),
    "protected_edges": ("protected edges", "edge constraints", "retain protected geometry",
                        "保護辺", "拘束辺"),
    "external_envelope": ("strict geometric envelope", "external envelope",
                          "external geometric envelope",
                          "mesh and an envelope", "幾何包絡", "包絡外へ出る"),
    "bounded_normal_change": ("bounded normal rotation", "allowed normal change",
                              "bounded normal change", "法線変化を制限", "法線回転を制限"),
    "fast_envelope": ("fast envelope", "fast-envelopes", "fast envelopes"),
    "dimension_2d": ("2d",),
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

METHOD_PARAMETER_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "pca": ("method", "pca"),
    "jet": ("method", "jet"),
    "union": ("operation", "union"),
    "intersection": ("operation", "intersection"),
    "difference": ("operation", "difference"),
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


@dataclass(frozen=True)
class QueryTerms:
    normalized: str
    words: tuple[str, ...]
    concepts: frozenset[str]
    phrases: tuple[str, ...]


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


def parse_query(text: str) -> QueryTerms:
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
    explicit_mesh_normal = any(_contains(normalized, phrase) for phrase in (
        "face normals", "vertex normals", "corner normals", "mesh normals",
        "頂点法線", "コーナー法線", "メッシュ法線"))
    # Japanese substring matching is intentional for ordinary domain phrases,
    # but ``表面法線`` (surface normal) contains ``面法線`` (face normal).
    # In point-cloud context the former means an estimated point normal; only
    # the standalone face-normal expression requests a mesh entity.
    explicit_mesh_normal = explicit_mesh_normal or (
        "面法線" in normalized and "表面法線" not in normalized)
    if ("point cloud" in normalized or "点群" in normalized) and not explicit_mesh_normal:
        if concepts & {"normals", "mesh_normals", "point_normals"}:
            concepts.discard("mesh_normals")
            concepts.add("point_normals")
    concepts = frozenset(concepts)
    words = tuple(dict.fromkeys(_stem(word) for word in re.findall(r"[a-z][a-z0-9]*|[23]d", normalized)
                                if word not in STOP_WORDS and (len(word) >= 3 or word in {"2d", "3d"})))
    phrases = tuple(dict.fromkeys(phrase for _, phrase in sorted(retained, key=lambda item: (-len(item[1]), item[1]))))
    return QueryTerms(normalized, words, concepts, phrases)


def document_terms(text: str) -> QueryTerms:
    return parse_query(text.replace(".", " ").replace("/", " ").replace("-", " "))


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
                    aliases: tuple[str, ...] = ()) -> MatchEvidence:
    """Return explicit routing evidence without consulting acceptance corpora.

    FTS and word overlap may discover a candidate, but they never compensate
    for a named geometry concept or method that the registered operation does
    not cover.  This distinction lets the planner reject a unique but wrong
    broad-text match (for example Poisson reconstruction routed to smoothing).
    """
    target = document_terms(" ".join((text, *aliases)))
    target_concepts = set(target.concepts)
    if target_concepts & {"mesh_normals", "point_normals"}:
        target_concepts.add("normals")
    requested = frozenset(query.concepts & PRIMARY_CONCEPTS)
    covered = requested & target_concepts
    uncovered = requested - target_concepts
    if "2d" in query.words and "2d" not in target.words:
        uncovered = frozenset((*uncovered, "dimension_2d"))
    requested_methods = requested & METHOD_CONCEPTS
    covered_methods = requested_methods & target_concepts
    uncovered_methods = requested_methods - target_concepts
    words = frozenset(set(query.words) & set(target.words))
    alias_matches = tuple(alias for alias in aliases
                          if len(normalize(alias)) >= 3
                          and _contains(query.normalized, alias))
    score = 14.0 * len(covered) + 3.0 * len(words)
    score += sum(10.0 + min(len(normalize(alias)), 40) / 4.0
                 for alias in alias_matches)
    exact_text = normalize(text)
    if query.normalized and query.normalized in exact_text:
        score += 30.0
    # Concept-bearing goals require complete semantic coverage.  A query with
    # only distinctive registered words/aliases remains discoverable, but is
    # deliberately medium confidence until the planner sees a clear score gap.
    route_supported = bool(requested and covered) and not uncovered
    if route_supported and score >= 14.0:
        confidence = "high"
    elif not requested and (alias_matches or len(words) >= 2):
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


def requested_parameter_values(concepts: frozenset[str]) -> dict[str, frozenset[str]]:
    """Map named methods to parameter values for planner conflict checks."""
    result: dict[str, set[str]] = {}
    for concept in concepts:
        requirement = METHOD_PARAMETER_REQUIREMENTS.get(concept)
        if requirement is not None:
            parameter, value = requirement
            result.setdefault(parameter, set()).add(value)
    return {parameter: frozenset(values) for parameter, values in result.items()}
