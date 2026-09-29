"""Tool-chain regression using explicitly synthetic local audit artifacts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from test_v2_gate import build_v2_fixture, add_v2_issue, report_for_fixture, write_json
from compare_copy import compare
from eval_contract import read_json, sha256
from export_findings import export_findings
from record_evidence import package
from render_report import render, media
from review_decisions import initial_decisions, validate_decisions
from task_packets import split, merge


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "audit"
        self.plan, self.report = build_v2_fixture(self.root)

    def save(self):
        write_json(self.root / "report.json", self.report)

    def add_cases(self, count=3):
        for index in range(2, count + 1):
            case = copy.deepcopy(self.plan["cases"][0])
            case["id"] = f"c{index}"
            self.plan["cases"].append(case)
        (self.root / "lock.json").unlink()
        self.report = report_for_fixture(self.root, self.plan)

    def shard(self, filename, results, issues=None):
        path = self.root / filename
        write_json(path, {**self.report, "results": results, "issues": issues or []})
        return path

    def join(self, parts, name="merged.json", allow_incomplete=False):
        return merge(self.root / "plan.json", self.root / "lock.json", parts,
                     self.root / name, "coordinator", allow_incomplete)

    def test_packets_are_bounded_and_cover_each_case_once(self):
        self.add_cases(5)
        manifest = split(self.root / "plan.json", self.root / "lock.json", self.root / "packets", 2)
        self.assertEqual([len(p["case_ids"]) for p in manifest["packets"]], [2, 2, 1])
        self.assertEqual([key for p in manifest["packets"] for key in p["case_ids"]], [f"c{i}" for i in range(1, 6)])
        packet = read_json(self.root / "packets/packet-001.json")
        self.assertEqual(packet["engine"], "static")
        self.assertEqual(packet["sources"][0]["id"], "source-1")
        self.assertTrue(Path(packet["sources"][0]["path"]).is_file())
        self.assertNotIn("verdict", packet)
        with self.assertRaises(ValueError):
            split(self.root / "plan.json", self.root / "lock.json", self.root / "packets", 2)

    def test_split_rejects_source_drift_and_wrong_lock_version(self):
        lock = read_json(self.root / "lock.json")
        write_json(self.root / "lock.json", {**lock, "version": 1})
        with self.assertRaises(ValueError):
            split(self.root / "plan.json", self.root / "lock.json", self.root / "packets")
        write_json(self.root / "lock.json", lock)
        (self.root / "source.txt").write_text("drift", encoding="utf-8")
        with self.assertRaises(ValueError):
            split(self.root / "plan.json", self.root / "lock.json", self.root / "packets")

    def test_merge_reports_missing_only_as_explicit_unverified(self):
        self.add_cases()
        partial = self.shard("partial.json", self.report["results"][:1])
        with self.assertRaises(ValueError):
            self.join([partial])
        checked = self.join([partial], allow_incomplete=True)
        self.assertTrue(checked["valid"], checked)
        self.assertFalse(checked["complete"])
        self.assertEqual(checked["counts"]["unverified"], 2)
        self.assertIsNone(checked["score"]["grade"])
        result = read_json(self.root / "merged.json")
        self.assertNotIn("score", result)
        self.assertEqual(result["results"][0]["executor"], "executor-a")

    def test_merge_rejects_duplicate_and_foreign_shards(self):
        part = self.shard("part.json", self.report["results"])
        with self.assertRaises(ValueError):
            self.join([part, part])
        document = read_json(part)
        document["plan_sha256"] = "0" * 64
        write_json(part, document)
        with self.assertRaises(ValueError):
            self.join([part])

    def test_workflow_tools_reject_non_object_inputs_without_traceback(self):
        part = self.root / "bad-part.json"
        write_json(part, [])
        with self.assertRaises(ValueError):
            self.join([part])
        write_json(self.root / "plan.json", [])
        with self.assertRaises(ValueError):
            split(self.root / "plan.json", self.root / "lock.json", self.root / "packets")
        with self.assertRaises(ValueError):
            package(self.root / "plan.json", "c1", self.root / "source.txt", {}, self.root)

    def test_merge_one_issue_spanning_cases_is_scored_once(self):
        self.add_cases(2)
        issue = add_v2_issue(self.root, self.plan, self.report, case_ids=["c1", "c2"])
        first = self.shard("first.json", self.report["results"][:1], [issue])
        second = self.shard("second.json", self.report["results"][1:])
        checked = self.join([first, second])
        self.assertTrue(checked["valid"] and checked["complete"], checked)
        self.assertEqual(len(checked["score"]["deductions"]), 1)

    def test_package_hashes_actual_artifact_without_inventing_observation(self):
        evidence = self.report["results"][0]["evidence"][0]
        metadata = {key: value for key, value in evidence.items() if key not in {"path", "sha256", "case_id", "plan_sha256"}}
        result = package(self.root / "plan.json", "c1", self.root / evidence["path"], metadata, self.root)
        self.assertEqual(result, evidence)
        metadata.pop("observation")
        with self.assertRaises(ValueError):
            package(self.root / "plan.json", "c1", self.root / evidence["path"], metadata, self.root)

    def test_package_rejects_mismatched_runtime_metadata(self):
        other = self.root / "browser"
        plan, report = build_v2_fixture(other, "browser")
        evidence = report["results"][0]["evidence"][1]
        metadata = {key: value for key, value in evidence.items() if key not in {"path", "sha256", "case_id", "plan_sha256"}}
        for key, value in (("viewport", {"width": 400, "height": 400}), ("build_id", "other"), ("state", "other")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                package(other / "plan.json", "c1", other / evidence["path"], {**metadata, key: value}, other)

    def test_decisions_bind_report_and_do_not_mutate_it(self):
        add_v2_issue(self.root, self.plan, self.report)
        self.save()
        original_hash = sha256(self.root / "report.json")
        document = initial_decisions(self.root / "report.json")
        document["decisions"][0].update(decision="approve", note="经批阅确认")
        self.assertEqual(validate_decisions(self.root / "report.json", document), document)
        self.assertEqual(sha256(self.root / "report.json"), original_hash)
        for change in ({"report_sha256": "0" * 64}, {"decisions": []},
                       {"decisions": document["decisions"] * 2}, {"decisions": [{"issue_id": "other", "decision": "approve", "note": ""}]}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_decisions(self.root / "report.json", {**document, **change})
        with self.assertRaises(ValueError):
            validate_decisions(self.root / "report.json", [])

    def test_render_escapes_report_text_and_uses_gate_score(self):
        issue = add_v2_issue(self.root, self.plan, self.report)
        issue.update(summary="<script>alert(1)</script> @@DATA@@", suggestion="保留否定词。",
                     code_location={"path": str(self.root / "source.txt"), "line": 1, "component": "fixture", "state": "source snapshot"})
        self.save()
        out = self.root / "rendered"
        result = render(self.root / "plan.json", self.root / "report.json", self.root / "lock.json", out)
        html = Path(result["html"]).read_text(encoding="utf-8")
        markdown = Path(result["markdown"]).read_text(encoding="utf-8")
        self.assertIn("76.67 / 100", html)
        self.assertIn("指定局部范围", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; @@DATA@@", html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn((self.root / "source.txt").as_posix() + ":1", markdown)
        self.assertIn("export-decisions", html)
        self.assertIn("复核证据", html)
        self.assertIn("review-issue-1-c1-code.json", html)
        with self.assertRaises(ValueError):
            render(self.root / "plan.json", self.root / "report.json", self.root / "lock.json", out)

    def test_render_all_unverified_has_no_misleading_no_applicable_label(self):
        self.report["results"][0].update(status="unverified", reason="未执行", evidence=[])
        self.save()
        output = render(self.root / "plan.json", self.root / "report.json", self.root / "lock.json", self.root / "rendered")
        html = Path(output["html"]).read_text(encoding="utf-8")
        self.assertIn("暂无可评分证据", html)
        self.assertIn("未评级", html)
        self.assertNotIn("无适用评分项", html)
        self.assertIn("未验证（预算 30）", html)
        self.assertNotIn("科学与文案：30 / 30", html)

    def test_media_uses_images_and_players_without_inline_svg(self):
        for suffix, tag in ((".png", "<img"), (".webm", "<video"), (".mp3", "<audio"), (".svg", "<a ")):
            evidence = {"path": "media sample" + suffix, "observation": "<screenshot>"}
            markdown, html = media(evidence, self.root, self.root / "rendered")
            self.assertIn(tag, html)
            self.assertIn("media%20sample", html)
            self.assertIn("&lt;screenshot&gt;", html)
            self.assertIn(self.root.as_posix(), markdown)

    def exportable_issue(self):
        issue = add_v2_issue(self.root, self.plan, self.report)
        issue.update(kind="product", certainty="confirmed", topic="fixture", location="解释节点",
                     environment="合成测试", steps=["打开合成文本"], evidence_summary="两次脚本检查一致",
                     boundary="仅合成文本，不是产品验收")
        self.save()

    def test_export_accepts_deterministic_rerun_and_filters_human_decisions(self):
        self.exportable_issue()
        args = (self.root / "plan.json", self.root / "report.json", self.root / "lock.json")
        document, warnings = export_findings(*args)
        self.assertEqual(len(document["findings"]), 1)
        self.assertIn("独立重跑", document["findings"][0]["description"])
        decision_path = self.root / "decisions.json"
        decisions = initial_decisions(self.root / "report.json")
        write_json(decision_path, decisions)
        self.assertEqual(export_findings(*args, decision_path)[0]["findings"], [])
        decisions["decisions"][0]["decision"] = "approve"
        write_json(decision_path, decisions)
        self.assertEqual(len(export_findings(*args, decision_path)[0]["findings"]), 1)

    def test_export_rejects_tampered_review_artifact(self):
        self.exportable_issue()
        artifact = self.root / self.report["issues"][0]["review"]["evidence"][0]["path"]
        artifact.write_text("tampered", encoding="utf-8")
        with self.assertRaises(ValueError):
            export_findings(self.root / "plan.json", self.root / "report.json", self.root / "lock.json")


class ContextualCopyTests(unittest.TestCase):
    def payload(self, actual="观察引力透镜。", **extra):
        return {"version": 1, "comparisons": [{"id": "c1", "source": {"anchor": "source#p1", "paragraph": "经确认的原文"},
                "expected": "观察引力透镜。", "actual": actual, "actual_origin": "合成样例", **extra}]}

    def test_terms_are_context_candidates_and_approved_terms_suppress_them(self):
        data = self.payload()
        first = compare(data)["comparisons"][0]
        self.assertEqual(first["comparison"], "match")
        warning = first["metrics"]["prohibited_term_warnings"][0]
        self.assertTrue(warning["candidate_only"] and warning["present_in_expected"])
        data["approved_terms"] = ["引力透镜"]
        self.assertEqual(compare(data)["comparisons"][0]["metrics"]["prohibited_term_warnings"], [])
        self.assertEqual(compare(self.payload(approved_terms=["引力透镜"]))["comparisons"][0]["metrics"]["prohibited_term_warnings"], [])

    def test_empty_actual_does_not_scan_expected(self):
        row = compare(self.payload(actual=""))["comparisons"][0]
        self.assertEqual(row["comparison"], "candidate_difference")
        self.assertEqual(row["metrics"]["max_clause_length"], 0)
        self.assertEqual(row["metrics"]["prohibited_term_warnings"], [])

    def test_bad_term_lists_and_length_are_rejected(self):
        for value in ("引力透镜", [""], ["重复", "重复"], [1]):
            data = self.payload()
            data["prohibited_terms"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                compare(data)
        for value in (0, -1, True, "18"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                compare(self.payload(), max_clause_length=value)


if __name__ == "__main__":
    unittest.main()
