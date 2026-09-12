from __future__ import annotations

import re


def parse_group_selection(value: str, available: list[int]) -> list[int]:
    normalised = value.translate(str.maketrans("，～~", ",--")).strip()
    if not normalised:
        raise ValueError("Enter at least one group number.")
    selected: set[int] = set()
    for part in (item.strip() for item in normalised.split(",")):
        if re.fullmatch(r"\d+", part):
            selected.add(int(part))
            continue
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if not match:
            raise ValueError(f"Cannot understand group selection: {part}")
        start, end = map(int, match.groups())
        if start > end:
            raise ValueError(f"Range must go from smaller to larger: {part}")
        selected.update(range(start, end + 1))
    invalid = sorted(selected.difference(available))
    if invalid:
        raise ValueError(f"Unavailable group numbers: {', '.join(map(str, invalid))}")
    return sorted(selected)
