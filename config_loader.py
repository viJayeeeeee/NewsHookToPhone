"""配置加载模块"""

import json
import os
from typing import Any


_CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_template")


def _resolve_path(filename: str, config_path: str | None) -> str:
    """确定配置文件路径：优先用 config/，找不到则 fallback 到 config_template/。"""
    if config_path:
        return config_path
    primary = os.path.join(_CONFIG_DIR, filename)
    if os.path.exists(primary):
        return primary
    fallback = os.path.join(_TEMPLATE_DIR, filename)
    if os.path.exists(fallback):
        return fallback
    return primary


def load_config(config_path: str | None = None) -> list[dict]:
    """加载 enabled_platforms.json，返回 categories 列表。"""
    config_path = _resolve_path("enabled_platforms.json", config_path)
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在（请检查 config/ 或 config_template/）: {config_path}")
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    return data["categories"]


def load_processors_config(config_path: str | None = None) -> dict[str, dict]:
    """加载 processors.json，返回处理器开关配置。"""
    config_path = _resolve_path("processors.json", config_path)
    if not os.path.exists(config_path):
        return {}
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("processors", {})


def save_config(categories: list[dict], config_path: str | None = None) -> None:
    """写回 enabled_platforms.json（始终写入 config/）。"""
    if config_path is None:
        config_path = os.path.join(_CONFIG_DIR, "enabled_platforms.json")
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    data = {"categories": categories}
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)