import re

with open('server.py', 'r') as f:
    content = f.read()

# Fix the isinstance bug:
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

old_is_acc_inner = """                for r in rows:
                    if isinstance(r, (list, tuple)):
                        if r[0] not in mem_attempts:
                            mem_attempts.append(r[0])
                    else:
                        if r not in mem_attempts:
                            mem_attempts.append(r)"""

content = content.replace(old_is_acc_inner, new_is_rate_inner)

# Fix indentation and memory leak by clearing DB syncs when pruning keys:
# We only track FAILED_AUTH_DB_SYNCED for IPs that are currently in FAILED_AUTH_ATTEMPTS.
# But wait, what if an IP is checked (synced) but has 0 attempts?
# It gets added to FAILED_AUTH_DB_SYNCED. It never gets added to FAILED_AUTH_ATTEMPTS.
# So `for ip in tuple(FAILED_AUTH_ATTEMPTS):` doesn't see it!
# Therefore, it leaks!
# To fix: FAILED_AUTH_DB_SYNCED can be bounded just like the dictionaries, or we can just intersect it with FAILED_AUTH_ATTEMPTS periodically.
# BUT if it's not in FAILED_AUTH_ATTEMPTS, it means it has 0 attempts!
# So we can just clear FAILED_AUTH_DB_SYNCED entirely periodically, or bound its size, or remove IPs that aren't in FAILED_AUTH_ATTEMPTS!
# BUT if we remove IPs with 0 attempts, they will be queried again! Is that a problem?
# No! A legitimate user logs in with 0 attempts -> queried once. The cache is lost. Next login, queried again.
# Wait, legitimate user logs in -> querying DB once per login is the original problem!
# So we DO want to cache 0 attempts.
# Thus, FAILED_AUTH_DB_SYNCED must be bounded!
# We can do `while len(FAILED_AUTH_DB_SYNCED) > MAX_AUTH_TRACKED_IPS: FAILED_AUTH_DB_SYNCED.pop()`

prune_code_old = """    while len(FAILED_AUTH_ATTEMPTS) > MAX_AUTH_TRACKED_IPS:
        oldest_ip = min(FAILED_AUTH_ATTEMPTS, key=lambda item: max(FAILED_AUTH_ATTEMPTS[item]))
        FAILED_AUTH_ATTEMPTS.pop(oldest_ip, None)"""

prune_code_new = """    while len(FAILED_AUTH_ATTEMPTS) > MAX_AUTH_TRACKED_IPS:
        oldest_ip = min(FAILED_AUTH_ATTEMPTS, key=lambda item: max(FAILED_AUTH_ATTEMPTS[item]))
        FAILED_AUTH_ATTEMPTS.pop(oldest_ip, None)
        FAILED_AUTH_DB_SYNCED.discard(oldest_ip)

    while len(FAILED_AUTH_DB_SYNCED) > MAX_AUTH_TRACKED_IPS * 2:
        FAILED_AUTH_DB_SYNCED.pop()"""

content = content.replace(prune_code_old, prune_code_new)

prune_acc_old = """    while len(ACCOUNT_FAILURES) > MAX_AUTH_ACCOUNTS:
        oldest_account = min(ACCOUNT_FAILURES, key=lambda item: max(ACCOUNT_FAILURES[item]))
        ACCOUNT_FAILURES.pop(oldest_account, None)"""

prune_acc_new = """    while len(ACCOUNT_FAILURES) > MAX_AUTH_ACCOUNTS:
        oldest_account = min(ACCOUNT_FAILURES, key=lambda item: max(ACCOUNT_FAILURES[item]))
        ACCOUNT_FAILURES.pop(oldest_account, None)
        ACCOUNT_FAILURES_DB_SYNCED.discard(oldest_account)

    while len(ACCOUNT_FAILURES_DB_SYNCED) > MAX_AUTH_ACCOUNTS * 2:
        ACCOUNT_FAILURES_DB_SYNCED.pop()"""

content = content.replace(prune_acc_old, prune_acc_new)


# Fix the incorrect FAILED_AUTH_DB_SYNCED discard indentation:
content = content.replace("        else:\n            FAILED_AUTH_ATTEMPTS.pop(ip, None)\n        FAILED_AUTH_DB_SYNCED.discard(ip)", "        else:\n            FAILED_AUTH_ATTEMPTS.pop(ip, None)\n            FAILED_AUTH_DB_SYNCED.discard(ip)")

with open('server.py', 'w') as f:
    f.write(content)
