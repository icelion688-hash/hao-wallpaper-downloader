<template>
  <div>
    <div class="page-header">
      <h1 class="page-title">筛选配置 <small>预设下载规则</small></h1>
      <div style="display:flex;gap:8px">
        <button class="btn" @click="loadPresets">↺ 重置</button>
        <button class="btn btn--primary" @click="savePreset">保存预设</button>
      </div>
    </div>

    <div class="page-body">
      <div class="filter-layout">

        <!-- 左列 -->
        <div class="filter-col">
          <div class="card">
            <div class="card-header">基本设置</div>
            <div class="filter-body">
              <div class="form-row">
                <label>壁纸类型</label>
                <div class="radio-group">
                  <label v-for="opt in typeOpts" :key="opt.value" class="radio-label">
                    <input type="radio" v-model="cfg.wallpaper_type" :value="opt.value" />
                    {{ opt.label }}
                  </label>
                </div>
              </div>
              <div class="form-row">
                <label>屏幕方向</label>
                <div class="radio-group">
                  <label v-for="opt in orientationOpts" :key="opt.value" class="radio-label">
                    <input type="radio" v-model="cfg.screen_orientation" :value="opt.value" />
                    {{ opt.label }}
                  </label>
                </div>
                <div class="orient-hint" v-if="cfg.screen_orientation !== 'all'">
                  {{ cfg.screen_orientation === 'landscape' ? '横屏：宽 ≥ 高，适合电脑桌面（推荐同时设置最低宽度 1920）' : '竖屏：高 > 宽，适合手机壁纸（推荐同时设置最低高度 1920）' }}
                </div>
              </div>
              <div class="form-row">
                <label>排序方式</label>
                <select class="select" v-model="cfg.sort_by">
                  <option value="yesterday_hot">昨日热门</option>
                  <option value="3days_hot">近三天热门</option>
                  <option value="7days_hot">上周热门</option>
                  <option value="latest">最新</option>
                  <option value="most_views">推荐的</option>
                </select>
              </div>
              <div class="form-row">
                <label>分类（点击多选）</label>
                <div class="tag-hints" v-if="metaCategories.length">
                  <span
                    class="tag hint-tag"
                    v-for="cat in metaCategories"
                    :key="cat.id"
                    :class="categorySet.has(cat.id) ? 'tag--info' : 'tag--grey'"
                    @click="toggleCategoryId(cat.id)"
                    :title="cat.code"
                  >{{ cat.name }}</span>
                </div>
                <div v-else class="tag-hints">
                  <span class="tag tag--grey hint-tag" v-for="c in quickCategories" :key="c"
                    @click="toggleCategory(c)">{{ c }}</span>
                </div>
                <!-- 已选 UUID 列表（提示） -->
                <div v-if="categorySet.size > 0" class="selected-hint">
                  已选 {{ categorySet.size }} 个分类 · UUID 已存入预设
                </div>
              </div>
              <div class="form-row">
                <label>下载数量上限</label>
                <div style="display:flex;align-items:center;gap:10px">
                  <input class="input" type="range" v-model.number="cfg.max_count" min="10" max="1000" step="10" style="flex:1;padding:0;background:none;border:none" />
                  <span class="font-mono" style="width:44px;text-align:right;color:var(--accent)">{{ cfg.max_count }}</span>
                </div>
              </div>
              <div class="form-row">
                <label>并发下载数</label>
                <div style="display:flex;gap:8px">
                  <button class="btn btn--sm" v-for="n in [1,2,3,5,8]" :key="n"
                    :class="cfg.concurrency===n ? 'btn--primary' : ''"
                    @click="cfg.concurrency=n">{{ n }}</button>
                </div>
              </div>
            </div>
          </div>

          <div class="card" style="margin-top:14px">
            <div class="card-header">账号策略</div>
            <div class="filter-body">
              <label class="check-label">
                <input type="checkbox" v-model="cfg.vip_only" />
                仅使用 VIP 账号（优先保证质量）
              </label>
              <label class="check-label">
                <input type="checkbox" v-model="cfg.use_proxy" />
                启用代理（降低被封风险）
              </label>
            </div>
          </div>
        </div>

        <!-- 右列 -->
        <div class="filter-col">
          <div class="card">
            <div class="card-header">分辨率筛选</div>
            <div class="filter-body">
              <div class="res-row">
                <div class="form-row">
                  <label>最小宽度</label>
                  <input class="input" type="number" v-model.number="cfg.min_width" placeholder="不限" />
                </div>
                <span class="res-sep">×</span>
                <div class="form-row">
                  <label>最小高度</label>
                  <input class="input" type="number" v-model.number="cfg.min_height" placeholder="不限" />
                </div>
                <button class="btn btn--sm" @click="cfg.min_width=null; cfg.min_height=null" style="margin-top:20px">清除</button>
              </div>
              <div style="margin-top:4px">
                <div class="res-label">电脑横屏</div>
                <div class="res-presets">
                  <span class="tag hint-tag"
                    v-for="p in pcPresets" :key="p.label"
                    :class="cfg.min_width===p.w && cfg.min_height===p.h ? 'tag--info' : 'tag--grey'"
                    @click="applyRes(p)">{{ p.label }}</span>
                </div>
              </div>
              <div style="margin-top:8px">
                <div class="res-label">手机竖屏</div>
                <div class="res-presets">
                  <span class="tag hint-tag"
                    v-for="p in phonePresets" :key="p.label"
                    :class="cfg.min_width===p.w && cfg.min_height===p.h ? 'tag--info' : 'tag--grey'"
                    @click="applyRes(p)">{{ p.label }}</span>
                </div>
              </div>
            </div>
          </div>

          <div class="card" style="margin-top:14px">
            <div class="card-header">内容筛选</div>
            <div class="filter-body">
              <div class="form-row">
                <label>最低热度分（0 = 不限）</label>
                <input class="input" type="number" v-model.number="cfg.min_hot_score" placeholder="0" />
                <div class="tag-hints" style="margin-top:6px">
                  <span class="tag tag--grey hint-tag" v-for="s in hotPresets" :key="s.val"
                    :class="cfg.min_hot_score === s.val ? 'tag--info' : ''"
                    @click="cfg.min_hot_score = s.val">{{ s.label }}</span>
                </div>
                <div class="orient-hint" style="margin-top:4px">
                  热度分 = 列表接口返回的下载次数。设置阈值可过滤掉小众图片。
                </div>
              </div>
              <div class="form-row">
                <label>色系偏好（点击多选）</label>
                <div class="tag-hints" v-if="metaColors.length">
                  <span
                    class="tag hint-tag color-tag"
                    v-for="c in metaColors"
                    :key="c.id"
                    :class="colorThemesSet.has(c.id) ? 'tag--info' : 'tag--grey'"
                    @click="toggleColor(c.id)"
                  >
                    <span class="color-dot" :style="{ background: c.hex || '#888' }"></span>
                    {{ c.name }}
                  </span>
                </div>
                <div class="tag-hints" v-else>
                  <span class="tag hint-tag"
                    v-for="c in colorOpts" :key="c.value"
                    :class="colorThemesSet.has(c.value) ? 'tag--info' : 'tag--grey'"
                    @click="toggleColor(c.value)">{{ c.label }}</span>
                </div>
              </div>
              <div class="form-row">
                <label>标签黑名单（逗号分隔）</label>
                <input class="input" v-model="blacklistStr" placeholder="nsfw, blood, horror…" />
              </div>
            </div>
          </div>

          <!-- 配置预览 -->
          <div class="card" style="margin-top:14px">
            <div class="card-header">当前配置预览</div>
            <pre class="cfg-preview">{{ JSON.stringify(previewCfg, null, 2) }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { galleryApi } from '../api'

const STORAGE_KEY = 'hao_filter_preset'

const cfg = ref({
  wallpaper_type: 'all',
  screen_orientation: 'all',
  sort_by: 'yesterday_hot',
  max_count: 100,
  concurrency: 3,
  min_width: null,
  min_height: null,
  min_hot_score: 0,
  vip_only: false,
  use_proxy: true,
  color_themes: [],
  tag_blacklist: [],
  categories: [],
})

const categoriesStr = ref('')
const blacklistStr = ref('')
const colorThemesSet = ref(new Set())
// 分类 UUID Set（新格式）
const categorySet = ref(new Set())

// 来自 API 的完整分类/色系列表
const metaCategories = ref([])  // [{id, name, code}]
const metaColors = ref([])       // [{id, name, hex}]

const typeOpts = [
  { value: 'all', label: '全部' },
  { value: 'static', label: '静态' },
  { value: 'dynamic', label: '动态' },
]

const orientationOpts = [
  { value: 'all',       label: '全部' },
  { value: 'landscape', label: '电脑横屏' },
  { value: 'portrait',  label: '手机竖屏' },
]

// 旧格式兼容（API 加载失败时显示）
const quickCategories = ['anime', 'landscape', 'girl', 'nature', 'car', 'game', 'movie', 'animal', 'city', 'abstract']

const hotPresets = [
  { val: 0,    label: '不限' },
  { val: 100,  label: '100+' },
  { val: 500,  label: '500+' },
  { val: 1000, label: '1000+' },
  { val: 5000, label: '5000+（超热门）' },
]

// 旧格式兼容（API 加载失败时显示）
const colorOpts = [
  { value: 'dark',     label: '暗色系' },
  { value: 'light',    label: '亮色系' },
  { value: 'colorful', label: '彩色' },
  { value: 'minimal',  label: '极简' },
  { value: 'warm',     label: '暖色' },
  { value: 'cool',     label: '冷色' },
]

const pcPresets = [
  { label: '1920×1080', w: 1920, h: 1080 },
  { label: '2560×1440', w: 2560, h: 1440 },
  { label: '3840×2160', w: 3840, h: 2160 },
]

const phonePresets = [
  { label: '1080×1920', w: 1080, h: 1920 },
  { label: '1170×2532', w: 1170, h: 2532 },
  { label: '1440×3200', w: 1440, h: 3200 },
]

// 切换分类 UUID
function toggleCategoryId(id) {
  const s = categorySet.value
  if (s.has(id)) s.delete(id)
  else s.add(id)
  categorySet.value = new Set(s)
}

// 旧格式：字符串分类切换（API 未加载时使用）
function toggleCategory(c) {
  const arr = categoriesStr.value ? categoriesStr.value.split(',').map(s => s.trim()).filter(Boolean) : []
  const i = arr.indexOf(c)
  if (i >= 0) arr.splice(i, 1)
  else arr.push(c)
  categoriesStr.value = arr.join(', ')
}

function toggleColor(v) {
  if (colorThemesSet.value.has(v)) colorThemesSet.value.delete(v)
  else colorThemesSet.value.add(v)
}

function applyRes(p) {
  cfg.value.min_width  = p.w
  cfg.value.min_height = p.h
  // 自动联动方向选择
  if (p.w > p.h && cfg.value.screen_orientation === 'all') cfg.value.screen_orientation = 'landscape'
  if (p.h > p.w && cfg.value.screen_orientation === 'all') cfg.value.screen_orientation = 'portrait'
}

// 最终预设：合并 UUID 分类和旧格式字符串分类
const previewCfg = computed(() => {
  // 优先使用 UUID 分类（新格式），若未选则用旧字符串格式
  const uuidCats = [...categorySet.value]
  const strCats  = categoriesStr.value ? categoriesStr.value.split(',').map(s => s.trim()).filter(Boolean) : []
  return {
    ...cfg.value,
    categories:    uuidCats.length ? uuidCats : strCats,
    tag_blacklist: blacklistStr.value ? blacklistStr.value.split(',').map(s => s.trim()).filter(Boolean) : [],
    color_themes:  [...colorThemesSet.value],
  }
})

function savePreset() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(previewCfg.value))
  alert('预设已保存')
}

function loadPresets() {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) {
    try {
      const d = JSON.parse(saved)
      cfg.value = {
        ...cfg.value,
        ...d,
        screen_orientation: d.screen_orientation || 'all',
      }
      // 判断 categories 是 UUID 格式还是旧字符串格式
      const savedCats = d.categories || []
      const isUuid = savedCats.length > 0 && savedCats[0].length === 32 && /^[0-9a-f]+$/.test(savedCats[0])
      if (isUuid) {
        categorySet.value = new Set(savedCats)
        categoriesStr.value = ''
      } else {
        categoriesStr.value = savedCats.join(', ')
        categorySet.value = new Set()
      }
      blacklistStr.value   = (d.tag_blacklist || []).join(', ')
      colorThemesSet.value = new Set(d.color_themes || [])
    } catch { /* ignore */ }
  }
}

async function loadMeta() {
  try {
    const res = await galleryApi.wallpaperMeta()
    metaCategories.value = res.categories || []
    metaColors.value     = res.colors     || []
  } catch { /* 静默失败，回退到旧格式 */ }
}

onMounted(async () => {
  loadPresets()
  await loadMeta()
})
</script>

<style scoped>
.filter-layout { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.filter-col { display: flex; flex-direction: column; }
.filter-body { padding: 16px; display: flex; flex-direction: column; gap: 16px; }

.radio-group { display: flex; gap: 14px; }
.radio-label { display: flex; align-items: center; gap: 6px; cursor: pointer; font-size: 13px; }

.tag-hints { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.hint-tag { cursor: pointer; transition: all .15s; }
.hint-tag:hover { border-color: var(--accent); color: var(--accent); }

.res-row { display: flex; align-items: flex-end; gap: 10px; }
.res-sep { color: var(--text-3); padding-bottom: 8px; }
.res-presets { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }

.check-label { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; }
.check-label input { accent-color: var(--accent); }

.cfg-preview {
  font-family: var(--font-ui);
  font-size: 11px;
  color: var(--text-2);
  background: var(--bg-base);
  padding: 14px;
  overflow-x: auto;
  line-height: 1.6;
  max-height: 200px;
  overflow-y: auto;
}

.font-mono { font-family: var(--font-ui); }

.orient-hint {
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.5;
  margin-top: 6px;
}
.res-label {
  font-size: 11px;
  color: var(--text-3);
  margin-bottom: 4px;
}

/* 色系标签内圆点 */
.color-tag { display: inline-flex; align-items: center; gap: 5px; }
.color-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 1px solid rgba(255,255,255,.15);
}

/* 已选分类提示 */
.selected-hint {
  font-size: 10px;
  color: var(--accent);
  margin-top: 6px;
  font-family: var(--font-ui);
}
</style>
