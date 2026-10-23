<script setup lang="ts">
/**
 * 导入预览：展示识别结果、修正题目边界、处理歧义、确认更新。
 *
 * 前端不猜测差异：所有 action / 候选关联都来自服务端的 diff 计算，
 * 用户在这里做的只是「确认或修正」。
 *
 * 需要注意的一点：改判分类会连带改变**父题**的答案边界，服务端会把这些
 * 受影响条目一起返回（`affected_items`），必须同步进本地预览，
 * 否则用户看到的答案和最终落库的答案会不一致。
 */

import { computed, ref } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'
import type {
  AmbiguityDecision,
  DeletedItem,
  PreviewItem,
  PreviewItemPatchResult,
  PreviewResponse,
} from '@/api/types'
import AnswerPanel from '@/components/AnswerPanel.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import DiffBadge from '@/components/DiffBadge.vue'

const route = useRoute()
const router = useRouter()
const bankId = computed(() => String(route.params.id))

const file = ref<File | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)
const preview = ref<PreviewResponse | null>(null)
const error = ref<string | null>(null)
const uploading = ref(false)
const confirming = ref(false)
const showDiscard = ref(false)
/** 最近一次被联动修改的条目，用于在界面上标出「这个也变了」 */
const recentlyAffected = ref<string[]>([])

/** 用户排除的预览项（默认全部接受） */
const excluded = ref<Set<string>>(new Set())
/** 歧义项的决定 */
const decisions = ref<Map<string, AmbiguityDecision>>(new Map())
/** 确认删除的旧题 */
const confirmedDeletes = ref<Set<string>>(new Set())
/** 正在编辑答案的预览项 */
const editingAnswer = ref<string | null>(null)
const answerDraft = ref('')

const candidates = computed(() =>
  (preview.value?.items ?? []).filter((item) => item.classification !== 'section'),
)

const acceptedItems = computed(() =>
  candidates.value.filter((item) => !excluded.value.has(item.preview_item_id)),
)

const unresolvedAmbiguities = computed(() =>
  acceptedItems.value.filter(
    (item) => item.action === 'ambiguous' && !decisions.value.has(item.preview_item_id),
  ),
)

const unresolvedNeedsReview = computed(() =>
  acceptedItems.value.filter((item) => item.classification === 'needs_review'),
)

const unresolvedDeletions = computed(() =>
  (preview.value?.deleted_items ?? []).filter((item) => {
    if (confirmedDeletes.value.has(item.question_id)) return false
    if (item.action === 'ambiguous') {
      // 改名候选已决定关联到某道新题，就不必再确认删除
      return ![...decisions.value.values()].some(
        (decision) =>
          (decision.decision === 'match_existing' || decision.decision === 'keep_existing') &&
          decision.question_id === item.question_id,
      )
    }
    return true
  }),
)

const blockingReasons = computed(() => {
  const reasons: string[] = []
  if (acceptedItems.value.length === 0) reasons.push('至少选择一道题目')
  if (unresolvedNeedsReview.value.length) {
    reasons.push(`${unresolvedNeedsReview.value.length} 个低置信标题需要确认是题目还是分类`)
  }
  if (unresolvedAmbiguities.value.length) {
    reasons.push(`${unresolvedAmbiguities.value.length} 个改名/歧义项需要选择处理方式`)
  }
  if (unresolvedDeletions.value.length) {
    reasons.push(`${unresolvedDeletions.value.length} 道旧题需要确认是否删除`)
  }
  return reasons
})

const canConfirm = computed(() => preview.value !== null && blockingReasons.value.length === 0)

async function onFileChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const selected = input.files?.[0] ?? null
  file.value = selected
  if (selected) {
    await upload()
  }
}

async function upload(): Promise<void> {
  if (!file.value) return
  uploading.value = true
  error.value = null
  try {
    preview.value = await api.uploadPreview(bankId.value, file.value)
    excluded.value = new Set()
    decisions.value = new Map()
    confirmedDeletes.value = new Set()
    recentlyAffected.value = []
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '上传失败'
    // 允许用户重选同一个文件重试
    if (fileInput.value) fileInput.value.value = ''
  } finally {
    uploading.value = false
  }
}

function toggleInclude(item: PreviewItem): void {
  const next = new Set(excluded.value)
  if (next.has(item.preview_item_id)) {
    next.delete(item.preview_item_id)
  } else {
    next.add(item.preview_item_id)
  }
  excluded.value = next
}

/** 把服务端返回的条目（含被联动的兄弟条目）同步进本地预览 */
function applyPatchResult(result: PreviewItemPatchResult): void {
  if (!preview.value) return
  const updates = new Map<string, PreviewItem>()
  updates.set(result.preview_item_id, result)
  for (const item of result.affected_items) {
    updates.set(item.preview_item_id, item)
  }

  preview.value = {
    ...preview.value,
    items: preview.value.items.map((item) => updates.get(item.preview_item_id) ?? item),
    summary: result.summary ?? preview.value.summary,
    diff: result.diff ?? preview.value.diff,
  }

  recentlyAffected.value = result.affected_items
    .map((item) => item.preview_item_id)
    .filter((id) => id !== result.preview_item_id)
}

async function setClassification(item: PreviewItem, classification: string): Promise<void> {
  if (!preview.value) return
  error.value = null
  try {
    const result = await api.patchPreviewItem(
      preview.value.preview_id,
      item.preview_item_id,
      { classification },
    )
    applyPatchResult(result)
    if (classification === 'section') {
      const next = new Set(excluded.value)
      next.add(item.preview_item_id)
      excluded.value = next
    }
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '修改分类失败'
  }
}

function startEditAnswer(item: PreviewItem): void {
  editingAnswer.value = item.preview_item_id
  answerDraft.value = item.answer_markdown
}

async function saveAnswer(item: PreviewItem): Promise<void> {
  if (!preview.value) return
  error.value = null
  try {
    applyPatchResult(
      await api.patchPreviewItem(preview.value.preview_id, item.preview_item_id, {
        answer_markdown: answerDraft.value,
      }),
    )
    editingAnswer.value = null
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '保存答案失败'
  }
}

function decide(
  item: PreviewItem,
  decision: AmbiguityDecision['decision'],
  questionId?: string,
): void {
  const next = new Map(decisions.value)
  next.set(item.preview_item_id, {
    preview_item_id: item.preview_item_id,
    decision,
    question_id: questionId ?? null,
  })
  decisions.value = next
}

function toggleDelete(item: DeletedItem): void {
  const next = new Set(confirmedDeletes.value)
  if (next.has(item.question_id)) {
    next.delete(item.question_id)
  } else {
    next.add(item.question_id)
  }
  confirmedDeletes.value = next
}

async function confirm(): Promise<void> {
  if (!preview.value) return
  confirming.value = true
  error.value = null
  try {
    const result = await api.confirmImport(preview.value.preview_id, {
      accepted_preview_item_ids: acceptedItems.value.map((item) => item.preview_item_id),
      resolved_ambiguities: [...decisions.value.values()],
      confirmed_deleted_question_ids: [...confirmedDeletes.value],
    })
    await router.replace({
      name: 'bank-detail',
      params: { id: result.bank_id },
      query: { imported: String(result.version_number) },
    })
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '确认导入失败'
  } finally {
    confirming.value = false
  }
}

function contentFlagLabels(item: PreviewItem): string[] {
  const labels: Record<string, string> = {
    code_block: '代码块',
    image: '图片',
    table: '表格',
    list: '列表',
    html: 'HTML',
  }
  return Object.entries(item.content_flags)
    .filter(([, present]) => present)
    .map(([key]) => labels[key] ?? key)
}
</script>

<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-header__title">
          {{ preview?.mode === 'update' ? '更新导入' : '导入 Markdown' }}
        </h1>
        <p class="page-header__subtitle">
          上传文档，确认识别结果后再写入题库。确认前不会改动任何现有数据。
        </p>
      </div>
      <div class="page-header__actions">
        <RouterLink class="btn" :to="{ name: 'bank-detail', params: { id: bankId } }">
          返回题库
        </RouterLink>
      </div>
    </div>

    <div v-if="error" class="alert alert--error" role="alert">
      <div class="alert__body">{{ error }}</div>
    </div>

    <div class="card">
      <label class="field" style="margin-bottom: 0">
        <span class="field__label">选择 Markdown 文件</span>
        <input
          ref="fileInput"
          class="file-input"
          type="file"
          accept=".md,.markdown,text/markdown"
          :disabled="uploading"
          @change="onFileChange"
        />
        <span class="field__hint">支持 .md / .markdown，UTF-8 编码，默认上限 10 MB。</span>
      </label>
      <p v-if="uploading" class="muted small" style="margin: 12px 0 0" role="status">
        正在解析文档…
      </p>
    </div>

    <template v-if="preview">
      <div class="card">
        <div class="card__header">
          <h2 class="card__title">
            {{ preview.mode === 'update' ? '更新预览' : '导入预览' }}
          </h2>
          <span class="card__header-meta mono">{{ preview.source_filename }}</span>
        </div>

        <div class="grid-stats">
          <div class="stat">
            <div class="stat__value">{{ preview.summary.total_candidates }}</div>
            <div class="stat__label">识别到的题目</div>
          </div>
          <div class="stat">
            <div class="stat__value">{{ preview.summary.high_confidence }}</div>
            <div class="stat__label">高置信</div>
          </div>
          <div class="stat">
            <div class="stat__value">{{ preview.summary.needs_review }}</div>
            <div class="stat__label">待确认</div>
          </div>
          <div class="stat">
            <div class="stat__value">{{ preview.summary.warnings }}</div>
            <div class="stat__label">警告</div>
          </div>
        </div>

        <div v-if="preview.mode === 'update'" class="row" style="margin-top: 16px; gap: 8px">
          <span class="tag tag--added">新增 {{ preview.diff.added }}</span>
          <span class="tag tag--modified">修改 {{ preview.diff.modified }}</span>
          <span class="tag tag--unchanged">未变化 {{ preview.diff.unchanged }}</span>
          <span class="tag tag--deleted">删除 {{ preview.diff.deleted }}</span>
          <span v-if="preview.diff.ambiguous" class="tag tag--ambiguous">
            歧义 {{ preview.diff.ambiguous }}
          </span>
        </div>

        <div v-if="preview.warnings.length" class="alert alert--warning" style="margin: 16px 0 0">
          <div class="alert__body">
            <div v-for="(warning, index) in preview.warnings" :key="index">{{ warning }}</div>
          </div>
        </div>
      </div>

      <!-- 题目：主列 + 确认栏 -->
      <div class="split split--aside" style="margin-top: 16px">
        <div>
          <div class="card">
            <div class="card__header">
              <h2 class="card__title">识别结果</h2>
              <span class="card__header-meta num">
                {{ acceptedItems.length }} / {{ candidates.length }} 已选
              </span>
            </div>
            <p class="card__hint">
              取消勾选可以放弃某道题；把误判的标题标为「分类」会把它并入上一题的答案。
            </p>

            <ul class="list">
              <li v-for="item in candidates" :key="item.preview_item_id" class="list__item">
                <div class="row row--top" style="gap: 12px; flex-wrap: nowrap">
                  <input
                    type="checkbox"
                    :checked="!excluded.has(item.preview_item_id)"
                    :aria-label="`包含题目 ${item.title}`"
                    style="margin-top: 5px; width: 17px; height: 17px; flex-shrink: 0"
                    @change="toggleInclude(item)"
                  />
                  <div style="flex: 1; min-width: 0">
                    <div class="row" style="gap: 8px">
                      <DiffBadge :action="item.action" />
                      <span v-if="item.needs_review" class="tag tag--needs_review">待确认</span>
                      <span
                        v-if="recentlyAffected.includes(item.preview_item_id)"
                        class="tag tag--modified"
                      >
                        答案已联动更新
                      </span>
                      <strong style="font-size: 15.5px; overflow-wrap: anywhere">
                        {{ item.title }}
                      </strong>
                    </div>

                    <p v-if="item.section_path.length" class="muted small" style="margin: 6px 0 0">
                      {{ item.section_path.join(' / ') }}
                    </p>

                    <p class="muted small num" style="margin: 6px 0 0">
                      H{{ item.heading_level }} · 置信度 {{ item.confidence }} · 行
                      {{ item.source_anchor.start_line }}–{{ item.source_anchor.end_line }}
                      <template v-if="contentFlagLabels(item).length">
                        · 保留：{{ contentFlagLabels(item).join('、') }}
                      </template>
                    </p>

                    <div
                      v-if="item.warnings.length"
                      class="alert alert--warning"
                      style="margin: 10px 0 0"
                    >
                      <div class="alert__body">
                        <div v-for="(warning, index) in item.warnings" :key="index">
                          {{ warning }}
                        </div>
                      </div>
                    </div>

                    <div v-if="item.diff_detail" class="alert alert--info" style="margin: 10px 0 0">
                      <div class="alert__body">{{ item.diff_detail }}</div>
                    </div>

                    <!-- 歧义：必须由用户决定 -->
                    <div
                      v-if="item.action === 'ambiguous'"
                      class="card card--quiet"
                      style="margin-top: 12px; border: 1px solid var(--warning); padding: 14px"
                    >
                      <p class="small" style="margin: 0 0 10px; font-weight: 600">
                        这可能是同一道题的改名，请选择处理方式：
                      </p>
                      <div class="stack">
                        <button
                          v-for="candidate in item.candidates"
                          :key="candidate.question_id"
                          class="btn btn--block"
                          :class="
                            decisions.get(item.preview_item_id)?.question_id ===
                              candidate.question_id &&
                            decisions.get(item.preview_item_id)?.decision === 'match_existing'
                              ? 'btn--primary'
                              : ''
                          "
                          type="button"
                          @click="decide(item, 'match_existing', candidate.question_id)"
                        >
                          关联旧题：{{ candidate.title }}（相似度
                          {{ Math.round(candidate.similarity * 100) }}%）
                        </button>
                        <div class="row">
                          <button
                            class="btn"
                            :class="
                              decisions.get(item.preview_item_id)?.decision === 'create_new'
                                ? 'btn--primary'
                                : ''
                            "
                            type="button"
                            @click="decide(item, 'create_new')"
                          >
                            作为新题导入
                          </button>
                          <button
                            v-if="item.candidates.length"
                            class="btn"
                            :class="
                              decisions.get(item.preview_item_id)?.decision === 'keep_existing'
                                ? 'btn--primary'
                                : ''
                            "
                            type="button"
                            @click="decide(item, 'keep_existing', item.candidates[0].question_id)"
                          >
                            保留旧题，忽略新内容
                          </button>
                        </div>
                      </div>
                    </div>

                    <!-- 待确认：是题目还是分类 -->
                    <div v-if="item.needs_review" class="row" style="margin-top: 12px">
                      <span class="small muted">请确认：</span>
                      <button
                        class="btn btn--sm"
                        type="button"
                        @click="setClassification(item, 'question')"
                      >
                        这是题目
                      </button>
                      <button
                        class="btn btn--sm"
                        type="button"
                        @click="setClassification(item, 'section')"
                      >
                        这是分类
                      </button>
                    </div>

                    <!-- 答案编辑 -->
                    <div style="margin-top: 12px">
                      <template v-if="editingAnswer === item.preview_item_id">
                        <textarea
                          v-model="answerDraft"
                          class="textarea"
                          :aria-label="`编辑 ${item.title} 的答案`"
                        />
                        <div class="row" style="margin-top: 8px">
                          <button class="btn btn--primary btn--sm" type="button" @click="saveAnswer(item)">
                            保存答案
                          </button>
                          <button class="btn btn--sm" type="button" @click="editingAnswer = null">
                            取消
                          </button>
                        </div>
                      </template>
                      <template v-else>
                        <p class="muted small" style="margin: 0 0 8px">
                          {{ item.answer_summary || '（没有识别到答案内容）' }}
                        </p>
                        <div class="row">
                          <button
                            class="btn btn--ghost btn--sm"
                            type="button"
                            @click="startEditAnswer(item)"
                          >
                            编辑答案
                          </button>
                          <button
                            class="btn btn--ghost btn--sm"
                            type="button"
                            @click="setClassification(item, 'section')"
                          >
                            标为分类
                          </button>
                        </div>
                      </template>
                    </div>
                  </div>
                </div>
              </li>
            </ul>
          </div>

          <!-- 删除候选必须逐个确认 -->
          <div v-if="preview.deleted_items.length" class="card">
            <h2 class="card__title">
              新文档中已不存在的题目（{{ preview.deleted_items.length }}）
            </h2>
            <p class="card__hint">默认不删除。勾选后这些题目会在新版本中移除。</p>
            <ul class="list">
              <li v-for="item in preview.deleted_items" :key="item.question_id" class="list__item">
                <div class="row row--top" style="gap: 12px; flex-wrap: nowrap">
                  <input
                    type="checkbox"
                    :checked="confirmedDeletes.has(item.question_id)"
                    :aria-label="`确认删除 ${item.title}`"
                    style="margin-top: 5px; width: 17px; height: 17px; flex-shrink: 0"
                    @change="toggleDelete(item)"
                  />
                  <div style="flex: 1; min-width: 0">
                    <div class="row" style="gap: 8px">
                      <span
                        class="tag"
                        :class="item.action === 'ambiguous' ? 'tag--ambiguous' : 'tag--deleted'"
                      >
                        {{ item.action === 'ambiguous' ? '可能被改名' : '待删除' }}
                      </span>
                      <strong style="overflow-wrap: anywhere">{{ item.title }}</strong>
                    </div>
                    <p v-if="item.section_path.length" class="muted small" style="margin: 6px 0 0">
                      {{ item.section_path.join(' / ') }}
                    </p>
                  </div>
                </div>
              </li>
            </ul>
          </div>
        </div>

        <!-- 侧栏：确认栏 + 渲染预览 -->
        <div class="split__aside">
          <div class="card">
            <h2 class="card__title">
              {{ preview.mode === 'update' ? '确认更新' : '确认导入' }}
            </h2>

            <div v-if="!canConfirm" class="alert alert--warning" style="margin-bottom: 14px">
              <div class="alert__body">
                <p class="alert__title">确认前还需要处理</p>
                <ul>
                  <li v-for="(reason, index) in blockingReasons" :key="index">{{ reason }}</li>
                </ul>
              </div>
            </div>

            <div class="stack">
              <button
                class="btn btn--primary btn--lg btn--block"
                type="button"
                :disabled="!canConfirm || confirming"
                @click="confirm"
              >
                <span v-if="confirming" class="btn__spinner" aria-hidden="true" />
                {{ confirming ? '提交中…' : preview.mode === 'update' ? '确认更新' : '确认导入' }}
              </button>
              <button
                class="btn btn--block"
                type="button"
                :disabled="confirming"
                @click="showDiscard = true"
              >
                放弃本次导入
              </button>
            </div>
          </div>

          <div v-if="acceptedItems.length" class="card">
            <h2 class="card__title">答案渲染预览</h2>
            <p class="card__hint">
              第一道题（{{ acceptedItems[0]?.title }}）的答案渲染效果，用于确认代码块与表格正常。
            </p>
            <AnswerPanel :markdown="acceptedItems[0]?.answer_markdown" />
          </div>
        </div>
      </div>
    </template>

    <ConfirmDialog
      :open="showDiscard"
      title="放弃本次导入"
      message="当前预览不会被写入题库，题库仍保持原状。"
      confirm-label="放弃导入"
      danger
      @confirm="router.push({ name: 'bank-detail', params: { id: bankId } })"
      @cancel="showDiscard = false"
    />
  </div>
</template>
