<template>
  <div class="page">
    <!-- 页头 -->
    <div class="page-header">
      <div>
        <h1 class="page-title">数据同步 <small>多服务器去重迁移</small></h1>
      </div>
    </div>

    <div class="page-body">

      <!-- 统计概览 -->
      <div class="stats-row">
        <div class="stat-card">
          <div class="stat-value">{{ stats.wallpaper_total ?? '—' }}</div>
          <div class="stat-label">画廊总记录</div>
        </div>
        <div class="stat-card stat-card--blue">
          <div class="stat-value">{{ stats.wallpaper_uploaded ?? '—' }}</div>
          <div class="stat-label">画廊已上传</div>
        </div>
        <div class="stat-card stat-card--orange">
          <div class="stat-value">{{ stats.registry_total ?? '—' }}</div>
          <div class="stat-label">注册表记录</div>
        </div>
        <div class="stat-card stat-card--green">
          <div class="stat-value">{{ stats.registry_with_hash ?? '—' }}</div>
          <div class="stat-label">注册表含哈希</div>
        </div>
      </div>

      <!-- 工作流说明 -->
      <div class="card info-card">
        <div class="card-header">工作流程说明</div>
        <div class="info-body">
          <div class="flow-step">
            <span class="flow-num">1</span>
            <div>
              <strong>服务器 A 导出</strong>
              <p>将本机已上传图床的壁纸记录（含 resource_id、MD5/SHA256、图床 URL）导出为 JSON 文件。</p>
            </div>
          </div>
          <div class="flow-arrow">↓</div>
          <div class="flow-step">
            <span class="flow-num">2</span>
            <div>
              <strong>服务器 B 导入</strong>
              <p>在另一台服务器上传此 JSON。系统会将上传记录合并到本地数据库，已有条目不会被覆盖。</p>
            </div>
          </div>
          <div class="flow-arrow">↓</div>
          <div class="flow-step">
            <span class="flow-num">3</span>
            <div>
              <strong>自动去重生效</strong>
              <p>服务器 B 运行下载任务时，遇到已有 resource_id 的壁纸会自动跳过；文件哈希匹配时直接复用图床 URL，无需重复上传。</p>
            </div>
          </div>
        </div>
      </div>

      <div class="card settings-card">
        <div class="card-header">同步设置</div>
        <div class="panel-body">
          <p class="desc">这里可以直接配置当前服务器的同步安全策略。保存后会写入后端配置，远程服务器拉取本机导出数据时需要遵守这些限制。</p>

          <div class="form-row">
            <label class="field-label">本机同步密钥</label>
            <input
              v-model="syncSettings.auth_token"
              class="input"
              type="password"
              placeholder="留空表示不启用同步密钥"
            />
          </div>

          <div class="form-row">
            <label class="field-label">来源白名单</label>
            <textarea
              v-model="syncAllowedSourcesText"
              class="input input--textarea"
              placeholder="每行一个 IP 或 CIDR，例如：&#10;192.168.1.10&#10;10.0.0.0/24"
            ></textarea>
            <span class="toggle-hint">留空表示允许所有来源；建议公网部署时至少填写对端服务器出口 IP。</span>
          </div>

          <div class="form-row">
            <label class="field-label">每分钟请求上限</label>
            <input
              v-model.number="syncSettings.export_rate_limit_per_minute"
              class="input"
              type="number"
              min="0"
              max="600"
              placeholder="0 表示不限制"
            />
            <span class="toggle-hint">作用于 `/api/sync/handshake` 和 `/api/sync/export`，按来源单独计数。</span>
          </div>

          <div class="remote-actions">
            <button class="btn btn--primary" @click="saveSyncSettings" :disabled="savingSyncSettings">
              <span v-if="savingSyncSettings">保存中...</span>
              <span v-else>保存同步设置</span>
            </button>
            <span class="toggle-hint">保存后，同步导出接口会立刻应用新的密钥、白名单和限流策略。</span>
          </div>
        </div>
      </div>

      <div class="card history-card">
        <div class="card-header">最近操作</div>
        <div class="panel-body">
            <div v-if="recentActions.length" class="history-list">
              <div v-for="item in recentActions" :key="item.id" class="history-item">
                <div class="history-item__head">
                  <span class="history-item__type" :class="{ 'history-item__type--error': item.status === 'error' }">
                    {{ item.typeLabel }}
                  </span>
                  <span class="history-item__time">{{ formatTime(item.at) }}</span>
                </div>
                <div class="history-item__body">{{ item.summary }}</div>
                <div v-if="item.detail" class="history-item__detail">{{ item.detail }}</div>
              </div>
            </div>
          <div v-else class="history-empty">暂无最近操作记录</div>
        </div>
      </div>

      <div class="two-col">
        <!-- 导出 -->
        <div class="card">
          <div class="card-header">导出上传记录</div>
          <div class="panel-body">
            <p class="desc">将本机已上传图床的壁纸记录导出为 JSON 文件，可用于在其他服务器导入以避免重复上传。你也可以按 Profile 和格式缩小迁移范围。</p>

            <div class="toggle-row">
              <label class="toggle-label">
                <input type="checkbox" v-model="exportIncludeAll" />
                <span class="toggle-text">包含所有记录（含未上传）</span>
              </label>
              <span class="toggle-hint">默认只导出有图床 URL 的记录</span>
            </div>

            <div class="filter-grid">
              <div class="form-row">
                <label class="field-label">导出 Profile</label>
                <select v-model="exportProfileKey" class="input" :disabled="loadingExportOptions">
                  <option value="">全部 Profile</option>
                  <option v-for="item in exportOptions.profile_keys" :key="item.key" :value="item.key">
                    {{ item.key }}（{{ item.total }}）
                  </option>
                </select>
              </div>
              <div class="form-row">
                <label class="field-label">导出格式</label>
                <select v-model="exportFormatKey" class="input" :disabled="loadingExportOptions">
                  <option value="">全部格式</option>
                  <option v-for="item in exportOptions.format_keys" :key="item.key" :value="item.key">
                    {{ item.key }}（{{ item.total }}）
                  </option>
                </select>
              </div>
            </div>

            <div class="export-preview" v-if="exportEstimate.total !== undefined">
              <span class="preview-icon">◈</span>
              预计导出
              <strong>{{ exportEstimate.total }}</strong>
              条记录
              <span v-if="exportProfileKey || exportFormatKey">（已按筛选条件收缩范围）</span>
            </div>

            <div v-if="exportProfileKey || exportFormatKey" class="preview-tags">
              <span class="preview-tags__label">当前筛选：</span>
              <span v-if="exportProfileKey" class="preview-tag">{{ exportProfileKey }}</span>
              <span v-if="exportFormatKey" class="preview-tag">{{ exportFormatKey }}</span>
            </div>

            <button class="btn btn--primary export-btn" @click="doExport" :disabled="exporting">
              <span v-if="exporting">导出中...</span>
              <span v-else>↓ 下载 JSON 文件</span>
            </button>
          </div>
        </div>

        <!-- 导入 -->
        <div class="card">
          <div class="card-header">导入上传记录</div>
          <div class="panel-body">
            <p class="desc">选择从其他服务器导出的 JSON 文件，系统将合并上传记录到本地数据库。</p>

            <div
              class="drop-zone"
              :class="{ 'drop-zone--active': dragging, 'drop-zone--has-file': selectedFile }"
              @dragover.prevent="dragging = true"
              @dragleave.prevent="dragging = false"
              @drop.prevent="onDrop"
              @click="triggerFileInput"
            >
              <input
                ref="fileInputRef"
                type="file"
                accept=".json"
                style="display:none"
                @change="onFileChange"
              />
              <template v-if="selectedFile">
                <div class="drop-icon">◈</div>
                <div class="drop-filename">{{ selectedFile.name }}</div>
                <div class="drop-filesize">{{ formatBytes(selectedFile.size) }}</div>
              </template>
              <template v-else>
                <div class="drop-icon">↑</div>
                <div class="drop-text">点击选择或拖拽 JSON 文件</div>
              </template>
            </div>

            <div v-if="previewResult" class="preview-panel">
              <div class="preview-panel__head">
                <span class="preview-panel__title">同步包预览</span>
                <span class="preview-panel__meta">版本 {{ previewResult.version }}</span>
              </div>
              <div v-if="previewResult.warning" class="probe-warning">{{ previewResult.warning }}</div>
              <div class="preview-grid">
                <div class="probe-item">
                  <span class="probe-item__label">原始记录数</span>
                  <span class="probe-item__value">{{ previewResult.raw_record_count }}</span>
                </div>
                <div class="probe-item">
                  <span class="probe-item__label">可导入记录</span>
                  <span class="probe-item__value">{{ previewResult.normalized_count }}</span>
                </div>
                <div class="probe-item">
                  <span class="probe-item__label">含哈希数量</span>
                  <span class="probe-item__value">{{ previewResult.with_hash_count }}</span>
                </div>
                <div class="probe-item">
                  <span class="probe-item__label">来源服务器数</span>
                  <span class="probe-item__value">{{ previewResult.source_servers.length }}</span>
                </div>
              </div>
              <div v-if="previewResult.profile_keys.length" class="preview-tags">
                <span class="preview-tags__label">Profile：</span>
                <span v-for="key in previewResult.profile_keys" :key="key" class="preview-tag">{{ key }}</span>
              </div>
              <div v-if="previewResult.format_keys.length" class="preview-tags">
                <span class="preview-tags__label">格式：</span>
                <span v-for="key in previewResult.format_keys" :key="key" class="preview-tag">{{ key }}</span>
              </div>
              <div v-if="previewResult.source_servers.length" class="preview-tags">
                <span class="preview-tags__label">来源服务器：</span>
                <span v-for="key in previewResult.source_servers" :key="key" class="preview-tag">{{ key }}</span>
              </div>
            </div>

            <div v-if="previewError" class="error-list">
              <div class="error-title">预览失败</div>
              <div class="error-item">{{ previewError }}</div>
            </div>

            <button
              class="btn btn--primary import-btn"
              @click="doImport"
              :disabled="!selectedFile || importing || previewing || !!previewError"
            >
              <span v-if="previewing">预览中...</span>
              <span v-else-if="importing">导入中...</span>
              <span v-else>↑ 开始导入</span>
            </button>

            <!-- 导入结果 -->
            <div v-if="importResult" class="import-result">
              <div class="result-grid">
                <div class="result-item result-item--blue">
                  <div class="result-num">{{ importResult.total }}</div>
                  <div class="result-lbl">总条数</div>
                </div>
                <div class="result-item result-item--green">
                  <div class="result-num">{{ importResult.inserted }}</div>
                  <div class="result-lbl">新增注册</div>
                </div>
                <div class="result-item result-item--orange">
                  <div class="result-num">{{ importResult.merged }}</div>
                  <div class="result-lbl">合并更新</div>
                </div>
                <div class="result-item result-item--grey">
                  <div class="result-num">{{ importResult.skipped }}</div>
                  <div class="result-lbl">已是最新</div>
                </div>
              </div>
              <div v-if="importResult.errors.length" class="error-list">
                <div class="error-title">错误（{{ importResult.errors.length }} 条）</div>
                <div v-for="e in importResult.errors" :key="e" class="error-item">{{ e }}</div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="card remote-card">
        <div class="card-header">一键从远程服务器迁移</div>
        <div class="panel-body">
          <p class="desc">填写另一台服务器的访问地址，系统会自动请求其同步导出接口并导入到本机注册表。</p>

          <div class="form-row">
            <label class="field-label">远程地址</label>
            <input
              v-model.trim="remoteBaseUrl"
              class="input"
              placeholder="例如：http://192.168.1.20:8000 或 https://example.com"
            />
          </div>

          <label class="toggle-label">
            <input type="checkbox" v-model="remoteIncludeAll" />
            <span class="toggle-text">请求远程导出全部记录</span>
          </label>

          <div class="form-row">
            <label class="field-label">远程迁移密钥</label>
            <input
              v-model="remoteSyncToken"
              class="input"
              type="password"
              placeholder="如果源服务器配置了 sync.auth_token，请在这里填写"
            />
          </div>

          <div class="remote-actions">
            <button class="btn" @click="probeRemote" :disabled="probing || !remoteBaseUrl">
              <span v-if="probing">测试中...</span>
              <span v-else>测试远程连接</span>
            </button>
            <button class="btn btn--primary" @click="pullRemote" :disabled="pulling || !remoteBaseUrl">
              <span v-if="pulling">迁移中...</span>
              <span v-else>⇅ 开始一键迁移</span>
            </button>
            <span class="toggle-hint">目标服务器需要可访问其 `/api/sync/export` 接口。</span>
          </div>

          <div v-if="probeResult" class="probe-panel">
            <div class="probe-panel__head">
              <span class="probe-dot" :class="probeResult.ok ? 'probe-dot--ok' : 'probe-dot--err'"></span>
              <span>{{ probeResult.ok ? '远程连接正常' : '远程连接异常' }}</span>
            </div>
            <div v-if="probeResult.warning" class="probe-warning">{{ probeResult.warning }}</div>
            <div class="probe-grid">
              <div class="probe-item">
                <span class="probe-item__label">远程服务</span>
                <span class="probe-item__value">{{ probeResult.source_server || '—' }}</span>
              </div>
              <div class="probe-item">
                <span class="probe-item__label">对端识别到的来源</span>
                <span class="probe-item__value">{{ probeResult.request_source || '—' }}</span>
              </div>
              <div class="probe-item">
                <span class="probe-item__label">协议版本</span>
                <span class="probe-item__value">{{ probeResult.version || '—' }}</span>
              </div>
              <div class="probe-item">
                <span class="probe-item__label">可导出记录</span>
                <span class="probe-item__value">{{ probeResult.stats?.registry_exportable ?? '—' }}</span>
              </div>
              <div class="probe-item">
                <span class="probe-item__label">注册表总量</span>
                <span class="probe-item__value">{{ probeResult.stats?.registry_total ?? '—' }}</span>
              </div>
              <div class="probe-item">
                <span class="probe-item__label">白名单</span>
                <span class="probe-item__value">{{ probeResult.stats?.export_allowlist_enabled ? '已启用' : '未启用' }}</span>
              </div>
              <div class="probe-item">
                <span class="probe-item__label">限流</span>
                <span class="probe-item__value">{{ probeResult.stats?.export_rate_limit_per_minute ?? 0 }}/分钟</span>
              </div>
            </div>
            <div v-if="probeResult.error" class="probe-error">{{ probeResult.error }}</div>
          </div>

          <div v-if="pullResult" class="import-result">
            <div class="result-grid">
              <div class="result-item result-item--blue">
                <div class="result-num">{{ pullResult.total }}</div>
                <div class="result-lbl">总条数</div>
              </div>
              <div class="result-item result-item--green">
                <div class="result-num">{{ pullResult.inserted }}</div>
                <div class="result-lbl">新增注册</div>
              </div>
              <div class="result-item result-item--orange">
                <div class="result-num">{{ pullResult.merged }}</div>
                <div class="result-lbl">合并更新</div>
              </div>
              <div class="result-item result-item--grey">
                <div class="result-num">{{ pullResult.skipped }}</div>
                <div class="result-lbl">已是最新</div>
              </div>
            </div>
            <div v-if="pullResult.errors.length" class="error-list">
              <div class="error-title">错误（{{ pullResult.errors.length }} 条）</div>
              <div v-for="e in pullResult.errors" :key="e" class="error-item">{{ e }}</div>
            </div>
          </div>
        </div>
      </div>

      <div class="card remote-card">
        <div class="card-header">注册表重复项</div>
        <div class="panel-body">
          <p class="desc">扫描 `upload_registry` 中由多次导入、历史回填或重复上传造成的冗余记录。合并时会保留信息最完整的一条主记录，其余同组记录会被删除。</p>

          <div class="remote-actions">
            <button class="btn" @click="scanRegistryDuplicates(true)" :disabled="scanningDuplicates">
              <span v-if="scanningDuplicates">扫描中...</span>
              <span v-else>扫描重复项</span>
            </button>
            <button
              class="btn btn--primary"
              @click="mergeRegistryDuplicates"
              :disabled="mergingDuplicates || !duplicateSummary?.total_groups"
            >
              <span v-if="mergingDuplicates">合并中...</span>
              <span v-else>一键合并重复项</span>
            </button>
            <span class="toggle-hint">当前会优先按 `sha256`，其次 `md5`、`resource_id` 来识别同组重复项。</span>
          </div>

          <div v-if="duplicateSummary" class="probe-panel">
            <div class="result-grid">
              <div class="result-item result-item--blue">
                <div class="result-num">{{ duplicateSummary.total_groups }}</div>
                <div class="result-lbl">重复组</div>
              </div>
              <div class="result-item result-item--orange">
                <div class="result-num">{{ duplicateSummary.total_duplicate_rows }}</div>
                <div class="result-lbl">冗余记录</div>
              </div>
              <div class="result-item result-item--grey">
                <div class="result-num">{{ duplicateSummary.conflict_groups }}</div>
                <div class="result-lbl">URL 冲突组</div>
              </div>
              <div class="result-item result-item--grey">
                <div class="result-num">{{ duplicateSummary.skipped_without_identity }}</div>
                <div class="result-lbl">无身份键</div>
              </div>
            </div>

            <div v-if="duplicateSummary.groups.length" class="duplicate-list">
              <div v-for="item in duplicateSummary.groups" :key="item.identity_key" class="duplicate-item">
                <div class="duplicate-item__head">
                  <span class="duplicate-item__title">{{ item.profile_key }} / {{ item.format_key }}</span>
                  <span class="duplicate-item__meta">主记录 #{{ item.canonical_id }}，共 {{ item.count }} 条</span>
                </div>
                <div class="duplicate-item__row">匹配字段：{{ item.identity_type }} / {{ item.match_value }}</div>
                <div class="duplicate-item__row">重复 ID：#{{ item.duplicate_ids.join('，#') }}</div>
                <div class="duplicate-item__row">URL 数：{{ item.url_count }}</div>
                <div v-if="item.source_servers.length" class="preview-tags">
                  <span class="preview-tags__label">来源服务器：</span>
                  <span v-for="key in item.source_servers" :key="key" class="preview-tag">{{ key }}</span>
                </div>
                <div v-if="item.sample_urls.length" class="preview-tags">
                  <span class="preview-tags__label">示例 URL：</span>
                  <span v-for="key in item.sample_urls" :key="key" class="preview-tag preview-tag--url">{{ key }}</span>
                </div>
              </div>
            </div>
          </div>

          <div v-if="duplicateMergeResult" class="import-result">
            <div class="result-grid">
              <div class="result-item result-item--blue">
                <div class="result-num">{{ duplicateMergeResult.scanned_groups }}</div>
                <div class="result-lbl">扫描组数</div>
              </div>
              <div class="result-item result-item--green">
                <div class="result-num">{{ duplicateMergeResult.merged_groups }}</div>
                <div class="result-lbl">已合并</div>
              </div>
              <div class="result-item result-item--orange">
                <div class="result-num">{{ duplicateMergeResult.removed_rows }}</div>
                <div class="result-lbl">移除冗余</div>
              </div>
              <div class="result-item result-item--grey">
                <div class="result-num">{{ duplicateMergeResult.updated_primary_rows }}</div>
                <div class="result-lbl">主记录补全</div>
              </div>
            </div>
            <div v-if="duplicateMergeResult.errors.length" class="error-list">
              <div class="error-title">错误（{{ duplicateMergeResult.errors.length }} 条）</div>
              <div v-for="e in duplicateMergeResult.errors" :key="e" class="error-item">{{ e }}</div>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { settingsApi } from '../api'

const stats = ref({})
const syncSettings = ref({ auth_token: '', allowed_sources: [], export_rate_limit_per_minute: 60 })
const syncAllowedSourcesText = ref('')
const exporting = ref(false)
const importing = ref(false)
const pulling = ref(false)
const probing = ref(false)
const savingSyncSettings = ref(false)
const exportIncludeAll = ref(false)
const exportProfileKey = ref('')
const exportFormatKey = ref('')
const exportOptions = ref({ profile_keys: [], format_keys: [] })
const exportEstimate = ref({ total: 0 })
const loadingExportOptions = ref(false)
const selectedFile = ref(null)
const dragging = ref(false)
const fileInputRef = ref(null)
const importResult = ref(null)
const pullResult = ref(null)
const probeResult = ref(null)
const previewResult = ref(null)
const previewing = ref(false)
const previewError = ref('')
const duplicateSummary = ref(null)
const duplicateMergeResult = ref(null)
const scanningDuplicates = ref(false)
const mergingDuplicates = ref(false)
const recentActions = ref([])
const remoteBaseUrl = ref('')
const remoteIncludeAll = ref(false)
const remoteSyncToken = ref('')
const REMOTE_SYNC_STORAGE_KEY = 'hao-wallpaper-sync-remote-base-url'

async function loadStats() {
  try {
    const res = await fetch('/api/sync/stats')
    stats.value = await res.json()
  } catch (e) {
    console.error('加载统计失败', e)
  }
}

async function loadSyncSettings() {
  try {
    const data = await settingsApi.getSync()
    syncSettings.value = {
      auth_token: data.auth_token || '',
      allowed_sources: Array.isArray(data.allowed_sources) ? data.allowed_sources : [],
      export_rate_limit_per_minute: Number(data.export_rate_limit_per_minute ?? 60),
    }
    syncAllowedSourcesText.value = syncSettings.value.allowed_sources.join('\n')
  } catch (e) {
    console.error('加载同步设置失败', e)
  }
}

async function saveSyncSettings() {
  savingSyncSettings.value = true
  try {
    const allowedSources = syncAllowedSourcesText.value
      .split(/\r?\n|,/)
      .map((item) => item.trim())
      .filter(Boolean)
    const res = await settingsApi.setSync({
      auth_token: (syncSettings.value.auth_token || '').trim(),
      allowed_sources: allowedSources,
      export_rate_limit_per_minute: Math.max(0, Number(syncSettings.value.export_rate_limit_per_minute || 0)),
    })
    syncSettings.value = {
      auth_token: res.sync?.auth_token || '',
      allowed_sources: Array.isArray(res.sync?.allowed_sources) ? res.sync.allowed_sources : [],
      export_rate_limit_per_minute: Number(res.sync?.export_rate_limit_per_minute ?? 60),
    }
    syncAllowedSourcesText.value = syncSettings.value.allowed_sources.join('\n')
    await loadStats()
  } catch (e) {
    alert('保存同步设置失败: ' + e.message)
  } finally {
    savingSyncSettings.value = false
  }
}

async function probeRemote() {
  if (!remoteBaseUrl.value) return
  probing.value = true
  probeResult.value = null
  try {
    const res = await fetch('/api/sync/probe', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        remote_base_url: remoteBaseUrl.value,
        remote_sync_token: remoteSyncToken.value.trim() || undefined,
      }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data))
    probeResult.value = data
    await loadRecentActions()
  } catch (e) {
    probeResult.value = { ok: false, error: e.message, stats: {} }
    await loadRecentActions()
    alert('远程测试失败: ' + e.message)
  } finally {
    probing.value = false
  }
}

async function doExport() {
  exporting.value = true
  try {
    const params = new URLSearchParams({
      include_all: String(exportIncludeAll.value),
    })
    if (exportProfileKey.value) params.set('profile_keys', exportProfileKey.value)
    if (exportFormatKey.value) params.set('format_keys', exportFormatKey.value)
    const url = `/api/sync/export?${params.toString()}`
    const headers = {}
    if ((syncSettings.value.auth_token || '').trim()) headers['X-Sync-Token'] = syncSettings.value.auth_token.trim()
    const res = await fetch(url, { headers })
    if (!res.ok) throw new Error(await res.text())
    const blob = await res.blob()
    const disposition = res.headers.get('content-disposition') || ''
    const match = disposition.match(/filename="(.+?)"/)
    const filename = match ? match[1] : 'wallpaper-sync.json'
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = filename
    a.click()
    URL.revokeObjectURL(a.href)
    await loadRecentActions()
  } catch (e) {
    alert('导出失败: ' + e.message)
  } finally {
    exporting.value = false
  }
}

async function loadExportOptions() {
  loadingExportOptions.value = true
  try {
    const res = await fetch(`/api/sync/export-options?include_all=${exportIncludeAll.value}`)
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data))
    exportOptions.value = data

    if (exportProfileKey.value && !data.profile_keys.some((item) => item.key === exportProfileKey.value)) {
      exportProfileKey.value = ''
    }
    if (exportFormatKey.value && !data.format_keys.some((item) => item.key === exportFormatKey.value)) {
      exportFormatKey.value = ''
    }
  } catch (e) {
    console.error('加载导出筛选项失败', e)
  } finally {
    loadingExportOptions.value = false
  }
}

async function loadExportEstimate() {
  try {
    const params = new URLSearchParams({
      include_all: String(exportIncludeAll.value),
    })
    if (exportProfileKey.value) params.set('profile_keys', exportProfileKey.value)
    if (exportFormatKey.value) params.set('format_keys', exportFormatKey.value)
    const res = await fetch(`/api/sync/export-estimate?${params.toString()}`)
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data))
    exportEstimate.value = data
  } catch (e) {
    console.error('加载导出预估失败', e)
  }
}

function triggerFileInput() {
  fileInputRef.value?.click()
}

function onFileChange(e) {
  const f = e.target.files[0]
  if (f) {
    selectedFile.value = f
    importResult.value = null
    previewResult.value = null
    previewError.value = ''
    previewImportFile()
  }
}

function onDrop(e) {
  dragging.value = false
  const f = e.dataTransfer.files[0]
  if (f && f.name.endsWith('.json')) {
    selectedFile.value = f
    importResult.value = null
    previewResult.value = null
    previewError.value = ''
    previewImportFile()
  }
}

async function previewImportFile() {
  if (!selectedFile.value) return
  previewing.value = true
  previewResult.value = null
  previewError.value = ''
  try {
    const form = new FormData()
    form.append('file', selectedFile.value)
    const res = await fetch('/api/sync/preview', { method: 'POST', body: form })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data))
    previewResult.value = data
  } catch (e) {
    previewError.value = e.message
  } finally {
    previewing.value = false
  }
}

async function doImport() {
  if (!selectedFile.value) return
  importing.value = true
  importResult.value = null
  try {
    const form = new FormData()
    form.append('file', selectedFile.value)
    const res = await fetch('/api/sync/import', { method: 'POST', body: form })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data))
    importResult.value = data
    await loadStats()
    if (duplicateSummary.value) {
      await scanRegistryDuplicates(false, false, false)
    }
    await loadRecentActions()
  } catch (e) {
    await loadRecentActions()
    alert('导入失败: ' + e.message)
  } finally {
    importing.value = false
  }
}

async function pullRemote() {
  if (!remoteBaseUrl.value) return
  pulling.value = true
  pullResult.value = null
  try {
    const res = await fetch('/api/sync/pull', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        remote_base_url: remoteBaseUrl.value,
        include_all: remoteIncludeAll.value,
        remote_sync_token: remoteSyncToken.value.trim() || undefined,
      }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data))
    pullResult.value = data
    await loadStats()
    if (duplicateSummary.value) {
      await scanRegistryDuplicates(false, false, false)
    }
    await loadRecentActions()
  } catch (e) {
    await loadRecentActions()
    alert('远程迁移失败: ' + e.message)
  } finally {
    pulling.value = false
  }
}

async function scanRegistryDuplicates(showAlert = false, resetMergeResult = true, recordHistory = true) {
  scanningDuplicates.value = true
  try {
    const res = await fetch('/api/sync/duplicates?limit=8')
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data))
    duplicateSummary.value = data
    if (resetMergeResult) {
      duplicateMergeResult.value = null
    }
    if (recordHistory) {
      await loadRecentActions()
    }
    if (showAlert) {
      alert(`扫描完成：发现 ${data.total_groups} 组重复项，冗余记录 ${data.total_duplicate_rows} 条`)
    }
  } catch (e) {
    if (showAlert) {
      alert('扫描重复项失败: ' + e.message)
    }
  } finally {
    scanningDuplicates.value = false
  }
}

async function mergeRegistryDuplicates() {
  if (!duplicateSummary.value?.total_groups) return
  const confirmed = window.confirm(
    `将合并 ${duplicateSummary.value.total_groups} 组重复项，并删除 ${duplicateSummary.value.total_duplicate_rows} 条冗余记录。是否继续？`
  )
  if (!confirmed) return

  mergingDuplicates.value = true
  duplicateMergeResult.value = null
  try {
    const res = await fetch('/api/sync/duplicates/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit: 50 }),
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data))
    duplicateMergeResult.value = data
    await loadStats()
    await scanRegistryDuplicates(false, false, false)
    await loadRecentActions()
  } catch (e) {
    alert('合并重复项失败: ' + e.message)
  } finally {
    mergingDuplicates.value = false
  }
}

function formatBytes(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

async function loadRecentActions() {
  try {
    const res = await fetch('/api/sync/history?limit=12')
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || JSON.stringify(data))
    recentActions.value = (data.items || []).map((item) => ({
      id: item.id,
      at: item.at,
      status: item.status,
      type: item.type,
      typeLabel: item.type_label,
      summary: item.summary,
      detail: item.detail,
    }))
  } catch {
    recentActions.value = []
  }
}

onMounted(async () => {
  remoteBaseUrl.value = localStorage.getItem(REMOTE_SYNC_STORAGE_KEY) || ''
  await Promise.all([loadStats(), loadSyncSettings(), loadExportOptions(), loadRecentActions()])
  await loadExportEstimate()
})

watch(remoteBaseUrl, (value) => {
  localStorage.setItem(REMOTE_SYNC_STORAGE_KEY, value || '')
})

watch(exportIncludeAll, async () => {
  await loadExportOptions()
  await loadExportEstimate()
})

watch([exportProfileKey, exportFormatKey], () => {
  loadExportEstimate()
})
</script>

<style scoped>
.page { min-height: 100vh; }

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 20px;
  text-align: center;
}
.stat-card--blue  { border-color: var(--accent-dim); }
.stat-card--orange { border-color: rgba(245,166,35,.3); }
.stat-card--green  { border-color: rgba(62,207,114,.3); }

.stat-value { font-size: 28px; font-weight: 700; font-family: var(--font-ui); color: var(--text-1); }
.stat-card--blue  .stat-value { color: var(--accent); }
.stat-card--orange .stat-value { color: var(--orange); }
.stat-card--green  .stat-value { color: var(--green); }
.stat-label { font-size: 11px; color: var(--text-3); margin-top: 4px; text-transform: uppercase; letter-spacing: .05em; }

/* 说明卡片 */
.info-card { margin-bottom: 24px; }
.settings-card { margin-bottom: 24px; }
.history-card { margin-bottom: 24px; }
.info-body { padding: 20px 24px; display: flex; flex-direction: column; gap: 0; }
.history-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.history-item {
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-base);
}
.history-item__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}
.history-item__type {
  font-size: 11px;
  color: var(--accent);
  text-transform: uppercase;
  letter-spacing: .05em;
}
.history-item__type--error {
  color: var(--red);
}
.history-item__time {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-ui);
}
.history-item__body {
  font-size: 13px;
  color: var(--text-2);
  line-height: 1.6;
}
.history-item__detail {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
  margin-top: 4px;
  word-break: break-word;
}
.history-empty {
  font-size: 13px;
  color: var(--text-3);
}
.flow-step {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  padding: 12px 0;
}
.flow-num {
  width: 26px; height: 26px;
  border-radius: 50%;
  background: var(--accent-dim);
  color: var(--accent);
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  font-family: var(--font-ui);
}
.flow-step strong { font-size: 13px; color: var(--text-1); display: block; margin-bottom: 4px; }
.flow-step p { font-size: 12px; color: var(--text-2); line-height: 1.6; margin: 0; }
.flow-arrow { color: var(--text-3); font-size: 18px; padding-left: 12px; }

/* 两列布局 */
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
}

.panel-body { padding: 20px 24px; display: flex; flex-direction: column; gap: 16px; }
.desc { font-size: 13px; color: var(--text-2); line-height: 1.6; }
.field-label { font-size: 12px; color: var(--text-2); }
.form-row { display: flex; flex-direction: column; gap: 8px; }
.input {
  width: 100%;
  min-height: 40px;
  padding: 0 12px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  background: var(--bg-base);
  color: var(--text-1);
}
.input--textarea {
  min-height: 110px;
  padding: 10px 12px;
  resize: vertical;
}
.input:focus {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-glow);
}

/* 导出切换 */
.toggle-row { display: flex; flex-direction: column; gap: 4px; }
.toggle-label { display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px; color: var(--text-1); }
.toggle-label input[type=checkbox] { width: 14px; height: 14px; accent-color: var(--accent); cursor: pointer; }
.toggle-hint { font-size: 11px; color: var(--text-3); padding-left: 22px; }
.filter-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.export-preview {
  background: var(--bg-base);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  font-size: 13px;
  color: var(--text-2);
}
.export-preview strong { color: var(--accent); font-family: var(--font-ui); }
.preview-icon { color: var(--accent); margin-right: 6px; }

.export-btn, .import-btn { align-self: flex-start; }
.remote-card { margin-top: 24px; }
.remote-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.probe-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-base);
}
.probe-panel__head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-1);
}
.probe-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.probe-dot--ok {
  background: var(--green);
  box-shadow: 0 0 6px rgba(62, 207, 114, 0.45);
}
.probe-dot--err {
  background: var(--red);
  box-shadow: 0 0 6px rgba(240, 90, 90, 0.45);
}
.probe-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.probe-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-card);
}
.probe-item__label {
  font-size: 10px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: .05em;
}
.probe-item__value {
  font-size: 13px;
  color: var(--text-1);
  font-family: var(--font-ui);
}
.probe-error {
  font-size: 12px;
  color: var(--red);
  line-height: 1.6;
}
.probe-warning {
  font-size: 12px;
  color: var(--orange);
  line-height: 1.6;
}

/* 拖拽区域 */
.drop-zone {
  border: 2px dashed var(--border-hi);
  border-radius: var(--radius);
  padding: 28px 20px;
  text-align: center;
  cursor: pointer;
  transition: all .15s;
  background: var(--bg-base);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.drop-zone:hover, .drop-zone--active {
  border-color: var(--accent);
  background: var(--accent-glow);
}
.drop-zone--has-file {
  border-color: var(--green);
  background: rgba(62,207,114,.05);
}
.drop-icon { font-size: 24px; color: var(--text-3); }
.drop-zone--has-file .drop-icon { color: var(--green); }
.drop-text { font-size: 13px; color: var(--text-3); }
.drop-filename { font-size: 13px; color: var(--text-1); font-family: var(--font-ui); }
.drop-filesize { font-size: 11px; color: var(--text-3); }
.preview-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-base);
}
.preview-panel__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}
.preview-panel__title {
  font-size: 13px;
  color: var(--text-1);
}
.preview-panel__meta {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-ui);
}
.preview-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.preview-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.preview-tags__label {
  font-size: 11px;
  color: var(--text-3);
}
.preview-tag {
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--accent-glow);
  color: var(--accent);
  font-size: 11px;
  font-family: var(--font-ui);
}
.preview-tag--url {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}
.duplicate-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.duplicate-item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-card);
}
.duplicate-item__head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}
.duplicate-item__title {
  font-size: 13px;
  color: var(--text-1);
  font-weight: 600;
}
.duplicate-item__meta {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-ui);
}
.duplicate-item__row {
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.6;
  word-break: break-all;
}

/* 导入结果 */
.import-result { display: flex; flex-direction: column; gap: 12px; }
.result-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
}
.result-item {
  background: var(--bg-base);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 6px;
  text-align: center;
}
.result-item--blue   { border-color: var(--accent-dim); }
.result-item--green  { border-color: rgba(62,207,114,.3); }
.result-item--orange { border-color: rgba(245,166,35,.3); }
.result-item--grey   { border-color: var(--border-hi); }

.result-num { font-size: 20px; font-weight: 700; font-family: var(--font-ui); color: var(--text-1); }
.result-item--blue   .result-num { color: var(--accent); }
.result-item--green  .result-num { color: var(--green); }
.result-item--orange .result-num { color: var(--orange); }

.result-lbl { font-size: 10px; color: var(--text-3); text-transform: uppercase; letter-spacing: .04em; margin-top: 2px; }

.error-list {
  background: rgba(240,90,90,.08);
  border: 1px solid rgba(240,90,90,.25);
  border-radius: var(--radius);
  padding: 10px 14px;
}
.error-title { font-size: 11px; color: var(--red); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 6px; }
.error-item { font-size: 12px; color: var(--text-2); font-family: var(--font-ui); line-height: 1.8; }

@media (max-width: 960px) {
  .stats-row,
  .result-grid,
  .two-col,
  .probe-grid,
  .preview-grid,
  .filter-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 640px) {
  .stats-row,
  .result-grid,
  .two-col,
  .probe-grid,
  .preview-grid,
  .filter-grid {
    grid-template-columns: 1fr;
  }
}
</style>
