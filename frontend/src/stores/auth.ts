/**
 * 认证状态。
 * 服务端 Cookie 是唯一真源，这里的 user 只是缓存，用于路由守卫和顶栏展示。
 */

import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, ApiError } from '@/api/client'
import type { User } from '@/api/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loading = ref(false)
  const initialized = ref(false)

  async function fetchMe(): Promise<User | null> {
    loading.value = true
    try {
      user.value = await api.me()
      return user.value
    } catch (error) {
      if (error instanceof ApiError && error.isUnauthenticated) {
        user.value = null
        return null
      }
      throw error
    } finally {
      loading.value = false
      initialized.value = true
    }
  }

  async function login(username: string, password: string): Promise<void> {
    const result = await api.login(username, password)
    user.value = result.user
    initialized.value = true
  }

  async function logout(): Promise<void> {
    try {
      await api.logout()
    } finally {
      user.value = null
    }
  }

  return { user, loading, initialized, fetchMe, login, logout }
})
