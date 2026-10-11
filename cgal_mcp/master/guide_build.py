"""Generate the AI-facing guide from the registry, catalog and workflow set.

``build_topics(root)`` is a pure function of checked-in data files; the guide
served by the MCP server is a committed snapshot of its output and a unit test
fails when the snapshot differs from a fresh build, so the text cannot drift.
No timestamps, absolute paths or environment values enter the output.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any

from . import guide_texts as T
from .resources import DEFAULT_CONCURRENCY, DEFAULT_MEMORY_MB, DEFAULT_WALL_TIME_MS, MAX_WALL_TIME_MS

LANGS = ("en", "ja")
FIXTURE_ROOT = "tests/fixtures/master"
SCHEMA_VERSION = 1
TOPIC_NAMES = ("start", "families", "recipes", "errors", "glossary", "limits-and-status")
PROMPT_NAMES = ("start_here", "repair_and_simplify_mesh", "reconstruct_surface_from_points",
                "validate_geometry", "compare_meshes", "2d_boolean_offset", "choose_operation")
TOOL_NAMES = ("cgal_get_guide", "cgal_capabilities_search", "cgal_capabilities_describe", "cgal_plan",
              "cgal_execute", "cgal_job_status", "cgal_job_cancel", "cgal_validate", "cgal_artifact_import",
              "cgal_artifact_inspect", "cgal_artifact_export", "cgal_docs_search", "cgal_system_health")


def jdump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(", ", ": "))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------------------
class Sources:
    def __init__(self, root: Path):
        self.root = root
        read = lambda rel: json.loads((root / rel).read_text(encoding="utf-8"))  # noqa: E731
        operations = read("cgal_mcp/master/operations.json")
        self.cgal_version = operations["cgal_version"]
        self.ops: dict[str, dict] = {o["id"]: o for o in operations["operations"]}
        self.phrases: dict[str, list[str]] = read("cgal_mcp/master/search_data.json")["operations"]
        self.packages: dict[str, dict] = {x["id"]: x for x in read("catalog/packages.json")["packages"]}
        self.policy = read("catalog/package_status_policy.json")
        self.workflows = read("docs/master/workflows.json")
        self.gloss = read("cgal_mcp/master/unsupported_gloss.json")["packages"]
        self.policies = read("cgal_mcp/master/policies.json")
        self.families_contract = self._load_contracts()
        self.error_codes = self._scan_error_codes()
        self.family_of = self._family_map()

    def _load_contracts(self) -> dict[str, dict]:
        path = self.root / "scripts/master_replay_families.py"
        spec = importlib.util.spec_from_file_location("_guide_replay_families", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules["_guide_replay_families"] = module
        try:
            spec.loader.exec_module(module)
        finally:
            sys.modules.pop("_guide_replay_families", None)
        return module.GENERIC_FAMILIES

    def _scan_error_codes(self) -> list[str]:
        pattern = re.compile(r'(?:InvalidInput|PreconditionFailure|UnsupportedOperation|MasterError|WorkerFailure)'
                             r'\(\s*"([a-z_0-9]+)"')
        codes: set[str] = set()
        for path in sorted((self.root / "cgal_mcp/master").glob("*.py")):
            if path.name == "guide_texts.py":
                continue
            codes.update(pattern.findall(path.read_text(encoding="utf-8")))
        return sorted(codes)

    def _family_map(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for oid in sorted(self.ops):
            reqs = self.ops[oid].get("major_requirements") or []
            families = sorted({".".join(r.split(".")[1:3]) for r in reqs})
            if families:
                result[oid] = families[0]
        for oid in sorted(self.ops):
            if oid in result:
                continue
            users = sorted(o["id"] for o in self.ops.values()
                           if oid in o["validation"].get("validators", []) and o["id"] in result)
            if users:
                result[oid] = result[users[0]]
        for oid in sorted(self.ops):
            result.setdefault(oid, T.PREFIX_FALLBACK[oid.split(".")[0]])
        for family in result.values():
            assert family in T.FAMILIES, family
        return result

    def positive_workflows(self) -> list[dict]:
        return [w for w in self.workflows["workflows"] if w["category"] == "positive"]

    def negative_workflows(self) -> list[dict]:
        return [w for w in self.workflows["workflows"] if w["category"] == "negative"]


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------
def ja_phrases(src: Sources, oid: str) -> list[str]:
    return [p for p in src.phrases.get(oid, []) if re.search(r"[^\x00-\x7f]", p)]


def en_phrases(src: Sources, oid: str) -> list[str]:
    return [p for p in src.phrases.get(oid, []) if not re.search(r"[^\x00-\x7f]", p)]


def type_note(name: str, lang: str) -> str:
    index = 0 if lang == "en" else 1
    if name in T.ARTIFACT_TYPE_NOTES:
        return T.ARTIFACT_TYPE_NOTES[name][index]
    return T.REPORT_TYPE_NOTE[index]


def bounded_input(op: dict) -> dict:
    for cond in op["preconditions"]:
        if cond.get("id") == "bounded_input":
            return {k: v for k, v in cond.items() if k.startswith("maximum_")}
    return {}


def schema_text(schema: dict, lang: str) -> str:
    kind = schema.get("type")
    if "oneOf" in schema:
        return "one of: " + " | ".join(jdump(s) for s in schema["oneOf"]) if lang == "en" else \
            "次のいずれか: " + " | ".join(jdump(s) for s in schema["oneOf"])
    if kind == "TypedLength":
        text = '{"value": number, "unit": "mm"|"cm"|"m"} (length)'
        return text if lang == "en" else text.replace("(length)", "（長さ）")
    if kind == "TypedAngle":
        text = '{"value": number, "unit": "deg"|"rad"} (angle)'
        return text if lang == "en" else text.replace("(angle)", "（角度）")
    if kind in ("object", "array") or kind is None:
        keep = {k: v for k, v in schema.items() if k != "description"}
        return jdump(keep)
    return str(kind)


def constraint_text(schema: dict) -> str:
    parts = []
    for key, label in (("minimum", ">="), ("exclusiveMinimum", ">"), ("maximum", "<="), ("exclusiveMaximum", "<")):
        if key in schema:
            parts.append(f"{label} {schema[key]}")
    if "minimum_degrees" in schema:
        parts.append(f">= {schema['minimum_degrees']} deg")
    if "maximum_degrees" in schema:
        parts.append(f"<= {schema['maximum_degrees']} deg")
    if "enum" in schema:
        parts.append("one of " + jdump(schema["enum"]))
    if "minItems" in schema or "maxItems" in schema:
        parts.append(f"items {schema.get('minItems', 0)}..{schema.get('maxItems', 'n')}")
    if "default" in schema:
        parts.append("default " + jdump(schema["default"]))
    return "; ".join(parts) if parts else "-"


# --------------------------------------------------------------------------------------
# Examples (one verified-by-replay call per executable, non-validator operation)
# --------------------------------------------------------------------------------------
def _fixture_size(src: Sources, rel: str) -> int:
    path = src.root / FIXTURE_ROOT / rel
    return path.stat().st_size if path.is_file() else 10 ** 12


def _imports(items: list[tuple[str, str, str, str]]) -> tuple[list[dict], list[str]]:
    imports: list[dict] = []
    names: list[str] = []
    seen: dict[tuple[str, str], str] = {}
    for path, unit, kind, stem in items:
        key = (path, unit)
        if key not in seen:
            name = stem
            used = {i["name"] for i in imports}
            n = 2
            while name in used:
                name = f"{stem}_{n}"
                n += 1
            seen[key] = name
            imports.append({"name": name, "path": path, "unit": unit, "artifact_type": kind})
        names.append(seen[key])
    return imports, names


def build_examples(src: Sources) -> dict[str, dict]:
    result: dict[str, dict] = {}
    fixtures = src.workflows["fixtures"]
    for workflow in src.positive_workflows():
        for step in workflow["steps"]:
            oid = step["operation"]
            op = src.ops.get(oid)
            if (op is None or op["role"] == "validator" or oid in result
                    or not all(isinstance(v, str) and v.startswith("fixture:") for v in step["inputs"].values())):
                continue
            items = []
            for slot in op["io"]["inputs"]:
                fx = fixtures[step["inputs"][slot["slot"]][len("fixture:"):]]
                items.append((fx["path"], fx["unit"], fx["type"], Path(fx["path"]).stem))
            imports, names = _imports(items)
            result[oid] = {"source": f"workflow {workflow['id']}", "imports": imports,
                           "plan_request": {"operation_id": oid, "parameters": step["parameters"],
                                            "inputs": {s["slot"]: "$" + n for s, n in zip(op["io"]["inputs"], names)}}}
    candidates: dict[str, list[tuple]] = {}
    for fid in sorted(src.families_contract):
        for case in src.families_contract[fid]["cases"]:
            oid = case["operation"]
            op = src.ops.get(oid)
            if op is None or op["role"] == "validator" or oid in result:
                continue
            if len(case["inputs"]) != len(op["io"]["inputs"]):
                continue
            size = sum(_fixture_size(src, i["fixture"]) for i in case["inputs"])
            candidates.setdefault(oid, []).append((size, case["id"], fid, case))
    for oid, options in sorted(candidates.items()):
        size, case_id, fid, case = sorted(options, key=lambda o: (o[0], o[1]))[0]
        op = src.ops[oid]
        items = [(f"{FIXTURE_ROOT}/{i['fixture']}", i["unit"], i["type"], Path(i["fixture"]).stem)
                 for i in case["inputs"]]
        imports, names = _imports(items)
        result[oid] = {"source": f"replay case {case_id} (family {fid})", "imports": imports,
                       "plan_request": {"operation_id": oid, "parameters": case["parameters"],
                                        "inputs": {s["slot"]: "$" + n for s, n in zip(op["io"]["inputs"], names)}}}
    result.update(MANUAL_EXAMPLES(src, result))
    return result


MANUAL_CASES = {
    "mesh.analysis.connected_components": ("cube_a", {}),
    "mesh.analysis.sharp_features": ("cube_a", {"angle": {"value": 30, "unit": "deg"}}),
}


def MANUAL_EXAMPLES(src: Sources, found: dict[str, dict]) -> dict[str, dict]:
    """Examples for executable operations no replay/workflow case covers on its own."""
    manual = {}
    for oid, (fixture, parameters) in sorted(MANUAL_CASES.items()):
        if oid in found or oid not in src.ops:
            continue
        fx = src.workflows["fixtures"][fixture]
        op = src.ops[oid]
        manual[oid] = {
            "source": f"manual (fixture {fixture})",
            "imports": [{"name": fixture, "path": fx["path"], "unit": fx["unit"], "artifact_type": fx["type"]}],
            "plan_request": {"operation_id": oid, "parameters": parameters,
                             "inputs": {op["io"]["inputs"][0]["slot"]: "$" + fixture}}}
    return manual


def example_lines(example: dict, lang: str) -> list[str]:
    en = lang == "en"
    lines = []
    lines.append(("Example call (fixture-backed; source: " if en else "呼び出し例（fixture使用。出典: ") + example["source"] + ")")
    for number, item in enumerate(example["imports"], 1):
        args = {"path": item["path"], "unit": item["unit"], "artifact_type": item["artifact_type"]}
        lines.append(f"{number}. cgal_artifact_import {jdump(args)}  -> " +
                     (f"artifact_id, call it ${item['name']}" if en else f"artifact_id（${item['name']}と呼ぶ）"))
    n = len(example["imports"]) + 1
    lines.append(f"{n}. cgal_plan {jdump({'request': example['plan_request']})}  " +
                 ("(replace each $name by the artifact_id from the import)" if en else "（$nameは対応するimportのartifact_idに置換）"))
    lines.append(f"{n + 1}. cgal_execute {{\"plan_id\": <plan_id>}}  ->  cgal_job_status {{\"job_id\": <job_id>}} " +
                 ("until state is succeeded/rejected/failed" if en else "をstateがsucceeded/rejected/failedになるまで"))
    return lines


# --------------------------------------------------------------------------------------
# Operation cards
# --------------------------------------------------------------------------------------
LABELS = {
    "en": {"purpose": "Purpose", "when": "Use it when", "notwhen": "Do not use it when", "inputs": "Inputs",
           "outputs": "Outputs", "params": "Parameters", "validation": "Validation", "limits": "Limits and precision",
           "failures": "Failure codes you can meet", "example": "Example", "related": "Related operations",
           "provenance": "Provenance", "family": "Family", "role": "Role", "status": "Status", "none": "none"},
    "ja": {"purpose": "目的", "when": "使う場面", "notwhen": "使ってはいけない場面", "inputs": "入力",
           "outputs": "出力", "params": "パラメータ", "validation": "検証", "limits": "上限と精度",
           "failures": "遭遇しうる失敗コード", "example": "例", "related": "関連する操作",
           "provenance": "出典", "family": "分野", "role": "役割", "status": "状態", "none": "なし"},
}
ROLE_TEXT = {
    "transform": ("transform: produces new geometry from its inputs (inputs are never modified)",
                  "transform: 入力から新しい幾何を作る（入力は変更されない）"),
    "analysis": ("analysis: produces a JSON report/measurement, no geometry change",
                 "analysis: JSONレポート・測定値を作る。幾何は変えない"),
    "validator": ("validator: independent check of another operation's result; inserted automatically",
                  "validator: 他の操作の結果を独立に検査する。自動で挿入される"),
}


def _precondition_lines(op: dict, lang: str) -> list[str]:
    en = lang == "en"
    out = []
    for cond in op["preconditions"]:
        cid = cond["id"]
        if cid == "bounded_input":
            bits = ", ".join(f"{k.replace('maximum_', 'at most ')}: {v}" for k, v in sorted(bounded_input(op).items()))
            out.append((f"input size bound ({bits}); larger inputs are refused with unmet_precondition" if en else
                        f"入力サイズ上限（{bits}）。超えるとunmet_preconditionで拒否される"))
        elif "property" in cond:
            pair = T.PROPERTY_TEXT.get(cond["property"])
            minimum = cond.get("minimum")
            if pair:
                text = pair[0 if en else 1].replace("{n}", str(minimum))
                out.append(("input requirement: " if en else "入力の要件: ") + text)
            else:
                out.append((f"input must satisfy {cond['property']}" if en else f"入力は {cond['property']} を満たすこと"))
        elif "bounds" in cond:
            out.append((f"numeric envelope {jdump(cond['bounds'])} (inputs outside it are refused)" if en else
                        f"数値範囲 {jdump(cond['bounds'])}（外側の入力は拒否される）"))
        else:
            out.append((f"worker-checked precondition `{cid}` (refused with unmet_precondition when false)" if en else
                        f"workerが検査する前提条件 `{cid}`（偽ならunmet_preconditionで拒否）"))
    for item in op.get("parameter_preconditions", []):
        extra = ", ".join(f"{k}={v}" for k, v in sorted(item.items()) if k not in ("parameter", "input"))
        out.append((f"parameter `{item['parameter']}` is checked against input `{item.get('input')}` ({extra}); a violating value is refused" if en else
                    f"パラメータ `{item['parameter']}` は入力 `{item.get('input')}` に対して検査される（{extra}）。違反値は拒否される"))
    return out


def effective_bounds(src: Sources, op: dict) -> list[tuple[str, dict]]:
    """Own bound plus bounds inherited from mandatory validators (a validator refusal fails the job)."""
    result = []
    own = bounded_input(op)
    if own:
        result.append((op["id"], own))
    for vid in op["validation"].get("validators", []):
        bound = bounded_input(src.ops[vid])
        if bound:
            result.append((vid, bound))
    return result


def op_card(src: Sources, oid: str, lang: str, examples: dict[str, dict], users: dict[str, list[str]]) -> str:
    en = lang == "en"
    L = LABELS[lang]
    op = src.ops[oid]
    fam = src.family_of[oid]
    fam_name = T.FAMILIES[fam][lang]
    lines = [f"# {oid}", "",
             f"- {L['status']}: {op['status']} " + ("(executable; replay-verified on bundled fixtures)" if en else "（実行可能。同梱fixtureで再実行検証済み）"),
             f"- {L['family']}: {fam} {fam_name}",
             f"- {L['role']}: {ROLE_TEXT[op['role']][0 if en else 1]}",
             f"- CGAL package: {op['package']} (CGAL {src.cgal_version})", ""]
    lines += [f"## {L['purpose']}", op["summary"]]
    jp = ja_phrases(src, oid)
    ep = en_phrases(src, oid)
    aliases = op.get("aliases", [])
    lines.append(("Also known as: " if en else "別名: ") + ("; ".join(aliases) if aliases else L["none"]))
    lines.append("")
    lines += [f"## {L['when']}"]
    if op["role"] == "validator":
        lines.append("- " + ("Never as a first choice: it runs automatically after the operations listed under Validation; call cgal_validate only to re-check an existing artifact against its source." if en else
                              "最初の選択肢にしない。検証欄の操作の後で自動実行される。既存artifactをsourceと照合し直すときだけcgal_validateを使う。"))
    elif en:
        lines += [f"- {p}" for p in (ep[:4] or [op["summary"]])]
    else:
        lines += [f"- {p}" for p in (jp[:4] or ["（日本語の呼び名データなし）" + op["summary"]])]
    lines += ["", f"## {L['notwhen']}"]
    notwhen = _precondition_lines(op, lang)
    contract = op.get("output_contract", {})
    if op["role"] == "validator":
        notwhen.append("to produce geometry; validators emit a report only" if en else "幾何を作る目的。検証器はレポートしか出さない")
    if contract.get("geometry_mutation") is True:
        notwhen.append("you need the input preserved in place: a new artifact is created and the input stays unchanged" if en else
                       "入力をその場で書き換えたいとき。新しいartifactが作られ入力は変わらない")
    if not notwhen:
        notwhen.append("(no operation-specific exclusions are declared)" if en else "（この操作固有の除外条件は宣言されていない）")
    lines += [f"- {n}" for n in notwhen]
    lines += ["", f"## {L['inputs']}"]
    for spec in op["io"]["inputs"]:
        types = ", ".join(spec["types"])
        unit = spec.get("unit_dimension") or spec.get("units") or spec.get("unit") or "none"
        fmts = "/".join(spec.get("formats", [])) or "-"
        unit_text = ("length (mm, cm or m)" if en else "長さ（mm/cm/m）") if unit == "length" else unit
        lines.append(f"- `{spec['slot']}`: {types} ({fmts}; " + ("unit: " if en else "単位: ") + f"{unit_text}) - {type_note(spec['types'][0], lang)}")
    lines += ["", f"## {L['outputs']}"]
    for spec in op["io"]["outputs"]:
        unit = spec.get("unit") or ("same as input " + spec["unit_from"] if en else "入力 " + spec["unit_from"] + " と同じ"
                                    if spec.get("unit_from") else "none")
        lines.append(f"- `{spec['slot']}`: {spec['type']} ({spec.get('format', '-')}; " + ("unit: " if en else "単位: ") + f"{unit}) - {type_note(spec['type'], lang)}")
    lines += ["", f"## {L['params']}"]
    schema = op["parameters"]
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    if not props:
        lines.append("- " + ("none (pass an empty object {})" if en else "なし（空のオブジェクト {} を渡す）"))
    for name in sorted(props):
        child = props[name]
        req = ("required" if name in required else "optional") if en else ("必須" if name in required else "任意")
        desc = f" - {child['description']}" if child.get("description") else ""
        lines.append(f"- `{name}` ({req}): {schema_text(child, lang)}; {constraint_text(child)}{desc}")
    if "oneOf" in schema:
        lines.append("- " + ("top-level alternatives: " if en else "トップレベルの選択肢: ") + schema_text({"oneOf": schema["oneOf"]}, lang))
    lines += ["", f"## {L['validation']}"]
    validators = op["validation"].get("validators", [])
    if op["role"] == "validator":
        used = users.get(oid, [])
        lines.append(("Runs automatically for: " if en else "自動実行される対象: ") + (", ".join(used) if used else L["none"]))
    elif validators:
        lines.append(("Mandatory and automatic (cannot be skipped or replaced): " if en else "必須かつ自動（省略・差し替え不可）: ") + ", ".join(validators))
        checks = op["validation"].get("required_report_checks")
        if checks:
            lines.append(("Required report checks: " if en else "必須のレポート検査: ") + jdump(checks))
        lines.append("Outputs are published only after the validator passes; otherwise the job ends 'rejected'/'failed' (validation_failed)." if en else
                     "検証器が合格した後にだけ出力が公開される。合格しなければjobは'rejected'/'failed'（validation_failed）。")
    else:
        lines.append("No validator is declared (read-only analysis)." if en else "検証器は宣言されていない（読み取り専用の解析）。")
    lines += ["", f"## {L['limits']}"]
    bounds = effective_bounds(src, op)
    if not bounds:
        lines.append(("Input bound: " if en else "入力上限: ") + L["none"])
    for owner, bound in bounds:
        lines.append((("Input bound" if en else "入力上限") + (" (own): " if owner == oid else (f" inherited from mandatory validator {owner}: " if en else f"（必須検証器 {owner} から継承）: "))) + jdump(bound) +
                     ("" if owner == oid else (" - a larger input is refused when this validator is planned/run" if en else " - これを超える入力はこの検証器の計画・実行時に拒否される")))
    precision = op.get("precision", {})
    for key in ("effective_kernel", "coordinate_storage", "exact_constructions", "effective_concurrency", "bound_interpretation"):
        if key in precision:
            lines.append(f"{key}: {precision[key]}")
    lines.append(("Kernel: default " if en else "kernel: 既定 ") + f"{op['kernel']['default']}; " +
                 ("supported " if en else "対応 ") + ", ".join(op["kernel"]["supported"]))
    lines.append((f"Server defaults: concurrency {DEFAULT_CONCURRENCY}, worker memory {DEFAULT_MEMORY_MB} MiB, wall time {DEFAULT_WALL_TIME_MS // 1000} s (see cgal_system_health for the live values)." if en else
                  f"サーバ既定: 同時実行{DEFAULT_CONCURRENCY}、workerメモリ{DEFAULT_MEMORY_MB}MiB、壁時間{DEFAULT_WALL_TIME_MS // 1000}秒（実値はcgal_system_health）。"))
    lines += ["", f"## {L['failures']}"]
    codes: list[str] = []
    if props:
        codes += ["parameters_required"] if required else []
        codes += ["parameters_unknown", "parameter_type", "parameter_range"]
    if op["preconditions"]:
        codes.append("unmet_precondition")
    if len(op["io"]["inputs"]) >= 2:
        codes.append("unit_mismatch")
    codes += ["input_binding", "dag_type"]
    if op["validation"].get("validators"):
        codes.append("validation_failed")
    codes.append("resource_limit")
    for code in codes:
        meaning = T.ERROR_SPECIFIC.get(code, (None, None))[0 if en else 1]
        lines.append(f"- `{code}`: {meaning}" if meaning else
                     f"- `{code}` " + ("(see cgal_get_guide topic 'errors')" if en else "（cgal_get_guideのtopic 'errors'参照）"))
    if op["role"] != "validator":
        lines.append("- " + ("worker codes (UPPER_SNAKE_CASE, operation specific) arrive in job.error.code with a class; see 'errors'" if en else
                              "workerコード（UPPER_SNAKE_CASE、操作固有）はclassと共にjob.error.codeで届く。'errors'参照"))
    lines += ["", f"## {L['example']}"]
    if oid in examples:
        lines += example_lines(examples[oid], lang)
    elif op["role"] == "validator":
        lines.append("Not called directly: plan the operation it validates and this validator is added for you (or use cgal_validate)." if en else
                     "直接は呼ばない。検証対象の操作をplanすればこの検証器が自動で追加される（またはcgal_validate）。")
    else:
        raise AssertionError(f"no example for {oid}")
    lines += ["", f"## {L['related']}"]
    same = sorted(o for o in src.ops if o != oid and src.ops[o]["role"] != "validator"
                  and src.ops[o]["package"] == op["package"])[:4]
    near = sorted(o for o in src.ops if o != oid and src.ops[o]["role"] != "validator" and o not in same
                  and src.family_of[o] == fam and src.ops[o]["io"]["inputs"][0]["types"][0] == op["io"]["inputs"][0]["types"][0])[:3]
    rel = same + near
    if rel:
        lines.append(("Same package or family and input type: " if en else "同じパッケージ/分野・入力型: ") + ", ".join(rel))
    if validators:
        lines.append(("Its validators: " if en else "この操作の検証器: ") + ", ".join(validators))
    if not rel and not validators:
        lines.append(L["none"])
    lines += ["", f"## {L['provenance']}"]
    symbols = [s["identifier"] for s in op["sources"] if s["kind"] == "cgal_symbol"][:6]
    headers = [s["identifier"] for s in op["sources"] if s["kind"] == "header"][:4]
    lines.append(f"license: {op['license']['expression']}" + (" (commercial option exists)" if op["license"].get("commercial_option") else ""))
    lines.append("CGAL symbols: " + (", ".join(symbols) or L["none"]))
    lines.append("headers: " + (", ".join(headers) or L["none"]))
    lines.append(("registry revision " if en else "レジストリrev ") + str(op["revision"]) +
                 (("; evidence: " if en else "；証拠: ") + ", ".join(op.get("evidence", {}).get("tests", []))))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# Recipes
# --------------------------------------------------------------------------------------
def _placeholder(binding: Any) -> Any:
    if isinstance(binding, str) and binding.startswith("fixture:"):
        return "$" + binding[len("fixture:"):]
    return binding


def _plan_request(workflow: dict) -> dict:
    def steps(items: list[dict]) -> list[dict]:
        return [{**{k: v for k, v in s.items() if k != "inputs"},
                 "inputs": {slot: _placeholder(b) for slot, b in s["inputs"].items()}} for s in items]
    request: dict[str, Any] = {"steps": steps(workflow["steps"])}
    for key in ("rules", "policy"):
        if key in workflow:
            request[key] = workflow[key]
    if "alternatives" in workflow:
        request["alternatives"] = [
            {"steps": steps(a["steps"]), **({"rules": a["rules"]} if "rules" in a else {})}
            for a in workflow["alternatives"]]
    return request


def recipe_ops(src: Sources, workflow: dict) -> list[str]:
    seen: list[str] = []
    for step in workflow["steps"]:
        if step["operation"] not in seen:
            seen.append(step["operation"])
    return seen


def recipe_keywords(src: Sources, workflow: dict) -> list[str]:
    words: list[str] = []
    for oid in recipe_ops(src, workflow):
        for alias in src.ops.get(oid, {}).get("aliases", []):
            if alias not in words:
                words.append(alias)
    return words[:24]


def recipe_body(src: Sources, workflow: dict, lang: str) -> str:
    en = lang == "en"
    wid = workflow["id"]
    desc = workflow["description"]
    heading_en = desc[0].upper() + desc[1:]
    positive = workflow["category"] == "positive"
    lines = [f"# {wid}", "",
             ("If the user wants: " if en else "ユーザーの要望: ") + (heading_en if en else T.RECIPE_JA[wid]),
             ("(EN) " + heading_en) if not en else "(JA) " + T.RECIPE_JA[wid], "",
             ("Families: " if en else "分野: ") + ", ".join(workflow["families"]), ""]
    fixtures = src.workflows["fixtures"]
    lines.append("## " + ("Inputs (import first)" if en else "入力（最初に取り込む）"))
    for name in workflow.get("fixtures", []):
        fx = fixtures[name]
        lines.append(f"- ${name}: cgal_artifact_import {jdump({'path': fx['path'], 'unit': fx['unit'], 'artifact_type': fx['type']})}")
    lines.append(("(Use your own file of the same artifact type and unit for real work.)" if en else
                  "（実作業では同じ型・単位の自分のファイルを使う。）"))
    lines += ["", "## " + ("Steps" if en else "手順")]
    for number, step in enumerate(workflow["steps"], 1):
        op = src.ops.get(step["operation"])
        summary = op["summary"] if op else "(unregistered on purpose)" if en else "（意図的に未登録）"
        lines.append(f"{number}. `{step['operation']}` ({step['id']}): {summary}")
        lines.append(f"   inputs {jdump({s: _placeholder(b) for s, b in step['inputs'].items()})}; parameters {jdump(step['parameters'])}")
    if "rules" in workflow:
        lines.append(("Planner rules: " if en else "プランナー規則: ") + jdump(workflow["rules"]))
    if "alternatives" in workflow:
        lines.append(("Declared fallbacks: " if en else "宣言済みの代替案: ") + str(len(workflow["alternatives"])) +
                     (" (tried in order only after a blocked, failed or rejected head plan)" if en else "（先頭のプランがブロック・失敗・却下された後にだけ順に試される）"))
    lines += ["", "## cgal_plan " + ("request" if en else "リクエスト"),
              "```json", jdump({"request": _plan_request(workflow)}), "```"]
    if workflow.get("limits"):
        lines.append(("Execute with execution=" if en else "実行時は execution=") + jdump(workflow["limits"]))
    expect = workflow["expect"]
    lines += ["", "## " + ("Expected outcome" if en else "期待される結果")]
    if positive:
        lines.append("job state `succeeded`; every inserted validator `pass`. Inspect job.outputs (type, unit, properties) and job.validation[].report." if en else
                     "jobのstateは`succeeded`、挿入された全検証器が`pass`。job.outputs（型・単位・properties）とjob.validation[].reportを読む。")
    else:
        lines.append(("Expected REFUSAL/FAILURE (demonstrates fail-closed behaviour): " if en else "期待されるのは拒否・失敗（fail-closed動作の実演）: ") + jdump(expect))
    return "\n".join(lines) + "\n"


def recipes_index(src: Sources, lang: str) -> str:
    en = lang == "en"
    lines = ["# " + ("Recipes: if the user wants X, do these steps" if en else "レシピ: ユーザーがXを望むならこの手順"), "",
             ("Each recipe is a verified workflow (run by the acceptance suite against the real worker). Read one with cgal_get_guide(topic=\"recipe:<id>\") "
              "or resource cgal://guide/recipe/<id>; it contains fixtures, the exact cgal_plan request and the expected outcome." if en else
              "各レシピは検証済みワークフロー（受入試験が実workerで実行）。cgal_get_guide(topic=\"recipe:<id>\")またはcgal://guide/recipe/<id>で読む。fixture、cgal_planのリクエスト全文、期待結果が載っている。"), "",
             "## " + ("Positive recipes" if en else "成功するレシピ")]
    for wf in src.positive_workflows():
        desc = wf["description"]
        chain = " -> ".join(recipe_ops(src, wf))
        lines.append(f"- {wf['id']}: " + (f"If the user wants: {desc[0].upper() + desc[1:]}" if en else f"要望: {T.RECIPE_JA[wf['id']]}"))
        lines.append(f"  {'EN' if not en else 'JA'}: " + (T.RECIPE_JA[wf["id"]] if en else desc))
        lines.append(f"  ops: {chain}")
        lines.append("  keywords: " + "; ".join(recipe_keywords(src, wf)))
    lines += ["", "## " + ("Expected refusals (fail-closed demonstrations)" if en else "期待される拒否・失敗（fail-closedの実演）")]
    for wf in src.negative_workflows():
        lines.append(f"- {wf['id']}: " + (wf["description"] if en else T.RECIPE_JA[wf["id"]]) + f" -> {jdump(wf['expect'])}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# Families / limits / status / errors / glossary / start
# --------------------------------------------------------------------------------------
def users_of_validators(src: Sources) -> dict[str, list[str]]:
    users: dict[str, list[str]] = {}
    for oid in sorted(src.ops):
        for vid in src.ops[oid]["validation"].get("validators", []):
            users.setdefault(vid, []).append(oid)
    return users


def family_ops(src: Sources) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {f: [] for f in T.FAMILIES}
    for oid in sorted(src.ops):
        result[src.family_of[oid]].append(oid)
    return result


def families_page(src: Sources, lang: str, ids: list[str] | None = None) -> str:
    en = lang == "en"
    fam_ops = family_ops(src)
    lines = ["# " + ("Families and operations" if en else "分野と操作の一覧"), ""]
    for fid in (ids or list(T.FAMILIES)):
        meta = T.FAMILIES[fid]
        ops = fam_ops[fid]
        main = [o for o in ops if src.ops[o]["role"] != "validator"]
        vals = [o for o in ops if src.ops[o]["role"] == "validator"]
        lines.append(f"## {fid} {meta[lang]} ({len(main)} " + ("operations" if en else "操作") + f" + {len(vals)} " + ("validators" if en else "検証器") + ")")
        lines.append(meta["use_en" if en else "use_ja"])
        for oid in main:
            op = src.ops[oid]
            ins = "+".join(s["types"][0] for s in op["io"]["inputs"])
            outs = "+".join(s["type"] for s in op["io"]["outputs"])
            lines.append(f"- {oid} [{op['role']}] {ins} -> {outs}: {op['summary']}")
        if vals:
            lines.append(("Validators (automatic): " if en else "検証器（自動）: ") + ", ".join(vals))
        lines.append("")
    return "\n".join(lines)


def limits_status_page(src: Sources, lang: str) -> str:
    en = lang == "en"
    counts: dict[str, int] = {}
    for op in src.ops.values():
        counts[op["status"]] = counts.get(op["status"], 0) + 1
    pk: dict[str, list[str]] = {"VALIDATED": [], "CATALOGED": [], "EXCLUDED": []}
    for name in sorted(src.packages):
        pk[src.packages[name]["status"]].append(name)
    lines = ["# " + ("Limits and honest coverage" if en else "上限と正直な対応範囲"), "",
             "## " + ("Operation status" if en else "操作の状態"),
             ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + f" (CGAL {src.cgal_version})",
             ("Only VALIDATED/IMPLEMENTED operations can execute. VALIDATED means replay-verified on bundled fixtures with an independent validator, not a proof for every input. "
              "Whole-system acceptance is tracked separately by the replay-bound evaluator (scripts/master_acceptance.py) and is not claimed by this guide." if en else
              "実行できるのはVALIDATED/IMPLEMENTEDの操作だけ。VALIDATEDは同梱fixtureで独立検証器つきの再実行に合格した意味で、全入力の証明ではない。"
              "システム全体の受入は再実行束縛の評価器（scripts/master_acceptance.py）が別に管理し、このガイドは達成を主張しない。"), "",
             "## " + ("Package catalog" if en else "パッケージ目録"),
             f"{len(src.packages)} CGAL packages: " + ", ".join(f"{k} {len(v)}" for k, v in pk.items()),
             ("VALIDATED = has at least one executable validated operation. CATALOGED = documentation/source indexed only, NOT executable. EXCLUDED = no standalone headless operation exists." if en else
              "VALIDATED=実行可能な検証済み操作が1つ以上ある。CATALOGED=文書・ソースの索引のみで実行不可。EXCLUDED=単独のヘッドレス操作が存在しない。"), "",
             "## " + ("Limits" if en else "上限"),
             f"- import: at most 512 MiB per file; formats off, obj, ply (ASCII), stl, xyz and typed json; units mm, cm or m (reports: none)",
             f"- execution defaults: concurrency {DEFAULT_CONCURRENCY}, worker memory {DEFAULT_MEMORY_MB} MiB, wall time {DEFAULT_WALL_TIME_MS // 1000} s, ceiling {MAX_WALL_TIME_MS // 1000} s; live values: cgal_system_health; per call: cgal_execute execution={{\"wall_time_ms\":..., \"memory_mb\":...}}"]
    face_bounds: dict[int, list[str]] = {}
    for oid in sorted(src.ops):
        faces = bounded_input(src.ops[oid]).get("maximum_faces")
        if faces is not None:
            face_bounds.setdefault(faces, []).append(oid)
    lines.append(("- per-operation face bounds (cards list each one): " if en else "- 操作ごとの面数上限（各カードに明記）: ") +
                 "; ".join(f"{k} faces: {len(v)} ops" for k, v in sorted(face_bounds.items())))
    tight = min(face_bounds)
    wide = face_bounds[400] if 400 in face_bounds else face_bounds[tight]
    lines.append(("- tightest common bound: " if en else "- 厳しい上限の例: ") + f"{400 if 400 in face_bounds else tight} faces: " + ", ".join(wide))
    lines += ["", "## " + ("Not supported (cataloged or excluded packages)" if en else "未対応（CATALOGEDまたはEXCLUDEDのパッケージ）"),
              ("When a request names one of these, cgal_capabilities_search/cgal_plan fail closed (unsupported_operation with details.unsupported_cgal_packages). "
               "Tell the user it is not supported; do not substitute a nearby operation silently." if en else
               "これらを名指しした要求は、cgal_capabilities_search/cgal_planがfail-closed（unsupported_operation、details.unsupported_cgal_packages）。"
               "ユーザーに未対応と伝え、近い操作を黙って代用しない。")]
    reasons = src.policy["reason_codes"]
    for status in ("CATALOGED", "EXCLUDED"):
        lines += ["", f"### {status}"]
        for name in pk[status]:
            code = src.packages[name]["reason_code"]
            gloss = [g for g in src.gloss.get(name, {}).get("ja", []) if re.search(r"[^\x00-\x7f]", g)]
            lines.append(f"- {name}: {code}" + (f" ({gloss[0]})" if (not en and gloss) else ""))
    lines += ["", "### " + ("Reason codes" if en else "理由コード")]
    for code in sorted(reasons):
        info = reasons[code]
        lines.append(f"- {code} ({info['status']}): {info['meaning']}")
    lines += ["", "### " + ("Validated packages" if en else "検証済みパッケージ"), ", ".join(pk["VALIDATED"])]
    return "\n".join(lines) + "\n"


def collect_error_groups(src: Sources) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {g["id"]: [] for g in T.ERROR_GROUPS}
    for code in src.error_codes:
        for group in T.ERROR_GROUPS:
            if any(code == m or (m.endswith("_") and code.startswith(m)) for m in group["match"]):
                groups[group["id"]].append(code)
                break
        else:
            raise AssertionError(f"error code {code!r} matches no guide group; add it to guide_texts.ERROR_GROUPS")
    return groups


def errors_page(src: Sources, lang: str) -> str:
    en = lang == "en"
    groups = collect_error_groups(src)
    lines = ["# " + ("Errors, refusals and how to react" if en else "エラー・拒否と対処"), "",
             ("Errors arrive as {class, code, message, recoverable, suggested_operations, details}. Fix the cause named by the code; never retry an unchanged request that failed with invalid_input, unmet_precondition, unsupported_adapter or validation_failure." if en else
              "エラーは {class, code, message, recoverable, suggested_operations, details} で届く。codeが示す原因を直す。invalid_input・unmet_precondition・unsupported_adapter・validation_failureの失敗を同じ要求のまま再試行しない。"), "",
             "## " + ("Job states" if en else "ジョブの状態")]
    for state, e, j in T.JOB_STATES:
        lines.append(f"- {state}: {e if en else j}")
    lines += ["", "## " + ("Failure classes" if en else "失敗クラス")]
    for name, e, j in T.FAILURE_CLASSES:
        lines.append(f"- {name}: {e if en else j}")
    lines += ["", "## " + ("Error codes by group" if en else "グループ別エラーコード")]
    for group in T.ERROR_GROUPS:
        lines += ["", f"### {group['en'] if en else group['ja']}",
                  ("Meaning: " if en else "意味: ") + group["means_en" if en else "means_ja"],
                  ("Do: " if en else "対処: ") + group["fix_en" if en else "fix_ja"]]
        for code in groups[group["id"]]:
            specific = T.ERROR_SPECIFIC.get(code)
            lines.append(f"- `{code}`" + (f": {specific[0 if en else 1]}" if specific else ""))
    lines += ["", "## " + ("Worker (CGAL-side) codes" if en else "worker（CGAL側）のコード"),
              ("UPPER_SNAKE_CASE codes come from the native worker or a validator and are operation specific, e.g. " if en else
               "UPPER_SNAKE_CASEのコードはnative workerや検証器由来で操作固有。例: ") +
              ", ".join(sorted({w["expect"]["code"] for w in src.negative_workflows() if w["expect"].get("code", "").isupper()})) + ".",
              ("Read error.class first (table above), then the code and message." if en else "まずerror.class（上表）、次にcodeとmessageを読む."), ""]
    return "\n".join(lines)


def glossary_page(src: Sources, lang: str) -> str:
    en = lang == "en"
    lines = ["# " + ("Glossary" if en else "用語集"), ""]
    for term, e, j, jdesc in T.GLOSSARY:
        lines.append(f"- {term if en else j}: {e if en else jdesc}")
    lines += ["", "## " + ("Artifact types" if en else "アーティファクトの型")]
    types: dict[str, set[str]] = {}
    for op in src.ops.values():
        for spec in op["io"]["inputs"]:
            for kind in spec["types"]:
                types.setdefault(kind, set())
        for spec in op["io"]["outputs"]:
            types.setdefault(spec["type"], set())
    for kind in sorted(types):
        lines.append(f"- {kind}: {type_note(kind, lang)}")
    lines += ["", "## " + ("Units and coordinates" if en else "単位と座標")]
    lines.append("- every geometry artifact carries a unit (mm, cm or m); reports are unitless ('none'). Units are never guessed or converted silently between artifacts; mixing units in one operation fails with unit_mismatch." if en else
                 "- 幾何artifactは必ず単位（mm/cm/m）を持つ。レポートは単位なし('none')。単位は推測せず、artifact間で黙って変換もしない。1操作で単位が混在するとunit_mismatch。")
    lines.append("- parameters written as TypedLength are converted to the input artifact's unit by the planner; the conversion is recorded in the plan." if en else
                 "- TypedLengthのパラメータはプランナーが入力artifactの単位へ変換し、変換をプランに記録する。")
    lines.append("- coordinates are right-handed Cartesian, stored as IEEE-754 binary64; face orientation is counter-clockwise seen from outside (outward normal); angles are degrees unless a card says otherwise." if en else
                 "- 座標は右手系直交座標、IEEE-754 binary64で保持。面の向きは外から見て反時計回り（外向き法線）。角度は特記なき限り度（deg）。")
    return "\n".join(lines) + "\n"


def start_page(src: Sources, lang: str, examples: dict[str, dict]) -> str:
    en = lang == "en"
    example = examples["hull.convex_3"]
    lines = ["# " + ("Quickstart" if en else "クイックスタート"), "",
             "## 1. " + ("Find the operation" if en else "操作を探す"),
             "- " + ("Known workflow? cgal_get_guide(topic=\"recipes\") then topic=\"recipe:<id>\". Otherwise cgal_capabilities_search(query=<goal in any language>)." if en else
                     "既知のワークフローか？ cgal_get_guide(topic=\"recipes\")→topic=\"recipe:<id>\"。違えばcgal_capabilities_search(query=<goalを任意の言語で>)。"),
             "- " + ("Read candidates: operation_id, status, score, why, input_types, output_types, route_supported. query_analysis.abstained=true means nothing relevant is executable: say so." if en else
                     "候補の読み方: operation_id・status・score・why・input_types・output_types・route_supported。query_analysis.abstained=trueは該当する実行可能な操作がないという意味。そのまま伝える。"),
             "- " + ("Then read the card: cgal_get_guide(topic=\"op:<operation_id>\") (parameters, units, limits, an example)." if en else
                     "次にカードを読む: cgal_get_guide(topic=\"op:<operation_id>\")（パラメータ・単位・上限・例）。"), "",
             "## 2. " + ("Import inputs" if en else "入力を取り込む"),
             "- " + ("cgal_artifact_import(path, unit, artifact_type?) copies the file into immutable storage and parses it (no repair). Returns artifact_id, type, unit, properties. The path must be readable by the server." if en else
                     "cgal_artifact_import(path, unit, artifact_type?)はファイルを不変ストアへ複製して解析する（修復はしない）。artifact_id・型・単位・propertiesを返す。pathはサーバから読めること。"),
             "- " + ("Pass artifact_type when the extension is ambiguous (json, xyz). Unit is mandatory: mm, cm or m." if en else
                     "拡張子だけで曖昧なとき（json、xyz）はartifact_typeを渡す。単位は必須でmm/cm/m。"), "",
             "## 3. " + ("Plan" if en else "プランを作る"),
             "- " + ("Single operation: cgal_plan(request={\"operation_id\": ..., \"inputs\": {<slot>: <artifact_id>}, \"parameters\": {...}}). Pipeline: request={\"steps\": [{\"id\", \"operation\", \"inputs\": {<slot>: <artifact_id> | {\"step\": id, \"slot\": output_slot}}, \"parameters\"}]}." if en else
                     "単一操作: cgal_plan(request={\"operation_id\": ..., \"inputs\": {<slot>: <artifact_id>}, \"parameters\": {...}})。パイプライン: request={\"steps\": [{\"id\", \"operation\", \"inputs\": {<slot>: <artifact_id> | {\"step\": id, \"slot\": 出力slot}}, \"parameters\"}]}。"),
             "- " + ("Mandatory validators are inserted for you; the plan lists them with estimate (cost tier, risk). Planning failures happen before any compute." if en else
                     "必須検証器は自動で挿入される。プランにはestimate（コスト階層・リスク）も載る。計画段階の失敗は計算前に起きる。"), "",
             "## 4. " + ("Execute and read" if en else "実行して読む"),
             "- " + ("cgal_execute(plan_id[, execution={\"wall_time_ms\", \"memory_mb\"}]) returns job_id at once. Poll cgal_job_status(job_id) every second or two until state is succeeded, rejected, failed or cancelled." if en else
                     "cgal_execute(plan_id[, execution={\"wall_time_ms\", \"memory_mb\"}])はすぐjob_idを返す。cgal_job_status(job_id)をstateがsucceeded/rejected/failed/cancelledになるまで1〜2秒おきに確認する。"),
             "- " + ("On succeeded: job.outputs[] hold artifact_id, type, unit, format, sha256, properties; job.validation[] hold each validator report. Report numbers from these, never invent them." if en else
                     "succeeded時: job.outputs[]にartifact_id・型・単位・形式・sha256・properties、job.validation[]に各検証器のレポート。数値はここから報告し、作り話をしない。"),
             "- " + ("cgal_artifact_inspect(artifact_id) for metadata and provenance; cgal_artifact_export(artifact_id, path) writes the exact bytes to a NEW path." if en else
                     "cgal_artifact_inspect(artifact_id)でメタデータと来歴、cgal_artifact_export(artifact_id, path)で正確なバイト列を新しいパスへ書き出す。"),
             "- " + ("rejected/failed: read job.error {class, code, message}; see topic 'errors'. Do not present rejected output as a result." if en else
                     "rejected/failed: job.error {class, code, message}を読む（topic 'errors'）。却下された出力を結果として示さない。"), "",
             "## 5. " + ("Worked example (hull.convex_3)" if en else "実例（hull.convex_3）")]
    lines += example_lines(example, lang)
    lines += ["", "## " + ("Rules of thumb" if en else "心得"),
              "- " + ("Never guess units, operation ids or parameters; read the card." if en else "単位・操作ID・パラメータを推測しない。カードを読む。"),
              "- " + ("If the server refuses, relay the refusal; do not work around validators or route to an unsupported package." if en else "サーバが拒否したら拒否をそのまま伝える。検証器の回避や非対応パッケージへの迂回をしない。"),
              "- " + ("Several goals match equally (ambiguous_route)? ask the user, then plan with operation_id." if en else "複数が同等（ambiguous_route）ならユーザーに尋ね、operation_idでplanする。"),
              "- " + ("Prompts: " + ", ".join(PROMPT_NAMES) + "." if en else "プロンプト: " + ", ".join(PROMPT_NAMES) + "。")]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# Server instructions
# --------------------------------------------------------------------------------------
def instructions_text(src: Sources, lang: str) -> str:
    en = lang == "en"
    n_ops = len(src.ops)
    n_val = sum(1 for o in src.ops.values() if o["role"] == "validator")
    n_main = n_ops - n_val
    statuses: dict[str, int] = {}
    for op in src.ops.values():
        statuses[op["status"]] = statuses.get(op["status"], 0) + 1
    pk: dict[str, int] = {}
    for p in src.packages.values():
        s = p["status"]
        pk[s] = pk.get(s, 0) + 1
    status_line = ", ".join(f"{v} {k}" for k, v in sorted(statuses.items()))
    fam = "; ".join(f"{fid} {T.FAMILIES[fid][lang]}" for fid in T.FAMILIES)
    types = sorted({t for op in src.ops.values() for spec in op["io"]["inputs"] for t in spec["types"]}
                   | {spec["type"] for op in src.ops.values() for spec in op["io"]["outputs"]})
    types_line = ", ".join(types)
    if en:
        return f"""CGAL Master MCP: a data-driven geometry server over CGAL {src.cgal_version}. It registers {n_ops} operations ({n_main} user-facing, {n_val} independent validators) in {len(T.FAMILIES)} families: {fam}. Every operation runs in an isolated native worker; every result must pass a mandatory validator before it is published.

CALL ORDER (do not skip)
1. cgal_get_guide(topic="start") once. It is the quickstart; topics: start, families, recipes, recipe:<id>, op:<operation_id>, family:<id>, errors, glossary, limits-and-status. lang="ja" gives Japanese. Resources cgal://guide/... and prompts ({', '.join(PROMPT_NAMES)}) carry the same content.
2. Discover: if the request matches a workflow, topic="recipes" lists verified recipes (if the user wants X, do these steps). Otherwise cgal_capabilities_search(query=<goal, any language>) then cgal_get_guide(topic="op:<operation_id>") for the complete card (parameters, units, limits, example call).
3. Import inputs: cgal_artifact_import(path, unit, artifact_type) with unit mm, cm or m (mandatory; never guessed). Formats: off, obj, ply, stl, xyz and typed json; at most 512 MiB. Files are parsed, never repaired.
4. cgal_plan(request): {{"operation_id", "inputs": {{slot: artifact_id}}, "parameters"}} or a {{"steps": [...]}} DAG wiring outputs with {{"step", "slot"}}. Validators are inserted automatically and cannot be skipped. Lengths are {{"value", "unit"}}.
5. cgal_execute(plan_id) returns a job at once; poll cgal_job_status until succeeded, rejected, failed or cancelled. Read results only from job.outputs (type, unit, properties) and job.validation[].report. cgal_artifact_export writes bytes to a NEW path.

STATUS VOCABULARY (be honest with the user)
Operations: {status_line}. VALIDATED means executable and replay-verified on bundled fixtures with an independent validator; it is evidence, not a proof for every input. Packages ({len(src.packages)} CGAL packages): {pk.get('VALIDATED', 0)} VALIDATED (have executable operations), {pk.get('CATALOGED', 0)} CATALOGED (documentation indexed only, NOT executable), {pk.get('EXCLUDED', 0)} EXCLUDED (no standalone headless operation: GUI-only, generic infrastructure, I/O only). Overall acceptance of this server is not claimed here.

CONVENTIONS
Units mm/cm/m per artifact; mixing units in one operation fails with unit_mismatch. Reports are unitless. Coordinates are right-handed Cartesian binary64; outward normals are counter-clockwise. Angles are degrees unless the card says otherwise.

TOOLS ({len(TOOL_NAMES)})
cgal_get_guide (CALL FIRST: guides, cards, recipes), cgal_capabilities_search (rank operations for a goal), cgal_capabilities_describe (raw registry definition), cgal_artifact_import / cgal_artifact_inspect / cgal_artifact_export (move data in and out), cgal_plan (typed immutable plan), cgal_execute / cgal_job_status / cgal_job_cancel (run, poll, stop), cgal_validate (re-check an artifact against its source), cgal_docs_search (pinned CGAL documentation index; documentation is not execution), cgal_system_health (limits, worker build, registry revision).

ARTIFACT TYPES
{types_line}. Operation cards name the exact type each input slot accepts and each output slot produces; a JSON report type is read, not imported.

FAIL-CLOSED BEHAVIOUR
The server refuses or fails with a coded error instead of guessing. rejected = a validator did not confirm the result (output unpublished). unmet_precondition = a documented bound or property failed before compute (for example the distance/Hausdorff operations accept at most 400 faces, except mesh.distance.symmetric_hausdorff with validation_mode certified_bvh: up to 2,000,000 faces; every card lists its bounds). resource_limit/timeout = shrink the input or raise execution={{"wall_time_ms","memory_mb"}} within cgal_system_health maxima. Never retry an unchanged request after invalid_input, unmet_precondition, unsupported_operation or validation failure. Unknown operations are refused; the server never generates C++ on demand.

AMBIGUITY
cgal_plan(goal=...) works only when one operation clearly fits. ambiguous_route (or unsupported_operation with details.options) carries a recorded question and options (operation_id, summary, distinguishing_concepts). Do not guess: ask the user which one, then re-plan with operation_id. Search with query_analysis.abstained=true means nothing executable fits.

NOT SUPPORTED
CATALOGED and EXCLUDED packages (topic "limits-and-status" lists them with reason codes) cannot run; requests naming them fail with details.unsupported_cgal_packages. Say so, offer the nearest executable operation as a question, never as a silent substitute. Other limits: defaults concurrency {DEFAULT_CONCURRENCY}, {DEFAULT_MEMORY_MB} MiB per worker, {DEFAULT_WALL_TIME_MS // 1000} s wall time (cgal_system_health shows live values). On error read topic="errors". Present only numbers that appear in job outputs or validation reports.
"""
    return f"""CGAL Master MCP: CGAL {src.cgal_version} 上のデータ駆動の幾何サーバ。{n_ops}個の操作（ユーザー向け{n_main}、独立検証器{n_val}）を{len(T.FAMILIES)}分野で登録: {fam}。全操作は隔離されたnative workerで動き、全結果は公開前に必須検証器の合格が必要。

呼び出し順序（飛ばさない）
1. cgal_get_guide(topic="start", lang="ja")を最初に1回。topic: start, families, recipes, recipe:<id>, op:<operation_id>, family:<id>, errors, glossary, limits-and-status。resource cgal://guide/ja/... とprompts（{', '.join(PROMPT_NAMES)}）も同内容。
2. 探す: 要望が既知ワークフローならtopic="recipes"（Xを望むならこの手順）。そうでなければcgal_capabilities_search(query=<goal、任意の言語>)→cgal_get_guide(topic="op:<operation_id>")で完全なカード（パラメータ・単位・上限・呼び出し例）。
3. 入力: cgal_artifact_import(path, unit, artifact_type)。unitはmm/cm/mで必須（推測しない）。形式: off, obj, ply, stl, xyz, 型付きjson。最大512MiB。解析のみで修復はしない。
4. cgal_plan(request): {{"operation_id", "inputs": {{slot: artifact_id}}, "parameters"}}、または出力を{{"step", "slot"}}でつなぐ{{"steps": [...]}} のDAG。検証器は自動挿入され省略不可。長さは{{"value", "unit"}}。
5. cgal_execute(plan_id)は即座にjobを返す。cgal_job_statusをsucceeded/rejected/failed/cancelledまで確認。結果はjob.outputs（型・単位・properties）とjob.validation[].reportからのみ読む。cgal_artifact_exportは新しいパスへバイト列を書く。

状態の語彙（ユーザーに正直に）
操作: {status_line}。VALIDATEDは実行可能で、同梱fixtureで独立検証器つきの再実行に合格した意味。全入力の証明ではない。パッケージ（CGAL {len(src.packages)}個）: VALIDATED {pk.get('VALIDATED', 0)}（実行可能な操作あり）、CATALOGED {pk.get('CATALOGED', 0)}（文書索引のみ。実行不可）、EXCLUDED {pk.get('EXCLUDED', 0)}（単独のヘッドレス操作なし: GUI専用・汎用基盤・I/Oのみ）。サーバ全体の受入達成はここでは主張しない。

規約
単位はartifactごとにmm/cm/m。1操作での単位混在はunit_mismatch。レポートは単位なし。座標は右手系直交・binary64、外向き法線は反時計回り。角度は特記なき限り度。

ツール（{len(TOOL_NAMES)}個）
cgal_get_guide（最初に呼ぶ: ガイド・カード・レシピ）、cgal_capabilities_search（goalに合う操作の順位付け）、cgal_capabilities_describe（レジストリ定義の原本）、cgal_artifact_import / cgal_artifact_inspect / cgal_artifact_export（データの出し入れ）、cgal_plan（型付き不変プラン）、cgal_execute / cgal_job_status / cgal_job_cancel（実行・確認・中止）、cgal_validate（既存artifactをsourceと再照合）、cgal_docs_search（固定されたCGAL文書索引。文書は実行ではない）、cgal_system_health（上限・workerビルド・レジストリrev）。

アーティファクトの型
{types_line}。操作カードに各入力slotが受ける型と各出力slotが作る型を明記。JSONレポート型は読むもので取り込むものではない。

fail-closed
推測せず、コード付きで拒否・失敗する。rejected=検証器が結果を確認できず出力は非公開。unmet_precondition=宣言済みの上限・性質が計算前に不成立（例: 距離/Hausdorff系は400面以下。ただしmesh.distance.symmetric_hausdorffはvalidation_mode=certified_bvhで2,000,000面まで。各カードに上限）。resource_limit/timeout=入力を小さくするか、cgal_system_healthの上限内でexecution={{"wall_time_ms","memory_mb"}}を指定。invalid_input・unmet_precondition・unsupported_operation・検証失敗の後に同じ要求を再試行しない。未知の操作は拒否され、C++をその場で生成しない。

曖昧さ
cgal_plan(goal=...)は1つの操作が明確に当てはまるときだけ。ambiguous_route（またはdetails.optionsつきunsupported_operation）は記録済みの質問と選択肢を持つ。推測せずユーザーに尋ね、operation_idで再plan。検索でquery_analysis.abstained=trueは実行可能な該当なしの意味。

未対応
CATALOGED/EXCLUDEDのパッケージ（topic "limits-and-status"に理由コード付きで一覧）は実行不可。名指しするとdetails.unsupported_cgal_packagesで失敗。その旨を伝え、最も近い実行可能な操作は質問として示し、黙って代用しない。既定: 同時実行{DEFAULT_CONCURRENCY}、worker {DEFAULT_MEMORY_MB}MiB、壁時間{DEFAULT_WALL_TIME_MS // 1000}秒（実値はcgal_system_health）。エラーはtopic="errors"。数値はjob出力・検証レポートにあるものだけを示す。
"""


# --------------------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------------------
PROMPT_SPECS: dict[str, dict] = {
    "start_here": {
        "args": [("request", "What the user wants, in their own words", True)],
        "recipes": [], "ops": [],
        "en": "The user asks: <<request>>\nWork through this with the CGAL Master MCP.\n1. cgal_get_guide(topic=\"start\").\n2. Check topic=\"recipes\" for a matching verified recipe; if one fits, read recipe:<id> and follow it with the user's own files.\n3. Otherwise cgal_capabilities_search(query=<request>), read the card with cgal_get_guide(topic=\"op:<id>\") for the best candidate, confirm units with the user if unknown.\n4. Import, cgal_plan, cgal_execute, poll cgal_job_status. Report only numbers from job outputs and validation reports.\n5. If the server refuses, relay the code and the remedy from topic=\"errors\"; for ambiguous_route ask the user which option they mean.",
        "ja": "ユーザーの要望: <<request>>\nCGAL Master MCPで進める。\n1. cgal_get_guide(topic=\"start\", lang=\"ja\")。\n2. topic=\"recipes\"で合う検証済みレシピを探し、あればrecipe:<id>を読んでユーザー自身のファイルで従う。\n3. なければcgal_capabilities_search(query=<要望>)→最有力候補をcgal_get_guide(topic=\"op:<id>\")で読む。単位が不明ならユーザーに確認。\n4. 取込み→cgal_plan→cgal_execute→cgal_job_statusで確認。数値はjob出力と検証レポートにあるものだけ報告。\n5. 拒否されたらコードとtopic=\"errors\"の対処を伝える。ambiguous_routeはどの選択肢かユーザーに尋ねる。"},
    "repair_and_simplify_mesh": {
        "args": [("mesh_path", "Path of the mesh file the server can read", True), ("unit", "mm, cm or m", True),
                 ("target_ratio", "Fraction of faces to keep, for example 0.5", False)],
        "recipes": ["wf05-dirtysoup-clean-orient-measure", "wf02-fillholes-loop-measures", "wf35-simplify-loop-inspect", "wf06-remesh-simplify-hausdorff-join"],
        "ops": ["mesh.inspect.pmp", "mesh.repair.polygon_soup", "mesh.repair.orient", "mesh.repair.stitch_borders",
                "mesh.analysis.boundary_cycles", "mesh.repair.fill_holes", "mesh.repair.remove_degenerate",
                "mesh.simplify.edge_collapse", "mesh.distance.symmetric_hausdorff"],
        "en": "Repair the mesh <<mesh_path>> (unit <<unit>>) and then simplify it to about <<target_ratio>> of its faces.\n1. Import it (artifact_type PolygonSoup3 if it is a soup, otherwise TriangleSurfaceMesh) with the stated unit.\n2. Inspect first (<<OPS>>: start with mesh.inspect.pmp) to learn what is wrong: open borders, flipped faces, degenerate faces, non-manifold parts.\n3. Repair only what the inspection shows. Holes are never filled blindly: list them first with mesh.analysis.boundary_cycles (hole_id, edge count, perimeter, area estimate, location), show that list to the user, ask which holes to close, and only then run mesh.repair.fill_holes with hole_ids (list first, ask the user, then fill by ids); unselected holes stay open. Verified recipes: <<RECIPES>>; read them with cgal_get_guide(topic=\"recipe:<id>\").\n4. Simplify with mesh.simplify.edge_collapse: its card (topic \"op:mesh.simplify.edge_collapse\") lists the required stop rule, policy, max_symmetric_deviation and hausdorff_error_bound. Non-manifold input is refused; meshes above the card's face bound are refused. If a collapse result self-intersects the integrity validator refuses it (nothing is published): retry with foldover_policy protect_and_retry (max_retry_rounds, accept_target_shortfall), which protects the edges around each intersection and reports the achieved face count and attempts; an unreachable target is refused with the best achievable count.\n5. The mandatory Hausdorff validator accepts at most 400 faces per mesh by default; for larger meshes (scans) pass hausdorff_validation_mode certified_bvh, which certifies a [lower, upper] bracket of the exact symmetric Hausdorff distance against max_symmetric_deviation. Report only validated numbers.",
        "ja": "メッシュ <<mesh_path>>（単位 <<unit>>）を修復し、面数を約 <<target_ratio>> に軽量化する。\n1. 指定単位で取り込む（ポリゴンスープならartifact_type PolygonSoup3、そうでなければTriangleSurfaceMesh）。\n2. まず検査（<<OPS>>: mesh.inspect.pmpから）で問題（開境界・反転・退化面・非多様体）を把握する。\n3. 検査で分かった問題だけを直す。穴は勝手に全部埋めない: まずmesh.analysis.boundary_cycles（hole_id・辺数・周長・面積目安・位置）で一覧し、一覧をユーザーに見せてどの穴を埋めるか確認し、そのあとでmesh.repair.fill_holesにhole_idsを渡して埋める（先に一覧、次に確認、最後にIDで指定）。選ばれなかった穴は開いたまま残る。検証済みレシピ: <<RECIPES>>。cgal_get_guide(topic=\"recipe:<id>\")で読む。\n4. mesh.simplify.edge_collapseで軽量化。カード（topic \"op:mesh.simplify.edge_collapse\"）に停止条件・policy・max_symmetric_deviation・hausdorff_error_boundが載っている。非多様体や面数上限超過は拒否される。縮退結果が自己交差すると検証器が拒否し何も公開されない: その場合はfoldover_policy=protect_and_retry（max_retry_rounds、accept_target_shortfall）で交差箇所周辺の辺を保護して再試行できる（達成面数と試行回数を報告し、目標に届かない場合は達成可能な最良面数つきで拒否される）。\n5. 必須のHausdorff検証は既定で各メッシュ400面以下。それより大きい（スキャン等）ときはhausdorff_validation_mode=certified_bvhを指定する（厳密な対称Hausdorff距離の[下限,上限]をmax_symmetric_deviationに対して保証）。検証済みの数値だけ報告する。"},
    "reconstruct_surface_from_points": {
        "args": [("points_path", "Path of the point file (xyz or ply with normals)", True), ("unit", "mm, cm or m", True)],
        "recipes": ["wf15-points-alphawrap-remesh-measures", "wf16-poisson-remesh-inspect", "wf17-outliers-grid-afsr-measures", "wf20-outlier-normals-orient"],
        "ops": ["pointset.remove_outliers", "pointset.normals.estimate", "pointset.normals.orient_mst", "reconstruction.alpha_wrap",
                "reconstruction.poisson", "reconstruction.advancing_front"],
        "en": "Reconstruct a surface from the points in <<points_path>> (unit <<unit>>).\n1. Import as PointSet3 (xyz) or PointSet3Normals (ply with normals).\n2. Clean first when noisy: <<OPS>> (outlier removal, normal estimation and orientation).\n3. Pick a method by the data: alpha wrapping for a watertight envelope, Poisson for oriented normals, advancing front for clean dense samples. Recipes: <<RECIPES>>.\n4. Read each chosen card (topic \"op:<id>\") for parameters; lengths need units.\n5. An empty or unverifiable reconstruction is a failure, not a result: report the error code instead of a surface.",
        "ja": "<<points_path>>（単位 <<unit>>）の点群から曲面を再構成する。\n1. PointSet3（xyz）またはPointSet3Normals（法線付きply）として取り込む。\n2. ノイズがあれば先に整える: <<OPS>>（外れ値除去・法線推定と向き付け）。\n3. データで手法を選ぶ: 水密な外皮ならalpha wrapping、向きの揃った法線があればPoisson、きれいで密な点ならadvancing front。レシピ: <<RECIPES>>。\n4. 選んだ操作のカード（topic \"op:<id>\"）でパラメータを確認。長さには単位が要る。\n5. 空や検証できない再構成は結果でなく失敗。曲面ではなくエラーコードを報告する。"},
    "validate_geometry": {
        "args": [("path", "Path of the geometry file", True), ("unit", "mm, cm or m", True), ("artifact_type", "For example TriangleSurfaceMesh", False)],
        "recipes": ["wf04-degenerate-remove-selfintersect", "wf01-soup-orient-loop-inspect"],
        "ops": ["mesh.inspect.pmp", "mesh.analysis.self_intersections", "mesh.analysis.connected_components", "mesh.analysis.measures", "mesh.analysis.normals"],
        "en": "Check whether <<path>> (unit <<unit>>, type <<artifact_type>>) is sound geometry.\n1. Import it exactly as given; a parse error (off_*/obj_*/ply_*/stl_*/xyz_*) already answers the question: relay it.\n2. Run the analysis operations (<<OPS>>) as separate cgal_plan calls; they only read.\n3. Summarize: closed or open, manifold or not, self-intersections, number of connected components, area and volume, with units from the outputs.\n4. Suggest repair operations only if a problem was found (topic \"families\", repair). Do not modify the input: every operation creates new artifacts. Recipes with checks: <<RECIPES>>.",
        "ja": "<<path>>（単位 <<unit>>、型 <<artifact_type>>）が健全な幾何かを調べる。\n1. そのまま取り込む。解析エラー（off_*/obj_*/ply_*/stl_*/xyz_*）が出ればそれが答えなので伝える。\n2. 解析操作（<<OPS>>）を個別のcgal_planで実行する（読み取りのみ）。\n3. 要約: 閉/開、多様体か、自己交差、連結成分数、面積・体積（単位は出力のもの）。\n4. 問題があったときだけ修復操作を提案（topic \"families\"の修復）。入力は変更しない（全操作が新しいartifactを作る）。検査を含むレシピ: <<RECIPES>>。"},
    "compare_meshes": {
        "args": [("reference_path", "Reference mesh file", True), ("candidate_path", "Candidate mesh file", True), ("unit", "mm, cm or m (both files)", True)],
        "recipes": ["wf38-union-simplify-compare", "wf06-remesh-simplify-hausdorff-join"],
        "ops": ["mesh.distance.hausdorff_bounded", "mesh.distance.symmetric_hausdorff", "mesh.distance.hausdorff_approximate", "mesh.analysis.measures"],
        "en": "Compare <<candidate_path>> against <<reference_path>> (both in <<unit>>).\n1. Import both as TriangleSurfaceMesh with the same unit; different units fail with unit_mismatch.\n2. Use the distance operations (<<OPS>>). The Hausdorff operations and their validators accept at most 400 faces each, except mesh.distance.symmetric_hausdorff with validation_mode certified_bvh (up to 2,000,000 faces per mesh; its validator reports certified_lower_bound, certified_upper_bound and certified_verdict).\n3. mesh.distance.symmetric_hausdorff needs tolerance and error_bound (lengths with units) and answers pass, fail or indeterminate: report indeterminate honestly.\n4. Add mesh.analysis.measures to each mesh for area/volume context. Recipes: <<RECIPES>>.",
        "ja": "<<candidate_path>>を<<reference_path>>と比較する（どちらも単位 <<unit>>）。\n1. 同じ単位のTriangleSurfaceMeshとして2つ取り込む。単位が違うとunit_mismatch。\n2. 距離系操作（<<OPS>>）を使う。Hausdorff系と検証器はどちらも400面以下。ただしmesh.distance.symmetric_hausdorffはvalidation_mode=certified_bvhで各メッシュ2,000,000面まで（検証器がcertified_lower_bound・certified_upper_bound・certified_verdictを報告）。\n3. mesh.distance.symmetric_hausdorffはtoleranceとerror_bound（単位付き長さ）が必要で、pass/fail/indeterminateを返す。indeterminateはそのまま正直に報告する。\n4. 面積・体積の文脈としてmesh.analysis.measuresも各メッシュに。レシピ: <<RECIPES>>。"},
    "2d_boolean_offset": {
        "args": [("polygon_path", "Path of the 2D polygon JSON file", True), ("unit", "mm, cm or m", True), ("offset", "Offset distance as a number in the stated unit", False)],
        "recipes": ["wf27-hull2-polygon-boolean", "wf28-hull2-minkowski"],
        "ops": ["polygon.boolean", "polygon.offset.interior", "polygon.offset.exterior", "polygon.minkowski_sum", "polygon.analysis.properties"],
        "en": "Do 2D polygon boolean and offset work on <<polygon_path>> (unit <<unit>>, offset <<offset>>).\n1. Import as Polygon2 or PolygonWithHoles2 (json) with the unit.\n2. Operations: <<OPS>>. Read each card (topic \"op:<id>\"): offsets take the distance as a typed length {\"value\", \"unit\"}; the guaranteed shapes are stated on the card (for example convex or axis-aligned polygons for offsets; non-covered inputs are refused, not approximated).\n3. For two polygons use polygon.boolean (join, intersection or difference as its card states) on the same unit.\n4. Recipes: <<RECIPES>>. Report areas and vertex counts only from outputs and validator reports.",
        "ja": "<<polygon_path>>（単位 <<unit>>、オフセット <<offset>>）に対し2D多角形のBooleanとオフセットを行う。\n1. Polygon2またはPolygonWithHoles2（json）として単位つきで取り込む。\n2. 操作: <<OPS>>。各カード（topic \"op:<id>\"）を読む。オフセットの距離は型付き長さ{\"value\", \"unit\"}。保証される形状はカードに明記（例: オフセットは凸や軸平行の多角形。対象外は近似せず拒否）。\n3. 2つの多角形はpolygon.boolean（カードの通りjoin/intersection/difference）。同じ単位で。\n4. レシピ: <<RECIPES>>。面積や頂点数は出力と検証レポートからだけ報告する。"},
    "choose_operation": {
        "args": [("goal", "The user's goal in plain words", True)],
        "recipes": [], "ops": [],
        "en": "Choose the right CGAL Master operation for: <<goal>>\n1. cgal_capabilities_search(query=<goal>, limit=8). If query_analysis.abstained is true, or unsupported_cgal_packages is present, tell the user it is not supported and why (topic \"limits-and-status\").\n2. Compare the top candidates: why, input_types versus the user's data, output_types, status. Read the cards (topic \"op:<id>\") of the best two.\n3. If several fit equally, ask the user one short question listing the options; do not pick silently.\n4. Confirm units and the input file type, then plan with operation_id.",
        "ja": "次の目的に合うCGAL Master操作を選ぶ: <<goal>>\n1. cgal_capabilities_search(query=<目的>, limit=8)。query_analysis.abstainedがtrue、またはunsupported_cgal_packagesがあれば、未対応であることと理由（topic \"limits-and-status\"）を伝える。\n2. 上位候補を比較: why、input_typesとユーザーのデータ、output_types、status。上位2つのカード（topic \"op:<id>\"）を読む。\n3. 同等に当てはまる複数があれば、選択肢を挙げて短く1つ質問する。黙って選ばない。\n4. 単位と入力ファイルの型を確認し、operation_idでplanする。"},
}


def build_prompts(src: Sources) -> dict[str, dict]:
    result = {}
    workflow_ids = {w["id"] for w in src.workflows["workflows"]}
    for name in PROMPT_NAMES:
        spec = PROMPT_SPECS[name]
        for oid in spec["ops"]:
            assert oid in src.ops, (name, oid)
        for wid in spec["recipes"]:
            assert wid in workflow_ids, (name, wid)
        entry = {"arguments": [{"name": n, "description": d, "required": r} for n, d, r in spec["args"]],
                 "recipes": spec["recipes"], "operations": spec["ops"], "template": {}}
        for lang in LANGS:
            entry["template"][lang] = (spec[lang].replace("<<OPS>>", ", ".join(spec["ops"]))
                                       .replace("<<RECIPES>>", ", ".join(spec["recipes"])))
        result[name] = entry
    return result


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------
def build_topics(root: Path) -> dict[str, Any]:
    src = Sources(root)
    examples = build_examples(src)
    users = users_of_validators(src)
    for oid, op in src.ops.items():
        if op["role"] != "validator":
            assert oid in examples, f"operation {oid} has no example"
    topics: dict[str, dict[str, str]] = {lang: {} for lang in LANGS}
    fam_ops = family_ops(src)
    for lang in LANGS:
        out = topics[lang]
        out["instructions"] = instructions_text(src, lang)
        out["start"] = start_page(src, lang, examples)
        out["families"] = families_page(src, lang)
        out["recipes"] = recipes_index(src, lang)
        out["errors"] = errors_page(src, lang)
        out["glossary"] = glossary_page(src, lang)
        out["limits-and-status"] = limits_status_page(src, lang)
        for fid in T.FAMILIES:
            out[f"family/{fid}"] = families_page(src, lang, [fid])
        for wf in src.workflows["workflows"]:
            out[f"recipe/{wf['id']}"] = recipe_body(src, wf, lang)
        for oid in sorted(src.ops):
            out[f"op/{oid}"] = op_card(src, oid, lang, examples, users)
    return {"schema_version": SCHEMA_VERSION, "cgal_version": src.cgal_version,
            "topics": topics, "prompts": build_prompts(src), "examples": examples,
            "counts": {"operations": len(src.ops), "families": len(T.FAMILIES),
                       "recipes": len(src.workflows["workflows"]),
                       "positive_recipes": len(src.positive_workflows()),
                       "error_codes": len(src.error_codes), "packages": len(src.packages)}}


def render_bundle(root: Path) -> str:
    return json.dumps(build_topics(root), ensure_ascii=False, sort_keys=True, indent=1) + "\n"


def doc_files(bundle: dict[str, Any]) -> dict[str, str]:
    """Human-readable snapshots committed under docs/master/guide/."""
    files: dict[str, str] = {}
    for lang in LANGS:
        topics = bundle["topics"][lang]
        for name in ("instructions",) + TOPIC_NAMES:
            files[f"{name}.{lang}.md"] = topics[name] if name == "instructions" else topics[name]
    prompts = []
    for name in PROMPT_NAMES:
        entry = bundle["prompts"][name]
        prompts.append(f"## {name}\narguments: {jdump(entry['arguments'])}\n\n### EN\n{entry['template']['en']}\n\n### JA\n{entry['template']['ja']}\n")
    files["prompts.md"] = "# Prompts\n\n" + "\n".join(prompts)
    return files
