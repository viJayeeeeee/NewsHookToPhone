"""飞书消息推送（富文本 + 签名）"""

import hashlib
import hmac
import json
import os
import time
from base64 import b64encode
from typing import Optional

import requests

_WEBHOOK_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")
_SECRET = os.environ.get("FEISHU_SECRET", "")


def _gen_sign(timestamp: int) -> str:
    """生成飞书签名校验。"""
    if not _SECRET:
        return ""
    string_to_sign = f"{timestamp}\n{_SECRET}"
    hmac_code = hmac.new(
        _SECRET.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return b64encode(hmac_code).decode("utf-8")


def _build_platform_payload(
    platform_name: str,
    items: list,
    update_time: str,
) -> dict:
    """
    构建单个平台的推送 payload。

    参数:
        platform_name: 平台名称，如 "微博热搜"
        items: 推送条目列表，每项包含 title, formatted_hot, extra 等
        update_time: 数据更新时间字符串

    返回:
        飞书富文本消息 payload
    """
    content_lines = [
        [{"tag": "text", "text": f"{'=' * 40}"}],
        [{"tag": "text", "text": f"📍 {platform_name} · {update_time}"}],
        [{"tag": "text", "text": f"{'=' * 40}"}],
    ]

    for item in items:
        rank = item.get("index", "")
        title = item.get("title", "")
        hot = item.get("formatted_hot", item.get("hot_value", ""))
        tags = item.get("extra", {}).get("display_tags", "")

        line_text = f"#{rank}  {title}   {hot}"
        if tags:
            line_text += f"  {tags}"

        content_lines.append([{"tag": "text", "text": line_text}])

    content_lines.append([{"tag": "text", "text": f"{'=' * 40}"}])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"📍 {platform_name}",
                    "content": content_lines,
                }
            }
        },
    }


def _build_keyword_payload(
    scored_keywords: list,
    total_platforms: int,
    total_items: int,
    window_hours: int,
) -> dict:
    """
    构建关键词聚合推送 payload。

    参数:
        scored_keywords: ScoredKeyword 列表（需包含 keyword, score, related_news, stats 等字段）
        total_platforms: 覆盖平台数
        total_items: 覆盖条目数
        window_hours: 聚合窗口

    返回:
        飞书富文本消息 payload
    """
    content_lines = [
        [{"tag": "text", "text": f"{'=' * 45}"}],
        [{"tag": "text", "text": f"🔥 热点关键词聚合 · 过去 {window_hours} 小时"}],
        [{"tag": "text", "text": f"{'=' * 45}"}],
    ]

    for i, kw in enumerate(scored_keywords, 1):
        score_str = f"{kw.get('score', 0) * 100:.1f}"
        fire_count = "🔥" * min(int(kw.get('score', 0) * 5) + 1, 3)
        content_lines.append([
            {"tag": "text", "text": f"{i}.  "},
            {"tag": "text", "text": kw.get("keyword", ""), "style": [["bold"]]},
            {"tag": "text", "text": f"    {score_str}分  {fire_count}"},
        ])

        # 关联新闻行（斜体小字）
        platform_summary = kw.get("platform_summary", "")
        if platform_summary:
            content_lines.append([
                {"tag": "text", "text": f"    出现在: {platform_summary}", "style": [["italic"]]},
            ])

        # 各平台具体条目
        for news in kw.get("related_news", []):
            content_lines.append([
                {"tag": "text", "text": f"    ├ {news.get('platform_name', '')}: {news.get('title', '')}",
                 "style": [["italic"]]},
            ])

        content_lines.append([{"tag": "text", "text": ""}])

    content_lines.append([{"tag": "text", "text": f"{'=' * 45}"}])
    content_lines.append([
        {"tag": "text", "text": f"📊 基于 {total_platforms} 个平台、{total_items} 条热榜数据"}
    ])

    return {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": "🔥 热点关键词聚合",
                    "content": content_lines,
                }
            }
        },
    }


def _build_card_payload(categories: list[dict]) -> dict:
    """
    构建控制面板卡片 payload。

    参数:
        categories: categories 配置列表

    返回:
        飞书消息卡片 payload
    """
    header_text = f"🔧 热榜推送控制面板\n当前已启用: {sum(1 for c in categories for p in c['platforms'] if p['enabled'])}/{sum(len(c['platforms']) for c in categories)} 个平台"

    elements = [
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": header_text},
        },
        {"tag": "hr"},
    ]

    # TODO: 生成完整卡片（含按类别的按钮布局）
    for cat in categories:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"{cat.get('icon', '')} {cat['name']}"},
        })

        btn_group = []
        for p in cat["platforms"]:
            status = "✅" if p["enabled"] else "❌"
            btn_group.append({
                "tag": "button",
                "text": {"tag": "lark_md", "content": f"{status}{p['name']}"},
                "type": "default",
                "multi_url": {
                    "url": f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'owner/repo')}/actions/workflows/toggle-platform.yml?workflow_dispatch[platform]={p['type']}",
                    "android_url": "",
                    "ios_url": "",
                    "pc_url": "",
                },
            })

        elements.append({
            "tag": "action",
            "actions": btn_group,
        })

    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": "点击按钮切换对应平台的启用状态，切换后将在下一次轮转时生效"}],
    })

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": "🔧 热榜推送控制面板"},
                "template": "blue",
            },
            "elements": elements,
        },
    }


def push_platform(platform_name: str, items: list, update_time: str) -> bool:
    """
    推送单个平台的热榜消息到飞书。

    返回:
        True 表示推送成功，False 表示失败
    """
    payload = _build_platform_payload(platform_name, items, update_time)
    return _do_push(payload)


def push_keywords(scored_keywords: list, total_platforms: int, total_items: int, window_hours: int = 6) -> bool:
    """
    推送关键词聚合消息到飞书。

    返回:
        True 表示推送成功，False 表示失败
    """
    payload = _build_keyword_payload(scored_keywords, total_platforms, total_items, window_hours)
    return _do_push(payload)


def push_control_card(categories: list[dict]) -> bool:
    """
    推送控制面板卡片到飞书。

    返回:
        True 表示推送成功，False 表示失败
    """
    payload = _build_card_payload(categories)
    return _do_push(payload)


def _do_push(payload: dict) -> bool:
    """发送 payload 到飞书 Webhook。"""
    if not _WEBHOOK_URL:
        print("[pusher] FEISHU_WEBHOOK_URL 未设置，跳过推送")
        return False

    body = {**payload}
    if _SECRET:
        timestamp = int(time.time())
        body["timestamp"] = str(timestamp)
        body["sign"] = _gen_sign(timestamp)

    try:
        resp = requests.post(_WEBHOOK_URL, json=body, timeout=10)
        result = resp.json()
        if result.get("code") == 0:
            return True
        elif result.get("code") == 11232:
            # 限流，重试一次
            print("[pusher] 限流，等待 5 秒重试...")
            time.sleep(5)
            resp = requests.post(_WEBHOOK_URL, json=body, timeout=10)
            return resp.json().get("code") == 0
        else:
            print(f"[pusher] 飞书推送失败: {result}")
            return False
    except requests.RequestException as e:
        print(f"[pusher] 网络错误: {e}")
        return False