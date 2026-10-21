import re

with open('tests/test_server.py', 'r') as f:
    content = f.read()

# Fix Fail2banUnitTests to explicitly set _FAIL2BAN_CONFIG_CACHE before calling get_fail2ban_config
content = content.replace("mock_connection.execute.return_value.fetchall.return_value = []\n        config = server.get_fail2ban_config()", "mock_connection.execute.return_value.fetchall.return_value = []\n        server._FAIL2BAN_CONFIG_CACHE = None\n        config = server.get_fail2ban_config()")
content = content.replace("]\n        config = server.get_fail2ban_config()", "]\n        server._FAIL2BAN_CONFIG_CACHE = None\n        config = server.get_fail2ban_config()")
content = content.replace("mock_connection.execute.side_effect = Exception(\"DB error\")\n        config = server.get_fail2ban_config()", "mock_connection.execute.side_effect = Exception(\"DB error\")\n        server._FAIL2BAN_CONFIG_CACHE = None\n        config = server.get_fail2ban_config()")

# Fix test_is_rate_limited_window_expiration
content = content.replace("def test_is_rate_limited_window_expiration(self, mock_time):", "def test_is_rate_limited_window_expiration(self, mock_time):\n        server._FAIL2BAN_CONFIG_CACHE = None")

with open('tests/test_server.py', 'w') as f:
    f.write(content)
