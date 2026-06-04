"""调用 UApi SDK 获取单个平台热榜数据"""

import os
import time
from uapi import UapiClient

_BASE_URL = "https://uapis.cn"
_TIMEOUT = 10
_MAX_RETRIES = 3  # 最大重试次数

_client: UapiClient | None = None


def _get_client() -> UapiClient:
    global _client
    if _client is None:
        _client = UapiClient(_BASE_URL)
    return _client


def fetch_hotboard(platform_type: str) -> dict:
    """
    获取指定平台的热榜数据。

    参数:
        platform_type: 平台标识，如 "weibo", "zhihu"

    返回:
        API 返回的原始字典:
        {
            "type": "weibo",
            "update_time": "2026-06-04 20:25:58",
            "list": [
                {"index": 1, "title": "...", "url": "...", "hot_value": "1138695", "extra": {}},
                ...
            ]
        }

    异常:
        Exception: API 调用失败时抛出，由调用方处理
    """
    client = _get_client()
    result = client.misc.get_misc_hotboard(type=platform_type)
    return result


def fetch_hotboard_safe(platform_type: str) -> dict | None:
    """
    安全版本：指数退避重试，失败返回 None。

    重试策略：
      - 第 1 次失败：等待 2 秒
      - 第 2 次失败：等待 4 秒
      - 第 3 次失败：返回 None
    """
    for attempt in range(_MAX_RETRIES):
        try:
            return fetch_hotboard(platform_type)
        except Exception as e:
            if attempt < _MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)  # 2s, 4s
                print(f"[fetcher] 获取 {platform_type} 失败（第{attempt + 1}次），{wait}s 后重试: {e}")
                time.sleep(wait)
            else:
                print(f"[fetcher] 获取 {platform_type} 失败，已重试 {_MAX_RETRIES} 次: {e}")
                return None
    return None