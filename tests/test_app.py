import unittest
import subprocess
from pathlib import Path

class TestAppJS(unittest.TestCase):
    def test_app_js_suite(self):
        """Run the JavaScript test suite for app.js"""
        test_script_path = Path(__file__).parent / 'test_app.js'
        result = subprocess.run(['node', str(test_script_path)], capture_output=True, text=True)
        self.assertEqual(
            result.returncode, 0,
            f"Node test failed with return code {result.returncode}.\nStderr: {result.stderr}\nStdout: {result.stdout}"
        )
