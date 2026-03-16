<template>
  <div>
    <div class="page-header">
      <h1 class="page-title">系统监控</h1>
      <button class="btn" @click="loadAll">刷新</button>
    </div>

    <div class="page-body">
      <div class="overview-grid" v-if="overview">
        <div class="ov-card">
          <div class="ov-num">{{ overview.total_wallpapers.toLocaleString() }}</div>
          <div class="ov-lbl">已下载壁纸</div>
        </div>
        <div class="ov-card">
          <div class="ov-num">{{ overview.total_size_gb }} <span class="ov-unit">GB</span></div>
          <div class="ov-lbl">总存储占用</div>
        </div>
        <div class="ov-card">
          <div class="ov-num">{{ overview.active_accounts }}<span class="ov-unit">/{{ overview.total_accounts }}</span></div>
          <div class="ov-lbl">活跃账号</div>
        </div>
        <div class="ov-card" :class="overview.running_tasks > 0 ? 'ov-card--active' : ''">
          <div class="ov-num">{{ overview.running_tasks }}</div>
          <div class="ov-lbl">运行中任务</div>
        </div>
      </div>

      <div class="charts-row">
        <div class="card chart-card">
          <div class="card-header">每日下载趋势（近30天）</div>
          <div class="chart-wrap" ref="trendChart"></div>
        </div>

        <div class="card chart-card">
          <div class="card-header">分类分布</div>
          <div class="chart-wrap" ref="catChart"></div>
        </div>
      </div>

      <div class="card" style="margin-top:20px">
        <div class="card-header">分类统计</div>
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
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { statsApi } from '../api'
import { use } from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { init } from 'echarts/core'

use([BarChart, PieChart, GridComponent, TooltipComponent, SVGRenderer])

const overview = ref(null)
const categories = ref([])
const trendChart = ref(null)
const catChart = ref(null)
let trendInstance = null
let catInstance = null

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
  const [ov, cat, daily] = await Promise.all([
    statsApi.overview(),
    statsApi.byCategory(),
    statsApi.byDate(30),
  ])

  overview.value = ov
  categories.value = cat.categories

  await nextTick()
  renderTrend(daily.daily)
  renderCategory(cat.categories.slice(0, 10))
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

function totalCount() {
  return categories.value.reduce((sum, row) => sum + row.count, 0)
}

function pct(count) {
  const total = totalCount()
  return total ? (count / total) * 100 : 0
}

onMounted(() => {
  loadAll()
  window.addEventListener('resize', resizeCharts)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  disposeCharts()
})
</script>

<style scoped>
.overview-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
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

.charts-row {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 16px;
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

  .charts-row {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .overview-grid {
    grid-template-columns: 1fr;
  }
}
</style>
