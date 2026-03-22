<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-title">图床整理</h1>
        <div class="page-subtitle">根据本地数据库记录，自动将文件整理到正确目录，并同步元数据标签</div>
      </div>
    </div>

    <!-- Profile 选择栏 -->
    <div class="profile-bar">
      <template v-if="profiles.length === 0">
        <span class="warn-text">未加载到 Profile，请前往「设置」配置图床</span>
      </template>
      <template v-else>
        <label class="form-label-inline">图床账号</label>
        <select class="select select--sm" v-model="activeKey">
          <option v-for="p in profiles" :key="p.key" :value="p.key">{{ p.name }}</option>
        </select>
        <span class="profile-dirs" v-if="activeProfile">
          横屏 → {{ activeProfile.folder_landscape || 'bg/pc' }}
          &nbsp;·&nbsp;
          竖屏 → {{ activeProfile.folder_portrait || 'bg/mb' }}
          <template v-if="activeProfile.folder_dynamic">
            &nbsp;·&nbsp;动态 → {{ activeProfile.folder_dynamic }}
          </template>
        </span>
        <span class="warn-text" v-if="!profileReady">未启用或缺少 base_url / api_token</span>
      </template>
    </div>

    <!-- 全局错误 / 成功 -->
    <div class="notice notice--error" v-if="globalError">{{ globalError }}</div>
    <div class="notice notice--ok" v-if="globalNotice">{{ globalNotice }}</div>

    <!-- ═══ 卡片一：自动整理目录 ═══ -->
    <div class="card">
      <div class="card-head">
        <span class="card-icon">📁</span>
        <div>
          <div class="card-title">自动整理目录</div>
          <div class="card-desc">
            扫描指定目录，对比本地数据库，将位置错误的文件自动移到正确目录
            （横屏 → {{ activeProfile ? (activeProfile.folder_landscape || 'bg/pc') : 'bg/pc' }}，
            竖屏 → {{ activeProfile ? (activeProfile.folder_portrait || 'bg/mb') : 'bg/mb' }}）
          </div>
        </div>
      </div>

      <div class="action-row">
        <label class="form-label-inline">扫描目录</label>
        <input
          class="input input--fill"
          v-model="organizeScanDir"
          placeholder="bg（留空则扫描全部）"
          :disabled="analyzing || organizing"
        />
        <button class="btn btn--primary" @click="analyzeOrganize" :disabled="analyzing || organizing || !profileReady">
          {{ analyzing ? '分析中...' : '开始分析' }}
        </button>
        <button
          class="btn"
          v-if="organizeResult && !analyzing && !organizing"
          @click="organizeResult = null; organizeError = ''; organizeNotice = ''"
        >清除</button>
      </div>

      <div class="inline-msg inline-msg--error" v-if="organizeError">{{ organizeError }}</div>
      <div class="inline-msg inline-msg--ok" v-if="organizeNotice">{{ organizeNotice }}</div>

      <template v-if="organizeResult">
        <!-- 分析结果三格 -->
        <div class="result-grid">
          <div class="result-cell result-cell--ok">
            <span class="result-num">{{ organizeResult.correct.length }}</span>
            <span class="result-label">已在正确位置</span>
          </div>
          <div class="result-cell result-cell--warn">
            <span class="result-num">{{ organizeResult.needsMove.length }}</span>
            <span class="result-label">需要移动</span>
          </div>
          <div class="result-cell result-cell--muted">
            <span class="result-num">{{ organizeResult.unmatched.length }}</span>
            <span class="result-label">无本地记录</span>
          </div>
        </div>

        <!-- 待移动文件预览（折叠） -->
        <details class="move-preview" v-if="organizeResult.needsMove.length > 0">
          <summary class="move-summary">查看待移动文件（{{ organizeResult.needsMove.length }} 张）</summary>
          <div class="move-table">
            <div class="move-table-head">
              <span>文件名</span><span>当前位置</span><span>目标位置</span><span>原因</span>
            </div>
            <div v-for="item in organizeResult.needsMove" :key="item.path" class="move-row">
              <span class="move-file" :title="item.path">{{ item.filename }}</span>
              <span class="move-from">{{ item.currentDir || '/' }}</span>
              <span class="move-to">{{ item.targetDir }}</span>
              <span class="move-hint">
                {{ item.meta.orientation === 'portrait' ? '竖屏' : '横屏' }}
                <template v-if="item.meta.width && item.meta.height">{{ item.meta.width }}×{{ item.meta.height }}</template>
              </span>
            </div>
          </div>
        </details>

        <!-- 执行按钮 + 进度 -->
        <div class="execute-row" v-if="organizeResult.needsMove.length > 0">
          <button class="btn btn--primary btn--lg" @click="executeOrganize" :disabled="organizing">
            <template v-if="organizing">整理中 {{ organizeProgress }}/{{ organizeResult.needsMove.length }}...</template>
            <template v-else>一键执行整理（{{ organizeResult.needsMove.length }} 张）</template>
          </button>
          <div class="progress-wrap" v-if="organizing">
            <div class="progress-fill" :style="{ width: (organizeProgress / organizeResult.needsMove.length * 100) + '%' }"></div>
          </div>
        </div>

        <div class="hint" v-if="organizeResult.needsMove.length === 0 && !organizeNotice">
          ✓ 所有已匹配的文件都在正确位置，无需整理。
        </div>
      </template>
    </div>

    <!-- ═══ 卡片二：同步元数据标签 ═══ -->
    <div class="card">
      <div class="card-head">
        <span class="card-icon">🏷️</span>
        <div>
          <div class="card-title">同步元数据标签</div>
          <div class="card-desc">将本地数据库中的分类、色系、横/竖屏等信息写入图床标签，方便搜索和筛选</div>
        </div>
      </div>

      <div class="action-row">
        <label class="form-label-inline">目录</label>
        <input class="input input--fill" v-model="tagSyncDir" placeholder="bg（留空则全部）" :disabled="tagSyncing" />
        <button class="btn btn--primary" @click="syncTagsFromDB" :disabled="tagSyncing || !profileReady">
          {{ tagSyncing ? ('同步中 ' + tagSyncProgress + '/' + tagSyncTotal + '...') : '同步标签' }}
        </button>
      </div>

      <div class="inline-msg inline-msg--error" v-if="tagSyncError">{{ tagSyncError }}</div>

      <div class="tag-sync-result" v-if="tagSyncResult">
        <span class="badge badge--ok">✓ 成功 {{ tagSyncResult.success }} 张</span>
        <span class="badge" v-if="tagSyncResult.skipped > 0">跳过 {{ tagSyncResult.skipped }} 张（无本地记录）</span>
        <span class="badge badge--warn" v-if="tagSyncResult.failed > 0">失败 {{ tagSyncResult.failed }} 张</span>
      </div>

      <div class="progress-wrap" style="margin-top:8px" v-if="tagSyncing && tagSyncTotal > 0">
        <div class="progress-fill" :style="{ width: (tagSyncProgress / tagSyncTotal * 100) + '%' }"></div>
      </div>
    </div>

    <!-- ═══ 文件浏览器（折叠，高级操作） ═══ -->
    <details class="browser-section" @toggle="onBrowserToggle">
      <summary class="browser-summary">
        <span>文件浏览器</span>
        <span class="browser-summary-hint">手动查看、移动、删除远端文件</span>
      </summary>

      <div class="browser-body" v-if="browserOpen">
        <div class="notice notice--error" v-if="remoteError">{{ remoteError }}</div>
        <div class="notice notice--ok" v-if="remoteNotice">{{ remoteNotice }}</div>

        <!-- 工具栏 -->
        <div class="browser-toolbar">
          <button class="btn btn--sm" @click="goParentDirectory" :disabled="!remoteParentDir && !remoteQuery.dir">↑ 上级</button>
          <input class="input path-input" v-model="remoteQuery.dir" placeholder="目录路径（留空为根目录）" @keyup.enter="loadRemoteList" />
          <button class="btn btn--sm" @click="loadRemoteList" :disabled="remoteLoading || !profileReady">
            {{ remoteLoading ? '加载中...' : '进入' }}
          </button>
          <button class="btn btn--sm" @click="showFilters = !showFilters">{{ showFilters ? '收起' : '筛选' }}</button>
        </div>

        <!-- 筛选面板 -->
        <div class="filter-panel" v-if="showFilters">
          <div class="filter-row">
            <div class="form-row-v"><label>文件名关键词</label><input class="input input--sm" v-model="remoteQuery.search" placeholder="关键词" @keyup.enter="loadRemoteList" /></div>
            <div class="form-row-v"><label>包含标签</label><input class="input input--sm" v-model="remoteQuery.includeTags" placeholder="标签名" @keyup.enter="loadRemoteList" /></div>
            <div class="form-row-v"><label>最大返回数</label><input class="input input--sm" type="number" v-model.number="remoteQuery.limit" /></div>
            <label class="check-label"><input type="checkbox" v-model="remoteQuery.recursive" />递归子目录</label>
          </div>
          <div class="filter-presets">
            <span class="hint">快捷：</span>
            <button v-for="preset in quickFilterPresets" :key="preset.label" class="chip" @click="applyQuickFilter(preset)">{{ preset.label }}</button>
            <button class="chip chip--muted" @click="resetQuery">重置</button>
          </div>
          <button class="btn btn--sm" @click="loadRemoteList" :disabled="remoteLoading">应用筛选</button>
        </div>

        <!-- 子目录芯片 -->
        <div class="dir-chips" v-if="remoteDirectories.length">
          <button v-for="dir in remoteDirectories" :key="dir" class="chip chip--dir" @click="openDirectory(dir)">
            📁 {{ dir.split('/').filter(Boolean).pop() || dir }}
          </button>
        </div>

        <!-- 批量操作栏 -->
        <div class="batch-bar" v-if="selectedPaths.length > 0">
          <span class="batch-count">已选 <strong>{{ selectedPaths.length }}</strong> 张</span>
          <button class="btn btn--sm" @click="toggleSelectCurrentPage(false)">取消选择</button>
          <button class="btn btn--sm btn--accent" @click="openAutoTagPanel" :disabled="autoTagLoading || !canManageSelected">
            {{ autoTagLoading ? '匹配中...' : '从本地DB补全标签' }}
          </button>
          <span class="hint" v-if="!canManageSelected">图床需支持标签管理</span>
        </div>

        <!-- 状态栏 -->
        <div class="list-status" v-if="remoteSummary">
          <span class="hint">{{ remoteSummary }}</span>
        </div>

        <!-- 主体：文件列表 + 操作面板 -->
        <div class="browser-main">
          <!-- 文件列表 -->
          <div class="file-table-wrap">
            <div class="empty-state" v-if="!remoteFiles.length">
              {{ remoteLoading ? '正在加载...' : (profileReady ? '当前目录没有文件' : '请先配置并启用 Profile') }}
            </div>
            <table class="file-table" v-else>
              <thead>
                <tr>
                  <th class="col-check">
                    <input type="checkbox"
                      :checked="selectedPaths.length === remoteFiles.length && remoteFiles.length > 0"
                      @change="toggleSelectCurrentPage($event.target.checked)" />
                  </th>
                  <th>文件</th>
                  <th class="col-size">大小</th>
                  <th class="col-time">时间</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="file in remoteFiles" :key="file.name"
                  :class="['file-row', { 'row-active': selectedFile && selectedFile.name === file.name, 'row-checked': selectedPaths.includes(file.name) }]"
                  @click="selectFile(file)">
                  <td class="col-check" @click.stop="toggleSelectFile(file.name)">
                    <input type="checkbox" :checked="selectedPaths.includes(file.name)" @change="toggleSelectFile(file.name)" @click.stop />
                  </td>
                  <td class="col-file">
                    <div class="file-name" :title="file.name">{{ getFileBaseName(file.name) }}</div>
                    <div class="file-dir hint">{{ getDirectoryName(file.name) || '/' }}</div>
                    <div class="file-tags" v-if="file.tags && file.tags.length">
                      <span class="tag-chip" v-for="t in file.tags" :key="t">{{ t }}</span>
                    </div>
                  </td>
                  <td class="col-size hint">{{ formatRemoteSize(file.size) }}</td>
                  <td class="col-time hint">{{ formatTimestamp(file.created_at || file.updatedAt) }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 操作面板 -->
          <div class="action-panel">
            <!-- 无文件选中：目录分布 + 高级操作 -->
            <div class="action-empty" v-if="!selectedFile">
              <div class="empty-title">目录分布</div>
              <div class="dir-bucket" v-for="b in directoryBuckets.slice(0, 8)" :key="b.path">
                <button class="bucket-path" @click="openDirectory(b.path)">{{ b.path || '/' }}</button>
                <span class="bucket-count">{{ b.count }}</span>
              </div>
              <div class="hint" style="margin-top:8px" v-if="!directoryBuckets.length">点击文件查看操作</div>
              <details class="adv-ops">
                <summary>高级操作</summary>
                <div class="adv-btns">
                  <button class="btn btn--sm" @click="loadRemoteIndexInfo" :disabled="remoteActionLoading || !profileReady">索引信息</button>
                  <button class="btn btn--sm" @click="rebuildRemoteIndex" :disabled="remoteActionLoading || !profileReady">重建索引</button>
                </div>
                <div class="hint adv-hint" v-if="remoteIndexInfo">
                  索引更新：{{ formatTimestamp(remoteIndexInfo.lastUpdated || remoteIndexInfo.indexLastUpdated) }}
                </div>
              </details>
            </div>

            <!-- 文件选中：操作面板 -->
            <div class="file-panel" v-if="selectedFile">
              <div class="file-preview-block">
                <img class="file-preview-img" :src="buildRemoteFileUrl(selectedFile.name)" :alt="selectedFile.name"
                  @error="$event.target.style.display='none'" />
              </div>

              <div class="current-tags" v-if="selectedCurrentTags.length">
                <span class="hint">当前标签：</span>
                <span class="tag-chip" v-for="t in selectedCurrentTags" :key="t">{{ t }}</span>
              </div>

              <div class="reclassify-form">
                <div class="form-section-title">重新分类</div>

                <div class="form-row-h">
                  <label>类型</label>
                  <div class="seg-group">
                    <button v-for="opt in [{v:'static',l:'静态图'},{v:'dynamic',l:'动态图'}]" :key="opt.v"
                      class="seg-btn" :class="{'seg-btn--active': assistantForm.wallpaperType === opt.v}"
                      @click="assistantForm.wallpaperType = opt.v">{{ opt.l }}</button>
                  </div>
                </div>

                <div class="form-row-h">
                  <label>方向</label>
                  <div class="seg-group">
                    <button v-for="opt in [{v:'landscape',l:'横屏'},{v:'portrait',l:'竖屏'}]" :key="opt.v"
                      class="seg-btn" :class="{'seg-btn--active': assistantForm.orientation === opt.v}"
                      @click="assistantForm.orientation = opt.v">{{ opt.l }}</button>
                  </div>
                </div>

                <div class="form-row-h">
                  <label>分类</label>
                  <select class="select select--sm" v-model="assistantForm.category">
                    <option value="">不设置</option>
                    <option v-for="c in categoryOptions" :key="c" :value="c">{{ c }}</option>
                  </select>
                </div>

                <div class="form-row-h">
                  <label>色系</label>
                  <select class="select select--sm" v-model="assistantForm.colorTheme">
                    <option value="">不设置</option>
                    <option v-for="c in colorOptions" :key="c" :value="c">{{ c }}</option>
                  </select>
                </div>

                <div class="form-row-h">
                  <label>附加标签</label>
                  <input class="input input--sm" v-model="assistantForm.customTags" placeholder="逗号分隔" />
                </div>

                <div class="preview-box">
                  <span class="hint">标签预览：</span>
                  <span class="tag-chip" v-for="t in previewTags" :key="t">{{ t }}</span>
                </div>

                <div class="form-row-h">
                  <label>目标目录</label>
                  <div class="dir-input-wrap">
                    <input class="input input--sm" :value="assistantForm.targetDirectory" @input="handleTargetDirectoryInput" placeholder="目标目录" />
                    <button class="btn btn--xs" @click="restoreSuggestedDirectory" title="重置为推荐目录">↺</button>
                  </div>
                </div>

                <div class="sync-options">
                  <label class="check-label"><input type="checkbox" v-model="reclassifyOptions.syncDirectory" />修改目录</label>
                  <label class="check-label"><input type="checkbox" v-model="reclassifyOptions.syncTags" />修改标签</label>
                </div>

                <div class="apply-btns">
                  <button class="btn btn--primary btn--sm" @click="applyReclassifyToCurrent" :disabled="!canApplyToCurrent">
                    {{ remoteActionLoading ? '处理中...' : '应用到此文件' }}
                  </button>
                  <button class="btn btn--sm" v-if="selectedPaths.length > 1" @click="applyReclassifyToBatch" :disabled="!canApplyToBatch">
                    {{ batchActionLoading ? '批量处理中...' : ('应用到已选 ' + selectedPaths.length + ' 张') }}
                  </button>
                </div>
              </div>

              <!-- 自动补全标签 -->
              <div class="auto-tag-block" v-if="autoTagPanel.visible">
                <div class="auto-tag-head">
                  <span class="form-section-title">从本地DB补全标签</span>
                  <button class="btn btn--xs btn--ghost" @click="closeAutoTagPanel">✕</button>
                </div>
                <div v-if="autoTagLoading" class="hint">正在匹配本地数据库...</div>
                <template v-else-if="autoTagPanel.result">
                  <div class="auto-tag-badges">
                    <span class="badge badge--ok">匹配 {{ autoTagPanel.result.matched_count }} 张</span>
                    <span class="badge" v-if="autoTagPanel.result.unmatched_count > 0">未找到 {{ autoTagPanel.result.unmatched_count }} 张</span>
                  </div>
                  <div class="hint" style="margin:6px 0" v-if="autoTagPanel.result.matched_count > 0">将按数据库记录写入标签</div>
                  <button class="btn btn--primary btn--sm" @click="applyAutoTags" :disabled="autoTagApplying" v-if="autoTagPanel.result.matched_count > 0">
                    {{ autoTagApplying ? ('写入 ' + autoTagApplyProgress + '/' + autoTagPanel.result.matched_count + '...') : ('确认为 ' + autoTagPanel.result.matched_count + ' 张补全标签') }}
                  </button>
                  <div v-if="autoTagPanel.applyResult" class="auto-tag-result">
                    成功 {{ autoTagPanel.applyResult.success }} 张，失败 {{ autoTagPanel.applyResult.failed }} 张
                  </div>
                </template>
              </div>

              <div class="file-actions">
                <button class="btn btn--sm" @click="openRemoteFile(selectedFile)">在图床查看</button>
                <button class="btn btn--sm" @click="copySelectedPath">复制路径</button>
                <button class="btn btn--sm btn--danger" @click="deleteRemote(selectedFile.name, false)" :disabled="remoteActionLoading">删除</button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </details>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { galleryApi, imgbedApi, settingsApi } from '../api'
import { normalizeUploadSettings } from '../utils/uploadProfiles'

const ORIENTATION_LABELS = { landscape: '横图', portrait: '竖图', square: '方图', unknown: '未知' }

// ── Profile & meta ──────────────────────────────────────────────
const loadingProfiles = ref(false)
const loadingMeta = ref(false)
const profiles = ref([])
const galleryMeta = ref({ categories: [], colors: [] })
const activeKey = ref('')

// ── 整理向导 ────────────────────────────────────────────────────
const organizeScanDir = ref('bg')
const analyzing = ref(false)
const organizing = ref(false)
const organizeProgress = ref(0)
const organizeResult = ref(null)
const organizeError = ref('')
const organizeNotice = ref('')

// ── 标签同步 ────────────────────────────────────────────────────
const tagSyncDir = ref('bg')
const tagSyncing = ref(false)
const tagSyncProgress = ref(0)
const tagSyncTotal = ref(0)
const tagSyncResult = ref(null)
const tagSyncError = ref('')

// ── 文件浏览器 ──────────────────────────────────────────────────
const browserOpen = ref(false)
const remoteLoading = ref(false)
const remoteActionLoading = ref(false)
const batchActionLoading = ref(false)
const capabilityLoading = ref(false)
const selectedTagLoading = ref(false)
const remoteError = ref('')
const remoteNotice = ref('')
const globalError = ref('')
const globalNotice = ref('')
const remoteCapabilities = ref(null)
const remoteIndexInfo = ref(null)
const remoteData = ref({ files: [], directories: [], totalCount: 0, returnedCount: 0, indexLastUpdated: null })
const selectedFile = ref(null)
const selectedPaths = ref([])
const selectedCurrentTags = ref([])
const lastFilterLabel = ref('')
const targetDirectoryManuallyEdited = ref(false)
const showFilters = ref(false)

const autoTagLoading = ref(false)
const autoTagApplying = ref(false)
const autoTagApplyProgress = ref(0)
const autoTagPanel = ref({ visible: false, result: null, applyResult: null })

const remoteQuery = ref({ dir: '', search: '', includeTags: '', excludeTags: '', limit: 200, recursive: false })
const assistantForm = ref(createAssistantForm())
const reclassifyOptions = ref({ syncDirectory: true, syncTags: true })
const quickFilterPresets = [
  { label: '横图', includeTags: '横图' },
  { label: '竖图', includeTags: '竖图' },
  { label: '动态图', includeTags: '动态图' },
]

// ── Computed ─────────────────────────────────────────────────────
const activeProfile = computed(() => profiles.value.find((p) => p.key === activeKey.value) || profiles.value[0] || null)
const profileReady = computed(() => Boolean(activeProfile.value?.enabled && activeProfile.value?.base_url && activeProfile.value?.api_token))
const remoteFiles = computed(() => Array.isArray(remoteData.value.files) ? remoteData.value.files : [])
const remoteDirectories = computed(() => Array.isArray(remoteData.value.directories) ? remoteData.value.directories : [])
const categoryOptions = computed(() => (galleryMeta.value.categories || []).map((i) => typeof i === 'string' ? i : i.name).filter(Boolean))
const colorOptions = computed(() => (galleryMeta.value.colors || []).map((i) => typeof i === 'string' ? i : i.name).filter(Boolean))
const remoteParentDir = computed(() => {
  const current = normalizeRemotePath(remoteQuery.value.dir)
  if (!current) return ''
  const parts = current.split('/').filter(Boolean)
  parts.pop()
  return parts.join('/')
})
const remoteSummary = computed(() => {
  const t = remoteData.value.totalCount
  const r = remoteData.value.returnedCount
  return [typeof t === 'number' ? ('总数 ' + t) : '', typeof r === 'number' ? ('本次返回 ' + r) : ''].filter(Boolean).join(' / ')
})
const directoryBuckets = computed(() => {
  const counter = new Map()
  for (const file of remoteFiles.value) {
    const dir = getDirectoryName(file.name)
    const key = dir || '/'
    counter.set(key, (counter.get(key) || 0) + 1)
  }
  return [...counter.entries()].map(([path, count]) => ({ path, count })).sort((a, b) => b.count - a.count)
})
const canManageSelected = computed(() => Boolean(profileReady.value && remoteCapabilities.value?.manage_tags))
const previewTags = computed(() => buildPreviewTags(assistantForm.value))
const suggestedDirectory = computed(() => computeSuggestedDirectory(activeProfile.value, assistantForm.value, selectedFile.value?.name || ''))
const canApplyToCurrent = computed(() => {
  if (!selectedFile.value || !profileReady.value || remoteActionLoading.value) return false
  if (!reclassifyOptions.value.syncDirectory && !reclassifyOptions.value.syncTags) return false
  if (reclassifyOptions.value.syncDirectory && !assistantForm.value.targetDirectory) return false
  return true
})
const canApplyToBatch = computed(() => {
  if (!selectedPaths.value.length || !profileReady.value || batchActionLoading.value) return false
  if (!reclassifyOptions.value.syncDirectory && !reclassifyOptions.value.syncTags) return false
  if (reclassifyOptions.value.syncDirectory && !assistantForm.value.targetDirectory) return false
  return true
})

// ── 工具函数 ─────────────────────────────────────────────────────
function createAssistantForm() {
  return { wallpaperType: 'static', orientation: 'landscape', category: '', colorTheme: '', customTags: '', targetDirectory: '' }
}

function pickPreferredProfileKey(list, currentKey) {
  const current = list.find((p) => p.key === currentKey)
  if (current) return current.key
  const enabled = list.find((p) => p.enabled && p.base_url && p.api_token)
  return enabled?.key || list[0]?.key || ''
}

function splitTags(value) {
  return String(value || '').split(',').map((s) => s.trim()).filter(Boolean)
}

function uniqueTags(items) {
  const seen = new Set()
  return items.filter((item) => {
    const text = String(item || '').trim()
    const key = text.toLowerCase()
    if (!text || seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function safePathSegment(value, fallback) {
  const cleaned = String(value || '').replace(/[^\w\u4e00-\u9fa5\-_.]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '').trim()
  return cleaned || (fallback || 'unknown')
}

function normalizeRemotePath(value) {
  return String(value || '').replace(/\\/g, '/').replace(/\/+/g, '/').replace(/^\/|\/$/g, '').trim()
}

function getDirectoryName(path) {
  const parts = normalizeRemotePath(path).split('/').filter(Boolean)
  parts.pop()
  return parts.join('/')
}

function getFileBaseName(path) {
  const parts = normalizeRemotePath(path).split('/').filter(Boolean)
  return parts[parts.length - 1] || path
}

function getFileNameWithoutExt(path) {
  const base = getFileBaseName(path)
  const dotIdx = base.lastIndexOf('.')
  return dotIdx > 0 ? base.slice(0, dotIdx) : base
}

function buildRemoteFileUrl(fileName) {
  if (!activeProfile.value?.base_url || !fileName) return ''
  const encoded = String(fileName).split('/').map((s) => encodeURIComponent(s)).join('/')
  return String(activeProfile.value.base_url).replace(/\/+$/, '') + '/file/' + encoded
}

function formatTimestamp(value) {
  if (!value) return '—'
  const numeric = Number(value)
  const date = Number.isFinite(numeric) && numeric > 0 ? new Date(numeric * 1000) : new Date(value)
  if (isNaN(date.getTime())) return String(value)
  return date.toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

function formatRemoteSize(value) {
  const size = Number(value)
  if (!Number.isFinite(size) || size <= 0) return '—'
  if (size < 1024) return size + ' B'
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + ' KB'
  return (size / (1024 * 1024)).toFixed(2) + ' MB'
}

function inferTypeFromPath(path) {
  return /dynamic|gif|webp/i.test(normalizeRemotePath(path)) ? 'dynamic' : 'static'
}

function inferOrientationFromPath(path) {
  const n = normalizeRemotePath(path)
  if (/\/mb\/|portrait|vertical/i.test(n)) return 'portrait'
  if (/\/pc\/|landscape|horizontal/i.test(n)) return 'landscape'
  return 'unknown'
}

function buildPreviewTags(form) {
  const typeTag = form.wallpaperType === 'dynamic' ? '动态图' : '静态图'
  const orientTag = ORIENTATION_LABELS[form.orientation] || ORIENTATION_LABELS.unknown
  const userTags = [
    ...(form.category ? [form.category] : []),
    ...(form.colorTheme ? [form.colorTheme] : []),
    ...splitTags(form.customTags),
  ]
  return uniqueTags([typeTag, orientTag, ...userTags])
}

function computeSuggestedDirectory(profile, form, fileName) {
  const now = new Date()
  const p = profile || {}
  const folderPattern = String(p.folder_pattern || '').trim()
  const customTags = splitTags(form.customTags)
  const values = {
    type: form.wallpaperType === 'dynamic' ? 'dynamic' : 'static',
    orientation: form.orientation || 'unknown',
    category: safePathSegment(form.category, 'unknown'),
    color: safePathSegment(form.colorTheme, 'unknown'),
    color_theme: safePathSegment(form.colorTheme, 'unknown'),
    tag: safePathSegment(customTags[0], ''),
    filename: getFileNameWithoutExt(fileName || ''),
    year: String(now.getFullYear()),
    month: (now.getMonth() + 1 + '').padStart(2, '0'),
    date: now.getFullYear() + (now.getMonth() + 1 + '').padStart(2, '0') + (now.getDate() + '').padStart(2, '0'),
  }
  if (folderPattern) {
    let folder = folderPattern
    for (const [key, value] of Object.entries(values)) {
      folder = folder.replaceAll('{' + key + '}', value)
    }
    return normalizeRemotePath(folder)
  }
  if (form.wallpaperType === 'dynamic') return normalizeRemotePath(p.folder_dynamic || 'bg/dynamic')
  if (form.orientation === 'portrait') return normalizeRemotePath(p.folder_portrait || 'bg/mb')
  return normalizeRemotePath(p.folder_landscape || 'bg/pc')
}

function restoreSuggestedDirectory() {
  assistantForm.value.targetDirectory = suggestedDirectory.value
  targetDirectoryManuallyEdited.value = false
}

function handleTargetDirectoryInput(event) {
  assistantForm.value.targetDirectory = event.target.value
  targetDirectoryManuallyEdited.value = true
}

function syncAssistantDirectory(force) {
  if (!targetDirectoryManuallyEdited.value || force) {
    assistantForm.value.targetDirectory = suggestedDirectory.value
    if (force) targetDirectoryManuallyEdited.value = false
  }
}

function applyTagsToAssistant(tags, fileName) {
  const normalizedTags = (Array.isArray(tags) ? tags : []).map((t) => String(t).trim()).filter(Boolean)
  const typeTag = normalizedTags.includes('动态图') ? 'dynamic' : normalizedTags.includes('静态图') ? 'static' : inferTypeFromPath(fileName)
  const orientTag = normalizedTags.includes('横图') ? 'landscape' : normalizedTags.includes('竖图') ? 'portrait' : inferOrientationFromPath(fileName)
  const category = normalizedTags.find((t) => categoryOptions.value.includes(t)) || ''
  const colorTheme = normalizedTags.find((t) => colorOptions.value.includes(t)) || ''
  const systemTags = new Set(['动态图', '静态图', '横图', '竖图', '方图', '未知', ...categoryOptions.value, ...colorOptions.value])
  const customTags = normalizedTags.filter((t) => !systemTags.has(t))
  assistantForm.value = { wallpaperType: typeTag, orientation: orientTag, category, colorTheme, customTags: customTags.join(', '), targetDirectory: assistantForm.value.targetDirectory }
  targetDirectoryManuallyEdited.value = false
}

function resetRemoteState() {
  remoteData.value = { files: [], directories: [], totalCount: 0, returnedCount: 0, indexLastUpdated: null }
  selectedFile.value = null
  selectedPaths.value = []
  remoteError.value = ''
  remoteNotice.value = ''
  remoteIndexInfo.value = null
  remoteCapabilities.value = null
}

function resetQuery() {
  remoteQuery.value = { dir: '', search: '', includeTags: '', excludeTags: '', limit: 200, recursive: false }
  lastFilterLabel.value = ''
}

function applyQuickFilter(preset) {
  remoteQuery.value.includeTags = preset.includeTags || ''
  remoteQuery.value.search = preset.search || ''
  lastFilterLabel.value = preset.label
  loadRemoteList()
}

function buildMovedFilePath(oldPath, targetDirectory) {
  const normalizedTarget = normalizeRemotePath(targetDirectory)
  const fileName = getFileBaseName(oldPath)
  return normalizedTarget ? normalizedTarget + '/' + fileName : fileName
}

// ── 整理向导 ─────────────────────────────────────────────────────
async function analyzeOrganize() {
  if (!profileReady.value) return
  analyzing.value = true
  organizeError.value = ''
  organizeNotice.value = ''
  organizeResult.value = null
  globalError.value = ''

  try {
    const listRes = await imgbedApi.list(activeProfile.value.key, {
      dir: organizeScanDir.value || '',
      recursive: true,
      count: -1,
    })
    const files = listRes?.data?.files || listRes?.files || []
    if (!files.length) {
      organizeError.value = '该目录没有找到文件，请确认目录名称正确。'
      return
    }

    const paths = files.map((f) => f.name)
    const matchRes = await galleryApi.matchRemote({
      paths,
      base_url: activeProfile.value.base_url || '',
    })
    const matched = matchRes?.matched || matchRes?.data?.matched || {}
    const unmatchedPaths = matchRes?.unmatched || matchRes?.data?.unmatched || []

    const correct = []
    const needsMove = []
    for (const [path, meta] of Object.entries(matched)) {
      const currentDir = normalizeRemotePath(getDirectoryName(path))
      const targetDir = computeSuggestedDirectory(
        activeProfile.value,
        { wallpaperType: meta.wallpaper_type || 'static', orientation: meta.orientation || 'landscape', category: meta.category || '', colorTheme: meta.color_theme || '', customTags: '' },
      )
      if (currentDir === normalizeRemotePath(targetDir)) {
        correct.push({ path, meta, currentDir, targetDir })
      } else {
        needsMove.push({ path, meta, currentDir, targetDir, filename: getFileBaseName(path) })
      }
    }

    organizeResult.value = { correct, needsMove, unmatched: unmatchedPaths }
  } catch (err) {
    organizeError.value = '分析失败：' + (err?.message || String(err))
  } finally {
    analyzing.value = false
  }
}

async function executeOrganize() {
  if (!organizeResult.value?.needsMove?.length) return
  const count = organizeResult.value.needsMove.length
  if (!confirm('确认将 ' + count + ' 张文件移到正确目录？此操作不可撤销。')) return

  organizing.value = true
  organizeProgress.value = 0
  organizeError.value = ''
  organizeNotice.value = ''
  let successCount = 0
  let failCount = 0

  for (const item of organizeResult.value.needsMove) {
    try {
      await imgbedApi.movePath(activeProfile.value.key, { path: item.path, dist: item.targetDir })
      successCount++
    } catch (err) {
      failCount++
      console.warn('[整理] 移动失败：', item.path, err?.message)
    }
    organizeProgress.value++
  }

  organizing.value = false
  organizeNotice.value = failCount === 0
    ? ('整理完成！共移动 ' + successCount + ' 张文件。')
    : ('完成：成功 ' + successCount + ' 张，失败 ' + failCount + ' 张')
  organizeResult.value = null
}

// ── 标签同步 ─────────────────────────────────────────────────────
async function syncTagsFromDB() {
  if (!profileReady.value) return
  tagSyncing.value = true
  tagSyncProgress.value = 0
  tagSyncTotal.value = 0
  tagSyncResult.value = null
  tagSyncError.value = ''

  try {
    const listRes = await imgbedApi.list(activeProfile.value.key, {
      dir: tagSyncDir.value || '',
      recursive: true,
      count: -1,
    })
    const files = listRes?.data?.files || listRes?.files || []
    if (!files.length) {
      tagSyncError.value = '该目录没有找到文件，请确认目录名称正确。'
      return
    }

    const paths = files.map((f) => f.name)
    const matchRes = await galleryApi.matchRemote({
      paths,
      base_url: activeProfile.value.base_url || '',
    })
    const matched = matchRes?.matched || matchRes?.data?.matched || {}
    const unmatchedPaths = matchRes?.unmatched || matchRes?.data?.unmatched || []

    const entries = Object.entries(matched)
    tagSyncTotal.value = entries.length
    let success = 0
    let failed = 0

    for (const [path, meta] of entries) {
      try {
        await imgbedApi.setTags(activeProfile.value.key, { path, tags: meta.suggested_tags || [], action: 'set' })
        success++
      } catch {
        failed++
      }
      tagSyncProgress.value++
    }

    tagSyncResult.value = { success, failed, skipped: unmatchedPaths.length }
  } catch (err) {
    tagSyncError.value = '同步失败：' + (err?.message || String(err))
  } finally {
    tagSyncing.value = false
  }
}

// ── 文件浏览器 ───────────────────────────────────────────────────
function onBrowserToggle(event) {
  browserOpen.value = event.target.open
  if (browserOpen.value && profileReady.value && !remoteFiles.value.length) {
    loadRemoteCapabilities()
    loadRemoteList()
  }
}

function openDirectory(directory) { remoteQuery.value.dir = directory; loadRemoteList() }
function goParentDirectory() { remoteQuery.value.dir = remoteParentDir.value; loadRemoteList() }

function toggleSelectFile(path) {
  const idx = selectedPaths.value.indexOf(path)
  if (idx >= 0) selectedPaths.value.splice(idx, 1)
  else selectedPaths.value.push(path)
}

function toggleSelectCurrentPage(checked) {
  selectedPaths.value = checked ? remoteFiles.value.map((f) => f.name) : []
}

function openRemoteFile(file) {
  const url = buildRemoteFileUrl(file?.name)
  if (url) window.open(url, '_blank')
}

function copySelectedPath() {
  if (!selectedFile.value) return
  navigator.clipboard?.writeText(selectedFile.value.name).catch(() => {})
}

async function loadSettings() {
  loadingProfiles.value = true
  try {
    const settings = normalizeUploadSettings(await settingsApi.getUploads())
    const list = Array.isArray(settings.profiles) ? settings.profiles : []
    profiles.value = list
    activeKey.value = pickPreferredProfileKey(list, activeKey.value)
  } catch (err) {
    globalError.value = '加载 Profile 失败：' + (err?.message || err)
  } finally {
    loadingProfiles.value = false
  }
}

async function loadGalleryMeta() {
  loadingMeta.value = true
  try {
    const data = await galleryApi.wallpaperMeta()
    galleryMeta.value = {
      categories: Array.isArray(data?.categories) ? data.categories : [],
      colors: Array.isArray(data?.colors) ? data.colors : [],
    }
  } catch {
    galleryMeta.value = { categories: [], colors: [] }
  } finally {
    loadingMeta.value = false
  }
}

async function loadRemoteCapabilities() {
  capabilityLoading.value = true
  try {
    const res = await imgbedApi.capabilities(activeProfile.value.key)
    remoteCapabilities.value = res?.data || res || null
  } catch {
    remoteCapabilities.value = null
  } finally {
    capabilityLoading.value = false
  }
}

async function loadRemoteList() {
  if (!profileReady.value) return
  remoteLoading.value = true
  remoteError.value = ''
  remoteNotice.value = ''
  try {
    const res = await imgbedApi.list(activeProfile.value.key, {
      dir: remoteQuery.value.dir,
      search: remoteQuery.value.search,
      include_tags: remoteQuery.value.includeTags,
      exclude_tags: remoteQuery.value.excludeTags,
      limit: remoteQuery.value.limit,
      recursive: remoteQuery.value.recursive,
    })
    const data = res?.data || res || {}
    remoteData.value = {
      files: Array.isArray(data.files) ? data.files : [],
      directories: Array.isArray(data.directories) ? data.directories : [],
      totalCount: data.totalCount ?? data.total_count ?? 0,
      returnedCount: data.returnedCount ?? data.returned_count ?? (Array.isArray(data.files) ? data.files.length : 0),
      indexLastUpdated: data.indexLastUpdated ?? data.index_last_updated ?? null,
    }
    selectedFile.value = null
    selectedPaths.value = []
  } catch (err) {
    remoteError.value = '加载远端文件失败：' + (err?.message || err)
  } finally {
    remoteLoading.value = false
  }
}

async function loadRemoteIndexInfo() {
  if (!profileReady.value) return
  remoteActionLoading.value = true
  try {
    const res = await imgbedApi.indexInfo(activeProfile.value.key, { dir: remoteQuery.value.dir })
    remoteIndexInfo.value = res?.data || res || null
  } catch (err) {
    remoteError.value = '获取索引信息失败：' + (err?.message || err)
  } finally {
    remoteActionLoading.value = false
  }
}

async function rebuildRemoteIndex() {
  if (!activeProfile.value?.key || !confirm('确认重建索引？这会重新扫描远端文件，可能需要较长时间。')) return
  remoteActionLoading.value = true
  try {
    await imgbedApi.rebuildIndex(activeProfile.value.key, { dir: remoteQuery.value.dir })
    remoteNotice.value = '索引重建完成'
    await loadRemoteList()
  } catch (err) {
    remoteError.value = '重建索引失败：' + (err?.message || err)
  } finally {
    remoteActionLoading.value = false
  }
}

async function deleteRemote(path, folder) {
  if (!activeProfile.value?.key || !path || !window.confirm('确认删除远端' + (folder ? '目录' : '文件') + ' ' + path + '？')) return
  remoteActionLoading.value = true
  try {
    await imgbedApi.deletePath(activeProfile.value.key, { path, recursive: folder })
    remoteNotice.value = '已删除' + (folder ? '目录' : '文件') + '：' + path
    if (!folder && selectedFile.value?.name === path) selectedFile.value = null
    await loadRemoteList()
  } catch (err) {
    remoteError.value = '删除失败：' + (err?.message || err)
  } finally {
    remoteActionLoading.value = false
  }
}

async function selectFile(file) {
  selectedFile.value = file
  syncAssistantDirectory()
  await loadSelectedTags()
}

async function loadSelectedTags() {
  if (!selectedFile.value || !profileReady.value) return
  selectedTagLoading.value = true
  try {
    const res = await imgbedApi.getTags(activeProfile.value.key, { path: selectedFile.value.name })
    const tags = Array.isArray(res.data?.tags) ? res.data.tags : []
    selectedCurrentTags.value = tags
    applyTagsToAssistant(tags, selectedFile.value.name)
    syncAssistantDirectory()
  } catch {
    selectedCurrentTags.value = []
  } finally {
    selectedTagLoading.value = false
  }
}

async function applyClassificationToPaths(paths) {
  const targetDirectory = normalizeRemotePath(assistantForm.value.targetDirectory)
  const tags = previewTags.value
  const syncDirectory = reclassifyOptions.value.syncDirectory
  const syncTags = reclassifyOptions.value.syncTags
  if (!syncDirectory && !syncTags) { remoteError.value = '请至少选择"修改目录"或"修改标签"中的一个。'; return }
  if (syncDirectory && !targetDirectory) { remoteError.value = '目标目录不能为空。'; return }
  const finalPaths = []
  for (const originalPath of paths) {
    const currentDirectory = getDirectoryName(originalPath)
    const movedPath = syncDirectory ? buildMovedFilePath(originalPath, targetDirectory) : originalPath
    const needsMove = syncDirectory && normalizeRemotePath(currentDirectory) !== targetDirectory
    try {
      if (needsMove) {
        await imgbedApi.movePath(activeProfile.value.key, { path: originalPath, dist: targetDirectory })
      }
      if (syncTags) {
        await imgbedApi.setTags(activeProfile.value.key, { path: movedPath, tags, action: 'set' })
      }
      finalPaths.push(movedPath)
    } catch (err) {
      remoteError.value = '处理 ' + getFileBaseName(originalPath) + ' 失败：' + (err?.message || err)
    }
  }
  return finalPaths
}

async function applyReclassifyToCurrent() {
  if (!selectedFile.value || !canApplyToCurrent.value) return
  remoteActionLoading.value = true
  remoteError.value = ''
  remoteNotice.value = ''
  try {
    const finalPaths = await applyClassificationToPaths([selectedFile.value.name])
    const focusPath = finalPaths?.[0] || selectedFile.value.name
    remoteNotice.value = '已应用新的目录和标签。'
    await loadRemoteList()
    const newFile = remoteFiles.value.find((f) => f.name === focusPath)
    if (newFile) await selectFile(newFile)
    else selectedFile.value = null
  } catch (err) {
    remoteError.value = '应用失败：' + (err?.message || err)
  } finally {
    remoteActionLoading.value = false
  }
}

async function applyReclassifyToBatch() {
  if (!selectedPaths.value.length || !canApplyToBatch.value) return
  const count = selectedPaths.value.length
  if (!confirm('确认对已选的 ' + count + ' 张图片应用当前分类设置？')) return
  batchActionLoading.value = true
  remoteError.value = ''
  remoteNotice.value = ''
  try {
    await applyClassificationToPaths([...selectedPaths.value])
    remoteNotice.value = '已对 ' + count + ' 张图片应用新的目录和标签。'
    selectedPaths.value = []
    await loadRemoteList()
  } catch (err) {
    remoteError.value = '批量应用失败：' + (err?.message || err)
  } finally {
    batchActionLoading.value = false
  }
}

function openAutoTagPanel() {
  autoTagPanel.value = { visible: true, result: null, applyResult: null }
  fetchAutoTagSuggestions()
}

function closeAutoTagPanel() {
  autoTagPanel.value = { visible: false, result: null, applyResult: null }
}

async function fetchAutoTagSuggestions() {
  autoTagLoading.value = true
  try {
    const result = await galleryApi.matchRemote({
      paths: selectedPaths.value,
      base_url: activeProfile.value?.base_url || '',
    })
    autoTagPanel.value.result = result?.data || result || null
  } catch (err) {
    remoteError.value = '匹配失败：' + (err?.message || err)
    autoTagPanel.value.visible = false
  } finally {
    autoTagLoading.value = false
  }
}

async function applyAutoTags() {
  const matched = autoTagPanel.value.result?.matched || {}
  const entries = Object.entries(matched)
  if (!entries.length) return
  autoTagApplying.value = true
  autoTagApplyProgress.value = 0
  let success = 0
  let failed = 0
  for (const [path, meta] of entries) {
    try {
      await imgbedApi.setTags(activeProfile.value.key, { path, tags: meta.suggested_tags || [], action: 'add' })
      success++
    } catch {
      failed++
    }
    autoTagApplyProgress.value++
  }
  autoTagApplying.value = false
  autoTagPanel.value.applyResult = { success, failed }
  if (success > 0) remoteNotice.value = '标签补全完成：成功 ' + success + ' 张，失败 ' + failed + ' 张。'
  await loadRemoteList()
}

// ── Watchers & lifecycle ──────────────────────────────────────────
watch(
  () => [
    assistantForm.value.wallpaperType,
    assistantForm.value.orientation,
    assistantForm.value.category,
    assistantForm.value.colorTheme,
    assistantForm.value.customTags,
    activeProfile.value?.folder_pattern,
    activeProfile.value?.folder_landscape,
    activeProfile.value?.folder_portrait,
    activeProfile.value?.folder_dynamic,
    selectedFile.value?.name,
  ],
  () => { syncAssistantDirectory() },
)

watch(activeKey, async () => {
  resetRemoteState()
  if (activeProfile.value?.key && profileReady.value && browserOpen.value) {
    await loadRemoteCapabilities()
    await loadRemoteList()
  }
})

onMounted(async () => {
  await Promise.all([loadSettings(), loadGalleryMeta()])
  syncAssistantDirectory(true)
})
</script>

<style scoped>
/* ── Profile 栏 ── */
.profile-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.profile-dirs { font-size: 12px; color: var(--text-muted); background: var(--bg-subtle, #f4f4f4); padding: 2px 8px; border-radius: 4px; }
.form-label-inline { font-size: 13px; color: var(--text-muted); white-space: nowrap; }
.warn-text { font-size: 12px; color: #e67e22; }

/* ── 通知条 ── */
.notice { padding: 8px 14px; border-radius: 6px; font-size: 13px; margin-bottom: 12px; }
.notice--error { background: #fdecea; color: #c0392b; border: 1px solid #f5b7b1; }
.notice--ok    { background: #eafaf1; color: #1e8449; border: 1px solid #a9dfbf; }

/* ── 卡片 ── */
.card { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; padding: 20px; margin-bottom: 14px; }
.card-head { display: flex; gap: 12px; align-items: flex-start; margin-bottom: 16px; }
.card-icon { font-size: 24px; line-height: 1; flex-shrink: 0; margin-top: 2px; }
.card-title { font-size: 16px; font-weight: 600; margin-bottom: 4px; }
.card-desc { font-size: 13px; color: var(--text-muted); line-height: 1.5; }

/* ── 操作行 ── */
.action-row { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
.input--fill { flex: 1; min-width: 160px; }

/* ── 内联消息 ── */
.inline-msg { font-size: 13px; padding: 6px 10px; border-radius: 5px; margin-bottom: 10px; }
.inline-msg--error { background: #fdecea; color: #c0392b; }
.inline-msg--ok    { background: #eafaf1; color: #1e8449; }

/* ── 分析结果 ── */
.result-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 16px; }
.result-cell { text-align: center; padding: 16px 12px; border-radius: 8px; border: 1px solid var(--border); }
.result-cell--ok   { background: #eafaf1; border-color: #a9dfbf; }
.result-cell--warn { background: #fef9e7; border-color: #f9e79f; }
.result-cell--muted { background: var(--bg-subtle, #f4f4f4); }
.result-num { display: block; font-size: 28px; font-weight: 700; line-height: 1.1; margin-bottom: 4px; }
.result-cell--ok .result-num   { color: #1e8449; }
.result-cell--warn .result-num { color: #b7950b; }
.result-cell--muted .result-num { color: var(--text-muted); }
.result-label { font-size: 12px; color: var(--text-muted); }

/* ── 待移动预览 ── */
.move-preview { margin-bottom: 14px; }
.move-summary { font-size: 13px; color: var(--text-muted); cursor: pointer; padding: 6px 0; user-select: none; }
.move-table { border: 1px solid var(--border); border-radius: 6px; overflow: hidden; margin-top: 8px; font-size: 12px; }
.move-table-head { display: grid; grid-template-columns: 2fr 1.5fr 1.5fr 1fr; background: var(--bg-subtle, #f4f4f4); padding: 6px 12px; font-weight: 600; color: var(--text-muted); gap: 8px; }
.move-row { display: grid; grid-template-columns: 2fr 1.5fr 1.5fr 1fr; padding: 7px 12px; border-top: 1px solid var(--border); align-items: center; gap: 8px; }
.move-row:hover { background: var(--bg-hover, #f8f8f8); }
.move-file { font-family: monospace; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.move-from { color: var(--text-muted); font-size: 11px; }
.move-to { color: #1e8449; font-weight: 600; font-size: 11px; }
.move-hint { font-size: 11px; color: var(--text-muted); }

/* ── 执行行 ── */
.execute-row { display: flex; flex-direction: column; gap: 8px; }
.btn--lg { padding: 10px 24px; font-size: 15px; font-weight: 600; }
.progress-wrap { height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--primary, #4f8ef7); border-radius: 2px; transition: width 0.2s ease; }

/* ── 标签同步 ── */
.tag-sync-result { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.badge { display: inline-flex; align-items: center; font-size: 12px; padding: 2px 8px; border-radius: 10px; background: var(--bg-subtle, #eee); color: var(--text-muted); }
.badge--ok   { background: #eafaf1; color: #1e8449; }
.badge--warn { background: #fef9e7; color: #b7950b; }

/* ── 文件浏览器折叠 ── */
.browser-section { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin-bottom: 14px; }
.browser-summary { display: flex; align-items: center; gap: 10px; padding: 14px 20px; cursor: pointer; font-size: 15px; font-weight: 600; user-select: none; list-style: none; }
.browser-summary::-webkit-details-marker { display: none; }
.browser-summary::before { content: '▸'; font-size: 12px; transition: transform 0.2s; margin-right: 2px; }
details[open] .browser-summary::before { transform: rotate(90deg); }
.browser-summary-hint { font-size: 13px; font-weight: 400; color: var(--text-muted); }
.browser-body { padding: 0 20px 20px; border-top: 1px solid var(--border); }

.browser-toolbar { display: flex; align-items: center; gap: 8px; padding: 12px 0; flex-wrap: wrap; }
.path-input { flex: 1; min-width: 160px; }

.filter-panel { background: var(--bg-subtle, #f8f8f8); border: 1px solid var(--border); border-radius: 6px; padding: 12px; margin-bottom: 12px; }
.filter-row { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; margin-bottom: 8px; }
.form-row-v { display: flex; flex-direction: column; gap: 4px; font-size: 12px; }
.check-label { display: flex; align-items: center; gap: 6px; font-size: 13px; cursor: pointer; }
.filter-presets { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }

.dir-chips { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 10px; }
.chip { display: inline-flex; align-items: center; padding: 3px 10px; border-radius: 12px; font-size: 12px; border: 1px solid var(--border); background: var(--bg-card); cursor: pointer; color: var(--text); transition: background 0.15s; }
.chip:hover { background: var(--bg-hover, #f0f0f0); }
.chip--dir { background: var(--bg-subtle, #f4f4f4); }
.chip--muted { color: var(--text-muted); }

.batch-bar { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--primary-light, #eef4ff); border: 1px solid var(--primary, #4f8ef7); border-radius: 6px; margin-bottom: 10px; flex-wrap: wrap; }
.batch-count { font-size: 13px; font-weight: 500; }
.list-status { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }

.browser-main { display: grid; grid-template-columns: 1fr 340px; gap: 14px; align-items: start; }

/* ── 文件列表 ── */
.file-table-wrap { border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.empty-state { text-align: center; padding: 32px 16px; color: var(--text-muted); font-size: 13px; }
.file-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.file-table thead th { background: var(--bg-subtle, #f4f4f4); padding: 7px 10px; text-align: left; font-weight: 500; font-size: 12px; color: var(--text-muted); border-bottom: 1px solid var(--border); }
.file-row { border-bottom: 1px solid var(--border); cursor: pointer; transition: background 0.12s; }
.file-row:last-child { border-bottom: none; }
.file-row:hover { background: var(--bg-hover, #f8f8f8); }
.row-active { background: var(--primary-light, #eef4ff) !important; }
.row-checked { background: var(--bg-selected, #f0f7ff); }
.file-row td { padding: 7px 10px; vertical-align: top; }
.col-check { width: 32px; }
.col-file { max-width: 0; }
.col-size  { width: 72px; text-align: right; white-space: nowrap; }
.col-time  { width: 90px; text-align: right; white-space: nowrap; }
.file-name { font-size: 13px; line-height: 1.3; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-dir  { font-size: 11px; margin-top: 2px; }
.file-tags { display: flex; gap: 3px; flex-wrap: wrap; margin-top: 3px; }
.tag-chip { display: inline-block; padding: 1px 6px; background: var(--bg-subtle, #eee); border-radius: 8px; font-size: 11px; color: var(--text-muted); }

/* ── 操作面板 ── */
.action-panel { position: sticky; top: 16px; max-height: 80vh; overflow-y: auto; }
.action-empty { background: var(--bg-subtle, #f8f8f8); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.empty-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 10px; }
.dir-bucket { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--border); }
.dir-bucket:last-of-type { border-bottom: none; }
.bucket-path { font-size: 12px; color: var(--primary, #4f8ef7); cursor: pointer; background: none; border: none; text-align: left; padding: 0; }
.bucket-count { font-size: 12px; color: var(--text-muted); }
.adv-ops { margin-top: 12px; }
.adv-btns { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
.adv-hint { margin-top: 6px; }

.file-panel { background: var(--bg-card); border: 1px solid var(--border); border-radius: 8px; padding: 14px; }
.file-preview-block { margin-bottom: 10px; text-align: center; }
.file-preview-img { max-width: 100%; max-height: 160px; border-radius: 6px; object-fit: contain; background: var(--bg-subtle, #f4f4f4); }
.current-tags { margin-bottom: 10px; display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }

.reclassify-form { display: flex; flex-direction: column; gap: 8px; }
.form-section-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); margin-bottom: 2px; }
.form-row-h { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.form-row-h > label { min-width: 56px; font-size: 12px; color: var(--text-muted); flex-shrink: 0; }

.seg-group { display: flex; border: 1px solid var(--border); border-radius: 5px; overflow: hidden; }
.seg-btn { flex: 1; padding: 4px 10px; font-size: 12px; background: var(--bg-card); border: none; cursor: pointer; color: var(--text); transition: background 0.12s; white-space: nowrap; }
.seg-btn + .seg-btn { border-left: 1px solid var(--border); }
.seg-btn:hover { background: var(--bg-hover, #f0f0f0); }
.seg-btn--active { background: var(--primary, #4f8ef7); color: #fff; }

.preview-box { background: var(--bg-subtle, #f4f4f4); border-radius: 5px; padding: 6px 10px; display: flex; gap: 4px; flex-wrap: wrap; align-items: center; font-size: 12px; }
.dir-input-wrap { display: flex; align-items: center; gap: 4px; flex: 1; }
.sync-options { display: flex; gap: 12px; padding: 4px 0; }
.apply-btns { display: flex; gap: 6px; margin-top: 2px; }

.auto-tag-block { border: 1px solid var(--border); border-radius: 6px; padding: 10px; margin-top: 10px; background: var(--bg-subtle, #f8f8f8); }
.auto-tag-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.auto-tag-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.auto-tag-result { font-size: 12px; color: var(--text-muted); margin-top: 6px; }
.file-actions { display: flex; gap: 6px; margin-top: 12px; flex-wrap: wrap; }

.btn--xs { padding: 2px 6px; font-size: 11px; }
.btn--ghost { background: transparent; border: none; box-shadow: none; }
.btn--accent { background: var(--accent, #8e44ad); color: #fff; }
.btn--danger { color: #c0392b; }
.btn--danger:hover { background: #fdecea; }
.hint { font-size: 12px; color: var(--text-muted); }
</style>
