/**
 * 刷题状态。
 *
 * 铁律（docs/02 第 5 节）：前端状态只是服务端状态的缓存。
 * 这里不生成题目顺序、不修改 current_index——所有变更都必须先得到服务端响应。
 *
 * 409 冲突的处理方式：重新拉取轮次，不自动覆盖其他设备的操作。
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, ApiError, createIdempotencyKey } from '@/api/client'
import type { RoundDetail, RoundDirection } from '@/api/types'

export const useRoundStore = defineStore('round', () => {
  const round = ref<RoundDetail | null>(null)
  const answer = ref<string | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  const conflictNotice = ref<string | null>(null)

  const isCompleted = computed(() => round.value?.status === 'completed')
  const total = computed(() => round.value?.total_count ?? 0)
  const position = computed(() => (round.value ? round.value.current_index + 1 : 0))
  const progressPercent = computed(() =>
    total.value === 0 ? 0 : Math.round((position.value / total.value) * 100),
  )

  function applyDetail(detail: RoundDetail): void {
    round.value = detail
    // 服务端在未 reveal 时返回 answer=null，前端不能自行保留旧答案
    answer.value = detail.current_item?.answer ?? null
  }

  async function load(roundId: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      applyDetail(await api.getRound(roundId))
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '加载轮次失败'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function reveal(roundId: string): Promise<void> {
    error.value = null
    const requestedItemId = round.value?.current_item?.id ?? null
    try {
      const result = await api.revealAnswer(roundId)
      // 服务端可能因为其他设备推进而返回了另一道题的答案。
      // 直接贴到当前题上会把 A 题的答案显示在 B 题下面，必须丢弃并重新同步。
      if (requestedItemId !== null && result.id !== requestedItemId) {
        applyDetail(await api.getRound(roundId))
        conflictNotice.value = '进度已被其他设备更新，已为你同步到最新位置'
        return
      }
      answer.value = result.answer
      if (round.value?.current_item) {
        round.value.current_item.answer_revealed = result.answer_revealed
        round.value.current_item.answer = result.answer
      }
    } catch (err) {
      error.value = err instanceof ApiError ? err.message : '查看答案失败'
      throw err
    }
  }

  /**
   * 移动当前位置。`next` 与 `previous` 走同一个接口，因此并发与幂等语义完全一致：
   * 409 冲突时一律重新拉取服务端状态，绝不静默改写本地位置。
   */
  async function move(roundId: string, direction: RoundDirection): Promise<void> {
    if (!round.value) return
    error.value = null
    conflictNotice.value = null
    try {
      // 幂等键必须在 try 内部生成：生成过程本身也可能抛错（例如非安全上下文
      // 没有 crypto.randomUUID），那样错误会绕过下面的提示逻辑。
      const idempotencyKey = createIdempotencyKey()
      applyDetail(
        await api.advanceRound(
          roundId,
          round.value.progress_version,
          idempotencyKey,
          direction,
        ),
      )
    } catch (err) {
      if (err instanceof ApiError && err.isProgressConflict) {
        // 其他设备已经移动：拉取最新状态并明确告知用户，绝不静默跳题
        conflictNotice.value = '进度已被其他设备更新，已为你同步到最新位置'
        applyDetail(await api.getRound(roundId))
        return
      }
      error.value =
        err instanceof ApiError
          ? err.message
          : direction === 'previous'
            ? '返回上一题失败，请重试'
            : '推进失败，请重试'
      throw err
    }
  }

  function advance(roundId: string): Promise<void> {
    return move(roundId, 'next')
  }

  function retreat(roundId: string): Promise<void> {
    return move(roundId, 'previous')
  }

  function reset(): void {
    round.value = null
    answer.value = null
    error.value = null
    conflictNotice.value = null
  }

  return {
    round,
    answer,
    loading,
    error,
    conflictNotice,
    isCompleted,
    total,
    position,
    progressPercent,
    load,
    reveal,
    advance,
    retreat,
    reset,
  }
})
