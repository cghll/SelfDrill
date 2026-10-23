<script setup lang="ts">
/** 题目/答案/分类的差异标签。 */

import type { ItemAction } from '@/api/types'

const props = defineProps<{ action: ItemAction }>()

const LABELS: Record<ItemAction, string> = {
  added: '新增',
  modified: '修改',
  deleted: '删除',
  unchanged: '未变化',
  ambiguous: '待确认',
  ignored: '分类',
}

const label = LABELS[props.action] ?? props.action
</script>

<template>
  <span class="tag" :class="`tag--${props.action}`">{{ label }}</span>
</template>
