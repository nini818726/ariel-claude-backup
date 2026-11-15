# Claude 备份（私有）

每天晚上自动更新。里面是 Claude App 的 Code 页对话、偏好、skill、插件、设置。
上传前已抹掉 Claude 账号的编号、邮箱、登录信息和账号链接，换号后新账号看不到旧账号的任何信息。

## 换 Claude 账号时（同一台 Mac）

用新账号登录 Claude App，在 Code 页说：「从 GitHub 恢复我的 Claude」。
它会自己做完，最后按 ⌘Q 重开 App 即可。

## 换了一台新 Mac

1. 在新 Mac 上装好 Claude App（先别登录）。
2. 下载这个仓库：终端里运行 `gh repo clone claude-backup ~/.claude-backup/repo`
   （或网页上 Code → Download ZIP 解压）。
3. 登录新账号，在 Code 页说：「运行 ~/.claude-backup/repo/tool/claude_backup.py adopt 恢复我的 Claude」。

带不走：Cowork 任务对话、claude.ai 网页聊天（在服务器上）。
30 天没动过的对话，Claude 会按官方规则自己删除。
