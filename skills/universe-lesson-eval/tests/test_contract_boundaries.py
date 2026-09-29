"""Independent-review regressions, using local synthetic fixtures only."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from test_gate import build_fixture
from report_gate import freeze, validate


class ContractBoundaryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.plan, self.report = build_fixture(self.root)
        self.plan_path, self.report_path, self.lock_path = [self.root / name for name in
                                                         ("plan.json", "report.json", "lock.json")]

    def write(self, path, data):
        path.write_text(json.dumps(data), encoding="utf-8")

    def check(self):
        self.write(self.report_path, self.report)
        return validate(self.plan_path, self.report_path, self.lock_path)

    def test_plan_report_and_lock_reject_boolean_versions(self):
        for name in ("plan", "report", "lock"):
            with self.subTest(name=name):
                path = self.root / f"{name}.json"
                self.write(self.report_path, self.report)
                original = path.read_bytes()
                value = json.loads(original)
                value["version"] = True
                self.write(path, value)
                checked = validate(self.plan_path, self.report_path, self.lock_path)
                self.assertFalse(checked["valid"])
                self.assertIn("version", " ".join(checked["errors"]))
                path.write_bytes(original)

    def test_blackbox_source_requires_exact_frozen_url(self):
        for source in ("https://another-topic.invalid/", "http://localhost/", "http://localhost/#/modules/other",
                       "http://127.0.0.1/#/modules/fixture", "http://localhost/#/modules/fixture/"):
            for status in ("pass", "fail", "unverified"):
                with self.subTest(source=source, status=status):
                    self.report["results"][0]["status"] = status
                    self.report["results"][0]["evidence"][0]["source"] = source
                    self.assertFalse(self.check()["valid"])

    def test_explicit_case_url_overrides_scope_without_step_text_equality(self):
        target = "http://localhost/#/modules/other"
        self.plan["cases"][0]["url"] = target
        self.write(self.plan_path, self.plan)
        self.lock_path = self.root / "new-lock.json"
        self.report["plan_sha256"] = freeze(self.plan_path, self.lock_path)["plan_sha256"]
        self.assertFalse(self.check()["valid"])
        self.report["results"][0]["evidence"][0].update(source=target, steps=["actual observed operation"])
        self.assertTrue(self.check()["accepted"])

    def test_blackbox_plan_requires_state_steps_and_viewport(self):
        for field in ("state", "steps", "viewport"):
            with self.subTest(field=field):
                plan = copy.deepcopy(self.plan)
                del plan["cases"][0][field]
                self.write(self.plan_path, plan)
                with self.assertRaises(ValueError):
                    freeze(self.plan_path, self.root / "invalid-lock.json")

    def test_blackbox_plan_rejects_empty_state_steps_and_case_url(self):
        for field, values in (("state", ["", "  ", None]), ("steps", [[], [""], [1], "click"]),
                              ("url", ["", None])):
            for value in values:
                with self.subTest(field=field, value=value):
                    plan = copy.deepcopy(self.plan)
                    plan["cases"][0][field] = value
                    self.write(self.plan_path, plan)
                    with self.assertRaises(ValueError):
                        freeze(self.plan_path, self.root / "invalid-lock.json")

    def test_viewport_dimensions_are_finite_positive_numbers(self):
        for dimension in ("width", "height"):
            for value in (0, -1, True, "1024", None, float("inf"), float("nan")):
                with self.subTest(dimension=dimension, value=value):
                    plan = copy.deepcopy(self.plan)
                    plan["cases"][0]["viewport"][dimension] = value
                    self.write(self.plan_path, plan)
                    with self.assertRaises(ValueError):
                        freeze(self.plan_path, self.root / "invalid-lock.json")

    def test_code_only_case_does_not_need_ui_dimensions(self):
        case = self.plan["cases"][0]
        case["required_evidence"] = ["code"]
        for field in ("state", "steps", "viewport", "blackbox_method"):
            del case[field]
        self.write(self.plan_path, self.plan)
        self.assertIn("plan_sha256", freeze(self.plan_path, self.root / "code-lock.json"))


if __name__ == "__main__":
    unittest.main()
