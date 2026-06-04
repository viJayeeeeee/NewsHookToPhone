"""
主入口：轮转调度 + Processor Pipeline + 重复追踪 + 推送编排

运行流程:
  1. 读取配置（enabled_platforms.json）
  2. 计算当前轮次索引 → 确定要推送的类别
  3. 初始化处理器流水线
  4. 遍历该类别下已启用的平台：fetch → process → dedup → push
  5. 每完成一轮完整轮转（7次），自动触发关键词聚合
"""

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
from pusher import push_platform

# ---- 轮转调度参数 ----
_EPOCH = datetime(2026, 1, 1)
_CYCLE_MINUTES = 10
_CATEGORY_COUNT = 7


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


def main() -> None:
    categories = load_config()
    cycle_index = get_current_cycle_index()
    category = categories[cycle_index]
    pipeline = build_pipeline()

    print(f"[main] 轮次 {cycle_index} → 类别: {category['name']}")

    enabled_platforms = [p for p in category["platforms"] if p.get("enabled")]
    if not enabled_platforms:
        print(f"[main] 类别 '{category['name']}' 下没有已启用的平台，跳过本轮")
        return

    total_pushed = 0
    for platform in enabled_platforms:
        pt = platform["type"]
        print(f"[main] 正在处理: {platform['name']} ({pt})")

        # 1. fetch
        raw_data = fetch_hotboard_safe(pt)
        if raw_data is None:
            print(f"  [main] {pt} 获取失败，跳过")
            continue

        raw_list = raw_data.get("list", [])
        update_time = raw_data.get("update_time", "")
        if not raw_list:
            print(f"  [main] {pt} 数据为空，跳过")
            continue

        # 2. 标准化为 NewsItem
        news_items = [
            NewsItem(
                title=item["title"],
                url=item.get("url", ""),
                hot_value=item.get("hot_value", "0"),
                index=item.get("index", i + 1),
                platform_type=pt,
                platform_name=platform["name"],
            )
            for i, item in enumerate(raw_list[:10])  # 只取 Top 10
        ]

        # 3. Processor Pipeline 处理
        context = ProcessContext(
            platform_type=pt,
            platform_name=platform["name"],
            fetch_time=update_time,
            category_name=category["name"],
            all_items=news_items,
        )
        processed_items = pipeline.run(context, news_items)

        # 4. 转为 dict 供 snapshot_manager 使用
        item_dicts = [item_to_dict(item) for item in processed_items]

        # 5. 重复追踪 + 持续霸榜标记
        diff = merge_with_snapshot(pt, item_dicts)
        if not diff:
            print(f"  [main] {pt} 无新推送条目")
            continue

        # 6. 推送
        success = push_platform(platform["name"], diff, update_time)
        if success:
            total_pushed += len(diff)
            print(f"  [main] {pt} 推送 {len(diff)} 条")
        else:
            print(f"  [main] {pt} 推送失败")

        time.sleep(0.5)  # 限流间隔

    print(f"[main] 本轮推送完成，共推送 {total_pushed} 条")

    # 每轮完整轮转后触发关键词聚合
    # 第 7 轮（cycle_index == 6）且推送了内容时，触发关键词聚合
    # 由于 GitHub Actions 每 10 分钟运行一次，这里不直接调用
    # 关键词聚合由独立的 keyword-aggregation.yml 处理
    # 此处仅做日志记录，便于排查
    if cycle_index == _CATEGORY_COUNT - 1 and total_pushed > 0:
        print("[main] 本轮为类别轮转最后一轮，关键词聚合将在定时/手动触发时执行")


if __name__ == "__main__":
    main()