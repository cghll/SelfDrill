/**
 * Markdown 渲染器。
 *
 * markdown-it 负责把 Markdown 转成 HTML，sanitizeHtml 负责白名单清洗。
 * 两层缺一不可：
 * - 只靠 markdown-it 的 `html: false` 会丢掉答案里「必要的 HTML 内容」（FR-003）。
 * - 直接开 `html: true` 又会把用户文档里的脚本原样送进刷题页（NFR-001）。
 * 所以打开 HTML 支持，再用白名单把危险标签与属性全部剥掉。
 *
 * 代码高亮不做语法着色（第一版不引入 highlight.js），
 * 只保证代码块结构与换行正确，语言标记保留在 class 上供后续扩展。
 */

import MarkdownIt from 'markdown-it'
import { sanitizeHtml } from './sanitize'

const md = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: true,
  typographer: false,
})

export function renderMarkdown(source: string | null | undefined): string {
  if (!source) return ''
  return sanitizeHtml(md.render(source))
}
