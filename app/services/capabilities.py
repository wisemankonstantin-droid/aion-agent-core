import re


def normalize_capability(value: str | None) -> str:
    """Normalize capability labels without pretending semantic equivalence."""
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def capability_matches(left: str | None, right: str | None) -> bool:
    a = normalize_capability(left)
    b = normalize_capability(right)
    return bool(a and b and a == b)
