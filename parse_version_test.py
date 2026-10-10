import re
def parse_version(version_str):
    return tuple(int(x) for x in re.findall(r'\d+', str(version_str)))
print(parse_version("0.1.3.8"))
print(parse_version("0.1.3.8.1"))
