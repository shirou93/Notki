import urllib.request, json, re
VERSION = '0.1.3.8'

def parse_version(version_str):
    return tuple(int(x) for x in re.findall(r'\d+', str(version_str)))

req = urllib.request.Request('https://api.github.com/repos/shirou93/Notki/tags')
req.add_header('User-Agent', 'Notki-App')
with urllib.request.urlopen(req, timeout=10) as response:
    tags = json.loads(response.read().decode('utf-8'))
    valid_tags = [t for t in tags if re.match(r'^[0-9.]+$', t.get('name', ''))]
    latest_tag = max(valid_tags, key=lambda t: parse_version(t.get('name', '')))
    latest_version = latest_tag.get('name', '').lstrip('v')

    print("Latest version:", latest_version)
    print("Is update available:", latest_version and parse_version(latest_version) > parse_version(VERSION))
