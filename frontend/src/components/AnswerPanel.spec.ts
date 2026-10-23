/**
 * 阶段 7：答案渲染组件测试。
 *
 * 渲染管线为 markdown-it（html: true）→ sanitizeHtml 白名单，
 * 验证「合法结构正常显示」与「脚本注入被剥离」两个方向。
 */

import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AnswerPanel from './AnswerPanel.vue'

describe('AnswerPanel', () => {
  it('渲染标题、列表与代码块', () => {
    const wrapper = mount(AnswerPanel, {
      props: { markdown: '# 标题\n\n- 项目一\n- 项目二\n\n```java\nint a = 1;\n```' },
    })
    const html = wrapper.html()
    expect(html).toContain('<h1>标题</h1>')
    expect(html).toContain('项目一')
    expect(html).toContain('<pre>')
    expect(html).toContain('int a = 1;')
  })

  it('渲染表格', () => {
    const wrapper = mount(AnswerPanel, {
      props: { markdown: '| 方式 | 说明 |\n| --- | --- |\n| synchronized | 关键字 |' },
    })
    const html = wrapper.html()
    expect(html).toContain('<table>')
    expect(html).toContain('<th>方式</th>')
    expect(html).toContain('<td>关键字</td>')
  })

  it('渲染图片链接', () => {
    const wrapper = mount(AnswerPanel, {
      props: { markdown: '![示意图](https://example.com/a.png)' },
    })
    expect(wrapper.html()).toContain('src="https://example.com/a.png"')
  })

  it('保留答案中有意义的行内 HTML', () => {
    const wrapper = mount(AnswerPanel, {
      props: { markdown: '答案是 <strong>红黑树</strong> 和 <br>链表' },
    })
    const html = wrapper.html()
    expect(html).toContain('<strong>红黑树</strong>')
  })

  it('剥离答案中的脚本注入', () => {
    const wrapper = mount(AnswerPanel, {
      props: { markdown: '正常内容\n\n<script>alert(1)</script>\n\n<img src=x onerror="alert(2)">' },
    })
    const html = wrapper.html()
    expect(html).toContain('正常内容')
    expect(html).not.toContain('script')
    expect(html).not.toContain('onerror')
    expect(html).not.toContain('alert')
  })

  it('空内容不产生额外结构', () => {
    const wrapper = mount(AnswerPanel, { props: { markdown: null } })
    expect(wrapper.find('.answer').exists()).toBe(true)
    expect(wrapper.find('.answer').text()).toBe('')
  })
})
