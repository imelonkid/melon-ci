import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from urllib.error import HTTPError

spec = importlib.util.spec_from_file_location('page_artifact', Path(__file__).parents[1] / '.github/actions/page-artifact/page_artifact.py')
page = importlib.util.module_from_spec(spec)
spec.loader.exec_module(page)


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous = Path.cwd()
        os.chdir(self.tmp.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        Path('site/assets').mkdir(parents=True)
        Path('site/index.html').write_text('<h1>Hero</h1>')
        Path('site/assets/app.js').write_text('void 0;')
        Path('private.env').write_text('NOT_PUBLIC')
        self.commit()
        self.git('tag', 'page-v1.0.0')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')

    def tearDown(self):
        os.chdir(self.previous)
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.check_output(['git', *args], stderr=subprocess.DEVNULL)

    def commit(self):
        self.git('add', '.')
        self.git('commit', '-qm', 'fixture')

    def package(self):
        return page.package('owner/repo', 'project', 'page-v1.0.0', 'site', 'out')

    def retag(self):
        self.git('tag', '-f', 'page-v1.0.0')
        self.git('update-ref', 'refs/remotes/origin/main', 'HEAD')

    def test_only_page_and_stable_retry(self):
        manifest = self.package()
        first = Path('out/site.tar.gz').read_bytes()
        time.sleep(1.1)
        self.assertEqual(manifest, self.package())
        self.assertEqual(first, Path('out/site.tar.gz').read_bytes())
        with tarfile.open('out/site.tar.gz') as archive:
            names = archive.getnames()
        self.assertIn('index.html', names)
        self.assertNotIn('private.env', names)
        self.assertNotIn('site/index.html', names)
        self.assertEqual(manifest['commit'], self.git('rev-parse', 'HEAD').decode().strip())

    def test_symlink_rejected(self):
        Path('site/leak').symlink_to('../private.env')
        self.commit()
        self.retag()
        with self.assertRaisesRegex(ValueError, '不安全'):
            self.package()

    def test_missing_index_rejected(self):
        Path('site/index.html').unlink()
        self.commit()
        self.retag()
        with self.assertRaisesRegex(ValueError, 'index.html'):
            self.package()

    def test_unreviewed_tag_rejected(self):
        Path('site/index.html').write_text('new')
        self.commit()
        self.git('tag', '-f', 'page-v1.0.0')
        with self.assertRaises(subprocess.CalledProcessError):
            self.package()

    def test_path_and_tag_boundaries(self):
        for tag, path in [('page-v1.0.0;bad', 'site'), ('page-v1.0.0', '../site')]:
            with self.assertRaises(ValueError):
                page.package('owner/repo', 'project', tag, path, 'out')

    def test_upload_conflict_is_not_overwritten(self):
        class Fake:
            def __init__(self, existing):
                self.existing = existing
                self.calls = []
            def open(self, req, timeout):
                self.calls.append(req)
                if not isinstance(req, str):
                    raise HTTPError(req.full_url, 409, 'Conflict', {}, None)
                return io.BytesIO(self.existing)
        for existing, ok in [(b'expected', True), (b'other', False)]:
            client = Fake(existing)
            args = ('https://bucket.example', 'bucket', 'project/page/page-v1.0.0/site.tar.gz', b'expected', 'application/gzip', 'test-id', 'test-secret')
            if ok:
                page.put(*args, opener=client)
            else:
                with self.assertRaisesRegex(ValueError, '冲突'):
                    page.put(*args, opener=client)
            self.assertEqual(len(client.calls), 2)
            self.assertEqual(client.calls[0].get_header('X-oss-forbid-overwrite'), 'true')


if __name__ == '__main__':
    unittest.main()
