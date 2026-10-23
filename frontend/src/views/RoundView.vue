<script setup lang="ts">
/**
 * 刷题页。
 *
 * 关键交互（FR-007 / FR-008 / FR-009 / NFR-003）：
 * - 答案默认隐藏，点击后展示，查看答案不自动跳题。
 * - 答案展开后可以再收起：收起只是本地显示状态，服务端的「已查看」不回退，
 *   所以刷新或换设备回来仍然直接看到答案，不会丢失查看记录。
 * - 桌面端支持键盘：空格/回车看答案，答案展开时空格收起，→ 或 J 下一题，← 或 K 上一题。
 * - 上一题同样由服务端改写位置（advance 的 direction=previous），
 *   前端不自行修改 current_index，回退也受乐观锁与幂等保护。
 * - 网络失败时保留当前页面状态并提示重试，不推进到下一题。
 * - 409 冲突时提示并同步到服务端最新位置，不静默跳题。
 *
 * 布局意图：这是整个产品的主界面，一屏只做一件事——读题、看答案、下一题。
 * 进度条常驻顶部回答「我在哪」，并在同一行给出「返回题库」的退出口，回到我的题库列表
 * （进度已落库，中途离开不丢进度，回题库可以继续）；操作按钮在手机上吸底，
 * 避免长答案滚到底还要回卷。
 */

import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'
import { useRoundStore } from '@/stores/round'
import AnswerPanel from '@/components/AnswerPanel.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'

const route = useRoute()
const router = useRouter()
const store = useRoundStore()
const roundId = computed(() => String(route.params.id))

const actionError = ref<string | null>(null)
const busy = ref(false)
const showAbandon = ref(false)
const startingNext = ref(false)

/** 本地收起答案：只改显示，不改服务端的已查看状态 */
const answerCollapsed = ref(false)

const revealed = computed(() => store.round?.current_item?.answer_revealed ?? false)
/** 答案此刻是否显示在页面上：服务端已揭答案 + 本地没有收起 */
const answerVisible = computed(() => revealed.value && !answerCollapsed.value)
const isCompleted = computed(() => store.round?.status === 'completed')
const isLast = computed(() => store.position === store.total && store.total > 0)
/** 第一题没有上一题。按钮保持可见但禁用，位置稳定比忽隐忽现更好找。 */
const hasPrevious = computed(() => store.position > 1)

// 换题（下一题、冲突后重新同步、重新加载）后答案回到默认隐藏，收起状态不跨题残留
watch(
  () => store.round?.current_item?.id ?? null,
  () => {
    answerCollapsed.value = false
  },
)

async function load(): Promise<void> {
  actionError.value = null
  try {
    await store.load(roundId.value)
  } catch {
    actionError.value = store.error
  }
}

async function reveal(): Promise<void> {
  if (answerVisible.value || busy.value) return
  // 服务端已经揭过答案，只是被本地收起了：直接展开，不必再请求一次
  if (revealed.value) {
    answerCollapsed.value = false
    return
  }
  busy.value = true
  actionError.value = null
  try {
    await store.reveal(roundId.value)
    answerCollapsed.value = false
  } catch {
    actionError.value = store.error ?? '查看答案失败，请重试'
  } finally {
    busy.value = false
  }
}

/** 收起答案：纯显示状态，服务端的已查看记录保持不变，随时可以再展开 */
function collapseAnswer(): void {
  answerCollapsed.value = true
}

async function next(): Promise<void> {
  if (busy.value) return
  busy.value = true
  actionError.value = null
  try {
    await store.advance(roundId.value)
  } catch {
    // 失败时不清空当前题，用户可以重试（NFR-003）
    actionError.value = store.error ?? '推进失败，请重试'
  } finally {
    busy.value = false
  }
}

/** 回退到上一题。位置同样由服务端改写，前端只负责发起请求。 */
async function previous(): Promise<void> {
  if (busy.value || !hasPrevious.value) return
  busy.value = true
  actionError.value = null
  try {
    await store.retreat(roundId.value)
  } catch {
    actionError.value = store.error ?? '返回上一题失败，请重试'
  } finally {
    busy.value = false
  }
}

/** 本轮结束后直接开下一轮，而不是把用户丢回题库再点一次 */
async function startNextRound(): Promise<void> {
  const bankId = store.round?.bank_id
  if (!bankId || startingNext.value) return
  startingNext.value = true
  actionError.value = null
  try {
    const round = await api.startRound(bankId)
    await router.push({ name: 'round', params: { id: round.id } })
  } catch (err) {
    actionError.value = err instanceof ApiError ? err.message : '开始下一轮失败'
  } finally {
    startingNext.value = false
  }
}

async function abandon(): Promise<void> {
  busy.value = true
  try {
    await api.abandonRound(roundId.value)
    showAbandon.value = false
    await load()
  } catch (err) {
    actionError.value = err instanceof ApiError ? err.message : '放弃轮次失败'
  } finally {
    busy.value = false
  }
}

function onKeydown(event: KeyboardEvent): void {
  const target = event.target as HTMLElement | null
  if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return
  // 确认框打开时键盘只归确认框：否则「→」会在用户还在犹豫时把题跳过去
  if (showAbandon.value) return
  if (busy.value || isCompleted.value) return

  if (event.key === ' ' || event.key === 'Enter') {
    if (!answerVisible.value) {
      event.preventDefault()
      void reveal()
      return
    }
    // 答案已展开：空格再按一次收起，形成可逆的开关。
    // 回车不接管，留给当前聚焦的按钮（例如「下一题」）保持原生激活行为。
    if (event.key === ' ') {
      event.preventDefault()
      collapseAnswer()
    }
    return
  }

  if (event.key === 'ArrowRight' || event.key.toLowerCase() === 'j') {
    event.preventDefault()
    void next()
    return
  }

  // 回退键与前进键成对：← / K。没有上一题时直接忽略，不做无意义的请求。
  if (event.key === 'ArrowLeft' || event.key.toLowerCase() === 'k') {
    event.preventDefault()
    void previous()
  }
}

onMounted(() => {
  void load()
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  store.reset()
})
</script>

<template>
  <div>
    <!-- 加载中：骨架屏保持布局稳定，不闪一个孤零零的「加载中…」 -->
    <template v-if="store.loading && !store.round">
      <div class="card">
        <div class="skeleton skeleton--title" />
        <div class="skeleton skeleton--line" style="width: 82%" />
        <div class="skeleton skeleton--line" style="width: 64%" />
        <div class="skeleton skeleton--line" style="width: 71%; margin-bottom: 0" />
      </div>
    </template>

    <template v-else-if="store.round">
      <!-- 进度轨：常驻可见 -->
      <div v-if="!isCompleted" class="drill-rail">
        <div class="drill-rail__inner">
          <div class="drill-rail__top">
            <!-- 退出口常驻在进度轨里：不需要先答完题、也不需要先放弃本轮才能回题库 -->
            <RouterLink
              class="drill-rail__back"
              :to="{ name: 'banks' }"
              title="进度已保存在服务端，随时可以从题库继续"
            >
              <span aria-hidden="true">←</span> 返回题库
            </RouterLink>
            <span class="drill-rail__count">第 {{ store.position }} / {{ store.total }} 题</span>
            <span class="drill-rail__label">第 {{ store.round.round_number }} 轮</span>
            <span class="drill-rail__percent">{{ store.progressPercent }}%</span>
          </div>
          <div
            class="progress"
            role="progressbar"
            :aria-valuenow="store.position"
            aria-valuemin="1"
            :aria-valuemax="store.total"
            :aria-label="`本轮进度：第 ${store.position} 题，共 ${store.total} 题`"
          >
            <div class="progress__bar" :style="{ width: `${store.progressPercent}%` }" />
          </div>
        </div>
      </div>

      <!-- 错误：说明发生了什么 + 一个明确的恢复动作 -->
      <div v-if="actionError" class="alert alert--error" role="alert">
        <div class="alert__body">
          <p class="alert__title">操作没有完成</p>
          <p style="margin: 0">{{ actionError }}</p>
        </div>
        <div class="alert__actions">
          <button class="btn btn--sm" type="button" @click="load">重新加载</button>
        </div>
      </div>

      <div v-if="store.conflictNotice" class="alert alert--info" role="status">
        <div class="alert__body">{{ store.conflictNotice }}</div>
      </div>

      <!-- 本轮完成 -->
      <div v-if="isCompleted" class="card">
        <div class="done">
          <div class="done__mark" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                 stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
              <path d="M20 6 9 17l-5-5" />
            </svg>
          </div>
          <h1 class="done__title">第 {{ store.round.round_number }} 轮已完成</h1>
          <p class="done__hint">
            本轮 {{ store.total }} 道题已全部过完一遍。开始下一轮会重新随机排序，并使用最新的题库版本。
          </p>
          <div class="row" style="justify-content: center">
            <button
              class="btn btn--primary btn--lg"
              type="button"
              :disabled="startingNext"
              @click="startNextRound"
            >
              <span v-if="startingNext" class="btn__spinner" aria-hidden="true" />
              {{ startingNext ? '正在开始…' : '开始下一轮' }}
            </button>
            <RouterLink class="btn btn--accent" :to="{ name: 'banks' }">返回题库</RouterLink>
          </div>
        </div>
      </div>

      <!-- 当前题 -->
      <div v-else-if="store.round.current_item" class="question">
        <div class="question__meta">
          <span class="question__crumb">第 {{ store.round.round_number }} 轮</span>
          <template v-if="store.round.current_item.question.section_path.length">
            <span aria-hidden="true">/</span>
            <span>{{ store.round.current_item.question.section_path.join(' / ') }}</span>
          </template>
        </div>

        <h1 class="question__title">{{ store.round.current_item.question.title }}</h1>

        <!-- 未揭答案 -->
        <div v-if="!answerVisible" class="reveal">
          <button
            class="btn btn--primary btn--lg"
            type="button"
            :disabled="busy"
            aria-controls="current-answer"
            :aria-expanded="false"
            @click="reveal"
          >
            <span v-if="busy" class="btn__spinner" aria-hidden="true" />
            {{ busy ? '正在获取…' : '查看答案' }}
          </button>
          <span class="reveal__hint">先自己回忆一遍，再对照答案</span>
        </div>

        <!-- 已揭答案：可以再收起，收起后回到上面的「查看答案」 -->
        <div v-else id="current-answer" class="answer-block">
          <AnswerPanel :markdown="store.answer" />
        </div>

        <div class="drill-actions">
          <button
            class="btn btn--lg"
            type="button"
            :disabled="busy || !hasPrevious"
            :title="hasPrevious ? '回到上一题（← 或 K）' : '已经是第一题'"
            @click="previous"
          >
            上一题
          </button>
          <button
            class="btn btn--primary btn--lg"
            type="button"
            :disabled="busy"
            @click="next"
          >
            <span v-if="busy" class="btn__spinner" aria-hidden="true" />
            {{ isLast ? '完成本轮' : '下一题' }}
          </button>
          <button v-if="answerVisible" class="btn" type="button" @click="collapseAnswer">
            收起答案
          </button>
          <button
            class="btn drill-actions__spacer"
            type="button"
            :disabled="busy"
            @click="showAbandon = true"
          >
            放弃本轮
          </button>
        </div>

        <p class="drill-hints">
          <span class="drill-hints__item">
            <kbd>空格</kbd> {{ answerVisible ? '收起答案' : '查看答案' }}
          </span>
          <span class="drill-hints__item"><kbd>→</kbd> 或 <kbd>J</kbd> 下一题</span>
          <span class="drill-hints__item"><kbd>←</kbd> 或 <kbd>K</kbd> 上一题</span>
        </p>
      </div>

      <div v-else class="card">
        <div class="empty">
          <p class="empty__title">这道题暂时无法显示</p>
          <p class="empty__hint">可能是题库版本已经变化。重新加载可以获取最新状态。</p>
          <div class="empty__actions">
            <button class="btn" type="button" @click="load">重新加载</button>
          </div>
        </div>
      </div>
    </template>

    <!-- 轮次加载失败 -->
    <div v-else class="card">
      <div class="empty">
        <p class="empty__title">轮次加载失败</p>
        <p class="empty__hint">{{ actionError ?? store.error ?? '轮次不存在或已被删除。' }}</p>
        <div class="empty__actions">
          <button class="btn btn--primary" type="button" @click="load">重新加载</button>
          <RouterLink class="btn btn--accent" :to="{ name: 'banks' }">返回题库列表</RouterLink>
        </div>
      </div>
    </div>

    <!-- 屏幕阅读器播报：答案出现是状态变化，需要被通知 -->
    <p class="visually-hidden" role="status" aria-live="polite">
      {{ revealed ? '答案已显示' : '' }}
    </p>

    <ConfirmDialog
      :open="showAbandon"
      title="放弃本轮"
      message="放弃后本轮不会计入完成，你可以重新开始一轮新的随机顺序。"
      confirm-label="放弃本轮"
      danger
      :busy="busy"
      @confirm="abandon"
      @cancel="showAbandon = false"
    />
  </div>
</template>
