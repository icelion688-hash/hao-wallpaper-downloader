<template>
  <div>
    <!-- Toast 通知 -->
    <div v-if="toast" class="toast" :class="`toast--${toast.type}`">{{ toast.msg }}</div>

    <div class="page-header">
      <h1 class="page-title">任务中心 <small>{{ tasks.length }} 个任务</small></h1>
      <div class="header-actions">
        <button v-if="finishedCount > 0" class="btn btn--sm" @click="cleanupFinished"
          title="删除所有已完成 / 取消 / 失败的任务记录">
          清理已结束 ({{ finishedCount }})
        </button>
        <button class="btn btn--primary" @click="openCreate(null)">＋ 创建任务</button>
      </div>
    </div>

    <div class="page-body">

      <!-- 定时计划 -->
      <div class="card sched-card">
        <div class="sched-header" @click="scheduleExpanded = !scheduleExpanded">
          <span class="sched-title">⏰ 定时计划</span>
          <span class="sched-status" :class="schedule.enabled ? 'sched-status--on' : ''">
            {{ scheduleStatusText }}
          </span>
          <span class="sched-toggle">{{ scheduleExpanded ? '▲' : '▼' }}</span>
        </div>
        <div class="sched-body" v-if="scheduleExpanded">
          <div class="sched-row">
            <label class="check-label">
              <input type="checkbox" v-model="schedule.enabled" />
              启用定时任务
            </label>
            <div class="sched-time-row" v-if="schedule.enabled">
              <span class="sched-label">每天</span>
              <input class="input sched-time-input" type="time" v-model="schedule.time" />
              <span class="sched-label">自动运行</span>
            </div>
          </div>
          <div class="sched-hint" v-if="schedule.enabled">
            启用后，每天 <strong>{{ schedule.time }}</strong> 后端将自动用「筛选配置」页保存的预设创建并启动下载任务。<br />
            需保持后端程序持续运行（前端页面不需要打开）。
          </div>
          <div class="sched-actions">
            <button class="btn btn--sm" @click="saveSchedule" :disabled="scheduleSaving">
              {{ scheduleSaving ? '保存中…' : '保存定时设置' }}
            </button>
            <span class="sched-tip">定时任务将读取「筛选配置」页当前已保存的预设</span>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="tasks.length === 0" class="empty-state card" style="margin-top:14px">
        <div class="empty-icon">▶</div>
        <div>暂无任务，点击「创建任务」开始下载</div>
      </div>

      <!-- 任务列表 -->
      <div class="task-list" v-if="tasks.length > 0">
        <div class="card task-card" v-for="t in tasks" :key="t.id">

          <!-- 头部：ID + 名称（可内联编辑）+ 状态 + 生命周期操作 -->
          <div class="task-head">
            <span class="task-id">#{{ t.id }}</span>

            <input
              v-if="editingId === t.id"
              class="task-name-input"
              v-model="editingName"
              @blur="saveRename(t.id)"
              @keyup.enter="saveRename(t.id)"
              @keyup.escape="cancelRename"
              :ref="el => { if (el && editingId === t.id) nextTick(() => el.focus()) }"
            />
            <span v-else class="task-name" @click="startRename(t)" title="点击可重命名">
              {{ t.name }}
            </span>

            <span class="tag task-status-tag" :class="statusClass(t.status)">{{ statusLabel(t.status) }}</span>

            <div class="task-lifecycle">
              <button class="btn btn--sm btn--primary"
                v-if="['pending', 'paused'].includes(t.status)"
                @click="startTask(t.id)">▶ 启动</button>
              <button class="btn btn--sm"
                v-if="t.status === 'running'"
                @click="pauseTask(t.id)">⏸ 暂停</button>
              <button class="btn btn--sm btn--danger"
                v-if="t.status === 'running'"
                @click="cancelTask(t.id)">✕ 取消</button>
            </div>
          </div>

          <!-- 配置摘要 + 时间信息 -->
          <div class="task-meta">
            <div class="meta-tags">
              <span class="meta-tag" v-for="tag in configTags(t)" :key="tag">{{ tag }}</span>
            </div>
            <span class="task-time">{{ timeInfo(t) }}</span>
          </div>

          <!-- 进度条 -->
          <div class="progress-row">
            <div class="progress-bar">
              <div class="progress-fill"
                :style="{ width: t.progress + '%', background: progressColor(t.status) }">
              </div>
            </div>
            <span class="progress-label">{{ t.progress.toFixed(1) }}%</span>
          </div>

          <!-- 统计 + 工具按钮 -->
          <div class="task-footer">
            <div class="task-stats">
              <span class="tstat tstat--ok" title="成功下载">✓ {{ t.success_count }}</span>
              <span class="tstat tstat--err" title="失败">✗ {{ t.failed_count }}</span>
              <span class="tstat tstat--skip" title="跳过（已存在 / 不符合筛选）">⊘ {{ t.skip_count }}</span>
              <span class="tstat tstat--total">/ {{ t.total_count }}</span>
              <span v-if="t.error_msg" class="error-badge" :title="t.error_msg">
                ⚠ {{ t.error_msg.slice(0, 40) }}{{ t.error_msg.length > 40 ? '…' : '' }}
              </span>
            </div>
            <div class="task-util">
              <!-- 预留位：后续「上传图床」按钮插入此处 -->
              <button class="btn btn--sm"
                :class="{ 'btn--active': openLogId === t.id }"
                @click="toggleLogs(t.id)">
                {{ openLogId === t.id ? '收起日志' : '日志' }}
              </button>
              <button class="btn btn--sm" @click="openCreate(t)" title="复制此任务配置创建新任务">克隆</button>
              <button class="btn btn--sm btn--danger" @click="askDelete(t)">删除</button>
            </div>
          </div>

          <!-- 日志面板 -->
          <div class="log-panel" v-if="openLogId === t.id" :ref="el => setLogRef(t.id, el)">
            <div class="log-toolbar">
              <span class="log-count">{{ (taskLogs[t.id] || []).length }} 行</span>
              <button class="btn btn--sm" @click="copyLogs(t.id)">复制全部</button>
            </div>
            <div class="log-body">
              <div class="log-line" v-for="(line, i) in taskLogs[t.id] || []" :key="i">{{ line }}</div>
              <div class="log-empty" v-if="!(taskLogs[t.id]?.length)">等待日志输出…</div>
            </div>
          </div>

        </div>
      </div>
    </div>

    <!-- 创建 / 克隆任务弹窗 -->
    <div class="modal-overlay" v-if="showCreate" @click.self="showCreate = false">
      <div class="modal modal--wide">
        <div class="modal-header">
          <span>{{ cloneSource ? `克隆任务 #${cloneSource.id}` : '创建下载任务' }}</span>
          <button class="modal-close" @click="showCreate = false">✕</button>
        </div>
        <div class="modal-body">

          <!-- 基本信息 -->
          <div class="form-section">
            <div class="form-section-title">基本信息</div>
            <div class="form-grid2">
              <div class="form-row" style="grid-column:1/-1">
                <label>任务名称</label>
                <input class="input" v-model="form.name" placeholder="如：动漫-昨日热门-横屏" />
              </div>
              <div class="form-row">
                <label>排序方式</label>
                <select class="select" v-model="form.sort_by">
                  <option value="yesterday_hot">昨日热门</option>
                  <option value="3days_hot">近三天热门</option>
                  <option value="7days_hot">上周热门</option>
                  <option value="latest">最新</option>
                  <option value="most_views">推荐的</option>
                </select>
              </div>
              <div class="form-row">
                <label>下载数量上限</label>
                <input class="input" type="number" v-model.number="form.max_count" min="1" max="9999" />
              </div>
            </div>
          </div>

          <!-- 筛选条件 -->
          <div class="form-section">
            <div class="form-section-title">筛选条件</div>
            <div class="form-grid3">
              <div class="form-row">
                <label>壁纸类型</label>
                <select class="select" v-model="form.wallpaper_type">
                  <option value="all">全部</option>
                  <option value="static">静态</option>
                  <option value="dynamic">动态</option>
                </select>
              </div>
              <div class="form-row">
                <label>屏幕方向</label>
                <select class="select" v-model="form.screen_orientation">
                  <option value="all">全部</option>
                  <option value="landscape">电脑横屏</option>
                  <option value="portrait">手机竖屏</option>
                </select>
              </div>
              <div class="form-row">
                <label>最低热度分</label>
                <input class="input" type="number" v-model.number="form.min_hot_score" min="0" placeholder="0" />
              </div>
              <div class="form-row">
                <label>最低宽度 (px)</label>
                <input class="input" type="number" v-model.number="form.min_width" placeholder="不限" />
              </div>
              <div class="form-row">
                <label>最低高度 (px)</label>
                <input class="input" type="number" v-model.number="form.min_height" placeholder="不限" />
              </div>
              <div class="form-row">
                <label>并发数</label>
                <input class="input" type="number" v-model.number="form.concurrency" min="1" max="10" />
              </div>
              <div class="form-row" style="grid-column:1/-1">
                <label>分类筛选（点击多选）</label>
                <!-- 有 API 数据时显示芯片 -->
                <div class="meta-chips" v-if="metaCategories.length">
                  <span
                    v-for="cat in metaCategories" :key="cat.id"
                    class="meta-chip"
                    :class="{ 'meta-chip--on': selectedCatIds.has(cat.id) }"
                    @click="toggleCatId(cat.id)"
                  >{{ cat.name }}</span>
                </div>
                <!-- 无 API 数据时回退到文本输入 -->
                <input v-else class="input" v-model="categoriesStr" placeholder="anime, landscape, girl…" />
                <div class="meta-selected-hint" v-if="selectedCatIds.size > 0">
                  已选 {{ selectedCatIds.size }} 个分类
                </div>
              </div>
              <div class="form-row" style="grid-column:1/-1">
                <label>色系筛选（可选）</label>
                <div class="meta-chips" v-if="metaColors.length">
                  <span
                    v-for="c in metaColors" :key="c.id"
                    class="meta-chip meta-chip--color"
                    :class="{ 'meta-chip--on': selectedColorIds.has(c.id) }"
                    @click="toggleColorId(c.id)"
                  >
                    <span class="meta-color-dot" :style="{ background: c.hex || '#888' }"></span>
                    {{ c.name }}
                  </span>
                </div>
              </div>
              <div class="form-row" style="grid-column:1/-1">
                <label>黑名单标签（逗号分隔）</label>
                <input class="input" v-model="blacklistStr" placeholder="nsfw, blood…" />
              </div>
            </div>
          </div>

          <!-- 账号策略 -->
          <div class="form-section">
            <div class="form-section-title">账号策略</div>
            <div class="form-inline-checks">
              <label class="check-label">
                <input type="checkbox" v-model="form.vip_only" />
                仅使用 VIP 账号
              </label>
              <label class="check-label">
                <input type="checkbox" v-model="form.use_proxy" />
                启用代理
              </label>
              <label class="check-label">
                <input type="checkbox" v-model="form.use_imgbed_upload" />
                下载后自动上传到图床
              </label>
              <label class="check-label" v-if="form.use_imgbed_upload">
                <input type="checkbox" v-model="form.upload_with_tags" />
                上传时同步标签到图床
              </label>
            </div>
          </div>

        </div>
        <div class="modal-footer">
          <button class="btn" @click="showCreate = false">取消</button>
          <button class="btn" @click="submitCreate(false)" :disabled="creating">仅创建</button>
          <button class="btn btn--primary" @click="submitCreate(true)" :disabled="creating">
            {{ creating ? '创建中…' : '创建并启动' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 删除确认弹窗 -->
    <div class="modal-overlay" v-if="deleteTarget" @click.self="deleteTarget = null">
      <div class="modal modal--sm">
        <div class="modal-header">
          <span>删除任务</span>
          <button class="modal-close" @click="deleteTarget = null">✕</button>
        </div>
        <div class="modal-body">
          <p class="confirm-text">确认删除「<strong>{{ deleteTarget.name }}</strong>」？</p>
          <p class="confirm-hint">任务记录和日志将被永久清除，已下载的壁纸文件不受影响。</p>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="deleteTarget = null">取消</button>
          <button class="btn btn--danger" @click="doDelete">确认删除</button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { tasksApi, scheduleApi, galleryApi } from '../api'

const FILTER_KEY = 'hao_filter_preset'

// ── State ──────────────────────────────────────────────────────────
const tasks       = ref([])
const showCreate  = ref(false)
const cloneSource = ref(null)
const creating    = ref(false)
const openLogId   = ref(null)
const taskLogs    = ref({})
const logPanelRefs = {}   // { taskId: HTMLElement } — 规避 v-for 数组 ref 问题
const sseMap      = {}

const editingId   = ref(null)
const editingName = ref('')

const deleteTarget = ref(null)

const toast     = ref(null)
let   toastTimer = null

const categoriesStr = ref('')
const blacklistStr  = ref('')
const form = ref(defaultForm())

// 来自 API 的分类/色系元数据
const metaCategories = ref([])   // [{id, name, code}]
const metaColors     = ref([])   // [{id, name, hex}]
// 已选分类 UUID Set
const selectedCatIds = ref(new Set())
// 已选色系 UUID Set
const selectedColorIds = ref(new Set())

const schedule        = ref({ enabled: false, time: '09:00', task_config: {} })
const scheduleExpanded = ref(false)
const scheduleSaving   = ref(false)

let pollTimer = null

// ── Computed ───────────────────────────────────────────────────────
const finishedCount = computed(() =>
  tasks.value.filter(t => ['done', 'failed', 'cancelled'].includes(t.status)).length
)

const scheduleStatusText = computed(() =>
  schedule.value.enabled ? `每天 ${schedule.value.time} 自动运行` : '未启用'
)

// ── Helpers ────────────────────────────────────────────────────────
function defaultForm() {
  return {
    name: '新建任务',
    wallpaper_type: 'all',
    screen_orientation: 'all',
    sort_by: 'yesterday_hot',
    min_width: null,
    min_height: null,
    max_count: 100,
    concurrency: 3,
    min_hot_score: 0,
    vip_only: false,
    use_proxy: true,
    use_imgbed_upload: false,
    upload_with_tags: true,
  }
}

function showToast(type, msg, duration = 3500) {
  clearTimeout(toastTimer)
  toast.value = { type, msg }
  toastTimer = setTimeout(() => { toast.value = null }, duration)
}

const SORT_LABELS   = { yesterday_hot: '昨日热门', '3days_hot': '近三天', '7days_hot': '上周热门', latest: '最新', most_views: '推荐的' }
const TYPE_LABELS   = { static: '静态', dynamic: '动态' }
const ORIENT_LABELS = { landscape: '横屏', portrait: '竖屏' }

function configTags(t) {
  const cfg = t.config || {}
  const tags = []
  if (cfg.sort_by)             tags.push(SORT_LABELS[cfg.sort_by] || cfg.sort_by)
  if (cfg.wallpaper_type && cfg.wallpaper_type !== 'all')       tags.push(TYPE_LABELS[cfg.wallpaper_type] || cfg.wallpaper_type)
  if (cfg.screen_orientation && cfg.screen_orientation !== 'all') tags.push(ORIENT_LABELS[cfg.screen_orientation] || cfg.screen_orientation)
  if (cfg.max_count)           tags.push(`${cfg.max_count}张`)
  if (cfg.min_hot_score > 0)  tags.push(`热度≥${cfg.min_hot_score}`)
  if (cfg.categories?.length) tags.push(cfg.categories.slice(0, 2).join(' · '))
  if (cfg.min_width)          tags.push(`宽≥${cfg.min_width}`)
  if (cfg.use_imgbed_upload === false) tags.push('仅本地保存')
  if (cfg.use_imgbed_upload !== false && cfg.upload_with_tags === false) tags.push('上传不带标签')
  return tags
}

function fmtDuration(secs) {
  if (secs < 60)   return `${secs}秒`
  const m = Math.floor(secs / 60), s = secs % 60
  if (m < 60)      return s ? `${m}分${s}秒` : `${m}分钟`
  const h = Math.floor(m / 60)
  return `${h}时${m % 60}分`
}

function fmtRelative(dateStr) {
  if (!dateStr) return ''
  const diff = Math.floor((Date.now() - new Date(dateStr)) / 1000)
  if (diff < 60)   return `${diff}秒前`
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  return `${Math.floor(diff / 86400)}天前`
}

function timeInfo(t) {
  if (t.status === 'running' && t.started_at) {
    const elapsed = Math.floor((Date.now() - new Date(t.started_at)) / 1000)
    return `运行 ${fmtDuration(elapsed)}`
  }
  if (t.finished_at && t.started_at) {
    const dur = Math.floor((new Date(t.finished_at) - new Date(t.started_at)) / 1000)
    return `耗时 ${fmtDuration(dur)}`
  }
  if (t.created_at) return `创建 ${fmtRelative(t.created_at)}`
  return ''
}

function statusClass(s) {
  return { running: 'tag--info', done: 'tag--ok', failed: 'tag--err', paused: 'tag--warn', cancelled: 'tag--grey', pending: 'tag--grey' }[s] || 'tag--grey'
}
function statusLabel(s) {
  return { running: '运行中', done: '已完成', failed: '失败', paused: '已暂停', cancelled: '已取消', pending: '待启动' }[s] || s
}
function progressColor(s) {
  return s === 'done' ? 'var(--green)' : s === 'failed' ? 'var(--red)' : 'var(--accent)'
}

// ── Task CRUD ──────────────────────────────────────────────────────
async function loadTasks() {
  try {
    const res = await tasksApi.list()
    tasks.value = res.tasks
  } catch {}
}

async function startTask(id) {
  try {
    await tasksApi.start(id)
    await loadTasks()
    openLogId.value = id
    connectSSE(id)
  } catch (e) {
    showToast('err', `启动失败: ${e.message}`)
  }
}

async function pauseTask(id) {
  await tasksApi.pause(id)
  disconnectSSE(id)
  await loadTasks()
}

async function cancelTask(id) {
  await tasksApi.cancel(id)
  disconnectSSE(id)
  await loadTasks()
}

function askDelete(task) {
  deleteTarget.value = task
}

async function doDelete() {
  const id = deleteTarget.value?.id
  if (!id) return
  deleteTarget.value = null
  disconnectSSE(id)
  await tasksApi.delete(id)
  await loadTasks()
  showToast('ok', '任务已删除')
}

async function cleanupFinished() {
  const finished = tasks.value.filter(t => ['done', 'failed', 'cancelled'].includes(t.status))
  if (!finished.length) return
  for (const t of finished) {
    disconnectSSE(t.id)
    try { await tasksApi.delete(t.id) } catch {}
  }
  await loadTasks()
  showToast('ok', `已清理 ${finished.length} 个已结束任务`)
}

// ── Rename（内联编辑）──────────────────────────────────────────────
function startRename(task) {
  editingId.value   = task.id
  editingName.value = task.name
}

async function saveRename(id) {
  const name = editingName.value.trim()
  const old  = tasks.value.find(t => t.id === id)?.name
  editingId.value = null
  if (!name || name === old) return
  try {
    await tasksApi.rename(id, name)
    await loadTasks()
    showToast('ok', '重命名成功')
  } catch (e) {
    showToast('err', `重命名失败: ${e.message}`)
  }
}

function cancelRename() {
  editingId.value   = null
  editingName.value = ''
}

// ── Create / Clone ─────────────────────────────────────────────────
function openCreate(sourceTask) {
  cloneSource.value = sourceTask
  if (sourceTask) {
    const cfg = sourceTask.config || {}
    form.value = {
      name:               `${sourceTask.name} (副本)`,
      wallpaper_type:     cfg.wallpaper_type     || 'all',
      screen_orientation: cfg.screen_orientation || 'all',
      sort_by:            cfg.sort_by            || 'yesterday_hot',
      min_width:          cfg.min_width          || null,
      min_height:         cfg.min_height         || null,
      max_count:          cfg.max_count          || 100,
      concurrency:        cfg.concurrency        || 3,
      min_hot_score:      cfg.min_hot_score      || 0,
      vip_only:           cfg.vip_only           || false,
      use_proxy:          cfg.use_proxy !== false,
      use_imgbed_upload:  cfg.use_imgbed_upload !== false,
      upload_with_tags:   cfg.upload_with_tags !== false,
    }
    categoriesStr.value = (cfg.categories   || []).join(', ')
    blacklistStr.value  = (cfg.tag_blacklist || []).join(', ')
  } else {
    try {
      const saved = localStorage.getItem(FILTER_KEY)
      if (saved) {
        const p = JSON.parse(saved)
        form.value = {
          name:               '新建任务',
          wallpaper_type:     p.wallpaper_type     || 'all',
          screen_orientation: p.screen_orientation || 'all',
          sort_by:            p.sort_by            || 'yesterday_hot',
          min_width:          p.min_width          || null,
          min_height:         p.min_height         || null,
          max_count:          p.max_count          || 100,
          concurrency:        p.concurrency        || 3,
          min_hot_score:      p.min_hot_score      || 0,
          vip_only:           p.vip_only           || false,
          use_proxy:          p.use_proxy !== false,
          use_imgbed_upload:  p.use_imgbed_upload === true,
          upload_with_tags:   p.upload_with_tags !== false,
        }
        const savedCats = p.categories || []
        const isUuid = savedCats.length > 0 && savedCats[0].length === 32 && /^[0-9a-f]+$/.test(savedCats[0])
        if (isUuid) {
          selectedCatIds.value = new Set(savedCats)
          categoriesStr.value  = ''
        } else {
          categoriesStr.value  = savedCats.join(', ')
          selectedCatIds.value = new Set()
        }
        const savedColors = p.color_themes || []
        const isColorUuid = savedColors.length > 0 && savedColors[0].length === 32 && /^[0-9a-f]+$/.test(savedColors[0])
        selectedColorIds.value = isColorUuid ? new Set(savedColors) : new Set()
        blacklistStr.value     = (p.tag_blacklist || []).join(', ')
      } else {
        form.value = defaultForm()
        categoriesStr.value    = ''
        blacklistStr.value     = ''
        selectedCatIds.value   = new Set()
        selectedColorIds.value = new Set()
      }
    } catch {
      form.value = defaultForm()
      categoriesStr.value    = ''
      blacklistStr.value     = ''
      selectedCatIds.value   = new Set()
      selectedColorIds.value = new Set()
    }
  }
  showCreate.value = true
}

async function submitCreate(autoStart) {
  creating.value = true
  try {
    // 分类：优先使用 UUID（新格式），回退到字符串（旧格式）
    const uuidCats = [...selectedCatIds.value]
    const strCats  = categoriesStr.value ? categoriesStr.value.split(',').map(s => s.trim()).filter(Boolean) : []
    const colorIds = [...selectedColorIds.value]
    const payload = {
      ...form.value,
      categories:    uuidCats.length ? uuidCats : strCats,
      color_themes:  colorIds,
      tag_blacklist: blacklistStr.value ? blacklistStr.value.split(',').map(s => s.trim()).filter(Boolean) : [],
    }
    const res = await tasksApi.create(payload)
    showCreate.value = false
    await loadTasks()
    if (autoStart) {
      await startTask(res.task.id)
    } else {
      showToast('ok', `任务「${res.task.name}」已创建，可手动启动`)
    }
  } catch (e) {
    showToast('err', `创建失败: ${e.message}`)
  } finally {
    creating.value = false
  }
}

// ── Schedule ───────────────────────────────────────────────────────
async function loadSchedule() {
  try { schedule.value = await scheduleApi.get() } catch {}
}

async function saveSchedule() {
  scheduleSaving.value = true
  try {
    const preset = (() => {
      try { return JSON.parse(localStorage.getItem(FILTER_KEY) || '{}') } catch { return {} }
    })()
    const payload = { ...schedule.value, task_config: { ...preset } }
    await scheduleApi.set(payload)
    schedule.value = payload
    showToast('ok', '定时设置已保存')
  } finally {
    scheduleSaving.value = false
  }
}

// ── Logs ───────────────────────────────────────────────────────────
function setLogRef(id, el) {
  if (el) logPanelRefs[id] = el
  else    delete logPanelRefs[id]
}

function toggleLogs(id) {
  if (openLogId.value === id) {
    openLogId.value = null
  } else {
    openLogId.value = id
    if (!taskLogs.value[id]) taskLogs.value[id] = []
    const t = tasks.value.find(x => x.id === id)
    if (t?.status === 'running' && !sseMap[id]) connectSSE(id)
  }
}

function connectSSE(taskId) {
  if (sseMap[taskId]) return
  const es = tasksApi.streamLogs(taskId)
  sseMap[taskId] = es

  es.onmessage = (e) => {
    const data = JSON.parse(e.data)
    if (data.log) {
      if (!taskLogs.value[taskId]) taskLogs.value[taskId] = []
      taskLogs.value[taskId].push(data.log)
      if (taskLogs.value[taskId].length > 300) taskLogs.value[taskId].shift()
      nextTick(() => {
        const panel = logPanelRefs[taskId]
        const body  = panel?.querySelector('.log-body')
        if (body) body.scrollTop = body.scrollHeight
      })
    }
    if (data.done) {
      disconnectSSE(taskId)
      loadTasks()
    }
  }
  es.onerror = () => disconnectSSE(taskId)
}

function disconnectSSE(taskId) {
  if (sseMap[taskId]) { sseMap[taskId].close(); delete sseMap[taskId] }
}

async function copyLogs(id) {
  const lines = taskLogs.value[id] || []
  try {
    await navigator.clipboard.writeText(lines.join('\n'))
    showToast('ok', '日志已复制到剪贴板')
  } catch {
    showToast('warn', '复制失败，请手动选择文本')
  }
}

// ── Keyboard ───────────────────────────────────────────────────────
function onKeyDown(e) {
  if (e.key !== 'Escape') return
  if (deleteTarget.value)  { deleteTarget.value = null; return }
  if (showCreate.value)    { showCreate.value = false;  return }
  if (editingId.value)     cancelRename()
}

async function loadMeta() {
  try {
    const res = await galleryApi.wallpaperMeta()
    metaCategories.value = res.categories || []
    metaColors.value     = res.colors     || []
  } catch { /* 静默失败 */ }
}

function toggleCatId(id) {
  const s = new Set(selectedCatIds.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedCatIds.value = s
}

function toggleColorId(id) {
  const s = new Set(selectedColorIds.value)
  if (s.has(id)) s.delete(id)
  else s.add(id)
  selectedColorIds.value = s
}

// ── Lifecycle ──────────────────────────────────────────────────────
onMounted(async () => {
  await loadTasks()
  await loadSchedule()
  await loadMeta()
  // 页面刷新后自动重连运行中任务的 SSE
  tasks.value.filter(t => t.status === 'running').forEach(t => connectSSE(t.id))
  pollTimer = setInterval(loadTasks, 3000)
  window.addEventListener('keydown', onKeyDown)
})

onUnmounted(() => {
  clearInterval(pollTimer)
  clearTimeout(toastTimer)
  Object.keys(sseMap).forEach(id => disconnectSSE(Number(id)))
  window.removeEventListener('keydown', onKeyDown)
})
</script>

<style scoped>
/* ── 页面头部 ─────────────────────────────────────── */
.header-actions { display: flex; gap: 8px; align-items: center; }


/* ── 任务列表 ─────────────────────────────────────── */
.task-list { display: flex; flex-direction: column; gap: 12px; margin-top: 14px; }

.task-card { padding: 0; }

/* 头部行 */
.task-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px 10px;
  flex-wrap: wrap;
}

.task-id {
  font-family: var(--font-ui);
  font-size: 11px;
  color: var(--text-3);
  min-width: 28px;
  flex-shrink: 0;
}

.task-name {
  font-weight: 600;
  font-size: 14px;
  flex: 1;
  cursor: text;
  border-radius: 3px;
  padding: 2px 4px;
  margin: -2px -4px;
  transition: background .15s;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-name:hover { background: var(--bg-hover); color: var(--accent); }

.task-name-input {
  flex: 1;
  background: var(--bg-base);
  border: 1px solid var(--accent);
  border-radius: var(--radius);
  padding: 3px 8px;
  color: var(--text-1);
  font-size: 14px;
  font-weight: 600;
  font-family: var(--font-body);
  outline: none;
}

.task-status-tag { flex-shrink: 0; }

.task-lifecycle { display: flex; gap: 6px; flex-shrink: 0; margin-left: auto; }

/* 配置摘要行 */
.task-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 18px 10px;
  gap: 10px;
  flex-wrap: wrap;
}

.meta-tags { display: flex; gap: 6px; flex-wrap: wrap; }

.meta-tag {
  font-family: var(--font-ui);
  font-size: 10px;
  color: var(--text-3);
  background: var(--bg-base);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 1px 6px;
  letter-spacing: .03em;
}

.task-time {
  font-family: var(--font-ui);
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  flex-shrink: 0;
}

/* 进度行 */
.progress-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 18px 10px;
}
.progress-bar { flex: 1; height: 3px; background: var(--bg-base); border-radius: 2px; overflow: hidden; }
.progress-fill { height: 100%; border-radius: 2px; transition: width .4s ease; }
.progress-label { font-size: 11px; width: 40px; text-align: right; color: var(--text-3); font-family: var(--font-ui); }

/* 底部行：统计 + 工具按钮 */
.task-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 18px 14px;
  gap: 10px;
  border-top: 1px solid var(--border);
}

.task-stats { display: flex; gap: 12px; align-items: center; font-size: 12px; font-family: var(--font-ui); flex-wrap: wrap; }
.tstat--ok    { color: var(--green); }
.tstat--err   { color: var(--red); }
.tstat--skip  { color: var(--text-3); }
.tstat--total { color: var(--text-3); }

.error-badge {
  font-size: 11px;
  color: var(--orange);
  background: rgba(245,166,35,.1);
  border: 1px solid rgba(245,166,35,.2);
  border-radius: 3px;
  padding: 1px 6px;
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-util { display: flex; gap: 6px; flex-shrink: 0; }

.btn--active { border-color: var(--accent); color: var(--accent); background: var(--accent-glow); }

/* 日志面板 */
.log-panel {
  margin: 0 18px 14px;
  background: var(--bg-base);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.log-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  border-bottom: 1px solid var(--border);
}
.log-count { font-size: 11px; color: var(--text-3); font-family: var(--font-ui); }

.log-body {
  height: 220px;
  overflow-y: auto;
  padding: 8px 12px;
  font-family: var(--font-ui);
  font-size: 11px;
  line-height: 1.7;
}
.log-line { color: var(--text-2); white-space: pre-wrap; word-break: break-all; }
.log-line:last-child { color: var(--text-1); }
.log-empty { color: var(--text-3); font-style: italic; }

/* ── 定时计划 ─────────────────────────────────────── */
.sched-card { margin-bottom: 0; }
.sched-header {
  display: flex; align-items: center; gap: 10px;
  padding: 12px 16px; cursor: pointer; user-select: none;
  transition: background .15s;
}
.sched-header:hover { background: var(--bg-base); }
.sched-title  { font-weight: 600; font-size: 13px; }
.sched-status { font-size: 12px; color: var(--text-3); font-family: var(--font-ui); }
.sched-status--on { color: var(--green); }
.sched-toggle { margin-left: auto; font-size: 11px; color: var(--text-3); }
.sched-body   { padding: 14px 16px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 12px; }
.sched-row    { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.sched-time-row { display: flex; align-items: center; gap: 8px; }
.sched-label  { font-size: 12px; color: var(--text-2); }
.sched-time-input { width: 110px; }
.check-label  { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; }
.check-label input { accent-color: var(--accent); }
.sched-hint   { font-size: 12px; color: var(--text-2); line-height: 1.7; background: var(--bg-base); padding: 10px 12px; border-radius: var(--radius); }
.sched-hint strong { color: var(--accent); }
.sched-actions { display: flex; align-items: center; gap: 12px; }
.sched-tip    { font-size: 11px; color: var(--text-3); }

/* ── 弹窗 ─────────────────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.65);
  display: flex; align-items: center; justify-content: center;
  z-index: 200;
  backdrop-filter: blur(2px);
}

.modal {
  background: var(--bg-panel);
  border: 1px solid var(--border-hi);
  border-radius: var(--radius);
  max-width: 90vw;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
}
.modal--wide { width: 680px; }
.modal--sm   { width: 420px; }

.modal-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border);
  font-weight: 600;
  font-size: 14px;
  flex-shrink: 0;
}

.modal-close {
  background: none; border: none; color: var(--text-3);
  cursor: pointer; font-size: 14px; padding: 2px 6px;
  border-radius: 3px; transition: all .15s;
}
.modal-close:hover { color: var(--text-1); background: var(--bg-hover); }

.modal-body   { padding: 20px; overflow-y: auto; flex: 1; }
.modal-footer {
  padding: 14px 20px;
  border-top: 1px solid var(--border);
  display: flex; justify-content: flex-end; gap: 8px;
  flex-shrink: 0;
}

/* 表单分节 */
.form-section { margin-bottom: 20px; }
.form-section:last-child { margin-bottom: 0; }
.form-section-title {
  font-size: 11px;
  font-family: var(--font-ui);
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: .06em;
  margin-bottom: 12px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}

.form-grid2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 14px; }
.form-grid3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }

.form-inline-checks { display: flex; gap: 20px; flex-wrap: wrap; }

/* 删除确认 */
.confirm-text { font-size: 14px; margin-bottom: 8px; }
.confirm-text strong { color: var(--text-1); }
.confirm-hint { font-size: 12px; color: var(--text-3); line-height: 1.6; }

/* ── Toast ────────────────────────────────────────── */
.toast {
  position: fixed;
  bottom: 28px; right: 28px;
  background: var(--bg-panel);
  border: 1px solid var(--border-hi);
  border-radius: var(--radius);
  padding: 10px 16px;
  font-size: 13px;
  z-index: 999;
  max-width: 380px;
  animation: toast-in .2s ease;
  border-left: 3px solid var(--border-hi);
}
.toast--ok   { border-left-color: var(--green); }
.toast--err  { border-left-color: var(--red); }
.toast--warn { border-left-color: var(--orange); }

@keyframes toast-in {
  from { opacity: 0; transform: translateY(8px); }
  to   { opacity: 1; transform: translateY(0); }
}

/* ── 分类/色系多选芯片 ────────────────────────── */
.meta-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.meta-chip {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 12px;
  border: 1px solid var(--border);
  cursor: pointer;
  transition: all .15s;
  color: var(--text-2);
  background: var(--bg-base);
  user-select: none;
}

.meta-chip:hover { border-color: var(--accent); color: var(--accent); }

.meta-chip--on {
  background: var(--accent-glow);
  border-color: var(--accent);
  color: var(--accent);
}

.meta-chip--color { display: inline-flex; align-items: center; gap: 5px; }

.meta-color-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 1px solid rgba(255,255,255,.2);
  flex-shrink: 0;
}

.meta-selected-hint {
  font-size: 10px;
  color: var(--accent);
  margin-top: 6px;
  font-family: var(--font-ui);
}

@media (max-width: 900px) {
  .form-grid2,
  .form-grid3 {
    grid-template-columns: 1fr;
  }

  .task-lifecycle {
    width: 100%;
    margin-left: 0;
  }
}
</style>
