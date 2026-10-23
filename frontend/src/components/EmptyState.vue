<script setup lang="ts">
/** 空状态占位：一句说明 + 一个明确的下一步动作。 */

defineProps<{
  title?: string
  hint?: string
}>()
</script>

<template>
  <div class="empty">
    <p class="empty__title">
      <slot name="title">{{ title ?? '暂无内容' }}</slot>
    </p>
    <p v-if="hint || $slots.hint" class="empty__hint">
      <slot name="hint">{{ hint }}</slot>
    </p>
    <div v-if="$slots.actions" class="empty__actions">
      <slot name="actions" />
    </div>
  </div>
</template>
