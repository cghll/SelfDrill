/**
 * 阶段 7：答案 Markdown 安全渲染测试。
 *
 * 覆盖 NFR-001：所有 HTML 必须经过白名单清洗，脚本注入不能穿透。
 */

import { describe, expect, it } from 'vitest'
import { renderMarkdown } from './markdown'
import { sanitizeHtml } from './sanitize'

describe('sanitizeHtml', () => {
  it('移除 script 标签及其内容', () => {
    const result = sanitizeHtml('<p>安全</p><script>alert(1)</script>')
    expect(result).toContain('<p>安全</p>')
    expect(result).not.toContain('script')
    expect(result).not.toContain('alert')
  })

  it('移除 style / iframe / object / embed', () => {
    const result = sanitizeHtml(
      '<style>body{display:none}</style><iframe src="https://evil.test"></iframe>' +
        '<object data="x"></object><embed src="y">',
    )
    expect(result).not.toMatch(/style|iframe|object|embed/i)
  })

  it('移除事件处理属性', () => {
    const result = sanitizeHtml('<img src="https://a.test/a.png" onerror="alert(1)">')
    expect(result).toContain('src="https://a.test/a.png"')
    expect(result).not.toContain('onerror')
    expect(result).not.toContain('alert')
  })

  it('拒绝 javascript: 与 data: 协议', () => {
    const result = sanitizeHtml('<a href="javascript:alert(1)">点我</a>')
    expect(result).not.toContain('javascript:')
    expect(sanitizeHtml('<a href="data:text/html,<script>x</script>">x</a>')).not.toContain(
      'data:',
    )
  })

  it('允许 http/https 链接并强制 rel', () => {
    const result = sanitizeHtml('<a href="https://example.com">链接</a>')
    expect(result).toContain('href="https://example.com"')
    expect(result).toContain('rel="noopener noreferrer"')
  })

  it('保留白名单标签', () => {
    const result = sanitizeHtml('<h2>标题</h2><pre><code>int a = 1;</code></pre>')
    expect(result).toContain('<h2>标题</h2>')
    expect(result).toContain('<pre><code>int a = 1;</code></pre>')
  })

  it('转义属性中的引号，避免属性逃逸', () => {
    const result = sanitizeHtml('<a href="https://a.test/?q=1" title=\'a"b\'>x</a>')
    expect(result).not.toContain('a"b"')
  })

  it('丢弃未知标签但保留其文本内容', () => {
    const result = sanitizeHtml('<custom-tag>内容</custom-tag>')
    expect(result).toBe('内容')
  })
})

/**
 * 回归：手写正则清洗器的绕过方式。
 *
 * 原实现用 `<tag ...>` 正则匹配标签，属性值里一旦出现 `>`，匹配就会提前结束，
 * 后面的 `onerror` 被当成标签外的普通文本原样留在输出里——真实的 XSS。
 * 换成 DOMPurify 后这些载荷都必须被拦住。
 */
describe('sanitizeHtml 绕过回归', () => {
  function parse(html: string): HTMLElement {
    const div = document.createElement('div')
    div.innerHTML = sanitizeHtml(html)
    return div
  }

  it('属性值含 > 时不能漏掉事件属性', () => {
    const result = sanitizeHtml('<img src="x" onerror="window.__audit=1" title="<">')
    expect(result).not.toContain('onerror')
    expect(parse('<img src="x" onerror="window.__audit=1" title="<">').querySelector('img')
      ?.getAttribute('onerror')).toBeNull()
  })

  it('未闭合标签夹带的事件属性同样被清掉', () => {
    expect(sanitizeHtml('<img src=x onerror=alert(1)')).not.toContain('onerror')
  })

  it('svg / math 等外来命名空间不携带事件属性', () => {
    const result = sanitizeHtml('<svg><g onload="alert(1)"></g></svg>')
    expect(result).not.toContain('onload')
  })

  it('style 属性与 style 标签都被移除', () => {
    expect(sanitizeHtml('<p style="background:url(javascript:alert(1))">x</p>')).not.toContain('style')
    expect(sanitizeHtml('<style>p{color:red}</style>')).not.toContain('color:red')
  })

  it('表单与可执行标签不在白名单内', () => {
    const result = sanitizeHtml('<form action="https://evil.test"><input name="p"></form>')
    expect(result).not.toMatch(/form|input|action/i)
  })

  it('图片不接受 data: 与 javascript: 协议', () => {
    expect(sanitizeHtml('<img src="data:image/svg+xml,<svg onload=alert(1)>">')).not.toContain('data:')
    expect(sanitizeHtml('<img src="javascript:alert(1)">')).not.toContain('javascript:')
  })

  it('嵌套的 script 不会留下可执行的脚本元素', () => {
    // 剩下的文本是惰性的（已被转义），关键是不能再产生 <script> 元素
    const div = parse('<scr<script>ipt>alert(1)</scr</script>ipt>')
    expect(div.querySelector('script')).toBeNull()
    expect(div.innerHTML).not.toContain('<script')
  })
})

describe('renderMarkdown', () => {
  it('渲染标题、列表与代码块', () => {
    const html = renderMarkdown('# 标题\n\n- 项目一\n- 项目二\n\n```java\nint a = 1;\n```')
    expect(html).toContain('<h1>标题</h1>')
    expect(html).toContain('<li>项目一</li>')
    expect(html).toContain('<pre><code class="language-java">')
  })

  it('渲染表格', () => {
    const html = renderMarkdown('| 方式 | 说明 |\n| --- | --- |\n| synchronized | 关键字 |')
    expect(html).toContain('<table>')
    expect(html).toContain('<th>方式</th>')
    expect(html).toContain('<td>关键字</td>')
  })

  it('保留图片链接但不下发脚本', () => {
    const html = renderMarkdown('![示意图](https://example.com/a.png)')
    expect(html).toContain('src="https://example.com/a.png"')
    expect(html).toContain('alt="示意图"')
  })

  it('清洗 Markdown 中内嵌的 HTML 注入', () => {
    const html = renderMarkdown('正常内容\n\n<img src=x onerror="alert(1)">\n\n<script>alert(2)</script>')
    expect(html).not.toContain('onerror')
    expect(html).not.toContain('script')
    expect(html).toContain('正常内容')
  })

  it('清洗链接形式的注入', () => {
    // markdown-it 本身会拒绝 javascript: 链接（降级为纯文本），
    // 即使它透传，sanitizeHtml 的白名单也会再拦一层。
    const html = renderMarkdown('[点我](javascript:alert(1))')
    expect(html).not.toContain('href="javascript:')
    expect(sanitizeHtml('<a href="javascript:alert(1)">点我</a>')).not.toContain('href=')
  })

  it('空输入返回空字符串', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown(null)).toBe('')
    expect(renderMarkdown(undefined)).toBe('')
  })

  it('保留中文与代码块内的特殊字符', () => {
    const html = renderMarkdown('```\n<not-a-tag> && "引号"\n```')
    expect(html).toContain('&lt;not-a-tag&gt;')
    expect(html).toContain('&amp;&amp;')
  })
})
