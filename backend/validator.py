import re

NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")

def validate(text, whitelist):
    allowed = {float(v) for v in whitelist if not isinstance(v, bool)}
    found = [float(x) for x in NUMBER.findall(text)]
    rejected = [x for x in found if x not in allowed]
    return {"passed": not rejected, "numbers": found, "rejected": rejected}
