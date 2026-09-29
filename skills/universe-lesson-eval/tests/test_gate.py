"""Synthetic local fixtures only; these are not NB Universe product findings."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from report_gate import freeze, validate


def build_fixture(root):
    plan = {"version": 1, "audit_id": "synthetic-audit",
            "scope": {"topic": "fixture", "version": "fixture", "url": "http://localhost/#/modules/fixture",
                      "environment": "synthetic fixture only"},
            "inventory": [{"node_id": "n1", "required_rules": ["CONTENT-01"]}],
            "cases": [{"id": "c1", "title": "copy", "node": "n1", "rule_id": "CONTENT-01",
                       "source": "fixture#p1", "expected": "exact text", "critical": True,
                       "required_evidence": ["blackbox"], "blackbox_method": "visual",
                       "state": "fixture opened", "steps": ["read fixture"],
                       "viewport": {"width": 1024, "height": 768}, "allow_not_applicable": False}]}
    (root / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    lock = freeze(root / "plan.json", root / "lock.json")
    (root / "capture.txt").write_text("synthetic fixture only", encoding="utf-8")
    report = {"version": 1, "audit_id": "synthetic-audit", "executor": "executor-a",
              "plan_sha256": lock["plan_sha256"], "results": [{"id": "c1", "status": "pass",
              "reason": "fixture observed", "evidence": [{"kind": "blackbox", "path": "capture.txt",
              "executor": "executor-a", "observation": "fixture text", "source": plan["scope"]["url"],
              "steps": ["fixture step"], "method": "visual"}]}]}
    return plan, report


class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan_path, self.report_path, self.lock_path = [self.root / name for name in
                                                         ("plan.json", "report.json", "lock.json")]
        self.plan, self.report = build_fixture(self.root)

    def write(self, path, data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def check(self):
        self.write(self.report_path, self.report)
        return validate(self.plan_path, self.report_path, self.lock_path)

    def test_valid_complete_report(self):
        result = self.check()
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["accepted"])

    def test_missing_extra_duplicate_results(self):
        original = copy.deepcopy(self.report["results"])
        for rows in ([], original * 2, original + [{**original[0], "id": "extra"}]):
            with self.subTest(rows=rows):
                self.report["results"] = rows
                self.assertFalse(self.check()["valid"])

    def test_mutated_frozen_plan(self):
        self.plan["cases"][0]["critical"] = False
        self.write(self.plan_path, self.plan)
        self.assertFalse(self.check()["valid"])

    def test_initial_missing_node_or_rule_is_rejected(self):
        for missing in ({"node_id": "n2", "required_rules": ["CONTENT-01"]},
                        {"node_id": "n2", "required_rules": []}):
            with self.subTest(missing=missing):
                self.plan["inventory"].append(missing)
                self.write(self.plan_path, self.plan)
                with self.assertRaises(ValueError):
                    freeze(self.plan_path, self.root / "other-lock.json")
                self.plan["inventory"].pop()

    def test_missing_blackbox_file_or_required_channel(self):
        result = self.report["results"][0]
        for evidence in ([], [{**result["evidence"][0], "path": "missing.png"}]):
            with self.subTest(evidence=evidence):
                result["evidence"] = evidence
                self.assertFalse(self.check()["valid"])

    def test_failure_and_unverified_cannot_average_away(self):
        for status in ("fail", "unverified"):
            with self.subTest(status=status):
                self.report["results"][0]["status"] = status
                checked = self.check()
                self.assertTrue(checked["valid"], checked)
                self.assertFalse(checked["accepted"])
                self.assertEqual(checked["critical_blockers"], ["c1"])

    def test_no_late_not_applicable_or_unknown_status(self):
        for status in ("not_applicable", "skipped", "PASS"):
            self.report["results"][0]["status"] = status
            self.assertFalse(self.check()["valid"])

    def test_separate_evidence_executors_are_supported(self):
        evidence = self.report["results"][0]["evidence"][0]
        evidence["executor"] = "another-agent"
        self.assertTrue(self.check()["valid"])
        evidence["method"] = "listening"
        self.assertFalse(self.check()["valid"])

    def test_not_applicable_requires_a_frozen_reason(self):
        self.plan["cases"][0]["allow_not_applicable"] = True
        self.write(self.plan_path, self.plan)
        with self.assertRaises(ValueError):
            freeze(self.plan_path, self.root / "new-lock.json")

    def test_planned_audio_stage_not_applicable_does_not_block(self):
        case = self.plan["cases"][0]
        case.update(allow_not_applicable=True,
                    not_applicable_reason="音频后置，本轮尚未接入")
        self.write(self.plan_path, self.plan)
        self.lock_path = self.root / "audio-stage-lock.json"
        self.report["plan_sha256"] = freeze(self.plan_path, self.lock_path)["plan_sha256"]
        self.report["results"][0].update(
            status="not_applicable", reason="音频后置，本轮尚未接入", evidence=[])
        checked = self.check()
        self.assertTrue(checked["valid"], checked)
        self.assertTrue(checked["accepted"], checked)
        self.assertEqual(checked["counts"]["not_applicable"], 1)

    def test_listening_cannot_be_proved_by_screenshot(self):
        self.plan["cases"][0]["blackbox_method"] = "listening"
        self.write(self.plan_path, self.plan)
        self.lock_path = self.root / "listening-lock.json"
        self.report["plan_sha256"] = freeze(self.plan_path, self.lock_path)["plan_sha256"]
        evidence = self.report["results"][0]["evidence"][0]
        evidence.update(method="listening", path="capture.png")
        (self.root / "capture.png").write_bytes(b"synthetic screenshot fixture")
        for status in ("pass", "fail"):
            self.report["results"][0]["status"] = status
            self.assertFalse(self.check()["valid"])

    def test_freeze_refuses_overwrite(self):
        before = self.lock_path.read_bytes()
        with self.assertRaises(FileExistsError):
            freeze(self.plan_path, self.lock_path)
        self.assertEqual(before, self.lock_path.read_bytes())

    def test_duplicate_json_key_is_rejected(self):
        self.plan_path.write_text('{"version":1,"version":1}', encoding="utf-8")
        self.assertFalse(self.check()["valid"])


if __name__ == "__main__":
    unittest.main()
