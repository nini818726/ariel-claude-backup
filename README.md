# ariel-claude-backup

作者：Ariel · MIT 开源

**换 Claude 账号、换电脑，你的工作不丢、不乱。**

给 Claude 桌面 App（Code 页）用的插件，解决三件事：

1. **换号后对话全没了** —— 每 10 分钟把 Code 页的全部对话、记忆、skills、设置、插件、MCP 配置自动备份到**你自己的 GitHub 私有仓库**（只传有变化的部分，几秒钟）。换号或换电脑后说一句「从 GitHub 恢复我的 Claude」，全部回来，点进去能接着聊。
2. **不想让新账号看到旧账号的信息** —— 上传前自动抹掉旧账号的身份信息（账号编号、登录邮箱、设备编号、请求编号、签名、账号链接、密钥），自检 0 残留才上传。
3. **文件夹挪了、改名了，对话就找不到地方** —— 每个项目文件夹放一张隐藏「身份证」（`.claude-folder-id`）。挪位置、改名、放进移动硬盘，都能自动找回，对话跟过去。

装好后输入框下面会多一行：`☁️ 备份正常 · 18:04 同步过 · 277 个对话`。上传失败、很久没备份、文件夹挪了需要重开，都会在这里提醒。

不花 Claude 的 token，不占电脑空间（存在 GitHub 上）。

## 安装

前提：macOS + Claude 桌面 App；一个 GitHub 账号（免费）。

在 Claude 的 Code 页依次输入：

```
/plugin marketplace add kkkariel888/ariel-claude-backup
/plugin install ariel-claude-backup@ariel-claude-backup
```

然后对 Claude 说：**「开始备份」**。

Claude 会帮你装好 GitHub 工具；需要登录 GitHub 时会请你自己在浏览器确认（密码只由你输入）。之后它会在你的 GitHub 上自动建一个私有仓库 `claude-backup`，开始每 10 分钟自动备份。

## 换号 / 换电脑

1. 新电脑：先用 U 盘把项目文件夹**整个**拷过去（隐藏的身份证会跟着走）。
2. 登录新的 Claude 账号，按上面的步骤装插件。
3. 在 Code 页说：**「从 GitHub 恢复我的 Claude」**。
4. 按提示 ⌘Q 退出 Claude 再打开，以前的对话就在左边了。

## 带不走的

- Cowork 任务对话、claude.ai 网页聊天（存在 Anthropic 服务器上）。
- 连接器 / 需要登录授权的 MCP，要重新授权。
- 抹掉的是本地文件里的账号信息；同一台电脑、同一网络，服务器端仍可能把两个账号联系起来。

## English

A Claude Code (desktop app, macOS) plugin by Ariel. It backs up every Code-tab conversation, memory, skill, setting, plugin and MCP config to your own **private** GitHub repo every 10 minutes (incremental), with old-account identifiers scrubbed and verified before upload. After switching accounts or computers, say "restore my Claude from GitHub" and keep working. Hidden `.claude-folder-id` files let conversations follow project folders that are moved or renamed. A status line under the prompt shows the backup state. MIT licensed.
