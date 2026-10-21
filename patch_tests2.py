import re

with open('tests/test_server.py', 'r') as f:
    content = f.read()

# Clear duplicate setUps and fix them! FAILED_AUTH_DB_SYNCED also needs clearing!
content = content.replace("class IsRateLimitedTests(unittest.TestCase):\n    def setUp(self):\n        server._FAIL2BAN_CONFIG_CACHE = None\n    def setUp(self):\n        server._FAIL2BAN_CONFIG_CACHE = None\n    def setUp(self):\n        server.FAILED_AUTH_ATTEMPTS.clear()\n\n    def tearDown(self):\n        server.FAILED_AUTH_ATTEMPTS.clear()", "class IsRateLimitedTests(unittest.TestCase):\n    def setUp(self):\n        server._FAIL2BAN_CONFIG_CACHE = None\n        server.FAILED_AUTH_ATTEMPTS.clear()\n        server.FAILED_AUTH_DB_SYNCED.clear()\n\n    def tearDown(self):\n        server.FAILED_AUTH_ATTEMPTS.clear()\n        server.FAILED_AUTH_DB_SYNCED.clear()")

# And fix `[1000.0] * 14` etc because set logic removes duplicates from DB sync, but mem checking uses lists so `[1000.0] * 14` should technically work?
# Yes, because mem checking is just `len(mem_attempts)`. But let's just make them unique timestamps to be safe!
content = content.replace("[1000.0] * 14", "[1000.0 - i for i in range(14)]")
content = content.replace("[1000.0] * 15", "[1000.0 - i for i in range(15)]")
content = content.replace("[1000.0] * 16", "[1000.0 - i for i in range(16)]")
content = content.replace("[939.0] * 15", "[939.0 - i for i in range(15)]")
content = content.replace("[941.0] * 15", "[941.0 - i for i in range(15)]")

# Fail2banUnitTests setUp
content = content.replace("class Fail2banUnitTests(unittest.TestCase):\n    def setUp(self):\n        server._FAIL2BAN_CONFIG_CACHE = None\n    def setUp(self):\n        server._FAIL2BAN_CONFIG_CACHE = None\n", "class Fail2banUnitTests(unittest.TestCase):\n    def setUp(self):\n        server._FAIL2BAN_CONFIG_CACHE = None\n")

with open('tests/test_server.py', 'w') as f:
    f.write(content)
