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
  delete: (id, deleteFile = true) =>
    http.delete(`/gallery/${id}`, { params: { delete_file: deleteFile } }),
  batchDelete: (data) => http.delete('/gallery/batch', { data }),
  scanDuplicates: () => http.post('/gallery/scan-duplicates'),
  cleanDuplicates: (dryRun = false) =>
    http.post('/gallery/clean-duplicates', null, { params: { dry_run: dryRun } }),
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
}

export const healthCheck = () => http.get('/health')
