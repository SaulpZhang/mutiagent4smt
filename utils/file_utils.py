from __future__ import annotations

import json
from pathlib import Path


def load_json(path: str) -> dict:
    """加载JSON文件"""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_text(path: str) -> str:
    """加载文本文件"""
    return Path(path).read_text(encoding="utf-8")


def write_text(path: str, content: str) -> None:
    """写入文本文件"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def write_json(path: str, data: dict | list) -> None:
    """写入JSON文件"""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def ensure_dir(path: str) -> None:
    """确保目录存在"""
    Path(path).mkdir(parents=True, exist_ok=True)
