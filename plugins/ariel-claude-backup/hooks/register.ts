import type { Register } from 'claude-code'

type Status = {
  ok?: boolean
  note?: string
  last_run?: string
  last_success?: string
  conversations_local?: number
  every_minutes?: number
}

const hhmm = (t?: string) => (t ? t.slice(11, 16) : '?')

export function describe(s: Status | undefined, now: number): string {
  if (!s) return '☁️ 备份还没开始'
  const every = s.every_minutes ?? 10
  const last = s.last_success ? Date.parse(s.last_success.replace(' ', 'T')) : NaN
  const stale = !Number.isNaN(last) && now - last > every * 60_000 * 4
  if (s.note && s.ok && /folder moved/.test(s.note)) return '📁 文件夹已对上新位置，退出 Claude 再打开就好'
  if (!s.ok) return `⚠️ 上传失败，${every} 分钟后自动重试 · 上次成功 ${hhmm(s.last_success)}`
  if (stale) return `⚠️ 已经很久没备份了 · 上次成功 ${hhmm(s.last_success)}`
  return `☁️ 备份正常 · ${hhmm(s.last_success)} 同步过 · ${s.conversations_local ?? 0} 个对话`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    const home = await $.env.get('HOME')
    const refresh = async () => {
      let s: Status | undefined
      try {
        s = JSON.parse(await $.fs.read(`${home}/.claude-backup/status.json`)) as Status
      } catch {
        s = undefined
      }
      $.ui.status(describe(s, Date.now()))
    }
    await refresh()
    $.clock.every(30_000, refresh)
    return result
  })
}
