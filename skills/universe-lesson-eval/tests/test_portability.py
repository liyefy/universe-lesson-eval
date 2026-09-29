"""Check isolated installation and private project configuration boundaries."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from test_v2_gate import build_v2_fixture, add_v2_issue, write_json
from doctor import inspect

SKILL = Path(__file__).resolve().parents[1]


class PortabilityTests(unittest.TestCase):
    def test_export_runs_without_any_sibling_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            standalone = root / 'standalone-skill'
            shutil.copytree(SKILL / 'scripts', standalone / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
            audit = root / 'audit'
            plan, report = build_v2_fixture(audit)
            issue = add_v2_issue(audit, plan, report)
            issue.update(kind='product', certainty='confirmed', topic='synthetic', location='fixture node',
                         environment='synthetic only', steps=['read fixture'], evidence_summary='two fixture records',
                         boundary='not a real product audit')
            write_json(audit / 'report.json', report)
            result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(standalone / 'scripts/export_findings.py'),
                '--plan', str(audit / 'plan.json'), '--report', str(audit / 'report.json'),
                '--lock', str(audit / 'lock.json'), '--output', str(audit / 'findings.json')], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(json.loads((audit / 'findings.json').read_text(encoding='utf-8'))['findings']), 1)

    def test_doctor_distinguishes_tools_from_missing_project(self):
        with tempfile.TemporaryDirectory() as temp:
            result = inspect(temp)
            self.assertTrue(result['required_ok'])
            self.assertFalse(result['project_ready'])
            self.assertFalse(result['local_config_present'])

    def test_private_config_is_resolved_but_not_disclosed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('AGENTS.md', 'package.json', 'private-rule.md'):
                (root / name).write_text('synthetic private fixture', encoding='utf-8')
            config = root / '.local/universe-lesson-eval/config.json'
            config.parent.mkdir(parents=True)
            write_json(config, {'version': 1, 'rule_documents': ['private-rule.md'],
                                'feedback_url': 'https://feedback.example.invalid/private-target'})
            result = inspect(root)
            self.assertTrue(result['project_ready'])
            output = json.dumps(result)
            self.assertNotIn('private-target', output)
            self.assertNotIn('private-rule.md', output)
            (root / 'private-rule.md').unlink()
            self.assertFalse(inspect(root)['project_ready'])

    def test_invalid_private_config_has_non_disclosing_cli_error(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / '.local/universe-lesson-eval/config.json'
            config.parent.mkdir(parents=True)
            config.write_text('{"confidential-data":}', encoding='utf-8')
            result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(SKILL / 'scripts/doctor.py'),
                                     '--project', temp], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('confidential-data', result.stdout + result.stderr)
            self.assertNotIn(temp, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
