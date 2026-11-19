"""Browser logic checks use a small DOM fixture; no browser or npm install is needed."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parent.parent


class SetupBrowserTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node is optional for browser logic checks')
    def test_settings_and_welcome_flows(self):
        result = subprocess.run(['node', str(ROOT/'tests/js/setup.test.cjs'), str(ROOT/'stratabench/web/setup.js')],
            capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for browser logic checks')
    def test_grid_and_list_inspection(self):
        result=subprocess.run(['node',str(ROOT/'tests/js/outcomes.test.cjs'),str(ROOT)],capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    @unittest.skipUnless(shutil.which('node'), 'Node is optional for browser logic checks')
    def test_standard_library_controls(self):
        result=subprocess.run(['node',str(ROOT/'tests/js/standards.test.cjs'),str(ROOT)],capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__ == '__main__': unittest.main()
