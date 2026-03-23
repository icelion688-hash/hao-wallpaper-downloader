<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="logo">
        <span class="logo-icon">◉</span>
        <span class="logo-text">好壁纸<em>下载器</em></span>
      </div>

      <nav class="nav">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          active-class="nav-item--active"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span class="nav-label">{{ item.label }}</span>
          <span v-if="item.badge" class="nav-badge">{{ item.badge }}</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div class="sidebar-theme">
          <span class="sidebar-theme__label">主题</span>
          <div class="theme-switch">
            <button class="theme-switch__btn" :class="{ 'theme-switch__btn--active': themeMode === 'light' }" @click="setTheme('light')">亮色</button>
            <button class="theme-switch__btn" :class="{ 'theme-switch__btn--active': themeMode === 'dark' }" @click="setTheme('dark')">暗色</button>
          </div>
        </div>
        <div class="sidebar-status">
          <div class="status-dot" :class="serverOk ? 'status-dot--ok' : 'status-dot--err'"></div>
          <span class="status-label">{{ serverOk ? '服务运行中' : '连接断开' }}</span>
        </div>
      </div>
    </aside>

    <main class="main-content">
      <router-view v-slot="{ Component }">
        <Suspense>
          <template #default>
            <transition name="page" mode="out-in">
              <component :is="Component" />
            </transition>
          </template>
          <template #fallback>
            <div class="route-loading">
              <div class="route-loading__line"></div>
              <div class="route-loading__title">页面加载中</div>
              <div class="route-loading__text">正在按需载入模块...</div>
            </div>
          </template>
        </Suspense>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { healthCheck } from './api'

const APP_THEME_STORAGE_KEY = 'hao-wallpaper-theme'
const serverOk = ref(true)
const themeMode = ref('dark')
let healthTimer = null

const navItems = [
  { path: '/stats', icon: '◧', label: '系统监控' },
  { path: '/autopilot', icon: '◎', label: '自动驾驶' },
  { path: '/accounts', icon: '◉', label: '账号管理' },
  { path: '/tasks', icon: '▣', label: '任务中心' },
  { path: '/filters', icon: '◌', label: '筛选配置' },
  { path: '/gallery', icon: '▥', label: '下载画廊' },
  { path: '/upload', icon: '↥', label: '图床上传' },
  { path: '/imgbed-manager', icon: '▤', label: '远端图床' },
  { path: '/convert', icon: '↺', label: '格式转换' },
  { path: '/sync', icon: '⇄', label: '数据同步' },
]

async function checkHealth() {
  try {
    await healthCheck()
    serverOk.value = true
  } catch {
    serverOk.value = false
  }
}

function applyTheme(theme) {
  const normalized = theme === 'light' ? 'light' : 'dark'
  themeMode.value = normalized
  document.documentElement.setAttribute('data-theme', normalized)
  localStorage.setItem(APP_THEME_STORAGE_KEY, normalized)
}

function setTheme(theme) {
  applyTheme(theme)
}

onMounted(() => {
  const savedTheme = localStorage.getItem(APP_THEME_STORAGE_KEY)
  applyTheme(savedTheme || 'dark')
  checkHealth()
  healthTimer = setInterval(checkHealth, 30000)
})

onUnmounted(() => {
  clearInterval(healthTimer)
})
</script>

<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --primary:     #4f8eff;
  --primary-light:#eef4ff;
  --text:        #e8edf5;
  --text-muted:  #8a96a8;
  --bg-subtle:   #171b22;
  --bg-selected: #152033;
}

:root,
:root[data-theme='dark'] {
  --bg-base:    #0d0f12;
  --bg-panel:   #13161b;
  --bg-card:    #1a1e25;
  --bg-hover:   #1f242d;
  --border:     #252b35;
  --border-hi:  #3a4455;
  --accent:     #4f8eff;
  --accent-dim: #2a4a8a;
  --accent-glow:rgba(79,142,255,.15);
  --text-1:     #e8edf5;
  --text-2:     #8a96a8;
  --text-3:     #4f5a6a;
  --green:      #3ecf72;
  --red:        #f05a5a;
  --orange:     #f5a623;
  --page-backdrop:
    radial-gradient(circle at top left, rgba(79, 142, 255, 0.14), transparent 24%),
    radial-gradient(circle at bottom right, rgba(62, 207, 114, 0.08), transparent 22%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.02), transparent 28%),
    var(--bg-base);
  --font-ui:    'DM Mono', 'Fira Code', 'Courier New', monospace;
  --font-body:  'DM Sans', 'Helvetica Neue', sans-serif;
  --radius:     6px;
  --sidebar-w:  228px;
}

:root[data-theme='light'] {
  --bg-base:    #eef3f8;
  --bg-panel:   #f7f9fc;
  --bg-card:    #ffffff;
  --bg-hover:   #edf3fa;
  --border:     #d5deea;
  --border-hi:  #b7c5d8;
  --accent:     #2d6cdf;
  --accent-dim: #dce7fb;
  --accent-glow:rgba(45,108,223,.12);
  --text-1:     #17212f;
  --text-2:     #5f6f84;
  --text-3:     #8592a4;
  --primary:    #2d6cdf;
  --primary-light:#eaf1ff;
  --text:       #17212f;
  --text-muted: #5f6f84;
  --bg-subtle:  #f3f6fb;
  --bg-selected:#eaf1ff;
  --green:      #1d9252;
  --red:        #d54b4b;
  --orange:     #cc7f18;
  --page-backdrop:
    radial-gradient(circle at top left, rgba(45, 108, 223, 0.12), transparent 24%),
    radial-gradient(circle at bottom right, rgba(16, 185, 129, 0.08), transparent 24%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.62), rgba(255, 255, 255, 0.24)),
    var(--bg-base);
}

html, body, #app {
  height: 100%;
  background: var(--bg-base);
  color: var(--text-1);
  font-family: var(--font-body);
  font-size: 14px;
}

::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-hi); border-radius: 3px; }

.app-shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
  background: var(--page-backdrop);
}

.sidebar {
  width: var(--sidebar-w);
  flex-shrink: 0;
  background: var(--bg-panel);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 24px 20px 20px;
  border-bottom: 1px solid var(--border);
  font-family: var(--font-ui);
  letter-spacing: .04em;
}

.logo-icon { font-size: 20px; color: var(--accent); }
.logo-text { font-size: 14px; color: var(--text-1); font-weight: 600; }
.logo-text em { font-style: normal; color: var(--text-2); margin-left: 2px; }

.nav {
  flex: 1;
  padding: 12px 0;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 20px;
  color: var(--text-2);
  text-decoration: none;
  font-size: 13px;
  letter-spacing: .02em;
  transition: all .15s;
  border-left: 2px solid transparent;
  position: relative;
}

.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-1);
}

.nav-item--active {
  color: var(--accent);
  border-left-color: var(--accent);
  background: var(--accent-glow);
}

.nav-icon { font-size: 12px; width: 16px; text-align: center; }

.nav-badge {
  margin-left: auto;
  background: var(--accent-dim);
  color: var(--accent);
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 10px;
  font-family: var(--font-ui);
}

.sidebar-footer {
  padding: 16px 20px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 12px;
}

.sidebar-theme {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.sidebar-theme__label {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-ui);
  letter-spacing: .05em;
  text-transform: uppercase;
}

.theme-switch {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--bg-base);
}

.theme-switch__btn {
  border: none;
  background: transparent;
  color: var(--text-2);
  padding: 5px 10px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 12px;
  font-family: var(--font-body);
  transition: background .15s, color .15s;
}

.theme-switch__btn--active {
  background: var(--accent);
  color: #fff;
}

.sidebar-status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-dot--ok { background: var(--green); box-shadow: 0 0 6px var(--green); }
.status-dot--err { background: var(--red); box-shadow: 0 0 6px var(--red); }
.status-label { font-size: 11px; color: var(--text-3); font-family: var(--font-ui); }

.main-content {
  flex: 1;
  overflow-y: auto;
  background: var(--page-backdrop);
  position: relative;
}

.route-loading {
  min-height: 100vh;
  display: grid;
  place-content: center;
  gap: 10px;
  padding: 32px;
  text-align: center;
}

.route-loading__line {
  width: 180px;
  height: 2px;
  margin: 0 auto;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  animation: route-loading 1.1s linear infinite;
}

.route-loading__title {
  font-size: 14px;
  color: var(--text-1);
  letter-spacing: .06em;
  font-family: var(--font-ui);
}

.route-loading__text {
  font-size: 12px;
  color: var(--text-3);
}

@keyframes route-loading {
  from { transform: scaleX(.35); opacity: .4; }
  50% { transform: scaleX(1); opacity: 1; }
  to { transform: scaleX(.35); opacity: .4; }
}

.page-enter-active, .page-leave-active { transition: opacity .18s, transform .18s; }
.page-enter-from { opacity: 0; transform: translateY(6px); }
.page-leave-to   { opacity: 0; transform: translateY(-4px); }

.page-header {
  padding: 28px 32px 20px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}

.page-title { font-size: 20px; font-weight: 700; letter-spacing: -.01em; }
.page-title small { font-size: 12px; font-weight: 400; color: var(--text-2); margin-left: 8px; font-family: var(--font-ui); }
.page-body { padding: 24px 32px; }

.btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: 1px solid var(--border-hi);
  border-radius: var(--radius);
  background: var(--bg-card);
  color: var(--text-1);
  font-size: 13px;
  cursor: pointer;
  transition: all .15s;
  font-family: var(--font-body);
  white-space: nowrap;
}

.btn:hover { background: var(--bg-hover); border-color: var(--accent); color: var(--accent); }
.btn--primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.btn--primary:hover { filter: brightness(1.15); color: #fff; }
.btn--danger { border-color: var(--red); color: var(--red); }
.btn--danger:hover { background: rgba(240,90,90,.12); }
.btn--sm { padding: 5px 10px; font-size: 12px; }
.btn:disabled { opacity: .4; cursor: not-allowed; pointer-events: none; }

.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.card-header {
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
  font-family: var(--font-ui);
  color: var(--text-2);
  letter-spacing: .05em;
  text-transform: uppercase;
}

.table { width: 100%; border-collapse: collapse; }
.table th, .table td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); }
.table th { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: .05em; font-family: var(--font-ui); font-weight: 500; }
.table td { font-size: 13px; }
.table tr:last-child td { border-bottom: none; }
.table tbody tr:hover td { background: var(--bg-hover); }

.tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-family: var(--font-ui);
  letter-spacing: .03em;
}

.tag--vip     { background: rgba(245,166,35,.15); color: var(--orange); }
.tag--free    { background: rgba(62,207,114,.1);  color: var(--green); }
.tag--ok      { background: rgba(62,207,114,.1);  color: var(--green); }
.tag--err     { background: rgba(240,90,90,.12);  color: var(--red); }
.tag--warn    { background: rgba(245,166,35,.12); color: var(--orange); }
.tag--info    { background: var(--accent-glow);   color: var(--accent); }
.tag--grey    { background: var(--bg-hover);      color: var(--text-2); }

.input {
  background: var(--bg-base);
  border: 1px solid var(--border-hi);
  border-radius: var(--radius);
  padding: 8px 12px;
  color: var(--text-1);
  font-size: 13px;
  font-family: var(--font-body);
  width: 100%;
  transition: border-color .15s;
  outline: none;
}

.input:focus { border-color: var(--accent); }

.select {
  appearance: none;
  background: var(--bg-base) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%238a96a8'/%3E%3C/svg%3E") no-repeat right 10px center;
  border: 1px solid var(--border-hi);
  border-radius: var(--radius);
  padding: 8px 32px 8px 12px;
  color: var(--text-1);
  font-size: 13px;
  cursor: pointer;
  outline: none;
}

.select:focus { border-color: var(--accent); }

.form-row { display: flex; flex-direction: column; gap: 6px; }
.form-row label { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: .05em; font-family: var(--font-ui); }

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-3);
  font-size: 13px;
}

.empty-state .empty-icon {
  font-size: 36px;
  margin-bottom: 12px;
  opacity: .4;
}
</style>
