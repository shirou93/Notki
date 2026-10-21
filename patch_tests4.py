import re

with open('tests/test_server.py', 'r') as f:
    content = f.read()

# I used `1000.0 - i` inside test_is_rate_limited_window_expiration, so the items are:
# 1000.0, 999.0, 998.0 ... 986.0
# At 1059.0, cutoff = 1059.0 - 60 = 999.0.
# So attempts > cutoff: only 1000.0 is > 999.0!
# Therefore mem_attempts only has 1 element! Length = 1 >= 15 is False.
# That's why test_is_rate_limited_window_expiration fails!
# We want all 15 attempts to be at exactly 1000.0, or at most 999.9, so they are all > 999.0.
# wait! The mem_attempts list didn't need to have unique values for tests NOT using DB sync,
# because mem checking is just `len(mem_attempts) >= max_failed`.
# Ah! FAILED_AUTH_ATTEMPTS.get() returns what we put there, and `mem_attempts = [t for t in FAILED_AUTH_ATTEMPTS.get(ip, []) if t > cutoff]`
# DOES NOT remove duplicates during memory check, ONLY during DB sync.
# BUT I changed it to `[1000.0 - i for i in range(15)]`. Let's change back `[1000.0 - i for i in range(15)]` to `[1000.0] * 15` FOR THAT SPECIFIC TEST.

content = content.replace("server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0 - i for i in range(15)]", "server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0] * 15")

# Check other ones just in case
content = content.replace("server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0 - i for i in range(14)]", "server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0] * 14")
content = content.replace("server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0 - i for i in range(16)]", "server.FAILED_AUTH_ATTEMPTS['192.168.1.100'] = [1000.0] * 16")

with open('tests/test_server.py', 'w') as f:
    f.write(content)
