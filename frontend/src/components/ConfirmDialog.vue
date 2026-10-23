<script setup lang="ts">
/**
 * 确认对话框：删除题库、放弃轮次等破坏性操作前必须二次确认（FR-002）。
 *
 * 除了视觉，这里还负责三件键盘/无障碍上的事：
 * 1. Esc 关闭（modal-escape）。
 * 2. 打开时把焦点移进对话框，关闭后还给触发元素（focus-management）。
 * 3. 把背景内容标记为 aria-hidden，避免读屏器读到弹层后面的内容。
 */

import { nextTick, ref, watch } from 'vue'

const props = withDefaults(
  defineProps<{
    open: boolean
    title: string
    message: string
    confirmLabel?: string
    cancelLabel?: string
    danger?: boolean
    busy?: boolean
  }>(),
  {
    confirmLabel: '确认',
    cancelLabel: '取消',
    danger: false,
    busy: false,
  },
)

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const cancelRef = ref<HTMLButtonElement | null>(null)
let lastFocused: HTMLElement | null = null

watch(
  () => props.open,
  async (open) => {
    if (open) {
      lastFocused = document.activeElement as HTMLElement | null
      await nextTick()
      // 焦点给「取消」而不是「确认」：破坏性操作不该是回车的第一落点
      cancelRef.value?.focus()
    } else {
      lastFocused?.focus?.()
      lastFocused = null
    }
  },
)

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape' && !props.busy) {
    emit('cancel')
  }
}
</script>

<template>
  <div
    v-if="props.open"
    class="modal-backdrop"
    role="dialog"
    aria-modal="true"
    :aria-label="props.title"
    @click.self="emit('cancel')"
    @keydown="onKeydown"
  >
    <div class="modal">
      <h2 class="modal__title">{{ props.title }}</h2>
      <p class="modal__body">{{ props.message }}</p>
      <slot />
      <div class="modal__actions">
        <button
          ref="cancelRef"
          class="btn"
          type="button"
          :disabled="props.busy"
          @click="emit('cancel')"
        >
          {{ props.cancelLabel }}
        </button>
        <button
          class="btn"
          :class="props.danger ? 'btn--danger' : 'btn--primary'"
          type="button"
          :disabled="props.busy"
          @click="emit('confirm')"
        >
          <span v-if="props.busy" class="btn__spinner" aria-hidden="true" />
          {{ props.busy ? '处理中…' : props.confirmLabel }}
        </button>
      </div>
    </div>
  </div>
</template>
