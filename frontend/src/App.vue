<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const isPublic = computed(() => route.meta.public === true)
const showChrome = computed(() => !isPublic.value && auth.user !== null)

async function handleLogout(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <div class="app-shell">
    <header v-if="showChrome" class="app-header">
      <div class="app-header__inner">
        <RouterLink class="app-header__brand" :to="{ name: 'banks' }">
          <span class="app-header__mark" aria-hidden="true">S</span>
          SelfDrill
        </RouterLink>
        <nav class="app-header__nav" aria-label="主导航">
          <span class="app-header__user">{{ auth.user?.username }}</span>
          <RouterLink class="btn btn--ghost btn--sm" :to="{ name: 'settings' }">设置</RouterLink>
          <button class="btn btn--ghost btn--sm" type="button" @click="handleLogout">退出</button>
        </nav>
      </div>
    </header>

    <main class="app-main">
      <RouterView />
    </main>
  </div>
</template>
