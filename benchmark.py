import time
import random

# Generate dummy data
cutoff = 0
rows = []
for i in range(10000):
    ip = f"192.168.1.{random.randint(1, 100)}"
    t = random.uniform(1, 1000)
    rows.append({'ip': ip, 'created_at': t})

def original_code():
    ip_attempts = {}
    for row in rows:
        ip = row['ip']
        t = row['created_at']
        if ip not in ip_attempts:
            ip_attempts[ip] = []
        if t not in ip_attempts[ip]:
            ip_attempts[ip].append(t)
    return ip_attempts

def optimized_code():
    ip_attempts = {}
    for row in rows:
        ip = row['ip']
        t = row['created_at']
        if ip not in ip_attempts:
            ip_attempts[ip] = set()
        ip_attempts[ip].add(t)
    return ip_attempts

def benchmark(func, iterations=100):
    start_time = time.time()
    for _ in range(iterations):
        func()
    end_time = time.time()
    return end_time - start_time

t1 = benchmark(original_code)
t2 = benchmark(optimized_code)

print(f"Original: {t1:.4f} s")
print(f"Optimized: {t2:.4f} s")
print(f"Improvement: {(t1-t2)/t1*100:.2f}%")
