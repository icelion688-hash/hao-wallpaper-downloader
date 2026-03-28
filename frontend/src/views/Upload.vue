<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-title">图床上传 <small>配置、分类上传与远端管理</small></h1>
        <div class="page-subtitle">复用当前 Profile 直接调用图床 API，完成上传、列出、删除与索引管理。</div>
      </div>
      <button class="btn btn--primary" @click="saveSettings" :disabled="saving">
        {{ saving ? '保存中...' : '保存配置' }}
      </button>
    </div>

    <div class="page-body">
      <div class="card section-card">
        <div class="card-header">任务默认上传配置</div>
        <div class="section-body">
          <div class="field-grid">
            <div class="form-row">
              <label>下载任务自动上传使用的 Profile</label>
              <select class="select" v-model="settings.task_profile">
                <option v-for="profile in settings.profiles" :key="profile.key" :value="profile.key">
                  {{ profile.name }} ({{ profile.key }})
                </option>
              </select>
            </div>
            <div class="form-row">
              <label>画廊批量上传默认格式</label>
              <select class="select" v-model="settings.gallery_default_format">
                <option v-for="item in uploadFormatOptions" :key="item.value" :value="item.value">
                  {{ item.label }}
                </option>
              </select>
            </div>
            <div class="form-row">
              <label>自动巡检</label>
              <label class="check-label">
                <input type="checkbox" v-model="settings.upload_guard.enabled" />
                启用图库与本地上传数据的定时巡检
              </label>
            </div>
            <div class="form-row">
              <label>巡检间隔（分钟）</label>
              <input class="input" type="number" min="5" max="1440" v-model.number="settings.upload_guard.interval_minutes" />
            </div>
            <div class="form-row">
              <label>首次延迟（分钟）</label>
              <input class="input" type="number" min="0" max="1440" v-model.number="settings.upload_guard.initial_delay_minutes" />
            </div>
          </div>
          <div class="section-tip">
            自动巡检会按这里的间隔，定时检查图床索引与本地上传记录是否一致，并自动补传本地未上传或远端已缺失的图片。
          </div>
        </div>
      </div>

      <div class="card section-card" v-if="settings.profiles.length">
        <div class="card-header">上传配置（Profiles）</div>
        <div class="profile-layout">
          <div class="profile-list">
            <div
              v-for="profile in settings.profiles"
              :key="profile.key"
              class="profile-tab"
              :class="{ 'profile-tab--active': activeKey === profile.key }"
              @click="activeKey = profile.key"
            >
              <div class="profile-tab__name">{{ profile.name }}</div>
              <div class="profile-tab__meta">
                <span class="tag" :class="profile.enabled ? 'tag--ok' : 'tag--grey'">
                  {{ profile.enabled ? '启用' : '禁用' }}
                </span>
                <span class="profile-channel">{{ profile.channel }}</span>
              </div>
            </div>
          </div>

          <div v-if="activeProfile" class="profile-editor">
            <div class="editor-topbar">
              <div class="editor-title">{{ activeProfile.name }}</div>
              <label class="check-label">
                <input type="checkbox" v-model="activeProfile.enabled" />
                启用当前 Profile
              </label>
            </div>
            <div class="capability-row" v-if="activeProfile.base_url && activeProfile.api_token">
              <span class="tag" :class="capabilityLoading ? 'tag--grey' : (remoteCapabilities?.manage ? 'tag--ok' : 'tag--warn')">
                {{ capabilityLoading ? '权限检测中' : (remoteCapabilities?.manage ? 'manage 可用' : 'manage 不可用') }}
              </span>
              <span class="tag" :class="capabilityLoading ? 'tag--grey' : (remoteCapabilities?.list ? 'tag--ok' : 'tag--warn')">
                {{ capabilityLoading ? 'list 检测中' : (remoteCapabilities?.list ? 'list 可用' : 'list 不可用') }}
              </span>
              <span class="tag" :class="capabilityLoading ? 'tag--grey' : (remoteCapabilities?.channels ? 'tag--ok' : 'tag--warn')">
                {{ capabilityLoading ? 'channels 检测中' : (remoteCapabilities?.channels ? 'channels 可用' : 'channels 不可用') }}
              </span>
              <span class="capability-note" v-if="remoteCapabilities && !remoteCapabilities.manage">
                当前 Token 未检测到 `manage` 权限，上传后的自动打标、重分类与远端标签管理会受限。
              </span>
            </div>

            <div class="field-grid">
              <div class="form-row">
                <label>配置名称</label>
                <input class="input" v-model="activeProfile.name" />
              </div>
              <div class="form-row">
                <label>上传渠道</label>
                <select class="select" v-model="activeProfile.channel">
                  <option value="telegram">telegram</option>
                  <option value="cfr2">cfr2</option>
                  <option value="s3">s3</option>
                  <option value="discord">discord</option>
                  <option value="huggingface">huggingface</option>
                </select>
              </div>
              <div class="form-row">
                <label>指定渠道名</label>
                <input class="input" v-model="activeProfile.channel_name" placeholder="可选，多渠道时指定具体渠道名" />
              </div>
              <div class="form-row">
                <label>上传命名方式</label>
                <select class="select" v-model="activeProfile.upload_name_type">
                  <option value="default">default</option>
                  <option value="index">index</option>
                  <option value="origin">origin</option>
                  <option value="short">short</option>
                </select>
              </div>
              <div class="form-row form-row--full">
                <label>base_url</label>
                <input class="input" v-model="activeProfile.base_url" placeholder="https://imgbed.example.com" />
              </div>
              <div class="form-row form-row--full">
                <label>api_token</label>
                <input class="input" type="password" v-model="activeProfile.api_token" placeholder="imgbed_xxx" />
              </div>
              <div class="form-row form-row--full">
                <div class="inline-checks">
                  <label class="check-label">
                    <input type="checkbox" v-model="activeProfile.auto_retry" />
                    失败时自动切换渠道重试
                  </label>
                  <label class="check-label">
                    <input type="checkbox" v-model="activeProfile.sync_remote_tags" />
                    上传后同步标签到图床
                  </label>
                  <label class="check-label">
                    <input type="checkbox" v-model="activeProfile.server_compress" />
                    启用图床服务端压缩
                  </label>
                </div>
              </div>
            </div>

            <div class="mode-row">
              <button
                class="btn btn--sm"
                type="button"
                :class="{ 'btn--primary': isLossless(activeProfile) }"
                @click="applyLossless(activeProfile)"
              >
                原图直传
              </button>
              <button
                class="btn btn--sm"
                type="button"
                :class="{ 'btn--primary': !isLossless(activeProfile) }"
                @click="applyCompressed(activeProfile)"
              >
                压缩 WebP
              </button>
              <span class="mode-hint">
                {{ isLossless(activeProfile) ? '保留原始格式，不做本地预处理。' : '先转 WebP，再按目标大小控制体积。' }}
              </span>
            </div>

            <div class="field-grid" v-if="!isLossless(activeProfile)">
              <div class="form-row">
                <label>本地预处理</label>
                <input type="checkbox" v-model="activeProfile.image_processing.enabled" class="chk" />
              </div>
              <div class="form-row">
                <label>仅 Telegram 时预处理</label>
                <input type="checkbox" v-model="activeProfile.image_processing.telegram_only" class="chk" />
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

            <div class="sub-section">
              <div class="sub-section__title">上传目录配置</div>
              <div class="form-row form-row--full">
                <label>
                  路径模板
                  <span class="label-hint">非空时优先于固定目录，可按元数据自动分类</span>
                </label>
                <input
                  class="input"
                  v-model="activeProfile.folder_pattern"
                  placeholder="例如：wallpaper/{type}/{orientation}/{category}/{color}/{primary_tag}"
                />
              </div>
              <div class="var-hint">
                <code>{type}</code>
                <code>{orientation}</code>
                <code>{category}</code>
                <code>{type_id}</code>
                <code>{color}</code>
                <code>{color_id}</code>
                <code>{primary_tag}</code>
                <code>{tags}</code>
                <code>{originality}</code>
                <code>{resource_id}</code>
                <code>{year}</code>
                <code>{month}</code>
                <code>{date}</code>
              </div>
              <div class="preset-row">
                <button class="btn btn--sm" type="button" @click="applyFolderPattern('wallpaper/{type}/{orientation}/{category}')">
                  类型 / 横竖 / 分类
                </button>
                <button class="btn btn--sm" type="button" @click="applyFolderPattern('wallpaper/{type}/{orientation}/{category}/{color}')">
                  再加颜色
                </button>
                <button class="btn btn--sm" type="button" @click="applyFolderPattern('wallpaper/{type}/{primary_tag}/{category}')">
                  标签优先
                </button>
              </div>
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

            <div class="sub-section">
              <div class="sub-section__title">上传过滤</div>
              <div class="field-grid">
                <div class="form-row">
                  <label>最小宽度 (px)</label>
                  <input
                    class="input"
                    type="number"
                    min="0"
                    :value="activeProfile.upload_filter.min_width || ''"
                    @input="activeProfile.upload_filter.min_width = $event.target.value ? +$event.target.value : null"
                    placeholder="不限"
                  />
                </div>
                <div class="form-row">
                  <label>最小高度 (px)</label>
                  <input
                    class="input"
                    type="number"
                    min="0"
                    :value="activeProfile.upload_filter.min_height || ''"
                    @input="activeProfile.upload_filter.min_height = $event.target.value ? +$event.target.value : null"
                    placeholder="不限"
                  />
                </div>
                <div class="form-row form-row--full">
                  <label class="check-label">
                    <input type="checkbox" v-model="activeProfile.upload_filter.only_original" />
                    仅上传原图
                  </label>
                </div>
              </div>
            </div>

            <div class="sub-section">
              <div class="sub-section__title">批量上传</div>
              <div class="batch-inline-head">
                <span class="tag tag--info">{{ activeProfile.name }}</span>
                <span class="batch-inline-meta">{{ activeProfile.channel }} / {{ activeProfile.enabled ? '已启用' : '未启用' }}</span>
              </div>
              <div class="field-grid">
                <div class="form-row">
                  <label>分类筛选</label>
                  <select class="select" v-model="batchCategory" :disabled="loadingCategories">
                    <option value="">全部分类</option>
                    <option v-for="item in categoryOptions" :key="item.name" :value="item.name">
                      {{ item.name }} ({{ item.count }})
                    </option>
                  </select>
                </div>
                <div class="form-row">
                  <label>颜色筛选</label>
                  <select class="select" v-model="batchColorTheme" :disabled="loadingColorThemes">
                    <option value="">全部颜色</option>
                    <option v-for="item in colorThemeOptions" :key="item.name" :value="item.name">
                      {{ item.name }} ({{ item.count }})
                    </option>
                  </select>
                </div>
                <div class="form-row">
                  <label>壁纸类型</label>
                  <select class="select" v-model="batchWallpaperType">
                    <option value="">全部</option>
                    <option value="static">静态图</option>
                    <option value="dynamic">动态图</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>横竖方向</label>
                  <select class="select" v-model="batchOrientation">
                    <option value="">全部</option>
                    <option value="landscape">横图</option>
                    <option value="portrait">竖图</option>
                  </select>
                </div>
                <div class="form-row form-row--full">
                  <label>本次上传格式</label>
                  <select class="select" v-model="batchUploadFormat">
                    <option v-for="item in uploadFormatOptions" :key="item.value" :value="item.value">
                      {{ item.label }}
                    </option>
                  </select>
                  <div class="batch-hint">{{ batchFormatHint }}</div>
                </div>
              </div>
              <label class="check-label">
                <input type="checkbox" v-model="batchOnlyNew" />
                仅上传尚未上传该 Profile 同格式版本的壁纸
              </label>
              <label class="check-label">
                <input type="checkbox" v-model="batchUploadWithTags" />
                本次上传后同步标签到图床
              </label>
              <div class="batch-inline-actions">
                <button class="btn btn--primary" @click="batchUpload" :disabled="uploading || !activeProfile.enabled">
                  {{ uploading ? '上传中...' : '使用当前 Profile 开始批量上传' }}
                </button>
                <span class="batch-inline-warn" v-if="!activeProfile.enabled">当前 Profile 未启用，无法上传</span>
              </div>
              <div class="upload-result" v-if="uploadResult">
                <span class="result-ok">成功 {{ uploadResult.success_count }}</span>
                <span class="result-skip">跳过 {{ uploadResult.skipped_count }}</span>
                <span class="result-fail" v-if="uploadResult.failed_count">失败 {{ uploadResult.failed_count }}</span>
                <span class="result-format">格式: {{ uploadResult.upload_format_label || formatUploadFormatLabel(batchUploadFormat) }}</span>
                <span class="result-format">标签: {{ uploadResult.upload_with_tags === false ? '未同步' : '已同步' }}</span>
                <span class="result-profile">Profile: {{ uploadResult.profile_name }}</span>
              </div>
            </div>

            <div class="sub-section">
              <div class="sub-section__title">远端图床管理</div>
              <div class="manager-toolbar">
                <router-link class="btn btn--sm" to="/imgbed-manager">打开独立管理台</router-link>
                <button class="btn btn--sm" @click="loadRemoteList" :disabled="remoteLoading || !canManageRemote">
                  {{ remoteLoading ? '加载中...' : '刷新列表' }}
                </button>
                <button class="btn btn--sm" @click="loadRemoteIndexInfo" :disabled="remoteActionLoading || !canManageRemote">
                  索引信息
                </button>
                <button class="btn btn--sm" @click="rebuildRemoteIndex" :disabled="remoteActionLoading || !canManageRemote">
                  重建索引
                </button>
                <span class="manager-hint" v-if="!canManageRemote">启用 Profile 并配置 Token 后可管理远端图床。</span>
              </div>

              <div class="field-grid">
                <div class="form-row">
                  <label>目录</label>
                  <input class="input" v-model="remoteQuery.dir" placeholder="例如 wallpaper/static" />
                </div>
                <div class="form-row">
                  <label>搜索文件名</label>
                  <input class="input" v-model="remoteQuery.search" placeholder="支持关键字搜索" />
                </div>
                <div class="form-row">
                  <label>包含标签</label>
                  <input class="input" v-model="remoteQuery.includeTags" placeholder="多个标签用逗号分隔" />
                </div>
                <div class="form-row">
                  <label>排除标签</label>
                  <input class="input" v-model="remoteQuery.excludeTags" placeholder="多个标签用逗号分隔" />
                </div>
                <div class="form-row">
                  <label>存储渠道</label>
                  <select class="select" v-model="remoteQuery.channel">
                    <option value="">全部</option>
                    <option value="telegram">telegram</option>
                    <option value="cfr2">cfr2</option>
                    <option value="s3">s3</option>
                    <option value="discord">discord</option>
                    <option value="huggingface">huggingface</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>返回数量</label>
                  <select class="select" v-model.number="remoteQuery.count">
                    <option :value="20">20</option>
                    <option :value="50">50</option>
                    <option :value="100">100</option>
                    <option :value="200">200</option>
                  </select>
                </div>
                <div class="form-row form-row--full">
                  <div class="inline-checks">
                    <label class="check-label">
                      <input type="checkbox" v-model="remoteQuery.recursive" />
                      递归列出子目录
                    </label>
                  </div>
                </div>
              </div>

              <div class="manager-status" v-if="remoteIndexInfo">
                <span>总文件数: {{ remoteIndexInfo.totalFiles ?? remoteIndexInfo.sum ?? '-' }}</span>
                <span v-if="remoteIndexInfo.lastUpdated || remoteIndexInfo.indexLastUpdated">
                  最近更新: {{ formatTimestamp(remoteIndexInfo.lastUpdated || remoteIndexInfo.indexLastUpdated) }}
                </span>
              </div>
              <div class="manager-error" v-if="remoteError">{{ remoteError }}</div>

              <div class="directory-bar">
                <button class="btn btn--sm" @click="goParentDirectory" :disabled="!remoteParentDir && !remoteQuery.dir">
                  返回上级
                </button>
                <span class="directory-current">当前目录: {{ remoteQuery.dir || '/' }}</span>
              </div>

              <div v-if="remoteDirectories.length" class="directory-list">
                <button
                  v-for="directory in remoteDirectories"
                  :key="directory"
                  class="directory-chip"
                  @click="openDirectory(directory)"
                >
                  {{ directory }}
                </button>
              </div>

              <div class="remote-summary" v-if="remoteSummary">
                {{ remoteSummary }}
              </div>

              <div class="remote-table-wrap">
                <table class="remote-table" v-if="remoteFiles.length">
                  <thead>
                    <tr>
                      <th>文件</th>
                      <th>渠道</th>
                      <th>MIME</th>
                      <th>大小</th>
                      <th>时间</th>
                      <th class="remote-table__actions">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="file in remoteFiles" :key="file.name">
                      <td class="remote-name">{{ file.name }}</td>
                      <td>{{ file.metadata?.Channel || '-' }}</td>
                      <td>{{ file.metadata?.['File-Mime'] || '-' }}</td>
                      <td>{{ formatRemoteSize(file.metadata?.['File-Size']) }}</td>
                      <td>{{ formatTimestamp(file.metadata?.TimeStamp) }}</td>
                      <td class="remote-table__actions">
                        <button class="btn btn--sm btn--danger" @click="deleteRemote(file.name, false)" :disabled="remoteActionLoading">
                          删除
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
                <div v-else class="remote-empty">
                  {{ remoteLoading ? '正在加载远端文件...' : '当前条件下没有返回文件。' }}
                </div>
              </div>

              <div v-if="remoteDirectories.length" class="remote-folder-actions">
                <button class="btn btn--sm btn--danger" @click="deleteRemote(remoteQuery.dir, true)" :disabled="remoteActionLoading || !remoteQuery.dir">
                  删除当前目录
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { galleryApi, imgbedApi, settingsApi } from '../api'
import {
  applyCompressedUploadProfile,
  applyLosslessUploadProfile,
  formatUploadFormatLabel,
  isLosslessUploadProfile,
  normalizeUploadFormat,
  normalizeUploadSettings,
  uploadFormatOptions,
} from '../utils/uploadProfiles'

const saving = ref(false)
const uploading = ref(false)
const activeKey = ref('')
const batchUploadFormat = ref('profile')
const batchCategory = ref('')
const batchColorTheme = ref('')
const batchWallpaperType = ref('')
const batchOrientation = ref('')
const batchOnlyNew = ref(true)
const batchUploadWithTags = ref(true)
const uploadResult = ref(null)
const categoryOptions = ref([])
const colorThemeOptions = ref([])
const loadingCategories = ref(false)
const loadingColorThemes = ref(false)

const remoteLoading = ref(false)
const remoteActionLoading = ref(false)
const remoteError = ref('')
const remoteCapabilities = ref(null)
const capabilityLoading = ref(false)
const remoteIndexInfo = ref(null)
const remoteData = ref({ files: [], directories: [], totalCount: 0, returnedCount: 0, indexLastUpdated: null })
const remoteQuery = ref({
  dir: '',
  search: '',
  includeTags: '',
  excludeTags: '',
  recursive: false,
  count: 50,
  channel: '',
})

const settings = ref({
  task_profile: 'compressed_webp',
  gallery_default_format: 'profile',
  upload_guard: {
    enabled: true,
    interval_minutes: 30,
    initial_delay_minutes: 3,
  },
  profiles: [],
})

const activeProfile = computed(() => settings.value.profiles.find((item) => item.key === activeKey.value) || null)
const canManageRemote = computed(() => Boolean(activeProfile.value?.enabled && activeProfile.value?.api_token && activeProfile.value?.base_url))
const remoteFiles = computed(() => Array.isArray(remoteData.value?.files) ? remoteData.value.files : [])
const remoteDirectories = computed(() => Array.isArray(remoteData.value?.directories) ? remoteData.value.directories : [])
const remoteParentDir = computed(() => {
  const current = String(remoteQuery.value.dir || '').replace(/^\/+|\/+$/g, '')
  if (!current) return ''
  const parts = current.split('/').filter(Boolean)
  parts.pop()
  return parts.join('/')
})
const remoteSummary = computed(() => {
  const total = remoteData.value?.totalCount
  const returned = remoteData.value?.returnedCount
  if (typeof total !== 'number' && typeof returned !== 'number') return ''
  const totalLabel = typeof total === 'number' ? `总数 ${total}` : ''
  const returnedLabel = typeof returned === 'number' ? `本次返回 ${returned}` : ''
  return [totalLabel, returnedLabel].filter(Boolean).join(' / ')
})

const batchFormatHint = computed(() => {
  switch (normalizeUploadFormat(batchUploadFormat.value)) {
    case 'original':
      return '直接上传原始文件，不额外套用 Profile 的本地格式处理。'
    case 'webp':
      return '静态图可直接压成 WebP；动态图建议先到格式转换页生成动态 WebP。'
    case 'gif':
      return '仅上传 GIF 文件；如果当前没有 GIF，请先到格式转换页生成。'
    case 'png':
    case 'jpg':
      return '仅上传对应格式文件；如果当前没有该格式，请先生成转换文件。'
    default:
      return '沿用当前 Profile 的默认上传策略，适合日常批量上传。'
  }
})

function isLossless(profile) {
  return isLosslessUploadProfile(profile)
}

function applyLossless(profile) {
  applyLosslessUploadProfile(profile)
}

function applyCompressed(profile) {
  applyCompressedUploadProfile(profile)
}

function applyFolderPattern(pattern) {
  if (!activeProfile.value) return
  activeProfile.value.folder_pattern = pattern
}

function resolveProfileSyncRemoteTags(profile) {
  return profile?.sync_remote_tags !== false
}

function syncBatchUploadWithTagsFromProfile() {
  batchUploadWithTags.value = resolveProfileSyncRemoteTags(activeProfile.value)
}

function pickPreferredProfileKey(uploadSettings, currentKey = '') {
  const profiles = Array.isArray(uploadSettings?.profiles) ? uploadSettings.profiles : []
  if (!profiles.length) return ''
  const currentProfile = profiles.find((item) => item.key === currentKey)
  if (currentProfile) return currentProfile.key
  const taskProfile = profiles.find((item) => item.key === uploadSettings?.task_profile)
  if (taskProfile?.enabled) return taskProfile.key
  const firstEnabledProfile = profiles.find((item) => item.enabled)
  if (firstEnabledProfile) return firstEnabledProfile.key
  return taskProfile?.key || profiles[0]?.key || ''
}

function resetRemoteState() {
  remoteError.value = ''
  remoteCapabilities.value = null
  remoteIndexInfo.value = null
  remoteData.value = { files: [], directories: [], totalCount: 0, returnedCount: 0, indexLastUpdated: null }
}

function formatTimestamp(value) {
  if (!value) return '-'
  const numeric = Number(value)
  const date = Number.isFinite(numeric) && numeric > 0
    ? new Date(String(value).length === 13 ? numeric : numeric * 1000)
    : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString()
}

function formatRemoteSize(value) {
  const size = Number(value)
  if (!Number.isFinite(size) || size <= 0) return '-'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(2)} MB`
}

async function loadSettings() {
  const res = await settingsApi.getUploads()
  settings.value = normalizeUploadSettings(res)
  activeKey.value = pickPreferredProfileKey(settings.value, activeKey.value)
  batchUploadFormat.value = settings.value.gallery_default_format
  syncBatchUploadWithTagsFromProfile()
}

async function loadCategories() {
  loadingCategories.value = true
  try {
    const res = await galleryApi.categories()
    categoryOptions.value = Array.isArray(res.categories) ? res.categories : []
    if (batchCategory.value && !categoryOptions.value.some((item) => item.name === batchCategory.value)) {
      batchCategory.value = ''
    }
  } catch (error) {
    console.error('加载上传分类失败', error)
    categoryOptions.value = []
  } finally {
    loadingCategories.value = false
  }
}

async function loadColorThemes() {
  loadingColorThemes.value = true
  try {
    const res = await galleryApi.colorThemes()
    colorThemeOptions.value = Array.isArray(res.color_themes) ? res.color_themes : []
    if (batchColorTheme.value && !colorThemeOptions.value.some((item) => item.name === batchColorTheme.value)) {
      batchColorTheme.value = ''
    }
  } catch (error) {
    console.error('加载颜色筛选失败', error)
    colorThemeOptions.value = []
  } finally {
    loadingColorThemes.value = false
  }
}

async function saveSettings() {
  saving.value = true
  try {
    const res = await settingsApi.setUploads({
      task_profile: settings.value.task_profile,
      gallery_default_format: normalizeUploadFormat(settings.value.gallery_default_format),
      upload_guard: {
        enabled: settings.value.upload_guard.enabled !== false,
        interval_minutes: Math.min(1440, Math.max(5, Number(settings.value.upload_guard.interval_minutes) || 30)),
        initial_delay_minutes: Math.min(1440, Math.max(0, Number(settings.value.upload_guard.initial_delay_minutes) || 0)),
      },
      profiles: settings.value.profiles.map((profile) => ({
        ...profile,
        image_processing: { ...profile.image_processing },
        upload_filter: { ...profile.upload_filter },
      })),
    })
    settings.value = normalizeUploadSettings(res.uploads)
    activeKey.value = pickPreferredProfileKey(settings.value, activeKey.value)
    batchUploadFormat.value = normalizeUploadFormat(settings.value.gallery_default_format)
    syncBatchUploadWithTagsFromProfile()
    await loadRemoteCapabilities()
  } finally {
    saving.value = false
  }
}

async function loadRemoteCapabilities() {
  if (!activeProfile.value?.key || !canManageRemote.value) {
    remoteCapabilities.value = null
    return
  }
  capabilityLoading.value = true
  try {
    const res = await imgbedApi.capabilities(activeProfile.value.key)
    remoteCapabilities.value = res.data || null
  } catch (error) {
    remoteCapabilities.value = null
    remoteError.value = error.message
  } finally {
    capabilityLoading.value = false
  }
}

async function batchUpload() {
  if (!activeProfile.value?.key || !activeProfile.value.enabled) return
  uploading.value = true
  uploadResult.value = null
  try {
    const res = await galleryApi.batchUpload({
      profile_key: activeProfile.value.key,
      upload_format: normalizeUploadFormat(batchUploadFormat.value),
      upload_with_tags: batchUploadWithTags.value,
      upload_scope: 'filtered',
      category: batchCategory.value || undefined,
      color_theme: batchColorTheme.value || undefined,
      wallpaper_type: batchWallpaperType.value || undefined,
      screen_orientation: batchOrientation.value || undefined,
      only_not_uploaded: batchOnlyNew.value,
    })
    uploadResult.value = res
    if (canManageRemote.value) {
      await loadRemoteList()
    }
  } finally {
    uploading.value = false
  }
}

async function loadRemoteList() {
  if (!activeProfile.value?.key || !canManageRemote.value) return
  remoteLoading.value = true
  remoteError.value = ''
  try {
    const res = await imgbedApi.list(activeProfile.value.key, {
      dir: remoteQuery.value.dir || undefined,
      search: remoteQuery.value.search || undefined,
      includeTags: remoteQuery.value.includeTags || undefined,
      excludeTags: remoteQuery.value.excludeTags || undefined,
      recursive: remoteQuery.value.recursive,
      count: remoteQuery.value.count,
      channel: remoteQuery.value.channel || undefined,
    })
    remoteData.value = {
      files: Array.isArray(res.data?.files) ? res.data.files : [],
      directories: Array.isArray(res.data?.directories) ? res.data.directories : [],
      totalCount: typeof res.data?.totalCount === 'number' ? res.data.totalCount : null,
      returnedCount: typeof res.data?.returnedCount === 'number' ? res.data.returnedCount : null,
      indexLastUpdated: res.data?.indexLastUpdated || null,
    }
  } catch (error) {
    remoteError.value = error.message
    resetRemoteState()
  } finally {
    remoteLoading.value = false
  }
}

async function loadRemoteIndexInfo() {
  if (!activeProfile.value?.key || !canManageRemote.value) return
  remoteActionLoading.value = true
  remoteError.value = ''
  try {
    const res = await imgbedApi.indexInfo(activeProfile.value.key, {
      dir: remoteQuery.value.dir || undefined,
    })
    remoteIndexInfo.value = res.data
  } catch (error) {
    remoteError.value = error.message
  } finally {
    remoteActionLoading.value = false
  }
}

async function rebuildRemoteIndex() {
  if (!activeProfile.value?.key || !canManageRemote.value) return
  if (!window.confirm('将请求图床异步重建索引，是否继续？')) return
  remoteActionLoading.value = true
  remoteError.value = ''
  try {
    await imgbedApi.rebuildIndex(activeProfile.value.key, {
      dir: remoteQuery.value.dir || undefined,
    })
    await loadRemoteIndexInfo()
  } catch (error) {
    remoteError.value = error.message
  } finally {
    remoteActionLoading.value = false
  }
}

function openDirectory(directory) {
  remoteQuery.value.dir = directory
  loadRemoteList()
}

function goParentDirectory() {
  remoteQuery.value.dir = remoteParentDir.value
  loadRemoteList()
}

async function deleteRemote(path, folder) {
  if (!activeProfile.value?.key || !path) return
  const target = folder ? `目录 ${path}` : `文件 ${path}`
  if (!window.confirm(`确认删除远端${target}？`)) return
  remoteActionLoading.value = true
  remoteError.value = ''
  try {
    await imgbedApi.deletePath(activeProfile.value.key, { path, folder })
    await loadRemoteList()
  } catch (error) {
    remoteError.value = error.message
  } finally {
    remoteActionLoading.value = false
  }
}

watch(activeKey, async () => {
  uploadResult.value = null
  resetRemoteState()
  remoteQuery.value.dir = ''
  syncBatchUploadWithTagsFromProfile()
  if (canManageRemote.value) {
    await loadRemoteCapabilities()
    await loadRemoteList()
  }
})

onMounted(async () => {
  await Promise.all([loadSettings(), loadCategories(), loadColorThemes()])
  if (canManageRemote.value) {
    await loadRemoteCapabilities()
    await loadRemoteList()
  }
})
</script>

<style scoped>
.page-subtitle {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 4px;
  font-family: var(--font-ui);
}

.page-body {
  padding: 24px 32px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section-card {
  overflow: visible;
}

.section-body {
  padding: 18px;
}

.section-tip {
  margin-top: 12px;
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.6;
}

.profile-layout {
  display: flex;
  min-height: 360px;
}

.profile-list {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  padding: 8px 0;
}

.profile-tab {
  padding: 12px 16px;
  cursor: pointer;
  transition: background .12s;
  border-left: 2px solid transparent;
}

.profile-tab:hover {
  background: var(--bg-hover);
}

.profile-tab--active {
  border-left-color: var(--accent);
  background: var(--accent-glow);
}

.profile-tab__name {
  font-size: 13px;
  font-weight: 500;
  margin-bottom: 4px;
}

.profile-tab__meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.profile-channel {
  font-size: 10px;
  color: var(--text-3);
  font-family: var(--font-ui);
}

.profile-editor {
  flex: 1;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.editor-topbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border);
}

.capability-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.capability-note {
  font-size: 11px;
  color: var(--orange);
  font-family: var(--font-ui);
}

.editor-title {
  font-size: 15px;
  font-weight: 600;
}

.field-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}

.form-row--full {
  grid-column: 1 / -1;
}

.mode-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.mode-hint {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-ui);
}

.chk {
  accent-color: var(--accent);
  width: 15px;
  height: 15px;
}

.inline-checks {
  display: flex;
  gap: 18px;
  flex-wrap: wrap;
}

.sub-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border-radius: var(--radius);
  background: var(--bg-base);
  border: 1px solid var(--border);
}

.sub-section__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.label-hint {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-3);
  margin-left: 4px;
}

.var-hint {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.8;
  padding: 8px 10px;
  background: var(--bg-hover);
  border-radius: var(--radius);
  font-family: var(--font-ui);
}

.var-hint code {
  font-family: var(--font-mono, monospace);
  color: var(--accent);
  background: transparent;
  font-size: 11px;
}

.preset-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.dir-grid {
  grid-template-columns: repeat(3, 1fr);
}

.batch-inline-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.batch-inline-meta {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-ui);
}

.batch-inline-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.batch-inline-warn,
.manager-hint {
  font-size: 11px;
  color: var(--orange);
  font-family: var(--font-ui);
}

.batch-hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.6;
  font-family: var(--font-ui);
}

.upload-result {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  padding: 12px 16px;
  background: var(--bg-panel);
  border-radius: var(--radius);
  font-size: 13px;
  font-family: var(--font-ui);
  border: 1px solid var(--border);
}

.result-ok {
  color: var(--green);
}

.result-skip {
  color: var(--text-2);
}

.result-fail {
  color: var(--red);
}

.result-format {
  color: var(--accent);
}

.result-profile {
  color: var(--text-3);
  margin-left: auto;
  font-size: 11px;
}

.check-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 13px;
}

.check-label input {
  accent-color: var(--accent);
}

.manager-toolbar,
.directory-bar,
.remote-folder-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.manager-status,
.remote-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  font-size: 12px;
  color: var(--text-3);
}

.manager-error {
  color: var(--red);
  font-size: 12px;
}

.directory-current {
  font-size: 12px;
  color: var(--text-2);
  font-family: var(--font-ui);
}

.directory-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.directory-chip {
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  border-radius: 999px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 12px;
}

.directory-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.remote-table-wrap {
  overflow-x: auto;
}

.remote-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.remote-table th,
.remote-table td {
  padding: 10px 8px;
  border-bottom: 1px solid var(--border);
  text-align: left;
}

.remote-table th {
  color: var(--text-3);
  font-weight: 500;
}

.remote-name {
  min-width: 260px;
  word-break: break-all;
}

.remote-table__actions {
  width: 100px;
}

.remote-empty {
  padding: 18px 0 8px;
  color: var(--text-3);
  font-size: 12px;
}

@media (max-width: 960px) {
  .profile-layout {
    flex-direction: column;
  }

  .profile-list {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid var(--border);
    flex-direction: row;
    flex-wrap: wrap;
  }

  .field-grid,
  .dir-grid {
    grid-template-columns: 1fr;
  }
}
</style>
