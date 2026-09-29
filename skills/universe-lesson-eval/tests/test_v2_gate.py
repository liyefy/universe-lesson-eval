"""Synthetic contract fixtures only. No browser execution or product acceptance is claimed."""
import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from eval_contract import plan_cases, read_json, sha256
from report_gate import freeze, validate

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def fixture_evidence(root, plan, report, case_id, kind, filename, executor="executor-a", offset=2, exit_code=0):
    """Fabricate clearly labeled local test metadata; never use as audit evidence."""
    case = next(row for row in plan["cases"] if row["id"] == case_id)
    captured = datetime.fromisoformat(read_json(root / "lock.json")["frozen_at"]) + timedelta(seconds=offset)
    artifact = root / filename
    if kind == "code":
        record = {"version": 1, "kind": "code", "audit_id": plan["audit_id"],
                  "plan_sha256": report["plan_sha256"], "case_id": case_id, "executor": executor,
                  "command": ["synthetic-fixture-check"], "executable": "synthetic-fixture-check",
                  "cwd": str(root), "inputs": [], "stdin": None,
                  "started_at": (captured - timedelta(seconds=1)).isoformat(),
                  "timeout_seconds": 10, "elapsed_seconds": 0.01, "encoding": "utf-8",
                  "outcome": "exited", "exit_code": exit_code,
                  "stdout": "SYNTHETIC FIXTURE ONLY", "stderr": ""}
        write_json(artifact, record)
    else:
        artifact.write_text(f"SYNTHETIC FIXTURE ONLY: {filename}", encoding="utf-8")
    evidence = {"kind": kind, "path": filename, "observation": "synthetic local fixture observation",
                "executor": executor, "case_id": case_id, "plan_sha256": report["plan_sha256"],
                "build_id": plan["scope"]["build_id"], "captured_at": captured.isoformat(),
                "sha256": sha256(artifact)}
    if kind == "blackbox":
        evidence.update(source=case.get("url", plan["scope"]["url"]), method=case["blackbox_method"],
                        state=case["state"], viewport=copy.deepcopy(case["viewport"]),
                        steps=["read a synthetic fixture; no real browser was used"])
    return evidence


def report_for_fixture(root, plan):
    """Freeze a fresh plan in a test directory and create synthetic passing artifacts."""
    write_json(root / "plan.json", plan)
    lock = freeze(root / "plan.json", root / "lock.json")
    report = {"version": 2, "audit_id": plan["audit_id"], "executor": "executor-a",
              "plan_sha256": lock["plan_sha256"], "results": [], "issues": []}
    for case in plan["cases"]:
        report["results"].append({"id": case["id"], "status": "pass", "reason": "synthetic fixture passes",
                                  "evidence": [fixture_evidence(root, plan, report, case["id"], kind,
                                               f"{case['id']}-{kind}.json" if kind == "code"
                                               else f"{case['id']}-{kind}.txt")
                                               for kind in case["required_evidence"]]})
    return report


def build_v2_fixture(root, engine="static"):
    """Return (plan, report); plan.json, lock.json and artifacts are already saved."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / "source.txt").write_text("SYNTHETIC REQUIREMENT SNAPSHOT ONLY", encoding="utf-8")
    plan = {"version": 2, "audit_id": "synthetic-v2-audit",
            "scope": {"topic": "fixture", "version": "fixture-v1", "url": "http://localhost/#/modules/fixture",
                      "environment": "synthetic fixture only", "build_id": "fixture-build-1",
                      "dimensions": ["science"], "coverage": "focused"},
            "sources": [{"id": "source-1", "path": "source.txt", "sha256": sha256(root / "source.txt")}],
            "rules": [{"id": "SCI-01", "source": "source-1", "version": "fixture-v1",
                       "applicability": "synthetic fixture only"}],
            "inventory": [{"node_id": "n1", "required_rules": ["SCI-01"]}],
            "cases": [{"id": "c1", "title": "fixture check", "node": "n1", "rule_id": "SCI-01",
                       "source": "source-1#line1", "expected": "synthetic expectation", "critical": True,
                       "dimension": "science", "engine": engine, "source_ids": ["source-1"],
                       "required_evidence": ["analysis"] if engine == "model" else ["code", "blackbox"]
                       if engine == "browser" else ["code"], "model_reason": "semantic fixture review",
                       "blackbox_method": "visual", "state": "fixture-open", "steps": ["read fixture"],
                       "viewport": {"width": 1024, "height": 768}, "allow_not_applicable": False}]}
    return plan, report_for_fixture(root, plan)


def add_v2_issue(root, plan, report, case_ids=None, issue_id="issue-1", severity="moderate",
                 method=None, reviewer=None, fingerprint=None):
    """Add one synthetic reviewed issue, returning it for integration test customization."""
    case_ids = case_ids or ["c1"]
    cases = {row["id"]: row for row in plan["cases"]}
    method = method or ("independent" if any(cases[c]["engine"] == "model" for c in case_ids) else "rerun")
    reviewer = reviewer or ("reviewer-b" if method == "independent" else "executor-a")
    review_evidence = []
    for result in report["results"]:
        if result["id"] not in case_ids:
            continue
        result.update(status="fail", issue_id=issue_id, reason="synthetic confirmed failure")
        for evidence in result["evidence"]:
            if evidence["kind"] == "code":
                artifact = root / evidence["path"]
                record = read_json(artifact)
                record["exit_code"] = 1
                write_json(artifact, record)
                evidence["sha256"] = sha256(artifact)
        for kind in cases[result["id"]]["required_evidence"]:
            filename = f"review-{issue_id}-{result['id']}-{kind}.json" if kind == "code" else \
                       f"review-{issue_id}-{result['id']}-{kind}.txt"
            review_evidence.append(fixture_evidence(root, plan, report, result["id"], kind, filename,
                                                    executor=reviewer, offset=10, exit_code=1))
    issue = {"id": issue_id, "fingerprint": fingerprint or f"synthetic-{issue_id}", "case_ids": case_ids,
             "dimension": cases[case_ids[0]]["dimension"], "severity": severity,
             "summary": "synthetic issue, not a product finding", "actual": "synthetic mismatch",
             "expected": "synthetic expectation", "impact": "fixture scoring only",
             "review": {"method": method, "reviewer": reviewer, "confirmed": True,
                        "reason": "synthetic second observation", "evidence": review_evidence}}
    report["issues"].append(issue)
    return issue


class V2GateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "audit"
        self.plan, self.report = build_v2_fixture(self.root)

    def check(self):
        write_json(self.root / "report.json", self.report)
        return validate(self.root / "plan.json", self.root / "report.json", self.root / "lock.json")

    def rebuild(self):
        # This helper resets synthetic fixtures only; production freeze never overwrites a lock.
        (self.root / "lock.json").unlink()
        self.report = report_for_fixture(self.root, self.plan)

    def add_case(self, case_id, dimension=None):
        case = copy.deepcopy(self.plan["cases"][0])
        case["id"] = case_id
        if dimension:
            case["dimension"] = dimension
            if dimension not in self.plan["scope"]["dimensions"]:
                self.plan["scope"]["dimensions"].append(dimension)
        self.plan["cases"].append(case)

    def set_engine(self, engine):
        case = self.plan["cases"][0]
        case["engine"] = engine
        case["required_evidence"] = ["analysis"] if engine == "model" else ["code", "blackbox"]
        self.rebuild()

    def test_pass_has_scoped_derived_score_and_no_accepted_flag(self):
        result = self.check()
        self.assertTrue(result["valid"], result)
        self.assertTrue(result["complete"])
        self.assertNotIn("accepted", result)
        self.assertEqual((result["score"]["value"], result["score"]["grade"]), (100, "A"))
        self.assertEqual(result["score"]["scope"], "focused")
        self.assertEqual(result["coverage"]["ratio"], 1)

    def test_confirmed_failure_is_complete_and_scored_without_veto(self):
        add_v2_issue(self.root, self.plan, self.report, severity="severe")
        result = self.check()
        self.assertTrue(result["valid"] and result["complete"], result)
        self.assertEqual(result["score"]["value"], 33.33)
        self.assertEqual(result["score"]["deductions"][0]["raw"], 20)
        self.assertEqual(len(result["hard_findings"]), 1)

    def test_same_issue_across_cases_deducted_once(self):
        self.add_case("c2")
        self.rebuild()
        add_v2_issue(self.root, self.plan, self.report, case_ids=["c1", "c2"], severity="minor")
        result = self.check()
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["counts"]["fail"], 2)
        self.assertEqual(len(result["score"]["deductions"]), 1)
        self.assertEqual(result["score"]["value"], 93.33)

    def test_caps_keep_all_hard_findings_and_are_order_independent(self):
        for case_id in ("c2", "c3"):
            self.add_case(case_id)
        self.rebuild()
        for index in (1, 2, 3):
            add_v2_issue(self.root, self.plan, self.report, case_ids=[f"c{index}"],
                         issue_id=f"issue-{index}", severity="severe")
        first = self.check()
        self.assertTrue(first["valid"], first)
        self.report["issues"].reverse()
        self.report["results"].reverse()
        second = self.check()
        self.assertEqual(first["score"], second["score"])
        self.assertEqual(first["hard_findings"], second["hard_findings"])
        self.assertEqual(len(first["hard_findings"]), 3)
        self.assertEqual([row["applied"] for row in first["score"]["deductions"]], [20, 10, 0])
        self.assertEqual(first["score"]["dimensions"]["science"]["raw_deduction"], 60)

    def test_unverified_is_valid_provisional_and_has_no_grade(self):
        self.report["results"][0].update(status="unverified", reason="environment unavailable", evidence=[])
        result = self.check()
        self.assertTrue(result["valid"], result)
        self.assertFalse(result["complete"])
        self.assertTrue(result["score"]["provisional"])
        self.assertIsNone(result["score"]["value"])
        self.assertIsNone(result["score"]["grade"])
        self.assertEqual(result["coverage"]["ratio"], 0)

    def test_partly_verified_score_is_provisional_without_final_grade(self):
        self.add_case("c2")
        self.rebuild()
        add_v2_issue(self.root, self.plan, self.report, severity="minor")
        self.report["results"][1].update(status="unverified", reason="not executed", evidence=[])
        result = self.check()
        self.assertTrue(result["valid"], result)
        self.assertFalse(result["complete"])
        self.assertEqual(result["score"]["value"], 93.33)
        self.assertTrue(result["score"]["provisional"])
        self.assertIsNone(result["score"]["grade"])
        self.assertEqual(result["coverage"]["ratio"], 0.5)

    def test_all_not_applicable_has_no_score_or_grade(self):
        self.plan["cases"][0].update(allow_not_applicable=True, not_applicable_reason="not in this production stage")
        self.rebuild()
        self.report["results"][0].update(status="not_applicable", reason="not in this production stage", evidence=[])
        result = self.check()
        self.assertTrue(result["valid"] and result["complete"], result)
        self.assertIsNone(result["score"]["value"])
        self.assertIsNone(result["score"]["grade"])

    def test_not_applicable_dimension_is_excluded_and_normalized(self):
        self.add_case("c2", "interaction")
        self.plan["cases"][0].update(allow_not_applicable=True, not_applicable_reason="out of stage")
        self.rebuild()
        self.report["results"][0].update(status="not_applicable", reason="out of stage", evidence=[])
        result = self.check()
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["score"]["active_budget"], 25)
        self.assertEqual(result["score"]["dimensions"]["interaction"]["normalized_weight"], 100)

    def test_no_late_not_applicable_or_manual_aggregate(self):
        self.report["results"][0]["status"] = "not_applicable"
        self.assertFalse(self.check()["valid"])
        self.report["results"][0]["status"] = "pass"
        for field in ("score", "grade", "dimension_scores", "accepted"):
            with self.subTest(field=field):
                self.report[field] = 100
                self.assertFalse(self.check()["valid"])
                self.report.pop(field)

    def test_missing_duplicate_extra_results_rejected(self):
        original = copy.deepcopy(self.report["results"])
        for rows in ([], original * 2, original + [{**original[0], "id": "other"}]):
            with self.subTest(rows=rows):
                self.report["results"] = rows
                self.assertFalse(self.check()["valid"])

    def test_case_binding_and_artifact_hashes_are_checked(self):
        evidence = self.report["results"][0]["evidence"][0]
        for field, value in (("case_id", "other"), ("plan_sha256", "0" * 64),
                             ("build_id", "other-build"), ("sha256", "0" * 64)):
            old = evidence[field]
            evidence[field] = value
            self.assertFalse(self.check()["valid"], field)
            evidence[field] = old
        artifact = self.root / evidence["path"]
        artifact.write_bytes(artifact.read_bytes() + b" ")
        self.assertFalse(self.check()["valid"])

    def test_snapshot_hash_is_checked_at_freeze_and_at_report(self):
        (self.root / "source.txt").write_text("changed snapshot", encoding="utf-8")
        self.assertFalse(self.check()["valid"])
        with self.assertRaises(ValueError):
            freeze(self.root / "plan.json", self.root / "other-lock.json")

    def test_evidence_cannot_escape_report_root(self):
        evidence = self.report["results"][0]["evidence"][0]
        outside = self.root.parent / "outside.json"
        outside.write_bytes((self.root / evidence["path"]).read_bytes())
        for path in ("../outside.json", str(outside.resolve())):
            with self.subTest(path=path):
                evidence["path"] = path
                self.assertFalse(self.check()["valid"])

    def test_source_paths_and_rule_bindings_are_frozen(self):
        for field, value in (("path", "../source.txt"), ("path", str((self.root / "source.txt").resolve())),
                             ("sha256", "invalid")):
            plan = copy.deepcopy(self.plan)
            plan["sources"][0][field] = value
            with self.assertRaises(ValueError):
                plan_cases(plan)
        for update in ({"source": "unknown"}, {"version": ""}, {"applicability": ""}):
            plan = copy.deepcopy(self.plan)
            plan["rules"][0].update(update)
            with self.assertRaises(ValueError):
                plan_cases(plan)

    def test_full_and_focused_dimension_coverage(self):
        self.plan["scope"]["coverage"] = "full"
        with self.assertRaises(ValueError):
            plan_cases(self.plan)
        self.plan["scope"]["coverage"] = "focused"
        self.plan["scope"]["dimensions"].append("viewport")
        with self.assertRaises(ValueError):
            plan_cases(self.plan)

    def test_explicit_state_viewport_matrix_cannot_be_omitted(self):
        case = self.plan["cases"][0]
        self.plan["inventory"][0]["required_variants"] = [
            {"rule_id": case["rule_id"], "state": "another-state", "viewport": case["viewport"]}]
        with self.assertRaises(ValueError):
            plan_cases(self.plan)
        self.plan["inventory"][0]["required_variants"][0]["state"] = case["state"]
        self.assertIn("c1", plan_cases(self.plan))

    def test_blackbox_requires_actual_state_viewport_url_and_all_channels(self):
        self.set_engine("browser")
        evidence = self.report["results"][0]["evidence"][1]
        for field, value in (("state", "different-state"), ("viewport", {"width": 1, "height": 1}),
                             ("source", "http://another.invalid/"), ("method", "listening")):
            old = evidence[field]
            evidence[field] = value
            for status in ("pass", "unverified"):
                self.report["results"][0]["status"] = status
                self.assertFalse(self.check()["valid"], field)
            evidence[field] = old
        self.report["results"][0]["status"] = "pass"
        self.report["results"][0]["evidence"].pop()
        self.assertFalse(self.check()["valid"])
        self.report["results"][0]["status"] = "unverified"
        self.assertTrue(self.check()["valid"])

    def test_timezone_and_freeze_timestamp_are_checked(self):
        evidence = self.report["results"][0]["evidence"][0]
        for value in ("2026-09-01T12:00:00", "2000-01-01T00:00:00+00:00", "nonsense"):
            evidence["captured_at"] = value
            self.assertFalse(self.check()["valid"])

    def test_missing_artifact_or_required_evidence_is_not_a_pass(self):
        evidence = self.report["results"][0]["evidence"][0]
        (self.root / evidence["path"]).unlink()
        self.assertFalse(self.check()["valid"])
        self.report["results"][0]["evidence"] = []
        self.assertFalse(self.check()["valid"])

    def test_code_inputs_and_stdin_text_require_valid_hashes(self):
        evidence = self.report["results"][0]["evidence"][0]
        artifact = self.root / evidence["path"]
        record = read_json(artifact)
        for update in ({"inputs": [{"path": "fixture.txt", "sha256": "invalid"}]},
                       {"stdin": {"path": "fixture.txt", "sha256": "0" * 64, "text": "different"}}):
            changed = {**record, **update}
            write_json(artifact, changed)
            evidence["sha256"] = sha256(artifact)
            self.assertFalse(self.check()["valid"])

    def test_code_timeout_remains_unverified(self):
        evidence = self.report["results"][0]["evidence"][0]
        artifact = self.root / evidence["path"]
        record = read_json(artifact)
        record.update(outcome="timeout", exit_code=None)
        write_json(artifact, record)
        evidence["sha256"] = sha256(artifact)
        self.assertFalse(self.check()["valid"])
        self.report["results"][0]["status"] = "unverified"
        self.assertTrue(self.check()["valid"])

    def test_failure_requires_exact_issue_mapping_and_dimension(self):
        self.report["results"][0]["status"] = "fail"
        self.assertFalse(self.check()["valid"])
        issue = add_v2_issue(self.root, self.plan, self.report)
        for field, value in (("case_ids", ["c1", "absent"]), ("dimension", "interaction"),
                             ("severity", "critical")):
            old = issue[field]
            issue[field] = value
            self.assertFalse(self.check()["valid"], field)
            issue[field] = old
        self.assertTrue(self.check()["valid"])

    def test_duplicate_fingerprint_rejected(self):
        self.add_case("c2")
        self.rebuild()
        add_v2_issue(self.root, self.plan, self.report, fingerprint="one-symptom")
        add_v2_issue(self.root, self.plan, self.report, case_ids=["c2"], issue_id="issue-2", fingerprint="one-symptom")
        self.assertFalse(self.check()["valid"])

    def test_deterministic_same_executor_rerun_allowed_but_new_execution_required(self):
        issue = add_v2_issue(self.root, self.plan, self.report)
        self.assertTrue(self.check()["valid"])
        original = self.report["results"][0]["evidence"][0]
        review = issue["review"]["evidence"][0]
        artifact = self.root / review["path"]
        record = read_json(artifact)
        record["started_at"] = read_json(self.root / original["path"])["started_at"]
        write_json(artifact, record)
        review["sha256"] = sha256(artifact)
        self.assertFalse(self.check()["valid"])

    def test_rerun_requires_the_same_command_environment_and_inputs(self):
        issue = add_v2_issue(self.root, self.plan, self.report)
        review = issue["review"]["evidence"][0]
        artifact = self.root / review["path"]
        original = read_json(artifact)
        stdin = {"path": str(self.root / "stdin.txt"), "text": "synthetic input",
                 "sha256": hashlib.sha256(b"synthetic input").hexdigest()}
        for field, value in (("command", ["different-command"]), ("executable", "different-executable"),
                             ("cwd", str(self.root / "different-directory")),
                             ("inputs", [{"path": "other.txt", "sha256": "0" * 64}]), ("stdin", stdin)):
            with self.subTest(field=field):
                write_json(artifact, {**original, field: value})
                review["sha256"] = sha256(artifact)
                result = self.check()
                self.assertFalse(result["valid"])
                self.assertIn("rerun command/cwd/inputs/stdin differ", " ".join(result["errors"]))

    def test_rerun_normalizes_cwd_and_input_paths_without_requiring_input_order(self):
        issue = add_v2_issue(self.root, self.plan, self.report)
        original, review = self.report["results"][0]["evidence"][0], issue["review"]["evidence"][0]
        inputs = [{"path": str(self.root / "a.txt"), "sha256": "a" * 64},
                  {"path": str(self.root / "b.txt"), "sha256": "b" * 64}]
        for evidence in (original, review):
            artifact = self.root / evidence["path"]
            record = read_json(artifact)
            record["inputs"] = copy.deepcopy(inputs)
            if evidence is review:
                record["cwd"] = str(self.root / "unused" / "..")
                record["inputs"].reverse()
                record["inputs"][0]["path"] = "b.txt"
            write_json(artifact, record)
            evidence["sha256"] = sha256(artifact)
        result = self.check()
        self.assertTrue(result["valid"], result)

    def test_independent_review_can_use_a_different_check(self):
        issue = add_v2_issue(self.root, self.plan, self.report, method="independent")
        review = issue["review"]["evidence"][0]
        artifact = self.root / review["path"]
        record = read_json(artifact)
        record.update(command=["different-synthetic-check"], executable="different-synthetic-check")
        write_json(artifact, record)
        review["sha256"] = sha256(artifact)
        issue["review"]["reason"] = "synthetic independent cross-check with another assertion"
        result = self.check()
        self.assertTrue(result["valid"], result)

    def test_review_reuse_and_missing_case_channels_rejected(self):
        self.set_engine("browser")
        issue = add_v2_issue(self.root, self.plan, self.report)
        original_review = copy.deepcopy(issue["review"]["evidence"])
        issue["review"]["evidence"] = [copy.deepcopy(self.report["results"][0]["evidence"][0])]
        self.assertFalse(self.check()["valid"])
        issue["review"]["evidence"] = original_review[:1]
        self.assertFalse(self.check()["valid"])

    def test_review_must_cover_every_case_in_deduplicated_issue(self):
        self.add_case("c2")
        self.rebuild()
        issue = add_v2_issue(self.root, self.plan, self.report, case_ids=["c1", "c2"])
        issue["review"]["evidence"] = issue["review"]["evidence"][:1]
        self.assertFalse(self.check()["valid"])

    def test_model_needs_reason_semantic_evidence_and_independent_reviewer(self):
        self.set_engine("model")
        issue = add_v2_issue(self.root, self.plan, self.report)
        self.assertTrue(self.check()["valid"])
        issue["review"]["method"] = "rerun"
        self.assertFalse(self.check()["valid"])
        issue["review"]["method"] = "independent"
        issue["review"]["reviewer"] = "executor-a"
        self.assertFalse(self.check()["valid"])
        for update in ({"model_reason": ""}, {"required_evidence": ["code"]}):
            plan = copy.deepcopy(self.plan)
            plan["cases"][0].update(update)
            with self.assertRaises(ValueError):
                plan_cases(plan)

    def test_independent_reviewer_cannot_be_any_original_evidence_executor(self):
        issue = add_v2_issue(self.root, self.plan, self.report, method="independent")
        self.report["results"][0]["executor"] = "different-result-author"
        issue["review"]["reviewer"] = "executor-a"
        self.assertFalse(self.check()["valid"])

    def test_independent_identity_ignores_case_and_surrounding_whitespace(self):
        issue = add_v2_issue(self.root, self.plan, self.report, method="independent")
        initial = self.report["results"][0]["evidence"][0]
        review = issue["review"]["evidence"][0]
        for original_name, reviewer_name in (("executor-a", "EXECUTOR-A"),
                                             ("executor-a", "  executor-a  "),
                                             (" ExEcUtOr-A ", "executor-a")):
            with self.subTest(original=original_name, reviewer=reviewer_name):
                self.report["executor"] = original_name
                issue["review"]["reviewer"] = reviewer_name
                for evidence, executor in ((initial, original_name), (review, reviewer_name)):
                    evidence["executor"] = executor
                    artifact = self.root / evidence["path"]
                    record = read_json(artifact)
                    record["executor"] = executor
                    write_json(artifact, record)
                    evidence["sha256"] = sha256(artifact)
                checked = self.check()
                self.assertFalse(checked["valid"])
                self.assertIn("reviewer is not independent", " ".join(checked["errors"]))

    def test_review_evidence_executor_and_confirmation_are_checked(self):
        issue = add_v2_issue(self.root, self.plan, self.report)
        issue["review"]["evidence"][0]["executor"] = "someone-else"
        self.assertFalse(self.check()["valid"])
        issue["review"]["evidence"][0]["executor"] = "executor-a"
        for value in (False, 1, "true"):
            issue["review"]["confirmed"] = value
            self.assertFalse(self.check()["valid"])

    def test_static_analysis_cannot_substitute_for_required_code(self):
        case = self.plan["cases"][0]
        original = copy.deepcopy(case)
        for update in ({"required_evidence": ["analysis"]},
                       {"engine": "browser", "required_evidence": ["code"]},
                       {"source_ids": ["unknown"]}):
            case.update(update)
            with self.assertRaises(ValueError):
                plan_cases(self.plan)
            case.clear()
            case.update(original)
        evidence = fixture_evidence(self.root, self.plan, self.report, "c1", "analysis", "notes.txt")
        self.report["results"][0]["evidence"].append(evidence)
        self.assertFalse(self.check()["valid"])

    def test_v2_frozen_plan_change_and_broken_json_are_invalid(self):
        self.plan["cases"][0]["expected"] = "rewritten expectation"
        write_json(self.root / "plan.json", self.plan)
        result = self.check()
        self.assertFalse(result["valid"])
        self.assertIn("frozen plan changed", result["errors"])
        (self.root / "report.json").write_text('{"version":2,"version":2}', encoding="utf-8")
        result = validate(self.root / "plan.json", self.root / "report.json", self.root / "lock.json")
        self.assertFalse(result["valid"])
        self.assertNotIn("accepted", result)

    def test_plan_report_and_lock_reject_boolean_versions(self):
        for name in ("plan", "report", "lock"):
            with self.subTest(name=name):
                write_json(self.root / "report.json", self.report)
                path = self.root / f"{name}.json"
                original = path.read_bytes()
                value = read_json(path)
                value["version"] = True
                write_json(path, value)
                checked = validate(self.root / "plan.json", self.root / "report.json", self.root / "lock.json")
                self.assertFalse(checked["valid"])
                self.assertNotIn("accepted", checked)
                path.write_bytes(original)

    def test_cli_exits_zero_for_complete_failure_one_unverified_two_invalid(self):
        add_v2_issue(self.root, self.plan, self.report)
        for expected in (0, 1, 2):
            if expected == 1:
                self.report["issues"] = []
                self.report["results"][0].pop("issue_id")
                self.report["results"][0]["status"] = "unverified"
            if expected == 2:
                self.report["results"][0]["status"] = "bad-status"
            write_json(self.root / "report.json", self.report)
            completed = subprocess.run([sys.executable, "-B", "-X", "utf8", str(SCRIPTS / "report_gate.py"),
                                        "check", str(self.root / "plan.json"), str(self.root / "report.json"),
                                        str(self.root / "lock.json")], capture_output=True, text=True,
                                       encoding="utf-8", timeout=10, check=False)
            self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
            self.assertNotIn("accepted", json.loads(completed.stdout))


if __name__ == "__main__":
    unittest.main()
