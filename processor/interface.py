"""Processor 中间层：标准化数据结构与处理器接口"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class NewsItem:
    """单条热榜条目的标准化中间表示"""

    # 原始数据
    title: str
    url: str
    hot_value: str  # 原始热度字符串，如 "1138695"
    index: int  # 当前排名
    platform_type: str  # 平台标识，如 "weibo"
    platform_name: str  # 平台名称，如 "微博热搜"

    # 处理器填充字段（初始为空，由 processor 填充）
    summary: Optional[str] = None
    keywords: list[str] = field(default_factory=list)
    sentiment: Optional[str] = None
    category: Optional[str] = None
    importance_score: Optional[float] = None
    is_sensitive: bool = False
    extra: dict = field(default_factory=dict)


@dataclass
class ProcessContext:
    """处理器上下文：跨处理器共享的运行时信息"""

    platform_type: str
    platform_name: str
    fetch_time: str  # 数据获取时间
    category_name: str  # 所属类别名（如"社交媒体·热榜"）
    all_items: list[NewsItem]  # 本轮所有条目
    snapshot: Optional[dict] = None  # 该平台历史快照
    extra: dict = field(default_factory=dict)  # 扩展字段


class NewsProcessor:
    """处理器基类：所有具体处理器继承此类"""

    def process(self, context: ProcessContext, items: list[NewsItem]) -> list[NewsItem]:
        """
        处理一批新闻条目。

        参数:
            context: 处理上下文，包含平台信息、快照等
            items:   待处理的新闻条目列表

        返回:
            处理后的新闻条目列表（可过滤、排序、增强）
        """
        return items