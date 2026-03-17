<template>
  <div>
    <div class="page-header">
      <h1 class="page-title">格式转换 <small>MP4 → 动态 WebP / GIF · 静态图 → WebP</small></h1>
      <div class="header-actions">
        <button class="btn" @click="applyRecommend" :disabled="!sysInfo" title="根据当前机器配置一键填入建议值">
          一键推荐配置
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
          视频转换需要 <code>imageio-ffmpeg</code>（pip 包，内含 ffmpeg 二进制，<strong>无需系统安装</strong>）。
          运行 <code>pip install imageio imageio-ffmpeg</code> 安装。
          静态图转换仅需 Pillow（已内置）。已内置 CPU 降权、内存自适应和超时保护，不会卡死服务器。
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
                <div class="toggle-sub">下载完成后立即后台转换，视频较慢，建议在低并发时开启</div>
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
              <label>视频超时 <span class="form-hint">超时后软取消，已采集帧仍会保存</span></label>
              <div class="input-row">
                <input class="input" type="number" v-model.number="form.video.timeout_seconds" min="30" max="3600" />
                <span class="unit">秒</span>
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
              <label>CPU 降权（视频） <span class="form-hint">0=不降 5=后台 19=最低，仅 Linux</span></label>
              <div class="nice-row">
                <input type="range" class="range" v-model.number="form.video.cpu_nice" min="0" max="19" />
                <span class="quality-val font-mono">{{ NICE_LABEL[form.video.cpu_nice] || form.video.cpu_nice }}</span>
              </div>
            </div>
            <div class="form-row">
              <label>CPU 降权（图片）</label>
              <div class="nice-row">
                <input type="range" class="range" v-model.number="form.image.cpu_nice" min="0" max="19" />
                <span class="quality-val font-mono">{{ NICE_LABEL[form.image.cpu_nice] || form.image.cpu_nice }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="two-col">
        <!-- 视频转换 -->
        <div class="card">
          <div class="card-header">
            <span>视频 &nbsp;MP4 → 动态 WebP / GIF</span>
            <label class="inline-toggle">
              <input type="checkbox" v-model="form.video.enabled" />
              <span>{{ form.video.enabled ? '已启用' : '已禁用' }}</span>
            </label>
          </div>
          <div class="card-body" :class="{ 'cfg-disabled': !form.video.enabled }">
            <div class="form-grid">
              <div class="form-row">
                <label>输出格式</label>
                <select class="select" v-model="form.video.output_format">
                  <option value="webp">动态 WebP（推荐，体积小，浏览器 &lt;img&gt; 自动循环）</option>
                  <option value="gif">GIF（兼容性更强，体积大）</option>
                </select>
              </div>
              <div class="form-row">
                <label>输出帧率 <span class="form-hint">原始帧率按比例降采样</span></label>
                <div class="input-row">
                  <input class="input" type="number" v-model.number="form.video.fps" min="1" max="60" />
                  <span class="unit">fps</span>
                </div>
              </div>
              <div class="form-row">
                <label>
                  最大帧数
                  <span class="form-hint">实际值由可用内存自动压缩</span>
                  <span class="form-badge" :class="framesBudgetClass">{{ framesBudgetHint }}</span>
                </label>
                <div class="input-row">
                  <input class="input" type="number" v-model.number="form.video.max_frames" min="10" max="600" />
                  <span class="unit">帧</span>
                  <span class="unit-calc">≈ {{ (form.video.max_frames / Math.max(form.video.fps, 1)).toFixed(1) }}s</span>
                </div>
              </div>
              <div class="form-row">
                <label>
                  帧宽上限 max_width
                  <span class="form-hint">4K(3840)→1280px 内存从 24MB→2.8MB/帧</span>
                </label>
                <div class="input-row">
                  <input class="input" type="number" v-model.number="form.video.max_width" min="0" step="8" />
                  <span class="unit">px</span>
                  <span class="unit-calc" v-if="form.video.max_width">
                    ~{{ memPerFrame(form.video.max_width) }} MB/帧
                  </span>
                </div>
              </div>
              <div class="form-row">
                <label>固定输出宽度 <span class="form-hint">0 = 使用 max_width 自动裁剪</span></label>
                <div class="input-row">
                  <input class="input" type="number" v-model.number="form.video.width" min="0" step="8" />
                  <span class="unit">px</span>
                </div>
              </div>
              <div class="form-row">
                <label>WebP 质量 <span class="form-hint">仅 WebP 格式生效</span></label>
                <div class="quality-row">
                  <input type="range" class="range" v-model.number="form.video.quality" min="1" max="100" />
                  <span class="quality-val font-mono">{{ form.video.quality }}</span>
                </div>
              </div>
              <div class="form-row">
                <label class="toggle-row toggle-row--inline">
                  <input type="checkbox" v-model="form.video.delete_original" />
                  <div>
                    <div class="toggle-label">转换后删除原 MP4</div>
                    <div class="toggle-sub">⚠ 不可恢复，请先确认质量满意</div>
                  </div>
                </label>
              </div>
            </div>
          </div>
        </div>

        <!-- 静态图转换 -->
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
                <option value="dynamic">全部动态视频（MP4）</option>
                <option value="static">全部静态图片</option>
                <option value="all">全部（视频 + 图片）</option>
              </select>
            </div>
            <div class="form-row">
              <label>覆盖输出格式 <span class="form-hint">留空=使用上方配置</span></label>
              <select class="select" v-model="batchFormat">
                <option value="">使用配置默认值</option>
                <option value="webp">WebP</option>
                <option value="gif">GIF（仅视频）</option>
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
              {{ converting ? `转换中… ${convertProgress}` : '开始批量转换' }}
            </button>
            <div v-if="convertResult" class="convert-result">
              <span class="result-ok">✓ 成功 {{ convertResult.success_count }}</span>
              <span class="result-skip">跳过 {{ convertResult.skipped_count }}</span>
              <span v-if="convertResult.failed_count" class="result-fail">✗ 失败 {{ convertResult.failed_count }}</span>
              <span class="result-total">共 {{ convertResult.total }} 张</span>
            </div>
          </div>
          <div v-if="convertResult?.failed_items?.length" class="failed-list">
            <div class="failed-list__title">失败项目：</div>
            <div v-for="item in convertResult.failed_items" :key="item.id" class="failed-item">
              ID {{ item.id }} — {{ item.reason }}
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { settingsApi, convertApi } from '../api'

const saving     = ref(false)
const converting = ref(false)
const convertProgress = ref('')
const convertResult   = ref(null)
const sysInfo    = ref(null)

const batchScope          = ref('dynamic')
const batchFormat         = ref('')
const batchDeleteOriginal = ref(false)

const TIER_LABEL = { high: '高配机器', mid: '中配机器', low: '低配机器' }

// nice 值 → 可读标签
const NICE_LABEL = { 0: '不降权', 5: '后台(5)', 10: '较低(10)', 15: '很低(15)', 19: '最低(19)' }

const DEFAULT_FORM = () => ({
  auto_convert: false,
  max_concurrent: 1,
  video: {
    enabled: false, output_format: 'webp',
    fps: 10, max_frames: 120, width: 0, max_width: 1280,
    quality: 80, delete_original: false,
    timeout_seconds: 300, cpu_nice: 5,
  },
  image: {
    enabled: false, output_format: 'webp',
    quality: 85, delete_original: false,
    timeout_seconds: 120, cpu_nice: 5,
  },
})

const form = ref(DEFAULT_FORM())

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
  if (hint.startsWith('警告')) return 'badge--warn'
  if (hint.startsWith('中等')) return 'badge--ok'
  return 'badge--safe'
})

// ── 初始化 ────────────────────────────────────────────
onMounted(async () => {
  await Promise.all([loadSettings(), loadSysInfo()])
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
}

// ── 一键推荐配置 ──────────────────────────────────────
function applyRecommend() {
  if (!sysInfo.value) return
  const r = sysInfo.value.recommend
  form.value.video.max_frames = r.max_frames
  form.value.video.max_width  = r.max_width
  form.value.video.fps        = r.fps
  // 低配自动调高超时
  if (sysInfo.value.tier === 'low') {
    form.value.video.timeout_seconds = 600
    form.value.max_concurrent = 1
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

// ── 批量转换 ──────────────────────────────────────────
async function startBatchConvert() {
  converting.value = true
  convertResult.value = null
  convertProgress.value = '请求中…'
  try {
    const payload = {
      scope:          batchScope.value,
      output_format:  batchFormat.value || null,
      delete_original: batchDeleteOriginal.value || null,
    }
    const res = await convertApi.batchConvert(payload)
    convertResult.value = res
  } catch (e) {
    alert(`转换失败: ${e.message}`)
  } finally {
    converting.value = false
    convertProgress.value = ''
  }
}
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

.header-actions { display: flex; gap: 8px; align-items: center; }
</style>
