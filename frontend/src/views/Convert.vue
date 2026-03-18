<template>
  <div>
    <div class="page-header">
      <h1 class="page-title">格式转换 <small>静态图 → WebP / JPG / PNG</small></h1>
      <div class="header-actions">
        <button class="btn" @click="applyRecommend" :disabled="!sysInfo || applyingRecommend" title="根据当前机器配置一键填入建议值并保存">
          {{ applyingRecommend ? '应用中…' : '一键推荐配置' }}
        </button>
        <button class="btn btn--primary" @click="saveSettings" :disabled="saving">
          {{ saving ? '保存中…' : '保存配置' }}
        </button>
      </div>
    </div>

    <div class="page-body">

      <!-- 机器资源卡片 -->
      <div class="sys-card" :class="`sys-card--${sysInfo?.tier || 'mid'}`">
        <div class="sys-card__left">
          <div class="sys-tier-badge" :class="`tier--${sysInfo?.tier || 'mid'}`">
            {{ TIER_LABEL[sysInfo?.tier] || '检测中…' }}
          </div>
          <div class="sys-metrics" v-if="sysInfo">
            <span class="sys-metric"><span class="sys-metric__label">可用内存</span><strong>{{ sysInfo.available_memory_mb }} MB</strong></span>
            <span class="sys-metric"><span class="sys-metric__label">CPU 核心</span><strong>{{ sysInfo.cpu_count }}</strong></span>
          </div>
          <div class="sys-metrics" v-else>
            <span class="sys-metric sys-loading">正在检测服务器资源…</span>
          </div>
        </div>
        <div class="sys-card__right" v-if="sysInfo">
          <div class="sys-recommend-label">自动推荐</div>
          <div class="sys-recommend-values">
            <span>max_frames: <strong>{{ sysInfo.recommend.max_frames }}</strong></span>
            <span>max_width: <strong>{{ sysInfo.recommend.max_width }}px</strong></span>
            <span>fps: <strong>{{ sysInfo.recommend.fps }}</strong></span>
          </div>
          <div class="sys-note" v-if="sysInfo.tier === 'low'">
            低配机建议保守配置，超时或崩溃时先降低 max_frames 和 max_width
          </div>
        </div>
      </div>

      <!-- 说明提示 -->
      <div class="notice-card">
        <div class="notice-icon">ℹ</div>
        <div>
          当前版本仅保留静态图格式转换。
          为了适配小型服务器并降低 CPU 压力，动态图转换入口已关闭。
          静态图转换仅需 Pillow（已内置），支持 WebP / JPG / PNG。
        </div>
      </div>

      <!-- 全局 + 性能控制 -->
      <div class="card">
        <div class="card-header">全局控制 &amp; 性能保护</div>
        <div class="card-body">
          <div class="perf-grid">
            <label class="toggle-row">
              <input type="checkbox" v-model="form.auto_convert" />
              <div>
                <div class="toggle-label">下载时自动转换</div>
                <div class="toggle-sub">下载完成后立即后台转换静态图，适合低并发小机器</div>
              </div>
            </label>
            <div class="form-row">
              <label>最大并发数 <span class="form-hint">同时运行的转换任务数，低配建议 1</span></label>
              <div class="input-row">
                <input class="input" type="number" v-model.number="form.max_concurrent" min="1" max="4" />
                <span class="unit">个</span>
              </div>
            </div>
            <div class="form-row">
              <label>图片超时</label>
              <div class="input-row">
                <input class="input" type="number" v-model.number="form.image.timeout_seconds" min="10" max="600" />
                <span class="unit">秒</span>
              </div>
            </div>
            <div class="form-row">
              <label>CPU 降权（图片）</label>
              <div class="nice-row">
                <input type="range" class="range" v-model.number="form.image.cpu_nice" min="0" max="19" />
                <span class="quality-val font-mono">{{ NICE_LABEL[form.image.cpu_nice] || form.image.cpu_nice }}</span>
              </div>
            </div>
            <div class="form-row">
              <label>动态图转换</label>
              <div class="input-row">
                <span class="unit">已关闭，仅保留静态图转换</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="two-col">
        <div class="card">
          <div class="card-header">动态图转换</div>
          <div class="card-body">
            <div class="inline-note">已关闭动态图转换，仅保留静态图格式转换与原始文件保存。</div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <span>静态图 &nbsp;PNG / JPG → WebP / JPG / PNG</span>
            <label class="inline-toggle">
              <input type="checkbox" v-model="form.image.enabled" />
              <span>{{ form.image.enabled ? '已启用' : '已禁用' }}</span>
            </label>
          </div>
          <div class="card-body" :class="{ 'cfg-disabled': !form.image.enabled }">
            <div class="form-grid">
              <div class="form-row">
                <label>输出格式</label>
                <select class="select" v-model="form.image.output_format">
                  <option value="webp">WebP（推荐，体积最小）</option>
                  <option value="jpg">JPEG</option>
                  <option value="png">PNG（无损）</option>
                </select>
              </div>
              <div class="form-row">
                <label>质量 <span class="form-hint">WebP / JPEG 生效</span></label>
                <div class="quality-row">
                  <input type="range" class="range" v-model.number="form.image.quality" min="1" max="100" />
                  <span class="quality-val font-mono">{{ form.image.quality }}</span>
                </div>
              </div>
              <div class="form-row">
                <label class="toggle-row toggle-row--inline">
                  <input type="checkbox" v-model="form.image.delete_original" />
                  <div>
                    <div class="toggle-label">转换后删除原文件</div>
                    <div class="toggle-sub">⚠ 不可恢复，请先确认质量满意</div>
                  </div>
                </label>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 批量转换 -->
      <div class="card">
        <div class="card-header">批量转换</div>
        <div class="card-body">
          <div class="batch-toolbar">
            <div class="form-row">
              <label>转换范围</label>
              <select class="select" v-model="batchScope">
                <option value="static">全部静态图片</option>
              </select>
            </div>
            <div class="form-row">
              <label>覆盖输出格式 <span class="form-hint">留空=使用配置</span></label>
              <select class="select" v-model="batchFormat">
                <option value="">使用配置默认值</option>
                <option value="webp">WebP</option>
                <option value="jpg">JPEG（仅图片）</option>
                <option value="png">PNG（仅图片）</option>
              </select>
            </div>
            <div class="form-row">
              <label class="toggle-row toggle-row--inline">
                <input type="checkbox" v-model="batchDeleteOriginal" />
                <div>
                  <div class="toggle-label">覆盖：转换后删除原文件</div>
                  <div class="toggle-sub">不勾选则沿用各自配置中的设置</div>
                </div>
              </label>
            </div>
          </div>
          <div class="batch-actions">
            <button class="btn btn--primary" @click="startBatchConvert" :disabled="converting">
              {{ converting ? '提交中…' : '开始批量转换' }}
            </button>
            <button class="btn" @click="refreshQueueStatus" title="刷新队列状态">刷新队列</button>
          </div>

          <!-- 当前批次进度 -->
          <div v-if="batchJob" class="batch-progress">
            <div class="batch-progress__header">
              <span class="batch-id">批次 {{ batchJob.batch_id }}</span>
              <span class="batch-status-badge" :class="batchJob.is_complete ? 'badge--done' : 'badge--running'">
                {{ batchJob.is_complete ? '已完成' : '转换中…' }}
              </span>
            </div>
            <div class="batch-progress__bar-wrap">
              <div class="batch-progress__bar" :style="{ width: batchProgressPct + '%' }"></div>
            </div>
            <div class="batch-progress__stats">
              <span class="result-ok">✓ {{ batchJob.success }}</span>
              <span class="result-skip">跳过 {{ batchJob.skipped }}</span>
              <span v-if="batchJob.failed" class="result-fail">✗ {{ batchJob.failed }}</span>
              <span class="result-total">/ {{ batchJob.total }} 张</span>
              <span class="result-total" style="margin-left:8px">{{ batchJob.done }}/{{ batchJob.total }} 完成</span>
            </div>
            <div v-if="batchJob.failed_items?.length" class="failed-list">
              <div class="failed-list__title">失败项目：</div>
              <div v-for="item in batchJob.failed_items" :key="item.id" class="failed-item">
                ID {{ item.id }} — {{ item.reason }}
              </div>
            </div>
          </div>

          <!-- 全局队列概览 -->
          <div v-if="queueStatus" class="queue-overview">
            <div class="queue-overview__title">队列概览</div>
            <div class="queue-overview__stats">
              <span>等待中：<strong>{{ queueStatus.queue_size }}</strong></span>
              <span v-if="queueStatus.running">
                正在转换：<strong>ID {{ queueStatus.running.wallpaper_id }}</strong>
                ({{ queueStatus.running.wallpaper_type }})
              </span>
              <span v-else>空闲</span>
              <span>历史批次：<strong>{{ queueStatus.batch_count }}</strong></span>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { settingsApi, convertApi } from '../api'

const saving          = ref(false)
const applyingRecommend = ref(false)
const converting      = ref(false)
const sysInfo         = ref(null)
const activePreset    = ref('original')  // 当前选中的视频预设 key

const batchScope          = ref('static')
const batchPreset         = ref('')
const batchFormat         = ref('')
const batchDeleteOriginal = ref(false)

// 队列相关
const batchJob     = ref(null)   // 当前批次 BatchJob
const queueStatus  = ref(null)   // 全局队列状态
let _pollTimer = null

const batchProgressPct = computed(() => {
  if (!batchJob.value || !batchJob.value.total) return 0
  return Math.round((batchJob.value.done / batchJob.value.total) * 100)
})

// 视频预设定义（与后端 _CONVERT_PRESETS 对应）
const VIDEO_PRESETS = [
  {
    key: 'original',
    label: '原图模式',
    hint: '保留源帧率/分辨率/全帧，流式写入无内存限制，文件较大',
    values: { fps: 0, max_width: 0, max_frames: 0, quality: 100 },
  },
  {
    key: 'standard',
    label: '标准模式',
    hint: '30fps / 1280px 宽，兼顾质量与体积',
    values: { fps: 30, max_width: 1280, max_frames: 120, quality: 80 },
  },
  {
    key: 'lite',
    label: '低配模式',
    hint: '8fps / 854px，内存占用极低，适合低配服务器',
    values: { fps: 8, max_width: 854, max_frames: 30, quality: 65 },
  },
]

const TIER_LABEL = { high: '高配机器', mid: '中配机器', low: '低配机器' }
const VIDEO_FPS_CHOICES = [
  { label: '源帧率', value: 0 },
  { label: '24fps', value: 24 },
  { label: '30fps', value: 30 },
  { label: '60fps', value: 60 },
  { label: '120fps', value: 120 },
]
const VIDEO_WIDTH_CHOICES = [
  { label: '原始尺寸', value: 0 },
  { label: '1080p', value: 1920 },
  { label: '2K', value: 2560 },
  { label: '4K', value: 3840 },
]
const VIDEO_FRAME_CHOICES = [
  { label: '全帧/全时长', value: 0 },
  { label: '120 帧', value: 120 },
  { label: '240 帧', value: 240 },
  { label: '360 帧', value: 360 },
]

// nice 值 → 可读标签
const NICE_LABEL = { 0: '不降权', 5: '后台(5)', 10: '较低(10)', 15: '很低(15)', 19: '最低(19)' }

const DEFAULT_FORM = () => ({
  auto_convert: false,
  max_concurrent: 1,
  video: {
    enabled: false, output_format: 'webp',
    fps: 0, max_frames: 0, width: 0, max_width: 0,
    quality: 100, delete_original: false,
    timeout_seconds: 300, cpu_nice: 5,
  },
  image: {
    enabled: false, output_format: 'webp',
    quality: 100, delete_original: false,
    timeout_seconds: 120, cpu_nice: 5,
  },
})

const form = ref(DEFAULT_FORM())

const videoPolicySummary = computed(() => {
  const fpsText = form.value.video.fps === 0 ? '保留源帧率' : `${form.value.video.fps}fps`
  const widthText = form.value.video.max_width === 0 ? '保留源分辨率' : `最长 ${form.value.video.max_width}px`
  const framesText = form.value.video.max_frames === 0 ? '保留源时长 / 全帧' : `最多 ${form.value.video.max_frames} 帧`
  const qualityText = form.value.video.output_format === 'webp' ? `质量 ${form.value.video.quality}` : 'GIF 按时间轴输出'
  return `${fpsText} · ${widthText} · ${framesText} · ${qualityText}`
})

function syncActivePreset() {
  const matched = VIDEO_PRESETS.find(({ values }) =>
    values.fps === form.value.video.fps &&
    values.max_width === form.value.video.max_width &&
    values.max_frames === form.value.video.max_frames &&
    values.quality === form.value.video.quality
  )
  activePreset.value = matched?.key || null
}

function setVideoField(field, value) {
  form.value.video[field] = value
  syncActivePreset()
}

// ── 内存消耗估算（MB/帧） ─────────────────────────────
function memPerFrame(width) {
  if (!width) return '-'
  // 假设 16:9，RGBA 4 字节/像素
  const h = Math.round(width * 9 / 16)
  return (width * h * 4 / (1024 * 1024)).toFixed(1)
}

// ── 帧数内存预警 ──────────────────────────────────────
const framesBudgetHint = computed(() => {
  if (!sysInfo.value) return ''
  if (form.value.video.max_frames === 0 && form.value.video.max_width === 0) {
    return '原图直出: 不限制帧率、分辨率和时长，实际占用取决于源视频'
  }
  if (form.value.video.max_frames === 0) {
    return '全帧模式: 不限制时长，实际占用取决于源视频总帧数'
  }
  if (form.value.video.max_width === 0) {
    return '原始分辨率: 不缩放，内存占用按源视频尺寸波动'
  }
  const mpf = parseFloat(memPerFrame(form.value.video.max_width || 1280))
  const totalMb = mpf * form.value.video.max_frames
  const avail   = sysInfo.value.available_memory_mb
  const pct     = totalMb / avail * 100
  if (pct > 80) return `警告: ~${totalMb.toFixed(0)}MB (${pct.toFixed(0)}%可用内存)`
  if (pct > 40) return `中等: ~${totalMb.toFixed(0)}MB`
  return `安全: ~${totalMb.toFixed(0)}MB`
})

const framesBudgetClass = computed(() => {
  const hint = framesBudgetHint.value
  if (hint.startsWith('原图直出') || hint.startsWith('全帧模式') || hint.startsWith('原始分辨率')) {
    return 'badge--ok'
  }
  if (hint.startsWith('警告')) return 'badge--warn'
  if (hint.startsWith('中等')) return 'badge--ok'
  return 'badge--safe'
})

// ── 初始化 ────────────────────────────────────────────
onMounted(async () => {
  await Promise.all([loadSettings(), loadSysInfo(), refreshQueueStatus()])
})

async function loadSettings() {
  try {
    const data = await settingsApi.getMediaConvert()
    if (data) mergeForm(data)
  } catch (e) {
    console.error('[Convert] 加载配置失败', e)
  }
}

async function loadSysInfo() {
  try {
    sysInfo.value = await settingsApi.getSystemInfo()
  } catch (e) {
    console.warn('[Convert] 获取系统信息失败', e)
  }
}

function mergeForm(data) {
  if (typeof data.auto_convert === 'boolean') form.value.auto_convert = data.auto_convert
  if (typeof data.max_concurrent === 'number') form.value.max_concurrent = data.max_concurrent
  if (data.video) Object.assign(form.value.video, data.video)
  if (data.image) Object.assign(form.value.image, data.image)
  syncActivePreset()
}

// ── 视频预设切换 ──────────────────────────────────────
function applyVideoPreset(key) {
  const preset = VIDEO_PRESETS.find(p => p.key === key)
  if (!preset) return
  Object.assign(form.value.video, preset.values)
  syncActivePreset()
}

// ── 一键推荐配置（应用并自动保存）────────────────────
async function applyRecommend() {
  if (!sysInfo.value || applyingRecommend.value) return
  const r = sysInfo.value.recommend
  // 应用视频参数
  form.value.video.max_frames = r.max_frames
  form.value.video.max_width  = r.max_width
  form.value.video.fps        = r.fps
  if (r.quality) form.value.video.quality = r.quality
  if (r.timeout_seconds) form.value.video.timeout_seconds = r.timeout_seconds
  if (r.max_concurrent)  form.value.max_concurrent        = r.max_concurrent
  syncActivePreset()

  // 自动保存，让用户看到明确效果
  applyingRecommend.value = true
  try {
    await settingsApi.setMediaConvert(form.value)
  } catch (e) {
    alert(`应用推荐配置失败: ${e.message}`)
  } finally {
    applyingRecommend.value = false
  }
}

// ── 保存 ──────────────────────────────────────────────
async function saveSettings() {
  saving.value = true
  try {
    await settingsApi.setMediaConvert(form.value)
  } catch (e) {
    alert(`保存失败: ${e.message}`)
  } finally {
    saving.value = false
  }
}

// ── 批量转换（队列模式）──────────────────────────────
async function startBatchConvert() {
  converting.value = true
  batchJob.value = null
  stopPolling()
  try {
    const payload = {
      scope:           batchScope.value,
      preset:          batchPreset.value || null,
      output_format:   batchFormat.value || null,
      delete_original: batchDeleteOriginal.value || null,
    }
    const res = await convertApi.batchConvert(payload)
    if (res.batch_id) {
      // 立即拉一次进度，然后启动轮询
      await pollBatchStatus(res.batch_id)
      if (!res.queued_count || batchJob.value?.is_complete) return
      startPolling(res.batch_id)
    } else {
      // 没有可转换的壁纸
      alert(res.message || '没有可转换的壁纸')
    }
  } catch (e) {
    alert(`提交失败: ${e.message}`)
  } finally {
    converting.value = false
  }
}

async function pollBatchStatus(batchId) {
  try {
    batchJob.value = await convertApi.batchStatus(batchId)
  } catch { /* ignore */ }
}

function startPolling(batchId) {
  stopPolling()
  _pollTimer = setInterval(async () => {
    await pollBatchStatus(batchId)
    await refreshQueueStatus()
    if (batchJob.value?.is_complete) stopPolling()
  }, 2000)
}

function stopPolling() {
  if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null }
}

async function refreshQueueStatus() {
  try {
    queueStatus.value = await convertApi.queueStatus()
  } catch { /* ignore */ }
}

onUnmounted(stopPolling)
</script>

<style scoped>
.page-body { padding: 24px 32px; display: flex; flex-direction: column; gap: 16px; }

/* ── 系统资源卡片 ─────────────────────────── */
.sys-card {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 16px; padding: 14px 18px;
  border-radius: var(--radius); border: 1px solid;
  flex-wrap: wrap;
}
.sys-card--high { background: rgba(62,207,114,.06); border-color: rgba(62,207,114,.25); }
.sys-card--mid  { background: rgba(245,166,35,.06);  border-color: rgba(245,166,35,.25); }
.sys-card--low  { background: rgba(240,90,90,.06);   border-color: rgba(240,90,90,.25); }

.sys-card__left  { display: flex; flex-direction: column; gap: 8px; }
.sys-card__right { display: flex; flex-direction: column; gap: 4px; align-items: flex-end; }

.sys-tier-badge {
  display: inline-block; font-size: 11px; font-family: var(--font-ui);
  font-weight: 700; letter-spacing: .08em; text-transform: uppercase;
  padding: 2px 8px; border-radius: 3px;
}
.tier--high { background: rgba(62,207,114,.2);  color: var(--green); }
.tier--mid  { background: rgba(245,166,35,.2);  color: var(--orange); }
.tier--low  { background: rgba(240,90,90,.2);   color: var(--red); }

.sys-metrics { display: flex; gap: 16px; flex-wrap: wrap; }
.sys-metric  { display: flex; flex-direction: column; gap: 2px; }
.sys-metric__label { font-size: 10px; color: var(--text-3); font-family: var(--font-ui); }
.sys-metric strong { font-size: 14px; color: var(--text-1); }
.sys-loading { font-size: 12px; color: var(--text-3); font-style: italic; }

.sys-recommend-label { font-size: 10px; color: var(--text-3); font-family: var(--font-ui); text-transform: uppercase; }
.sys-recommend-values { display: flex; gap: 12px; font-size: 12px; color: var(--text-2); font-family: var(--font-ui); }
.sys-recommend-values strong { color: var(--accent); }
.sys-note { font-size: 11px; color: var(--red); max-width: 240px; text-align: right; }

/* ── 提示卡 ──────────────────────────────── */
.notice-card {
  display: flex; gap: 12px; align-items: flex-start;
  background: rgba(79,142,255,.08); border: 1px solid rgba(79,142,255,.2);
  border-radius: var(--radius); padding: 12px 16px;
  font-size: 12px; color: var(--text-2); line-height: 1.6;
}
.notice-icon { font-size: 16px; color: var(--accent); flex-shrink: 0; }
code {
  background: var(--bg-hover); padding: 1px 5px; border-radius: 3px;
  font-family: var(--font-ui); font-size: 11px; color: var(--text-1);
}

/* ── 布局 ─────────────────────────────────── */
.two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
@media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }

.card-header {
  padding: 12px 16px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
  font-size: 11px; font-family: var(--font-ui); color: var(--text-2);
  letter-spacing: .05em; text-transform: uppercase;
}
.card-body { padding: 16px; }
.cfg-disabled { opacity: .45; pointer-events: none; }

/* ── 性能配置网格 ─────────────────────────── */
.perf-grid {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  gap: 14px 20px; align-items: start;
}
@media (max-width: 1000px) { .perf-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 700px)  { .perf-grid { grid-template-columns: 1fr; } }

/* ── 表单 ─────────────────────────────────── */
.form-grid { display: flex; flex-direction: column; gap: 14px; }
.form-row { display: flex; flex-direction: column; gap: 6px; }
.form-row > label {
  font-size: 11px; color: var(--text-3); text-transform: uppercase;
  letter-spacing: .05em; font-family: var(--font-ui);
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.form-hint { text-transform: none; color: var(--text-3); font-style: italic; font-size: 10px; }

.form-badge {
  font-size: 10px; padding: 1px 6px; border-radius: 3px;
  font-family: var(--font-ui); text-transform: none; font-style: normal;
}
.badge--warn { background: rgba(240,90,90,.18); color: var(--red); }
.badge--ok   { background: rgba(245,166,35,.18); color: var(--orange); }
.badge--safe { background: rgba(62,207,114,.15); color: var(--green); }

.input-row { display: flex; align-items: center; gap: 8px; }
.input-row .input { flex: 1; }
.unit { font-size: 12px; color: var(--text-3); font-family: var(--font-ui); white-space: nowrap; }
.unit-calc { font-size: 11px; color: var(--accent); font-family: var(--font-ui); white-space: nowrap; }

.quality-row, .nice-row { display: flex; align-items: center; gap: 10px; }
.range { flex: 1; accent-color: var(--accent); cursor: pointer; }
.quality-val { width: 64px; text-align: right; font-size: 12px; color: var(--text-1); white-space: nowrap; }

.toggle-row {
  display: flex; align-items: flex-start; gap: 10px; cursor: pointer;
}
.toggle-row input[type="checkbox"] { margin-top: 2px; accent-color: var(--accent); width: 14px; height: 14px; flex-shrink: 0; }
.toggle-row--inline { flex-direction: row; }
.toggle-label { font-size: 13px; color: var(--text-1); font-family: var(--font-body); text-transform: none; letter-spacing: 0; }
.toggle-sub   { font-size: 11px; color: var(--text-3); margin-top: 2px; }

.inline-toggle {
  display: flex; align-items: center; gap: 6px; cursor: pointer;
  font-size: 11px; color: var(--text-2); text-transform: none; letter-spacing: 0;
}
.inline-toggle input { accent-color: var(--accent); }

/* ── 批量转换 ────────────────────────────── */
.batch-toolbar { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 14px; }
@media (max-width: 800px) { .batch-toolbar { grid-template-columns: 1fr; } }

.batch-actions { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.convert-result {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  font-size: 13px; font-family: var(--font-ui);
}
.result-ok    { color: var(--green); }
.result-skip  { color: var(--text-3); }
.result-fail  { color: var(--red); }
.result-total { color: var(--text-2); }

.failed-list { margin-top: 12px; padding: 12px 14px; background: rgba(240,90,90,.06); border-radius: var(--radius); }
.failed-list__title { font-size: 11px; color: var(--red); margin-bottom: 6px; font-family: var(--font-ui); }
.failed-item { font-size: 12px; color: var(--text-2); padding: 2px 0; font-family: var(--font-ui); }

/* ── 批次进度 ─────────────────────────── */
.batch-progress {
  margin-top: 14px; padding: 12px 14px;
  background: var(--bg-2); border: 1px solid var(--border);
  border-radius: var(--radius);
}
.batch-progress__header {
  display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
}
.batch-id { font-size: 11px; color: var(--text-2); font-family: var(--font-ui); }
.batch-status-badge {
  font-size: 11px; font-family: var(--font-ui); font-weight: 600;
  padding: 1px 7px; border-radius: 3px;
}
.badge--running { background: rgba(245,166,35,.18); color: var(--orange); }
.badge--done    { background: rgba(62,207,114,.18); color: var(--green); }
.batch-progress__bar-wrap {
  height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; margin-bottom: 8px;
}
.batch-progress__bar {
  height: 100%; background: var(--accent); border-radius: 3px;
  transition: width .3s ease;
}
.batch-progress__stats { display: flex; gap: 12px; flex-wrap: wrap; font-size: 12px; }

/* ── 队列概览 ─────────────────────────── */
.queue-overview {
  margin-top: 10px; padding: 10px 14px;
  background: rgba(99,102,241,.04); border: 1px solid rgba(99,102,241,.15);
  border-radius: var(--radius);
}
.queue-overview__title {
  font-size: 11px; font-family: var(--font-ui); font-weight: 600;
  color: var(--accent); margin-bottom: 6px;
}
.queue-overview__stats {
  display: flex; gap: 16px; flex-wrap: wrap; font-size: 12px; color: var(--text-2);
}
.queue-overview__stats strong { color: var(--text-1); }

.batch-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }

.header-actions { display: flex; gap: 8px; align-items: center; }

/* ── 预设行 ───────────────────────────────── */
.preset-row {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 8px 16px 0; border-bottom: 1px solid var(--border);
  padding-bottom: 8px;
}
.preset-label {
  font-size: 11px; color: var(--text-3); font-family: var(--font-ui);
  text-transform: uppercase; letter-spacing: .05em; flex-shrink: 0;
}
.btn--preset {
  font-size: 11px; padding: 3px 10px; border-radius: 3px;
  border: 1px solid var(--border); background: var(--bg-hover);
  color: var(--text-2); cursor: pointer; transition: all .15s;
  font-family: var(--font-ui);
}
.btn--preset:hover { border-color: var(--accent); color: var(--accent); }
.btn--preset-active {
  background: rgba(79,142,255,.15); border-color: var(--accent);
  color: var(--accent); font-weight: 600;
}
.btn--preset-clear {
  font-size: 10px; padding: 2px 7px; border-radius: 3px;
  border: 1px solid var(--border); background: transparent;
  color: var(--text-3); cursor: pointer; font-family: var(--font-ui);
}
.btn--preset-clear:hover { color: var(--red); border-color: var(--red); }
.policy-summary {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 0 16px 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text-2);
  font-size: 12px;
}
.policy-summary strong {
  color: var(--text-1);
  font-family: var(--font-ui);
  letter-spacing: .03em;
}
.choice-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.btn--choice {
  font-size: 11px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--bg-hover);
  color: var(--text-2);
  cursor: pointer;
  transition: all .15s;
  font-family: var(--font-ui);
}
.btn--choice:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.btn--choice-active {
  color: var(--accent);
  border-color: var(--accent);
  background: rgba(79,142,255,.12);
}

/* ── 特殊标签 ─────────────────────────────── */
.unit-tag {
  font-size: 10px; padding: 1px 6px; border-radius: 3px;
  font-family: var(--font-ui); white-space: nowrap;
}
.unit-tag--special {
  background: rgba(62,207,114,.15); color: var(--green);
  border: 1px solid rgba(62,207,114,.3);
}
</style>
