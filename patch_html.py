import re

favicon_tag = '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,%3Csvg xmlns%3D%22http%3A//www.w3.org/2000/svg%22 viewBox%3D%220 0 24 24%22%3E%3Cstyle%3E.m%7Bstroke%3A%2352734c%7D%40media %28prefers-color-scheme%3Adark%29%7B.m%7Bstroke%3A%23b8d98c%7D%7D%3C/style%3E%3Cg class%3D%22m%22 transform%3D%22rotate%28-8 12 12%29%22 fill%3D%22none%22 stroke-width%3D%221.8%22%3E%3Crect x%3D%222.5%22 y%3D%222.5%22 width%3D%228%22 height%3D%2219%22 rx%3D%222%22/%3E%3Crect x%3D%2213.5%22 y%3D%222.5%22 width%3D%228%22 height%3D%228%22 rx%3D%222%22/%3E%3Crect x%3D%2213.5%22 y%3D%2213.5%22 width%3D%228%22 height%3D%228%22 rx%3D%222%22/%3E%3C/g%3E%3C/svg%3E">'

for filename in ['index.html', 'setup.html']:
    with open(filename, 'r') as f:
        content = f.read()

    if '<link rel="icon"' not in content:
        content = content.replace('<link rel="manifest" href="manifest.json">', f'<link rel="manifest" href="manifest.json">\n  {favicon_tag}')
        with open(filename, 'w') as f:
            f.write(content)
