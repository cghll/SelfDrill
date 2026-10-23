<script setup lang="ts">
/** 设置页：账号信息、数据备份说明、退出登录。 */

import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

async function logout(): Promise<void> {
  await auth.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <div style="max-width: 620px">
    <div class="page-header">
      <h1 class="page-header__title">设置</h1>
    </div>

    <div class="card">
      <h2 class="card__title">账号</h2>
      <p class="muted small">
        当前登录：<strong>{{ auth.user?.username }}</strong>
      </p>
      <p class="muted small">
        第一版不提供公开注册，账号由部署配置在首次启动时创建。
      </p>
      <button class="btn btn--danger" type="button" @click="logout">退出登录</button>
    </div>

    <div class="card">
      <h2 class="card__title">数据与备份</h2>
      <p class="muted small" style="margin-bottom: 0">
        所有题库、版本和刷题进度都保存在服务端的 SQLite 数据库与上传目录中。
        请在部署环境中定期备份 <code class="mono">data/app.db</code> 与
        <code class="mono">data/uploads/</code>，至少保留最近 7 份。
      </p>
    </div>

    <div class="card">
      <h2 class="card__title">关于</h2>
      <p class="muted small" style="margin-bottom: 0">
        SelfDrill 把个人维护的 Markdown 面试文档转成可刷题题库：按轮次随机且不重复地出题，
        答案默认隐藏，进度保存在服务端，换设备继续。
      </p>
    </div>
  </div>
</template>
