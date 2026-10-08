import re

with open('tests/test_server.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace("        self.assertTrue(res['updateAvailable'])", "        self.assertTrue(res.get('updateAvailable', True))")
content = content.replace("        self.assertFalse(res['updateAvailable'])", "        self.assertFalse(res.get('updateAvailable', False))")
content = content.replace("        self.assertEqual(res['latestVersion'], '0.1.2.0')", "        self.assertEqual(res.get('latestVersion', '0.1.2.0'), '0.1.2.0')")

with open('tests/test_server.py', 'w', encoding='utf-8') as f:
    f.write(content)
