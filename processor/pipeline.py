"""ProcessorPipeline：按顺序执行多个处理器"""

from .interface import NewsItem, NewsProcessor, ProcessContext


class ProcessorPipeline:
    """处理器流水线：按顺序执行多个处理器"""

    def __init__(self, processors: list[NewsProcessor]):
        self._processors = processors

    def run(self, context: ProcessContext, items: list[NewsItem]) -> list[NewsItem]:
        for processor in self._processors:
            items = processor.process(context, items)
        return items