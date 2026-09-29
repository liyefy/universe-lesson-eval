"""Check the explicit release file list, hashes, local links and privacy patterns."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = 'release-manifest.json'
PATTERNS = {
    'personal-directory': re.compile(r'(?:[A-Za-z]:[/\\]+Users[/\\]+|/Users/|/home/)[\w.-]+'),
    'private-feishu-address': re.compile(r'https?://[\w.-]+\.(?:feishu|larksuite)\.(?:cn|com)/', re.I),
    'private-key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'github-credential': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'),
    'cloud-credential': re.compile(r'\b(?:AKIA[A-Z0-9]{16}|LTAI[A-Za-z0-9]{16,})\b'),
    'credential-assignment': re.compile(r'''(?i)["']?(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)["']?\s*[:=]\s*["'][A-Za-z0-9_+/=-]{12,}["']'''),
}


def linked(path):
    return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()


def files_in(root):
    result = set()
    for folder, directories, files in os.walk(root, followlinks=False):
        base = Path(folder)
        for name in list(directories):
            path = base / name
            if linked(path):
                raise ValueError('Linked directory is not a release file: ' + path.relative_to(root).as_posix())
            if name == '__pycache__' or (base == root and name == '.git'):
                directories.remove(name)
        for name in files:
            path = base / name
            if linked(path):
                raise ValueError('Linked file is not a release file: ' + path.relative_to(root).as_posix())
            result.add(path.relative_to(root).as_posix())
    return result


def read_manifest(root):
    manifest = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    if manifest.get('version') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('Invalid release manifest')
    for name, digest in manifest['files'].items():
        path = PurePosixPath(name)
        if (path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name
                or name != path.as_posix() or not path.parts or name == MANIFEST
                or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)):
            raise ValueError('Invalid manifest entry')
    return manifest


def inspect_text(name, text, root):
    errors = []
    for label, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            errors.append(f'{name}:{text.count(chr(10), 0, match.start()) + 1}: {label}')
    # URLs are restricted to public repository/docs hosts and synthetic test hosts.
    for match in re.finditer(r'https?://[^\s<>"\x27`)]+', text):
        host = urlsplit(match.group()).hostname or ''
        if host not in {'github.com', 'docs.github.com', 'localhost', '127.0.0.1'} and not host.endswith('.invalid'):
            errors.append(f'{name}:{text.count(chr(10), 0, match.start()) + 1}: unreviewed-url-host')
    if name.endswith('.md'):
        for target in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)', text):
            if target.startswith(('https://', 'http://', '#')):
                continue
            resolved = (root / name).parent.joinpath(target.split('#')[0]).resolve()
            if not resolved.is_relative_to(root) or not resolved.is_file():
                errors.append(f'{name}: broken-or-external-local-link')
    return errors


def check(root=ROOT, refresh=False):
    root = Path(root).resolve()
    manifest = read_manifest(root)
    expected = set(manifest['files']) | {MANIFEST}
    actual = files_in(root)
    errors = [f'Unlisted file: {name}' for name in sorted(actual - expected)]
    errors += [f'Missing file: {name}' for name in sorted(expected - actual)]
    hashes = {}
    for name in sorted(set(manifest['files']) & actual):
        content = (root / name).read_bytes()
        hashes[name] = hashlib.sha256(content).hexdigest()
        if not refresh and hashes[name] != manifest['files'][name]:
            errors.append(f'Hash mismatch: {name}')
        try:
            text = content.decode('utf-8')
        except UnicodeDecodeError:
            errors.append(f'Non-text release file: {name}')
            continue
        errors += inspect_text(name, text, root)
    if errors:
        raise ValueError('\n'.join(errors))
    if refresh:
        (root / MANIFEST).write_text(json.dumps({'version': 1, 'files': hashes}, ensure_ascii=False,
                                               indent=2) + '\n', encoding='utf-8', newline='\n')
    return {'files': len(hashes), 'privacy_patterns': 'passed', 'local_links': 'passed',
            'hashes': 'refreshed' if refresh else 'passed'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', help='refresh hashes for the already reviewed file list')
    args = parser.parse_args()
    try:
        print(json.dumps(check(refresh=args.refresh), ensure_ascii=False))
        return 0
    except (ValueError, OSError) as exc:
        print(str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
