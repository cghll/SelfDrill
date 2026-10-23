/**
 * 统一 API 客户端。
 *
 * 约束：
 * - 所有请求都带 credentials: 'include'，会话在 HttpOnly Cookie 里。
 * - 非 2xx 一律抛出 ApiError，由调用方决定如何提示；
 *   409 ROUND_PROGRESS_CONFLICT 需要单独处理（重新拉取最新状态，不能静默跳题）。
 */

import type {
  ApiErrorBody,
  BankSummary,
  BankVersion,
  ConfirmPayload,
  ConfirmResponse,
  PreviewItemPatchResult,
  PreviewResponse,
  QuestionListPage,
  RoundDetail,
  RoundDirection,
  RoundStatus,
  RoundSummary,
  User,
} from './types'

const BASE = '/api/v1'

/**
 * 生成幂等键。
 *
 * `crypto.randomUUID` 只在**安全上下文**（HTTPS 或 localhost）里存在。
 * 项目默认部署方式是 Caddy 的 `:80`（见 deploy/Caddyfile），也就是通过
 * 局域网 http://<ip> 访问——那里 `crypto.randomUUID` 是 undefined。
 * 之前直接调用它会让 `advance` 在发出请求之前就抛 TypeError，
 * 表现就是刷题页永远提示「推进失败，请重试」。这里做三级降级。
 */
export function createIdempotencyKey(): string {
  const webCrypto = globalThis.crypto
  if (typeof webCrypto?.randomUUID === 'function') {
    return webCrypto.randomUUID()
  }
  if (typeof webCrypto?.getRandomValues === 'function') {
    const bytes = webCrypto.getRandomValues(new Uint8Array(16))
    // RFC 4122 v4
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  // 最后的兜底：不保证密码学强度，但足以让重试语义成立
  return `k-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  get isProgressConflict(): boolean {
    return this.code === 'ROUND_PROGRESS_CONFLICT'
  }

  get isUnauthenticated(): boolean {
    return this.code === 'UNAUTHENTICATED'
  }
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = 20000): Promise<T> {
  // 没有超时的话，连接被中间设备悄悄丢弃时按钮会永远停在「处理中」，
  // 而 NFR-003 要求网络失败必须给出可重试的明确提示。
  const controller = new AbortController()
  const timer = timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null

  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      credentials: 'include',
      signal: controller.signal,
      ...init,
      headers: {
        ...(init.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
        ...(init.headers ?? {}),
      },
    })
  } catch (error) {
    // 网络层失败不能让前端误以为操作成功（NFR-003）
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError(0, 'NETWORK_ERROR', '请求超时，请检查网络后重试')
    }
    throw new ApiError(0, 'NETWORK_ERROR', '网络连接失败，请检查网络后重试')
  } finally {
    if (timer !== null) clearTimeout(timer)
  }

  if (response.status === 204) {
    return undefined as T
  }

  const text = await response.text()
  const payload = text ? safeJsonParse(text) : null

  if (!response.ok) {
    const body = payload as ApiErrorBody | null
    throw new ApiError(
      response.status,
      body?.error?.code ?? 'INTERNAL_ERROR',
      body?.error?.message ?? `请求失败（${response.status}）`,
      body?.error?.details ?? {},
    )
  }

  return payload as T
}

function safeJsonParse(text: string): unknown {
  try {
    return JSON.parse(text)
  } catch {
    return null
  }
}

export const api = {
  // --- 认证 ---
  login(username: string, password: string): Promise<{ user: User }> {
    return request('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
  },

  logout(): Promise<void> {
    return request('/auth/logout', { method: 'POST' })
  },

  me(): Promise<User> {
    return request('/auth/me')
  },

  // --- 题库 ---
  listBanks(): Promise<BankSummary[]> {
    return request('/banks')
  },

  createBank(name: string, description?: string): Promise<BankSummary> {
    return request('/banks', {
      method: 'POST',
      body: JSON.stringify({ name, description: description ?? null }),
    })
  },

  getBank(bankId: string): Promise<BankSummary> {
    return request(`/banks/${bankId}`)
  },

  deleteBank(bankId: string): Promise<void> {
    return request(`/banks/${bankId}`, { method: 'DELETE' })
  },

  listVersions(bankId: string): Promise<BankVersion[]> {
    return request(`/banks/${bankId}/versions`)
  },

  listQuestions(
    bankId: string,
    params: { version_id?: string; page?: number; page_size?: number; keyword?: string } = {},
  ): Promise<QuestionListPage> {
    const query = new URLSearchParams()
    if (params.version_id) query.set('version_id', params.version_id)
    if (params.page) query.set('page', String(params.page))
    if (params.page_size) query.set('page_size', String(params.page_size))
    if (params.keyword) query.set('keyword', params.keyword)
    const suffix = query.toString() ? `?${query}` : ''
    return request(`/banks/${bankId}/questions${suffix}`)
  },

  // --- 导入 ---
  uploadPreview(bankId: string, file: File): Promise<PreviewResponse> {
    const form = new FormData()
    form.append('file', file)
    // 上传 10MB 文档并等待服务端解析，需要比普通请求宽松得多
    return request(`/banks/${bankId}/imports/preview`, { method: 'POST', body: form }, 120000)
  },

  patchPreviewItem(
    previewId: string,
    itemId: string,
    patch: {
      classification?: string
      title?: string
      answer_markdown?: string
      match_question_id?: string | null
      clear_match?: boolean
    },
  ): Promise<PreviewItemPatchResult> {
    return request(`/imports/${previewId}/items/${itemId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    })
  },

  confirmImport(previewId: string, payload: ConfirmPayload): Promise<ConfirmResponse> {
    return request(`/imports/${previewId}/confirm`, {
      method: 'POST',
      body: JSON.stringify(payload),
    })
  },

  // --- 轮次 ---
  startRound(bankId: string, restart = false): Promise<RoundDetail> {
    return request(`/banks/${bankId}/rounds`, {
      method: 'POST',
      body: JSON.stringify({ restart }),
    })
  },

  listRounds(bankId: string): Promise<RoundSummary[]> {
    return request(`/banks/${bankId}/rounds`)
  },

  getRound(roundId: string): Promise<RoundDetail> {
    return request(`/rounds/${roundId}`)
  },

  revealAnswer(roundId: string): Promise<{ id: string; answer: string | null; answer_revealed: boolean }> {
    return request(`/rounds/${roundId}/reveal`, { method: 'POST' })
  },

  advanceRound(
    roundId: string,
    expectedProgressVersion: number,
    idempotencyKey: string,
    direction: RoundDirection = 'next',
  ): Promise<RoundDetail> {
    return request(`/rounds/${roundId}/advance`, {
      method: 'POST',
      body: JSON.stringify({
        expected_progress_version: expectedProgressVersion,
        idempotency_key: idempotencyKey,
        direction,
      }),
    })
  },

  abandonRound(roundId: string): Promise<{ id: string; status: RoundStatus; round_number: number }> {
    return request(`/rounds/${roundId}/abandon`, { method: 'POST' })
  },
}
