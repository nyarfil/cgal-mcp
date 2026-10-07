"""Deterministic search and goal-routing acceptance for CGAL Master.

Natural-language retrieval, exact-name package discovery, and explicit planner
policy gates are measured separately. Production goal routing is exercised with
typed synthetic artifacts, while execution remains deliberately UNMEASURED.
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import json
import re
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
CORPUS_PATH = REPO / "tests" / "fixtures" / "master" / "search_intents.json"
PACKAGE_SMOKE_PATH = REPO / "tests" / "fixtures" / "master" / "package_discovery_cases.json"
TEST_SOURCE_PATH = REPO / "tests" / "test_master_search_acceptance.py"
OPERATIONS_PATH = REPO / "cgal_mcp" / "master" / "operations.json"
PACKAGES_PATH = REPO / "catalog" / "packages.json"
REQUIREMENTS_PATH = REPO / "catalog" / "major_requirements.json"
INVENTORY_PATH = REPO / "catalog" / "major_capability_inventory.json"
EXECUTABLE = frozenset({"IMPLEMENTED", "VALIDATED"})
LANGUAGES = frozenset({"ja", "en"})
EXECUTION_EXPECTATIONS = frozenset({"eligible", "documentation_only"})
KNOWN_INPUT_TYPES = frozenset({
    "PointSet3", "PointSet3Normals", "PolygonSoup3", "TriangleSurfaceMesh"})
SIMPLIFICATION_REQUIREMENTS = frozenset(
    {f"major.7.7.{index:02d}" for index in range(1, 7)} | {"major.7.9.04"})
MAX_STRUCTURAL_SKELETON_REUSE = 12
MAX_OPENING_REUSE = 6
MAX_NEAR_DUPLICATE_RATIO = 0.94
_BANNED_SCAFFOLDS = (
    re.compile(r"に相当する幾何処理を行うこと"),
    re.compile(r"(?:locate|find) (?:a|the) suitable method for (?:this|the) geometry task", re.I),
    re.compile(r"which supported capability best fits", re.I),
)


def _query_skeleton(query: str, language: str) -> str:
    """Keep sentence structure while replacing task-specific content."""
    if language == "en":
        structural = {
            "a", "an", "and", "as", "at", "by", "for", "from", "given", "i", "in",
            "into", "is", "it", "need", "of", "on", "please", "so", "that", "the",
            "then", "this", "to", "use", "using", "want", "with", "without",
        }
        tokens = re.findall(r"[a-z]+", query.casefold())
        mapped = [token if token in structural else "¤" for token in tokens]
    else:
        tokens = re.findall(
            r"として|について|から|まで|によって|に対して|へ|を|に|が|は|と|で|し|して|した|する|"
            r"してください|ほしい|欲しい|たい|必要|入力|出力|結果|です|ます|。|、",
            query,
        )
        mapped = tokens
    collapsed: list[str] = []
    for token in mapped:
        if token != "¤" or not collapsed or collapsed[-1] != "¤":
            collapsed.append(token)
    return "|".join(collapsed)


def _near_duplicate_pairs(intents: list[dict[str, Any]]) -> list[tuple[str, str, float]]:
    normalized = []
    for intent in intents:
        query = re.sub(r"[^a-z0-9\u3040-\u30ff\u3400-\u9fff]+", " ",
                       str(intent.get("query", "")).casefold()).strip()
        normalized.append((str(intent.get("id", "")), str(intent.get("language", "")), query))
    pairs = []
    for index, (first_id, language, first) in enumerate(normalized):
        for second_id, second_language, second in normalized[index + 1:]:
            if language != second_language:
                continue
            ratio = SequenceMatcher(None, first, second, autojunk=False).ratio()
            if ratio > MAX_NEAR_DUPLICATE_RATIO:
                pairs.append((first_id, second_id, round(ratio, 4)))
    return pairs


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _requirements(document: dict[str, Any]) -> tuple[set[str], set[str]]:
    families = document.get("families", [])
    return ({family["id"] for family in families},
            {item["id"] for family in families for item in family["requirements"]})


def _requirement_context(requirements: dict[str, Any], inventory: dict[str, Any]) -> tuple[dict[str, str], dict[str, set[str]]]:
    families = {item["id"]: family["id"] for family in requirements["families"]
                for item in family["requirements"]}
    packages = {item["id"]: set(item["package_ids"]) for item in inventory["items"]}
    return families, packages


def _package_ids(document: dict[str, Any]) -> set[str]:
    return {item["id"] for item in document["packages"]}


def _operations(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in document["operations"]}


def _types_match_operation(available: list[str], operation: dict[str, Any]) -> bool:
    specifications = operation.get("io", {}).get("inputs", [])
    if len(available) != len(specifications):
        return False
    def assign(index: int, remaining: list[str]) -> bool:
        if index == len(specifications):
            return not remaining
        for position, kind in enumerate(remaining):
            if kind in specifications[index].get("types", []) and assign(
                    index + 1, remaining[:position] + remaining[position + 1:]):
                return True
        return False
    return assign(0, list(available))


def validate_package_smoke(corpus: Any, package_ids: set[str]) -> list[str]:
    if not isinstance(corpus, dict) or corpus.get("schema_version") != 1:
        return ["Package smoke corpus must be a schema_version 1 object"]
    cases = corpus.get("cases")
    if not isinstance(cases, list):
        return ["Package smoke cases must be an array"]
    errors: list[str] = []
    if len(cases) != len(package_ids):
        errors.append(f"Package smoke must contain {len(package_ids)} cases; found {len(cases)}")
    expected = {case.get("expected_package") for case in cases if isinstance(case, dict)}
    if expected != package_ids:
        errors.append("Package smoke must cover every pinned package exactly once")
    if len({case.get("id") for case in cases if isinstance(case, dict)}) != len(cases):
        errors.append("Package smoke case ids must be unique")
    if any(case.get("query") != case.get("expected_package")
           for case in cases if isinstance(case, dict)):
        errors.append("Package smoke queries must be exact pinned package ids")
    return errors


def validate_corpus(corpus: Any, *, package_ids: set[str], operation_ids: set[str],
                    requirement_ids: set[str], family_ids: set[str],
                    operation_index: dict[str, dict[str, Any]] | None = None,
                    requirement_families: dict[str, str] | None = None,
                    requirement_packages: dict[str, set[str]] | None = None,
                    require_full_count: bool = True) -> list[str]:
    """Validate natural intent quality and faithful catalog bindings."""
    errors: list[str] = []
    if not isinstance(corpus, dict) or corpus.get("schema_version") != 2:
        return ["Corpus must be a schema_version 2 object"]
    intents = corpus.get("intents")
    if not isinstance(intents, list):
        return ["Corpus intents must be an array"]
    if corpus.get("intent_count") != len(intents):
        errors.append("Corpus intent_count must match the intent array")
    if corpus.get("wrong_execution_measurement") != \
            "UNMEASURED_AUTOMATIC_EXECUTION_NOT_INVOKED":
        errors.append("Corpus must preserve the UNMEASURED automatic-execution contract")
    if require_full_count and len(intents) != 300:
        errors.append(f"Corpus must contain exactly 300 intents; found {len(intents)}")
    ids: set[str] = set()
    queries: set[str] = set()
    language_counts: Counter[str] = Counter()
    bound_requirements: set[str] = set()
    covered_families: set[str] = set()
    exact_name_mentions = 0
    simplification_count = 0
    skeleton_counts: Counter[tuple[str, str]] = Counter()
    opening_counts: Counter[tuple[str, str]] = Counter()
    serial_marker = re.compile(r"(?:brief|資料|case)\s*[#番号]?\s*\d+", re.IGNORECASE)
    package_labels = [(package, package.replace("_", " ").casefold()) for package in package_ids]
    for ordinal, intent in enumerate(intents, 1):
        label = f"intent[{ordinal}]"
        if not isinstance(intent, dict):
            errors.append(f"{label} must be an object"); continue
        identifier = intent.get("id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{label} has invalid id")
        elif identifier in ids:
            errors.append(f"Duplicate intent id: {identifier}")
        else:
            ids.add(identifier)
        language = intent.get("language")
        if language not in LANGUAGES:
            errors.append(f"{label} has invalid language: {language!r}")
        else:
            language_counts[language] += 1
        query = intent.get("query")
        if not isinstance(query, str) or len(query.strip()) < 20:
            errors.append(f"{label} query must be a realistic natural-language task")
        else:
            folded = query.casefold()
            if folded in queries:
                errors.append(f"Duplicate query: {query}")
            queries.add(folded)
            if serial_marker.search(query):
                errors.append(f"{label} contains a synthetic serial marker")
            if any(pattern.search(query) for pattern in _BANNED_SCAFFOLDS):
                errors.append(f"{label} contains a banned task scaffold")
            if any(lbl and lbl in folded for _, lbl in package_labels):
                exact_name_mentions += 1
            skeleton_counts[(str(language), _query_skeleton(query, str(language)))] += 1
            if language == "en":
                opening = " ".join(re.findall(r"[a-z]+", folded)[:3])
            else:
                opening = re.sub(r"[\s。、]", "", query)[:6]
            opening_counts[(str(language), opening)] += 1
        family = intent.get("family")
        if family not in family_ids:
            errors.append(f"{label} references unknown family: {family!r}")
        else:
            covered_families.add(family)
        requirements = intent.get("requirement_ids")
        if not isinstance(requirements, list) or not requirements or not all(isinstance(x, str) for x in requirements):
            errors.append(f"{label} needs non-empty requirement_ids"); requirements = []
        unknown_requirements = set(requirements) - requirement_ids
        if unknown_requirements:
            errors.append(f"{label} has unknown requirements: {sorted(unknown_requirements)}")
        bound_requirements.update(requirements)
        if requirement_families:
            mismatched = [rid for rid in requirements if requirement_families.get(rid) != family]
            if mismatched:
                errors.append(f"{label} requirement/family mismatch: {mismatched}")
        sources = intent.get("source_packages")
        expected_packages = intent.get("expected_packages")
        known_source_packages = package_ids
        if requirement_packages:
            known_source_packages = known_source_packages | set().union(
                *requirement_packages.values())
        for field, values, known in (
                ("source_packages", sources, known_source_packages),
                ("expected_packages", expected_packages, package_ids)):
            if not isinstance(values, list) or not values or not all(isinstance(x, str) for x in values):
                errors.append(f"{label} needs non-empty {field}")
            elif set(values) - known:
                errors.append(f"{label} has unknown {field}: {sorted(set(values)-known)}")
        if isinstance(sources, list) and isinstance(expected_packages, list) and not set(expected_packages).issubset(sources):
            errors.append(f"{label} expected_packages must be source_packages")
        if requirement_packages and isinstance(sources, list):
            allowed = set().union(*(requirement_packages.get(rid, set()) for rid in requirements))
            if not set(sources).issubset(allowed):
                errors.append(f"{label} source_packages do not match original requirement evidence")
        expected_execution = intent.get("expected_execution")
        if expected_execution not in EXECUTION_EXPECTATIONS:
            errors.append(f"{label} has invalid expected_execution")
        alternatives = intent.get("expected_operations")
        if not isinstance(alternatives, list) or not all(isinstance(x, str) for x in alternatives):
            errors.append(f"{label} expected_operations must be a string array"); alternatives = []
        elif set(alternatives) - operation_ids:
            errors.append(f"{label} has unknown expected_operations: {sorted(set(alternatives)-operation_ids)}")
        input_types = intent.get("input_types", [])
        if not isinstance(input_types, list) or not all(x in KNOWN_INPUT_TYPES for x in input_types):
            errors.append(f"{label} input_types must use supported synthetic artifact types"); input_types = []
        if expected_execution == "eligible":
            if not alternatives:
                errors.append(f"{label} eligible intent needs expected_operations")
            if not input_types:
                errors.append(f"{label} eligible intent needs input_types")
            if operation_index:
                executable = [operation_index.get(op, {}) for op in alternatives]
                if not any(op.get("status") in EXECUTABLE for op in executable):
                    errors.append(f"{label} eligible operations are not executable")
                if input_types and not any(
                        _types_match_operation(input_types, operation)
                        for operation in executable if operation):
                    errors.append(f"{label} input_types/arity do not match an expected operation")
        elif alternatives:
            errors.append(f"{label} documentation-only intent must not name executable operations")
        routing_probe = intent.get("routing_probe")
        if (not isinstance(routing_probe, dict) or routing_probe.get("status") not in
                {"measured", "unmeasured_input_model"}):
            errors.append(f"{label} needs a routing_probe status")
        elif routing_probe["status"] == "unmeasured_input_model":
            if expected_execution != "documentation_only":
                errors.append(f"{label} eligible intent cannot skip goal routing")
            if not isinstance(routing_probe.get("reason"), str) or not routing_probe["reason"]:
                errors.append(f"{label} unmeasured routing probe needs a reason")
        semantic_simplification = bool(set(requirements) & SIMPLIFICATION_REQUIREMENTS)
        if semantic_simplification:
            simplification_count += 1
        if (intent.get("intent_class") == "simplification") != semantic_simplification:
            errors.append(f"{label} intent_class disagrees with its simplification requirement")
        if not isinstance(intent.get("constraints", {}), dict):
            errors.append(f"{label} constraints must be an object")
        if "planner_rejection" in intent:
            errors.append(f"{label} must not mix planner gates into natural-intent measurement")
    gates = corpus.get("planner_gates")
    if not isinstance(gates, list) or len(gates) < 4:
        errors.append("Corpus needs explicit kernel, dependency, license, and unknown-operation planner gates")
    else:
        kinds = {key for gate in gates if isinstance(gate, dict) for key in gate.get("policy", {})}
        if not {"kernel", "dependencies", "allowed_licenses"}.issubset(kinds):
            errors.append("Planner gates must cover kernel, dependency, and license policies")
        if not any(gate.get("expected_error", {}).get("code") == "unsupported_operation" for gate in gates if isinstance(gate, dict)):
            errors.append("Planner gates need an explicit unknown-operation rejection")
    if simplification_count > 15:
        errors.append(f"Total simplification intents must be <=15; found {simplification_count}")
    if require_full_count:
        if language_counts != Counter({"ja": 150, "en": 150}):
            errors.append(f"Corpus language split must be ja=150,en=150; found {dict(language_counts)}")
        if corpus.get("language_split") != {"ja": 150, "en": 150}:
            errors.append("Corpus language_split metadata must be ja=150,en=150")
        if bound_requirements != requirement_ids:
            errors.append(f"Corpus requirement coverage mismatch; missing={sorted(requirement_ids-bound_requirements)}")
        if covered_families != family_ids:
            errors.append(f"Corpus family coverage mismatch; missing={sorted(family_ids-covered_families)}")
        if exact_name_mentions > len(intents) // 5:
            errors.append(f"At most 20% of natural intents may name exact packages; found {exact_name_mentions}")
        repeated_skeletons = [(language, skeleton, count)
                              for (language, skeleton), count in skeleton_counts.items()
                              if skeleton and count > MAX_STRUCTURAL_SKELETON_REUSE]
        if repeated_skeletons:
            errors.append("Natural intents overuse the same structural skeleton: " +
                          repr(sorted(repeated_skeletons)))
        repeated_openings = [(language, opening, count)
                             for (language, opening), count in opening_counts.items()
                             if opening and count > MAX_OPENING_REUSE]
        if repeated_openings:
            errors.append("Natural intents overuse the same opening: " +
                          repr(sorted(repeated_openings)))
        near_duplicates = _near_duplicate_pairs(intents)
        if near_duplicates:
            errors.append("Natural intents contain near-duplicate tasks: " +
                          repr(near_duplicates[:20]))
    return errors


def _candidate_ids(result: dict[str, Any]) -> list[str]:
    return [item["operation_id"] for item in result.get("candidates", []) if isinstance(item, dict)]


def _empty_bucket() -> dict[str, Any]:
    return {"total": 0, "eligible": 0, "eligible_hits": 0, "eligible_unavailable": 0,
            "documentation_only": 0, "docs_hits": 0, "failures": []}


def _bucket_report(bucket: dict[str, Any]) -> dict[str, Any]:
    report = {key: value for key, value in bucket.items() if key != "failures"}
    report["top3_recall_percent"] = (round(100 * report["eligible_hits"] / report["eligible"], 2)
                                     if report["eligible"] else None)
    report["documentation_recall_percent"] = (round(100 * report["docs_hits"] / report["documentation_only"], 2)
                                                if report["documentation_only"] else None)
    report["failures"] = bucket["failures"]
    return report


def evaluate(corpus: dict[str, Any], *, runtime: Any,
             operation_index: dict[str, dict[str, Any]],
             artifact_ids_by_type: dict[str, str]) -> dict[str, Any]:
    """Measure retrieval only; goal planning is measured separately."""
    by_language: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    by_family: dict[str, dict[str, Any]] = defaultdict(_empty_bucket)
    cases: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    eligible_total = eligible_hits = unavailable = 0
    docs_total = docs_hits = 0
    for intent in corpus["intents"]:
        buckets = (by_language[intent["language"]], by_family[intent["family"]])
        for bucket in buckets: bucket["total"] += 1
        case: dict[str, Any] = {"id": intent["id"], "language": intent["language"],
            "family": intent["family"], "expected_execution": intent["expected_execution"]}
        if intent["expected_execution"] == "eligible":
            eligible_total += 1
            for bucket in buckets: bucket["eligible"] += 1
            known = [op for op in intent["expected_operations"]
                     if operation_index.get(op, {}).get("status") in EXECUTABLE]
            if not known:
                unavailable += 1
                case["search"] = {"hit": False, "reason": "expected_operation_not_executable",
                                  "expected_operations": intent["expected_operations"]}
                for bucket in buckets: bucket["eligible_unavailable"] += 1
            else:
                artifact_ids = [artifact_ids_by_type[t] for t in intent["input_types"]]
                result = runtime.capabilities_search(intent["query"], artifact_ids=artifact_ids,
                    constraints=intent.get("constraints", {}), limit=3)
                returned = _candidate_ids(result)
                hit = bool(set(known) & set(returned))
                case["search"] = {"hit": hit, "expected_operations": known,
                                  "returned_operations": returned,
                                  "input_types": intent["input_types"]}
                if hit:
                    eligible_hits += 1
                    for bucket in buckets: bucket["eligible_hits"] += 1
            if not case["search"]["hit"]:
                failures.append(case)
                for bucket in buckets: bucket["failures"].append(case)
        else:
            docs_total += 1
            for bucket in buckets: bucket["documentation_only"] += 1
            docs = runtime.docs_search(intent["query"], 10)
            results = docs.get("results", [])
            returned = {item.get("package") for item in results if isinstance(item, dict)}
            reference_only = all(item.get("executable") is False and item.get("scope") == "reference"
                                 for item in results if isinstance(item, dict))
            hit = bool(set(intent["expected_packages"]) & returned) and reference_only
            case["docs"] = {"hit": hit, "expected_packages": intent["expected_packages"],
                            "returned_packages": sorted(x for x in returned if x),
                            "reference_only": reference_only}
            if hit:
                docs_hits += 1
                for bucket in buckets: bucket["docs_hits"] += 1
            else:
                failures.append(case)
                for bucket in buckets: bucket["failures"].append(case)
        case["automatic_execution"] = {"status": "UNMEASURED",
            "reason": "The acceptance runner stops after planning and never calls execute"}
        cases.append(case)
    recall = 100 * eligible_hits / eligible_total if eligible_total else 0.0
    docs_recall = 100 * docs_hits / docs_total if docs_total else 0.0
    return {
        "eligibility": {"denominator": eligible_total, "top3_hits": eligible_hits,
                        "expected_operation_unavailable": unavailable,
                        "top3_recall_percent": round(recall, 2), "target_percent": 95.0,
                        "passes_target": recall >= 95.0},
        "documentation_discovery": {"denominator": docs_total, "hits": docs_hits,
                                    "recall_percent": round(docs_recall, 2),
                                    "target_percent": 95.0,
                                    "passes_target": docs_recall >= 95.0},
        "automatic_execution": {"status": "UNMEASURED",
            "reason": "The acceptance runner measures goal planning but never calls execute"},
        "by_language": {k: _bucket_report(v) for k, v in sorted(by_language.items())},
        "by_family": {k: _bucket_report(v) for k, v in sorted(by_family.items())},
        "failure_count": len(failures), "failures": failures, "cases": cases,
    }


def _sample_schema_value(schema: dict[str, Any]) -> Any:
    """Produce a deterministic, schema-valid value for planning-only probes."""
    if "oneOf" in schema:
        return _sample_schema_value(schema["oneOf"][0])
    if "const" in schema:
        return schema["const"]
    if schema.get("enum"):
        return schema["enum"][0]
    kind = schema.get("type")
    if kind == "object":
        properties = schema.get("properties", {})
        return {name: _sample_schema_value(properties[name])
                for name in schema.get("required", [])}
    if kind == "array":
        return [_sample_schema_value(schema.get("items", {}))
                for _ in range(schema.get("minItems", 0))]
    if kind == "TypedLength":
        minimum = schema.get("exclusiveMinimum", schema.get("minimum", 0))
        return {"value": float(minimum) + 1.0, "unit": "mm"}
    if kind == "TypedAngle":
        minimum = schema.get("minimum_degrees", 0)
        maximum = schema.get("maximum_degrees", 180)
        return {"value": (float(minimum) + float(maximum)) / 2.0, "unit": "deg"}
    if kind in {"number", "integer"}:
        minimum = schema.get("exclusiveMinimum", schema.get("minimum", 0))
        maximum = schema.get("exclusiveMaximum", schema.get("maximum"))
        value = float(minimum) + (1.0 if "exclusiveMinimum" in schema else 0.0)
        if maximum is not None and value >= float(maximum):
            value = (float(minimum) + float(maximum)) / 2.0
        return int(value) if kind == "integer" else value
    if kind == "boolean":
        return False
    if kind == "string":
        return "sample"
    return None


_ROUTING_PARAMETERS: dict[str, dict[str, Any]] = {
    "mesh.simplify.edge_collapse": {
        "stop": {"kind": "edge_ratio", "value": 0.8},
        "policy": "gh_plane_line",
        "max_symmetric_deviation": {"value": 2.0, "unit": "mm"},
        "hausdorff_error_bound": {"value": 0.01, "unit": "mm"},
    },
    "mesh.distance.symmetric_hausdorff": {
        "tolerance": {"value": 2.0, "unit": "mm"},
        "error_bound": {"value": 0.01, "unit": "mm"},
    },
    "pointset.normals.estimate": {"method": "pca", "neighbors": 3},
    "pointset.remove_outliers": {
        "neighbors": 3, "threshold_percent": 10.0,
        "threshold_distance": {"value": 0.1, "unit": "mm"},
    },
    "pointset.smooth.jet": {"neighbors": 3, "degree_fitting": 2,
                              "degree_monge": 2},
    "mesh.analysis.sharp_features": {"angle": {"value": 45.0, "unit": "deg"}},
}


def _routing_probe(intent: dict[str, Any], *, runtime: Any,
                   operation_index: dict[str, dict[str, Any]],
                   artifact_ids_by_type: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a valid goal-plan request and run the production planner once."""
    seed_artifacts = [artifact_ids_by_type[item] for item in intent["input_types"]]
    preview = runtime.capabilities_search(intent["query"], artifact_ids=seed_artifacts,
                                          constraints={}, limit=5)
    candidates = _candidate_ids(preview)
    analysis = preview.get("query_analysis", {})
    route_selected = analysis.get("recommended_operation")
    if not isinstance(route_selected, str):
        route_selected = None
    predicted = route_selected or (candidates[0] if candidates else None)
    operation = operation_index.get(predicted or "")
    if operation is None:
        input_types = list(intent["input_types"])
        parameters: dict[str, Any] = {}
    else:
        specifications = operation["io"]["inputs"]
        def assign(index: int, remaining: list[str]) -> list[str] | None:
            if index == len(specifications):
                return [] if not remaining else None
            for position, kind in enumerate(remaining):
                if kind not in specifications[index].get("types", []):
                    continue
                tail = assign(index + 1, remaining[:position] + remaining[position + 1:])
                if tail is not None:
                    return [kind, *tail]
            return None
        matched = assign(0, list(intent["input_types"]))
        if matched is None:
            raise ValueError(f"Preview operation {predicted} does not match probe artifacts")
        input_types = matched
        parameters = _ROUTING_PARAMETERS.get(
            predicted, _sample_schema_value(operation["parameters"]))
    request = {
        "goal": intent["query"],
        "inputs": [artifact_ids_by_type[item] for item in input_types],
        "parameters": parameters,
        "policy": {},
    }
    context = {"preview_top_operation": predicted,
               "preview_operations": candidates,
               "preview_route_selected": route_selected,
               "preview_query_analysis": analysis,
               "used_input_types": input_types,
               "request_parameters": parameters}
    return request, context


def _error_details(error: Exception) -> dict[str, Any]:
    return {"class": getattr(error, "failure_class", type(error).__name__),
            "code": getattr(error, "code", None), "reason": str(error)}


def evaluate_goal_routing(corpus: dict[str, Any], *, runtime: Any,
                          operation_index: dict[str, dict[str, Any]],
                          artifact_ids_by_type: dict[str, str]) -> dict[str, Any]:
    """Measure production ``plan(goal=...)`` without executing any plan."""
    cases: list[dict[str, Any]] = []
    eligible_top1 = eligible_ambiguous = eligible_clarification = 0
    eligible_wrong = eligible_wrong_post_error = eligible_indeterminate = 0
    docs_rejected = docs_executable = docs_wrong_post_error = docs_indeterminate = 0
    docs_unmeasured = planner_calls = 0
    for intent in corpus["intents"]:
        probe = intent["routing_probe"]
        if probe["status"] == "unmeasured_input_model":
            docs_unmeasured += 1
            cases.append({"id": intent["id"],
                          "expected_execution": intent["expected_execution"],
                          "outcome": "unmeasured_input_model",
                          "reason": probe["reason"],
                          "declared_input_types": intent["input_types"]})
            continue
        request, context = _routing_probe(
            intent, runtime=runtime, operation_index=operation_index,
            artifact_ids_by_type=artifact_ids_by_type)
        planner_calls += 1
        case: dict[str, Any] = {
            "id": intent["id"], "expected_execution": intent["expected_execution"],
            **context,
        }
        try:
            plan = runtime.plan(request)
        except Exception as error:
            actual = _error_details(error)
            case["actual_error"] = actual
            if intent["expected_execution"] == "eligible":
                preview_selected = context["preview_route_selected"]
                if actual["class"] == "invalid_input" and actual["code"] == "ambiguous_route":
                    case["outcome"] = "ambiguous_explicit"
                    eligible_ambiguous += 1
                elif (actual["class"] == "invalid_input" and
                      actual["code"] in {"route_parameter_missing", "route_parameter_conflict"}):
                    if preview_selected and preview_selected not in intent["expected_operations"]:
                        case["outcome"] = "wrong_route_with_post_error"
                        eligible_wrong_post_error += 1
                    else:
                        case["outcome"] = "clarification_required"
                        eligible_clarification += 1
                elif preview_selected and preview_selected not in intent["expected_operations"]:
                    case["outcome"] = "wrong_route_with_post_error"
                    eligible_wrong_post_error += 1
                else:
                    case["outcome"] = "indeterminate_error"
                    eligible_indeterminate += 1
            else:
                if ((actual["class"] == "unsupported_adapter" and
                     actual["code"] == "unsupported_operation") or
                    (actual["class"] == "invalid_input" and
                     actual["code"] == "ambiguous_route")):
                    case["outcome"] = "explicitly_rejected"
                    docs_rejected += 1
                elif context["preview_route_selected"]:
                    case["outcome"] = "wrong_route_with_post_error"
                    docs_wrong_post_error += 1
                else:
                    case["outcome"] = "indeterminate_error"
                    docs_indeterminate += 1
        else:
            selected = plan.get("route", {}).get("selected")
            case["selected_operation"] = selected
            case["route_mode"] = plan.get("route", {}).get("mode")
            if intent["expected_execution"] == "eligible":
                if selected in intent["expected_operations"]:
                    case["outcome"] = "expected_top1"
                    eligible_top1 += 1
                else:
                    case["outcome"] = "wrong_executable_route"
                    eligible_wrong += 1
            else:
                case["outcome"] = "unexpected_executable_route"
                docs_executable += 1
        cases.append(case)
    eligible_total = sum(case["expected_execution"] == "eligible" for case in cases)
    docs_total = len(cases) - eligible_total
    passes = not (eligible_clarification or eligible_wrong or eligible_wrong_post_error or
                  eligible_indeterminate or docs_executable or docs_wrong_post_error or
                  docs_indeterminate or docs_unmeasured)
    return {
        "eligible": {"denominator": eligible_total, "expected_top1": eligible_top1,
                     "ambiguous_explicit": eligible_ambiguous,
                     "clarification_required": eligible_clarification,
                     "wrong_executable_route": eligible_wrong,
                     "wrong_route_with_post_error": eligible_wrong_post_error,
                     "indeterminate_error": eligible_indeterminate},
        "documentation_only": {"denominator": docs_total,
                               "explicitly_rejected": docs_rejected,
                               "unexpected_executable_route": docs_executable,
                               "wrong_route_with_post_error": docs_wrong_post_error,
                               "unmeasured_input_model": docs_unmeasured,
                               "indeterminate_error": docs_indeterminate},
        "passes": passes,
        "actual_planning_coverage": {
            "denominator": len(cases), "planner_calls": planner_calls,
            "typed_probe_requests": planner_calls, "execute_calls": 0,
        },
        "automatic_execution": {"status": "UNMEASURED",
                                "reason": "The evaluator never calls execute"},
        "cases": cases,
    }


def evaluate_planner_gates(gates: list[dict[str, Any]], *, runtime: Any,
                           artifact_ids_by_type: dict[str, str]) -> dict[str, Any]:
    cases=[]
    for gate in gates:
        request={"operation_id":gate["operation_id"],
                 "inputs":[artifact_ids_by_type[t] for t in gate["input_types"]],
                 "parameters":gate.get("parameters",{}),"policy":gate.get("policy",{})}
        expected=gate["expected_error"]
        try:
            runtime.plan(request)
        except Exception as error:
            actual={"class":getattr(error,"failure_class",type(error).__name__),
                    "code":getattr(error,"code",None)}
            passed=actual==expected
        else:
            actual={"class":None,"code":None}; passed=False
        cases.append({"id":gate["id"],"passed":passed,"expected_error":expected,
                      "actual_error":actual,"used_input_types":gate["input_types"]})
    return {"total":len(cases),"passed":sum(x["passed"] for x in cases),
            "passes":all(x["passed"] for x in cases),"cases":cases}


def evaluate_package_smoke(corpus: dict[str, Any], *, runtime: Any) -> dict[str, Any]:
    cases=[]
    for case in corpus["cases"]:
        results=runtime.docs_search(case["query"],10).get("results",[])
        returned={item.get("package") for item in results if isinstance(item,dict)}
        reference_only=all(item.get("scope")=="reference" and
                           item.get("executable") is False
                           for item in results if isinstance(item,dict))
        hit=case["expected_package"] in returned and reference_only
        cases.append({"id":case["id"],"hit":hit,"expected_package":case["expected_package"],
                      "returned_packages":sorted(x for x in returned if x),
                      "reference_only":reference_only})
    hits=sum(x["hit"] for x in cases)
    return {"denominator":len(cases),"hits":hits,
            "recall_percent":round(100*hits/len(cases),2) if cases else 0.0,
            "target_percent":100.0,"passes":hits==len(cases),
            "separate_from_natural_intent_recall":True,"cases":cases}


def _synthetic_artifacts(folder: Path, runtime: Any) -> dict[str, str]:
    xyz=folder/"points.xyz"; xyz.write_text("0 0 0\n1 0 0\n0 1 0\n0 0 1\n1 1 1\n",encoding="ascii")
    off=folder/"mesh.off"; off.write_text("OFF\n4 4 0\n0 0 0\n1 0 0\n0 1 0\n0 0 1\n3 0 2 1\n3 0 1 3\n3 1 2 3\n3 2 0 3\n",encoding="ascii")
    ply=folder/"normals.ply"; ply.write_text("ply\nformat ascii 1.0\nelement vertex 4\nproperty double x\nproperty double y\nproperty double z\nproperty double nx\nproperty double ny\nproperty double nz\nend_header\n0 0 0 0 0 1\n1 0 0 0 0 1\n0 1 0 0 0 1\n1 1 0 0 0 1\n",encoding="ascii")
    soup=folder/"soup.off"; soup.write_text(
        "OFF\n4 1 0\n0 0 0\n1 0 0\n1 1 0\n0 1 0\n4 0 1 2 3\n",encoding="ascii")
    return {"PointSet3":runtime.artifact_import(str(xyz),"mm",artifact_type="PointSet3")["artifact_id"],
            "TriangleSurfaceMesh":runtime.artifact_import(str(off),"mm",artifact_type="TriangleSurfaceMesh")["artifact_id"],
            "PointSet3Normals":runtime.artifact_import(str(ply),"mm",artifact_type="PointSet3Normals")["artifact_id"],
            "PolygonSoup3":runtime.artifact_import(str(soup),"mm",artifact_type="PolygonSoup3")["artifact_id"]}


def run(corpus_path: Path = CORPUS_PATH, *, output: Path | None = None) -> dict[str, Any]:
    corpus=_load(corpus_path); package_smoke=_load(PACKAGE_SMOKE_PATH)
    packages=_load(PACKAGES_PATH); requirements=_load(REQUIREMENTS_PATH)
    inventory=_load(INVENTORY_PATH); operations_document=_load(OPERATIONS_PATH)
    package_ids=_package_ids(packages); family_ids, requirement_ids=_requirements(requirements)
    requirement_families, requirement_packages=_requirement_context(requirements,inventory)
    operation_index=_operations(operations_document)
    errors=validate_corpus(corpus,package_ids=package_ids,operation_ids=set(operation_index),
        requirement_ids=requirement_ids,family_ids=family_ids,operation_index=operation_index,
        requirement_families=requirement_families,requirement_packages=requirement_packages)
    smoke_errors=validate_package_smoke(package_smoke,package_ids)
    report={"schema_version":2,"generator":"master-search-acceptance",
        "corpus":str(corpus_path.relative_to(REPO)).replace("\\","/"),
        "package_smoke_corpus":str(PACKAGE_SMOKE_PATH.relative_to(REPO)).replace("\\","/"),
        "hashes":{"corpus_sha256":_hash(corpus_path),"package_smoke_sha256":_hash(PACKAGE_SMOKE_PATH),
                  "generator_sha256":_hash(Path(__file__)),
                  "test_source_sha256":_hash(TEST_SOURCE_PATH),
                  "operations_sha256":_hash(OPERATIONS_PATH),"packages_sha256":_hash(PACKAGES_PATH),
                  "major_requirements_sha256":_hash(REQUIREMENTS_PATH),"inventory_sha256":_hash(INVENTORY_PATH)},
        "corpus_errors":errors,"package_smoke_errors":smoke_errors}
    if errors or smoke_errors:
        report.update({"status":"invalid_corpus","passes_acceptance":False,
                       "overall_standalone_ready":False})
    else:
        from cgal_mcp.master.runtime import MasterRuntime
        with tempfile.TemporaryDirectory(prefix="master-search-acceptance-") as name:
            folder=Path(name); runtime=MasterRuntime(folder/"store",require_memory_limit=False)
            try:
                artifact_ids=_synthetic_artifacts(folder,runtime)
                result=evaluate(corpus,runtime=runtime,operation_index=operation_index,
                                artifact_ids_by_type=artifact_ids)
                routing=evaluate_goal_routing(corpus,runtime=runtime,
                    operation_index=operation_index,artifact_ids_by_type=artifact_ids)
                gates=evaluate_planner_gates(corpus["planner_gates"],runtime=runtime,
                                             artifact_ids_by_type=artifact_ids)
                smoke=evaluate_package_smoke(package_smoke,runtime=runtime)
            finally:
                runtime.close()
        report.update(result); report["goal_routing"]=routing
        report["planner_gates"]=gates; report["package_discovery_smoke"]=smoke
        search_pass=(result["eligibility"]["passes_target"] and
                     result["documentation_discovery"]["passes_target"] and
                     routing["passes"] and gates["passes"] and smoke["passes"])
        report["passes_search_acceptance"]=search_pass
        report["passes_acceptance"]=False
        report["overall_standalone_ready"]=False
        report["status"]="incomplete_measurement" if search_pass else "fail"
        report["standalone_blockers"]=["automatic_execution_UNMEASURED"]
    if output is not None:
        resolved=output.resolve(); work=(REPO/"work").resolve()
        if work not in resolved.parents: raise ValueError("Acceptance report output must be below work/")
        resolved.parent.mkdir(parents=True,exist_ok=True)
        resolved.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return report


def main() -> int:
    parser=argparse.ArgumentParser(); parser.add_argument("--corpus",type=Path,default=CORPUS_PATH)
    parser.add_argument("--output",type=Path,default=REPO/"work"/"master-search-acceptance.json")
    args=parser.parse_args(); report=run(args.corpus,output=args.output)
    keys=("status","passes_search_acceptance","passes_acceptance","overall_standalone_ready",
          "corpus_errors","package_smoke_errors","eligibility","documentation_discovery",
          "package_discovery_smoke","goal_routing","automatic_execution","planner_gates",
          "failure_count")
    summary={k:report[k] for k in keys if k in report}
    if "package_discovery_smoke" in summary:
        summary["package_discovery_smoke"]={
            key:value for key,value in summary["package_discovery_smoke"].items()
            if key != "cases"}
    if "goal_routing" in summary:
        summary["goal_routing"]={
            key:value for key,value in summary["goal_routing"].items()
            if key != "cases"}
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    return 2 if report.get("status")=="invalid_corpus" else 0

if __name__ == "__main__":
    raise SystemExit(main())
