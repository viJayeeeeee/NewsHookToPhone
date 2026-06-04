"""
主入口：轮转调度 + Processor Pipeline + 重复追踪 + 推送编排 + 跨轮次重试

运行流程:
  1. 读取配置（enabled_platforms.json）
  2. 加载重试队列，处理上一轮失败的平台
  3. 计算当前轮次索引 → 确定要推送的类别
  4. 初始化处理器流水线
  5. 遍历该类别下已启用的平台：fetch → process → dedup → push
  6. 失败的平台存入重试队列，下一轮自动重试
  7. 每轮推送成功后，飞书发送错误报告（如有）
"""

import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

from config_loader import load_config, load_processors_config
from fetcher import fetch_hotboard_safe
from processor import NewsItem, ProcessContext, ProcessorPipeline
from processor.builtin import HotValueFormatter, RankStabilizer, TitleCleaner
from snapshot_manager import merge_with_snapshot, load_all_history
from pusher import push_platform, push_error_report

# ---- 轮转调度参数 ----
_EPOCH = datetime(2026, 1, 1)
_CYCLE_MINUTES = 10
_CATEGORY_COUNT = 7

# ---- 重试队列 ----
_RETRY_QUEUE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "snapshots",
    "retry_queue.json",
)


def get_current_cycle_index() -> int:
    """计算当前轮次索引（基于时间戳）。"""
    now = datetime.now()
    elapsed_minutes = int((now - _EPOCH).total_seconds() / 60)
    cycle_number = elapsed_minutes // _CYCLE_MINUTES
    return cycle_number % _CATEGORY_COUNT


def build_pipeline() -> ProcessorPipeline:
    """根据 processors.json 配置构建处理器流水线。"""
    proc_config = load_processors_config()

    processors = []
    mapping = {
        "hot_value_formatter": HotValueFormatter,
        "rank_stabilizer": RankStabilizer,
        "title_cleaner": TitleCleaner,
    }

    for name, cls in mapping.items():
        cfg = proc_config.get(name, {})
        if cfg.get("enabled", True):
            processors.append(cls())

    return ProcessorPipeline(processors)


def item_to_dict(item: NewsItem) -> dict:
    """将 NewsItem 转为字典（供 snapshot_manager 使用）。"""
    return {
        "title": item.title,
        "url": item.url,
        "hot_value": item.hot_value,
        "index": item.index,
        "platform_type": item.platform_type,
        "platform_name": item.platform_name,
        "formatted_hot": item.extra.get("formatted_hot", item.hot_value),
        "extra": item.extra,
    }


# ---- 重试队列管理 ----

def _load_retry_queue() -> list[dict]:
    """加载重试队列，失败返回空列表。"""
    try:
        with open(_RETRY_QUEUE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, Exception):
        return []


def _save_retry_queue(queue: list[dict]) -> None:
    """保存重试队列到文件。"""
    os.makedirs(os.path.dirname(_RETRY_QUEUE_PATH), exist_ok=True)
    with open(_RETRY_QUEUE_PATH, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)


def _process_single_platform(
    platform: dict,
    category_name: str,
    pipeline: ProcessorPipeline,
) -> tuple[bool, int, str]:
    """
    处理单个平台：fetch → process → dedup → push。

    返回:
        (成功与否, 推送条数, 失败原因)
    """
    pt = platform["type"]
    print(f"[main] 正在处理: {platform['name']} ({pt})")

    raw_data = fetch_hotboard_safe(pt)
    if raw_data is None:
        reason = f"获取失败（已重试 3 次）"
        print(f"  [main] {pt} {reason}")
        return False, 0, reason

    raw_list = raw_data.get("list", [])
    update_time = raw_data.get("update_time", "")
    if not raw_list:
        reason = "数据为空"
        print(f"  [main] {pt} {reason}")
        return False, 0, reason

    news_items = [
        NewsItem(
            title=item["title"],
            url=item.get("url", ""),
            hot_value=item.get("hot_value", "0"),
            index=item.get("index", i + 1),
            platform_type=pt,
            platform_name=platform["name"],
        )
        for i, item in enumerate(raw_list[:10])
    ]

    context = ProcessContext(
        platform_type=pt,
        platform_name=platform["name"],
        fetch_time=update_time,
        category_name=category_name,
        all_items=news_items,
    )
    processed_items = pipeline.run(context, news_items)
    item_dicts = [item_to_dict(item) for item in processed_items]

    diff = merge_with_snapshot(pt, item_dicts)
    if not diff:
        print(f"  [main] {pt} 无新推送条目")
        return True, 0, ""

    success = push_platform(platform["name"], diff, update_time)
    if success:
        print(f"  [main] {pt} 推送 {len(diff)} 条")
        return True, len(diff), ""
    else:
        reason = "推送失败"
        print(f"  [main] {pt} {reason}")
        return False, 0, reason


def main() -> None:
    categories = load_config()
    if not categories:
        print("[main] 未配置任何类别，跳过本轮")
        return

    pipeline = build_pipeline()

    # ---- 1. 处理重试队列 ----
    retry_queue = _load_retry_queue()
    retry_count = 0
    retry_success = 0

    if retry_queue:
        print(f"[main] 重试队列中有 {len(retry_queue)} 个失败平台，开始重试...")
        new_queue = []
        for entry in retry_queue:
            pt = entry["platform_type"]
            # 在当前配置中找到该平台的最新信息
            platform_info = None
            for cat in categories:
                for p in cat["platforms"]:
                    if p["type"] == pt:
                        platform_info = p
                        break
                if platform_info:
                    break

            if not platform_info or not platform_info.get("enabled", False):
                print(f"[main] 重试跳过 {pt}（平台已禁用）")
                continue

            ok, count, reason = _process_single_platform(
                platform_info,
                entry.get("category_name", ""),
                pipeline,
            )
            time.sleep(0.5)

            if ok:
                retry_success += count
            else:
                # 仍失败，保留到下一轮
                new_queue.append(entry)

            retry_count += 1

        retry_queue = new_queue
        _save_retry_queue(retry_queue)

        if retry_count > 0:
            print(f"[main] 重试完成：成功 {retry_success} 条，仍失败 {len(retry_queue)} 个")

    # ---- 2. 处理本轮类别 ----
    cycle_index = get_current_cycle_index() % len(categories)
    category = categories[cycle_index]

    print(f"[main] 轮次 {cycle_index} → 类别: {category['name']}")

    enabled_platforms = [p for p in category["platforms"] if p.get("enabled")]
    if not enabled_platforms:
        print(f"[main] 类别 '{category['name']}' 下没有已启用的平台，跳过本轮")
        return

    total_pushed = 0
    for platform in enabled_platforms:
        ok, count, reason = _process_single_platform(
            platform,
            category["name"],
            pipeline,
        )
        time.sleep(0.5)

        if ok:
            if count > 0:
                total_pushed += count
        else:
            # 失败 → 加入重试队列
            retry_queue.append({
                "platform_type": platform["type"],
                "platform_name": platform["name"],
                "category_name": category["name"],
                "failed_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "reason": reason,
            })
            # 飞书报告错误
            push_error_report(category["name"], platform["name"], platform["type"], reason)

    _save_retry_queue(retry_queue)

    print(f"[main] 本轮推送完成，共推送 {total_pushed} 条")

    # 每轮完整轮转后触发关键词聚合
    if cycle_index == _CATEGORY_COUNT - 1 and total_pushed > 0:
        print("[main] 本轮为类别轮转最后一轮，关键词聚合将在定时/手动触发时执行")


if __name__ == "__main__":
    main()