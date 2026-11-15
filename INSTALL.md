# 给 AI 助手的安装说明（Claude 桌面 app Code 页 / Claude Code）

> 用户把这个仓库链接发给你，说「帮我装上」，你就照下面做完，**一次做完，不要分几轮问**。
> 跟用户说话用中文、大白话；只有真的需要用户本人点一下的，才停下来叫他。

这个仓库装一个插件：`ariel-claude-backup`（skill `ai-backup` + 备份程序 + 输入框下面的状态行），只支持 macOS。

## 1. 检查工具
- `git`、`python3`：没有就运行 `xcode-select --install`，让用户在弹窗里点「安装」，装完再继续
- `gh`：没有就 `brew install gh`；没有 Homebrew 先装 https://brew.sh（要用户输一次开机密码）
- `gh auth status` 没登录：请用户**自己**在终端运行 `gh auth login`，在浏览器里点授权。密码只由用户输入，你不要代填

## 2. 装插件
```bash
claude plugin marketplace add kkkariel888/ariel-claude-backup
claude plugin install ariel-claude-backup@ariel-claude-backup
```
跑不了 `claude` 命令时，把这两行发给用户在 Code 页输入（前面加 `/`）：
`/plugin marketplace add kkkariel888/ariel-claude-backup`、`/plugin install ariel-claude-backup@ariel-claude-backup`。
然后请用户打开自动更新：`/plugin` → Marketplaces → ariel-claude-backup → Enable auto-update。

## 3. 开始备份 / 恢复
找到插件里的 `skills/ai-backup/scripts/claude_backup.py`（记为 `$S`），运行：
```bash
python3 -I "$S" setup
```
它自己判断：GitHub 上没有 `claude-backup` 就建一个**私有**仓库并开始备份；已有备份而这个账号几乎没对话（新账号 / 新电脑）就恢复；最后装好每 10 分钟一次的自动同步。

## 4. 告诉用户结果
- 开始备份了：输入框下面会出现「☁️ 备份正常 · 几点同步过 · 多少个对话」（插件要在新对话或重开 Claude 后才加载）
- 做了恢复：请用户 ⌘Q 退出 Claude 再打开，左侧就是以前的对话；连接器要重新授权；旧账号原始数据在 `~/Claude旧账号原始数据-日期`，确认没问题后可以删
- 照实说带不走的：Cowork 和网页版对话
