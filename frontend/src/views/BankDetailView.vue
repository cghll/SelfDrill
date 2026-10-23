<script setup lang="ts">
/**
 * 题库详情：统计、版本历史、更新导入、继续刷题、删除题库。
 *
 * 布局：宽屏用「主内容 + 侧栏」。题目列表是主要阅读对象，占主列；
 * 统计、导入历史、轮次历史和危险操作收进侧栏，避免长页面里主次不分。
 */

import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'
import type { BankSummary, BankVersion, QuestionListPage, RoundSummary } from '@/api/types'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import EmptyState from '@/components/EmptyState.vue'

const route = useRoute()
const router = useRouter()
const bankId = computed(() => String(route.params.id))

const bank = ref<BankSummary | null>(null)
const versions = ref<BankVersion[]>([])
const rounds = ref<RoundSummary[]>([])
const questions = ref<QuestionListPage | null>(null)
const keyword = ref('')

const loading = ref(true)
const error = ref<string | null>(null)
const busy = ref(false)
const showDelete = ref(false)
const showRestart = ref(false)

/** 导入成功后从预览页带过来的版本号，用于给一次明确的成功反馈 */
const importedVersion = computed(() => {
  const value = route.query.imported
  return typeof value === 'string' && value ? value : null
})

const activeRoundPercent = computed(() => {
  const round = bank.value?.active_round
  if (!round || round.total_count <= 0) return 0
  return Math.round(((round.current_index + 1) / round.total_count) * 100)
})

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [bankData, versionData, roundData] = await Promise.all([
      api.getBank(bankId.value),
      api.listVersions(bankId.value),
      api.listRounds(bankId.value),
    ])
    bank.value = bankData
    versions.value = versionData
    rounds.value = roundData
    await loadQuestions()
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '加载题库失败'
  } finally {
    loading.value = false
  }
}

async function loadQuestions(): Promise<void> {
  try {
    questions.value = await api.listQuestions(bankId.value, {
      page_size: 20,
      keyword: keyword.value.trim() || undefined,
    })
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '加载题目失败'
  }
}

async function startRound(restart = false): Promise<void> {
  busy.value = true
  error.value = null
  try {
    const round = await api.startRound(bankId.value, restart)
    await router.push({ name: 'round', params: { id: round.id } })
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '开始轮次失败'
  } finally {
    busy.value = false
    showRestart.value = false
  }
}

async function confirmDelete(): Promise<void> {
  busy.value = true
  try {
    await api.deleteBank(bankId.value)
    await router.replace({ name: 'banks' })
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '删除题库失败'
  } finally {
    busy.value = false
    showDelete.value = false
  }
}

function roundStatusLabel(status: RoundSummary['status']): string {
  return { in_progress: '进行中', completed: '已完成', abandoned: '已放弃' }[status]
}

function roundStatusClass(status: RoundSummary['status']): string {
  return {
    in_progress: 'tag--modified',
    completed: 'tag--added',
    abandoned: 'tag--unchanged',
  }[status]
}

onMounted(load)
</script>

<template>
  <div>
    <div v-if="loading" class="card">
      <div class="skeleton skeleton--title" />
      <div class="skeleton skeleton--line" style="width: 70%" />
      <div class="skeleton skeleton--line" style="width: 45%; margin-bottom: 0" />
    </div>

    <template v-else-if="bank">
      <div class="page-header">
        <div style="min-width: 0">
          <h1 class="page-header__title">{{ bank.name }}</h1>
          <p v-if="bank.description" class="page-header__subtitle">{{ bank.description }}</p>
        </div>
        <div class="page-header__actions">
          <RouterLink class="btn" :to="{ name: 'bank-import', params: { id: bank.id } }">
            更新导入
          </RouterLink>
          <button
            v-if="bank.question_count > 0"
            class="btn btn--primary"
            type="button"
            :disabled="busy"
            @click="startRound(false)"
          >
            {{ bank.active_round ? '继续刷题' : '开始刷题' }}
          </button>
        </div>
      </div>

      <div v-if="importedVersion" class="alert alert--success" role="status">
        <div class="alert__body">
          导入完成，已生成版本 <span class="num">{{ importedVersion }}</span
          >。进行中的轮次仍使用它创建时的版本，新版本从下一轮开始生效。
        </div>
      </div>

      <div v-if="error" class="alert alert--error" role="alert">
        <div class="alert__body">
          <p class="alert__title">操作没有完成</p>
          <p style="margin: 0">{{ error }}</p>
        </div>
        <div class="alert__actions">
          <button class="btn btn--sm" type="button" @click="load">重新加载</button>
        </div>
      </div>

      <div class="grid-stats" style="margin-bottom: 20px">
        <div class="stat">
          <div class="stat__value">{{ bank.question_count }}</div>
          <div class="stat__label">当前题目数</div>
        </div>
        <div class="stat">
          <div class="stat__value">{{ bank.current_version ?? '—' }}</div>
          <div class="stat__label">当前版本</div>
        </div>
        <div class="stat">
          <div class="stat__value">{{ versions.length }}</div>
          <div class="stat__label">历史导入</div>
        </div>
        <div class="stat">
          <div class="stat__value">{{ rounds.length }}</div>
          <div class="stat__label">轮次总数</div>
        </div>
      </div>

      <!-- 进行中的轮次：最该被看见的一件事 -->
      <div v-if="bank.active_round" class="card">
        <div class="card__header">
          <h2 class="card__title">第 {{ bank.active_round.round_number }} 轮进行中</h2>
          <span class="card__header-meta">
            固定使用版本 {{ bank.current_version }}
          </span>
        </div>

        <div class="row row--between small" style="margin-bottom: 8px">
          <span>
            已完成
            <span class="num">
              {{ bank.active_round.current_index + 1 }}/{{ bank.active_round.total_count }}
            </span>
          </span>
          <span class="muted num">{{ activeRoundPercent }}%</span>
        </div>
        <div class="progress">
          <div class="progress__bar" :style="{ width: `${activeRoundPercent}%` }" />
        </div>

        <div class="row" style="margin-top: 16px">
          <RouterLink
            class="btn btn--primary"
            :to="{ name: 'round', params: { id: bank.active_round.id } }"
          >
            继续当前轮次
          </RouterLink>
          <button class="btn" type="button" :disabled="busy" @click="showRestart = true">
            放弃并重新开始
          </button>
        </div>
      </div>

      <div v-if="bank.question_count === 0" class="card" style="margin-top: 16px">
        <EmptyState
          title="这个题库还没有题目"
          hint="上传 Markdown 文档，系统会识别标题层级里的题目与答案。"
        >
          <template #actions>
            <RouterLink
              class="btn btn--primary"
              :to="{ name: 'bank-import', params: { id: bank.id } }"
            >
              导入 Markdown
            </RouterLink>
          </template>
        </EmptyState>
      </div>

      <div v-else class="split split--aside" style="margin-top: 16px">
        <!-- 主列：题目列表 -->
        <div class="card">
          <div class="card__header">
            <h2 class="card__title">题目列表</h2>
            <span v-if="questions" class="card__header-meta num">
              共 {{ questions.total }} 道
            </span>
          </div>

          <form class="row" style="margin-bottom: 16px" @submit.prevent="loadQuestions">
            <input
              v-model="keyword"
              class="input"
              type="search"
              placeholder="搜索题目标题或答案"
              aria-label="搜索题目"
              style="flex: 1; min-width: 180px"
            />
            <button class="btn" type="submit">搜索</button>
          </form>

          <p v-if="questions && questions.total === 0" class="muted small" style="margin: 0">
            没有匹配的题目。换个关键词试试。
          </p>

          <ul v-else-if="questions" class="list">
            <li v-for="item in questions.items" :key="item.id" class="list__item">
              <div class="row" style="gap: 8px">
                <strong style="font-size: 15.5px">{{ item.title }}</strong>
              </div>
              <p v-if="item.section_path.length" class="muted small" style="margin: 4px 0 0">
                {{ item.section_path.join(' / ') }}
              </p>
              <p v-if="item.answer_summary" class="muted small" style="margin: 6px 0 0">
                {{ item.answer_summary }}
              </p>
            </li>
          </ul>

          <p v-if="questions && questions.total_pages > 1" class="muted small" style="margin: 12px 0 0">
            共 {{ questions.total }} 道题，当前显示前 {{ questions.items.length }} 道。
          </p>
        </div>

        <!-- 侧栏 -->
        <div class="split__aside">
          <div class="card">
            <h2 class="card__title">导入历史</h2>
            <p v-if="versions.length === 0" class="muted small" style="margin: 0">
              还没有导入记录。
            </p>
            <ul v-else class="list list--rows" style="margin-top: 12px">
              <li v-for="version in versions" :key="version.id" class="list__item">
                <div class="row row--between">
                  <span class="row" style="gap: 8px">
                    <strong class="num">v{{ version.version_number }}</strong>
                    <span
                      class="tag"
                      :class="version.status === 'active' ? 'tag--added' : 'tag--unchanged'"
                    >
                      {{ version.status === 'active' ? '生效中' : '已被替换' }}
                    </span>
                  </span>
                  <span class="muted small num">{{ version.question_count }} 道</span>
                </div>
                <p class="muted small mono" style="margin: 6px 0 0; overflow-wrap: anywhere">
                  {{ version.source_filename }} · {{ version.source_hash.slice(0, 10) }}…
                </p>
              </li>
            </ul>
          </div>

          <div class="card">
            <h2 class="card__title">轮次历史</h2>
            <p v-if="rounds.length === 0" class="muted small" style="margin: 0">
              还没有刷题记录。
            </p>
            <ul v-else class="list list--rows" style="margin-top: 12px">
              <li v-for="round in rounds" :key="round.id" class="list__item">
                <div class="row row--between">
                  <span class="row" style="gap: 8px">
                    <strong class="num">第 {{ round.round_number }} 轮</strong>
                    <span class="tag" :class="roundStatusClass(round.status)">
                      {{ roundStatusLabel(round.status) }}
                    </span>
                  </span>
                  <RouterLink class="small" :to="{ name: 'round', params: { id: round.id } }">
                    查看
                  </RouterLink>
                </div>
                <p class="muted small num" style="margin: 6px 0 0">
                  {{ round.current_index + 1 }}/{{ round.total_count }} 道
                </p>
              </li>
            </ul>
          </div>

          <div class="card">
            <h2 class="card__title">删除题库</h2>
            <p class="muted small">
              会同时移除它的全部版本、题目和刷题记录，且无法恢复。
            </p>
            <button class="btn btn--danger" type="button" :disabled="busy" @click="showDelete = true">
              删除题库
            </button>
          </div>
        </div>
      </div>

      <ConfirmDialog
        :open="showDelete"
        title="删除题库"
        :message="`确定要删除「${bank.name}」吗？该操作不可恢复。`"
        confirm-label="确认删除"
        danger
        :busy="busy"
        @confirm="confirmDelete"
        @cancel="showDelete = false"
      />

      <ConfirmDialog
        :open="showRestart"
        title="重新开始轮次"
        message="当前进行中的轮次会被标记为已放弃，并生成一个全新的随机顺序。"
        confirm-label="放弃并重开"
        :busy="busy"
        @confirm="startRound(true)"
        @cancel="showRestart = false"
      />
    </template>

    <div v-else class="card">
      <EmptyState title="题库不存在" :hint="error ?? '它可能已经被删除。'">
        <template #actions>
          <RouterLink class="btn btn--primary" :to="{ name: 'banks' }">返回题库列表</RouterLink>
        </template>
      </EmptyState>
    </div>
  </div>
</template>
