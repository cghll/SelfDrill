/**
 * 题库列表页测试。
 *
 * 重点：列表页要能回答「这个题库刷完过几轮」，并且不把放弃的轮次算成完成。
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BankListView from './BankListView.vue'
import * as client from '@/api/client'
import type { BankSummary } from '@/api/types'

vi.mock('vue-router', () => ({
  RouterLink: { template: '<a><slot /></a>', props: ['to'] },
}))

function makeBank(overrides: Partial<BankSummary> = {}): BankSummary {
  return {
    id: 'bank-1',
    name: 'Java 热门面试',
    description: null,
    question_count: 74,
    current_version: 1,
    current_version_id: 'version-1',
    active_round: null,
    completed_round_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  }
}

const mounted: { unmount: () => void }[] = []

function mountView() {
  const wrapper = mount(BankListView, { global: { plugins: [createPinia()] } })
  mounted.push(wrapper)
  return wrapper
}

describe('BankListView', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  afterEach(() => {
    while (mounted.length) mounted.pop()?.unmount()
  })

  it('显示每个题库的已完成轮数', async () => {
    vi.spyOn(client.api, 'listBanks').mockResolvedValue([
      makeBank({ id: 'bank-1', name: 'Java 热门面试', completed_round_count: 3 }),
      makeBank({ id: 'bank-2', name: '食光', completed_round_count: 0 }),
    ])

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('已完成')
    const items = wrapper.findAll('.list__item')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toContain('3 轮')
    expect(items[1].text()).toContain('0 轮')
  })

  it('有进行中轮次时同时显示轮数与进度', async () => {
    vi.spyOn(client.api, 'listBanks').mockResolvedValue([
      makeBank({
        completed_round_count: 2,
        active_round: {
          id: 'round-3',
          round_number: 3,
          current_index: 1,
          total_count: 74,
          status: 'in_progress',
          progress_version: 2,
          bank_version_id: 'version-1',
        },
      }),
    ])

    const wrapper = mountView()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('已完成')
    expect(text).toContain('2 轮')
    expect(text).toContain('第 3 轮进行中')
    expect(text).toContain('继续刷题')
  })
})
