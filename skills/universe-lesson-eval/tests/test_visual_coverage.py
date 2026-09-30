"""Anonymized missed-audit regressions. All fixtures are synthetic, never audit evidence."""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from test_v2_gate import build_v2_fixture, report_for_fixture, write_json
from eval_contract import plan_cases, read_json, sha256
from render_report import render
from report_gate import freeze, validate
from v2_contract import VISUAL_RULES


def assertions(rule):
    if rule == "VIEW-01":
        return {"box_tolerance_px": 1, "edge_background_rgb": [0, 0, 0],
                "edge_color_tolerance": 4, "edge_min_non_background": 0.95}
    return {"subject_min_rgb": [200, 150, 0], "subject_max_rgb": [255, 255, 90],
            "subject_min_area_px": 10,
            **({"center_tolerance_px": 8} if rule == "VIEW-02" else {"safe_margin_px": 40})}


def visual_plan(root, full=True, not_applicable=False):
    plan, _ = build_v2_fixture(root)
    (root / "lock.json").unlink()
    plan["scope"].update(coverage="full" if full else "focused", visual_contract_version=1,
                         viewports=[{"width": 1024, "height": 768}, {"width": 800, "height": 600}])
    plan["sources"][0]["node_ids"] = ["n1"]
    template = plan["cases"][0]
    if full:
        for dimension in ("interaction", "motion", "hypothesis"):
            plan["scope"]["dimensions"].append(dimension)
            plan["cases"].append({**copy.deepcopy(template), "id": dimension, "dimension": dimension})
    plan["scope"]["dimensions"].append("viewport")
    node = plan["inventory"][0]
    node["visual_requirements"] = []
    node["visual_states"] = [{"state": "panel-open", "panel": "open", "phase": "default"},
                             {"state": "panel-closed", "panel": "closed", "phase": "default"}]
    node["visual_exclusions"] = [{"phase": phase, "source_ids": ["source-1"],
                                  "rationale": "synthetic still scene has no " + phase}
                                 for phase in ("terminal", "transition")]
    for rule in sorted(VISUAL_RULES if full else {"VIEW-01"}):
        reason = "synthetic text-only node has no scene" if not_applicable else "synthetic public scene"
        node["required_rules"].append(rule)
        node["visual_requirements"].append({"rule_id": rule, "applicable": not not_applicable,
                                             "source_ids": ["source-1"], "rationale": reason})
        plan["rules"].append({"id": rule, "source": "source-1", "version": "fixture-1", "applicability": reason})
        variants = [(state, viewport) for state in node["visual_states"] for viewport in plan["scope"]["viewports"]]
        if not_applicable or not full:
            variants = variants[:1]
        for index, (state, viewport) in enumerate(variants):
            case = {**copy.deepcopy(template), "id": f"{rule}-{index}", "rule_id": rule,
                    "title": "synthetic visual coverage", "dimension": "viewport", "engine": "browser",
                    "required_evidence": ["code", "blackbox"], "blackbox_method": "visual",
                    "state": state["state"], "viewport": viewport, "viewport_assertions": assertions(rule)}
            if not_applicable:
                case.update(engine="static", required_evidence=["code"], allow_not_applicable=True,
                            not_applicable_reason=reason)
            plan["cases"].append(case)
    return plan


def fixture_png(path, width, height, subject):
    """Small, valid generated PNG; no screenshot or browser execution is claimed."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    # A smaller isotropic image keeps deterministic pixel regressions inexpensive.
    pixel_width, pixel_height = width // 8, height // 8
    scanlines = bytearray()
    for y in range(pixel_height):
        scanlines.append(0)
        for x in range(pixel_width):
            inside = (subject["x"] <= (x + 0.5) * 8 < subject["x"] + subject["width"]
                      and subject["y"] <= (y + 0.5) * 8 < subject["y"] + subject["height"])
            scanlines.extend(b"\xf0\xd2\x1e" if inside else b"\x20\x40\x80")
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", pixel_width, pixel_height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


def refresh_visual_run(root, case_id, code):
    """Execute the real read-only image checker over explicitly synthetic captures."""
    from check_viewport import check_viewport
    path = root / code["path"]
    record = read_json(path)
    png, raw = root / (case_id + ".png"), root / (case_id + "-dom.json")
    output, exit_code = check_viewport(root / "plan.json", case_id, raw, png)
    record.update(stdout=json.dumps(output), exit_code=exit_code,
                  inputs=[{"path": str(artifact), "sha256": sha256(artifact)} for artifact in (raw, png)])
    write_json(path, record)
    code["sha256"] = sha256(path)
    return output, exit_code


def measured_report(root, plan):
    report = report_for_fixture(root, plan)
    for case, row in zip(plan["cases"], report["results"]):
        if case["rule_id"] not in VISUAL_RULES:
            continue
        if case["allow_not_applicable"]:
            row.update(status="not_applicable", evidence=[], reason=case["not_applicable_reason"])
            continue
        code, blackbox = row["evidence"]
        run_path = root / code["path"]
        record = read_json(run_path)
        width, height = case["viewport"]["width"], case["viewport"]["height"]
        metadata = {"node_id": case["node"], "state": case["state"], "viewport": case["viewport"],
                    "source": plan["scope"]["url"], "build_id": plan["scope"]["build_id"]}
        host = {"x": 0, "y": 0, "width": width, "height": height}
        available = {**host, "width": width - (240 if case["state"] == "panel-open" else 0)}
        subject = {"x": available["width"] / 2 - 48, "y": height / 2 - 48, "width": 96, "height": 96}
        png = root / (case["id"] + ".png")
        fixture_png(png, width, height, subject)
        blackbox.update(path=png.name, sha256=sha256(png))
        occluders = ([{"kind": "panel", "rect": {"x": width - 240, "y": 24, "width": 216, "height": height - 48}}]
                     if case["state"] == "panel-open" else [])
        raw_path = root / (case["id"] + "-dom.json")
        write_json(raw_path, {**metadata, "captured_at": (datetime.fromisoformat(record["started_at"]) - timedelta(milliseconds=100)).isoformat(),
                              "host": host, "scene": host, "occluders": occluders, "screenshot": png.name})
        output, exit_code = refresh_visual_run(root, case["id"], code)
        if exit_code != 0:
            raise ValueError(f"Synthetic visual fixture was not measurable: {output}")
    return report


class VisualCoverageTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.plan = visual_plan(self.root)

    def prepare(self):
        self.report = measured_report(self.root, self.plan)
        return self.check()

    def check(self):
        write_json(self.root / "report.json", self.report)
        return validate(self.root / "plan.json", self.root / "report.json", self.root / "lock.json")

    def first_visual(self):
        return next(row for row in self.report["results"] if row["id"].startswith("VIEW-01"))

    def mutate_output(self, action):
        code = self.first_visual()["evidence"][0]
        path = self.root / code["path"]
        record = read_json(path)
        output = json.loads(record["stdout"])
        action(output)
        record["stdout"] = json.dumps(output)
        write_json(path, record)
        code["sha256"] = sha256(path)

    def assert_unverified(self, result):
        self.assertTrue(result["valid"], result)
        self.assertFalse(result["complete"])
        self.assertFalse(result["full_certification"])
        self.assertEqual(result["counts"]["fail"], 0)
        self.assertGreater(result["counts"]["unverified"], 0)
        self.assertIsNone(result["score"]["grade"])
        self.assertTrue(result["diagnostics"])

    def test_full_measured_matrix_can_complete(self):
        result = self.prepare()
        self.assertTrue(result["valid"] and result["complete"] and result["full_certification"], result)
        self.assertEqual(result["score"]["grade"], "A")

    def test_omitted_view_rules_or_applicability_reject_freeze(self):
        for rule in ("VIEW-01", "VIEW-02", "VIEW-03"):
            plan = copy.deepcopy(self.plan)
            plan["inventory"][0]["visual_requirements"] = [row for row in plan["inventory"][0]["visual_requirements"]
                                                          if row["rule_id"] != rule]
            with self.subTest(rule=rule), self.assertRaisesRegex(ValueError, "applicability"):
                plan_cases(plan)

    def test_entire_panorama_source_node_cannot_disappear(self):
        self.plan["sources"][0]["node_ids"].append("panorama")
        with self.assertRaisesRegex(ValueError, "missing=.*panorama"):
            plan_cases(self.plan)

    def test_full_source_inventory_is_required(self):
        self.plan["sources"][0].pop("node_ids")
        with self.assertRaisesRegex(ValueError, "source.node_ids"):
            plan_cases(self.plan)

    def test_panel_closed_and_required_dimensions_cannot_be_omitted(self):
        for variant in ("panel", "size", "baseline"):
            plan = copy.deepcopy(self.plan)
            if variant == "panel":
                plan["inventory"][0]["visual_states"] = plan["inventory"][0]["visual_states"][:1]
                plan["cases"] = [case for case in plan["cases"] if case.get("state") != "panel-closed"]
            elif variant == "size":
                plan["cases"] = [case for case in plan["cases"] if not (case["rule_id"] == "VIEW-03"
                                   and case["viewport"]["width"] == 800)]
            else:
                plan["scope"]["viewports"] = [{"width": 800, "height": 600}]
            with self.subTest(variant=variant), self.assertRaises(ValueError):
                plan_cases(plan)

    def test_terminal_and_transition_are_declared_or_excluded_by_basis(self):
        for phase in ("terminal", "transition"):
            plan = copy.deepcopy(self.plan)
            plan["inventory"][0]["visual_exclusions"] = [row for row in plan["inventory"][0]["visual_exclusions"] if row["phase"] != phase]
            with self.subTest(phase=phase), self.assertRaisesRegex(ValueError, "terminal/transition"):
                plan_cases(plan)

    def test_visual_static_and_model_engine_cannot_evade_runtime(self):
        for engine in ("static", "model"):
            plan = copy.deepcopy(self.plan)
            case = next(case for case in plan["cases"] if case["rule_id"] == "VIEW-01")
            case.update(engine=engine, required_evidence=["analysis"] if engine == "model" else ["code"])
            with self.subTest(engine=engine), self.assertRaisesRegex(ValueError, "runtime blackbox|visual propositions"):
                plan_cases(plan)

    def test_full_other_viewport_rules_need_runtime_even_for_model_judgment(self):
        for rule in ("VIEW-04", "VIEW-07"):
            for engine in ("static", "model"):
                plan = copy.deepcopy(self.plan)
                plan["rules"].append({"id": rule, "source": "source-1", "version": "fixture", "applicability": "synthetic presentation"})
                plan["inventory"][0]["required_rules"].append(rule)
                plan["cases"].append({**copy.deepcopy(plan["cases"][0]), "id": rule, "rule_id": rule,
                                      "dimension": "viewport", "engine": engine,
                                      "required_evidence": ["analysis"] if engine == "model" else ["code"]})
                with self.subTest(rule=rule, engine=engine), self.assertRaisesRegex(ValueError, "runtime blackbox"):
                    plan_cases(plan)
                # A genuine runtime observation is still required for model perception.
                if engine == "model":
                    plan["cases"][-1]["required_evidence"].append("blackbox")
                    self.assertIn(rule, plan_cases(plan))

    def test_unsafe_or_missing_measurement_thresholds_reject_freeze(self):
        for value in ({}, {"box_tolerance_px": 10000}):
            plan = copy.deepcopy(self.plan)
            next(case for case in plan["cases"] if case["rule_id"] == "VIEW-01")["viewport_assertions"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                plan_cases(plan)

    def test_focused_has_honest_partial_scope_without_expanding_other_nodes(self):
        self.plan["scope"]["coverage"] = "focused"
        self.plan["sources"][0]["node_ids"].append("other-source-node")
        self.plan["cases"] = [case for case in self.plan["cases"] if not case["id"].startswith("VIEW-") or case["id"].endswith("-0")]
        result = self.prepare()
        self.assertTrue(result["valid"] and result["complete"], result)
        self.assertFalse(result["full_certification"])
        self.assertEqual(result["score"]["scope"], "focused")

    def test_frozen_na_is_legal_without_forcing_a_scene_on_text_only_nodes(self):
        self.plan = visual_plan(self.root, not_applicable=True)
        result = self.prepare()
        self.assertTrue(result["valid"] and result["complete"], result)
        self.assertEqual(result["counts"]["not_applicable"], 3)
        row = self.first_visual()
        row.update(status="pass", evidence=[])
        self.assertFalse(self.check()["valid"])

    def test_na_requires_basis_and_cannot_be_chosen_after_freeze(self):
        plan = copy.deepcopy(self.plan)
        plan["inventory"][0]["visual_requirements"][0]["rationale"] = ""
        with self.assertRaises(ValueError):
            plan_cases(plan)
        self.prepare()
        self.first_visual().update(status="not_applicable", evidence=[], reason="browser unavailable")
        self.assertFalse(self.check()["valid"])

    def test_missing_code_or_blackbox_derives_unverified_without_rewriting_claim(self):
        self.prepare()
        original = copy.deepcopy(self.first_visual()["evidence"])
        for kind in ("code", "blackbox"):
            self.first_visual()["evidence"] = [entry for entry in original if entry["kind"] != kind]
            result = self.check()
            self.assert_unverified(result)
            derived = next(row for row in result["derived_results"] if row["id"] == self.first_visual()["id"])
            self.assertEqual(derived["reported_status"], "pass")
            self.assertEqual(derived["status"], "unverified")
            self.assertEqual(read_json(self.root / "report.json")["results"], self.report["results"])

    def test_leaf_class_check_is_not_a_runtime_pass(self):
        self.prepare()
        code = self.first_visual()["evidence"][0]
        path = self.root / code["path"]
        record = read_json(path)
        record["stdout"] = "PASS: View and fullscreen class found; no calc(100vw - token"
        write_json(path, record)
        code["sha256"] = sha256(path)
        self.assert_unverified(self.check())

    def test_measurements_need_pixels_and_every_assertion(self):
        self.prepare()
        code = self.first_visual()["evidence"][0]
        path = self.root / code["path"]
        original = path.read_bytes()
        for mutate in (lambda output: output["measurement"].pop("edges"),
                       lambda output: output["checks"].pop(),
                       lambda output: output.pop("measurement"),
                       lambda output: output.pop("screenshot")):
            path.write_bytes(original)
            self.mutate_output(mutate)
            self.assert_unverified(self.check())

    def test_screenshot_and_dom_must_be_inputs_from_the_same_capture(self):
        self.prepare()
        code = self.first_visual()["evidence"][0]
        path = self.root / code["path"]
        record = read_json(path)
        record["inputs"] = []
        write_json(path, record)
        code["sha256"] = sha256(path)
        result = self.check()
        self.assertFalse(result["valid"])
        self.assertIsNone(result["score"]["grade"])

    def test_runtime_identity_mismatch_is_invalid_not_a_product_failure(self):
        self.prepare()
        self.mutate_output(lambda output: output.update(state="different-public-state"))
        result = self.check()
        self.assertFalse(result["valid"])
        self.assertFalse(result["full_certification"])
        self.assertEqual(result["counts"]["fail"], 0)

    def test_failed_dynamic_width_assertion_does_not_become_pass_or_invent_a_product_fail(self):
        self.prepare()
        row = self.first_visual()
        raw_path = self.root / (row["id"] + "-dom.json")
        raw = read_json(raw_path)
        raw["scene"]["width"] -= 80
        write_json(raw_path, raw)
        _, code = refresh_visual_run(self.root, row["id"], row["evidence"][0])
        self.assertEqual(code, 1)
        self.assert_unverified(self.check())

    def test_shape_correct_forged_pass_is_recomputed_from_pixels_and_geometry(self):
        self.prepare()
        row = self.first_visual()
        raw_path = self.root / (row["id"] + "-dom.json")
        raw = read_json(raw_path)
        raw["scene"]["width"] -= 80
        write_json(raw_path, raw)
        _, exit_code = refresh_visual_run(self.root, row["id"], row["evidence"][0])
        self.assertEqual(exit_code, 1)
        original = (self.root / row["evidence"][0]["path"]).read_bytes()
        for field, forged in (("passed", True), ("actual", 0), ("expected", 10000)):
            code = row["evidence"][0]
            path = self.root / code["path"]
            record = json.loads(original)
            output = json.loads(record["stdout"])
            output["status"] = "pass"
            for check in output["checks"]:
                if not check["passed"]:
                    check[field] = forged
                    check["passed"] = True
            record.update(exit_code=0, stdout=json.dumps(output))
            write_json(path, record)
            code["sha256"] = sha256(path)
            with self.subTest(field=field):
                result = self.check()
                self.assertFalse(result["valid"], result)
                self.assertFalse(result["full_certification"])
                self.assertIsNone(result["score"]["grade"])
                self.assertIn("recomputed", " ".join(result["errors"]))

    def test_report_displays_derived_unverified_and_retains_original_diagnosis(self):
        self.prepare()
        self.first_visual()["evidence"] = []
        self.check()
        original_hash = sha256(self.root / "report.json")
        output = render(self.root / "plan.json", self.root / "report.json", self.root / "lock.json", self.root / "rendered")
        page = Path(output["html"]).read_text(encoding="utf-8")
        self.assertIn("未评级", page)
        self.assertIn("未通过完整认证", page)
        self.assertIn("原始声明：通过", page)
        self.assertNotIn("完整认证通过", page)
        self.assertEqual(sha256(self.root / "report.json"), original_hash)

    def test_anonymized_seventeen_check_missed_audit_cannot_retain_full_grade(self):
        # Preserves only the observed miss structure: 16 static, 1 model, 0 browser,
        # a VIEW-01 token check, no VIEW-02/03 or frozen visual matrix. No project data.
        plan, _ = build_v2_fixture(self.root / "old")
        root = self.root / "old"
        (root / "lock.json").unlink()
        template = plan["cases"][0]
        plan["scope"].update(coverage="full", dimensions=["science", "interaction", "motion", "viewport", "hypothesis"])
        plan["cases"] = []
        dimensions = ["science"] * 5 + ["interaction"] * 3 + ["motion"] * 3 + ["viewport"] * 2 + ["hypothesis"] * 4
        for index, dimension in enumerate(dimensions):
            case = {**copy.deepcopy(template), "id": f"case-{index}", "dimension": dimension}
            if index == 4:
                case.update(engine="model", required_evidence=["analysis"])
            if index == 11:
                case["rule_id"] = "VIEW-01"
            plan["cases"].append(case)
        plan["inventory"][0]["required_rules"].append("VIEW-01")
        plan["rules"].append({"id": "VIEW-01", "source": "source-1", "version": "fixture", "applicability": "synthetic fullscreen"})
        write_json(root / "plan.json", plan)
        with self.assertRaisesRegex(ValueError, "older v2 plans"):
            freeze(root / "plan.json", root / "new-lock.json")
        report = {"version": 2, "audit_id": plan["audit_id"], "executor": "synthetic", "plan_sha256": sha256(root / "plan.json"),
                  "results": [{"id": case["id"], "status": "pass", "reason": "synthetic old declaration", "evidence": []} for case in plan["cases"]], "issues": []}
        write_json(root / "report.json", report)
        write_json(root / "lock.json", {"version": 2, "audit_id": plan["audit_id"], "plan_sha256": report["plan_sha256"],
                                        "frozen_at": datetime.now(timezone.utc).isoformat()})
        checked = validate(root / "plan.json", root / "report.json", root / "lock.json")
        self.assertFalse(checked["valid"])
        self.assertFalse(checked["full_certification"])
        self.assertIsNone(checked["score"]["value"])
        self.assertIsNone(checked["score"]["grade"])
        self.assertEqual(read_json(root / "report.json"), report)


if __name__ == "__main__":
    unittest.main()
