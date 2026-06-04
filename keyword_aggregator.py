"""
热点关键词聚合引擎

从快照历史数据中提取高频关键词，四维加权评分后输出 Top 10。
支持独立运行（被 keyword-aggregation.yml 调用）或作为模块导入。

用法:
    python keyword_aggregator.py [window_hours]
"""

import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import jieba

from snapshot_manager import load_all_history
from pusher import push_keywords


# ---- 停用词表（精简） ----
_STOP_WORDS = {
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "什么", "怎么", "如何", "为什么", "哪个", "多少",
    "与", "及", "或", "但", "而", "且", "等", "之", "被", "把", "让",
    "对", "从", "以", "为", "于", "向", "在", "因", "由", "用", "通过",
    "进行", "包括", "以及", "关于", "可以", "能够", "应该", "可能",
    "将", "已", "已经", "还", "仍", "仍", "再", "才", "又", "就", "便",
    "呢", "吗", "吧", "啊", "哦", "嗯", "啦",
}

_MIN_KEYWORD_LENGTH = 2
_TOP_K = 10


@dataclass
class KeywordStats:
    """单个关键词的统计信息"""
    total_hot_value: int = 0
    total_appearances: int = 0
    max_consecutive: int = 0
    platforms: set = field(default_factory=set)
    platform_counts: dict = field(default_factory=lambda: defaultdict(int))
    # 关联新闻列表
    related_news: list = field(default_factory=list)


@dataclass
class ScoredKeyword:
    keyword: str
    score: float
    stats: KeywordStats


def extract_keywords(title: str) -> list[str]:
    """对标题进行分词，返回过滤后的关键词列表。"""
    words = jieba.lcut(title)
    return [w.strip() for w in words if len(w) >= _MIN_KEYWORD_LENGTH and w not in _STOP_WORDS and w.strip()]


def calculate_weighted_score(stats: KeywordStats, max_platforms: int, max_hot: int, max_consecutive: int) -> float:
    """
    计算关键词的综合加权评分。

    四维:
      - H: 增量热度 (40%)
      - R: 重复出现率 (25%)
      - P: 跨平台广度 (25%)
      - D: 同平台密度 (10%)
    """
    H = stats.total_hot_value / max_hot if max_hot > 0 else 0
    R = stats.max_consecutive / max_consecutive if max_consecutive > 0 else 0
    P = len(stats.platforms) / max_platforms if max_platforms > 0 else 0
    D = max(stats.platform_counts.values()) / max(stats.platform_counts.values()) if stats.platform_counts else 0

    return 0.4 * H + 0.25 * R + 0.25 * P + 0.10 * D


def aggregate_keywords(snapshots: dict, window_hours: int = 6) -> list[dict]:
    """
    从快照中聚合关键词。

    参数:
        snapshots: {platform_type: [item_dict, ...]}  — 各平台的历史条目
        window_hours: 聚合时间窗口

    返回:
        按综合评分降序排列的 Top 10 关键词列表（dict 格式，含 related_news 等）
    """
    keyword_stats_map: dict[str, KeywordStats] = {}
    platform_name_map = _build_platform_name_map()

    for platform_type, items in snapshots.items():
        for item in items:
            title = item.get("title", "")
            hot_value = int(item.get("last_hot_value", 0))
            consecutive = item.get("consecutive_count", 1)
            platform_name = platform_name_map.get(platform_type, platform_type)

            keywords = extract_keywords(title)
            for kw in keywords:
                if kw not in keyword_stats_map:
                    keyword_stats_map[kw] = KeywordStats()
                stats = keyword_stats_map[kw]
                stats.total_hot_value += hot_value
                stats.total_appearances += 1
                stats.max_consecutive = max(stats.max_consecutive, consecutive)
                stats.platforms.add(platform_type)
                stats.platform_counts[platform_type] += 1
                stats.related_news.append({
                    "title": title,
                    "platform_type": platform_type,
                    "platform_name": platform_name,
                    "hot_value": item.get("last_hot_value", "0"),
                    "url": item.get("url", ""),
                })

    if not keyword_stats_map:
        return []

    # 计算归一化最大值
    max_hot = max(s.total_hot_value for s in keyword_stats_map.values())
    max_consecutive = max(s.max_consecutive for s in keyword_stats_map.values())
    max_platforms = max(len(s.platforms) for s in keyword_stats_map.values())

    scored: list[ScoredKeyword] = []
    for kw, stats in keyword_stats_map.items():
        score = calculate_weighted_score(stats, max_platforms, max_hot, max_consecutive)
        scored.append(ScoredKeyword(keyword=kw, score=score, stats=stats))

    scored.sort(key=lambda x: x.score, reverse=True)
    top_k = scored[:_TOP_K]

    # 转为 dict 格式方便 pusher 使用
    result = []
    for sk in top_k:
        # 构建平台摘要
        platform_summary_parts = []
        for pt, cnt in sorted(sk.stats.platform_counts.items(), key=lambda x: -x[1]):
            pn = platform_name_map.get(pt, pt)
            platform_summary_parts.append(f"{pn}({cnt}条)")
        platform_summary = "、".join(platform_summary_parts)

        result.append({
            "keyword": sk.keyword,
            "score": round(sk.score, 4),
            "platform_summary": platform_summary,
            "related_news": sk.stats.related_news,
        })

    return result


def _build_platform_name_map() -> dict:
    """从配置文件中读取 platform_type → platform_name 映射。"""
    from config_loader import load_config
    mapping = {}
    for cat in load_config():
        for p in cat["platforms"]:
            mapping[p["type"]] = p["name"]
    return mapping


def main() -> None:
    """独立运行入口（被 keyword-aggregation.yml 调用）。"""
    window_hours = int(os.environ.get("WINDOW_HOURS", sys.argv[1] if len(sys.argv) > 1 else "6"))

    print(f"[keyword_aggregator] 聚合窗口: {window_hours} 小时")

    snapshots = load_all_history(window_hours=window_hours)
    if not snapshots:
        print("[keyword_aggregator] 无快照数据，跳过")
        return

    # 统计总平台数和总条目数
    total_platforms = len(snapshots)
    total_items = sum(len(items) for items in snapshots.values())

    scored = aggregate_keywords(snapshots, window_hours=window_hours)
    if not scored:
        print("[keyword_aggregator] 未提取到关键词")
        return

    print(f"[keyword_aggregator] 提取到 {len(scored)} 个关键词")

    # 推送
    success = push_keywords(scored, total_platforms, total_items, window_hours=window_hours)
    if success:
        print("[keyword_aggregator] 关键词推送成功")
    else:
        print("[keyword_aggregator] 关键词推送失败")


if __name__ == "__main__":
    main()