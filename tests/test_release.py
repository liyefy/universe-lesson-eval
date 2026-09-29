import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_release import check, inspect_text


def fixture(root, text='synthetic public content'):
    (root / 'SKILL.md').write_text(text, encoding='utf-8')
    digest = hashlib.sha256(text.encode('utf-8')).hexdigest()
    (root / 'release-manifest.json').write_text(json.dumps({'version': 1, 'files': {'SKILL.md': digest}}), encoding='utf-8')


class ReleaseTests(unittest.TestCase):
    def test_unlisted_file_is_rejected_even_if_gitignored(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / '.env').write_text('private fixture', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Unlisted file'):
                check(root)

    def test_changed_hash_is_rejected_and_reviewed_refresh_works(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture(root)
            (root / 'SKILL.md').write_text('updated public content', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'Hash mismatch'):
                check(root)
            self.assertEqual(check(root, refresh=True)['hashes'], 'refreshed')
            self.assertEqual(check(root)['hashes'], 'passed')

    def test_refresh_cannot_bypass_sensitive_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            secret = 'gh' + 'p_' + 'A' * 30
            fixture(root, secret)
            with self.assertRaises(ValueError) as caught:
                check(root, refresh=True)
            self.assertIn('github-credential', str(caught.exception))
            self.assertNotIn(secret, str(caught.exception))

    def test_broken_or_external_local_links_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for target in ('missing.md', '../private.md'):
                errors = inspect_text('SKILL.md', '[rule](' + target + ')', root)
                self.assertIn('broken-or-external-local-link', errors[0])

    def test_personal_paths_and_unreviewed_hosts_are_flagged_without_values(self):
        with tempfile.TemporaryDirectory() as temp:
            personal = 'C:' + '/Users/' + 'private-owner' + '/rule.md'
            host = 'https://' + 'unreviewed.example.com/private'
            errors = inspect_text('SKILL.md', personal + '\n' + host, Path(temp))
            self.assertTrue(any('personal-directory' in item for item in errors))
            self.assertTrue(any('unreviewed-url-host' in item for item in errors))
            self.assertNotIn('private-owner', '\n'.join(errors))
            self.assertNotIn(host, '\n'.join(errors))


if __name__ == '__main__':
    unittest.main()
