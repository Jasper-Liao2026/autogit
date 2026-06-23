#!/usr/bin/env python3
"""AutoPush — 自动推送指定文件到 GitHub"""

import json
import os
import subprocess
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


def run_git(args, capture=True):
    """运行 git 命令，返回 (returncode, stdout, stderr)。"""
    result = subprocess.run(
        ["git"] + args,
        capture_output=capture,
        text=True,
        encoding="utf-8",
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def check_git_repo():
    """检查当前目录是否是 git 仓库，不是则退出。"""
    code, _, _ = run_git(["rev-parse", "--git-dir"])
    if code != 0:
        print("✗ 错误: 当前目录不是 Git 仓库，请先运行 git init")
        sys.exit(1)


def check_remote(branch):
    """检查是否配置了远程仓库和上游分支，没有则退出。"""
    code, stdout, _ = run_git(["remote"])
    if code != 0 or not stdout:
        print("✗ 错误: 未配置远程仓库，请先运行 git remote add origin <url>")
        sys.exit(1)

    # 检查本地分支是否有上游
    code, upstream, _ = run_git(["rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"])
    if code != 0:
        print(f"✗ 错误: 分支 {branch} 没有设置上游，请先运行 git push -u origin {branch}")
        sys.exit(1)


def get_changed_files(watch_files):
    """返回 watch_files 中相比 HEAD 有变动的文件列表。

    检测方式: git diff --name-only HEAD -- <file>
    同时检测工作区和暂存区的改动。
    """
    changed = []
    for f in watch_files:
        if not os.path.exists(f):
            continue  # 不存在的文件在启动时已警告，这里静默跳过
        # 检测工作区改动
        code1, _, _ = run_git(["diff", "--quiet", "HEAD", "--", f])
        # 检测暂存区改动
        code2, _, _ = run_git(["diff", "--quiet", "--cached", "--", f])
        # 任一返回非0表示有改动
        if code1 != 0 or code2 != 0:
            changed.append(f)
    return changed


def validate_files_exist(watch_files):
    """启动时检查文件是否存在，警告跳过不存在的文件。
    返回实际存在的文件列表。"""
    existing = []
    for f in watch_files:
        if os.path.exists(f):
            existing.append(f)
        else:
            print(f"⚠ 警告: 文件 '{f}' 不存在，已跳过")
    if not existing:
        print("✗ 错误: 所有监控文件都不存在，请检查 .autopush.json 中的 files 列表")
        sys.exit(1)
    return existing


if __name__ == "__main__":
    load_config()
