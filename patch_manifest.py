import json

with open('manifest.json', 'r') as f:
    data = json.load(f)

data['icons'][0]['src'] = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'%3E%3Cstyle%3E.m%7Bstroke%3A%2352734c%7D%40media %28prefers-color-scheme%3Adark%29%7B.m%7Bstroke%3A%23b8d98c%7D%7D%3C/style%3E%3Cg class='m' transform='rotate(-8 12 12)' fill='none' stroke-width='1.8'%3E%3Crect x='2.5' y='2.5' width='8' height='19' rx='2'/%3E%3Crect x='13.5' y='2.5' width='8' height='8' rx='2'/%3E%3Crect x='13.5' y='13.5' width='8' height='8' rx='2'/%3E%3C/g%3E%3C/svg%3E"

with open('manifest.json', 'w') as f:
    json.dump(data, f, indent=2)
    f.write('\n')
