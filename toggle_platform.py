"""
切换单个平台的启用状态（被 toggle-platform.yml 调用）

用法:
    python toggle_platform.py <platform_type>

效果:
    读取 config/enabled_platforms.json → 翻转指定平台的 enabled 值 → 写回
"""

import json
import sys
import os

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "enabled_platforms.json")


def toggle_platform(platform_type: str) -> bool:
    """
    切换指定平台的启用状态。

    返回:
        True 表示切换成功，False 表示未找到该平台
    """
    if not os.path.exists(_CONFIG_PATH):
        print(f"[toggle] 配置文件不存在: {_CONFIG_PATH}")
        return False

    with open(_CONFIG_PATH, encoding="utf-8") as f:
        data = json.load(f)

    found = False
    for cat in data.get("categories", []):
        for p in cat.get("platforms", []):
            if p["type"] == platform_type:
                p["enabled"] = not p["enabled"]
                status = "启用" if p["enabled"] else "关闭"
                print(f"[toggle] {p['name']}({platform_type}) → {status}")
                found = True
                break

    if found:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"[toggle] 配置已更新")
    else:
        print(f"[toggle] 未找到平台: {platform_type}")

    return found


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python toggle_platform.py <platform_type>")
        sys.exit(1)

    success = toggle_platform(sys.argv[1])
    sys.exit(0 if success else 1)