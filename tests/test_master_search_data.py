"""Authored search phrases: coverage, bilingual shape and non-interference."""
import json
import re
import unittest
from pathlib import Path

from cgal_mcp.master.registry import OperationRegistry
from cgal_mcp.master.search import PhraseIndex, retrieval_tokens

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "cgal_mcp" / "master" / "search_data.json"
JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")


class SearchDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = json.loads(DATA.read_text(encoding="utf-8"))
        cls.registry = OperationRegistry()

    def test_every_registered_operation_has_bilingual_phrases(self):
        data = self.document["operations"]
        self.assertEqual(set(data), set(self.registry.operations))
        for operation_id, phrases in data.items():
            self.assertTrue(phrases, operation_id)
            self.assertTrue(all(isinstance(item, str) and item.strip() for item in phrases), operation_id)
            self.assertTrue(any(JAPANESE.search(item) for item in phrases), operation_id)
            self.assertTrue(any(re.search(r"[a-z]", item) and not JAPANESE.search(item)
                                for item in phrases), operation_id)
            self.assertEqual(len(phrases), len(set(phrases)), operation_id)

    def test_phrases_are_not_operation_identifiers_or_corpus_text(self):
        corpus = json.loads((ROOT / "tests/fixtures/master/search_intents.json").read_text(encoding="utf-8"))
        queries = {item["query"].casefold() for item in corpus["intents"]}
        for operation_id, phrases in self.document["operations"].items():
            for phrase in phrases:
                self.assertNotEqual(phrase, operation_id)
                self.assertNotIn(phrase.casefold(), queries, operation_id)

    def test_phrases_do_not_change_registry_identity(self):
        # The pinned registry revision covers operations and policies only.
        self.assertTrue(self.registry.search_phrases)
        again = OperationRegistry()
        self.assertEqual(self.registry.revision, again.revision)

    def test_phrase_index_scores_known_and_ignores_unknown_operations(self):
        others = {f"o.{n}": (f"unrelated word{n} thing{n}",) for n in range(12)}
        index = PhraseIndex({"x.y": ("shrink the lattice",), **others})
        self.assertGreater(index.bonus("x.y", "please shrink the lattice now"), 0.0)
        self.assertEqual(index.bonus("missing.op", "shrink the model"), 0.0)

    def test_tokens_mix_english_stems_and_japanese_bigrams(self):
        tokens = retrieval_tokens("Simplification of 三角形メッシュ")
        self.assertIn("ja:三角", tokens)
        self.assertTrue(any(token.startswith("simplif") for token in tokens))

    def test_paraphrase_finds_operation_without_alias_overlap(self):
        result = self.registry.search("delete stray floating dust points around a scan",
                                      limit=3, discovery=True)
        self.assertIn("pointset.remove_outliers", [c["operation_id"] for c in result["candidates"]])


if __name__ == "__main__":
    unittest.main()
