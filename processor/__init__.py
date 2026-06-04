"""Processor 模块"""

from .interface import NewsItem, NewsProcessor, ProcessContext
from .pipeline import ProcessorPipeline

__all__ = ["NewsItem", "NewsProcessor", "ProcessContext", "ProcessorPipeline"]