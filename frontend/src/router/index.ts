/**
 * 路由与登录拦截。
 *
 * 未登录访问受保护页面时跳转登录页，并记录来源路径以便登录后返回。
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    redirect: '/banks',
  },
  {
    path: '/banks',
    name: 'banks',
    component: () => import('@/views/BankListView.vue'),
    meta: { title: '题库' },
  },
  {
    path: '/banks/new',
    name: 'bank-new',
    component: () => import('@/views/BankNewView.vue'),
    meta: { title: '新建题库' },
  },
  {
    path: '/banks/:id',
    name: 'bank-detail',
    component: () => import('@/views/BankDetailView.vue'),
    meta: { title: '题库详情' },
  },
  {
    path: '/banks/:id/import',
    name: 'bank-import',
    component: () => import('@/views/ImportPreviewView.vue'),
    meta: { title: '导入预览' },
  },
  {
    path: '/rounds/:id',
    name: 'round',
    component: () => import('@/views/RoundView.vue'),
    meta: { title: '刷题' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { title: '设置' },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { public: true, title: '页面不存在' },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 首次进入时确认会话状态，避免刷新后误判为未登录
  if (!auth.initialized) {
    await auth.fetchMe()
  }

  if (!to.meta.public && !auth.user) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && auth.user) {
    return { name: 'banks' }
  }
  return true
})

router.afterEach((to) => {
  const title = to.meta.title as string | undefined
  document.title = title ? `${title} · SelfDrill` : 'SelfDrill 面试刷题'
})
