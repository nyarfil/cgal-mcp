"""Regression checks for independent bilingual vocabulary and query safety."""
import sqlite3
import unittest
from contextlib import closing

from cgal_mcp.master.search import (document_terms, fts_expression, lexical_score,
                                    normalize, parse_query)


class SearchTermsTests(unittest.TestCase):
    def test_japanese_embedded_actions_are_not_one_unmatchable_token(self):
        query = parse_query("この点群の外れ値を除去して法線も計算したい")
        self.assertEqual(query.concepts, {"outliers", "normals", "point_normals"})
        score, shared = lexical_score(query, "pointset.remove_outliers 点群 外れ値除去")
        self.assertGreater(score, 0)
        self.assertEqual(shared, {"outliers"})

    def test_english_boundaries_do_not_match_normal_in_abnormal(self):
        self.assertNotIn("normals", parse_query("abnormal geometry").concepts)
        self.assertNotIn("union", parse_query("reunion of engineers").concepts)
        self.assertIn("normals", parse_query("estimate normals for scans").concepts)

    def test_specific_concepts_do_not_fall_back_to_contained_action(self):
        self.assertEqual(parse_query("Find self-intersections").concepts, {"self_intersection"})
        self.assertEqual(parse_query("straight skeleton").concepts, {"straight_skeleton"})
        self.assertEqual(parse_query("凸分解").concepts, {"convex_decomposition"})

    def test_document_identifiers_and_query_morphology_match(self):
        self.assertIn("normals", document_terms("estimate_normals").concepts)
        score, _ = lexical_score(parse_query("Find the connected components"),
                                  "mesh.analysis.connected_components")
        self.assertGreater(score, 0)
        self.assertEqual(normalize("ＰＣＡ　Normals"), "pca normals")

    def test_stopwords_do_not_create_geometry_candidates(self):
        query = parse_query("Which supported capability best fits the data?")
        self.assertFalse(query.words)
        self.assertFalse(query.concepts)
        self.assertIsNone(fts_expression(query))

    def test_fts_metacharacters_are_not_operators(self):
        expression = fts_expression(parse_query('"normals" OR NEAR(foo bar)'))
        self.assertIsNotNone(expression)
        self.assertNotIn('NEAR(', expression)
        self.assertNotIn('"or"', expression)
        self.assertIn('"normals"', expression)
        with closing(sqlite3.connect(":memory:")) as database:
            database.execute("CREATE VIRTUAL TABLE docs USING fts5(text,tokenize='trigram')")
            database.execute("INSERT INTO docs(text) VALUES('estimate normals')")
            self.assertEqual(database.execute("SELECT text FROM docs WHERE docs MATCH ?",
                                             (expression,)).fetchall(), [("estimate normals",)])

    def test_two_dimensional_intent_does_not_lose_dimension(self):
        self.assertIn("2d", parse_query("create a 2D convex hull").words)
        self.assertIn("3d", parse_query("3D mesh").words)

    def test_remeshing_vocabulary_is_bilingual_and_hole_stages_are_not_global_refinement(self):
        for text, concept in (("isotropic remeshing", "isotropic"), ("等方的に再メッシュ", "isotropic"),
                              ("refine the mesh", "mesh_refinement"), ("メッシュを細分", "mesh_refinement"),
                              ("split long edges", "split_long_edges"), ("長い辺を分割", "split_long_edges"),
                              ("adaptive sizing field", "adaptive_sizing"), ("曲率に応じて適応", "adaptive_sizing")):
            self.assertIn(concept, parse_query(text).concepts, text)
        self.assertNotIn("mesh_refinement", parse_query("triangulate and refine every hole").concepts)
        self.assertEqual(parse_query("頂点位置を平滑化して最適化").concepts, {"smoothing"})


if __name__ == "__main__":
    unittest.main()
