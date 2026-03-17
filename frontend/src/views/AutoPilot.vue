<template>
  <div>
    <div class="page-header">
      <h1 class="page-title">
        自动驾驶
        <small>全程模拟真人，无需手动创建任务</small>
      </h1>
      <div class="header-right">
        <div class="tz-clock">
          <span class="tz-name">{{ status.current_tz_name || 'Asia/Shanghai' }}</span>
          <span class="tz-time">{{ status.current_tz_time || '--:--' }}</span>
          <span class="tz-badge" :class="status.is_active_hour ? 'tz-badge--active' : 'tz-badge--sleep'">
            {{ status.is_active_hour ? '活跃时段' : '非活跃时段' }}
          </span>
        </div>
        <span class="tag" :class="statusTag.cls">{{ statusTag.text }}</span>
      </div>
    </div>

    <div class="page-body ap-layout">

      <!-- ── 左列 ───────────────────────────────────────────── -->
      <div class="ap-left">

        <!-- 电源开关 -->
        <div class="card power-card">
          <button class="power-btn" :class="running ? 'power-btn--on' : 'power-btn--off'"
            :disabled="toggling" @click="togglePower">
            <span class="power-icon">⏻</span>
            <span class="power-label">{{ running ? '点击停止' : '一键启动' }}</span>
          </button>
          <div class="power-meta">
            <span class="power-mode" v-if="running && status.mode">
              当前: {{ status.mode === 'active' ? '活跃模式' : '非活跃模式' }}
            </span>
            <span class="power-hint">{{ running ? '正在运行，点击安全停止' : '点击启动全自动下载' }}</span>
          </div>
        </div>

        <!-- 今日统计 -->
        <div class="card">
          <div class="card-header">今日统计</div>
          <div class="stat-grid">
            <div class="stat-item">
              <div class="stat-num">{{ status.today?.sessions ?? 0 }}</div>
              <div class="stat-lbl">已完成会话</div>
            </div>
            <div class="stat-item">
              <div class="stat-num">{{ status.today?.downloaded ?? 0 }}</div>
              <div class="stat-lbl">已下载图片</div>
            </div>
            <div class="stat-item stat-item--wide">
              <div class="stat-num" :class="nextSessionClass">{{ nextSessionLabel }}</div>
              <div class="stat-lbl">下次会话</div>
            </div>
          </div>
        </div>

        <!-- 运行状态（运行中才展示） -->
        <div class="card phase-card" v-if="running">
          <div class="card-header">运行阶段</div>
          <div class="phase-body">
            <div class="phase-dot" :class="`phase-dot--${status.phase}`"></div>
            <div>
              <div class="phase-name">{{ phaseLabel }}</div>
              <div class="phase-sub" v-if="status.current_task_id">
                任务 <span class="mono">#{{ status.current_task_id }}</span>
                <a class="link" href="/tasks">查看任务列表</a>
              </div>
            </div>
          </div>
        </div>

        <!-- 时段可视化 -->
        <div class="card">
          <div class="card-header">24 小时时段视图</div>
          <div class="hour-bar-wrap">
            <div class="hour-bar">
              <div
                v-for="h in 24" :key="h-1"
                class="hour-cell"
                :class="hourCellClass(h - 1)"
                :title="`${String(h-1).padStart(2,'0')}:00`"
              >
                <span v-if="h-1 === currentHour" class="hour-now">▼</span>
              </div>
            </div>
            <div class="hour-labels">
              <span>0</span><span>6</span><span>12</span><span>18</span><span>24</span>
            </div>
            <div class="hour-legend">
              <span class="legend-dot legend-dot--active"></span>活跃
              <span class="legend-dot legend-dot--inactive" v-if="cfg.inactive_enabled"></span>
              <span v-if="cfg.inactive_enabled">非活跃(下载中)</span>
              <span class="legend-dot legend-dot--sleep"></span>休眠
              <span class="legend-dot legend-dot--now"></span>当前
            </div>
          </div>
        </div>

      </div>

      <!-- ── 右列 ───────────────────────────────────────────── -->
      <div class="ap-right">

        <!-- 配置面板 -->
        <div class="card">
          <div class="card-header">
            运行配置
            <span class="cfg-hint">{{ running ? '运行中可修改，下次会话生效' : '启动时将使用以下配置' }}</span>
          </div>

          <!-- 时区与时段 -->
          <div class="cfg-section">
            <div class="cfg-section-title">时区与活跃时段</div>
            <div class="cfg-grid-3">
              <div class="form-row">
                <label>时区</label>
                <select class="select" v-model="cfg.timezone" @change="onCfgChange">
                  <option v-for="tz in supportedTimezones" :key="tz" :value="tz">{{ tz }}</option>
                </select>
              </div>
              <div class="form-row">
                <label>活跃时段开始</label>
                <select class="select" v-model.number="cfg.active_start" @change="onCfgChange">
                  <option v-for="h in 24" :key="h-1" :value="h-1">{{ String(h-1).padStart(2,'0') }}:00</option>
                </select>
              </div>
              <div class="form-row">
                <label>活跃时段结束</label>
                <select class="select" v-model.number="cfg.active_end" @change="onCfgChange">
                  <option v-for="h in 24" :key="h-1" :value="h-1">{{ String(h-1).padStart(2,'0') }}:00</option>
                </select>
              </div>
            </div>
            <div class="time-desc">
              活跃时段：{{ String(cfg.active_start).padStart(2,'0') }}:00 — {{ String(cfg.active_end).padStart(2,'0') }}:00
              <span v-if="cfg.active_start > cfg.active_end" class="tag tag--warn" style="margin-left:8px;font-size:10px">跨午夜</span>
            </div>
          </div>

          <div class="cfg-divider"></div>

          <!-- 活跃时段模式 -->
          <div class="cfg-section">
            <div class="cfg-section-title mode-title mode-title--active">活跃时段模式</div>
            <div class="cfg-grid">
              <div class="form-row">
                <label>单次最少张数</label>
                <input class="input" type="number" min="1" max="200" v-model.number="cfg.active_session_min" @change="onCfgChange" />
              </div>
              <div class="form-row">
                <label>单次最多张数</label>
                <input class="input" type="number" min="1" max="200" v-model.number="cfg.active_session_max" @change="onCfgChange" />
              </div>
              <div class="form-row">
                <label>最短间隔（分钟）</label>
                <input class="input" type="number" min="1" v-model.number="activeIntervalMinMin" @change="onActiveIntervalChange" />
              </div>
              <div class="form-row">
                <label>最长间隔（分钟）</label>
                <input class="input" type="number" min="1" v-model.number="activeIntervalMaxMin" @change="onActiveIntervalChange" />
              </div>
            </div>
            <div class="mode-hint">每次下载 {{ cfg.active_session_min }}–{{ cfg.active_session_max }} 张，间隔 {{ activeIntervalMinMin }}–{{ activeIntervalMaxMin }} 分钟</div>
          </div>

          <div class="cfg-divider"></div>

          <!-- 非活跃时段模式 -->
          <div class="cfg-section">
            <div class="mode-title-row">
              <div class="cfg-section-title mode-title mode-title--inactive">非活跃时段模式</div>
              <label class="toggle">
                <input type="checkbox" v-model="cfg.inactive_enabled" @change="onCfgChange" />
                <span class="toggle-track"></span>
              </label>
              <span class="toggle-label">{{ cfg.inactive_enabled ? '启用（深夜继续下载）' : '关闭（深夜完全休眠）' }}</span>
            </div>
            <template v-if="cfg.inactive_enabled">
              <div class="cfg-grid" style="margin-top:12px">
                <div class="form-row">
                  <label>单次最少张数</label>
                  <input class="input" type="number" min="1" max="100" v-model.number="cfg.inactive_session_min" @change="onCfgChange" />
                </div>
                <div class="form-row">
                  <label>单次最多张数</label>
                  <input class="input" type="number" min="1" max="100" v-model.number="cfg.inactive_session_max" @change="onCfgChange" />
                </div>
                <div class="form-row">
                  <label>最短间隔（分钟）</label>
                  <input class="input" type="number" min="1" v-model.number="inactiveIntervalMinMin" @change="onInactiveIntervalChange" />
                </div>
                <div class="form-row">
                  <label>最长间隔（分钟）</label>
                  <input class="input" type="number" min="1" v-model.number="inactiveIntervalMaxMin" @change="onInactiveIntervalChange" />
                </div>
              </div>
              <div class="mode-hint mode-hint--inactive">每次下载 {{ cfg.inactive_session_min }}–{{ cfg.inactive_session_max }} 张，间隔 {{ inactiveIntervalMinMin }}–{{ inactiveIntervalMaxMin }} 分钟</div>
            </template>
          </div>

          <div class="cfg-divider"></div>

          <!-- 通用参数 -->
          <div class="cfg-section">
            <div class="cfg-section-title">下载参数</div>
            <div class="cfg-grid">
              <div class="form-row">
                <label>图片类型</label>
                <select class="select" v-model="cfg.wallpaper_type" @change="onCfgChange">
                  <option value="static">静态图</option>
                  <option value="dynamic">动态壁纸</option>
                  <option value="all">全部</option>
                </select>
              </div>
              <div class="form-row">
                <label>屏幕方向</label>
                <select class="select" v-model="cfg.screen_orientation" @change="onCfgChange">
                  <option value="all">全部</option>
                  <option value="landscape">横屏</option>
                  <option value="portrait">竖屏</option>
                </select>
              </div>
              <div class="form-row">
                <label>排序方式</label>
                <select class="select" v-model="cfg.sort_by" @change="onCfgChange">
                  <option value="yesterday_hot">昨日热门</option>
                  <option value="3days_hot">近三天热门</option>
                  <option value="7days_hot">近七天热门</option>
                  <option value="latest">最新上传</option>
                  <option value="most_views">最多浏览</option>
                </select>
              </div>
              <div class="form-row">
                <label>最低热度</label>
                <input class="input" type="number" min="0" v-model.number="cfg.min_hot_score" @change="onCfgChange" />
              </div>
            </div>

            <div class="toggle-list">
              <label class="toggle-row">
                <span class="toggle-row-label">仅限 VIP 账号</span>
                <label class="toggle">
                  <input type="checkbox" v-model="cfg.vip_only" @change="onCfgChange" />
                  <span class="toggle-track"></span>
                </label>
              </label>
              <label class="toggle-row">
                <span class="toggle-row-label">图床上传（下载后自动上传）</span>
                <label class="toggle">
                  <input type="checkbox" v-model="cfg.use_imgbed_upload" @change="onCfgChange" />
                  <span class="toggle-track"></span>
                </label>
              </label>
            </div>
          </div>

          <div class="cfg-footer">
            <button class="btn btn--primary btn--sm" @click="saveConfig">保存配置</button>
            <span v-if="savedHint" class="saved-hint">已保存</span>
          </div>
        </div>

        <!-- 运行日志 -->
        <div class="card">
          <div class="card-header">
            运行日志
            <button class="btn btn--sm" style="margin-left:auto" @click="logs = []">清空</button>
          </div>
          <div class="log-body" ref="logEl">
            <div v-if="logs.length === 0" class="log-empty">暂无日志，启动后将显示运行记录</div>
            <div v-for="(line, i) in logs" :key="i" class="log-line" :class="logLineClass(line)">{{ line }}</div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { autopilotApi } from '../api'

// ── 响应式状态 ─────────────────────────────────────────────────────────────

const status = ref({})
const running = computed(() => status.value.status === 'running')
const toggling = ref(false)
const logs = ref([])
const logEl = ref(null)
const savedHint = ref(false)
let savedHintTimer = null
let pollTimer = null
let configLoaded = false   // 首次加载标志，之后 poll 不再覆盖本地配置

// 支持时区列表（由后端返回，首次 poll 后填充）
const supportedTimezones = ref(['Asia/Shanghai'])

// 配置本地副本（绑定表单）
const cfg = ref({
  timezone: 'Asia/Shanghai',
  active_start: 8,
  active_end: 23,
  active_session_min: 5,
  active_session_max: 20,
  active_interval_min: 1800,
  active_interval_max: 7200,
  inactive_enabled: false,
  inactive_session_min: 2,
  inactive_session_max: 8,
  inactive_interval_min: 7200,
  inactive_interval_max: 14400,
  use_imgbed_upload: false,
  wallpaper_type: 'static',
  sort_by: 'yesterday_hot',
  categories: [],
  color_themes: [],
  vip_only: false,
  min_hot_score: 0,
  tag_blacklist: [],
  min_width: null,
  min_height: null,
  screen_orientation: 'all',
})

// 分钟显示值（interval 秒→分转换）
const activeIntervalMinMin = ref(30)
const activeIntervalMaxMin = ref(120)
const inactiveIntervalMinMin = ref(120)
const inactiveIntervalMaxMin = ref(240)

// 当前小时（用于时段可视化指针）
const currentHour = ref(new Date().getHours())

// ── 计算属性 ───────────────────────────────────────────────────────────────

const statusTag = computed(() => {
  if (!running.value) return { cls: 'tag--grey', text: 'IDLE' }
  const map = {
    session:     { cls: 'tag--ok',   text: 'SESSION' },
    waiting:     { cls: 'tag--info', text: 'WAITING' },
    sleeping:    { cls: 'tag--warn', text: 'SLEEPING' },
    daily_limit: { cls: 'tag--warn', text: 'DAILY LIMIT' },
    starting:    { cls: 'tag--info', text: 'STARTING' },
  }
  return map[status.value.phase] || { cls: 'tag--ok', text: 'RUNNING' }
})

const phaseLabel = computed(() => {
  const map = {
    session:     '正在执行下载会话',
    waiting:     '会话间等待中',
    sleeping:    '等待活跃时段开始',
    daily_limit: '今日配额已用完，等待明天',
    starting:    '初始化中...',
  }
  return map[status.value.phase] || '运行中'
})

const nextSessionLabel = computed(() => {
  if (!running.value) return '—'
  if (status.value.phase === 'session') return '进行中'
  if (!status.value.next_session_at) return '即将开始'
  const diff = Math.max(0, Math.floor((new Date(status.value.next_session_at) - Date.now()) / 1000))
  if (diff < 60)   return `${diff}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}min`
  return `${Math.floor(diff / 3600)}h ${Math.floor((diff % 3600) / 60)}min`
})

const nextSessionClass = computed(() =>
  status.value.phase === 'session' ? 'stat-num--active' : ''
)

// ── 时段可视化 ─────────────────────────────────────────────────────────────

function isHourActive(h) {
  const s = cfg.value.active_start, e = cfg.value.active_end
  return s <= e ? (h >= s && h < e) : (h >= s || h < e)
}

function isHourInactive(h) {
  return !isHourActive(h) && cfg.value.inactive_enabled
}

function hourCellClass(h) {
  if (h === currentHour.value) return 'hour-cell--now'
  if (isHourActive(h))         return 'hour-cell--active'
  if (isHourInactive(h))       return 'hour-cell--inactive'
  return 'hour-cell--sleep'
}

// ── 轮询 ─────────────────────────────────────────────────────────────────

async function poll() {
  try {
    const data = await autopilotApi.status()
    status.value = data

    if (data.supported_timezones?.length) {
      supportedTimezones.value = data.supported_timezones
    }

    // 仅首次加载时同步后端配置；之后 poll 不再覆盖，避免用户编辑被重置
    if (!configLoaded && data.config) {
      applyConfig(data.config)
      configLoaded = true
    }

    // 追加新日志行
    if (data.logs?.length > logs.value.length) {
      const newLines = data.logs.slice(logs.value.length)
      logs.value.push(...newLines)
      nextTick(scrollLogs)
    }

    currentHour.value = new Date().getHours()
  } catch {
    // 忽略轮询错误
  }
}

function applyConfig(remote) {
  Object.assign(cfg.value, remote)
  activeIntervalMinMin.value   = Math.round((remote.active_interval_min   ?? 1800)  / 60)
  activeIntervalMaxMin.value   = Math.round((remote.active_interval_max   ?? 7200)  / 60)
  inactiveIntervalMinMin.value = Math.round((remote.inactive_interval_min ?? 7200)  / 60)
  inactiveIntervalMaxMin.value = Math.round((remote.inactive_interval_max ?? 14400) / 60)
}

// ── 操作 ─────────────────────────────────────────────────────────────────

async function togglePower() {
  toggling.value = true
  try {
    if (running.value) {
      await autopilotApi.stop()
    } else {
      logs.value = []
      await autopilotApi.start(buildPayload())
    }
    await poll()
  } catch (e) {
    alert('操作失败: ' + (e.message || e))
  } finally {
    toggling.value = false
  }
}

async function saveConfig() {
  // 无论运行与否，都持久化到后端；停止状态下修改，启动时直接生效
  try {
    await autopilotApi.saveConfig(buildPayload())
    showSavedHint()
  } catch {
    // silent
  }
}

function onCfgChange() {
  saveConfig()
}

function onActiveIntervalChange() {
  cfg.value.active_interval_min = activeIntervalMinMin.value * 60
  cfg.value.active_interval_max = activeIntervalMaxMin.value * 60
  onCfgChange()
}

function onInactiveIntervalChange() {
  cfg.value.inactive_interval_min = inactiveIntervalMinMin.value * 60
  cfg.value.inactive_interval_max = inactiveIntervalMaxMin.value * 60
  onCfgChange()
}

function buildPayload() {
  return {
    ...cfg.value,
    active_interval_min:   activeIntervalMinMin.value * 60,
    active_interval_max:   activeIntervalMaxMin.value * 60,
    inactive_interval_min: inactiveIntervalMinMin.value * 60,
    inactive_interval_max: inactiveIntervalMaxMin.value * 60,
  }
}

function showSavedHint() {
  savedHint.value = true
  clearTimeout(savedHintTimer)
  savedHintTimer = setTimeout(() => { savedHint.value = false }, 2000)
}

// ── 日志 ─────────────────────────────────────────────────────────────────

function scrollLogs() {
  if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
}

function logLineClass(line) {
  if (line.includes('失败') || line.includes('异常') || line.includes('错误')) return 'log-err'
  if (line.includes('⚠') || line.includes('警告') || line.includes('上限'))   return 'log-warn'
  if (line.includes('完成') || line.includes('成功'))                           return 'log-ok'
  if (line.includes('[活跃]') || line.includes('会话') || line.includes('开始')) return 'log-accent'
  if (line.includes('[非活跃]'))                                                 return 'log-inactive'
  return ''
}

// ── 生命周期 ─────────────────────────────────────────────────────────────

onMounted(async () => {
  await poll()
  pollTimer = setInterval(poll, 3000)
})
onUnmounted(() => {
  clearInterval(pollTimer)
  clearTimeout(savedHintTimer)
})
</script>

<style scoped>
/* ── 布局 ────────────────────────────────────────── */
.ap-layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 20px;
  align-items: start;
}
.ap-left  { display: flex; flex-direction: column; gap: 16px; }
.ap-right { display: flex; flex-direction: column; gap: 16px; }

/* ── 页头右侧 ─────────────────────────────────────── */
.header-right { display: flex; align-items: center; gap: 12px; }

.tz-clock {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  font-family: var(--font-ui);
}
.tz-name { font-size: 11px; color: var(--text-3); }
.tz-time { font-size: 14px; color: var(--text-1); font-weight: 600; }
.tz-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  font-weight: 500;
}
.tz-badge--active { background: rgba(62,207,114,.15); color: var(--green); }
.tz-badge--sleep  { background: rgba(79,142,255,.12); color: var(--accent); }

/* ── 电源卡 ──────────────────────────────────────── */
.power-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 28px 20px 20px;
  gap: 14px;
}

.power-btn {
  width: 96px; height: 96px;
  border-radius: 50%;
  border: 3px solid var(--border-hi);
  background: var(--bg-base);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  transition: all .25s;
}
.power-btn--off:hover { border-color: var(--accent); background: var(--accent-glow); }
.power-btn--on {
  border-color: var(--green);
  background: rgba(62,207,114,.08);
  animation: pulse-power 2.2s ease-in-out infinite;
}
.power-btn:disabled { opacity: .45; cursor: not-allowed; animation: none; }

@keyframes pulse-power {
  0%, 100% { box-shadow: 0 0 0 0 rgba(62,207,114,.35); }
  50%       { box-shadow: 0 0 0 12px rgba(62,207,114,0); }
}

.power-icon { font-size: 28px; color: var(--text-2); transition: color .25s; }
.power-btn--on .power-icon { color: var(--green); }
.power-btn--off:hover .power-icon { color: var(--accent); }
.power-label { font-size: 11px; color: var(--text-3); font-family: var(--font-ui); }

.power-meta { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.power-mode { font-size: 12px; color: var(--green); font-family: var(--font-ui); }
.power-hint { font-size: 11px; color: var(--text-3); }

/* ── 统计 ─────────────────────────────────────────── */
.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--border);
}
.stat-item { padding: 14px 16px; background: var(--bg-card); text-align: center; }
.stat-item--wide { grid-column: span 2; }
.stat-num { font-size: 22px; font-family: var(--font-ui); font-weight: 600; }
.stat-num--active { color: var(--green); }
.stat-lbl { font-size: 11px; color: var(--text-3); margin-top: 3px; }

/* ── 阶段 ─────────────────────────────────────────── */
.phase-body { display: flex; align-items: center; gap: 12px; padding: 14px 18px; }
.phase-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.phase-dot--session     { background: var(--green);  box-shadow: 0 0 8px var(--green);  animation: blink 1.2s ease-in-out infinite; }
.phase-dot--waiting     { background: var(--accent); box-shadow: 0 0 6px var(--accent); }
.phase-dot--sleeping    { background: var(--orange); }
.phase-dot--daily_limit { background: var(--red); }
.phase-dot--starting    { background: var(--text-3); animation: blink .8s ease-in-out infinite; }

@keyframes blink { 0%,100% { opacity:1; } 50% { opacity:.25; } }

.phase-name { font-size: 13px; color: var(--text-1); }
.phase-sub  { font-size: 11px; color: var(--text-3); margin-top: 4px; }
.mono  { font-family: var(--font-ui); }
.link  { color: var(--accent); text-decoration: none; margin-left: 8px; }
.link:hover { text-decoration: underline; }

/* ── 时段可视化 ───────────────────────────────────── */
.hour-bar-wrap { padding: 14px 18px 10px; }
.hour-bar {
  display: grid;
  grid-template-columns: repeat(24, 1fr);
  gap: 2px;
  margin-bottom: 4px;
}
.hour-cell {
  height: 22px;
  border-radius: 2px;
  position: relative;
  cursor: default;
}
.hour-cell--active   { background: rgba(62,207,114,.35); }
.hour-cell--inactive { background: rgba(245,166,35,.25); }
.hour-cell--sleep    { background: var(--bg-hover); }
.hour-cell--now      { background: var(--accent); box-shadow: 0 0 6px var(--accent); }

.hour-now {
  position: absolute;
  bottom: -14px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 8px;
  color: var(--accent);
}

.hour-labels {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--text-3);
  font-family: var(--font-ui);
  margin-top: 16px;
  padding: 0 2px;
}

.hour-legend {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
  font-size: 11px;
  color: var(--text-3);
}
.legend-dot {
  width: 10px; height: 10px;
  border-radius: 2px;
  flex-shrink: 0;
}
.legend-dot--active   { background: rgba(62,207,114,.35); }
.legend-dot--inactive { background: rgba(245,166,35,.25); }
.legend-dot--sleep    { background: var(--bg-hover); border: 1px solid var(--border-hi); }
.legend-dot--now      { background: var(--accent); }

/* ── 配置面板 ────────────────────────────────────── */
.cfg-hint {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-3);
  text-transform: none;
  letter-spacing: 0;
}
.cfg-section { padding: 16px 18px; }
.cfg-section-title {
  font-size: 11px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: .05em;
  font-family: var(--font-ui);
  margin-bottom: 12px;
}
.cfg-divider { height: 1px; background: var(--border); }
.cfg-grid   { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.cfg-grid-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 14px; }

.time-desc { font-size: 11px; color: var(--text-3); margin-top: 10px; font-family: var(--font-ui); }

.mode-title { display: inline; }
.mode-title--active   { color: var(--green); }
.mode-title--inactive { color: var(--orange); }

.mode-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 0;
}

.mode-hint { font-size: 11px; color: var(--text-3); margin-top: 10px; font-family: var(--font-ui); }
.mode-hint--inactive { color: rgba(245,166,35,.7); }

/* 开关 */
.toggle { display: flex; align-items: center; cursor: pointer; flex-shrink: 0; }
.toggle input { display: none; }
.toggle-track {
  width: 36px; height: 20px;
  border-radius: 10px;
  background: var(--border-hi);
  position: relative;
  transition: background .2s;
}
.toggle-track::after {
  content: '';
  position: absolute;
  top: 3px; left: 3px;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: var(--text-3);
  transition: transform .2s, background .2s;
}
.toggle input:checked + .toggle-track { background: var(--accent); }
.toggle input:checked + .toggle-track::after { transform: translateX(16px); background: #fff; }
.toggle-label { font-size: 12px; color: var(--text-2); }

.toggle-list { margin-top: 14px; display: flex; flex-direction: column; gap: 10px; }
.toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.toggle-row-label { font-size: 13px; color: var(--text-1); }

.cfg-footer {
  padding: 12px 18px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 10px;
}
.saved-hint { font-size: 11px; color: var(--green); font-family: var(--font-ui); }

/* ── 日志 ────────────────────────────────────────── */
.log-body {
  height: 300px;
  overflow-y: auto;
  padding: 10px 16px;
  font-family: var(--font-ui);
  font-size: 12px;
  line-height: 1.75;
}
.log-empty { color: var(--text-3); text-align: center; padding: 40px 0; }
.log-line    { color: var(--text-2); }
.log-ok      { color: var(--green); }
.log-err     { color: var(--red); }
.log-warn    { color: var(--orange); }
.log-accent  { color: var(--accent); }
.log-inactive{ color: var(--orange); opacity: .8; }
</style>
