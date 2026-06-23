#!/usr/bin/env python3
"""AutoPush — 自动推送指定文件到 GitHub"""

import json
import os
import sys

CONFIG_FILE = ".autopush.json"

DEFAULT_CONFIG = {
    "interval_minutes": 30,
    "branch": "main",
    "files": [
        "example.py",
        "README.md"
    ],
    "commit_prefix": "Auto"
}


def generate_default_config():
    """生成默认配置文件并退出。"""
    if os.path.exists(CONFIG_FILE):
        print(f"✓ 配置文件 {CONFIG_FILE} 已存在")
        return False
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
    print(f"✓ 已生成默认配置文件 {CONFIG_FILE}，请编辑 files 列表后重新运行")
    return True


def load_config():
    """读取并校验配置文件，返回配置字典。配置缺失时退出。"""
    if not os.path.exists(CONFIG_FILE):
        generate_default_config()
        sys.exit(0)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 校验必填字段
    if "files" not in config or not config["files"]:
        print("✗ 错误: .autopush.json 中 files 列表为空，请添加要监控的文件")
        sys.exit(1)

    # 填充默认值
    config.setdefault("interval_minutes", 30)
    config.setdefault("branch", "main")
    config.setdefault("commit_prefix", "Auto")

    return config


if __name__ == "__main__":
    load_config()
