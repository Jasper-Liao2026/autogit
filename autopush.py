#!/usr/bin/env python3
"""AutoPush — 自动推送指定文件到 GitHub"""

import glob as glob_mod
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta

# 修复 Windows GBK 终端 Unicode 编码问题
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

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

    # 校验 interval_minutes 为正整数
    interval = config.get("interval_minutes")
    if not isinstance(interval, int) or interval <= 0:
        print("✗ 错误: interval_minutes 必须为正整数")
        sys.exit(1)

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


def resolve_patterns(patterns):
    """展开 patterns 中的通配符和目录，返回匹配的文件路径列表。

    支持：
    - 普通文件路径: 原样保留（由 get_changed_files 检查是否存在）
    - 目录路径: 递归包含目录下所有文件（跳过 .git 目录）
    - glob 通配符: 如 *.py, src/**/*.py，支持 ** 递归匹配
    """
    expanded = set()
    has_glob_chars = lambda s: any(c in s for c in '*?[]')

    for pattern in patterns:
        # 目录 → 递归收集所有文件
        if os.path.isdir(pattern):
            found = False
            for root, dirs, filenames in os.walk(pattern):
                dirs[:] = [d for d in dirs if d != '.git']
                for fname in filenames:
                    expanded.add(os.path.normpath(os.path.join(root, fname)).replace('\\', '/'))
                    found = True
            if not found:
                print(f"⚠ 警告: 目录 '{pattern}' 下没有文件")
        elif has_glob_chars(pattern):
            # 通配符 → glob 展开
            matches = glob_mod.glob(pattern, recursive=True)
            matched = [os.path.normpath(m).replace('\\', '/') for m in matches if os.path.isfile(m)]
            expanded.update(matched)
            if not matched:
                print(f"⚠ 警告: 模式 '{pattern}' 没有匹配到任何文件")
        else:
            # 普通文件路径
            expanded.add(pattern)

    # 过滤掉 .git 目录下的文件
    result = sorted([f for f in expanded if '.git/' not in f and not f.startswith('.git/')])
    return result


def get_changed_files(watch_files):
    """返回 watch_files 中相比 HEAD 有变动的文件列表。

    同时检测工作区、暂存区和未跟踪文件的改动。
    """
    changed = []
    for f in watch_files:
        if not os.path.exists(f):
            continue  # 不存在的文件在启动时已警告，这里静默跳过
        # 检测文件是否被 git 跟踪
        code_tracked, _, _ = run_git(["ls-files", "--error-unmatch", "--", f])
        if code_tracked != 0:
            # 未跟踪的文件，存在即视为有变动
            changed.append(f)
            continue
        # 已跟踪的文件，检测工作区和暂存区改动
        code1, _, _ = run_git(["diff", "--quiet", "HEAD", "--", f])
        code2, _, _ = run_git(["diff", "--quiet", "--cached", "--", f])
        # 任一返回非0表示有改动
        if code1 != 0 or code2 != 0:
            changed.append(f)
    return changed


def validate_files_exist(patterns):
    """启动时展开 patterns，检查是否匹配到文件。
    返回展开后的文件列表。如果没有匹配到任何文件则退出。"""
    expanded = resolve_patterns(patterns)

    if not expanded:
        print("✗ 错误: 所有监控规则都没有匹配到文件，请检查 .autopush.json 中的 files 列表")
        sys.exit(1)

    return expanded


def build_commit_message(files, prefix):
    """构建 commit message。超过5个文件时，只列前3个。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    if len(files) <= 5:
        file_list = ", ".join(files)
    else:
        file_list = f"{', '.join(files[:3])}...等 {len(files)} 个文件"
    return f"{prefix}: {now} — 更新了 {file_list} ({len(files)} files)"


def git_add_files(files):
    """只 git add 指定的文件。"""
    code, _, stderr = run_git(["add"] + files)
    if code != 0:
        print(f"✗ git add 失败: {stderr}")
        return False
    return True


def git_commit(files, prefix):
    """生成 commit message 并提交。成功返回 True。"""
    message = build_commit_message(files, prefix)
    code, _, stderr = run_git(["commit", "-m", message])
    if code != 0:
        print(f"✗ git commit 失败: {stderr}")
        return False
    print(f"  ✓ 已提交: {message}")
    return True


def git_pull_rebase(branch):
    """执行 git pull --rebase origin <branch>。
    返回 (success: bool, has_conflict: bool)。"""
    code, stdout, stderr = run_git(["pull", "--rebase", "origin", branch])
    if code != 0:
        if "CONFLICT" in stdout or "CONFLICT" in stderr:
            print(f"✗ 合并冲突！请手动解决冲突后继续")
            return False, True
        # 可能只是"已经是最新的"
        if "Already up to date" in stdout or "Already up to date" in stderr:
            return True, False
        print(f"✗ git pull 失败: {stderr}")
        return False, False
    print(f"  ✓ 已拉取远程更新")
    return True, False


def git_push(branch):
    """执行 git push origin <branch>。成功返回 True。"""
    code, stdout, stderr = run_git(["push", "origin", branch])
    if code != 0:
        print(f"✗ git push 失败: {stderr}")
        return False
    print(f"  ✓ 已推送到 origin/{branch}")
    return True


def get_key():
    """非阻塞获取按键，没有按键时返回 None。"""
    if sys.platform == "win32":
        import msvcrt
        if msvcrt.kbhit():
            key = msvcrt.getch()
            try:
                return key.decode("utf-8").lower()
            except UnicodeDecodeError:
                return None
        return None
    else:
        # Unix (macOS/Linux)
        import select
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            r, _, _ = select.select([sys.stdin], [], [], 0)
            if r:
                return sys.stdin.read(1).lower()
            return None
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def get_key_blocking():
    """阻塞等待按键，用于暂停状态。"""
    if sys.platform == "win32":
        import msvcrt
        key = msvcrt.getch()
        try:
            return key.decode("utf-8").lower()
        except UnicodeDecodeError:
            return ""
    else:
        import tty
        import termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)
            return sys.stdin.read(1).lower()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def render_status(config, patterns, state, next_check, last_push):
    """打印运行状态界面。"""
    # 清屏
    os.system("cls" if sys.platform == "win32" else "clear")

    status_icon = {"running": "▶ 运行中", "paused": "⏸ 已暂停"}[state]
    hints = "[p]暂停  [q]退出" if state == "running" else "[r]恢复  [q]退出"

    print("=" * 45)
    print(f"  AutoPush 自动推送 | 状态: {status_icon}")
    print(f"  监控规则: {', '.join(patterns)}")
    print(f"  间隔: {config['interval_minutes']}分钟 | 分支: {config['branch']}")
    print(f"  {hints}")
    print("=" * 45)

    next_str = next_check.strftime("%Y-%m-%d %H:%M:%S") if next_check else "--"
    push_str = last_push if last_push else "尚无推送"
    print(f"下次检查: {next_str}  |  上次推送: {push_str}")


def main():
    # 1. 环境校验
    check_git_repo()

    # 2. 加载配置（不存在时自动生成并退出）
    config = load_config()

    check_remote(config["branch"])

    # 3. 校验监控规则
    watch_patterns = config["files"]
    initial_files = resolve_patterns(watch_patterns)
    if not initial_files:
        print("✗ 错误: 所有监控规则都没有匹配到文件，请检查 .autopush.json 中的 files 列表")
        sys.exit(1)
    print(f"✓ 监控规则: {', '.join(watch_patterns)}")
    print(f"  当前匹配 {len(initial_files)} 个文件")

    # 4. 初始化状态
    state = "running"  # running | paused
    interval = config["interval_minutes"] * 60  # 转为秒
    next_check = datetime.now() + timedelta(seconds=interval)  # 首次检查在未来 interval 秒后
    last_push_info = None
    consecutive_failures = 0
    push_count = 0
    start_time = datetime.now()

    # 首次渲染
    render_status(config, watch_patterns, state, next_check, last_push_info)

    # 5. 主循环
    tick = 0.2  # 每0.2秒检查一次按键
    elapsed = 0.0  # 距离上次检查的累计秒数

    try:
        while True:
            time.sleep(tick)

            # --- 处理按键 ---
            key = get_key()
            if key == "q":
                break
            elif key == "p" and state == "running":
                state = "paused"
                next_check = None
                render_status(config, watch_patterns, state, next_check, last_push_info)
                print("\n已暂停，按 [r] 恢复")
            elif key == "r" and state == "paused":
                state = "running"
                consecutive_failures = 0  # 手动恢复时重置失败计数
                next_check = datetime.now() + timedelta(seconds=interval)  # 恢复后立即检查一次
                elapsed = interval  # 触发立即检查
                render_status(config, watch_patterns, state, next_check, last_push_info)
                print("\n已恢复运行")

            # --- 暂停时跳过检查 ---
            if state == "paused":
                continue

            # --- 累计时间 ---
            elapsed += tick

            # --- 更新倒计时显示（每秒刷新） ---
            if int(elapsed) != int(elapsed - tick):
                render_status(config, watch_patterns, state, next_check, last_push_info)

            # --- 到达检查时间 ---
            if elapsed < interval:
                continue
            elapsed = 0.0
            next_check = datetime.now() + timedelta(seconds=interval)

            # 重新展开模式（捕获新文件），检测变动
            current_files = resolve_patterns(watch_patterns)
            changed = get_changed_files(current_files)

            if not changed:
                render_status(config, watch_patterns, state, next_check, last_push_info)
                continue

            # 有变动 → 执行 git 操作
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 检测到 {len(changed)} 个文件变动...")

            if not git_add_files(changed):
                continue

            if not git_commit(changed, config["commit_prefix"]):
                continue

            # pull --rebase
            pull_ok, has_conflict = git_pull_rebase(config["branch"])
            if has_conflict:
                state = "paused"
                last_push_info = f"{datetime.now().strftime('%H:%M')} ⚠ 冲突，需手动解决"
                render_status(config, watch_patterns, state, None, last_push_info)
                print("\n⚠ 检测到合并冲突，已自动暂停。请手动解决冲突后按 [r] 恢复。")
                continue
            if not pull_ok:
                consecutive_failures += 1
                last_push_info = f"{datetime.now().strftime('%H:%M')} ✗ pull 失败"
            else:
                # push
                if git_push(config["branch"]):
                    consecutive_failures = 0
                    push_count += 1
                    last_push_info = f"{datetime.now().strftime('%H:%M')} ✓ 第{push_count}次推送成功"
                else:
                    consecutive_failures += 1
                    last_push_info = f"{datetime.now().strftime('%H:%M')} ✗ push 失败"

            # 连续失败10次 → 自动暂停
            if consecutive_failures >= 10:
                state = "paused"
                last_push_info = f"{datetime.now().strftime('%H:%M')} ⚠ 连续10次失败，已暂停"
                render_status(config, watch_patterns, state, None, last_push_info)
                print(f"\n⚠ 连续 {consecutive_failures} 次推送失败，已自动暂停。按 [r] 恢复。")
                continue

            render_status(config, watch_patterns, state, next_check, last_push_info)

    except KeyboardInterrupt:
        print("\n")  # 换行

    # 6. 退出统计
    runtime = datetime.now() - start_time
    minutes = int(runtime.total_seconds() // 60)
    seconds = int(runtime.total_seconds() % 60)
    print("=" * 45)
    print(f"  AutoPush 已退出")
    print(f"  运行时间: {minutes}分{seconds}秒")
    print(f"  成功推送: {push_count} 次")
    print(f"  连续失败: {consecutive_failures} 次")
    print("=" * 45)


if __name__ == "__main__":
    main()
