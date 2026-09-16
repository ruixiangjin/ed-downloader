from __future__ import annotations

import re

SELECTION_TRANSLATION = str.maketrans("，、;；～~－﹣–—−", ",,,,-------")


def parse_group_selection(value: str, available: list[int]) -> list[int]:
    normalised = value.translate(SELECTION_TRANSLATION).strip()
    if not normalised:
        raise ValueError("Enter at least one Week/Module number.")
    selected: set[int] = set()
    for part in (item.strip() for item in normalised.split(",")):
        if not part:
            raise ValueError("Do not leave an empty item between separators. Example: 1,3-5.")
        if re.fullmatch(r"\d+", part):
            selected.add(int(part))
            continue
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if not match:
            raise ValueError(f"Cannot understand '{part}'. Enter a value such as 1, 1,3, or 1-3.")
        start, end = map(int, match.groups())
        if start > end:
            raise ValueError(f"A range must go from smaller to larger: {part}.")
        selected.update(range(start, end + 1))
    invalid = sorted(selected.difference(available))
    if invalid:
        choices = ", ".join(map(str, available)) or "none"
        raise ValueError(
            f"These numbers are outside the available range: {', '.join(map(str, invalid))}. "
            f"Available numbers: {choices}."
        )
    return sorted(selected)
