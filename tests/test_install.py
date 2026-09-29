import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from install import NAME, install


class InstallTests(unittest.TestCase):
    def test_project_install_preserves_private_config_and_other_skills(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            config = project / '.local/universe-lesson-eval/config.json'
            config.parent.mkdir(parents=True)
            config.write_text('{"version": 1}', encoding='utf-8')
            other = project / '.agents/skills/other/SKILL.md'
            other.parent.mkdir(parents=True)
            other.write_text('other skill', encoding='utf-8')
            result = install(project=project)
            target = project / '.agents/skills' / NAME
            self.assertTrue((target / 'scripts/doctor.py').is_file())
            self.assertEqual(result['status'], 'installed')
            self.assertEqual(config.read_text(encoding='utf-8'), '{"version": 1}')
            self.assertEqual(other.read_text(encoding='utf-8'), 'other skill')
            self.assertFalse((target / '.local').exists())

    def test_existing_installation_is_never_silently_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            target = project / '.agents/skills' / NAME
            target.mkdir(parents=True)
            (target / 'SKILL.md').write_text('local changes', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'already exists'):
                install(project=project)
            self.assertEqual((target / 'SKILL.md').read_text(encoding='utf-8'), 'local changes')

    def test_update_preserves_complete_backup_outside_skill_discovery(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            target = project / '.agents/skills' / NAME
            target.mkdir(parents=True)
            (target / 'SKILL.md').write_text('local changes', encoding='utf-8')
            (target / 'custom.txt').write_text('keep this', encoding='utf-8')
            result = install(project=project, update=True)
            backup = Path(result['backup'])
            self.assertTrue(backup.is_relative_to((project / '.local/skill-backups').resolve()))
            self.assertEqual((backup / 'SKILL.md').read_text(encoding='utf-8'), 'local changes')
            self.assertEqual((backup / 'custom.txt').read_text(encoding='utf-8'), 'keep this')
            self.assertTrue((target / 'scripts/doctor.py').is_file())
            again = install(project=project, update=True)
            self.assertEqual(again['status'], 'unchanged')
            self.assertIsNone(again['backup'])

    def test_copy_failure_preserves_current_installation(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            target = project / '.agents/skills' / NAME
            target.mkdir(parents=True)
            (target / 'SKILL.md').write_text('original', encoding='utf-8')
            with patch('install.shutil.copyfile', side_effect=OSError('synthetic disk error')):
                with self.assertRaises(OSError):
                    install(project=project, update=True)
            self.assertEqual((target / 'SKILL.md').read_text(encoding='utf-8'), 'original')

    def test_commit_failure_restores_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            target = project / '.agents/skills' / NAME
            target.mkdir(parents=True)
            (target / 'SKILL.md').write_text('original', encoding='utf-8')
            original_rename = Path.rename

            def fail_stage(path, to):
                if path.parent.name.startswith('.skill-install-'):
                    raise OSError('synthetic rename error')
                return original_rename(path, to)

            with patch.object(Path, 'rename', fail_stage):
                with self.assertRaises(OSError):
                    install(project=project, update=True)
            self.assertEqual((target / 'SKILL.md').read_text(encoding='utf-8'), 'original')

    def test_codex_home_and_custom_dest(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch.dict(os.environ, {'CODEX_HOME': str(Path(temp) / 'codex')}):
                result = install()
                self.assertEqual(Path(result['installed']), (Path(temp) / 'codex/skills' / NAME).resolve())
            custom = Path(temp) / 'other skills'
            result = install(dest=custom)
            self.assertEqual(Path(result['installed']), (custom / NAME).resolve())

    def test_missing_project_is_not_created(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / 'missing'
            with self.assertRaisesRegex(ValueError, 'must already exist'):
                install(project=project)
            self.assertFalse(project.exists())


if __name__ == '__main__':
    unittest.main()
