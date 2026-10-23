/**
 * 阶段 6：刷题页组件测试。
 *
 * 对应验收标准 10（答案默认隐藏）与 docs/02 第 9.3 节的前端测试要求。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { RouterLink } from 'vue-router'
import RoundView from './RoundView.vue'
import * as client from '@/api/client'
import { ApiError } from '@/api/client'
import type { RoundDetail } from '@/api/types'

const routeParams = { id: 'round-1' }

vi.mock('vue-router', () => ({
  useRoute: () => ({ params: routeParams }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
  RouterLink: { template: '<a><slot /></a>', props: ['to'] },
}))

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

/**
 * 挂载的组件统一登记，afterEach 里全部卸载。
 *
 * 这一点很关键：RoundView 会在 window 上注册 keydown 监听。
 * 如果测试不卸载，前一个用例的组件会继续响应后续用例派发的键盘事件，
 * 造成「看起来是别人的 bug」的假失败。
 */
const mounted: { unmount: () => void }[] = []

function mountView() {
  const wrapper = mount(RoundView, {
    global: { plugins: [createPinia()] },
  })
  mounted.push(wrapper)
  return wrapper
}

function findButton(wrapper: ReturnType<typeof mountView>, label: string) {
  return wrapper.findAll('button').find((button) => button.text().includes(label))
}

describe('RoundView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  afterEach(() => {
    while (mounted.length) mounted.pop()?.unmount()
  })

  it('答案默认隐藏，只显示「查看答案」按钮', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('HashMap 的原理是什么？')
    expect(wrapper.text()).toContain('查看答案')
    // 答案正文不应出现在 DOM 中
    expect(wrapper.text()).not.toContain('数组 + 链表')
    expect(wrapper.find('.answer').exists()).toBe(false)
  })

  it('点击「查看答案」后展示答案', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-1',
      answer: '数组 + 链表 + 红黑树',
      answer_revealed: true,
    })

    const wrapper = mountView()
    await flushPromises()

    await findButton(wrapper, '查看答案')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.answer').exists()).toBe(true)
    expect(wrapper.text()).toContain('红黑树')
  })

  it('查看答案后不自动跳题', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-1',
      answer: '答案',
      answer_revealed: true,
    })
    const advanceSpy = vi.spyOn(client.api, 'advanceRound')

    const wrapper = mountView()
    await flushPromises()
    await findButton(wrapper, '查看答案')!.trigger('click')
    await flushPromises()

    expect(advanceSpy).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('第 1 / 3 题')
  })

  /**
   * 回归：答案一旦展开就再也收不回去，想遮住答案只能刷新页面。
   * 收起只是本地显示状态，服务端的「已查看」记录不能因此回退。
   */
  it('答案展开后可以收起，收起是纯显示状态', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const revealSpy = vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-1',
      answer: '数组 + 链表 + 红黑树',
      answer_revealed: true,
    })

    const wrapper = mountView()
    await flushPromises()
    await findButton(wrapper, '查看答案')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.answer').exists()).toBe(true)

    await findButton(wrapper, '收起答案')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.answer').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('红黑树')
    expect(findButton(wrapper, '查看答案')).toBeTruthy()
    // 收起不打服务端：服务端仍然认为这道题已经查看过
    expect(revealSpy).toHaveBeenCalledTimes(1)
  })

  it('收起后可以再次展开，不会重复请求服务端', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const revealSpy = vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-1',
      answer: '数组 + 链表 + 红黑树',
      answer_revealed: true,
    })

    const wrapper = mountView()
    await flushPromises()
    await findButton(wrapper, '查看答案')!.trigger('click')
    await flushPromises()
    await findButton(wrapper, '收起答案')!.trigger('click')
    await flushPromises()
    await findButton(wrapper, '查看答案')!.trigger('click')
    await flushPromises()

    expect(wrapper.find('.answer').exists()).toBe(true)
    expect(wrapper.text()).toContain('红黑树')
    expect(revealSpy).toHaveBeenCalledTimes(1)
  })

  it('答案展开后按空格可以收起', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const revealSpy = vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-1',
      answer: '答案',
      answer_revealed: true,
    })

    const wrapper = mountView()
    await flushPromises()
    await findButton(wrapper, '查看答案')!.trigger('click')
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ' }))
    await flushPromises()

    expect(wrapper.find('.answer').exists()).toBe(false)
    expect(revealSpy).toHaveBeenCalledTimes(1)
  })

  it('换到下一题后不会残留上一题的收起状态', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-1',
      answer: '答案',
      answer_revealed: true,
    })
    // 第二题在服务端已经揭过答案：换过去之后应该直接显示，而不是继承收起状态
    vi.spyOn(client.api, 'advanceRound').mockResolvedValue(
      makeRound({
        current_index: 1,
        progress_version: 2,
        current_item: {
          id: 'item-2',
          position: 1,
          question: { id: 'q2', title: 'redis通常应用在哪些场景', section_path: [] },
          answer: '缓存、分布式锁',
          answer_revealed: true,
        },
      }),
    )

    const wrapper = mountView()
    await flushPromises()
    await findButton(wrapper, '查看答案')!.trigger('click')
    await flushPromises()
    await findButton(wrapper, '收起答案')!.trigger('click')
    await flushPromises()

    await findButton(wrapper, '下一题')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('redis通常应用在哪些场景')
    expect(wrapper.find('.answer').exists()).toBe(true)
    expect(wrapper.text()).toContain('缓存、分布式锁')
  })

  it('点击「下一题」推进到下一道题', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    vi.spyOn(client.api, 'advanceRound').mockResolvedValue(
      makeRound({
        current_index: 1,
        progress_version: 2,
        current_item: {
          id: 'item-2',
          position: 1,
          question: { id: 'q2', title: 'redis通常应用在哪些场景', section_path: [] },
          answer: null,
          answer_revealed: false,
        },
      }),
    )

    const wrapper = mountView()
    await flushPromises()
    await findButton(wrapper, '下一题')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('redis通常应用在哪些场景')
    expect(wrapper.text()).toContain('第 2 / 3 题')
  })

  it('最后一题按钮显示「完成本轮」', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({
        current_index: 2,
        current_item: {
          id: 'item-3',
          position: 2,
          question: { id: 'q3', title: '最后一题是什么？', section_path: [] },
          answer: null,
          answer_revealed: false,
        },
      }),
    )
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('完成本轮')
  })

  it('第一题时「上一题」按钮存在但不可用', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const wrapper = mountView()
    await flushPromises()

    const previous = findButton(wrapper, '上一题')
    expect(previous).toBeTruthy()
    expect(previous!.attributes('disabled')).toBeDefined()
  })

  it('点击「上一题」回到上一道题', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({
        current_index: 1,
        progress_version: 2,
        current_item: {
          id: 'item-2',
          position: 1,
          question: { id: 'q2', title: 'redis通常应用在哪些场景', section_path: [] },
          answer: null,
          answer_revealed: false,
        },
      }),
    )
    const retreatSpy = vi
      .spyOn(client.api, 'advanceRound')
      .mockResolvedValue(
        makeRound({ current_index: 0, progress_version: 3 }),
      )

    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('第 2 / 3 题')

    await findButton(wrapper, '上一题')!.trigger('click')
    await flushPromises()

    expect(retreatSpy).toHaveBeenCalledTimes(1)
    // 方向必须显式传给服务端，不能由前端自行改写位置
    expect(retreatSpy.mock.calls[0][3]).toBe('previous')
    expect(wrapper.text()).toContain('HashMap 的原理是什么？')
    expect(wrapper.text()).toContain('第 1 / 3 题')
  })

  it('上一题失败时保留当前题并提示重试', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({ current_index: 1, progress_version: 2 }),
    )
    vi.spyOn(client.api, 'advanceRound').mockRejectedValue(
      new ApiError(0, 'NETWORK_ERROR', '网络连接失败，请检查网络后重试'),
    )

    const wrapper = mountView()
    await flushPromises()
    await findButton(wrapper, '上一题')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('网络')
    // 仍然停在第二题
    expect(wrapper.text()).toContain('第 2 / 3 题')
  })

  it('桌面端快捷键可以回到上一题', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({ current_index: 1, progress_version: 2 }),
    )
    const retreatSpy = vi
      .spyOn(client.api, 'advanceRound')
      .mockResolvedValue(makeRound({ current_index: 0, progress_version: 3 }))

    const wrapper = mountView()
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    await flushPromises()

    expect(retreatSpy).toHaveBeenCalledTimes(1)
    expect(retreatSpy.mock.calls[0][3]).toBe('previous')
    expect(wrapper.text()).toContain('第 1 / 3 题')
  })

  it('第一题按回退快捷键不会发请求', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const retreatSpy = vi.spyOn(client.api, 'advanceRound')

    mountView()
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k' }))
    await flushPromises()

    expect(retreatSpy).not.toHaveBeenCalled()
  })

  it('放弃确认框打开时回退快捷键不生效', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({ current_index: 1, progress_version: 2 }),
    )
    const retreatSpy = vi.spyOn(client.api, 'advanceRound')

    const wrapper = mountView()
    await flushPromises()

    await findButton(wrapper, '放弃本轮')!.trigger('click')
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    await flushPromises()

    expect(retreatSpy).not.toHaveBeenCalled()
  })

  it('完成后显示轮次完成状态', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({
        status: 'completed',
        current_index: 2,
        progress_version: 4,
        current_item: null,
        completed_at: '2026-01-01T01:00:00Z',
      }),
    )
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('开始下一轮')
  })

  /**
   * 回归：刷题途中原本没有任何回题库的入口，用户只能靠浏览器后退。
   * 进度由服务端保存，所以中途离开是安全的，入口必须常驻可见。
   * 目标必须是我的题库列表：跳到题库详情会让用户以为「返回题库」没生效。
   */
  it('刷题途中提供返回题库的入口，指向我的题库列表', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const wrapper = mountView()
    await flushPromises()

    const back = wrapper
      .findAllComponents(RouterLink)
      .find((link) => link.text().includes('返回题库'))

    expect(back).toBeTruthy()
    expect(back!.props('to')).toEqual({ name: 'banks' })
  })

  it('轮次完成后返回题库同样指向我的题库列表', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({
        status: 'completed',
        current_index: 2,
        progress_version: 4,
        current_item: null,
        completed_at: '2026-01-01T01:00:00Z',
      }),
    )
    const wrapper = mountView()
    await flushPromises()

    const back = wrapper
      .findAllComponents(RouterLink)
      .find((link) => link.text().includes('返回题库'))

    expect(back).toBeTruthy()
    expect(back!.props('to')).toEqual({ name: 'banks' })
  })

  it('揭答案前后都保留返回题库的入口', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-1',
      answer: '数组 + 链表 + 红黑树',
      answer_revealed: true,
    })

    const wrapper = mountView()
    await flushPromises()
    await findButton(wrapper, '查看答案')!.trigger('click')
    await flushPromises()

    const back = wrapper
      .findAllComponents(RouterLink)
      .find((link) => link.text().includes('返回题库'))
    expect(back).toBeTruthy()
  })

  it('网络失败时保留当前题并提示重试', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    vi.spyOn(client.api, 'advanceRound').mockRejectedValue(
      new ApiError(0, 'NETWORK_ERROR', '网络连接失败，请检查网络后重试'),
    )

    const wrapper = mountView()
    await flushPromises()
    await findButton(wrapper, '下一题')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('网络')
    // 仍然停留在第一题
    expect(wrapper.text()).toContain('HashMap 的原理是什么？')
    expect(wrapper.text()).toContain('第 1 / 3 题')
  })

  it('409 冲突时提示已同步且不静默跳题', async () => {
    vi.spyOn(client.api, 'getRound')
      .mockResolvedValueOnce(makeRound())
      .mockResolvedValueOnce(makeRound({ current_index: 1, progress_version: 2 }))
    vi.spyOn(client.api, 'advanceRound').mockRejectedValue(
      new ApiError(409, 'ROUND_PROGRESS_CONFLICT', '轮次进度已被其他设备更新'),
    )

    const wrapper = mountView()
    await flushPromises()
    await findButton(wrapper, '下一题')!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('其他设备')
  })

  it('桌面端快捷键可以查看答案', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const revealSpy = vi.spyOn(client.api, 'revealAnswer').mockResolvedValue({
      id: 'item-1',
      answer: '答案',
      answer_revealed: true,
    })

    mountView()
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ' }))
    await flushPromises()
    expect(revealSpy).toHaveBeenCalled()
  })

  it('桌面端快捷键可以推进', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const advanceSpy = vi
      .spyOn(client.api, 'advanceRound')
      .mockResolvedValue(makeRound({ current_index: 1, progress_version: 2 }))

    mountView()
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await flushPromises()

    expect(advanceSpy).toHaveBeenCalledTimes(1)
  })

  /**
   * 回归：确认框打开时「→」仍然会推进，用户在犹豫是否放弃时题就被跳过去了。
   */
  it('放弃确认框打开时快捷键不会推进', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const advanceSpy = vi.spyOn(client.api, 'advanceRound')

    const wrapper = mountView()
    await flushPromises()

    await findButton(wrapper, '放弃本轮')!.trigger('click')
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'j' }))
    await flushPromises()

    expect(advanceSpy).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('放弃后本轮不会计入完成')
  })

  it('确认框打开时快捷键不会揭答案', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(makeRound())
    const revealSpy = vi.spyOn(client.api, 'revealAnswer')

    const wrapper = mountView()
    await flushPromises()

    await findButton(wrapper, '放弃本轮')!.trigger('click')
    await flushPromises()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: ' ' }))
    await flushPromises()

    expect(revealSpy).not.toHaveBeenCalled()
  })

  it('完成后可以直接开始下一轮，不需要先回题库', async () => {
    vi.spyOn(client.api, 'getRound').mockResolvedValue(
      makeRound({
        status: 'completed',
        current_index: 2,
        progress_version: 4,
        current_item: null,
        completed_at: '2026-01-01T01:00:00Z',
      }),
    )
    const startSpy = vi
      .spyOn(client.api, 'startRound')
      .mockResolvedValue(makeRound({ id: 'round-2', round_number: 2 }))

    const wrapper = mountView()
    await flushPromises()

    await findButton(wrapper, '开始下一轮')!.trigger('click')
    await flushPromises()

    expect(startSpy).toHaveBeenCalledWith('bank-1')
  })
})
