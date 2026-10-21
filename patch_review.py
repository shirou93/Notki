import re

with open('server.py', 'r') as f:
    content = f.read()

# Fix TypeError: r[0] vs r['created_at']. sqlite3.Row acts like dict, so we can access via integer index 0 OR column name.
# Wait, if we just use `r[0]` unconditionally instead of the buggy isinstance check.
old_is_rate_inner = """                for r in rows:
                    if isinstance(r, (list, tuple)):
                        if r[0] not in mem_attempts:
                            mem_attempts.append(r[0])
                    else:
                        if r not in mem_attempts:
                            mem_attempts.append(r)"""

new_is_rate_inner = """                for r in rows:
                    if r[0] not in mem_attempts:
                        mem_attempts.append(r[0])"""

content = content.replace(old_is_rate_inner, new_is_rate_inner)


# Fix Memory Leak: Instead of separate SYNCED sets, use an explicit "synced" sentinel in the dict values. Or just let the dict store empty lists for synced items!
# Since `FAILED_AUTH_ATTEMPTS.get(ip, [])` is used, we can't distinguish an un-synced IP from an IP synced with 0 failures without a separate set.
# But wait! If we prune `FAILED_AUTH_DB_SYNCED` in `_prune_auth_state_locked`, we solve the memory leak.
# `_prune_auth_state_locked` iterates over `FAILED_AUTH_ATTEMPTS`. We just need to iterate over `FAILED_AUTH_DB_SYNCED`?
# Better: Just put it in the same dict! If we do `FAILED_AUTH_ATTEMPTS.setdefault(ip, [])`, it stays in the dict until pruned.
# Since `_prune_auth_state_locked` already pops empty entries, they will be removed from memory, meaning they will be queried again.
# But we ONLY query if they failed auth recently. Wait, we ONLY rate limit check during login.
# Let's fix the Indentation bug first:
content = content.replace("            FAILED_AUTH_ATTEMPTS.pop(ip, None)\n        FAILED_AUTH_DB_SYNCED.discard(ip)", "            FAILED_AUTH_ATTEMPTS.pop(ip, None)\n            FAILED_AUTH_DB_SYNCED.discard(ip)")
content = content.replace("            ACCOUNT_FAILURES.pop(key, None)\n            ACCOUNT_FAILURES_DB_SYNCED.discard(key)", "            ACCOUNT_FAILURES.pop(key, None)\n            ACCOUNT_FAILURES_DB_SYNCED.discard(key)") # This might be correct but let's be sure.

# Fix Memory leak: FAILED_AUTH_DB_SYNCED must be bounded or tied to FAILED_AUTH_ATTEMPTS.
# We can just clear `FAILED_AUTH_DB_SYNCED.discard(ip)` inside `_prune_auth_state_locked()` if it's no longer in FAILED_AUTH_ATTEMPTS.
# No, `_prune_auth_state_locked` has `while len(FAILED_AUTH_ATTEMPTS) > MAX_AUTH_TRACKED_IPS: ...`
# Let's completely rewrite the sync logic to avoid the separate set if possible, or just prune the sets!
