/**
 * 答案 Markdown 安全渲染。
 *
 * 约束（NFR-001 / 约束文档第 7 节）：所有 HTML 必须经过白名单清洗后才能 v-html，
 * 禁止 script/style/iframe/on* 事件属性，外链强制 rel="noopener noreferrer"。
 *
 * 这里用 DOMPurify（约束文档第 2 节指定的渲染方案）。
 * 之前手写的正则清洗器有两个无法修补的缺陷：
 *
 * 1. 属性值里出现 `>` 时（例如 `<img src=x onerror=... title="<">`），
 *    标签匹配正则会提前截断，`onerror` 被原样留在输出里，构成真实 XSS。
 * 2. 正则无法理解 HTML 的词法结构，任何边界情况都只能靠补丁堆叠。
 *
 * DOMPurify 基于真实 DOM 解析，这两类问题从根上不存在。
 */

import DOMPurify from 'dompurify'

/** 标签白名单（约束文档第 7 节）。`s` 是 markdown-it 对 `~~删除线~~` 的实际输出。 */
const ALLOWED_TAGS = [
  'p', 'br', 'strong', 'em', 'del', 's', 'code', 'pre', 'blockquote',
  'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
  'table', 'thead', 'tbody', 'tr', 'th', 'td', 'hr',
  'a', 'img', 'span',
]

/** 属性白名单（约束文档第 7 节）。 */
const ALLOWED_ATTR = ['href', 'title', 'src', 'alt', 'class']

/**
 * 只放行绝对安全的协议。
 *
 * 注意：DOMPurify 默认**允许** `<img src="data:...">`（`DATA_URI_TAGS` 行为），
 * 而答案文档里的图片只应该来自 http/https 或站内相对路径。
 * 所以除了 ALLOWED_URI_REGEXP，下面还会在 hook 里逐个属性复核一遍。
 */
const SAFE_URL = /^(?:https?:|mailto:|#|\/)/i
const URI_ATTRS = ['href', 'src'] as const

let hooked = false

function ensureHook(): void {
  if (hooked) return
  hooked = true

  DOMPurify.addHook('afterSanitizeAttributes', (node) => {
    if (!(node instanceof Element)) return

    // 外链必须带 rel，防止 tabnabbing
    if (node.tagName.toLowerCase() === 'a') {
      node.setAttribute('rel', 'noopener noreferrer')
    }

    // 兜住 DOMPurify 默认放行、但本项目不允许的协议（data: 等）
    for (const attr of URI_ATTRS) {
      const value = node.getAttribute(attr)
      if (value !== null && !SAFE_URL.test(value.trim())) {
        node.removeAttribute(attr)
      }
    }
  })
}

export function sanitizeHtml(html: string): string {
  if (!html) return ''
  ensureHook()

  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOWED_URI_REGEXP: SAFE_URL,
    // 去掉 script/style/iframe/object/embed 等标签时保留其文本兄弟节点，
    // 但 script/style 的内容本身必须整体丢弃
    KEEP_CONTENT: true,
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'input', 'link', 'meta', 'base'],
    // 事件属性与 style 属性永远不在白名单里，这里再显式声明一次
    FORBID_ATTR: ['style'],
    RETURN_TRUSTED_TYPE: false,
  }) as unknown as string
}

/** 纯文本转义，用于标题等不需要 Markdown 的位置 */
export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
