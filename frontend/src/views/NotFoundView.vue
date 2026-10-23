<script setup lang="ts">
import { RouterLink } from 'vue-router'
</script>

<template>
  <div class="card">
    <div class="empty">
      <p class="empty__title">页面不存在</p>
      <p class="empty__hint">你访问的地址没有对应的页面。</p>
      <div class="empty__actions">
        <RouterLink class="btn btn--primary" :to="{ name: 'banks' }">返回题库</RouterLink>
      </div>
    </div>
  </div>
</template>
