"""Recognition of requests that name a CGAL package the catalog records as not supported.

The package catalog (catalog/packages.json) carries a status and a reason code per
official CGAL chapter.  A chapter that is CATALOGED because its algorithm adapter is not
implemented is known but unsupported: a request for it must fail closed with that reason
instead of being answered by the nearest supported operation.  Recognition uses only
(1) the chapter's own title as a contiguous stemmed phrase and (2) the authored gloss in
unsupported_gloss.json (distinctive title terms and their Japanese renderings).  No
evaluation query text is used.  Recognition is for refusal only: it never routes or
executes anything.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .search import _canonical_word, normalize

_ALGORITHM_REASONS = frozenset({"algorithm_adapter_not_implemented"})
_DIMENSION = re.compile(r"^(?:2d|3d|dd)$")
_WORD = re.compile(r"[a-z][a-z0-9]*|\d+d")
_FUNCTION_WORDS = frozenset({"and", "of", "the", "on", "in", "for"})


def _words(text: str) -> list[str]:
    return [_canonical_word(word) for word in _WORD.findall(normalize(text))]


def _contains_sequence(words: list[str], phrase: list[str]) -> bool:
    size = len(phrase)
    return size > 0 and any(words[i:i + size] == phrase for i in range(len(words) - size + 1))


class UnsupportedPackageIndex:
    def __init__(self, packages: list[dict[str, Any]], gloss: dict[str, Any]):
        self.entries: list[dict[str, Any]] = []
        for package in packages:
            if (package.get("status") != "CATALOGED"
                    or package.get("reason_code") not in _ALGORITHM_REASONS):
                continue
            title_words = [w for w in _words(str(package.get("title", ""))
                                              .replace("(", " ").replace(")", " "))
                           if w not in _FUNCTION_WORDS]
            phrases: list[list[str]] = []
            # A title that is only a dimension plus one generic word is too common to match alone.
            # match_title=false: PCA is a method inside supported operations (normal estimation),
            # so naming it must not refuse the request.
            if gloss.get(package["id"], {}).get("match_title", True) and (
                    len(title_words) >= 3 or len(title_words) == 2 and not _DIMENSION.match(title_words[0])):
                phrases.append(title_words)
            terms = gloss.get(package["id"], {})
            en = [_words(term) for term in terms.get("en", [])]
            ja = [normalize(term).replace("の", "") for term in terms.get("ja", [])]
            self.entries.append({
                "package": package["id"], "title": package.get("title"),
                "status": package["status"], "reason_code": package["reason_code"],
                "reason": package.get("reason"),
                "phrases": phrases + [p for p in en if p], "ja": ja})

    @classmethod
    def load(cls, catalog_root: Path) -> "UnsupportedPackageIndex | None":
        gloss_path = Path(__file__).with_name("unsupported_gloss.json")
        try:
            packages = json.loads((catalog_root / "packages.json").read_text(encoding="utf-8"))["packages"]
            gloss = json.loads(gloss_path.read_text(encoding="utf-8")).get("packages", {})
        except (OSError, ValueError, KeyError, TypeError):
            return None
        return cls(packages, gloss)

    def recognize(self, query: str) -> list[dict[str, Any]]:
        words = _words(query)
        normalized = normalize(query).replace("の", "")  # particle-insensitive
        found = []
        for entry in self.entries:
            matched = next((" ".join(p) for p in entry["phrases"] if _contains_sequence(words, p)), None)
            if matched is None:
                matched = next((term for term in entry["ja"] if term and term in normalized), None)
            if matched is not None:
                found.append({"package": entry["package"], "title": entry["title"],
                              "status": entry["status"], "reason_code": entry["reason_code"],
                              "reason": entry["reason"], "matched": matched})
        return found
