import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from compare_copy import compare


class CopyTests(unittest.TestCase):
    def setUp(self):
        self.data = {"version": 1, "comparisons": [{"id": "text-1",
                     "source": {"anchor": "fixture#p1", "paragraph": "温度不是 10 K。"},
                     "expected": "温度不是 10 K。", "actual": "温度不是 10 K。", "actual_origin": "fixture"}]}

    def test_exact_match_does_not_claim_runtime_verification(self):
        result = compare(self.data)
        self.assertFalse(result["runtime_verified"])
        self.assertEqual(result["comparisons"][0]["comparison"], "match")

    def test_version_requires_integer_one(self):
        for version in (True, False, 1.0, "1", None):
            with self.subTest(version=version):
                self.data["version"] = version
                with self.assertRaisesRegex(ValueError, "version"):
                    compare(self.data)

    def test_negation_number_unit_and_punctuation_are_retained(self):
        for actual in ("温度是 10 K。", "温度不是 11 K。", "温度不是 10 °C。", "温度不是 10 K!"):
            with self.subTest(actual=actual):
                self.data["comparisons"][0]["actual"] = actual
                self.assertEqual(compare(self.data, True)["comparisons"][0]["comparison"], "candidate_difference")

    def test_whitespace_is_explicit_and_preserves_boundaries(self):
        self.data["comparisons"][0]["actual"] = "\n温度不是\t 10\n K。 "
        self.assertEqual(compare(self.data)["comparisons"][0]["comparison"], "candidate_difference")
        self.assertEqual(compare(self.data, True)["comparisons"][0]["comparison"], "match")
        self.data["comparisons"][0]["actual"] = "温度不是 1 0 K。"
        self.assertEqual(compare(self.data, True)["comparisons"][0]["comparison"], "candidate_difference")

    def test_empty_actual_is_a_difference(self):
        self.data["comparisons"][0]["actual"] = ""
        self.assertEqual(compare(self.data)["comparisons"][0]["comparison"], "candidate_difference")

    def test_empty_duplicate_and_missing_source_rejected(self):
        for data in ({"version": 1, "comparisons": []},
                     {"version": 1, "comparisons": self.data["comparisons"] * 2},
                     copy.deepcopy(self.data)):
            if len(data["comparisons"]) == 1:
                del data["comparisons"][0]["source"]
            with self.assertRaises(ValueError):
                compare(data)

    def test_breath_rhythm_and_prohibited_terms_detected(self):
        long_sentence = "热的等离子体物质从内部上升到表面冷却后又下沉形成了米粒组织。"
        self.data["comparisons"][0]["actual"] = long_sentence
        self.data["comparisons"][0]["expected"] = long_sentence
        res = compare(self.data)
        metrics = res["comparisons"][0]["metrics"]
        self.assertTrue(any(w["length"] > 18 for w in metrics["breath_rhythm_warnings"]))
        self.assertGreater(metrics["max_clause_length"], 18)

        # Prohibited terms test
        term_sentence = "我们可以在这里观测三体运动规律。"
        self.data["comparisons"][0]["actual"] = term_sentence
        self.data["comparisons"][0]["expected"] = term_sentence
        res2 = compare(self.data)
        metrics2 = res2["comparisons"][0]["metrics"]
        self.assertTrue(any(w["term"] == "三体运动" for w in metrics2["prohibited_term_warnings"]))


if __name__ == "__main__":
    unittest.main()
