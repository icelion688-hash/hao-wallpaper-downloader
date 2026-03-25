<template>
  <div>
    <div v-if="toast" class="toast" :class="`toast--${toast.type}`">{{ toast.msg }}</div>
    <div class="page-header">
      <h1 class="page-title">系统监控</h1>
      <button class="btn" @click="loadAll">刷新</button>
    </div>

    <div class="page-body">
      <div class="overview-grid" v-if="overview">
        <div class="ov-card">
          <div class="ov-num">{{ overview.historical_downloaded.toLocaleString() }}</div>
          <div class="ov-lbl">历史总下载</div>
          <div class="ov-desc">保留数据库历史，不受本地清理影响</div>
        </div>
        <div class="ov-card">
          <div class="ov-num">{{ overview.current_local_count.toLocaleString() }}</div>
          <div class="ov-lbl">当前图库存量</div>
          <div class="ov-desc">当前本地仍保留的壁纸数量</div>
        </div>
        <div class="ov-card">
          <div class="ov-num">{{ overview.uploaded_gallery_count.toLocaleString() }}</div>
          <div class="ov-lbl">已上传图库</div>
          <div class="ov-desc">分类分布与分类统计基于这个口径</div>
        </div>
        <div class="ov-card">
          <div class="ov-num">{{ overview.current_local_size_gb }} <span class="ov-unit">GB</span></div>
          <div class="ov-lbl">当前存储占用</div>
          <div class="ov-desc">仅统计本地现存文件</div>
        </div>
        <div class="ov-card">
          <div class="ov-num">{{ overview.active_accounts }}<span class="ov-unit">/{{ overview.total_accounts }}</span></div>
          <div class="ov-lbl">活跃账号</div>
          <div class="ov-desc">当前仍可参与下载的账号</div>
        </div>
        <div class="ov-card" :class="overview.running_tasks > 0 ? 'ov-card--active' : ''">
          <div class="ov-num">{{ overview.running_tasks }}</div>
          <div class="ov-lbl">运行中任务</div>
          <div class="ov-desc">任务记录总数 {{ overview.total_tasks }}</div>
        </div>
      </div>

      <div class="card" style="margin-bottom:20px" v-if="uploadCoverage">
        <div class="card-header card-header--actions">
          <span>上传覆盖率</span>
          <div class="coverage-actions">
            <button class="btn btn--sm" @click="refreshCoverage">重新比对</button>
            <button class="btn btn--sm" :class="{ 'btn--active': showRepairableOnly }" @click="showRepairableOnly = !showRepairableOnly">
              {{ showRepairableOnly ? '显示全部未上传' : '仅看可补传' }}
            </button>
            <button
              class="btn btn--primary btn--sm"
              @click="reuploadMissing"
              :disabled="reuploading || !uploadCoverage.repairable_count || !uploadCoverage.profile_available"
            >
              {{ reuploading ? '补传中...' : `补传未上传图片 ${uploadCoverage.repairable_count || 0} 张` }}
            </button>
          </div>
        </div>
        <div class="coverage-grid">
          <div class="coverage-item">
            <div class="coverage-num">{{ uploadCoverage.historical_total.toLocaleString() }}</div>
            <div class="coverage-lbl">历史已下载</div>
          </div>
          <div class="coverage-item">
            <div class="coverage-num">{{ uploadCoverage.historical_uploaded_count.toLocaleString() }}</div>
            <div class="coverage-lbl">历史已上传</div>
          </div>
          <div class="coverage-item">
            <div class="coverage-num coverage-num--warn">{{ historicalGapCount.toLocaleString() }}</div>
            <div class="coverage-lbl">历史未上传</div>
          </div>
          <div class="coverage-item">
            <div class="coverage-num coverage-num--warn">{{ uploadCoverage.missing_count.toLocaleString() }}</div>
            <div class="coverage-lbl">当前本地未上传</div>
          </div>
          <div class="coverage-item">
            <div class="coverage-num">{{ uploadCoverage.historical_coverage_ratio.toFixed(1) }}<span class="ov-unit">%</span></div>
            <div class="coverage-lbl">历史上传覆盖率</div>
          </div>
          <div class="coverage-item">
            <div class="coverage-num">{{ uploadCoverage.profile_name || uploadCoverage.profile_key || '未配置' }}</div>
            <div class="coverage-lbl">任务默认 Profile</div>
          </div>
        </div>
        <div class="coverage-progress" v-if="uploadProgress.visible">
          <div class="coverage-progress__head">
            <span>{{ uploadProgress.label }}</span>
            <span class="font-mono">{{ uploadProgress.percent }}%</span>
          </div>
          <div class="coverage-progress__bar">
            <div class="coverage-progress__fill" :style="{ width: `${uploadProgress.percent}%` }"></div>
          </div>
          <div class="coverage-progress__note">{{ uploadProgress.note }}</div>
        </div>
        <div class="coverage-note">
          历史已下载 {{ uploadCoverage.historical_total.toLocaleString() }} 张，其中已上传 {{ uploadCoverage.historical_uploaded_count.toLocaleString() }} 张；当前本地仍保留 {{ uploadCoverage.total_local.toLocaleString() }} 张，其中未上传 {{ uploadCoverage.missing_count.toLocaleString() }} 张。
        </div>
        <div class="coverage-note">
          当前可直接补传 {{ uploadCoverage.repairable_count.toLocaleString() }} 张
          <span v-if="uploadCoverage.broken_local_file_count">，另有 {{ uploadCoverage.broken_local_file_count.toLocaleString() }} 张记录存在但本地文件已丢失</span>
          <span v-if="uploadCoverage.no_local_record_count">，{{ uploadCoverage.no_local_record_count.toLocaleString() }} 张历史记录已被清理，本轮无法自动补传</span>。
        </div>
        <div class="coverage-note" v-if="!uploadCoverage.profile_available">
          当前默认上传 Profile 不可用，请先在“图床上传”页确认 `task_profile` 已启用且 Token 有效。
        </div>
        <div class="coverage-note" v-if="reuploadSummary">{{ reuploadSummary }}</div>
        <div class="coverage-panels">
          <div class="coverage-reasons" v-if="uploadCoverage.reason_breakdown?.length">
            <div class="coverage-reasons__title">未上传原因</div>
            <div class="coverage-reason-chips">
              <span class="meta-tag" v-for="item in uploadCoverage.reason_breakdown" :key="item.reason">
                {{ item.reason }} · {{ item.count }}
              </span>
            </div>
          </div>
          <div class="coverage-reasons" v-if="uploadCoverage.missing_categories?.length">
            <div class="coverage-reasons__title">未上传分类排行</div>
            <div class="coverage-ranking">
              <div class="coverage-ranking__row" v-for="item in uploadCoverage.missing_categories" :key="item.category">
                <span class="coverage-ranking__name">{{ item.category }}</span>
                <span class="coverage-ranking__count">{{ item.count }}</span>
              </div>
            </div>
          </div>
        </div>
        <div class="coverage-detail" v-if="visiblePendingItems.length">
          <div class="coverage-reasons__title">
            未上传明细
            <span class="muted">（显示 {{ visiblePendingItems.length }} / {{ uploadCoverage.pending_items?.length || 0 }} 条）</span>
          </div>
          <table class="table table--compact">
            <thead>
              <tr>
                <th>ID</th>
                <th>下载时间</th>
                <th>分类</th>
                <th>文件</th>
                <th>原因</th>
                <th>本地</th>
                <th>补传</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in visiblePendingItems" :key="item.id">
                <td class="font-mono muted">#{{ item.id }}</td>
                <td class="font-mono muted">{{ formatDateTime(item.downloaded_at) }}</td>
                <td>{{ item.category }}</td>
                <td class="font-mono coverage-path">{{ item.local_path || '已清理' }}</td>
                <td>{{ item.reason }}</td>
                <td>
                  <span class="tag" :class="localStateClass(item.local_state)">
                    {{ localStateLabel(item.local_state) }}
                  </span>
                </td>
                <td>
                  <span class="tag" :class="item.repairable ? 'tag--ok' : 'tag--warn'">
                    {{ item.repairable ? '可补传' : '需人工处理' }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div class="charts-row">
        <div class="card chart-card">
          <div class="card-header">每日下载趋势（近30天）</div>
          <div class="chart-note">按历史下载记录统计，空白日期已补 0，方便看长期趋势。</div>
          <div class="chart-wrap" ref="trendChart"></div>
        </div>

        <div class="card chart-card">
          <div class="card-header">分类分布</div>
          <div class="chart-note">按已上传到图库的壁纸统计，不受本地自动清理影响。</div>
          <div class="chart-wrap" ref="catChart"></div>
        </div>
      </div>

      <div class="card" style="margin-top:20px">
        <div class="card-header">分类统计</div>
        <div class="table-note" v-if="categorySourceLabel">
          统计口径：{{ categorySourceLabel }}，共 {{ uploadedCategoryTotal.toLocaleString() }} 张
        </div>
        <table class="table" v-if="categories.length">
          <thead>
            <tr>
              <th>#</th>
              <th>分类</th>
              <th>数量</th>
              <th>占比</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in categories" :key="i">
              <td class="font-mono muted">{{ i + 1 }}</td>
              <td>{{ row.category }}</td>
              <td class="font-mono">{{ row.count.toLocaleString() }}</td>
              <td>
                <div class="ratio-row">
                  <div class="pct-bar">
                    <div class="pct-fill" :style="{ width: `${pct(row.count)}%` }"></div>
                  </div>
                  <span class="font-mono muted">{{ pct(row.count).toFixed(1) }}%</span>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="empty-state" v-else>暂无分类数据</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { statsApi } from '../api'
import { use } from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { init } from 'echarts/core'

use([BarChart, PieChart, GridComponent, TooltipComponent, SVGRenderer])

const overview = ref(null)
const categories = ref([])
const categorySource = ref('')
const uploadedCategoryTotal = ref(0)
const uploadCoverage = ref(null)
const reuploading = ref(false)
const reuploadSummary = ref('')
const showRepairableOnly = ref(true)
const toast = ref(null)
const uploadProgress = ref({
  visible: false,
  percent: 0,
  label: '',
  note: '',
})
const trendChart = ref(null)
const catChart = ref(null)
let trendInstance = null
let catInstance = null
let toastTimer = null
let progressTimer = null

function ensureChartInstance(containerRef, currentInstance) {
  if (!containerRef.value) return null
  return currentInstance || init(containerRef.value, null, { renderer: 'svg' })
}

function buildTrendOption(data) {
  return {
    backgroundColor: 'transparent',
    grid: { top: 16, bottom: 36, left: 48, right: 20 },
    xAxis: {
      type: 'category',
      data: data.map((item) => item.date.slice(5)),
      axisLine: { lineStyle: { color: '#252b35' } },
      axisTick: { show: false },
      axisLabel: { color: '#4f5a6a', fontSize: 10, interval: 4 },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#4f5a6a', fontSize: 10 },
      splitLine: { lineStyle: { color: '#1a1e25' } },
    },
    series: [{
      type: 'bar',
      data: data.map((item) => item.count),
      itemStyle: { color: '#4f8eff', borderRadius: [3, 3, 0, 0] },
      emphasis: { itemStyle: { color: '#74a8ff' } },
    }],
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#1a1e25',
      borderColor: '#252b35',
      textStyle: { color: '#e8edf5', fontSize: 12 },
    },
  }
}

function buildCategoryOption(data) {
  return {
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'item',
      backgroundColor: '#1a1e25',
      borderColor: '#252b35',
      textStyle: { color: '#e8edf5', fontSize: 12 },
    },
    series: [{
      type: 'pie',
      radius: ['45%', '75%'],
      data: data.map((item) => ({ name: item.category, value: item.count })),
      label: { color: '#8a96a8', fontSize: 11 },
      itemStyle: { borderColor: '#0d0f12', borderWidth: 2 },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(79,142,255,.3)' } },
    }],
    color: ['#4f8eff', '#3ecf72', '#f5a623', '#f05a5a', '#34d399', '#60a5fa', '#fb923c', '#94a3b8', '#f472b6', '#facc15'],
  }
}

function renderTrend(data) {
  trendInstance = ensureChartInstance(trendChart, trendInstance)
  if (!trendInstance) return
  trendInstance.setOption(buildTrendOption(data))
}

function renderCategory(data) {
  catInstance = ensureChartInstance(catChart, catInstance)
  if (!catInstance) return
  catInstance.setOption(buildCategoryOption(data))
}

async function loadAll() {
  const [ov, cat, daily, coverage] = await Promise.all([
    statsApi.overview(),
    statsApi.byCategory(),
    statsApi.byDate(30),
    statsApi.uploadCoverage(),
  ])

  overview.value = ov
  categories.value = cat.categories
  categorySource.value = cat.source || ''
  uploadedCategoryTotal.value = Number(cat.total_uploaded || 0)
  uploadCoverage.value = coverage

  await nextTick()
  renderTrend(daily.daily)
  renderCategory(cat.categories.slice(0, 10))
}

async function refreshCoverage() {
  uploadCoverage.value = await statsApi.uploadCoverage()
}

function resizeCharts() {
  trendInstance?.resize()
  catInstance?.resize()
}

function disposeCharts() {
  trendInstance?.dispose()
  catInstance?.dispose()
  trendInstance = null
  catInstance = null
}

function showToast(type, msg, duration = 3200) {
  clearTimeout(toastTimer)
  toast.value = { type, msg }
  toastTimer = setTimeout(() => {
    toast.value = null
  }, duration)
}

function stopProgress() {
  clearInterval(progressTimer)
  progressTimer = null
}

function startProgress(total) {
  stopProgress()
  uploadProgress.value = {
    visible: true,
    percent: 6,
    label: '正在补传未上传图片',
    note: `本次准备处理 ${total} 张图片，请稍候。`,
  }
  progressTimer = setInterval(() => {
    const current = Number(uploadProgress.value.percent || 0)
    if (current >= 92) return
    const next = current < 30 ? current + 12 : (current < 70 ? current + 7 : current + 3)
    uploadProgress.value = {
      ...uploadProgress.value,
      percent: Math.min(92, next),
      note: '正在等待图床返回结果，完成后会自动刷新统计数据。',
    }
  }, 450)
}

async function finishProgress(percent, label, note, keepMs = 1200) {
  stopProgress()
  uploadProgress.value = {
    visible: true,
    percent,
    label,
    note,
  }
  if (keepMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, keepMs))
  }
  uploadProgress.value = {
    visible: false,
    percent: 0,
    label: '',
    note: '',
  }
}

function totalCount() {
  return categories.value.reduce((sum, row) => sum + row.count, 0)
}

function pct(count) {
  const total = totalCount()
  return total ? (count / total) * 100 : 0
}

const categorySourceLabel = computed(() => (
  categorySource.value === 'uploaded_gallery' ? '已上传图库' : ''
))
const historicalGapCount = computed(() => Number(uploadCoverage.value?.historical_missing_count || 0))
const visiblePendingItems = computed(() => {
  const items = Array.isArray(uploadCoverage.value?.pending_items) ? uploadCoverage.value.pending_items : []
  return (showRepairableOnly.value ? items.filter((item) => item?.repairable) : items).slice(0, 20)
})

function formatDateTime(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function localStateLabel(state) {
  if (state === 'exists') return '文件存在'
  if (state === 'missing') return '文件丢失'
  return '已清理'
}

function localStateClass(state) {
  if (state === 'exists') return 'tag--ok'
  return 'tag--warn'
}

async function reuploadMissing() {
  if (!uploadCoverage.value?.repairable_count) {
    showToast('info', '当前没有可补传的图片')
    return
  }
  reuploading.value = true
  reuploadSummary.value = ''
  startProgress(uploadCoverage.value.repairable_count)
  try {
    const res = await statsApi.reuploadMissing()
    const result = res?.result || {}
    uploadCoverage.value = res?.coverage || uploadCoverage.value
    reuploadSummary.value = `补传完成：成功 ${result.success_count || 0} 张，失败 ${result.failed_count || 0} 张，跳过 ${result.skipped_count || 0} 张。`
    const successCount = Number(result.success_count || 0)
    const failedCount = Number(result.failed_count || 0)
    const skippedCount = Number(result.skipped_count || 0)
    await finishProgress(
      100,
      '补传完成',
      `成功 ${successCount} 张，失败 ${failedCount} 张，跳过 ${skippedCount} 张。`,
      1500,
    )
    if (failedCount > 0) {
      showToast('warn', `补传完成：成功 ${successCount} 张，失败 ${failedCount} 张，跳过 ${skippedCount} 张。`)
    } else {
      showToast('ok', `补传成功：成功 ${successCount} 张，跳过 ${skippedCount} 张。`)
    }
    await loadAll()
  } catch (error) {
    await finishProgress(100, '补传失败', `失败原因：${error.message}`, 1800)
    reuploadSummary.value = `补传失败：${error.message}`
    showToast('err', `补传失败：${error.message}`)
  } finally {
    reuploading.value = false
  }
}

onMounted(() => {
  loadAll()
  window.addEventListener('resize', resizeCharts)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  clearTimeout(toastTimer)
  stopProgress()
  disposeCharts()
})
</script>

<style scoped>
.overview-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 20px;
}

.ov-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 22px;
  transition: border-color .15s;
}

.ov-card--active {
  border-color: var(--accent);
  background: var(--accent-glow);
}

.toast {
  position: fixed;
  right: 24px;
  bottom: 24px;
  z-index: 9999;
  max-width: 420px;
  padding: 12px 20px;
  border-radius: var(--radius);
  font-size: 13px;
  line-height: 1.5;
  box-shadow: 0 4px 16px rgba(0, 0, 0, .35);
  border-left: 4px solid transparent;
  background: var(--bg-panel);
  color: var(--text-1);
  animation: toast-in .2s ease;
}

.toast--ok {
  border-left-color: var(--green);
}

.toast--warn {
  border-left-color: var(--orange);
}

.toast--err {
  border-left-color: var(--red);
}

.toast--info {
  border-left-color: var(--accent);
}

@keyframes toast-in {
  from {
    opacity: 0;
    transform: translateY(10px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.card-header--actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.ov-num {
  font-size: 32px;
  font-weight: 700;
  font-family: var(--font-ui);
  color: var(--text-1);
}

.ov-unit {
  font-size: 14px;
  color: var(--text-3);
}

.ov-lbl {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 6px;
  text-transform: uppercase;
  letter-spacing: .05em;
}

.ov-desc {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.5;
}

.coverage-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  padding: 0 18px 16px;
}

.coverage-item {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 18px;
  background: var(--bg-card-soft, rgba(255,255,255,.02));
}

.coverage-num {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-1);
  word-break: break-word;
}

.coverage-num--warn {
  color: var(--orange, #f39c12);
}

.coverage-lbl {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: .05em;
}

.coverage-note {
  padding: 0 18px 12px;
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.7;
}

.coverage-progress {
  margin: 0 18px 16px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-card-soft, rgba(255,255,255,.02));
}

.coverage-progress__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: var(--text-1);
  font-size: 13px;
  margin-bottom: 10px;
}

.coverage-progress__bar {
  height: 8px;
  border-radius: 999px;
  background: var(--bg-base);
  overflow: hidden;
}

.coverage-progress__fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #4f8eff 0%, #3ecf72 100%);
  transition: width .35s ease;
}

.coverage-progress__note {
  margin-top: 10px;
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.6;
}

.coverage-panels {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.coverage-reasons {
  padding: 0 18px 18px;
}

.coverage-reasons__title {
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--text-3);
}

.coverage-reason-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.coverage-ranking {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.coverage-ranking__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--bg-card-soft, rgba(255,255,255,.02));
  border: 1px solid var(--border);
}

.coverage-ranking__name {
  color: var(--text-1);
}

.coverage-ranking__count {
  color: var(--text-2);
  font-family: var(--font-ui);
}

.coverage-detail {
  padding: 0 18px 18px;
}

.coverage-path {
  max-width: 320px;
  word-break: break-all;
}

.charts-row {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 16px;
}

.chart-note,
.table-note {
  padding: 0 18px;
  color: var(--text-2);
  font-size: 12px;
  line-height: 1.6;
}

.chart-wrap {
  height: 220px;
  padding: 10px;
}

.ratio-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pct-bar {
  flex: 1;
  height: 4px;
  background: var(--bg-base);
  border-radius: 2px;
  overflow: hidden;
}

.pct-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
}

.font-mono {
  font-family: var(--font-ui);
}

.muted {
  font-size: 11px;
  color: var(--text-2);
}

@media (max-width: 960px) {
  .overview-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .coverage-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .charts-row {
    grid-template-columns: 1fr;
  }

  .coverage-panels {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .overview-grid {
    grid-template-columns: 1fr;
  }

  .coverage-grid {
    grid-template-columns: 1fr;
  }
}
</style>
