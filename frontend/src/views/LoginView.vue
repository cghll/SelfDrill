<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const error = ref<string | null>(null)
const submitting = ref(false)

const redirectTarget = computed(() => {
  const value = route.query.redirect
  return typeof value === 'string' && value.startsWith('/') ? value : '/banks'
})

async function submit(): Promise<void> {
  error.value = null
  if (!username.value.trim() || !password.value) {
    error.value = '请输入用户名和密码'
    return
  }

  submitting.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    password.value = ''
    await router.replace(redirectTarget.value)
  } catch (err) {
    error.value = err instanceof ApiError ? err.message : '登录失败，请稍后重试'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login">
    <div class="login__brand">
      <span class="app-header__mark" aria-hidden="true">S</span>
      <span>SelfDrill</span>
    </div>
    <p class="login__tagline">按轮次随机且不重复地过一遍你的面试文档</p>

    <div class="card">
      <h1 class="card__title" style="font-size: 18px">登录</h1>
      <p class="card__hint">使用部署时配置的个人账号登录，本应用不开放注册。</p>

      <div v-if="error" class="alert alert--error" role="alert">
        <div class="alert__body">{{ error }}</div>
      </div>

      <form @submit.prevent="submit">
        <label class="field">
          <span class="field__label">用户名</span>
          <input
            v-model="username"
            class="input"
            type="text"
            autocomplete="username"
            :disabled="submitting"
            autofocus
          />
        </label>

        <label class="field">
          <span class="field__label">密码</span>
          <input
            v-model="password"
            class="input"
            type="password"
            autocomplete="current-password"
            :disabled="submitting"
          />
        </label>

        <button class="btn btn--primary btn--block btn--lg" type="submit" :disabled="submitting">
          <span v-if="submitting" class="btn__spinner" aria-hidden="true" />
          {{ submitting ? '登录中…' : '登录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.login {
  max-width: 380px;
  margin: 10vh auto 0;
}

.login__brand {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--s-2);
  font-size: var(--fs-lg);
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: var(--s-2);
}

.login__tagline {
  text-align: center;
  color: var(--ink-2);
  font-size: var(--fs-sm);
  margin: 0 0 var(--s-6);
}
</style>
