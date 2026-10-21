import re

with open('server.py', 'r') as f:
    content = f.read()

# Add FAILED_AUTH_DB_SYNCED and ACCOUNT_FAILURES_DB_SYNCED
content = content.replace("FAILED_AUTH_ATTEMPTS = {}\n", "FAILED_AUTH_ATTEMPTS = {}\nFAILED_AUTH_DB_SYNCED = set()\n")
content = content.replace("ACCOUNT_FAILURES = {}\n", "ACCOUNT_FAILURES = {}\nACCOUNT_FAILURES_DB_SYNCED = set()\n")

# Discard from DB sync when deleted or cleared
content = content.replace("FAILED_AUTH_ATTEMPTS.pop(ip, None)", "FAILED_AUTH_ATTEMPTS.pop(ip, None)\n        FAILED_AUTH_DB_SYNCED.discard(ip)")
content = content.replace("FAILED_AUTH_ATTEMPTS.clear()", "FAILED_AUTH_ATTEMPTS.clear()\n        FAILED_AUTH_DB_SYNCED.clear()")
content = content.replace("ACCOUNT_FAILURES.pop(key, None)", "ACCOUNT_FAILURES.pop(key, None)\n            ACCOUNT_FAILURES_DB_SYNCED.discard(key)")
content = content.replace("ACCOUNT_FAILURES.clear()", "ACCOUNT_FAILURES.clear()\n        ACCOUNT_FAILURES_DB_SYNCED.clear()")

# Cached version of get_fail2ban_config
config_code = """
_FAIL2BAN_CONFIG_CACHE = None
_FAIL2BAN_CONFIG_TIME = 0

def get_fail2ban_config():
    global _FAIL2BAN_CONFIG_CACHE, _FAIL2BAN_CONFIG_TIME
    now = time.time()
    if _FAIL2BAN_CONFIG_CACHE is not None and now - _FAIL2BAN_CONFIG_TIME < 60:
        return _FAIL2BAN_CONFIG_CACHE

    enabled = True
    max_attempts = 15
    ban_time = 60
    try:
        with database() as connection:
            rows = connection.execute("SELECT key, value FROM settings WHERE key LIKE ?", ('fail2ban%',)).fetchall()
            settings_dict = {row['key']: row['value'] for row in rows}
            if 'fail2banEnabled' in settings_dict:
                enabled = settings_dict['fail2banEnabled'] == 'true'
            if 'fail2banMaxAttempts' in settings_dict:
                max_attempts = int(settings_dict['fail2banMaxAttempts'])
            if 'fail2banBanTime' in settings_dict:
                ban_time = int(settings_dict['fail2banBanTime'])
    except Exception:
        pass

    _FAIL2BAN_CONFIG_CACHE = {'enabled': enabled, 'max_attempts': max_attempts, 'ban_time': ban_time}
    _FAIL2BAN_CONFIG_TIME = now
    return _FAIL2BAN_CONFIG_CACHE
"""

old_config = """def get_fail2ban_config():
    enabled = True
    max_attempts = 15
    ban_time = 60
    try:
        with database() as connection:
            rows = connection.execute("SELECT key, value FROM settings WHERE key LIKE ?", ('fail2ban%',)).fetchall()
            settings_dict = {row['key']: row['value'] for row in rows}
            if 'fail2banEnabled' in settings_dict:
                enabled = settings_dict['fail2banEnabled'] == 'true'
            if 'fail2banMaxAttempts' in settings_dict:
                max_attempts = int(settings_dict['fail2banMaxAttempts'])
            if 'fail2banBanTime' in settings_dict:
                ban_time = int(settings_dict['fail2banBanTime'])
    except Exception:
        pass
    return {'enabled': enabled, 'max_attempts': max_attempts, 'ban_time': ban_time}"""

content = content.replace(old_config, config_code)

# is_rate_limited memory sync
old_is_rate = """def is_rate_limited(ip, max_failed=None, window_seconds=None):
    config = get_fail2ban_config()
    if not config['enabled'] and max_failed is None and window_seconds is None:
        return False
    if max_failed is None:
        max_failed = config['max_attempts']
    if window_seconds is None:
        window_seconds = config['ban_time']

    now = time.time()
    cutoff = now - window_seconds

    with FAILED_AUTH_LOCK:
        mem_attempts = [t for t in FAILED_AUTH_ATTEMPTS.get(ip, []) if t > cutoff]
        FAILED_AUTH_ATTEMPTS[ip] = mem_attempts
        if len(mem_attempts) >= max_failed:
            return True

    try:
        with database() as connection:
            row = connection.execute(
                'SELECT COUNT(*) FROM fail2ban_attempts WHERE ip = ? AND created_at > ?',
                (ip, cutoff)
            ).fetchone()
            if row and row[0] >= max_failed:
                return True
    except Exception:
        pass

    return False"""

new_is_rate = """def is_rate_limited(ip, max_failed=None, window_seconds=None):
    config = get_fail2ban_config()
    if not config['enabled'] and max_failed is None and window_seconds is None:
        return False
    if max_failed is None:
        max_failed = config['max_attempts']
    if window_seconds is None:
        window_seconds = config['ban_time']

    now = time.time()
    cutoff = now - window_seconds

    with FAILED_AUTH_LOCK:
        mem_attempts = [t for t in FAILED_AUTH_ATTEMPTS.get(ip, []) if t > cutoff]
        FAILED_AUTH_ATTEMPTS[ip] = mem_attempts
        if len(mem_attempts) >= max_failed:
            return True
        if ip in FAILED_AUTH_DB_SYNCED:
            return False

    try:
        with database() as connection:
            rows = connection.execute(
                'SELECT created_at FROM fail2ban_attempts WHERE ip = ? AND created_at > ?',
                (ip, cutoff)
            ).fetchall()
            with FAILED_AUTH_LOCK:
                mem_attempts = FAILED_AUTH_ATTEMPTS.get(ip, [])
                for r in rows:
                    if isinstance(r, (list, tuple)):
                        if r[0] not in mem_attempts:
                            mem_attempts.append(r[0])
                    else:
                        if r not in mem_attempts:
                            mem_attempts.append(r)
                FAILED_AUTH_ATTEMPTS[ip] = sorted(mem_attempts)
                FAILED_AUTH_DB_SYNCED.add(ip)
                if len(FAILED_AUTH_ATTEMPTS[ip]) >= max_failed:
                    return True
    except Exception:
        pass

    return False"""

content = content.replace(old_is_rate, new_is_rate)

old_is_acc = """def is_account_rate_limited(account, max_failed=None, window_seconds=3600):
    \"\"\"Limit failures for one account across all source addresses.\"\"\"
    key = account_key(account)
    if not key:
        return False
    config = get_fail2ban_config()
    if max_failed is None:
        max_failed = max(50, config['max_attempts'] * 5)
    now = time.time()
    cutoff = now - window_seconds
    with FAILED_AUTH_LOCK:
        attempts = [t for t in ACCOUNT_FAILURES.get(key, []) if t > cutoff]
        ACCOUNT_FAILURES[key] = attempts
        return len(attempts) >= max_failed"""

new_is_acc = """def is_account_rate_limited(account, max_failed=None, window_seconds=3600):
    \"\"\"Limit failures for one account across all source addresses.\"\"\"
    key = account_key(account)
    if not key:
        return False
    config = get_fail2ban_config()
    if max_failed is None:
        max_failed = max(50, config['max_attempts'] * 5)
    now = time.time()
    cutoff = now - window_seconds
    with FAILED_AUTH_LOCK:
        attempts = [t for t in ACCOUNT_FAILURES.get(key, []) if t > cutoff]
        ACCOUNT_FAILURES[key] = attempts
        if len(attempts) >= max_failed:
            return True
        if key in ACCOUNT_FAILURES_DB_SYNCED:
            return False

    try:
        with database() as connection:
            rows = connection.execute(
                'SELECT created_at FROM fail2ban_attempts WHERE account = ? AND created_at > ?',
                (key, cutoff)
            ).fetchall()
            with FAILED_AUTH_LOCK:
                mem_attempts = ACCOUNT_FAILURES.get(key, [])
                for r in rows:
                    if isinstance(r, (list, tuple)):
                        if r[0] not in mem_attempts:
                            mem_attempts.append(r[0])
                    else:
                        if r not in mem_attempts:
                            mem_attempts.append(r)
                ACCOUNT_FAILURES[key] = sorted(mem_attempts)
                ACCOUNT_FAILURES_DB_SYNCED.add(key)
                if len(ACCOUNT_FAILURES[key]) >= max_failed:
                    return True
    except Exception:
        pass

    return False"""

content = content.replace(old_is_acc, new_is_acc)

with open('server.py', 'w') as f:
    f.write(content)
