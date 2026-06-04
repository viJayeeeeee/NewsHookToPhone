"""
生成并发送控制面板卡片到飞书群聊（被 send-control-card.yml 调用）

用法:
    python send_control_card.py
"""

import os
import sys

from config_loader import load_config
from pusher import push_control_card


def main() -> None:
    print("[send_control_card] 加载配置...")
    categories = load_config()

    print(f"[send_control_card] 发送控制卡片（{sum(len(c['platforms']) for c in categories)} 个平台）...")
    success = push_control_card(categories)
    if success:
        print("[send_control_card] 控制卡片发送成功")
    else:
        print("[send_control_card] 控制卡片发送失败")
        sys.exit(1)


if __name__ == "__main__":
    main()