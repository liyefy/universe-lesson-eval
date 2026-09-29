"""Read-only dependency/configuration check. Never prints private config values."""
import argparse
import json
from pathlib import Path
import sys

from eval_contract import read_json, require

CONFIG_PATH = Path('.local/universe-lesson-eval/config.json')
OPTIONAL_SKILLS = ('r3f-best-practices', 'universe-responsive-ui', 'universe-lesson-tts',
                   'feishu-task-runner', 'universe-feedback-audit')


def inspect(project_root, skill_root=None):
    project = Path(project_root).resolve()
    skill = Path(skill_root).resolve() if skill_root else Path(__file__).resolve().parents[1]
    config_path = project / CONFIG_PATH
    config = read_json(config_path) if config_path.is_file() else {'version': 1, 'rule_documents': []}
    require(isinstance(config, dict) and type(config.get('version')) is int and config['version'] == 1,
            'local config must be an object with version=1')
    documents = config.get('rule_documents', [])
    require(isinstance(documents, list) and all(isinstance(p, str) and p.strip() for p in documents),
            'rule_documents must be an array of nonempty paths')
    feedback = config.get('feedback_url')
    require(feedback is None or isinstance(feedback, str), 'feedback_url must be text or null')
    paths = [Path(p).expanduser() if Path(p).expanduser().is_absolute() else project / p for p in documents]
    required_files = ('SKILL.md', 'scripts/report_gate.py', 'scripts/export_findings.py',
                      'scripts/render_report.py', 'assets/report.html', 'assets/report.js')
    missing_files = [name for name in required_files if not (skill / name).is_file()]
    project_files = {'agents': (project / 'AGENTS.md').is_file(),
                     'package': (project / 'package.json').is_file()}
    for key in ('topic_registry', 'shared_index'):
        value = config.get(key)
        if value is not None:
            require(isinstance(value, str) and value.strip(), f'{key} must be a nonempty path')
            project_files[key] = (project / value).is_file()
    required_ok = sys.version_info >= (3, 11) and not missing_files
    missing_rules = sum(not path.is_file() for path in paths)
    return {'python': '.'.join(map(str, sys.version_info[:3])), 'minimum_python': '3.11',
            'required_ok': required_ok, 'missing_skill_files': missing_files,
            'local_config_present': config_path.is_file(),
            'rule_documents_count': len(paths), 'missing_rule_documents': missing_rules,
            'feedback_configured': bool(feedback), 'project_files': project_files,
            'project_ready': required_ok and all(project_files.values()) and not missing_rules,
            'optional_project_skills': {name: (project / '.agents/skills' / name / 'SKILL.md').is_file()
                                        for name in OPTIONAL_SKILLS},
            'boundary': 'Checks presence only; no app launch, credentials, remote API or lesson acceptance.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', default='.', help='actual project root, not the installed skill directory')
    parser.add_argument('--require-project', action='store_true')
    args = parser.parse_args()
    try:
        result = inspect(args.project)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['required_ok'] and (not args.require_project or result['project_ready']) else 1
    except (ValueError, TypeError, KeyError, OSError):
        # A parser/OS exception can contain private values or personal paths.
        print(json.dumps({'required_ok': False, 'error': 'Cannot validate local configuration; inspect it locally.'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
