"""快照管理 + 重复追踪逻辑"""

import json
import os
import copy
from datetime import datetime
from typing import Optional

_SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "snapshots")
_MAX_RETENTION_HOURS = 72  # 快照保留时长


def _snapshot_path(platform_type: str) -> str:
    return os.path.join(_SNAPSHOTS_DIR, f"{platform_type}.json")


def load_snapshot(platform_type: str) -> dict:
    """
    加载平台快照。文件不存在时返回空快照。

    返回:
        {
            "update_time": "",
            "items": []
        }
    """
    path = _snapshot_path(platform_type)
    if not os.path.exists(path):
        return {"update_time": "", "items": []}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, Exception):
        print(f"[snapshot] {platform_type} 快照文件异常，重置快照")
        return {"update_time": "", "items": []}


def save_snapshot(platform_type: str, snapshot: dict) -> None:
    """保存快照到文件。"""
    path = _snapshot_path(platform_type)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)


def merge_with_snapshot(platform_type: str, items: list) -> list:
    """
    将当前轮次数据与快照对比，生成带标记的推送列表。

    参数:
        platform_type: 平台标识
        items: 当前轮次的新闻条目列表（dict 或 NewsItem-like），需有 title/index/hot_value/extra/formatted_hot

    返回:
        推送条目列表（每项在原数据基础上增加 extra.display_tags）
    """
    snapshot = load_snapshot(platform_type)
    now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    old_items = snapshot.get("items", [])
    old_map = {item["title"]: item for item in old_items}

    push_list = []
    new_snapshot_items = []

    for item in items:
        title = item.get("title", "") if isinstance(item, dict) else item.title
        if isinstance(item, dict):
            item_copy = copy.deepcopy(item)
        else:
            item_copy = {"title": item.title, "url": item.url, "hot_value": item.hot_value,
                         "index": item.index, "platform_type": item.platform_type,
                         "platform_name": item.platform_name, "formatted_hot": item.extra.get("formatted_hot", item.hot_value)}

        if title in old_map:
            old_entry = old_map[title]
            old_entry["consecutive_count"] = old_entry.get("consecutive_count", 1) + 1
            old_entry["last_hot_value"] = item_copy["hot_value"]
            old_entry["peak_rank"] = min(old_entry.get("peak_rank", 999), item_copy["index"])
            old_entry["last_seen_at"] = now_str

            tags = []
            cc = old_entry["consecutive_count"]
            if cc >= 2:
                tags.append(f"🔥持续霸榜{cc}轮")

            old_rank = old_entry.get("last_index", item_copy["index"])
            rank_diff = old_rank - item_copy["index"]  # 排名上升 → 差值正
            if rank_diff >= 5:
                tags.append(f"📈上升{rank_diff}位")

            item_copy["extra"] = item_copy.get("extra", {})
            if isinstance(item_copy["extra"], dict):
                item_copy["extra"]["display_tags"] = " ".join(tags)

            push_list.append(item_copy)

            # 保留 old_entry 结构供后续写入快照
            new_entry = {
                "title": title,
                "url": item_copy.get("url"),
                "last_hot_value": item_copy.get("hot_value"),
                "first_seen_at": old_entry["first_seen_at"],
                "last_seen_at": now_str,
                "consecutive_count": cc,
                "peak_rank": old_entry["peak_rank"],
                "is_new": False,
            }
            new_snapshot_items.append(new_entry)
            old_map.pop(title)  # 移出，剩下的为未出现条目
        else:
            # 新上榜
            item_copy["extra"] = item_copy.get("extra", {})
            if isinstance(item_copy["extra"], dict):
                item_copy["extra"]["display_tags"] = ""

            push_list.append(item_copy)

            new_entry = {
                "title": title,
                "url": item_copy.get("url"),
                "last_hot_value": item_copy.get("hot_value"),
                "first_seen_at": now_str,
                "last_seen_at": now_str,
                "consecutive_count": 1,
                "peak_rank": item_copy.get("index", 999),
                "is_new": True,
            }
            new_snapshot_items.append(new_entry)

    # 本轮未出现的条目 → 保留但 consecutive_count 置 0
    for title, old_entry in old_map.items():
        new_entry = {
            "title": title,
            "url": old_entry.get("url", ""),
            "last_hot_value": old_entry.get("last_hot_value", "0"),
            "first_seen_at": old_entry.get("first_seen_at", now_str),
            "last_seen_at": old_entry.get("last_seen_at", now_str),
            "consecutive_count": 0,
            "peak_rank": old_entry.get("peak_rank", 999),
            "is_new": False,
        }
        new_snapshot_items.append(new_entry)

    # 清理超出保留时长的条目
    cutoff = datetime.now().timestamp() - _MAX_RETENTION_HOURS * 3600
    cleaned = []
    for entry in new_snapshot_items:
        try:
            first_seen = datetime.strptime(entry["first_seen_at"], "%Y-%m-%dT%H:%M:%S").timestamp()
            if first_seen >= cutoff:
                cleaned.append(entry)
        except (ValueError, TypeError):
            cleaned.append(entry)
    new_snapshot_items = cleaned

    # 排序：按 index 排列
    new_snapshot_items.sort(key=lambda x: x.get("peak_rank", 999))

    snapshot["update_time"] = now_str
    snapshot["items"] = new_snapshot_items
    save_snapshot(platform_type, snapshot)

    return push_list


def load_all_history(window_hours: int = 6) -> dict:
    """
    加载所有平台快照的 history（用于关键词聚合）。

    返回:
        {platform_type: [item_dict, ...]}  — 只返回时间窗口内的条目
    """
    from datetime import datetime, timedelta

    cutoff = datetime.now() - timedelta(hours=window_hours)
    result = {}

    if not os.path.exists(_SNAPSHOTS_DIR):
        return result

    for filename in os.listdir(_SNAPSHOTS_DIR):
        if not filename.endswith(".json"):
            continue
        platform_type = filename[:-5]
        snapshot = load_snapshot(platform_type)
        items = snapshot.get("items", [])
        filtered = []
        for item in items:
            try:
                first_seen = datetime.strptime(item.get("first_seen_at", ""), "%Y-%m-%dT%H:%M:%S")
                if first_seen >= cutoff:
                    filtered.append(item)
            except (ValueError, TypeError):
                filtered.append(item)
        if filtered:
            result[platform_type] = filtered

    return result