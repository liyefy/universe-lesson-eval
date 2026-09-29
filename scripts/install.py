"""Install the skill locally; existing installations require --update and are backed up."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile

from check_release import ROOT, check, files_in, linked, read_manifest

NAME = 'universe-lesson-eval'
PREFIX = f'skills/{NAME}/'


def install(project=None, dest=None, update=False):
    check()
    if project and dest:
        raise ValueError('Choose --project or --dest, not both')
    if project:
        project = Path(project).expanduser().resolve()
        if not project.is_dir():
            raise ValueError('The project directory must already exist')
        skills = project / '.agents/skills'
        backups = project / '.local/skill-backups'
    else:
        skills = (Path(dest).expanduser() if dest else
                  Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))) / 'skills').resolve()
        backups = skills.parent / 'skill-backups'
    target = skills / NAME
    if target.resolve().is_relative_to(ROOT) or ROOT.is_relative_to(target.resolve()):
        raise ValueError('Install into a separate project or user skill directory')
    if linked(target) or (target.exists() and not target.is_dir()):
        raise ValueError('Existing target must be a normal directory')
    if target.exists() and not update:
        raise ValueError('Skill already exists; use --update to preserve a backup and update it')
    expected = {name[len(PREFIX):]: digest for name, digest in read_manifest(ROOT)['files'].items()
                if name.startswith(PREFIX)}
    if 'SKILL.md' not in expected:
        raise ValueError('The release contains no installable skill')
    if target.exists() and files_in(target) == set(expected) and all(
            hashlib.sha256((target / name).read_bytes()).hexdigest() == digest for name, digest in expected.items()):
        return {'status': 'unchanged', 'installed': str(target), 'backup': None}
    skills.mkdir(parents=True, exist_ok=True)
    # Stage outside the discovery directory, on the same volume as the destination.
    with tempfile.TemporaryDirectory(prefix='.skill-install-', dir=skills.parent) as temporary:
        stage = Path(temporary) / NAME
        for name, digest in expected.items():
            source = ROOT / PREFIX / name
            staged = stage / name
            staged.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, staged)
            if hashlib.sha256(staged.read_bytes()).hexdigest() != digest:
                raise ValueError('Source changed during installation; original installation preserved')
        backup = None
        if target.exists():
            # target and backup must remain within the explicit selected roots.
            backups.mkdir(parents=True, exist_ok=True)
            backup = backups / (NAME + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
                                + '-' + secrets.token_hex(4))
            if target.resolve().parent != skills.resolve() or backup.resolve().parent != backups.resolve():
                raise ValueError('Invalid installation or backup boundary')
            target.rename(backup)
        try:
            stage.rename(target)
        except OSError:
            if backup is not None and not target.exists():
                backup.rename(target)
            raise
    return {'status': 'installed', 'installed': str(target), 'backup': str(backup) if backup else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument('--project', type=Path, help='existing project root; installs into .agents/skills')
    target.add_argument('--dest', type=Path, help='custom skills directory; default is CODEX_HOME/skills')
    parser.add_argument('--update', action='store_true', help='preserve an existing installation in a backup first')
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.project, args.dest, args.update), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as exc:
        print(f'Install stopped: {exc}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
