<template>
  <div>
    <!-- 页头 -->
    <div class="page-header">
      <h1 class="page-title">下载画廊 <small>{{ total }} 张壁纸</small></h1>
      <div class="header-actions">
        <button class="btn" @click="scanDups">扫描重复</button>
        <button class="btn btn--danger" v-if="dupCount > 0" @click="cleanDups">清理 {{ dupCount }} 个重复</button>
      </div>
    </div>

    <!-- 可视化筛选面板 -->
    <div class="filter-panel">
      <!-- 搜索 + 活跃标签行 -->
      <div class="filter-row filter-row--search">
        <input class="input filter-search" v-model="filters.search" @input="debounceLoad" placeholder="搜索标签…" />
        <div class="active-tags" v-if="activeFilterCount > 0">
          <span class="active-tag" v-if="filters.wallpaper_type" @click="setFilter('wallpaper_type', '')">
            {{ filters.wallpaper_type === 'static' ? '静态' : '动态' }} ×
          </span>
          <span class="active-tag" v-if="filters.category" @click="setFilter('category', '')">
            {{ filters.category }} ×
          </span>
          <span class="active-tag" v-if="filters.color_theme" @click="setFilter('color_theme', '')">
            {{ filters.color_theme }} ×
          </span>
          <span class="active-tag" v-if="filters.screen_orientation" @click="setFilter('screen_orientation', '')">
            {{ filters.screen_orientation === 'landscape' ? '横屏' : '竖屏' }} ×
          </span>
          <span class="active-tag" v-if="filters.min_height" @click="clearResolution()">
            {{ filters.resolution_preset }}+ ×
          </span>
          <button class="clear-all-btn" @click="clearAllFilters">清除全部</button>
        </div>
        <span class="filter-stats font-mono">{{ total }} 张</span>
      </div>

      <!-- 类型 + 方向 + 分辨率 -->
      <div class="filter-row">
        <div class="filter-group">
          <span class="filter-label">类型</span>
          <div class="chip-group">
            <button class="chip" :class="{ 'chip--active': !filters.wallpaper_type }" @click="setFilter('wallpaper_type', '')">全部</button>
            <button class="chip" :class="{ 'chip--active': filters.wallpaper_type === 'static' }" @click="setFilter('wallpaper_type', 'static')">
              <span class="chip-icon">◼</span>静态
            </button>
            <button class="chip" :class="{ 'chip--active': filters.wallpaper_type === 'dynamic' }" @click="setFilter('wallpaper_type', 'dynamic')">
              <span class="chip-icon">▶</span>动态
            </button>
          </div>
        </div>
        <div class="filter-divider"></div>
        <div class="filter-group">
          <span class="filter-label">方向</span>
          <div class="chip-group">
            <button class="chip" :class="{ 'chip--active': !filters.screen_orientation }" @click="setFilter('screen_orientation', '')">全部</button>
            <button class="chip" :class="{ 'chip--active': filters.screen_orientation === 'landscape' }" @click="setFilter('screen_orientation', 'landscape')">
              <span class="chip-icon orient-icon orient-icon--land"></span>横屏
            </button>
            <button class="chip" :class="{ 'chip--active': filters.screen_orientation === 'portrait' }" @click="setFilter('screen_orientation', 'portrait')">
              <span class="chip-icon orient-icon orient-icon--port"></span>竖屏
            </button>
          </div>
        </div>
        <div class="filter-divider"></div>
        <div class="filter-group">
          <span class="filter-label">分辨率</span>
          <div class="chip-group">
            <button class="chip" :class="{ 'chip--active': !filters.min_height }" @click="clearResolution">全部</button>
            <button class="chip" :class="{ 'chip--active': filters.min_height === 1080 }" @click="setResolution(1080, '1080p')">
              <span class="chip-icon res-dot"></span>1080p+
            </button>
            <button class="chip" :class="{ 'chip--active': filters.min_height === 1440 }" @click="setResolution(1440, '2K')">
              <span class="chip-icon res-dot res-dot--2k"></span>2K+
            </button>
            <button class="chip" :class="{ 'chip--active': filters.min_height === 2160 }" @click="setResolution(2160, '4K')">
              <span class="chip-icon res-dot res-dot--4k"></span>4K+
            </button>
          </div>
        </div>
      </div>

      <!-- 分类行：DB 中已有的分类统计 -->
      <div class="filter-row" v-if="categories.length">
        <div class="filter-group filter-group--wide">
          <span class="filter-label">分类</span>
          <div class="chip-group chip-group--scroll">
            <button class="chip" :class="{ 'chip--active': !filters.category }" @click="setFilter('category', '')">
              全部 <span class="chip-count">{{ total }}</span>
            </button>
            <button
              v-for="cat in categories" :key="cat.name"
              class="chip"
              :class="{ 'chip--active': filters.category === cat.name }"
              @click="setFilter('category', cat.name)"
            >
              {{ cat.name }} <span class="chip-count">{{ cat.count }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 色系行 -->
      <div class="filter-row" v-if="colorThemes.length">
        <div class="filter-group filter-group--wide">
          <span class="filter-label">色系</span>
          <div class="chip-group chip-group--scroll">
            <button class="chip" :class="{ 'chip--active': !filters.color_theme }" @click="setFilter('color_theme', '')">全部</button>
            <button
              v-for="theme in colorThemes" :key="theme.name"
              class="chip chip--color"
              :class="{ 'chip--active': filters.color_theme === theme.name }"
              @click="setFilter('color_theme', theme.name)"
            >
              <span class="color-swatch" :style="{ background: getThemeColor(theme.name) }"></span>
              {{ theme.name }} <span class="chip-count">{{ theme.count }}</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 重复文件提示 -->
    <div class="dup-banner" v-if="dupResult">
      发现 {{ dupResult.duplicate_groups }} 组共 {{ dupResult.total_duplicates }} 个重复文件
      <button class="btn btn--sm btn--danger" @click="cleanDups" style="margin-left:12px">立即清理</button>
      <button class="btn btn--sm" @click="dupResult = null" style="margin-left:6px">关闭</button>
    </div>

    <!-- 批量删除面板 -->
    <div class="danger-panel card">
      <div class="danger-panel__head" @click="dangerPanelOpen = !dangerPanelOpen">
        <div class="danger-panel__title">批量删除</div>
        <span class="danger-panel__toggle">{{ dangerPanelOpen ? '▲ 收起' : '▼ 展开' }}</span>
      </div>
      <template v-if="dangerPanelOpen">
        <div class="danger-options">
          <label class="check-label">
            <input type="checkbox" v-model="batchDeleteFile" />
            同时删除本地文件
          </label>
        </div>
        <div class="danger-actions">
          <div class="danger-action">
            <div class="danger-action__desc">
              <div class="danger-action__title">删除已选图片</div>
              <div class="danger-action__sub">已选 {{ selectedIds.length }} 张</div>
            </div>
            <button class="btn btn--sm btn--danger" :disabled="!selectedIds.length || deleting" @click="batchDeleteSelected">
              删除已选
            </button>
          </div>
          <div class="danger-action">
            <div class="danger-action__desc">
              <div class="danger-action__title">按分类删除</div>
              <select class="select select--sm" v-model="deleteCategoryTarget" @click.stop>
                <option value="">选择分类</option>
                <option v-for="item in categories" :key="item.name" :value="item.name">{{ item.name }} ({{ item.count }})</option>
              </select>
            </div>
            <button class="btn btn--sm btn--danger" :disabled="!deleteCategoryTarget || deleting" @click="batchDeleteByCategory">
              删除该分类
            </button>
          </div>
          <div class="danger-action">
            <div class="danger-action__desc">
              <div class="danger-action__title">删除全部记录</div>
              <div class="danger-action__sub">共 {{ total }} 张，操作不可撤销</div>
            </div>
            <button class="btn btn--sm btn--danger" :disabled="!total || deleting" @click="batchDeleteAll">
              {{ deleting ? '删除中…' : '清空全部' }}
            </button>
          </div>
        </div>
        <div class="delete-result" v-if="deleteResult">
          已删除 {{ deleteResult.deleted_count }} 条记录
          <span v-if="deleteResult.file_failed > 0">（{{ deleteResult.file_failed }} 个文件删除失败）</span>
        </div>
      </template>
    </div>

    <!-- 选择工具栏 -->
    <div class="select-toolbar" v-if="wallpapers.length">
      <button class="btn btn--sm" @click="toggleSelectCurrentPage(true)">全选当前页</button>
      <button class="btn btn--sm" @click="toggleSelectCurrentPage(false)">清空选择</button>
      <span class="selected-count" v-if="selectedIds.length">已选 {{ selectedIds.length }} 张</span>
    </div>

    <!-- 确认对话框 -->
    <Teleport to="body">
      <div class="modal-overlay" v-if="confirmModal.visible" @click.self="confirmModal.resolve(false)">
        <div class="modal-box">
          <div class="modal-title">{{ confirmModal.title }}</div>
          <div class="modal-message" v-if="confirmModal.message">{{ confirmModal.message }}</div>
          <div class="modal-actions">
            <button class="btn" @click="confirmModal.resolve(false)">取消</button>
            <button class="btn btn--danger" @click="confirmModal.resolve(true)">
              {{ confirmModal.confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 图片网格 -->
    <div class="page-body">
      <div v-if="loading" class="empty-state"><div class="empty-icon">◌</div>加载中…</div>
      <div v-else-if="wallpapers.length === 0" class="empty-state"><div class="empty-icon">□</div>暂无下载记录</div>
      <div class="gallery-grid" v-else>
        <div
          class="gallery-item"
          v-for="w in wallpapers" :key="w.id"
          :class="{ 'gallery-item--dup': w.is_duplicate, 'gallery-item--selected': selectedIds.includes(w.id) }"
        >
          <div class="img-wrapper">
            <label class="select-box">
              <input type="checkbox" :checked="selectedIds.includes(w.id)" @change="toggleSelect(w.id)" />
            </label>

            <!-- 动态视频 -->
            <template v-if="w.wallpaper_type === 'dynamic'">
              <!-- 已转换为动态 WebP/GIF：直接 <img> 自动循环，无需 JS -->
              <img
                v-if="w.converted_url"
                class="gallery-img"
                :src="encodeFileUrl(w.converted_url)"
                loading="lazy"
                :title="`已转换: ${w.converted_path}`"
                @error="e => e.currentTarget.style.display='none'"
              />
              <!-- 未转换：原始 MP4，悬停时播放 -->
              <video
                v-else-if="w.file_url"
                class="gallery-img"
                :src="encodeFileUrl(w.file_url)"
                preload="none"
                muted loop playsinline
                @mouseenter="e => e.target.play()"
                @mouseleave="e => { e.target.pause(); e.target.currentTime = 0 }"
              />
              <!-- 悬停提示遮罩（转换后不显示）-->
              <div
                v-if="!w.converted_url"
                class="video-hint-mask"
                :class="{ 'video-hint-mask--has-file': !!w.file_url }"
              >
                <span class="video-play-icon">▶</span>
                <span class="video-hint-text" v-if="w.file_url">悬停播放</span>
                <span class="video-duration" v-if="w.video_duration">{{ fmtDuration(w.video_duration) }}</span>
              </div>
              <!-- 已转换标记 + 浏览器查看 -->
              <div v-if="w.converted_url" class="converted-badge" @click.stop="openInBrowser(w.converted_url)" title="在浏览器中直接查看动态 WebP">WebP ↗</div>
            </template>

            <!-- 静态图 -->
            <template v-else>
              <!-- 优先显示转换后图片 -->
              <img
                v-if="w.converted_url || w.file_url"
                :src="encodeFileUrl(w.converted_url || w.file_url)"
                class="gallery-img"
                loading="lazy"
                @error="e => e.currentTarget.style.display='none'"
              />
              <div class="img-placeholder" :class="{ 'img-placeholder--hidden': w.converted_url || w.file_url }">
                <span>○</span>
              </div>
              <div v-if="w.converted_url" class="converted-badge" @click.stop="openInBrowser(w.converted_url)" title="在浏览器中直接查看">WebP ↗</div>
            </template>

            <div class="img-overlay">
              <span class="res-badge font-mono">{{ w.resolution }}</span>
              <div class="overlay-actions">
                <button class="btn btn--sm convert-btn" @click.stop="convertOne(w)" title="转换格式">⇄</button>
                <a v-if="w.file_url" class="btn btn--sm" :href="encodeFileUrl(w.file_url)" target="_blank" @click.stop title="在浏览器查看原文件">↗</a>
                <button class="btn btn--sm btn--danger del-btn" @click.stop="deleteWallpaper(w.id)">删除</button>
              </div>
            </div>
          </div>

          <div class="gallery-meta">
            <div class="gallery-tags">
              <!-- 分类名称标签 -->
              <span class="tag tag--grey cat-tag" v-if="w.category">{{ w.category }}</span>
              <!-- 色系标签（带颜色色点）-->
              <span class="tag color-theme-tag" v-if="w.color_theme"
                :style="{ borderColor: getThemeColor(w.color_theme) + '55' }">
                <span class="color-dot" :style="{ background: getThemeColor(w.color_theme) }"></span>
                {{ w.color_theme }}
              </span>
              <span class="tag tag--info" v-if="w.wallpaper_type === 'dynamic'">动态</span>
              <span class="tag tag--ok" v-if="w.is_original === true" :title="fileSizeTooltip(w)">原图</span>
              <span class="tag tag--warn" v-else-if="w.is_original === false" :title="fileSizeTooltip(w)">预览图</span>
              <span class="tag tag--ok" v-if="uploadCount(w)">已上传{{ uploadCount(w) }}</span>
              <span class="tag tag--err" v-if="w.is_duplicate">重复</span>
            </div>

            <!-- 统计行：分辨率 · 大小 · 时长 · 下载量 · 收藏量 -->
            <div class="stats-row">
              <span v-if="w.resolution" class="stat">{{ w.resolution }}</span>
              <span v-if="w.file_size" class="stat stat--size">{{ formatBytes(w.file_size) }}</span>
              <span v-if="w.file_mb && w.file_size" class="stat stat--api" :title="`API标注大小: ${w.file_mb}`">
                API {{ w.file_mb }}
              </span>
              <span v-if="w.video_duration" class="stat stat--dur">⏱ {{ fmtDuration(w.video_duration) }}</span>
              <span v-if="w.hot_score" class="stat stat--down">↓{{ formatCount(w.hot_score) }}</span>
              <span v-if="w.favor_count" class="stat stat--fav">♥{{ formatCount(w.favor_count) }}</span>
            </div>

            <!-- 图床上传链接 -->
            <div class="upload-badges" v-if="Object.keys(w.upload_records || {}).length">
              <a v-for="(rec, key) in w.upload_records" :key="key"
                class="upload-badge" :href="rec.url" target="_blank" rel="noreferrer">
                {{ rec.profile_name || key }}<template v-if="rec.format_key && rec.format_key !== 'profile'"> · {{ rec.format_label || rec.format_key.toUpperCase() }}</template>
              </a>
            </div>
          </div>
        </div>
      </div>

      <div class="pagination" v-if="totalPages > 1">
        <button class="btn btn--sm" @click="page--; loadGallery()" :disabled="page <= 1">← 上一页</button>
        <span class="page-info font-mono">{{ page }} / {{ totalPages }}</span>
        <button class="btn btn--sm" @click="page++; loadGallery()" :disabled="page >= totalPages">下一页 →</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { galleryApi, convertApi } from '../api'

// ── 元数据（来自 API，用于色系颜色渲染）──────────
const metaColorMap = ref({})   // colorName → hex

// ── 列表状态 ──────────────────────────────────────
const wallpapers   = ref([])
const total        = ref(0)
const page         = ref(1)
const pageSize     = 60
const loading      = ref(false)
const dupResult    = ref(null)
const dupCount     = ref(0)
const categories   = ref([])
const colorThemes  = ref([])
const selectedIds  = ref([])
const deleting     = ref(false)
const dangerPanelOpen      = ref(false)
const batchDeleteFile      = ref(true)
const deleteCategoryTarget = ref('')
const deleteResult         = ref(null)

const filters = ref({
  search: '', wallpaper_type: '', category: '', color_theme: '',
  screen_orientation: '', resolution_preset: '', min_height: null,
})

const confirmModal = ref({ visible: false, title: '', message: '', confirmText: '确认', resolve: null })

// ── Computed ──────────────────────────────────────
const totalPages = computed(() => Math.ceil(total.value / pageSize))
const activeFilterCount = computed(() =>
  [filters.value.wallpaper_type, filters.value.category, filters.value.color_theme,
   filters.value.screen_orientation, filters.value.min_height].filter(Boolean).length
)

// ── 色系颜色映射 ─────────────────────────────────
const COLOR_FALLBACK = {
  '偏蓝':'#1C8DB5', '偏绿':'#318929', '偏红':'#6C1B1B',
  '灰/白':'#aeaeae', '紫/粉':'#9f2fc4', '暗色':'#303030',
  '偏黄':'#C2A72D', '其他颜色':'#888888',
}

function getThemeColor(name) {
  return metaColorMap.value[name] || COLOR_FALLBACK[name] || '#6b7280'
}

// ── 工具函数 ──────────────────────────────────────
function formatCount(n) {
  if (!n) return ''
  if (n >= 10000) return (n / 10000).toFixed(1) + 'w'
  if (n >= 1000)  return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

function fmtDuration(secs) {
  if (!secs) return ''
  const s = Math.round(secs)
  const m = Math.floor(s / 60), r = s % 60
  return m > 0 ? `${m}:${String(r).padStart(2, '0')}` : `${r}s`
}

function formatBytes(bytes) {
  if (!bytes) return ''
  if (bytes >= 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB'
  if (bytes >= 1024)        return (bytes / 1024).toFixed(0) + ' KB'
  return bytes + ' B'
}

function fileSizeTooltip(w) {
  if (!w.file_mb || !w.file_size) return ''
  return `API标注: ${w.file_mb}  实际下载: ${formatBytes(w.file_size)}`
}

function uploadCount(w) {
  return Object.keys(w.upload_records || {}).length || 0
}

function encodeFileUrl(url) {
  if (!url) return ''
  return url.split('/').map((seg, i) => i === 0 ? seg : encodeURIComponent(seg)).join('/')
}

function showConfirm(title, message = '', confirmText = '确认') {
  return new Promise(resolve => {
    confirmModal.value = {
      visible: true, title, message, confirmText,
      resolve: v => { confirmModal.value.visible = false; resolve(v) },
    }
  })
}

// ── 筛选 ──────────────────────────────────────────
let debounceTimer = null
function debounceLoad() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(resetAndLoad, 350)
}
function resetAndLoad() { page.value = 1; loadGallery() }
function setFilter(key, value) { filters.value[key] = value; resetAndLoad() }
function setResolution(h, preset) {
  filters.value.min_height = h
  filters.value.resolution_preset = preset
  resetAndLoad()
}
function clearResolution() {
  filters.value.min_height = null
  filters.value.resolution_preset = ''
  resetAndLoad()
}
function clearAllFilters() {
  Object.assign(filters.value, {
    wallpaper_type:'', category:'', color_theme:'',
    screen_orientation:'', min_height:null, resolution_preset:'', search:'',
  })
  resetAndLoad()
}

// ── 数据加载 ──────────────────────────────────────
async function loadGallery() {
  loading.value = true
  try {
    const res = await galleryApi.list({
      page: page.value, page_size: pageSize,
      search: filters.value.search          || undefined,
      wallpaper_type: filters.value.wallpaper_type   || undefined,
      category:       filters.value.category          || undefined,
      color_theme:    filters.value.color_theme        || undefined,
      screen_orientation: filters.value.screen_orientation || undefined,
      min_height:     filters.value.min_height          || undefined,
    })
    wallpapers.value = res.wallpapers
    total.value      = res.total
  } finally {
    loading.value = false
  }
}

async function loadCategories() {
  const res = await galleryApi.categories()
  categories.value = res.categories || []
}

async function loadColorThemes() {
  const res = await galleryApi.colorThemes()
  colorThemes.value = res.color_themes || []
}

async function loadMeta() {
  try {
    const res = await galleryApi.wallpaperMeta()
    const map = {}
    for (const c of (res.colors || [])) map[c.name] = c.hex
    metaColorMap.value = map
  } catch { /* ignore */ }
}

// ── 选择 ──────────────────────────────────────────
function toggleSelect(id) {
  if (selectedIds.value.includes(id))
    selectedIds.value = selectedIds.value.filter(i => i !== id)
  else
    selectedIds.value = [...selectedIds.value, id]
}

function toggleSelectCurrentPage(checked) {
  if (checked) {
    const union = new Set([...selectedIds.value, ...wallpapers.value.map(w => w.id)])
    selectedIds.value = [...union]
  } else {
    const pageIds = new Set(wallpapers.value.map(w => w.id))
    selectedIds.value = selectedIds.value.filter(id => !pageIds.has(id))
  }
}

// ── 格式转换 ───────────────────────────────────────
const converting = ref(false)

function openInBrowser(url) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

async function convertOne(w) {
  converting.value = true
  try {
    const res = await convertApi.batchConvert({ scope: 'selected', wallpaper_ids: [w.id] })
    if (res.success_count > 0) {
      const item = res.items?.[0]
      if (item?.converted_path) {
        w.converted_path = item.converted_path
        w.converted_url = `/downloads/${item.converted_path}`
        if (item.deleted_original) {
          w.local_path = item.converted_path
          w.file_url = `/downloads/${item.converted_path}`
        }
      }
    } else {
      alert('转换失败，请检查是否已安装 imageio-ffmpeg 并确认格式转换已在配置中启用。')
    }
  } catch (e) {
    alert(`转换失败: ${e.message}`)
  } finally {
    converting.value = false
  }
}

// ── 删除 ──────────────────────────────────────────
async function deleteWallpaper(id) {
  const ok = await showConfirm('删除壁纸', '将同时删除本地文件，此操作不可撤销。', '确认删除')
  if (!ok) return
  await galleryApi.delete(id)
  selectedIds.value = selectedIds.value.filter(i => i !== id)
  await loadGallery()
}

async function batchDeleteSelected() {
  if (!selectedIds.value.length) return
  const ok = await showConfirm(
    `删除已选 ${selectedIds.value.length} 张`,
    batchDeleteFile.value ? '将同时删除本地文件，不可撤销。' : '仅删除记录，保留本地文件。',
    '确认删除',
  )
  if (!ok) return
  deleting.value = true
  deleteResult.value = null
  try {
    const res = await galleryApi.batchDelete({ scope:'selected', wallpaper_ids:selectedIds.value, delete_file:batchDeleteFile.value })
    deleteResult.value = res
    selectedIds.value = []
    await loadGallery()
  } finally { deleting.value = false }
}

async function batchDeleteByCategory() {
  if (!deleteCategoryTarget.value) return
  const ok = await showConfirm(
    `删除分类「${deleteCategoryTarget.value}」的全部图片`,
    batchDeleteFile.value ? '将同时删除本地文件，不可撤销。' : '仅删除记录，保留本地文件。',
    '确认删除',
  )
  if (!ok) return
  deleting.value = true
  deleteResult.value = null
  try {
    const res = await galleryApi.batchDelete({ scope:'category', category:deleteCategoryTarget.value, delete_file:batchDeleteFile.value })
    deleteResult.value = res
    deleteCategoryTarget.value = ''
    await Promise.all([loadGallery(), loadCategories()])
  } finally { deleting.value = false }
}

async function batchDeleteAll() {
  const ok = await showConfirm(
    `清空全部 ${total.value} 张壁纸`,
    `${batchDeleteFile.value ? '将同时删除所有本地文件，' : ''}此操作不可撤销，请确认！`,
    '我已了解，清空全部',
  )
  if (!ok) return
  deleting.value = true
  deleteResult.value = null
  try {
    const res = await galleryApi.batchDelete({ scope:'all', delete_file:batchDeleteFile.value })
    deleteResult.value = res
    selectedIds.value = []
    await Promise.all([loadGallery(), loadCategories(), loadColorThemes()])
  } finally { deleting.value = false }
}

// ── 重复管理 ──────────────────────────────────────
async function scanDups() {
  const res = await galleryApi.scanDuplicates()
  dupResult.value = res
  dupCount.value  = res.total_duplicates
}

async function cleanDups() {
  const ok = await showConfirm(`清理 ${dupCount.value} 个重复文件`, '此操作不可撤销。', '确认清理')
  if (!ok) return
  const res = await galleryApi.cleanDuplicates(false)
  dupResult.value = null; dupCount.value = 0
  deleteResult.value = { deleted_count: res.cleaned, file_failed: 0 }
  await loadGallery()
}

// ── 挂载 ──────────────────────────────────────────
onMounted(() => {
  Promise.all([loadGallery(), loadCategories(), loadColorThemes(), loadMeta()])
})
</script>

<style scoped>
.header-actions { display: flex; gap: 8px; }

/* ── 筛选面板 ────────────────────────────────── */
.filter-panel {
  padding: 12px 32px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
  display: flex; flex-direction: column; gap: 8px;
}

.filter-row {
  display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}
.filter-row--search { gap: 10px; }

.filter-search { max-width: 280px; }
.filter-stats  { font-size: 12px; color: var(--text-3); margin-left: auto; }

.filter-label {
  font-size: 10px; color: var(--text-3);
  text-transform: uppercase; letter-spacing: .06em;
  font-family: var(--font-ui); white-space: nowrap;
}

.filter-group { display: flex; align-items: center; gap: 8px; }
.filter-group--wide { flex: 1; min-width: 0; }

.filter-divider { width: 1px; height: 20px; background: var(--border); flex-shrink: 0; }

.chip-group { display: flex; gap: 4px; flex-wrap: wrap; }
.chip-group--scroll { flex-wrap: nowrap; overflow-x: auto; padding-bottom: 2px; }
.chip-group--scroll::-webkit-scrollbar { height: 3px; }

.chip {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 4px 10px; border-radius: 16px;
  border: 1px solid var(--border); background: transparent;
  color: var(--text-2); font-size: 12px; cursor: pointer;
  transition: all .15s; white-space: nowrap;
}
.chip:hover { border-color: var(--accent); color: var(--accent); }
.chip--active { border-color: var(--accent); color: var(--accent); background: var(--accent-glow); }
.chip--color  { padding-left: 7px; }

.chip-count { font-size: 10px; opacity: .6; font-family: var(--font-ui); margin-left: 2px; }
.chip-icon  { font-size: 9px; line-height: 1; }

.color-swatch {
  width: 10px; height: 10px; border-radius: 50%;
  display: inline-block; flex-shrink: 0; border: 1px solid rgba(0,0,0,.1);
}

.orient-icon { display: inline-block; border: 1.5px solid currentColor; border-radius: 2px; }
.orient-icon--land { width: 12px; height: 8px; }
.orient-icon--port { width: 7px; height: 11px; }

.res-dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: currentColor; opacity: .5; }
.res-dot--2k { width: 8px; height: 8px; opacity: .7; }
.res-dot--4k { width: 10px; height: 10px; opacity: .9; }

/* 活跃筛选标签 */
.active-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.active-tag {
  font-size: 11px; padding: 2px 8px; border-radius: 12px;
  background: var(--accent-glow); color: var(--accent);
  border: 1px solid var(--accent); cursor: pointer;
  font-family: var(--font-ui);
}
.clear-all-btn {
  font-size: 11px; padding: 2px 8px; background: none;
  border: 1px solid var(--border-hi); border-radius: 12px;
  color: var(--text-2); cursor: pointer;
}
.clear-all-btn:hover { border-color: var(--red); color: var(--red); }

/* ── 重复提示 ──────────────────────────────── */
.dup-banner {
  padding: 10px 32px; background: rgba(240,90,90,.08);
  border-bottom: 1px solid rgba(240,90,90,.2);
  font-size: 13px; color: var(--red);
}

/* ── 批量删除 ──────────────────────────────── */
.danger-panel { margin: 14px 32px 0; }
.danger-panel__head {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 16px; cursor: pointer; user-select: none;
}
.danger-panel__title { font-size: 12px; color: var(--red); font-family: var(--font-ui); text-transform: uppercase; letter-spacing: .05em; }
.danger-panel__toggle { font-size: 11px; color: var(--text-3); }

.danger-options { padding: 12px 16px 0; }
.check-label { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; }
.check-label input { accent-color: var(--accent); }

.danger-actions { padding: 12px 16px; display: flex; flex-wrap: wrap; gap: 12px; border-top: 1px solid var(--border); }
.danger-action { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex: 1; min-width: 200px; }
.danger-action__title { font-size: 13px; }
.danger-action__sub   { font-size: 11px; color: var(--text-3); margin-top: 2px; }
.delete-result { padding: 10px 16px; font-size: 12px; color: var(--green); border-top: 1px solid var(--border); }

.select--sm { font-size: 12px; padding: 4px 28px 4px 8px; }

/* ── 选择工具栏 ────────────────────────────── */
.select-toolbar {
  display: flex; align-items: center; gap: 10px;
  padding: 8px 32px; border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
}
.selected-count { font-size: 12px; color: var(--accent); font-family: var(--font-ui); }

/* ── 图片网格 ──────────────────────────────── */
.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 16px;
}

.gallery-item {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  transition: border-color .15s;
}
.gallery-item:hover   { border-color: var(--border-hi); }
.gallery-item--dup    { border-color: rgba(240,90,90,.4); }
.gallery-item--selected { border-color: var(--accent); }

/* 图片区 */
.img-wrapper { position: relative; aspect-ratio: 16/9; background: var(--bg-base); overflow: hidden; }
.gallery-img { width: 100%; height: 100%; object-fit: cover; display: block; transition: transform .2s; }
.gallery-item:hover .gallery-img { transform: scale(1.03); }

.img-placeholder {
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 24px; color: var(--text-3);
}
.img-placeholder--hidden { display: none; }

/* 视频悬停提示遮罩 */
.video-hint-mask {
  position: absolute; inset: 0;
  display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 4px;
  background: rgba(0, 0, 0, .35);
  pointer-events: none;
  transition: opacity .2s;
}
.video-hint-mask--has-file .video-play-icon { font-size: 28px; color: rgba(255,255,255,.9); }
.video-hint-text { font-size: 10px; color: rgba(255,255,255,.7); font-family: var(--font-ui); }
.video-duration {
  position: absolute; bottom: 6px; right: 8px;
  font-size: 10px; font-family: var(--font-ui);
  color: #fff; background: rgba(0,0,0,.6);
  padding: 1px 5px; border-radius: 3px;
}
/* 悬停时隐藏提示（视频正在播放） */
.gallery-item:hover .video-hint-mask { opacity: 0; }

.img-overlay {
  position: absolute; inset: 0; background: rgba(0,0,0,.5);
  display: flex; flex-direction: column; align-items: flex-end; justify-content: space-between;
  padding: 8px; opacity: 0; transition: opacity .15s;
}
.gallery-item:hover .img-overlay { opacity: 1; }

.res-badge {
  background: rgba(0,0,0,.6); color: #fff; font-size: 10px;
  padding: 2px 6px; border-radius: 4px;
}

.overlay-actions { display: flex; gap: 4px; align-items: center; }
.convert-btn { font-size: 11px; padding: 3px 8px; color: #a78bfa; border-color: rgba(167,139,250,.4); }
.convert-btn:hover { background: rgba(167,139,250,.15); border-color: #a78bfa; color: #a78bfa; }

.select-box {
  position: absolute; top: 6px; left: 6px; z-index: 2; cursor: pointer;
}
.select-box input { accent-color: var(--accent); width: 14px; height: 14px; }

.del-btn { font-size: 11px; padding: 3px 8px; }

/* 已转换徽章 */
.converted-badge {
  position: absolute; top: 6px; right: 6px; z-index: 1;
  font-size: 9px; font-family: var(--font-ui); font-weight: 700;
  padding: 1px 5px; border-radius: 3px;
  background: rgba(167,139,250,.85); color: #fff; letter-spacing: .05em;
}

/* 元信息区 */
.gallery-meta { padding: 10px 12px; display: flex; flex-direction: column; gap: 6px; }

.gallery-tags { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }

.cat-tag { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 色系标签（带颜色色点）*/
.color-theme-tag {
  display: inline-flex; align-items: center; gap: 4px;
  border: 1px solid;
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 11px;
  font-family: var(--font-ui);
  color: var(--text-2);
  background: var(--bg-hover);
}
.color-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }

/* 统计行 */
.stats-row {
  display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
  font-size: 10px; font-family: var(--font-ui); color: var(--text-3);
}
.stat { display: inline-flex; align-items: center; }
.stat--size { color: var(--text-2); }
.stat--api  { color: var(--text-3); font-style: italic; }
.stat--down { color: var(--accent); opacity: .85; }
.stat--fav  { color: #e95d8a; opacity: .9; }
.stat--dur  { color: #a78bfa; }

/* 上传徽章 */
.upload-badges { display: flex; flex-wrap: wrap; gap: 4px; }
.upload-badge {
  font-size: 10px; padding: 2px 6px;
  background: var(--accent-glow); color: var(--accent);
  border: 1px solid var(--accent-dim); border-radius: 3px;
  text-decoration: none; font-family: var(--font-ui);
}

/* ── 分页 ──────────────────────────────────── */
.pagination {
  margin-top: 24px; display: flex; align-items: center;
  justify-content: center; gap: 12px;
}
.page-info { font-size: 12px; color: var(--text-3); }

/* ── 确认对话框 ─────────────────────────────── */
.modal-overlay {
  position: fixed; inset: 0; background: rgba(0,0,0,.6);
  display: flex; align-items: center; justify-content: center; z-index: 9999;
}
.modal-box {
  background: var(--bg-card); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 24px; min-width: 320px; max-width: 480px;
}
.modal-title   { font-size: 16px; font-weight: 600; margin-bottom: 10px; }
.modal-message { font-size: 13px; color: var(--text-2); margin-bottom: 20px; line-height: 1.6; }
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; }
</style>
