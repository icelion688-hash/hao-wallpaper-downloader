import { createRouter, createWebHistory } from 'vue-router'

const Accounts = () => import('../views/Accounts.vue')
const Tasks = () => import('../views/Tasks.vue')
const Gallery = () => import('../views/Gallery.vue')
const Upload = () => import('../views/Upload.vue')
const ImgbedManager = () => import('../views/ImgbedManager.vue')
const Filters = () => import('../views/Filters.vue')
const Stats = () => import('../views/Stats.vue')
const AutoPilot = () => import('../views/AutoPilot.vue')
const Convert = () => import('../views/Convert.vue')
const Sync = () => import('../views/Sync.vue')

const routes = [
  { path: '/', redirect: '/stats' },
  { path: '/autopilot', component: AutoPilot, meta: { title: '自动驾驶' } },
  { path: '/accounts', component: Accounts, meta: { title: '账号管理' } },
  { path: '/tasks', component: Tasks, meta: { title: '任务中心' } },
  { path: '/filters', component: Filters, meta: { title: '筛选配置' } },
  { path: '/gallery', component: Gallery, meta: { title: '下载画廊' } },
  { path: '/upload', component: Upload, meta: { title: '图床上传' } },
  { path: '/imgbed-manager', component: ImgbedManager, meta: { title: '远端图床管理' } },
  { path: '/convert', component: Convert, meta: { title: '格式转换' } },
  { path: '/stats', component: Stats, meta: { title: '系统监控' } },
  { path: '/sync', component: Sync, meta: { title: '数据同步' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.afterEach((to) => {
  document.title = `${to.meta.title || ''} - 好壁纸下载器`
})

export default router
