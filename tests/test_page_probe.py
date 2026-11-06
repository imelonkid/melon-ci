import importlib.util
import io
from pathlib import Path
import sys
import unittest
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).parents[1] / '.github/actions/page-artifact'))
import probe

class Response(io.BytesIO):
    def getcode(self): return 200

class Store:
    def __init__(self, immutable=True):
        self.objects={}; self.immutable=immutable
    def open(self, request, timeout):
        if isinstance(request,str):return Response(self.objects[request])
        key=request.full_url
        if key in self.objects and self.immutable:
            raise HTTPError(key,409,'AlreadyExists',{},None)
        self.objects[key]=request.data
        return Response(b'')

class ProbeTests(unittest.TestCase):
    def config(self):return ('fixture','https://example.invalid','fixture-id','fixture-secret')
    def test_checks_real_conditional_response_and_original_content(self):
        store=Store()
        key=probe.probe('sample',self.config,store)
        self.assertTrue(key.startswith('sample/page/_checks/'))
        self.assertEqual(len(store.objects),1)
        self.assertNotEqual(store.objects['https://example.invalid/'+key],b'conflicting contents\n')
    def test_detects_ignored_forbid_overwrite_header(self):
        with self.assertRaisesRegex(ValueError,'禁止覆盖'):
            probe.probe('sample',self.config,Store(immutable=False))
    def test_rejects_project_traversal(self):
        with self.assertRaises(ValueError):probe.probe('../other',self.config,Store())

if __name__ == '__main__':unittest.main()
