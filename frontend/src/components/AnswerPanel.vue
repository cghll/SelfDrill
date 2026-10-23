<script setup lang="ts">
/**
 * 答案渲染组件。
 * 通过 v-html 输出的是经过 DOMPurify 白名单清洗的 HTML（见 utils/markdown.ts）。
 */

import { computed } from 'vue'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  markdown: string | null | undefined
}>()

const html = computed(() => renderMarkdown(props.markdown))
</script>

<template>
  <div class="answer-block__inner">
    <p class="answer-block__label">参考答案</p>
    <!-- eslint-disable-next-line vue/no-v-html -- 内容已通过 sanitizeHtml 白名单清洗 -->
    <div class="answer" v-html="html" />
  </div>
</template>
