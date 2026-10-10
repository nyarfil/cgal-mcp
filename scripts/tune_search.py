"""Cross-validated tuning and calibration of the discovery search (retrieval only).

Two modes, both deterministic and read-only with respect to the registry:

``weights``  fit the discovery evidence-channel weights (search.DISCOVERY_WEIGHTS) over
             the pooled development corpus (300) and both authored blind sets (118+140),
             report 5-fold (3 seeds) and leave-one-set-out numbers, and write
             docs/master/evidence/search-cv.json.
``abstain``  fit the evidence-strength threshold that makes capabilities_search return no
             candidate for out-of-scope queries, report cross-validated abstain /
             false-abstain rates per category, and write
             docs/master/evidence/search-abstain.json.

Honesty note recorded in both outputs: the pooled queries are development data.  The
lexicon, phrase and tokenization changes were designed after reading development misses,
so these numbers do not estimate performance on an untouched blind set.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from cgal_mcp.master.registry import OperationRegistry  # noqa: E402
from cgal_mcp.master import search as search_module  # noqa: E402

CORPUS = REPO / "tests" / "fixtures" / "master" / "search_intents.json"
BLIND = [("blind1", REPO / "docs" / "master" / "search_blind_set.json"),
         ("blind2", REPO / "docs" / "master" / "search_blind_set_2.json")]
PROBES = REPO / "docs" / "master" / "search_out_of_scope_probes.json"
CV_EVIDENCE = REPO / "docs" / "master" / "evidence" / "search-cv.json"
ABSTAIN_EVIDENCE = REPO / "docs" / "master" / "evidence" / "search-abstain.json"
WEIGHT_GRID = {
    "evidence": [0.5, 0.7, 1.0, 1.3], "phrase": [0.2, 0.4, 0.6, 0.8, 1.0, 1.3],
    "fts": [0.0, 0.5, 1.0], "identity": [0.0, 0.5, 1.0],
    "coverage": [0.0, 20.0, 30.0, 45.0, 70.0, 100.0, 150.0],
    "penalty": [0.0, 1.0, 2.0, 3.0, 4.0, 6.0],
}
CHANNELS = ("evidence", "phrase", "fts", "identity", "coverage")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_queries() -> list[dict]:
    requirements = json.loads((REPO / "catalog" / "major_requirements.json").read_text(encoding="utf-8"))
    bound = {r["id"]: set(r["operation_ids"]) for f in requirements["families"] for r in f["requirements"]}
    rows = [{"set": "corpus", "id": i["id"], "query": i["query"], "language": i["language"],
             "expected": bound[i["requirement_ids"][0]]}
            for i in json.loads(CORPUS.read_text(encoding="utf-8"))["intents"]]
    for name, path in BLIND:
        rows += [{"set": name, "id": i["id"], "query": i["query"], "language": i["language"],
                  "expected": set(i["expected_operations"])}
                 for i in json.loads(path.read_text(encoding="utf-8"))["intents"]]
    return rows


def load_probes() -> list[dict]:
    rows = [{"id": p["id"], "query": p["query"], "category": p["category"], "language": p["language"]}
            for p in json.loads(PROBES.read_text(encoding="utf-8"))["probes"]]
    blind2 = json.loads(BLIND[1][1].read_text(encoding="utf-8"))
    rows += [{"id": p["id"], "query": p["query"], "category": "blind2_oos", "language": p["language"]}
             for p in blind2["out_of_scope_intents"]]
    return rows


class Pool:
    """Per-query channel matrices over all operations for vectorized re-ranking."""

    def __init__(self, registry: OperationRegistry, rows: list[dict]):
        self.ids = sorted(registry.operations)
        column = {op: i for i, op in enumerate(self.ids)}
        count, width = len(rows), len(self.ids)
        shape = (count, width)
        self.feature = {name: np.zeros(shape) for name in
                        ("evidence", "phrase", "fts", "identity", "coverage", "uncovered", "executable")}
        self.present = np.zeros(shape, bool)
        self.hard = np.zeros(shape, bool)
        self.soft = np.zeros(shape, bool)
        self.expected = np.zeros(shape, bool)
        self.sets = np.array([r["set"] for r in rows])
        for q, row in enumerate(rows):
            result = registry.search(row["query"], limit=100, discovery=True, explain=True)
            for candidate in result["candidates"]:
                c, ch = column[candidate["operation_id"]], candidate["channels"]
                self.present[q, c] = True
                self.feature["evidence"][q, c] = ch["evidence_rest"]
                self.feature["phrase"][q, c] = ch["phrase_bonus"]
                self.feature["fts"][q, c] = ch["fts"]
                self.feature["identity"][q, c] = ch["identity"]
                self.feature["coverage"][q, c] = ch["coverage"]
                self.feature["uncovered"][q, c] = ch["uncovered"]
                self.feature["executable"][q, c] = ch["executable"]
                self.hard[q, c] = ch["hard"]
                self.soft[q, c] = (not candidate["route_supported"]) and not ch["hard"]
            for op in row["expected"]:
                if op in column:
                    self.expected[q, column[op]] = True

    def top3(self, weights: dict[str, float], rows: np.ndarray | None = None) -> np.ndarray:
        sel = slice(None) if rows is None else rows
        score = sum(weights[name] * self.feature[name][sel] for name in CHANNELS) + self.feature["executable"][sel]
        score = score - weights["penalty"] * self.feature["uncovered"][sel] * self.soft[sel]
        score = np.where(self.hard[sel], score - 1e6, score)
        score = np.where(self.present[sel], score, -1e12)
        return np.argsort(-score, axis=1, kind="stable")[:, :3]

    def hits(self, weights: dict[str, float], rows: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        order = self.top3(weights, rows)
        expected = self.expected if rows is None else self.expected[rows]
        picked = np.take_along_axis(expected, order, axis=1)
        return picked[:, 0], picked.any(axis=1)


def objective(pool: Pool, weights: dict[str, float], rows: np.ndarray) -> float:
    top1, top3 = pool.hits(weights, rows)
    return float(top3.mean() + 0.5 * top1.mean())


def fit(pool: Pool, rows: np.ndarray, start: dict[str, float]) -> dict[str, float]:
    weights = dict(start)
    best = objective(pool, weights, rows)
    for _ in range(2):
        for name, values in WEIGHT_GRID.items():
            for value in values:
                trial = {**weights, name: value}
                score = objective(pool, trial, rows)
                if score > best + 1e-12:
                    best, weights = score, trial
    return weights


def summarize(pool: Pool, weights_by_row: dict[int, dict[str, float]], sets: np.ndarray) -> dict:
    result = {}
    for name in ["corpus", "blind1", "blind2", "pooled"]:
        index = [i for i in weights_by_row if name == "pooled" or sets[i] == name]
        if not index:
            continue
        top1 = top3 = 0
        for i in index:
            a, b = pool.hits(weights_by_row[i], np.array([i]))
            top1 += int(a[0])
            top3 += int(b[0])
        result[name] = {"count": len(index), "top1_pct": round(100 * top1 / len(index), 2),
                        "top3_pct": round(100 * top3 / len(index), 2)}
    return result


def run_weights() -> dict:
    registry = OperationRegistry()
    rows = load_queries()
    pool = Pool(registry, rows)
    every = np.arange(len(rows))
    current = dict(search_module.DISCOVERY_WEIGHTS)
    report = {"schema_version": 1, "generator": "tune-search-weights",
              "generator_sha256": sha(Path(__file__)),
              "search_py_sha256": sha(REPO / "cgal_mcp" / "master" / "search.py"),
              "search_data_sha256": sha(REPO / "cgal_mcp" / "master" / "search_data.json"),
              "operations_sha256": sha(REPO / "cgal_mcp" / "master" / "operations.json"),
              "pooled_counts": {n: int((pool.sets == n).sum()) for n in ("corpus", "blind1", "blind2")},
              "objective": "top3 + 0.5 * top1, coordinate descent over WEIGHT_GRID, 2 passes",
              "honesty": ("All pooled queries are development data. Lexicon, phrase and tokenization "
                          "changes were designed after reading development misses (including blind sets 1 "
                          "and 2). Cross-validation here covers only the 6 channel weights."),
              "weight_grid": WEIGHT_GRID, "production_weights": current}
    report["production_weights_in_sample"] = summarize(pool, {i: current for i in every}, pool.sets)
    fitted = fit(pool, every, current)
    report["fit_all_weights"] = fitted
    report["fit_all_in_sample"] = summarize(pool, {i: fitted for i in every}, pool.sets)
    folds = {}
    for seed in (11, 12, 13):
        order = list(every)
        random.Random(seed).shuffle(order)
        per_row: dict[int, dict] = {}
        for k in range(5):
            test = np.array(sorted(order[k::5]))
            train = np.array(sorted(set(order) - set(test)))
            weights = fit(pool, train, current)
            for i in test:
                per_row[int(i)] = weights
        folds[f"seed_{seed}"] = summarize(pool, per_row, pool.sets)
    report["five_fold_cv"] = folds
    mean = {name: {"top1_pct": round(float(np.mean([folds[s][name]["top1_pct"] for s in folds])), 2),
                   "top3_pct": round(float(np.mean([folds[s][name]["top3_pct"] for s in folds])), 2)}
            for name in ("corpus", "blind1", "blind2", "pooled")}
    report["five_fold_cv_mean"] = mean
    lodo = {}
    for held in ("corpus", "blind1", "blind2"):
        test = np.where(pool.sets == held)[0]
        train = np.where(pool.sets != held)[0]
        weights = fit(pool, train, current)
        lodo[held] = {"weights": weights,
                      **summarize(pool, {int(i): weights for i in test}, pool.sets)["pooled"]}
    report["leave_one_set_out"] = lodo
    return report


# ----------------------------------------------------------------------------- abstain

def evidence_vector(top: dict | None, concepts: int) -> np.ndarray:
    keys = ("score", "covered_concepts", "known_mass", "phrase_bonus", "coverage",
            "word_matches", "query_concepts")
    if top is None:
        return np.zeros(len(keys))
    return np.array([top["score"], top["covered_concepts"], 100.0 * (1.0 - top["unknown_share"]),
                     top["phrase_bonus"], 100.0 * top["coverage"], top["word_matches"], float(concepts)])


ABSTAIN_GRID = [(1.0, a, b, c, d, e, f)
                for a in (0.0, 5.0, 10.0) for b in (0.0, 0.1, 0.3, 0.6)
                for c in (0.0, 0.3, 0.6) for d in (0.0, 0.3) for e in (0.0, 2.0)
                for f in (0.0, 3.0, 6.0)]


def fit_abstain(features: np.ndarray, is_probe: np.ndarray, rows: np.ndarray,
                false_abstain: float) -> tuple[np.ndarray, float, float]:
    inside = [i for i in rows if not is_probe[i]]
    outside = [i for i in rows if is_probe[i]]
    best = None
    for raw in ABSTAIN_GRID:
        weights = np.array(raw)
        strength = np.sort(features[inside] @ weights)
        threshold = float(strength[int(false_abstain * len(strength))])
        rate = float(np.mean(features[outside] @ weights < threshold))
        if best is None or rate > best[0] + 1e-9:
            best = (rate, weights, threshold)
    return best[1], best[2], best[0]


def run_abstain(false_abstain: float = 0.02) -> dict:
    registry = OperationRegistry()
    queries = load_queries()
    probes = load_probes()
    items = [(q["query"], False, q["set"], q["language"]) for q in queries] + [
        (p["query"], True, p["category"], p["language"]) for p in probes]
    features = np.zeros((len(items), 7))
    for i, (text, _, _, _) in enumerate(items):
        result = registry.search(text, limit=3, discovery=True)
        analysis = result["query_analysis"]
        features[i] = evidence_vector(analysis["top_evidence"], len(analysis["primary_concepts"]))
    is_probe = np.array([item[1] for item in items])
    group = np.array([item[2] for item in items])
    language = np.array([item[3] for item in items])
    every = np.arange(len(items))
    rng = random.Random(21)
    inside = [i for i in every if not is_probe[i]]
    outside = [i for i in every if is_probe[i]]
    rng.shuffle(inside)
    rng.shuffle(outside)
    predicted = np.zeros(len(items), bool)
    for k in range(5):
        test = set(inside[k::5] + outside[k::5])
        train = np.array([i for i in every if i not in test])
        weights, threshold, _ = fit_abstain(features, is_probe, train, false_abstain)
        for i in test:
            predicted[i] = features[i] @ weights < threshold
    weights, threshold, train_rate = fit_abstain(features, is_probe, every, false_abstain)
    final = features @ weights < threshold

    def rates(flags: np.ndarray) -> dict:
        categories = sorted(set(group[is_probe]))
        return {"in_scope_false_abstain_pct": round(100 * flags[~is_probe].mean(), 2),
                "in_scope_false_abstain_by_set": {n: round(100 * flags[group == n].mean(), 2)
                                                   for n in ("corpus", "blind1", "blind2")},
                "out_of_scope_abstain_pct": round(100 * flags[is_probe].mean(), 2),
                "out_of_scope_abstain_by_category": {
                    c: {"count": int((is_probe & (group == c)).sum()),
                        "abstain_pct": round(100 * flags[is_probe & (group == c)].mean(), 2)}
                    for c in categories},
                "out_of_scope_abstain_by_language": {
                    lang: round(100 * flags[is_probe & (language == lang)].mean(), 2)
                    for lang in ("en", "ja")}}
    return {"schema_version": 1, "generator": "tune-search-abstain",
            "generator_sha256": sha(Path(__file__)),
            "search_py_sha256": sha(REPO / "cgal_mcp" / "master" / "search.py"),
            "search_data_sha256": sha(REPO / "cgal_mcp" / "master" / "search_data.json"),
            "probes_sha256": sha(PROBES),
            "target_false_abstain": false_abstain,
            "in_scope_queries": int((~is_probe).sum()), "out_of_scope_probes": int(is_probe.sum()),
            "feature_order": ["score", "covered_concepts", "known_mass", "phrase_bonus",
                              "coverage", "word_matches", "query_concepts"],
            "fit_all": {"weights": [float(x) for x in weights], "threshold": round(threshold, 4),
                        "train_out_of_scope_abstain_pct": round(100 * train_rate, 2)},
            "five_fold_cv": rates(predicted), "fit_all_in_sample": rates(final),
            "honesty": ("The probes are a development set authored before any score was viewed; "
                        "the 5-fold figures refit weights and threshold on the training folds only. "
                        "Unsupported-CGAL probes that name a supported family's neighbour are the "
                        "hard case and are reported separately.")}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "weights"
    if mode == "weights":
        out = run_weights()
        if "--publish" in sys.argv:
            CV_EVIDENCE.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    elif mode == "abstain":
        out = run_abstain()
        if "--publish" in sys.argv:
            ABSTAIN_EVIDENCE.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    else:
        raise SystemExit("usage: tune_search.py weights|abstain [--publish]")
    print(json.dumps(out, ensure_ascii=False, indent=1))
