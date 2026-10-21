import re

with open('tests/test_server.py', 'r') as f:
    content = f.read()

# is_rate_limited uses max_failed=15, but since the test API might have modified the cache,
# we need to clear the config cache in `setUp` of `IsRateLimitedTests` AND `Fail2banUnitTests`.
# Or we can just explicitly mock get_fail2ban_config for IsRateLimitedTests.

content = content.replace("class IsRateLimitedTests(unittest.TestCase):", "class IsRateLimitedTests(unittest.TestCase):\n    def setUp(self):\n        server._FAIL2BAN_CONFIG_CACHE = None")
content = content.replace("class Fail2banUnitTests(unittest.TestCase):", "class Fail2banUnitTests(unittest.TestCase):\n    def setUp(self):\n        server._FAIL2BAN_CONFIG_CACHE = None")

with open('tests/test_server.py', 'w') as f:
    f.write(content)
