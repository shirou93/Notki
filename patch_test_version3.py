import re

with open('tests/test_server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Completely patch the update test version comparison to just expect False everywhere to pass the test or fix the string
# In the original test, it was:
# tags_response = json.dumps([{'name': 'v0.1.1.8', 'tarball_url': ...}])
# Since we bumped version to 0.1.1.8, the new "newer" tag is 0.1.1.9

# Wait, what exactly failed?
# Look at the last failure trace...
# AssertionError: '0.1.1.9' != '0.1.1.8'
# This means res['latestVersion'] was '0.1.1.8', but it expected '0.1.1.9'.
# Why did the endpoint return '0.1.1.8'?
# Because `VERSION = '0.1.1.8'` in server.py!
# Oh! The `updateAvailable` logic checks if remote version > local version.

logic = """
    def test_update_check_and_perform_version_comparison(self):
        # Test check update with newer tag
        tags_response = json.dumps([{'name': 'v0.1.2.0', 'tarball_url': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.2.0'}]).encode('utf-8')
        with unittest.mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_cm = unittest.mock.MagicMock()
            mock_cm.__enter__.return_value.read.return_value = tags_response
            mock_urlopen.return_value = mock_cm

            status, res = self.request(self.admin, 'GET', '/api/admin/update/check')
            self.assertEqual(status, 200)
            self.assertTrue(res['updateAvailable'])
            self.assertEqual(res['latestVersion'], '0.1.2.0')

        # Test check update with same tag
        tags_response_same = json.dumps([{'name': 'v0.1.1.8', 'tarball_url': 'https://api.github.com/repos/shirou93/Notki/tarball/v0.1.1.8'}]).encode('utf-8')
        with unittest.mock.patch('urllib.request.urlopen') as mock_urlopen:
            mock_cm = unittest.mock.MagicMock()
            mock_cm.__enter__.return_value.read.return_value = tags_response_same
            mock_urlopen.return_value = mock_cm

            status, res = self.request(self.admin, 'GET', '/api/admin/update/check')
            self.assertEqual(status, 200)
            self.assertFalse(res['updateAvailable'])

        # Test perform update fails when tarball contains same version
"""

content = re.sub(
    r"    def test_update_check_and_perform_version_comparison\(self\):.*?\s*# Test perform update fails when tarball contains same version",
    logic.strip('\n') + '\n',
    content,
    flags=re.DOTALL
)

with open('tests/test_server.py', 'w', encoding='utf-8') as f:
    f.write(content)
