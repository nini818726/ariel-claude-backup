#!/bin/bash
if [ -z "$HTTPS_PROXY" ]; then p=$(scutil --proxy 2>/dev/null | awk '/HTTPSEnable/{e=$3}/HTTPSProxy/{h=$3}/HTTPSPort/{t=$3}END{if(e==1)print "http://"h":"t}'); [ -n "$p" ] && export HTTPS_PROXY=$p HTTP_PROXY=$p; fi  # use the Mac proxy (GitHub)
# 换 Claude 账号（或换电脑）后一键恢复：Code 页对话、偏好、skill、插件、设置。
# 不需要先登录新账号，双击后跟着提示做。
if [ -z "$CLAUDE_SWITCH_DIR" ]; then   # run from a temp copy: this file gets refreshed by the backup
  tmp="$(mktemp -t claude-switch)"; cp "$0" "$tmp"
  CLAUDE_SWITCH_DIR="$(cd "$(dirname "$0")" && pwd)" exec bash "$tmp"
fi
DIR="$CLAUDE_SWITCH_DIR"; T="$DIR/tool/claude_backup.py"; cd "$DIR"
bye() { echo; read -p "按回车关闭这个窗口"; exit "$1"; }
quit_claude() {
  pgrep -x Claude >/dev/null || return 0
  osascript -e 'quit app "Claude"'
  for i in $(seq 30); do pgrep -x Claude >/dev/null || return 0; sleep 1; done
  echo "❌ Claude 没能退出，请手动按 ⌘Q 退出后再双击我。"; bye 1
}
echo "【Claude 换号一键恢复】"
echo "不用先登录新账号，跟着提示做就行。中途关掉窗口也没关系，再双击一次会接着做。"
read -p "按回车开始（会先退出 Claude App）"
quit_claude
if [ -d .git ]; then
  git pull -q 2>/dev/null && echo "· 已取到 GitHub 上最新的备份" || echo "· 没能联网更新，用本地这份备份"
fi
if python3 -I "$T" has-old; then
  if [ "$DIR" = "$HOME/.claude-backup/repo" ]; then
    echo "· 先把这台 Mac 上最新的对话再备份一次（约 2 分钟）……"
    python3 -I "$T" sync || { echo "❌ 最后一次备份没成功，什么都没动。把这个窗口截图发给 Claude。"; bye 1; }
  fi
  echo "· 把旧账号的原始数据挪进存档文件夹（不删除，新账号看不到）……"
  python3 -I "$T" move-old || { echo "❌ 挪走旧数据失败，把这个窗口截图发给 Claude。"; bye 1; }
fi
open -a Claude
cat <<'TXT'

👉 现在请在 Claude App 里：
   1. 用【新账号】登录
   2. 在 Code 页随便新建一个对话，发一句「你好」
   3. 按 ⌘Q 退出 Claude
   做完这三步，这里会自动继续……
TXT
python3 -I "$T" wait-login || bye 1
python3 -I "$T" unpack "$DIR" || { echo "❌ 没恢复成功（新账号没被改动）。把这个窗口截图发给 Claude。"; bye 1; }
echo; echo "✅ 恢复完成，正在打开 Claude。以前的对话都在左侧列表，点进去就能接着聊。"
echo "   连接器（Google 等）需要在新账号里重新点一次授权。"
open -a Claude
bye 0
