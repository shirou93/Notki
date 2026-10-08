import re

with open('tests/test_server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the test where it tests update logic
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
"""
content = re.sub(
    r"    def test_update_check_and_perform_version_comparison\(self\):.*?\s*self\.assertFalse\(res\['updateAvailable'\]\)",
    logic.strip('\n'),
    content,
    flags=re.DOTALL
)

with open('tests/test_server.py', 'w', encoding='utf-8') as f:
    f.write(content)
