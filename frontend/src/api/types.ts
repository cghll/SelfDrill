/**
 * 后端 API 类型定义。
 * 与 backend/app 各模块的 schemas.py 一一对应，
 * 字段名保持 snake_case 以避免两层转换带来的偏差。
 */

export interface User {
  id: string
  username: string
  created_at: string
}

export type RoundStatus = 'in_progress' | 'completed' | 'abandoned'
/** 位置移动方向：`next` 下一题，`previous` 上一题。两者共用 advance 接口。 */
export type RoundDirection = 'next' | 'previous'
export type ItemAction = 'added' | 'modified' | 'deleted' | 'unchanged' | 'ambiguous' | 'ignored'
export type ItemClassification = 'question' | 'section' | 'needs_review'

export interface ActiveRoundSummary {
  id: string
  round_number: number
  current_index: number
  total_count: number
  status: RoundStatus
  progress_version: number
  bank_version_id: string
}

export interface BankSummary {
  id: string
  name: string
  description: string | null
  question_count: number
  current_version: number | null
  current_version_id: string | null
  active_round: ActiveRoundSummary | null
  completed_round_count: number
  created_at: string
  updated_at: string
}

export interface BankVersion {
  id: string
  version_number: number
  question_count: number
  source_filename: string
  source_hash: string
  status: 'active' | 'superseded'
  created_at: string
}

export interface QuestionListItem {
  id: string
  question_id: string
  title: string
  heading_level: number
  section_path: string[]
  answer_summary: string
}

export interface QuestionListPage {
  items: QuestionListItem[]
  page: number
  page_size: number
  total: number
  total_pages: number
}

export interface MatchCandidate {
  question_id: string
  title: string
  section_path: string[]
  similarity: number
  reason: string
}

export interface PreviewItem {
  preview_item_id: string
  action: ItemAction
  title: string
  raw_title: string
  heading_level: number
  section_path: string[]
  answer_markdown: string
  answer_summary: string
  classification: ItemClassification
  confidence: number
  needs_review: boolean
  matched_question_id: string | null
  source_anchor: { start_line: number; end_line: number }
  content_flags: Record<string, boolean>
  warnings: string[]
  candidates: MatchCandidate[]
  diff_detail: string | null
}

/**
 * PATCH 预览项的响应。
 *
 * 改判分类会连带改变**父题**的答案边界，所以除了被改的那一条，
 * 服务端还会返回受影响的兄弟条目，前端必须一并同步。
 */
export interface PreviewItemPatchResult extends PreviewItem {
  affected_items: PreviewItem[]
  summary: PreviewResponse['summary'] | null
  diff: DiffSummary | null
}

export interface DeletedItem {
  question_id: string
  title: string
  section_path: string[]
  action: 'deleted' | 'ambiguous'
  possible_local_ids: string[]
}

export interface DiffSummary {
  added: number
  modified: number
  deleted: number
  unchanged: number
  ambiguous: number
}

export interface PreviewResponse {
  preview_id: string
  bank_id: string
  mode: 'create' | 'update'
  source_filename: string
  source_hash: string
  expires_at: string
  summary: {
    total_candidates: number
    high_confidence: number
    needs_review: number
    warnings: number
  }
  diff: DiffSummary
  items: PreviewItem[]
  deleted_items: DeletedItem[]
  warnings: string[]
}

export interface ConfirmResponse {
  bank_id: string
  version_id: string
  version_number: number
  changes: DiffSummary
}

export interface RoundQuestion {
  id: string
  title: string
  section_path: string[]
}

export interface RoundItem {
  id: string
  position: number
  question: RoundQuestion
  answer: string | null
  answer_revealed: boolean
}

export interface RoundDetail {
  id: string
  bank_id: string
  bank_version_id: string
  round_number: number
  status: RoundStatus
  current_index: number
  total_count: number
  progress_version: number
  started_at: string
  completed_at: string | null
  current_item: RoundItem | null
}

export interface RoundSummary {
  id: string
  bank_id: string
  bank_version_id: string
  round_number: number
  status: RoundStatus
  current_index: number
  total_count: number
  progress_version: number
  started_at: string
  completed_at: string | null
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details: Record<string, unknown>
  }
}

export interface AmbiguityDecision {
  preview_item_id: string
  decision: 'match_existing' | 'create_new' | 'keep_existing' | 'ignore'
  question_id?: string | null
}

export interface ConfirmPayload {
  accepted_preview_item_ids: string[]
  resolved_ambiguities: AmbiguityDecision[]
  confirmed_deleted_question_ids: string[]
}
