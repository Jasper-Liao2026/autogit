# AutoPush — 自动推送到 GitHub 工具

**日期**: 2026-06-23
**状态**: 已确认

## 概述

一个 Python 脚本工具，定时监控 git 仓库中指定的文件，检测到变动时自动 commit 并 push 到 GitHub。支持终端按键实时控制开关（暂停/恢复/退出）。

## 架构

```
项目根目录/
├── autopush.py          # 主程序（单文件）
└── .autopush.json       # 配置文件
```

单文件脚本，无外部依赖（仅使用 Python 标准库 + git 命令行）。

## 工作流程

```
启动
  │
  ├─→ 校验环境
  │     ├─ 当前目录是 git 仓库？ → 否 → 报错退出
  │     └─ 有配置远程仓库？     → 否 → 报错退出
  │
  ├─→ 读取 .autopush.json
  │     ├─ 文件不存在？ → 自动生成示例配置 → 退出让用户编辑
  │     └─ 校验 files 列表中哪些文件存在 → 警告跳过不存在的
  │
  └─→ 进入主循环（状态: 运行中 ▶）
        │
        ├─ 每 N 分钟（默认30）检查一次
        │
        ├─ 监控的文件有变动？
        │     ├─ 否 → 输出"无变动"，继续等待
        │     └─ 是 →
        │           ├─ git add <仅监控的文件>
        │           ├─ git commit -m "Auto: 2026-06-23 23:11 — 更新了 file1.py, file2.md (2 files)"
        │           ├─ git pull --rebase（先拉取远程更新避免冲突）
        │           ├─ git push
        │           └─ 输出结果（成功/失败）
        │
        └─ 按键控制（非阻塞检测）
              ├─ [p] → 暂停 ⏸（跳过检查，保留循环）
              ├─ [r] → 恢复 ▶
              └─ [q] → 退出程序
```

## 配置设计

`.autopush.json`：

```json
{
  "interval_minutes": 30,
  "branch": "main",
  "files": [
    "src/main.py",
    "config.json"
  ],
  "commit_prefix": "Auto"
}
```

| 字段 | 类型 | 说明 | 默认值 |
|------|------|------|--------|
| `interval_minutes` | int | 检查间隔（分钟） | 30 |
| `branch` | string | 推送目标分支 | `"main"` |
| `files` | string[] | 监控文件列表（相对路径） | 必填 |
| `commit_prefix` | string | commit 信息前缀 | `"Auto"` |

## 提交信息格式

```
<commit_prefix>: YYYY-MM-DD HH:MM — 更新了 file1.py, file2.md (N files)
```

示例：
```
Auto: 2026-06-23 23:11 — 更新了 main.py, config.json (2 files)
```

## 运行界面

```
==================================
  AutoPush 运行中 | 状态: ▶ 运行中
  监控: src/main.py, config.json
  间隔: 30分钟 | 分支: main
  [p]暂停  [q]退出
==================================
下次检查: 2026-06-23 23:41:00  |  上次推送: 23:11 ✓ 成功
```

暂停时：
```
  状态: ⏸ 已暂停  |  [r]恢复  [q]退出
```

## 错误处理

| 场景 | 处理 |
|------|------|
| 不在 git 仓库 | 启动时检测，提示并退出 |
| 未配置远程仓库 | 启动时检测，提示并退出 |
| .autopush.json 不存在 | 自动生成示例文件，提示用户编辑后重新运行 |
| files 中文件不存在 | 启动时警告，跳过不存在的，继续监控其余 |
| 检查周期内无改动 | 输出"无变动"，不产生空提交 |
| push 网络失败 | 输出错误，等下一轮重试，连续失败 10 次后自动暂停 |
| 远程有新提交 | 先 `git pull --rebase` 再 push，有冲突时暂停并提示手动解决 |
| Ctrl+C 中断 | 优雅退出，显示本次运行统计 |

## 技术选型

- **语言**: Python 3.x
- **依赖**: 仅标准库（`subprocess`, `json`, `time`, `threading`）
- **平台**: Windows（也兼容 macOS/Linux）
- **Git 操作**: 通过 `subprocess` 调用 git CLI

## 非功能需求

- 不产生空 commit
- 只 add 配置中指定的文件，不影响仓库其他文件
- 支持文件名中文路径
- 超过 5 个被监控文件时，commit message 中只列前 3 个文件名 + `...等 N 个文件`
