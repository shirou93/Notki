import re

with open('tests/test_server.py', 'r') as f:
    content = f.read()

# is_rate_limited compares with max_failed which is from get_fail2ban_config().
# BUT IsRateLimitedTests is mocking `get_fail2ban_config()`!
# Ah wait! It mocks get_fail2ban_config, but we also mocked time.time() and the tests are failing because of state?
# No, let's look at `IsRateLimitedTests` class.
