<script setup lang="ts">
/** 新建题库：创建空题库后立即进入导入预览（FR-002 + FR-003）。 */

import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'

const router = useRouter()

const name = ref('')
const description = ref('')
const error = ref<string | null>(null)
const submitting = ref(false)

async function submit(): Promise<void> {
  error.value = null
  if (!name.value.trim()) {
    error.value = '请输入题库名称'
    return
  }

  submitting.value = true
  try {
    const bank = await api.createBank(name.value.trim(), description.value.trim() || undefined)
    await router.replace({ name: 'bank-import', params: { id: bank.id } })
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '创建题库失败'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div style="max-width: 560px">
    <div class="page-header">
      <div>
        <h1 class="page-header__title">新建题库</h1>
        <p class="page-header__subtitle">创建后立即导入 Markdown 文档</p>
      </div>
    </div>

    <div v-if="error" class="alert alert--error" role="alert">
      <div class="alert__body">{{ error }}</div>
    </div>

    <form class="card" @submit.prevent="submit">
      <label class="field">
        <span class="field__label">题库名称</span>
        <input
          v-model="name"
          class="input"
          type="text"
          maxlength="200"
          placeholder="例如：Java 热门面试"
          :disabled="submitting"
          autofocus
        />
      </label>

      <label class="field">
        <span class="field__label">描述（可选）</span>
        <input
          v-model="description"
          class="input"
          type="text"
          maxlength="2000"
          placeholder="例如：Java、Redis、并发和中间件"
          :disabled="submitting"
        />
      </label>

      <div class="row">
        <button class="btn btn--primary" type="submit" :disabled="submitting">
          <span v-if="submitting" class="btn__spinner" aria-hidden="true" />
          {{ submitting ? '创建中…' : '创建并导入' }}
        </button>
        <button class="btn" type="button" :disabled="submitting" @click="router.back()">
          返回
        </button>
      </div>
    </form>
  </div>
</template>
