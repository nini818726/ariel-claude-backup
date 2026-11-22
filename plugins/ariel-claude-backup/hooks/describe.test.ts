import { expect, test } from 'claude-code/testing'
import { describe } from './register'

const now = Date.parse('2026-11-15T18:10:00')
test('normal, failed, stale, folder moved, none', async () => {
  expect(describe({ ok: true, last_success: '2026-11-15 18:04:12', conversations_local: 277 }, now)).toBe('☁️ 备份正常 · 18:04 同步过 · 277 个对话')
  expect(describe({ ok: false, last_success: '2026-11-15 17:44:00' }, now)).toBe('⚠️ 上传失败，10 分钟后自动重试 · 上次成功 17:44')
  expect(describe({ ok: true, last_success: '2026-11-15 15:00:00' }, now)).toBe('⚠️ 已经很久没备份了 · 上次成功 15:00')
  expect(describe({ ok: true, last_success: '2026-11-15 18:04:12', note: 'folder moved: a → b' }, now)).toBe('📁 文件夹已对上新位置，退出 Claude 再打开就好')
  expect(describe(undefined, now)).toBe('☁️ 备份还没开始')
  expect(describe({ ok: true, last_success: '2026-11-15 18:04:12', conversations_local: 277, too_big: [{ name: 'a.jsonl', mb: 118 }, { name: 'b.jsonl', mb: 111 }, { name: 'c.jsonl', mb: 136 }] }, now)).toBe('⚠️ 3 个未备份（太大，等你决定）· 18:04 同步过 · 277 个对话')
})
