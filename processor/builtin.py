"""内置处理器实现"""

import re

from .interface import NewsItem, NewsProcessor, ProcessContext


class HotValueFormatter(NewsProcessor):
    """热度格式化: 1138695 → 113.9万"""

    def process(self, context: ProcessContext, items: list[NewsItem]) -> list[NewsItem]:
        for item in items:
            item.extra["formatted_hot"] = self._format_hot(item.hot_value)
        return items

    @staticmethod
    def _format_hot(value: str) -> str:
        try:
            v = int(value)
        except (ValueError, TypeError):
            return value
        if v >= 10_0000:
            return f"{v / 10_000:.1f}万"
        if v >= 1000:
            return f"{v / 1000:.1f}千"
        return str(v)


class RankStabilizer(NewsProcessor):
    """排序稳定器: 确保同热度时按 index 排序"""

    def process(self, context: ProcessContext, items: list[NewsItem]) -> list[NewsItem]:
        items.sort(key=lambda x: (self._safe_hot(x.hot_value), -x.index), reverse=True)
        return items

    @staticmethod
    def _safe_hot(value: str) -> int:
        try:
            return int(value)
        except (ValueError, TypeError):
            return 0


class TitleCleaner(NewsProcessor):
    """标题净化: 去除多余空格/特殊字符"""

    def process(self, context: ProcessContext, items: list[NewsItem]) -> list[NewsItem]:
        for item in items:
            item.title = re.sub(r"\s+", " ", item.title).strip()
        return items