/**
 * 阶段 6：刷题状态测试。
 *
 * 重点验证前端不会自行推进、409 冲突会被显式暴露、答案默认隐藏。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useRoundStore } from './round'
import { ApiError } from '@/api/client'
import * as client from '@/api/client'
import type { RoundDetail } from '@/api/types'

function makeRound(overrides: Partial<RoundDetail> = {}): RoundDetail {
  return {
    id: 'round-1',
    bank_id: 'bank-1',
    bank_version_id: 'version-1',
    round_number: 1,
    status: 'in_progress',
    current_index: 0,
    total_count: 3,
    progress_version: 1,
    started_at: '2026-01-01T00:00:00Z',
    completed_at: null,
    current_item: {
      id: 'item-1',
      position: 0,
      question: { id: 'q1', title: 'HashMap 的原理是什么？', section_path: ['Java 基础'] },
      answer: null,
      answer_revealed: false,
    },
    ...overrides,
  }
}

describe('round store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('加载后答案默认隐藏', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const store = useRoundStore()

    await store.load('round-1')

    expect(store.answer).toBeNull()
    expect(store.round?.current_item?.answer_revealed).toBe(false)
    expect(store.position).toBe(1)
    expect(store.total).toBe(3)
  })

  it('查看答案后展示内容但不跳题', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-1',
      answer: '数组 + 链表',
      answer_revealed: true,
    })
    const store = useRoundStore()
    await store.load('round-1')

    await store.reveal('round-1')

    expect(store.answer).toBe('数组 + 链表')
    expect(store.round?.current_index).toBe(0)
    expect(store.round?.current_item?.answer_revealed).toBe(true)
  })

  it('刷新页面后恢复到服务端位置', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({ current_index: 2, progress_version: 3 }),
    )
    const store = useRoundStore()

    await store.load('round-1')

    expect(store.position).toBe(3)
    expect(store.round?.progress_version).toBe(3)
  })

  it('推进时携带服务端进度版本号与幂等键', async () => {
    const spy = vi
      .spyOn(client.api, 'advanceRound')
      .mockResolvedValue(makeRound({ current_index: 1, progress_version: 2 }))
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const store = useRoundStore()
    await store.load('round-1')

    await store.advance('round-1')

    expect(spy).toHaveBeenCalledTimes(1)
    const [roundId, version, key] = spy.mock.calls[0]
    expect(roundId).toBe('round-1')
    expect(version).toBe(1)
    expect(typeof key).toBe('string')
    expect(key.length).toBeGreaterThan(0)
    expect(store.round?.current_index).toBe(1)
  })

  it('409 冲突时同步服务端状态并给出提示', async () => {
    vi.spyOn(client.api, 'getRound')
      .mockResolvedValueOnce(makeRound())
      .mockResolvedValueOnce(makeRound({ current_index: 2, progress_version: 3 }))
    vi.spyOn(client.api, 'advanceRound').mockRejectedValue(
      new ApiError(409, 'ROUND_PROGRESS_CONFLICT', '轮次进度已被其他设备更新'),
    )

    const store = useRoundStore()
    await store.load('round-1')

    await store.advance('round-1')

    expect(store.conflictNotice).toContain('其他设备')
    expect(store.round?.current_index).toBe(2)
    expect(store.error).toBeNull()
  })

  it('网络失败时不改变当前位置并暴露错误', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    vi.spyOn(client.api, 'advanceRound').mockRejectedValue(
      new ApiError(0, 'NETWORK_ERROR', '网络连接失败，请检查网络后重试'),
    )
    const store = useRoundStore()
    await store.load('round-1')

    await expect(store.advance('round-1')).rejects.toThrow()

    expect(store.round?.current_index).toBe(0)
    expect(store.error).toContain('网络')
  })

  it('轮次完成后不再显示当前题', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({
        status: 'completed',
        current_index: 2,
        progress_version: 4,
        current_item: null,
        completed_at: '2026-01-01T01:00:00Z',
      }),
    )
    const store = useRoundStore()

    await store.load('round-1')

    expect(store.isCompleted).toBe(true)
    expect(store.round?.current_item).toBeNull()
    expect(store.answer).toBeNull()
  })

  it('进度百分比按服务端位置计算', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({ current_index: 1, total_count: 4 }),
    )
    const store = useRoundStore()
    await store.load('round-1')
    expect(store.progressPercent).toBe(50)
  })

  it('回退上一题时携带 direction=previous 与当前版本号', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({ current_index: 2, progress_version: 3 }),
    )
    const spy = vi
      .spyOn(client.api, 'advanceRound')
      .mockResolvedValue(makeRound({ current_index: 1, progress_version: 4 }))
    const store = useRoundStore()
    await store.load('round-1')

    await store.retreat('round-1')

    expect(spy).toHaveBeenCalledTimes(1)
    const [roundId, version, key, direction] = spy.mock.calls[0]
    expect(roundId).toBe('round-1')
    expect(version).toBe(3)
    expect(typeof key).toBe('string')
    expect(direction).toBe('previous')
    expect(store.round?.current_index).toBe(1)
  })

  it('下一题显式携带 direction=next', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const spy = vi
      .spyOn(client.api, 'advanceRound')
      .mockResolvedValue(makeRound({ current_index: 1, progress_version: 2 }))
    const store = useRoundStore()
    await store.load('round-1')

    await store.advance('round-1')

    expect(spy.mock.calls[0][3]).toBe('next')
  })

  it('回退遇到 409 时同步服务端状态并给出提示', async () => {
    vi.spyOn(client.api, 'getRound')
      .mockResolvedValueOnce(makeRound({ current_index: 2, progress_version: 3 }))
      .mockResolvedValueOnce(makeRound({ current_index: 1, progress_version: 4 }))
    vi.spyOn(client.api, 'advanceRound').mockRejectedValue(
      new ApiError(409, 'ROUND_PROGRESS_CONFLICT', '轮次进度已被其他设备更新'),
    )

    const store = useRoundStore()
    await store.load('round-1')
    await store.retreat('round-1')

    expect(store.conflictNotice).toContain('其他设备')
    expect(store.round?.current_index).toBe(1)
    expect(store.error).toBeNull()
  })

  it('回退网络失败时不改变当前位置并暴露错误', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({ current_index: 2, progress_version: 3 }),
    )
    vi.spyOn(client.api, 'advanceRound').mockRejectedValue(
      new ApiError(0, 'NETWORK_ERROR', '网络连接失败，请检查网络后重试'),
    )
    const store = useRoundStore()
    await store.load('round-1')

    await expect(store.retreat('round-1')).rejects.toThrow()

    expect(store.round?.current_index).toBe(2)
    expect(store.error).toContain('网络')
  })
})

/**
 * 回归：用户报告的「刷题过程中推进失败」。
 *
 * `crypto.randomUUID` 只在安全上下文（HTTPS / localhost）存在，
 * 而项目默认用 Caddy 的 :80 通过局域网 http://<ip> 访问。
 * 原实现在发起请求前就调用它，抛出的 TypeError 让「下一题」永远失败。
 */
describe('round store 推进健壮性', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('非安全上下文（没有 crypto.randomUUID）时仍然能推进', async () => {
    vi.stubGlobal('crypto', {})
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const advanceSpy = vi
      .spyOn(client.api, 'advanceRound')
      .mockResolvedValue(makeRound({ current_index: 1, progress_version: 2 }))

    const store = useRoundStore()
    await store.load('round-1')

    await expect(store.advance('round-1')).resolves.toBeUndefined()
    expect(advanceSpy).toHaveBeenCalledTimes(1)
    expect(store.round?.current_index).toBe(1)
    expect(store.error).toBeNull()
  })

  it('完全没有 Web Crypto 时也能推进', async () => {
    vi.stubGlobal('crypto', undefined)
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const advanceSpy = vi
      .spyOn(client.api, 'advanceRound')
      .mockResolvedValue(makeRound({ current_index: 1, progress_version: 2 }))

    const store = useRoundStore()
    await store.load('round-1')
    await store.advance('round-1')

    const [, , key] = advanceSpy.mock.calls[0]
    expect(typeof key).toBe('string')
    expect(key.length).toBeGreaterThan(0)
  })

  it('reveal 返回的题目与当前题不一致时，不把答案贴到当前题上', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-other',
      answer: '别的题的答案',
      answer_revealed: true,
    })

    const store = useRoundStore()
    await store.load('round-1')
    await store.reveal('round-1')

    expect(store.round?.current_item?.answer).toBeNull()
    expect(store.answer).toBeNull()
    expect(store.conflictNotice).toContain('其他设备')
  })

  it('reveal 返回当前题时正常展示答案', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-1',
      answer: '数组 + 链表',
      answer_revealed: true,
    })

    const store = useRoundStore()
    await store.load('round-1')
    await store.reveal('round-1')

    expect(store.answer).toBe('数组 + 链表')
    expect(store.round?.current_item?.answer_revealed).toBe(true)
  })
})
