"""Loader for the small config files in this repo. No third-party YAML parser."""

from __future__ import annotations


def _coerce(value: str):
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_coerce(part.strip()) for part in inner.split(",")]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value.strip('"').strip("'")


def load_yaml(text: str) -> dict:
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        key, sep, val = line.partition(":")
        if not sep:
            raise ValueError(f"Expected 'key: value' in config line: {raw}")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if val.strip() == "":
            node: dict = {}
            parent[key.strip()] = node
            stack.append((indent, node))
        else:
            parent[key.strip()] = _coerce(val.strip())
    return root
