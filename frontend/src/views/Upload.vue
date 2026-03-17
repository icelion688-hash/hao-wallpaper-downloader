<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-title">图床上传 <small>配置与批量上传</small></h1>
        <div class="page-subtitle">配置上传渠道（Telegram / HuggingFace），并批量上传已下载壁纸到图床</div>
      </div>
      <button class="btn btn--primary" @click="saveSettings" :disabled="saving">
        {{ saving ? '保存中…' : '保存配置' }}
      </button>
    </div>

    <div class="page-body">
      <!-- 任务默认 Profile -->
      <div class="card section-card">
        <div class="card-header">任务默认上传配置</div>
        <div class="section-body">
          <div class="form-row">
            <label>下载任务自动上传使用的 Profile</label>
            <select class="select" v-model="settings.task_profile">
              <option v-for="p in settings.profiles" :key="p.key" :value="p.key">
                {{ p.name }} ({{ p.key }})
              </option>
            </select>
          </div>
        </div>
      </div>

      <!-- Profile 配置 -->
      <div class="card section-card" v-if="settings.profiles.length">
        <div class="card-header">上传配置（Profiles）</div>
        <div class="profile-layout">
          <!-- 左侧 Profile 列表 -->
          <div class="profile-list">
            <div
              v-for="p in settings.profiles" :key="p.key"
              class="profile-tab"
              :class="{ 'profile-tab--active': activeKey === p.key }"
              @click="activeKey = p.key"
            >
              <div class="profile-tab__name">{{ p.name }}</div>
              <div class="profile-tab__meta">
                <span class="tag" :class="p.enabled ? 'tag--ok' : 'tag--grey'">{{ p.enabled ? '启用' : '禁用' }}</span>
                <span class="profile-channel">{{ p.channel }}</span>
              </div>
            </div>
          </div>

          <!-- 右侧编辑器 -->
          <div class="profile-editor" v-if="activeProfile">
            <div class="editor-topbar">
              <div class="editor-title">{{ activeProfile.name }}</div>
              <label class="check-label">
                <input type="checkbox" v-model="activeProfile.enabled" />
                启用此 Profile
              </label>
            </div>

            <!-- 基础字段 -->
            <div class="field-grid">
              <div class="form-row">
                <label>配置名称</label>
                <input class="input" v-model="activeProfile.name" />
              </div>
              <div class="form-row">
                <label>上传渠道</label>
                <select class="select" v-model="activeProfile.channel">
                  <option value="telegram">telegram</option>
                  <option value="huggingface">huggingface</option>
                </select>
              </div>
              <div class="form-row form-row--full">
                <label>base_url（图床地址）</label>
                <input class="input" v-model="activeProfile.base_url" placeholder="https://imgbed.lacexr.com" />
              </div>
              <div class="form-row form-row--full">
                <label>api_token</label>
                <input class="input" type="password" v-model="activeProfile.api_token" placeholder="imgbed_xxx" />
              </div>
            </div>

            <!-- 上传模式 -->
            <div class="mode-row">
              <button class="btn btn--sm" type="button"
                :class="{ 'btn--primary': isLossless(activeProfile) }"
                @click="applyLossless(activeProfile)">原图直传</button>
              <button class="btn btn--sm" type="button"
                :class="{ 'btn--primary': !isLossless(activeProfile) }"
                @click="applyCompressed(activeProfile)">压缩 WebP</button>
              <span class="mode-hint">{{ isLossless(activeProfile) ? '保持原始格式，不做任何压缩' : '转 WebP 并压缩到目标大小' }}</span>
            </div>

            <!-- 压缩配置 -->
            <div class="field-grid" v-if="!isLossless(activeProfile)">
              <div class="form-row">
                <label>服务端压缩</label>
                <input type="checkbox" v-model="activeProfile.server_compress" class="chk" />
              </div>
              <div class="form-row">
                <label>本地预处理</label>
                <input type="checkbox" v-model="activeProfile.image_processing.enabled" class="chk" />
              </div>
              <div class="form-row">
                <label>起始质量</label>
                <input class="input" type="number" v-model.number="activeProfile.image_processing.quality" min="1" max="100" />
              </div>
              <div class="form-row">
                <label>最低质量</label>
                <input class="input" type="number" v-model.number="activeProfile.image_processing.min_quality" min="1" max="100" />
              </div>
              <div class="form-row">
                <label>压缩阈值 (MB)</label>
                <input class="input" type="number" step="0.1" v-model.number="activeProfile.image_processing.threshold_mb" />
              </div>
              <div class="form-row">
                <label>目标大小 (MB)</label>
                <input class="input" type="number" step="0.1" v-model.number="activeProfile.image_processing.target_mb" />
              </div>
            </div>

            <!-- 目录配置 -->
            <div class="sub-section">
              <div class="sub-section__title">上传目录配置</div>

              <!-- 路径模板 -->
              <div class="form-row form-row--full">
                <label>
                  路径模板
                  <span class="label-hint">（非空时优先，支持变量）</span>
                </label>
                <input class="input" v-model="activeProfile.folder_pattern"
                  placeholder="留空则按下方固定目录，例：bg/{type}/{year}/{month}" />
              </div>
              <div class="var-hint">
                可用变量：
                <code>{type}</code> 类型(static/dynamic) &nbsp;
                <code>{category}</code> 分类名 &nbsp;
                <code>{year}</code> 年份 &nbsp;
                <code>{month}</code> 月份(01-12) &nbsp;
                <code>{date}</code> 日期(20250317)
              </div>

              <!-- 固定目录（folder_pattern 为空时生效） -->
              <div class="field-grid dir-grid">
                <div class="form-row">
                  <label>横图目录</label>
                  <input class="input" v-model="activeProfile.folder_landscape" placeholder="bg/pc" />
                </div>
                <div class="form-row">
                  <label>竖图目录</label>
                  <input class="input" v-model="activeProfile.folder_portrait" placeholder="bg/mb" />
                </div>
                <div class="form-row">
                  <label>动态图目录</label>
                  <input class="input" v-model="activeProfile.folder_dynamic" placeholder="bg/dynamic" />
                </div>
              </div>
            </div>

            <!-- 上传过滤 -->
            <div class="sub-section">
              <div class="sub-section__title">上传过滤</div>
              <div class="field-grid">
                <div class="form-row">
                  <label>最小宽度 (px)</label>
                  <input class="input" type="number" min="0"
                    :value="activeProfile.upload_filter.min_width || ''"
                    @input="activeProfile.upload_filter.min_width = $event.target.value ? +$event.target.value : null"
                    placeholder="不限" />
                </div>
                <div class="form-row">
                  <label>最小高度 (px)</label>
                  <input class="input" type="number" min="0"
                    :value="activeProfile.upload_filter.min_height || ''"
                    @input="activeProfile.upload_filter.min_height = $event.target.value ? +$event.target.value : null"
                    placeholder="不限" />
                </div>
                <div class="form-row form-row--full">
                  <label class="check-label">
                    <input type="checkbox" v-model="activeProfile.upload_filter.only_original" />
                    仅上传原图（跳过未通过 getCompleteUrl 的预览图）
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 批量上传 -->
      <div class="card section-card">
        <div class="card-header">批量上传</div>
        <div class="section-body">
          <div class="batch-row">
            <div class="batch-form">
              <div class="form-row">
                <label>选择 Profile</label>
                <select class="select" v-model="batchProfileKey">
                  <option value="">请选择</option>
                  <option v-for="p in enabledProfiles" :key="p.key" :value="p.key">
                    {{ p.name }} / {{ p.channel }}
                  </option>
                </select>
              </div>
              <div class="form-row">
                <label>筛选分类（留空=全部）</label>
                <input class="input" v-model="batchCategory" placeholder="动漫｜二次元" />
              </div>
              <label class="check-label" style="margin-top:8px">
                <input type="checkbox" v-model="batchOnlyNew" />
                仅上传尚未上传该 Profile 的壁纸
              </label>
            </div>
            <button class="btn btn--primary batch-upload-btn" @click="batchUpload" :disabled="uploading || !batchProfileKey">
              {{ uploading ? '上传中…' : '开始批量上传' }}
            </button>
          </div>

          <div class="upload-result" v-if="uploadResult">
            <span class="result-ok">✓ 成功 {{ uploadResult.success_count }}</span>
            <span class="result-skip">— 跳过 {{ uploadResult.skipped_count }}</span>
            <span class="result-fail" v-if="uploadResult.failed_count">✗ 失败 {{ uploadResult.failed_count }}</span>
            <span class="result-profile">Profile: {{ uploadResult.profile_name }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { galleryApi, settingsApi } from '../api'

const saving       = ref(false)
const uploading    = ref(false)
const activeKey    = ref('compressed_webp')
const batchProfileKey = ref('')
const batchCategory   = ref('')
const batchOnlyNew    = ref(true)
const uploadResult    = ref(null)

const settings = ref({ task_profile: 'compressed_webp', profiles: [] })

const activeProfile  = computed(() => settings.value.profiles.find(p => p.key === activeKey.value) || null)
const enabledProfiles = computed(() => settings.value.profiles.filter(p => p.enabled))

const DEFAULT_FILTER = () => ({ min_width: null, min_height: null, only_original: false })

function defaultProfiles() {
  return [
    {
      key: 'compressed_webp', name: '壁纸压缩图床', enabled: true,
      base_url: 'https://imgbed.lacexr.com', api_token: '',
      channel: 'telegram', server_compress: true,
      folder_landscape: 'bg/pc', folder_portrait: 'bg/mb',
      folder_dynamic: 'bg/dynamic', folder_pattern: '',
      upload_filter: DEFAULT_FILTER(),
      image_processing: {
        enabled: true, telegram_only: false, format: 'webp',
        quality: 86, min_quality: 72, threshold_mb: 5, target_mb: 4, disable_above_mb: 10,
      },
    },
    {
      key: 'original_lossless', name: '原图无损图床', enabled: false,
      base_url: 'https://imgbed.lacexr.com', api_token: '',
      channel: 'huggingface', server_compress: false,
      folder_landscape: 'bg/pc', folder_portrait: 'bg/mb',
      folder_dynamic: 'bg/dynamic', folder_pattern: '',
      upload_filter: { ...DEFAULT_FILTER(), only_original: true },
      image_processing: {
        enabled: false, telegram_only: false, format: 'original',
        quality: 100, min_quality: 100, threshold_mb: 5, target_mb: 4, disable_above_mb: 10,
      },
    },
  ]
}

function isLossless(p) {
  return p?.image_processing?.format === 'original' || !p?.image_processing?.enabled
}

function applyLossless(p) {
  p.server_compress = false
  p.image_processing.enabled = false
  p.image_processing.format = 'original'
}

function applyCompressed(p) {
  p.image_processing.enabled = true
  p.image_processing.format = 'webp'
}

async function loadSettings() {
  const res = await settingsApi.getUploads()
  const fallback = defaultProfiles()
  settings.value = {
    task_profile: res.task_profile || 'compressed_webp',
    profiles: (res.profiles || fallback).map(p => {
      const base = fallback.find(f => f.key === p.key) || fallback[0]
      return {
        ...base, ...p,
        image_processing: { ...base.image_processing, ...(p.image_processing || {}) },
        upload_filter: { ...DEFAULT_FILTER(), ...(p.upload_filter || {}) },
      }
    }),
  }
  if (!settings.value.profiles.find(p => p.key === activeKey.value)) {
    activeKey.value = settings.value.profiles[0]?.key || ''
  }
  if (!batchProfileKey.value) {
    batchProfileKey.value = settings.value.task_profile
  }
}

async function saveSettings() {
  saving.value = true
  try {
    const res = await settingsApi.setUploads({
      task_profile: settings.value.task_profile,
      profiles: settings.value.profiles.map(p => ({ ...p, image_processing: { ...p.image_processing } })),
    })
    settings.value = res.uploads
  } finally {
    saving.value = false
  }
}

async function batchUpload() {
  if (!batchProfileKey.value) return
  uploading.value = true
  uploadResult.value = null
  try {
    const res = await galleryApi.batchUpload({
      profile_key:      batchProfileKey.value,
      upload_scope:     'filtered',
      category:         batchCategory.value || undefined,
      only_not_uploaded: batchOnlyNew.value,
    })
    uploadResult.value = res
  } finally {
    uploading.value = false
  }
}

onMounted(loadSettings)
</script>

<style scoped>
.page-subtitle {
  font-size: 12px; color: var(--text-3); margin-top: 4px; font-family: var(--font-ui);
}

.page-body { padding: 24px 32px; display: flex; flex-direction: column; gap: 20px; }

.section-card { overflow: visible; }

.section-body { padding: 18px; display: flex; flex-direction: column; gap: 14px; }

/* Profile 布局 */
.profile-layout { display: flex; min-height: 360px; }

.profile-list {
  width: 220px; flex-shrink: 0; border-right: 1px solid var(--border);
  display: flex; flex-direction: column; padding: 8px 0;
}

.profile-tab {
  padding: 12px 16px; cursor: pointer; transition: background .12s;
  border-left: 2px solid transparent;
}
.profile-tab:hover { background: var(--bg-hover); }
.profile-tab--active { border-left-color: var(--accent); background: var(--accent-glow); }

.profile-tab__name { font-size: 13px; font-weight: 500; margin-bottom: 4px; }
.profile-tab__meta { display: flex; align-items: center; gap: 6px; }
.profile-channel   { font-size: 10px; color: var(--text-3); font-family: var(--font-ui); }

/* Profile 编辑器 */
.profile-editor { flex: 1; padding: 20px; display: flex; flex-direction: column; gap: 16px; }

.editor-topbar {
  display: flex; justify-content: space-between; align-items: center;
  padding-bottom: 14px; border-bottom: 1px solid var(--border);
}
.editor-title { font-size: 15px; font-weight: 600; }

.field-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
}
.form-row--full { grid-column: 1 / -1; }

/* 模式切换 */
.mode-row { display: flex; align-items: center; gap: 10px; }
.mode-hint { font-size: 11px; color: var(--text-3); font-family: var(--font-ui); }

.chk { accent-color: var(--accent); width: 15px; height: 15px; }

/* 批量上传 */
.batch-row { display: flex; gap: 24px; align-items: flex-start; flex-wrap: wrap; }
.batch-form { flex: 1; min-width: 280px; display: flex; flex-direction: column; gap: 10px; }

.batch-upload-btn { height: 40px; padding: 0 24px; white-space: nowrap; align-self: flex-end; }

.upload-result {
  display: flex; flex-wrap: wrap; gap: 12px; align-items: center;
  padding: 12px 16px; background: var(--bg-base); border-radius: var(--radius);
  font-size: 13px; font-family: var(--font-ui); border: 1px solid var(--border);
}
.result-ok     { color: var(--green); }
.result-skip   { color: var(--text-2); }
.result-fail   { color: var(--red); }
.result-profile { color: var(--text-3); margin-left: auto; font-size: 11px; }

.check-label { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; }
.check-label input { accent-color: var(--accent); }

/* 目录配置 / 上传过滤子区块 */
.sub-section {
  display: flex; flex-direction: column; gap: 10px;
  padding: 14px 16px; border-radius: var(--radius);
  background: var(--bg-base); border: 1px solid var(--border);
}
.sub-section__title {
  font-size: 12px; font-weight: 600; color: var(--text-2);
  text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px;
}
.label-hint { font-size: 11px; font-weight: 400; color: var(--text-3); margin-left: 4px; }

.var-hint {
  font-size: 11px; color: var(--text-3); line-height: 1.8;
  padding: 6px 10px; background: var(--bg-hover); border-radius: var(--radius);
  font-family: var(--font-ui);
}
.var-hint code {
  font-family: var(--font-mono, monospace); color: var(--accent);
  background: transparent; font-size: 11px;
}

.dir-grid { grid-template-columns: repeat(3, 1fr); gap: 12px; }

@media (max-width: 900px) { .dir-grid { grid-template-columns: 1fr 1fr; } }
@media (max-width: 700px) {
  .profile-layout { flex-direction: column; }
  .profile-list { width: 100%; border-right: none; border-bottom: 1px solid var(--border); flex-direction: row; flex-wrap: wrap; }
  .field-grid { grid-template-columns: 1fr; }
  .dir-grid { grid-template-columns: 1fr; }
}


</style>
