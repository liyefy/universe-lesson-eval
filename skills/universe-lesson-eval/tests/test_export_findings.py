"""Synthetic local fixtures only; these findings must never be sent to Feishu."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from export_findings import export_findings


class ExportFindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan_path, self.report_path, self.lock_path = [self.root / name for name in (
            "plan.json", "report.json", "lock.json")]
        self.plan = {"version": 1, "audit_id": "synthetic-eval-test", "scope": {
            "topic": "synthetic", "version": "fixture-v1", "url": "http://localhost/#/modules/earth",
            "environment": "synthetic-only"}, "inventory": [{"node_id": "n1",
            "required_rules": ["CONTENT-01"]}], "cases": [{"id": "c1", "title": "测试项",
            "node": "n1", "rule_id": "CONTENT-01", "source": "fixture.md#p1",
            "expected": "作答后可继续", "critical": True, "required_evidence": ["blackbox"],
            "blackbox_method": "visual", "state": "仅供工具测试：练习第一题尚未作答",
            "steps": ["打开练习第一题", "选择错误答案"], "viewport": {"width": 1024, "height": 768},
            "allow_not_applicable": False}]}
        self.write(self.plan_path, self.plan)
        subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "report_gate.py"), "freeze",
                        str(self.plan_path), str(self.lock_path)], check=True, capture_output=True)
        digest = json.loads(self.lock_path.read_text(encoding="utf-8"))["plan_sha256"]
        for name in ("capture.txt", "review.md"):
            (self.root / name).write_text("Synthetic fixture only; not a real product observation.", encoding="utf-8")
        self.finding = {"kind": "product", "certainty": "confirmed", "topic": None,
            "summary": "答错第一题后无法继续完成本轮练习", "location": "练习第一题",
            "environment": "仅供工具测试的合成数据", "steps": ["选择错误答案"],
            "actual": "下一题不能点击", "expected": "作答后可继续", "impact": "无法完成本轮",
            "evidence_summary": "合成示例，不是真实缺陷", "boundary": "只验证转换器",
            "engineering": "src/private.tsx useFrame P1 must stay local",
            "review": {"reviewer": "reviewer-b", "confirmed": True, "reason": "测试复核门禁",
                       "evidence": ["review.md"]}}
        self.report = {"version": 1, "audit_id": "synthetic-eval-test", "executor": "executor-a",
            "plan_sha256": digest, "results": [{"id": "c1", "status": "fail", "reason": "测试复现",
            "evidence": [{"kind": "blackbox", "path": "capture.txt", "observation": "示例现象",
            "executor": "executor-a", "source": self.plan["scope"]["url"], "steps": ["模拟步骤"],
            "method": "visual"}], "finding": self.finding}]}

    def write(self, path, document):
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def export(self):
        self.write(self.report_path, self.report)
        return export_findings(self.plan_path, self.report_path, self.lock_path)

    def test_confirmed_failure_exports_without_product_acceptance(self):
        document, warnings = self.export()
        self.assertEqual(document["findings"][0]["certainty"], "confirmed")
        self.assertEqual(warnings, [])
        detail = document["findings"][0]["description"]
        self.assertIn("下一题不能点击", detail)
        self.assertNotIn("src/private.tsx", detail)
        self.assertNotIn("useFrame", detail)

    def test_unreviewed_failure_rejected(self):
        del self.finding["review"]
        with self.assertRaisesRegex(ValueError, "review required"):
            self.export()

    def test_self_review_rejected(self):
        self.finding["review"]["reviewer"] = " Executor-A "
        with self.assertRaisesRegex(ValueError, "independent"):
            self.export()

    def test_evidence_executor_cannot_review(self):
        self.report["results"][0]["evidence"][0]["executor"] = "reviewer-b"
        with self.assertRaisesRegex(ValueError, "independent"):
            self.export()

    def test_missing_review_artifact_rejected(self):
        self.finding["review"]["evidence"] = ["missing.md"]
        with self.assertRaisesRegex(ValueError, "nonempty file"):
            self.export()

    def test_outside_review_artifact_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            path = Path(outside) / "review.md"
            path.write_text("synthetic", encoding="utf-8")
            self.finding["review"]["evidence"] = [str(path)]
            with self.assertRaisesRegex(ValueError, "inside report"):
                self.export()

    def test_unconfirmed_and_environment_findings_stay_local(self):
        for field, value in (("certainty", "suspected"), ("kind", "environment")):
            old = self.finding[field]
            self.finding[field] = value
            self.assertEqual(self.export()[0]["findings"], [])
            self.finding[field] = old

    def test_pass_with_stale_finding_does_not_export(self):
        self.report["results"][0]["status"] = "pass"
        self.assertEqual(self.export()[0]["findings"], [])

    def test_changed_plan_rejected(self):
        self.plan["cases"][0]["critical"] = False
        self.write(self.plan_path, self.plan)
        with self.assertRaisesRegex(ValueError, "Report gate rejected"):
            self.export()

    def test_technical_wording_warns_without_claiming_readability(self):
        self.finding["summary"] = "DOM 挡住下一题按钮"
        document, warnings = self.export()
        self.assertEqual(len(document["findings"]), 1)
        self.assertTrue(any("human readability" in warning for warning in warnings))

    def test_writer_short_summary_limit_reused(self):
        self.finding["summary"] = "问题" * 31
        with self.assertRaisesRegex(ValueError, "60 characters"):
            self.export()

    def test_duplicate_problems_and_record_ids_rejected(self):
        self.plan["audit_id"] = self.report["audit_id"] = "synthetic-two-case-test"
        self.plan["cases"].append(dict(self.plan["cases"][0], id="c2"))
        self.report["results"].append(dict(copy.deepcopy(self.report["results"][0]), id="c2"))
        self.write(self.plan_path, self.plan)
        self.lock_path = self.root / "two-case-lock.json"
        subprocess.run([sys.executable, "-X", "utf8", str(SCRIPTS / "report_gate.py"), "freeze",
                        str(self.plan_path), str(self.lock_path)], check=True, capture_output=True)
        self.report["plan_sha256"] = json.loads(self.lock_path.read_text())["plan_sha256"]
        second = self.report["results"][1]["finding"]
        for record_mode in (False, True):
            if record_mode:
                second["summary"] = "另一种需独立核对的现象"
                second["record_id"] = self.finding["record_id"] = "recExample"
            with self.subTest(record_mode=record_mode), self.assertRaisesRegex(ValueError, "duplicate finding"):
                self.export()

    def test_cli_exports_locally_and_refuses_overwrite(self):
        self.write(self.report_path, self.report)
        output = self.root / "findings.json"
        command = [sys.executable, "-X", "utf8", str(SCRIPTS / "export_findings.py"), "--plan", str(self.plan_path),
                   "--report", str(self.report_path), "--lock", str(self.lock_path), "--output", str(output)]
        first = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertFalse(json.loads(first.stdout)["written_to_feishu"])
        before = output.read_bytes()
        second = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(second.returncode, 2)
        self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
