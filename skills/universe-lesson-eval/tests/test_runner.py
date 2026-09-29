import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from report_gate import freeze, validate

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.plan = {"version": 1, "audit_id": "runner-fixture",
                     "scope": dict(topic="fixture", version="fixture", url="http://localhost/", environment="fixture"),
                     "inventory": [{"node_id": "n", "required_rules": ["CONTENT-01"]}],
                     "cases": [{"id": "c", "title": "fixture", "node": "n", "rule_id": "CONTENT-01",
                                "source": "fixture#p1", "expected": "fixture", "critical": True,
                                "required_evidence": ["code"], "allow_not_applicable": False}]}
        (self.root / "plan.json").write_text(json.dumps(self.plan), encoding="utf-8")
        self.lock = freeze(self.root / "plan.json", self.root / "lock.json")

    def execute(self, source, *options, command_args=()):
        args = [sys.executable, "-X", "utf8", str(SCRIPTS / "run_check.py"), "--plan", str(self.root / "plan.json"),
                "--case-id", "c", "--executor", "runner", "--out", str(self.root / "run.json"),
                "--cwd", str(self.root), *options, "--", sys.executable, "-c", source, *command_args]
        completed = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", timeout=10, check=False)
        self.assertIn(completed.returncode, (0, 1, 2), completed.stderr)
        record = json.loads((self.root / "run.json").read_text(encoding="utf-8"))
        return completed, record

    def gate(self, status):
        report = {"version": 1, "audit_id": "runner-fixture", "executor": "runner",
                  "plan_sha256": self.lock["plan_sha256"], "results": [{"id": "c", "status": status,
                  "reason": "synthetic runner boundary", "evidence": [{"kind": "code", "path": "run.json",
                  "executor": "runner", "observation": "see captured stdout/stderr"}]}]}
        (self.root / "report.json").write_text(json.dumps(report), encoding="utf-8")
        return validate(self.root / "plan.json", self.root / "report.json", self.root / "lock.json")

    def test_success_records_real_input_output(self):
        stdin = self.root / "input.txt"
        stdin.write_text("actual input", encoding="utf-8")
        completed, record = self.execute("import sys; print(sys.stdin.read()); print('err', file=sys.stderr)",
                                         "--stdin", str(stdin), "--input", str(stdin))
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(record["stdin"]["text"], "actual input")
        self.assertEqual(record["stdout"].strip(), "actual input")
        self.assertEqual(record["stderr"].strip(), "err")
        self.assertEqual(record["inputs"][0]["sha256"], record["stdin"]["sha256"])
        self.assertTrue(self.gate("pass")["accepted"])

    def test_nonzero_is_never_pass(self):
        completed, record = self.execute("import sys; print('assertion failed'); sys.exit(3)")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(record["exit_code"], 3)
        self.assertFalse(self.gate("pass")["valid"])
        self.assertTrue(self.gate("fail")["valid"])

    def test_timeout_is_unverified_not_product_failure(self):
        completed, record = self.execute("import time; print('started', flush=True); time.sleep(10)", "--timeout", "0.5")
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(record["outcome"], "timeout")
        self.assertIn("started", record["stdout"])
        self.assertFalse(self.gate("pass")["valid"])
        self.assertFalse(self.gate("fail")["valid"])
        self.assertTrue(self.gate("unverified")["valid"])

    def test_existing_record_is_not_overwritten(self):
        self.execute("print('first')")
        before = (self.root / "run.json").read_bytes()
        completed, record = self.execute("print('second')")
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(before, (self.root / "run.json").read_bytes())
        self.assertIn("first", record["stdout"])

    def test_code_only_pass_or_fail_cannot_replace_required_blackbox(self):
        self.plan["cases"][0].update(required_evidence=["code", "blackbox"], blackbox_method="visual",
                                      state="fixture opened", steps=["read fixture"],
                                      viewport={"width": 1024, "height": 768})
        (self.root / "plan.json").write_text(json.dumps(self.plan), encoding="utf-8")
        (self.root / "lock.json").unlink()
        self.lock = freeze(self.root / "plan.json", self.root / "lock.json")
        self.execute("print('code check only')")
        self.assertFalse(self.gate("pass")["valid"])
        self.assertFalse(self.gate("fail")["valid"])
        self.assertTrue(self.gate("unverified")["valid"])

    def test_no_stdin_is_closed_and_arguments_remain_literal(self):
        literal = "$(not-a-command) & echo; literal"
        completed, record = self.execute("import sys; print(repr(sys.stdin.read())); print(sys.argv[1])",
                                         command_args=[literal])
        self.assertEqual(completed.returncode, 0)
        self.assertIsNone(record["stdin"])
        self.assertIn("''", record["stdout"])
        self.assertIn(literal, record["stdout"])

    def test_record_executor_must_match_evidence(self):
        self.execute("print('fixture')")
        path = self.root / "run.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["executor"] = "someone-else"
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertFalse(self.gate("pass")["valid"])

    def test_code_record_rejects_boolean_version(self):
        self.execute("print('fixture')")
        path = self.root / "run.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["version"] = True
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertFalse(self.gate("pass")["valid"])


if __name__ == "__main__":
    unittest.main()
