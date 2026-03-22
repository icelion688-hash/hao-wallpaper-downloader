<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-title">远端图床管理 <small>独立工作台</small></h1>
        <div class="page-subtitle">支持筛选、目录浏览、标签维护、单个与批量移动、批量删除。</div>
      </div>
      <div class="head-actions">
        <button class="btn" @click="loadSettings" :disabled="loadingProfiles">刷新 Profile</button>
        <button class="btn btn--primary" @click="loadRemoteList" :disabled="remoteLoading || !profileReady">刷新列表</button>
      </div>
    </div>

    <div class="page-body">
      <div class="top-grid">
        <section class="card block">
          <div class="card-header">Profile 与权限</div>
          <div class="block-body">
            <label class="form-row">
              <span>当前 Profile</span>
              <select class="select" v-model="activeKey">
                <option v-for="profile in profiles" :key="profile.key" :value="profile.key">{{ profile.name }} ({{ profile.key }})</option>
              </select>
            </label>
            <div v-if="activeProfile" class="inline-row">
              <span class="tag" :class="activeProfile.enabled ? 'tag--ok' : 'tag--warn'">{{ activeProfile.enabled ? '已启用' : '未启用' }}</span>
              <span class="tag tag--grey">{{ activeProfile.channel }}</span>
              <span class="mono">{{ activeProfile.base_url || '-' }}</span>
            </div>
            <div class="inline-row" v-if="activeProfile?.base_url && activeProfile?.api_token">
              <button class="btn btn--sm" @click="loadRemoteCapabilities" :disabled="capabilityLoading || !profileReady">{{ capabilityLoading ? '检测中...' : '检测权限' }}</button>
              <span class="tag" :class="remoteCapabilities?.channels ? 'tag--ok' : 'tag--warn'">channels {{ remoteCapabilities?.channels ? '可用' : '不可用' }}</span>
              <span class="tag" :class="remoteCapabilities?.list ? 'tag--ok' : 'tag--warn'">list {{ remoteCapabilities?.list ? '可用' : '不可用' }}</span>
              <span class="tag" :class="remoteCapabilities?.manage ? 'tag--ok' : 'tag--warn'">manage {{ remoteCapabilities?.manage ? '可用' : '不可用' }}</span>
            </div>
            <div class="hint" v-if="activeProfile && !profileReady">当前 Profile 未启用或缺少 `base_url / api_token`。</div>
            <div class="error" v-if="remoteError">{{ remoteError }}</div>
          </div>
        </section>

        <section class="card block">
          <div class="card-header">查询与索引</div>
          <div class="block-body">
            <div class="field-grid">
              <label class="form-row"><span>目录</span><input class="input" v-model.trim="remoteQuery.dir" placeholder="例如 wallpaper/static" /></label>
              <label class="form-row"><span>搜索文件名</span><input class="input" v-model.trim="remoteQuery.search" placeholder="关键字" /></label>
              <label class="form-row"><span>包含标签</span><input class="input" v-model.trim="remoteQuery.includeTags" placeholder="逗号分隔" /></label>
              <label class="form-row"><span>排除标签</span><input class="input" v-model.trim="remoteQuery.excludeTags" placeholder="逗号分隔" /></label>
              <label class="form-row">
                <span>存储通道</span>
                <select class="select" v-model="remoteQuery.channel">
                  <option value="">全部</option>
                  <option value="telegram">telegram</option>
                  <option value="cfr2">cfr2</option>
                  <option value="s3">s3</option>
                  <option value="discord">discord</option>
                  <option value="huggingface">huggingface</option>
                </select>
              </label>
              <label class="form-row">
                <span>返回数量</span>
                <select class="select" v-model.number="remoteQuery.count">
                  <option :value="20">20</option><option :value="50">50</option><option :value="100">100</option><option :value="200">200</option>
                </select>
              </label>
            </div>
            <label class="check-label"><input type="checkbox" v-model="remoteQuery.recursive" />递归列出子目录</label>
            <div class="inline-row">
              <button class="btn btn--sm" @click="loadRemoteList" :disabled="remoteLoading || !profileReady">加载列表</button>
              <button class="btn btn--sm" @click="loadRemoteIndexInfo" :disabled="remoteActionLoading || !profileReady">索引信息</button>
              <button class="btn btn--sm" @click="rebuildRemoteIndex" :disabled="remoteActionLoading || !profileReady">重建索引</button>
              <button class="btn btn--sm" @click="goParentDirectory" :disabled="!remoteParentDir && !remoteQuery.dir">返回上级</button>
            </div>
            <div class="inline-row meta-row">
              <span>当前目录: {{ remoteQuery.dir || '/' }}</span>
              <span v-if="remoteSummary">{{ remoteSummary }}</span>
              <span v-if="remoteIndexInfo?.lastUpdated || remoteIndexInfo?.indexLastUpdated">最近更新: {{ formatTimestamp(remoteIndexInfo?.lastUpdated || remoteIndexInfo?.indexLastUpdated) }}</span>
            </div>
            <div class="chip-row" v-if="remoteDirectories.length">
              <button v-for="directory in remoteDirectories" :key="directory" class="directory-chip" @click="openDirectory(directory)">{{ directory }}</button>
            </div>
          </div>
        </section>
      </div>

      <div class="main-grid">
        <section class="card block">
          <div class="card-header">远端文件列表</div>
          <div class="block-body">
            <div class="inline-row">
              <button class="btn btn--sm" @click="toggleSelectCurrentPage(true)" :disabled="!remoteFiles.length">全选当前列表</button>
              <button class="btn btn--sm" @click="toggleSelectCurrentPage(false)" :disabled="!selectedPaths.length">清空选择</button>
              <span class="hint" v-if="selectedPaths.length">已选 {{ selectedPaths.length }} 个文件</span>
            </div>

            <div class="batch-box" v-if="selectedPaths.length">
              <div class="batch-row">
                <textarea class="input textarea" v-model.trim="batchTagsInput" rows="3" placeholder="批量标签，多个标签用逗号分隔"></textarea>
                <div class="inline-row">
                  <select class="select" v-model="batchTagAction">
                    <option value="set">set 覆盖</option>
                    <option value="add">add 追加</option>
                    <option value="remove">remove 移除</option>
                  </select>
                  <button class="btn btn--sm btn--primary" @click="applyBatchTags" :disabled="batchActionLoading || !canManageBatch">批量保存标签</button>
                </div>
              </div>
              <div class="batch-row">
                <div class="inline-row">
                  <input class="input" v-model.trim="batchMoveTarget" placeholder="批量移动目标目录" />
                  <button class="btn btn--sm" @click="moveSelectedFiles" :disabled="batchActionLoading || !canManageBatch || !batchMoveTarget">批量移动</button>
                  <button class="btn btn--sm btn--danger" @click="deleteSelectedFiles" :disabled="batchActionLoading">删除已选</button>
                </div>
              </div>
            </div>

            <div class="remote-table-wrap">
              <table class="remote-table" v-if="remoteFiles.length">
                <thead>
                  <tr>
                    <th>文件</th><th>通道</th><th>MIME</th><th>大小</th><th>时间</th><th class="remote-table__actions">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="file in remoteFiles" :key="file.name" :class="{ 'row-active': selectedFile?.name === file.name }" @click="selectFile(file)">
                    <td class="remote-name">{{ file.name }}</td>
                    <td>{{ file.metadata?.Channel || '-' }}</td>
                    <td>{{ file.metadata?.['File-Mime'] || '-' }}</td>
                    <td>{{ formatRemoteSize(file.metadata?.['File-Size']) }}</td>
                    <td>{{ formatTimestamp(file.metadata?.TimeStamp) }}</td>
                    <td class="remote-table__actions">
                      <button class="btn btn--sm" @click.stop="toggleSelectFile(file.name)">{{ selectedPaths.includes(file.name) ? '移出批量' : '加入批量' }}</button>
                      <button class="btn btn--sm btn--danger" @click.stop="deleteRemote(file.name, false)" :disabled="remoteActionLoading">删除</button>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-else class="empty"> {{ remoteLoading ? '正在加载远端文件...' : '当前条件下没有返回文件。' }} </div>
            </div>
          </div>
        </section>

        <aside class="card block detail-panel">
          <div class="card-header">文件详情</div>
          <div class="block-body" v-if="selectedFile">
            <div class="detail-box">
              <div class="detail-line"><span>文件</span><code>{{ selectedFile.name }}</code></div>
              <div class="detail-line"><span>通道</span><code>{{ selectedFile.metadata?.Channel || '-' }}</code></div>
              <div class="detail-line"><span>MIME</span><code>{{ selectedFile.metadata?.['File-Mime'] || '-' }}</code></div>
              <div class="detail-line"><span>大小</span><code>{{ formatRemoteSize(selectedFile.metadata?.['File-Size']) }}</code></div>
              <div class="detail-line"><span>时间</span><code>{{ formatTimestamp(selectedFile.metadata?.TimeStamp) }}</code></div>
              <div class="inline-row">
                <button class="btn btn--sm" @click="toggleSelectFile(selectedFile.name)">{{ selectedPaths.includes(selectedFile.name) ? '移出批量选择' : '加入批量选择' }}</button>
                <button class="btn btn--sm" @click="copySelectedPath">复制路径</button>
                <button class="btn btn--sm" @click="openRemoteFile(selectedFile)">浏览器打开</button>
              </div>
            </div>

            <div class="detail-box">
              <div class="inline-row">
                <button class="btn btn--sm" @click="loadSelectedTags" :disabled="selectedTagLoading || !canManageSelected">{{ selectedTagLoading ? '加载中...' : '读取标签' }}</button>
              </div>
              <textarea class="input textarea" v-model.trim="selectedTagsInput" rows="4" placeholder="多个标签用逗号分隔"></textarea>
              <div class="inline-row">
                <select class="select" v-model="selectedTagAction">
                  <option value="set">set 覆盖</option>
                  <option value="add">add 追加</option>
                  <option value="remove">remove 移除</option>
                </select>
                <button class="btn btn--sm btn--primary" @click="applySelectedTags" :disabled="selectedTagLoading || !canManageSelected">保存标签</button>
              </div>
            </div>

            <div class="detail-box">
              <div class="inline-row">
                <input class="input" v-model.trim="moveTarget" placeholder="目标目录，例如 wallpaper/static/风景" />
                <button class="btn btn--sm" @click="moveSelectedFile" :disabled="remoteActionLoading || !canManageSelected || !moveTarget">移动到目标目录</button>
              </div>
              <button class="btn btn--sm btn--danger" @click="deleteRemote(selectedFile.name, false)" :disabled="remoteActionLoading">删除此文件</button>
            </div>
          </div>
          <div v-else class="empty block-body">从左侧列表选择一个远端文件后，可在这里查看并编辑详情。</div>
        </aside>
      </div>

      <div class="inline-row" v-if="remoteQuery.dir">
        <button class="btn btn--danger" @click="deleteRemote(remoteQuery.dir, true)" :disabled="remoteActionLoading">删除当前目录</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { imgbedApi, settingsApi } from '../api'
import { normalizeUploadSettings } from '../utils/uploadProfiles'

const loadingProfiles = ref(false)
const profiles = ref([])
const activeKey = ref('')
const remoteLoading = ref(false)
const remoteActionLoading = ref(false)
const batchActionLoading = ref(false)
const remoteError = ref('')
const remoteCapabilities = ref(null)
const capabilityLoading = ref(false)
const remoteIndexInfo = ref(null)
const remoteData = ref({ files: [], directories: [], totalCount: 0, returnedCount: 0, indexLastUpdated: null })
const selectedFile = ref(null)
const selectedPaths = ref([])
const selectedTagsInput = ref('')
const selectedTagAction = ref('set')
const selectedTagLoading = ref(false)
const moveTarget = ref('')
const batchTagsInput = ref('')
const batchTagAction = ref('set')
const batchMoveTarget = ref('')
const remoteQuery = ref({ dir: '', search: '', includeTags: '', excludeTags: '', recursive: false, count: 50, channel: '' })

const activeProfile = computed(() => profiles.value.find((item) => item.key === activeKey.value) || null)
const profileReady = computed(() => Boolean(activeProfile.value?.enabled && activeProfile.value?.base_url && activeProfile.value?.api_token))
const remoteFiles = computed(() => Array.isArray(remoteData.value.files) ? remoteData.value.files : [])
const remoteDirectories = computed(() => Array.isArray(remoteData.value.directories) ? remoteData.value.directories : [])
const canManageSelected = computed(() => Boolean(profileReady.value && remoteCapabilities.value?.manage))
const canManageBatch = computed(() => Boolean(canManageSelected.value && selectedPaths.value.length))
const remoteParentDir = computed(() => { const current = String(remoteQuery.value.dir || '').replace(/^\/+|\/+$/g, ''); if (!current) return ''; const parts = current.split('/').filter(Boolean); parts.pop(); return parts.join('/') })
const remoteSummary = computed(() => { const total = remoteData.value.totalCount; const returned = remoteData.value.returnedCount; return [typeof total === 'number' ? `总数 ${total}` : '', typeof returned === 'number' ? `本次返回 ${returned}` : ''].filter(Boolean).join(' / ') })

function pickPreferredProfileKey(list, currentKey = '') { const current = list.find((item) => item.key === currentKey); if (current) return current.key; return list.find((item) => item.enabled)?.key || list[0]?.key || '' }
function normalizeTagsInput(value) { return String(value || '').split(',').map((item) => item.trim()).filter(Boolean) }
function formatTimestamp(value) { if (!value) return '-'; const numeric = Number(value); const date = Number.isFinite(numeric) && numeric > 0 ? new Date(String(value).length === 13 ? numeric : numeric * 1000) : new Date(value); return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString() }
function formatRemoteSize(value) { const size = Number(value); if (!Number.isFinite(size) || size <= 0) return '-'; if (size < 1024) return `${size} B`; if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`; return `${(size / (1024 * 1024)).toFixed(2)} MB` }
function buildRemoteFileUrl(fileName) { if (!activeProfile.value?.base_url || !fileName) return ''; const encoded = String(fileName).split('/').map((part) => encodeURIComponent(part)).join('/'); return `${String(activeProfile.value.base_url).replace(/\/+$/, '')}/file/${encoded}` }
function resetRemoteState() { remoteError.value = ''; remoteCapabilities.value = null; remoteIndexInfo.value = null; remoteData.value = { files: [], directories: [], totalCount: 0, returnedCount: 0, indexLastUpdated: null }; selectedFile.value = null; selectedPaths.value = []; selectedTagsInput.value = ''; moveTarget.value = ''; batchTagsInput.value = ''; batchMoveTarget.value = '' }
function toggleSelectFile(path) { selectedPaths.value = selectedPaths.value.includes(path) ? selectedPaths.value.filter((item) => item !== path) : [...new Set([...selectedPaths.value, path])] }
function toggleSelectCurrentPage(checked) { selectedPaths.value = checked ? [...new Set([...selectedPaths.value, ...remoteFiles.value.map((file) => file.name)])] : [] }
function openDirectory(directory) { remoteQuery.value.dir = directory; loadRemoteList() }
function goParentDirectory() { remoteQuery.value.dir = remoteParentDir.value; loadRemoteList() }
function openRemoteFile(file) { const url = buildRemoteFileUrl(file?.name); if (url) window.open(url, '_blank', 'noopener,noreferrer') }

async function loadSettings() {
  loadingProfiles.value = true
  try {
    const settings = normalizeUploadSettings(await settingsApi.getUploads())
    profiles.value = Array.isArray(settings.profiles) ? settings.profiles : []
    activeKey.value = pickPreferredProfileKey(profiles.value, activeKey.value)
  } catch (error) { remoteError.value = error.message } finally { loadingProfiles.value = false }
}
async function loadRemoteCapabilities() {
  if (!activeProfile.value?.key || !profileReady.value) return
  capabilityLoading.value = true
  remoteError.value = ''
  try { remoteCapabilities.value = (await imgbedApi.capabilities(activeProfile.value.key)).data || null } catch (error) { remoteCapabilities.value = null; remoteError.value = error.message } finally { capabilityLoading.value = false }
}
async function loadRemoteList() {
  if (!activeProfile.value?.key || !profileReady.value) return
  remoteLoading.value = true
  remoteError.value = ''
  try {
    const res = await imgbedApi.list(activeProfile.value.key, { dir: remoteQuery.value.dir || undefined, search: remoteQuery.value.search || undefined, includeTags: remoteQuery.value.includeTags || undefined, excludeTags: remoteQuery.value.excludeTags || undefined, recursive: remoteQuery.value.recursive, count: remoteQuery.value.count, channel: remoteQuery.value.channel || undefined })
    remoteData.value = { files: Array.isArray(res.data?.files) ? res.data.files : [], directories: Array.isArray(res.data?.directories) ? res.data.directories : [], totalCount: typeof res.data?.totalCount === 'number' ? res.data.totalCount : null, returnedCount: typeof res.data?.returnedCount === 'number' ? res.data.returnedCount : null, indexLastUpdated: res.data?.indexLastUpdated || null }
    if (selectedFile.value) selectedFile.value = remoteData.value.files.find((item) => item.name === selectedFile.value.name) || null
  } catch (error) { remoteError.value = error.message; remoteData.value = { files: [], directories: [], totalCount: 0, returnedCount: 0, indexLastUpdated: null } } finally { remoteLoading.value = false }
}
async function loadRemoteIndexInfo() {
  if (!activeProfile.value?.key || !profileReady.value) return
  remoteActionLoading.value = true
  remoteError.value = ''
  try { remoteIndexInfo.value = (await imgbedApi.indexInfo(activeProfile.value.key, { dir: remoteQuery.value.dir || undefined })).data || null } catch (error) { remoteError.value = error.message } finally { remoteActionLoading.value = false }
}
async function rebuildRemoteIndex() {
  if (!activeProfile.value?.key || !profileReady.value || !window.confirm('将请求图床重建索引，是否继续？')) return
  remoteActionLoading.value = true
  remoteError.value = ''
  try { await imgbedApi.rebuildIndex(activeProfile.value.key, { dir: remoteQuery.value.dir || undefined }); await loadRemoteIndexInfo() } catch (error) { remoteError.value = error.message } finally { remoteActionLoading.value = false }
}
async function deleteRemote(path, folder) {
  if (!activeProfile.value?.key || !path || !window.confirm(`确认删除远端${folder ? '目录' : '文件'} ${path}？`)) return
  remoteActionLoading.value = true
  remoteError.value = ''
  try { await imgbedApi.deletePath(activeProfile.value.key, { path, folder }); selectedPaths.value = selectedPaths.value.filter((item) => item !== path); if (selectedFile.value?.name === path) selectedFile.value = null; await loadRemoteList() } catch (error) { remoteError.value = error.message } finally { remoteActionLoading.value = false }
}
async function deleteSelectedFiles() {
  if (!activeProfile.value?.key || !selectedPaths.value.length || !window.confirm(`确认删除已选中的 ${selectedPaths.value.length} 个远端文件？`)) return
  batchActionLoading.value = true
  remoteError.value = ''
  try { for (const path of selectedPaths.value) await imgbedApi.deletePath(activeProfile.value.key, { path, folder: false }); selectedPaths.value = []; selectedFile.value = null; await loadRemoteList() } catch (error) { remoteError.value = error.message } finally { batchActionLoading.value = false }
}
async function selectFile(file) { selectedFile.value = file; selectedTagsInput.value = ''; moveTarget.value = file?.name?.includes('/') ? file.name.split('/').slice(0, -1).join('/') : ''; if (remoteCapabilities.value?.manage) await loadSelectedTags() }
async function loadSelectedTags() {
  if (!activeProfile.value?.key || !selectedFile.value?.name || !remoteCapabilities.value?.manage) return
  selectedTagLoading.value = true
  remoteError.value = ''
  try { const res = await imgbedApi.getTags(activeProfile.value.key, { path: selectedFile.value.name }); selectedTagsInput.value = (Array.isArray(res.data?.tags) ? res.data.tags : []).join(', ') } catch (error) { remoteError.value = error.message } finally { selectedTagLoading.value = false }
}
async function applySelectedTags() {
  if (!activeProfile.value?.key || !selectedFile.value?.name || !remoteCapabilities.value?.manage) return
  selectedTagLoading.value = true
  remoteError.value = ''
  try { await imgbedApi.setTags(activeProfile.value.key, { path: selectedFile.value.name, tags: normalizeTagsInput(selectedTagsInput.value), action: selectedTagAction.value }); await loadSelectedTags() } catch (error) { remoteError.value = error.message } finally { selectedTagLoading.value = false }
}
async function applyBatchTags() {
  if (!activeProfile.value?.key || !selectedPaths.value.length || !remoteCapabilities.value?.manage) return
  batchActionLoading.value = true
  remoteError.value = ''
  try { await imgbedApi.batchTags(activeProfile.value.key, { paths: selectedPaths.value, tags: normalizeTagsInput(batchTagsInput.value), action: batchTagAction.value }); if (selectedFile.value && selectedPaths.value.includes(selectedFile.value.name)) await loadSelectedTags() } catch (error) { remoteError.value = error.message } finally { batchActionLoading.value = false }
}
async function moveSelectedFile() {
  if (!activeProfile.value?.key || !selectedFile.value?.name || !remoteCapabilities.value?.manage || !moveTarget.value) return
  remoteActionLoading.value = true
  remoteError.value = ''
  try { await imgbedApi.movePath(activeProfile.value.key, { path: selectedFile.value.name, dist: moveTarget.value, folder: false }); selectedFile.value = null; await loadRemoteList() } catch (error) { remoteError.value = error.message } finally { remoteActionLoading.value = false }
}
async function moveSelectedFiles() {
  if (!activeProfile.value?.key || !selectedPaths.value.length || !remoteCapabilities.value?.manage || !batchMoveTarget.value) return
  batchActionLoading.value = true
  remoteError.value = ''
  try { for (const path of selectedPaths.value) await imgbedApi.movePath(activeProfile.value.key, { path, dist: batchMoveTarget.value, folder: false }); selectedPaths.value = []; selectedFile.value = null; await loadRemoteList() } catch (error) { remoteError.value = error.message } finally { batchActionLoading.value = false }
}
async function copySelectedPath() { if (selectedFile.value?.name) await navigator.clipboard.writeText(selectedFile.value.name) }

watch(activeKey, async () => { resetRemoteState(); if (activeProfile.value?.key && profileReady.value) { await loadRemoteCapabilities(); await loadRemoteList() } })
onMounted(async () => { await loadSettings(); if (activeProfile.value?.key && profileReady.value) { await loadRemoteCapabilities(); await loadRemoteList() } })
</script>

<style scoped>
.page-subtitle,.hint,.meta-row,.mono,.empty{font-size:12px;color:var(--text-3)} .head-actions,.inline-row,.chip-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.top-grid,.main-grid,.field-grid{display:grid;gap:16px} .top-grid{grid-template-columns:1.1fr 1.9fr} .main-grid{grid-template-columns:1.7fr 1fr;margin-top:16px} .field-grid{grid-template-columns:1fr 1fr;gap:12px}
.block{border:1px solid var(--border)} .block-body{display:flex;flex-direction:column;gap:14px;padding:16px} .form-row{display:flex;flex-direction:column;gap:8px;color:var(--text-2);font-size:12px}
.error{color:var(--red);font-size:12px} .directory-chip{border:1px solid var(--border);background:transparent;color:var(--text-2);border-radius:999px;padding:4px 10px;cursor:pointer;font-size:12px}
.directory-chip:hover{border-color:var(--accent);color:var(--accent)} .batch-box,.detail-box{display:flex;flex-direction:column;gap:10px;padding:12px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg-base)}
.remote-table-wrap{overflow-x:auto} .remote-table{width:100%;border-collapse:collapse;font-size:12px} .remote-table th,.remote-table td{padding:10px 8px;border-bottom:1px solid var(--border);text-align:left}
.remote-table th{color:var(--text-3);font-weight:500} .remote-name{min-width:260px;word-break:break-all} .remote-table__actions{width:200px} .row-active{background:var(--accent-glow)}
.detail-panel .block-body{min-height:620px} .detail-line{display:grid;grid-template-columns:64px 1fr;gap:10px;align-items:start;font-size:12px;color:var(--text-2)} .detail-line code{word-break:break-all;color:var(--text-1)}
.textarea{resize:vertical;min-height:88px}
@media (max-width:1180px){.top-grid,.main-grid{grid-template-columns:1fr}}
@media (max-width:760px){.field-grid{grid-template-columns:1fr}.inline-row{flex-direction:column;align-items:stretch}}
</style>
