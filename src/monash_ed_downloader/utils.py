from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def safe_filename(value: object, *, limit: int = 100) -> str:
    text = str(value or "untitled")
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text[:limit] or "untitled"


def normalise_text(value: object) -> str:
    text = str(value or "").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(f"{json.dumps(value, ensure_ascii=False, indent=2)}\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def write_text_atomic(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(value, encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
