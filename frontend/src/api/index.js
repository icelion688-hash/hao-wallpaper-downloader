import axios from 'axios'

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

http.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const msg = err.response?.data?.detail || err.message || '请求失败'
    console.error('[API Error]', msg)
    return Promise.reject(new Error(msg))
  }
)

export const accountsApi = {
  list: () => http.get('/accounts'),
  add: (data) => http.post('/accounts', data),
  update: (id, data) => http.patch(`/accounts/${id}`, data),
  batchUpdateType: (account_ids, account_type) =>
    http.post('/accounts/batch-type', { account_ids, account_type }),
  refreshCookie: (id, cookie) => http.put(`/accounts/${id}/cookie`, { cookie }),
  delete: (id) => http.delete(`/accounts/${id}`),
  checkOne: (id) => http.post(`/accounts/${id}/check`),
  checkAll: () => http.post('/accounts/check-all'),
  poolStatus: () => http.get('/accounts/pool'),
  updateDailyUsed: (id, daily_used) => http.put(`/accounts/${id}/daily_used`, { daily_used }),
  verifyQuota: (id) => http.post(`/accounts/${id}/verify-quota`),
  verifyBatch: (account_ids) => http.post('/accounts/verify-batch', { account_ids }),
}

export const tasksApi = {
  list: () => http.get('/tasks'),
  create: (data) => http.post('/tasks', data),
  get: (id) => http.get(`/tasks/${id}`),
  rename: (id, name) => http.patch(`/tasks/${id}`, { name }),
  start: (id) => http.post(`/tasks/${id}/start`),
  pause: (id) => http.post(`/tasks/${id}/pause`),
  cancel: (id) => http.post(`/tasks/${id}/cancel`),
  delete: (id) => http.delete(`/tasks/${id}`),
  streamLogs: (id) => new EventSource(`/api/tasks/${id}/logs`),
}

export const galleryApi = {
  list: (params) => http.get('/gallery', { params }),
  categories: () => http.get('/gallery/categories'),
  categoriesByType: () => http.get('/gallery/categories-by-type'),
  colorThemes: () => http.get('/gallery/color-themes'),
  wallpaperMeta: () => http.get('/gallery/wallpaper-meta'),
  uploadProfiles: () => http.get('/gallery/upload-profiles'),
  batchUpload: (data) => http.post('/gallery/upload', data),
  reclassifyUpload: (id, data) => http.post(`/gallery/${id}/reclassify-upload`, data),
  batchReclassifyUpload: (data) => http.post('/gallery/reclassify-upload/batch', data),
  applyRemoteState: (data) => http.post('/gallery/apply-remote-state', data),
  delete: (id, deleteFile = true) =>
    http.delete(`/gallery/${id}`, { params: { delete_file: deleteFile } }),
  batchDelete: (data) => http.delete('/gallery/batch', { data }),
  scanDuplicates: () => http.post('/gallery/scan-duplicates'),
  cleanDuplicates: (dryRun = false) =>
    http.post('/gallery/clean-duplicates', null, { params: { dry_run: dryRun } }),
  // 远端路径匹配本地DB（用于 ImgbedManager 自动补全标签）
  matchRemote: (data) => http.post('/gallery/match-remote', data),
  reconcileRemoteRecords: (data) => http.post('/gallery/reconcile-remote-records', data),
  auditUploadConsistency: (data) => http.post('/gallery/audit-upload-consistency', data),
  // 本地存储滚动清仓
  cleanupLocal: (data) => http.post('/gallery/cleanup-local', data),
  storageStats: () => http.get('/gallery/storage-stats'),
}

export const statsApi = {
  overview: () => http.get('/stats/overview'),
  byCategory: () => http.get('/stats/by-category'),
  byDate: (days = 30) => http.get('/stats/by-date', { params: { days } }),
}

export const scheduleApi = {
  get: () => http.get('/schedule'),
  set: (data) => http.post('/schedule', data),
}

export const settingsApi = {
  getImgbed: () => http.get('/settings/imgbed'),
  setImgbed: (data) => http.put('/settings/imgbed', data),
  getUploads: () => http.get('/settings/uploads'),
  setUploads: (data) => http.put('/settings/uploads', data),
  getMediaConvert: () => http.get('/settings/media-convert'),
  setMediaConvert: (data) => http.put('/settings/media-convert', data),
  getSync: () => http.get('/settings/sync'),
  setSync: (data) => http.put('/settings/sync', data),
  getSystemInfo: () => http.get('/settings/system-info'),
}

export const imgbedApi = {
  channels: (profileKey) => http.get(`/imgbed/${profileKey}/channels`),
  capabilities: (profileKey) => http.get(`/imgbed/${profileKey}/capabilities`),
  list: (profileKey, params) => http.get(`/imgbed/${profileKey}/list`, { params }),
  indexInfo: (profileKey, params) => http.get(`/imgbed/${profileKey}/index-info`, { params }),
  rebuildIndex: (profileKey, params) => http.post(`/imgbed/${profileKey}/rebuild-index`, null, { params }),
  deletePath: (profileKey, params) => http.delete(`/imgbed/${profileKey}/delete`, { params }),
  movePath: (profileKey, data) => http.post(`/imgbed/${profileKey}/move`, data),
  getTags: (profileKey, params) => http.get(`/imgbed/${profileKey}/tags`, { params }),
  setTags: (profileKey, data) => http.post(`/imgbed/${profileKey}/tags`, data),
  batchTags: (profileKey, data) => http.post(`/imgbed/${profileKey}/tags/batch`, data),
}

export const convertApi = {
  batchConvert: (data) => http.post('/gallery/convert/batch', data),
  queueStatus: () => http.get('/gallery/convert/queue'),
  batchStatus: (batchId) => http.get(`/gallery/convert/queue/${batchId}`),
}

export const autopilotApi = {
  status: () => http.get('/autopilot/status'),
  start: (data) => http.post('/autopilot/start', data),
  stop: () => http.post('/autopilot/stop'),
  saveConfig: (data) => http.put('/autopilot/config', data),
}

export const healthCheck = () => http.get('/health')
