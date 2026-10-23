<script setup lang="ts">
/** 题库列表：查看题库、继续进行中的轮次、进入详情。 */

import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api, ApiError } from '@/api/client'
import type { BankSummary } from '@/api/types'
import EmptyState from '@/components/EmptyState.vue'

const banks = ref<BankSummary[]>([])
const loading = ref(true)
const error = ref<string | null>(null)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    banks.value = await api.listBanks()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '加载题库失败'
  } finally {
    loading.value = false
  }
}

function progressPercent(bank: BankSummary): number {
  const round = bank.active_round
  if (!round || round.total_count <= 0) return 0
  return Math.round(((round.current_index + 1) / round.total_count) * 100)
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-header__title">我的题库</h1>
        <p class="page-header__subtitle">导入 Markdown 面试文档，按轮次随机且不重复地刷题</p>
      </div>
      <div class="page-header__actions">
        <RouterLink class="btn btn--primary" :to="{ name: 'bank-new' }">新建题库</RouterLink>
      </div>
    </div>

    <div v-if="error" class="alert alert--error" role="alert">
      <div class="alert__body">
        <p class="alert__title">题库加载失败</p>
        <p style="margin: 0">{{ error }}</p>
      </div>
      <div class="alert__actions">
        <button class="btn btn--sm" type="button" @click="load">重新加载</button>
      </div>
    </div>

    <!-- 加载骨架：占位高度与真实卡片一致，避免内容跳入 -->
    <div v-if="loading" class="stack">
      <div class="skeleton skeleton--card" />
      <div class="skeleton skeleton--card" />
    </div>

    <EmptyState v-else-if="banks.length === 0" title="还没有题库">
      <template #hint>创建一个题库，然后导入你的 Markdown 面试文档。</template>
      <template #actions>
        <RouterLink class="btn btn--primary" :to="{ name: 'bank-new' }">新建题库</RouterLink>
      </template>
    </EmptyState>

    <ul v-else class="list">
      <li v-for="bank in banks" :key="bank.id" class="list__item list__item--interactive">
        <div class="row row--between row--top">
          <div style="min-width: 0">
            <RouterLink class="list__title" :to="{ name: 'bank-detail', params: { id: bank.id } }">
              {{ bank.name }}
            </RouterLink>
            <p v-if="bank.description" class="muted small" style="margin: 4px 0 0">
              {{ bank.description }}
            </p>
          </div>
          <RouterLink
            class="btn"
            :class="bank.active_round ? 'btn--primary' : ''"
            :to="{ name: 'bank-detail', params: { id: bank.id } }"
          >
            {{ bank.active_round ? '继续刷题' : '进入题库' }}
          </RouterLink>
        </div>

        <div class="list__meta">
          <span><span class="num">{{ bank.question_count }}</span> 道题</span>
          <span>
            当前版本
            <span class="num">{{ bank.current_version ?? '—' }}</span>
          </span>
          <span>
            已完成
            <span class="num">{{ bank.completed_round_count }}</span> 轮
          </span>
          <span v-if="bank.active_round">
            第 <span class="num">{{ bank.active_round.round_number }}</span> 轮进行中 ·
            <span class="num">
              {{ bank.active_round.current_index + 1 }}/{{ bank.active_round.total_count }}
            </span>
          </span>
          <span v-else>暂无进行中的轮次</span>
        </div>

        <div v-if="bank.active_round" class="progress" style="margin-top: 12px">
          <div class="progress__bar" :style="{ width: `${progressPercent(bank)}%` }" />
        </div>
      </li>
    </ul>
  </div>
</template>
