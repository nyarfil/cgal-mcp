"""Runtime access to the generated AI-facing guide (a committed snapshot).

The snapshot ``guide/guide.json`` is produced by ``scripts/build_master_guide.py``
from the registry, catalog and workflow set; a unit test fails when it is stale.
Nothing here computes guide text, so serving it is cheap and deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import InvalidInput

LANGS = ("en", "ja")
STATIC_TOPICS = ("start", "families", "recipes", "errors", "glossary", "limits-and-status")
PATTERNS = ("op:<operation_id>", "recipe:<workflow_id>", "family:<7.x>")
DEFAULT_PATH = Path(__file__).with_name("guide") / "guide.json"
INDEX_TOPIC = "index"


def _key(topic: str) -> str:
    return topic.strip().replace(":", "/", 1)


class Guide:
    def __init__(self, path: Path | None = None):
        self.path = path or DEFAULT_PATH
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise InvalidInput("registry_schema", "Unsupported guide snapshot version")
        self.data: dict[str, Any] = data
        self.topics: dict[str, dict[str, str]] = data["topics"]
        self.prompts: dict[str, dict[str, Any]] = data["prompts"]

    # ------------------------------------------------------------------ topics
    def keys(self, lang: str = "en") -> list[str]:
        return sorted(self.topics[lang])

    def operation_ids(self) -> list[str]:
        return sorted(k[3:] for k in self.topics["en"] if k.startswith("op/"))

    def recipe_ids(self) -> list[str]:
        return sorted(k[7:] for k in self.topics["en"] if k.startswith("recipe/"))

    def family_ids(self) -> list[str]:
        return sorted((k[7:] for k in self.topics["en"] if k.startswith("family/")),
                      key=lambda value: tuple(int(p) for p in value.split(".")))

    def instructions(self, lang: str = "en") -> str:
        return self.topics[lang]["instructions"]

    def index_text(self, lang: str = "en") -> str:
        en = lang == "en"
        lines = ["# " + ("Guide index" if en else "ガイド目次"), "",
                 ("Topics: " if en else "topic: ") + ", ".join(STATIC_TOPICS) + ", instructions, index",
                 ("Patterns: " if en else "パターン: ") + ", ".join(PATTERNS),
                 ("Families: " if en else "分野: ") + ", ".join(self.family_ids()),
                 ("Operations (" + str(len(self.operation_ids())) + "): " if en else f"操作（{len(self.operation_ids())}個）: ")
                 + ", ".join(self.operation_ids()),
                 ("Recipes: " if en else "レシピ: ") + ", ".join(self.recipe_ids())]
        return "\n".join(lines) + "\n"

    def get(self, topic: str, lang: str = "en") -> str:
        if lang not in LANGS:
            raise InvalidInput("guide_topic", f"lang must be one of {', '.join(LANGS)}")
        if not isinstance(topic, str) or not topic.strip():
            raise InvalidInput("guide_topic", "topic must be a non-empty string",
                               {"available": list(STATIC_TOPICS) + [INDEX_TOPIC], "patterns": list(PATTERNS)})
        if topic.strip() == INDEX_TOPIC:
            return self.index_text(lang)
        key = _key(topic)
        if key not in self.topics[lang]:
            raise InvalidInput("guide_topic", f"Unknown guide topic: {topic}",
                               {"available": list(STATIC_TOPICS) + [INDEX_TOPIC, "instructions"],
                                "patterns": list(PATTERNS)})
        return self.topics[lang][key]

    def get_tool_result(self, topic: str, lang: str = "en") -> dict[str, Any]:
        text = self.get(topic, lang)
        return {"topic": topic.strip(), "lang": lang, "format": "markdown", "text": text,
                "more": {"topics": list(STATIC_TOPICS) + [INDEX_TOPIC], "patterns": list(PATTERNS)}}

    # ----------------------------------------------------------------- prompts
    def render_prompt(self, name: str, lang: str = "en", **arguments: Any) -> str:
        if name not in self.prompts or lang not in LANGS:
            raise InvalidInput("guide_topic", f"Unknown prompt: {name}")
        entry = self.prompts[name]
        text = entry["template"][lang]
        for spec in entry["arguments"]:
            value = arguments.get(spec["name"])
            filled = str(value) if value not in (None, "") else ("(not specified)" if lang == "en" else "（未指定）")
            text = text.replace(f"<<{spec['name']}>>", filled)
        return text
