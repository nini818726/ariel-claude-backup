# 设计说明与边界

## 备份仓库的结构

| 仓库里的路径 | 来源 | 内容 |
|---|---|---|
| `claude-home/` | `~/.claude/` | 对话记录 `projects/<项目>/<会话>.jsonl`、自动记忆 `projects/<项目>/memory/`、`CLAUDE.md`、`settings.json`、`skills/`、`commands/`、`agents/`、`rules/`、`plugins/`、`history.jsonl`、`file-history/`、`plans/`、`tasks/`、`todos/`、`paste-cache/`、`keybindings.json` 等 |
| `claude.json` | `~/.claude.json` | 个人 MCP 服务器、各项目的权限与信任设置、界面偏好（已去掉账号信息） |
| `desktop-app/` | `~/Library/Application Support/Claude/` | 桌面 App 配置 `claude_desktop_config.json`、扩展、本地会话数据（去掉缓存、登录 cookie、虚拟机镜像） |
| `project-local/` | 各项目目录 | 被 git 忽略的个人文件：`CLAUDE.local.md`、`.claude/settings.local.json`、`.mcp.json` |
| `backup-manifest.json` | 生成 | 原 home 路径、每个文件的原始修改时间（恢复时还原） |
| `SECRETS-TO-REFILL.md` | 生成 | 哪些配置项的密钥被抹掉了（只有位置，没有值） |

## 故意不备份的

- `~/.claude/.credentials.json` 和 macOS 钥匙串里的登录凭证：换号本来就要重新登录，传上去只有风险。
- `~/.claude.json` 里的 `oauthAccount`、`userID` 等账号字段：恢复时保留新账号自己的。
- `skills/synced/`：由 Claude 按账号自动同步，不是用户数据。
- 缓存、调试日志、shell 快照、运行时状态、任何 `.git` 目录。
- 桌面 App 里的登录令牌文件（`buddy-tokens.json`）、设备编号、各种缓存。
- 单个超过 95 MB 的文件（GitHub 上限 100 MB）：会在输出里用 `! skipped` 明确列出。

## 关键行为

- **只增不删**：本机删掉或被 30 天清理掉的对话，仓库里仍然保留。代价是本机删除的 skill 恢复时也会回来。
- **增量**：按修改时间 + 大小判断，没变的文件不重写。`backup --full` 强制全量。
- **脱敏**：上传前对所有文本文件做模式匹配（Anthropic / OpenAI / GitHub / AWS / Google / Slack / Stripe 等 key、JWT、Bearer、私钥块、`token=xxx` 形式的赋值），替换为 `[REDACTED:类型]`；配置 JSON 中名字像密钥的字段整体替换为 `<REDACTED-REFILL-ME>`。对话的结构和其余文字不变，仍可 resume。**模式匹配不保证抓到所有密钥**，所以仓库必须保持私有；脚本推送前会用 gh 检查，发现是公开仓库就拒绝推送。
- **30 天清理**：按用户要求保持官方规则（30 天没动过的对话会被 Claude 删除），脚本不改 `cleanupPeriodDays`。
- **路径重定向**：对话按项目的绝对路径归档（`/Users/alice/app` → `-Users-alice-app`）。home 目录变了的话，恢复时会重命名这些文件夹、改写记录里的 `cwd`，并同步改仓库里的结构，避免之后出现重复。项目本身如果搬到了完全不同的相对位置，需要手动把对应文件夹改名。

## 「和原账号没有区别」能做到什么程度

| 项目 | 结果 |
|---|---|
| 本机 Claude Code 对话（CLI 与桌面 App 的 Code 标签本地会话） | 完整恢复，可继续对话 |
| 自动记忆、CLAUDE.md、skills、commands、agents、rules、设置、快捷键 | 完整恢复 |
| 插件、MCP 服务器配置 | 恢复；密钥需手填，OAuth 类需重新授权 |
| 云端会话（claude.ai/code、手机） | 仅限换号前 `claude --teleport` 拉到本机的那些；新账号网页列表里不会出现 |
| 桌面 App Code 页左侧列表 | 列表条目在 `claude-code-sessions/<账号ID>/<组织ID>/local_*.json`，每条通过 `cliSessionId` 指向 `~/.claude/projects/.../<id>.jsonl` 里的聊天内容。App 只读当前登录账号那一层文件夹，所以 `restore --desktop` 会把条目搬到新账号 ID 下（ID 取自 App 的 `config.json → lastKnownAccountUuid` 和 `~/.claude.json → oauthAccount`），并合并归档标记。App 启动时一次性读列表，恢复后要重开 App。2026-11-14 本机实测：挪走条目和聊天文件→重启后从列表消失→`restore --desktop`→重启后回到列表、能继续聊。换账号的搬文件夹逻辑只用假账号演练过，还没用真新账号验证 |
| Cowork 任务 | 对话本体在 Anthropic 服务器上（`session_01…` 编号），跟账号走，换号带不走。本机 `local-agent-mode-sessions/` 只有任务↔文件夹的对应表和插件缓存，备份它只是留底；Cowork 用到的本机文件夹本身不受影响 |
| claude.ai 网页 / App 的普通聊天、Projects、账号记忆 | 不能迁入新账号。可在旧账号 设置 → 隐私 → 导出数据 拿到存档，放进仓库留底 |
| 订阅、用量额度、组织设置 | 跟账号走，无法迁移 |

## 本地状态

`~/.claude-backup/`：`repo/`（仓库的本地克隆）、`state.json`（增量状态）、`backup.log`（定时任务日志）、`pre-restore-*/`（恢复前的安全副本）。定时任务是 `~/Library/LaunchAgents/com.claude-backup.daily.plist`。
