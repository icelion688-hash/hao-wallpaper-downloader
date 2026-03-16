<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-title">账号管理 <small>{{ filteredAccounts.length }} / {{ accounts.length }}</small></h1>
        <p class="page-subtitle">集中管理账号类型、Cookie、登录态和原图权限。</p>
      </div>
      <div class="header-actions">
        <button class="btn" @click="checkAll" :disabled="checking">
          {{ checking ? '批量检测中...' : '批量检测登录态' }}
        </button>
        <button class="btn btn--primary" @click="openAdd">+ 添加账号</button>
      </div>
    </div>

    <div v-if="toast" class="toast" :class="`toast--${toast.type}`">{{ toast.msg }}</div>

    <div class="page-body">
      <div class="pool-stats" v-if="pool">
        <div class="stat-box"><div class="stat-num">{{ pool.vip_available }}/{{ pool.vip_total }}</div><div class="stat-lbl">VIP 可用</div></div>
        <div class="stat-box"><div class="stat-num">{{ pool.free_available }}/{{ pool.free_total }}</div><div class="stat-lbl">免费可用</div></div>
        <div class="stat-box"><div class="stat-num">{{ pool.free_quota_remaining }}</div><div class="stat-lbl">免费剩余配额</div></div>
        <div class="stat-box" :class="{ 'stat-box--warn': pool.banned_count > 0 }"><div class="stat-num">{{ pool.banned_count }}</div><div class="stat-lbl">已封禁</div></div>
      </div>

      <div class="card" style="margin-top:20px">
        <div class="toolbar">
          <input v-model="keyword" class="input toolbar-search" placeholder="搜索备注名、验证结果或状态" />
          <div class="toolbar-filters">
            <button class="chip" :class="{ 'chip--active': filterMode === 'all' }" @click="filterMode = 'all'">全部</button>
            <button class="chip" :class="{ 'chip--active': filterMode === 'issue' }" @click="filterMode = 'issue'">仅异常</button>
            <button class="chip" :class="{ 'chip--active': filterMode === 'ok' }" @click="filterMode = 'ok'">原图正常</button>
            <button class="chip" :class="{ 'chip--active': filterMode === 'vip' }" @click="filterMode = 'vip'">仅 VIP</button>
          </div>
        </div>

        <div class="batch-toolbar">
          <div class="batch-toolbar__summary">
            <label class="select-all">
              <input type="checkbox" :checked="allFilteredSelected" :disabled="filteredAccounts.length === 0" @change="toggleSelectAllFiltered" />
              <span>选中当前筛选结果</span>
            </label>
            <span class="batch-pill">已选 {{ selectedCount }} 个账号</span>
            <span class="batch-meta">{{ selectionSummary }}</span>
          </div>
          <div class="batch-toolbar__actions">
            <button class="btn btn--sm" @click="selectIssueAccounts" :disabled="issueAccountIds.length === 0">选中异常账号</button>
            <button class="btn btn--sm" @click="clearSelection" :disabled="selectedCount === 0">清空选择</button>
            <button class="btn btn--sm btn--verify" @click="batchVerify" :disabled="selectedCount === 0 || batchVerifying">
              {{ batchVerifying ? '批量验证中...' : '批量验证原图权限' }}
            </button>
            <button class="btn btn--sm" @click="batchSetType('vip')" :disabled="selectedCount === 0 || batchUpdatingType">批量设为 VIP</button>
            <button class="btn btn--sm" @click="batchSetType('free')" :disabled="selectedCount === 0 || batchUpdatingType">批量设为免费</button>
          </div>
        </div>

        <div v-if="filteredAccounts.length === 0" class="empty-state">
          <div class="empty-icon">□</div>
          <div>{{ accounts.length === 0 ? '暂无账号，请先添加已登录 Cookie。' : '当前筛选条件下没有账号。' }}</div>
        </div>

        <table class="table" v-else>
          <thead>
            <tr>
              <th class="table-check"></th>
              <th>ID</th>
              <th>备注名</th>
              <th>类型</th>
              <th>状态</th>
              <th>今日剩余</th>
              <th>最近验证</th>
              <th>Cookie 到期</th>
              <th>最后活跃</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="account in filteredAccounts" :key="account.id" :class="{ 'row-selected': isSelected(account.id) }">
              <td class="table-check"><input type="checkbox" :checked="isSelected(account.id)" @change="toggleSelectAccount(account.id)" /></td>
              <td class="mono muted">{{ account.id }}</td>
              <td>{{ account.nickname }}</td>
              <td><span class="tag" :class="account.account_type === 'vip' ? 'tag--vip' : 'tag--free'">{{ account.account_type.toUpperCase() }}</span></td>
              <td>
                <span v-if="account.is_banned" class="tag tag--err">封禁</span>
                <span v-else-if="!account.is_active" class="tag tag--warn">登录失效</span>
                <span v-else-if="account.is_available" class="tag tag--ok">可用</span>
                <span v-else class="tag tag--grey">配额耗尽</span>
              </td>
              <td class="mono">
                <template v-if="account.account_type === 'vip'"><span class="vip-label">不限</span></template>
                <template v-else>
                  {{ getRemainingQuota(account) }}/{{ account.daily_limit }}
                  <span class="quota-bar"><span class="quota-fill" :style="{ width: getRemainingQuotaPercent(account) + '%' }"></span></span>
                  <span class="quota-meta">已用 {{ account.daily_used }}</span>
                </template>
              </td>
              <td>
                <div class="verify-cell">
                  <span class="tag" :class="verifyTagClass(account)">{{ verifyLabel(account) }}</span>
                  <div class="verify-time">{{ formatDate(account.last_verify_at) }}</div>
                  <div class="verify-msg" :title="account.last_verify_msg || ''">{{ truncate(account.last_verify_msg || '尚未验证', 34) }}</div>
                </div>
              </td>
              <td class="mono muted">{{ formatDate(account.cookie_expires_at) }}</td>
              <td class="mono muted">{{ formatDate(account.last_active) }}</td>
              <td>
                <div class="action-row">
                  <button class="btn btn--sm" @click="openEdit(account)">编辑</button>
                  <button class="btn btn--sm" @click="openRefresh(account)">更新 Cookie</button>
                  <button class="btn btn--sm" @click="checkOne(account.id)">检测</button>
                  <button class="btn btn--sm btn--verify" :disabled="verifyingId === account.id" @click="verifyQuota(account.id)">{{ verifyingId === account.id ? '验证中...' : '验证原图权限' }}</button>
                  <button v-if="account.account_type === 'free'" class="btn btn--sm" @click="openQuotaEdit(account)">校正配额</button>
                  <button class="btn btn--sm btn--danger" @click="deleteAccount(account.id)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="modal-overlay" v-if="showAdd" @click.self="closeAdd">
      <div class="modal modal--wide">
        <div class="modal-header">添加账号</div>
        <div class="modal-body">
          <div class="cookie-guide">
            <div class="guide-title">推荐方式</div>
            <ol class="guide-steps">
              <li>在浏览器访问 <a href="https://haowallpaper.com" target="_blank">haowallpaper.com</a> 并完成登录。</li>
              <li>打开开发者工具的 <strong>Application</strong> 或 <strong>存储</strong> 面板。</li>
              <li>优先复制完整 Cookie；如果不方便，也可以只填 `userData` 和 `server_name_session`。</li>
            </ol>
            <div class="cookie-example">示例：<code>userData=%7B%22token%22...%7D; server_name_session=88c76e...</code></div>
          </div>
          <div class="form-grid">
            <div class="form-row"><label>备注名</label><input v-model="addForm.nickname" class="input" placeholder="留空时自动识别昵称" /></div>
            <div class="form-row"><label>账号类型</label><select v-model="addForm.account_type" class="select"><option value="free">免费账号</option><option value="vip">VIP 账号</option></select></div>
          </div>
          <CookieEditor title="Cookie 输入" :form="addCookieForm" :issues="cookieIssues(addCookieForm)" :preview="cookiePreview(addCookieForm)" @mode-change="switchCookieMode(addCookieForm, $event)" @input="handleCookieInput(addCookieForm, addForm)" />
        </div>
        <div class="modal-footer">
          <button class="btn" @click="closeAdd">取消</button>
          <button class="btn btn--primary" :disabled="!canSubmitCookie(addCookieForm)" @click="submitAdd">添加并验证</button>
        </div>
      </div>
    </div>

    <div class="modal-overlay" v-if="editTarget" @click.self="closeEdit">
      <div class="modal">
        <div class="modal-header">编辑账号</div>
        <div class="modal-body">
          <div class="form-grid">
            <div class="form-row"><label>备注名</label><input v-model="editForm.nickname" class="input" /></div>
            <div class="form-row"><label>账号类型</label><select v-model="editForm.account_type" class="select"><option value="free">免费账号</option><option value="vip">VIP 账号</option></select></div>
          </div>
          <p class="modal-tip">切成 VIP 后本地配额会变为不限；切回免费账号时会自动恢复免费日配额上限。</p>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="closeEdit">取消</button>
          <button class="btn btn--primary" @click="submitEdit">保存修改</button>
        </div>
      </div>
    </div>

    <div class="modal-overlay" v-if="refreshTarget" @click.self="closeRefresh">
      <div class="modal modal--wide">
        <div class="modal-header">更新 Cookie - {{ refreshTarget.nickname }}</div>
        <div class="modal-body">
          <p class="modal-tip">更新后会自动重新验证登录态和原图权限，不需要再手动点一次。</p>
          <CookieEditor title="新 Cookie" :form="refreshCookieForm" :issues="cookieIssues(refreshCookieForm)" :preview="cookiePreview(refreshCookieForm)" @mode-change="switchCookieMode(refreshCookieForm, $event)" @input="handleCookieInput(refreshCookieForm)" />
        </div>
        <div class="modal-footer">
          <button class="btn" @click="closeRefresh">取消</button>
          <button class="btn btn--primary" :disabled="!canSubmitCookie(refreshCookieForm)" @click="submitRefresh">更新并验证</button>
        </div>
      </div>
    </div>

    <div class="modal-overlay" v-if="quotaTarget" @click.self="closeQuotaEdit">
      <div class="modal" style="width:360px">
        <div class="modal-header">校正配额 - {{ quotaTarget.nickname }}</div>
        <div class="modal-body">
          <p class="modal-tip">仅免费账号支持手动校正。适合站点实际下载数和本地记录暂时不一致的情况。</p>
          <div class="form-row">
            <label>今日已用次数（上限 {{ quotaTarget.daily_limit }}）</label>
            <input v-model.number="quotaEditValue" class="input" type="number" min="0" :max="quotaTarget.daily_limit" style="width:100px" />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" @click="closeQuotaEdit">取消</button>
          <button class="btn btn--primary" @click="submitQuota">确认校正</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { accountsApi } from '../api'

const CookieEditor = {
  props: { title: String, form: Object, issues: Array, preview: String },
  emits: ['mode-change', 'input'],
  template: `
    <div class="cookie-editor">
      <div class="cookie-editor__header">
        <div class="guide-title">{{ title }}</div>
        <div class="cookie-mode">
          <button type="button" class="cookie-mode__btn" :class="{ 'cookie-mode__btn--active': form.mode === 'raw' }" @click="$emit('mode-change', 'raw')">完整 Cookie</button>
          <button type="button" class="cookie-mode__btn" :class="{ 'cookie-mode__btn--active': form.mode === 'split' }" @click="$emit('mode-change', 'split')">分字段填写</button>
        </div>
      </div>
      <div v-if="form.mode === 'raw'" class="form-row">
        <label>完整 Cookie</label>
        <textarea v-model="form.raw" class="input" rows="5" placeholder="支持直接粘贴完整 Cookie 字符串" @input="$emit('input')"></textarea>
      </div>
      <div v-else class="cookie-split">
        <div class="form-row">
          <label>userData</label>
          <textarea v-model="form.userData" class="input" rows="3" placeholder="只填 userData 的值，不需要写 key=" @input="$emit('input')"></textarea>
        </div>
        <div class="form-row">
          <label>server_name_session</label>
          <input v-model="form.serverNameSession" class="input" placeholder="只填 server_name_session 的值" @input="$emit('input')" />
        </div>
      </div>
      <div class="cookie-meta">
        <span>自动识别昵称：{{ form.detectedName || '未识别' }}</span>
        <span>规范化预览：{{ preview || '未生成' }}</span>
      </div>
      <div v-if="issues.length" class="cookie-issues"><div v-for="issue in issues" :key="issue">{{ issue }}</div></div>
    </div>
  `,
}

function createCookieForm() {
  return { mode: 'raw', raw: '', userData: '', serverNameSession: '', detectedName: '' }
}

function createAddForm() {
  return { nickname: '', account_type: 'free' }
}

const accounts = ref([])
const pool = ref(null)
const toast = ref(null)
const checking = ref(false)
const verifyingId = ref(null)
const batchVerifying = ref(false)
const batchUpdatingType = ref(false)
const keyword = ref('')
const filterMode = ref('all')
const selectedIds = ref([])
const showAdd = ref(false)
const addForm = ref(createAddForm())
const addCookieForm = ref(createCookieForm())
const editTarget = ref(null)
const editForm = ref({ nickname: '', account_type: 'free' })
const refreshTarget = ref(null)
const refreshCookieForm = ref(createCookieForm())
const quotaTarget = ref(null)
const quotaEditValue = ref(0)

const filteredAccounts = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  return accounts.value
    .filter((account) => {
      const verifyText = `${account.last_verify_status || ''} ${account.last_verify_msg || ''}`.toLowerCase()
      const accountText = `${account.nickname || ''} ${account.account_type || ''}`.toLowerCase()
      const matchesKeyword = !q || accountText.includes(q) || verifyText.includes(q)
      let matchesMode = true
      if (filterMode.value === 'issue') matchesMode = !account.is_active || account.last_verify_can_original === false || account.is_banned
      else if (filterMode.value === 'ok') matchesMode = account.last_verify_can_original === true
      else if (filterMode.value === 'vip') matchesMode = account.account_type === 'vip'
      return matchesKeyword && matchesMode
    })
    .sort((a, b) => sortRank(a) - sortRank(b) || Number(a.id) - Number(b.id))
})

const selectedCount = computed(() => selectedIds.value.length)
const filteredAccountIds = computed(() => filteredAccounts.value.map((account) => account.id))
const issueAccountIds = computed(() => filteredAccounts.value.filter((account) => !account.is_active || account.last_verify_can_original === false || account.is_banned).map((account) => account.id))
const allFilteredSelected = computed(() => filteredAccountIds.value.length > 0 && filteredAccountIds.value.every((id) => selectedIds.value.includes(id)))
const selectionSummary = computed(() => {
  if (selectedCount.value === 0) return '优先选中异常账号后再批量处理。'
  const selectedAccounts = accounts.value.filter((account) => selectedIds.value.includes(account.id))
  const vipCount = selectedAccounts.filter((account) => account.account_type === 'vip').length
  const issueCount = selectedAccounts.filter((account) => !account.is_active || account.last_verify_can_original === false).length
  return `其中 VIP ${vipCount} 个，异常 ${issueCount} 个`
})

function sortRank(account) {
  if (account.is_banned) return 0
  if (!account.is_active) return 1
  if (account.last_verify_can_original === false) return 2
  if (!account.last_verify_status) return 3
  if (account.last_verify_can_original === true) return 5
  return 4
}

function showToast(type, msg, duration = 4000) {
  toast.value = { type, msg }
  setTimeout(() => {
    if (toast.value?.msg === msg) toast.value = null
  }, duration)
}

async function loadAccounts() {
  const res = await accountsApi.list()
  accounts.value = res.accounts
  pool.value = await accountsApi.poolStatus()
  const validIds = new Set(accounts.value.map((account) => account.id))
  selectedIds.value = selectedIds.value.filter((id) => validIds.has(id))
}

function parseCookieParts(input) {
  const source = String(input || '')
  return {
    userData: source.match(/(?:^|[;,]\s*)userData=([^;,]+)/)?.[1] || '',
    serverNameSession: source.match(/(?:^|[;,]\s*)server_name_session=([^;,]+)/)?.[1] || '',
  }
}

function detectNickname(encodedUserData) {
  if (!encodedUserData) return ''
  try {
    return String(JSON.parse(decodeURIComponent(encodedUserData)).userName || '').trim()
  } catch {
    return ''
  }
}

function parseUserData(encodedUserData) {
  if (!encodedUserData) return null
  try {
    return JSON.parse(decodeURIComponent(encodedUserData))
  } catch {
    return null
  }
}

function buildCookie(form) {
  if (form.mode === 'raw') return String(form.raw || '').trim()
  const parts = []
  if (form.userData?.trim()) parts.push(`userData=${form.userData.trim()}`)
  if (form.serverNameSession?.trim()) parts.push(`server_name_session=${form.serverNameSession.trim()}`)
  return parts.join('; ')
}

function cookiePreview(form) {
  const raw = buildCookie(form)
  return raw.length > 96 ? `${raw.slice(0, 96)}...` : raw
}

function cookieIssues(form) {
  const raw = buildCookie(form)
  const issues = []
  const parts = parseCookieParts(raw)
  if (!raw) issues.push('Cookie 不能为空。')
  if (!parts.userData) issues.push('缺少 userData。')
  if (!parts.serverNameSession) issues.push('缺少 server_name_session。')
  if (parts.userData) {
    const userData = parseUserData(parts.userData)
    if (!userData) issues.push('userData 不是合法的 URL 编码 JSON。')
    else if (!userData.token) issues.push('userData 中缺少 token。')
  }
  return issues
}

function canSubmitCookie(form) {
  return cookieIssues(form).length === 0
}

function handleCookieInput(form, profileForm = null) {
  if (form.mode === 'raw') {
    const parts = parseCookieParts(buildCookie(form))
    form.userData = parts.userData
    form.serverNameSession = parts.serverNameSession
  }
  form.detectedName = detectNickname(form.userData)
  if (profileForm && !profileForm.nickname?.trim() && form.detectedName) profileForm.nickname = form.detectedName
}

function switchCookieMode(form, nextMode) {
  if (form.mode === nextMode) return
  const raw = buildCookie(form)
  if (nextMode === 'split') {
    const parts = parseCookieParts(raw)
    form.userData = parts.userData
    form.serverNameSession = parts.serverNameSession
  } else {
    form.raw = raw
  }
  form.mode = nextMode
}

function resetAddState() {
  addForm.value = createAddForm()
  addCookieForm.value = createCookieForm()
}

function openAdd() {
  resetAddState()
  showAdd.value = true
}

function closeAdd() {
  showAdd.value = false
  resetAddState()
}

function openEdit(account) {
  editTarget.value = account
  editForm.value = { nickname: account.nickname, account_type: account.account_type }
}

function closeEdit() {
  editTarget.value = null
  editForm.value = { nickname: '', account_type: 'free' }
}

function openRefresh(account) {
  refreshTarget.value = account
  refreshCookieForm.value = createCookieForm()
}

function closeRefresh() {
  refreshTarget.value = null
  refreshCookieForm.value = createCookieForm()
}

function openQuotaEdit(account) {
  quotaTarget.value = account
  quotaEditValue.value = account.daily_used
}

function closeQuotaEdit() {
  quotaTarget.value = null
  quotaEditValue.value = 0
}

function isSelected(id) {
  return selectedIds.value.includes(id)
}

function toggleSelectAccount(id) {
  selectedIds.value = isSelected(id) ? selectedIds.value.filter((item) => item !== id) : [...selectedIds.value, id]
}

function toggleSelectAllFiltered() {
  if (allFilteredSelected.value) {
    const filteredSet = new Set(filteredAccountIds.value)
    selectedIds.value = selectedIds.value.filter((id) => !filteredSet.has(id))
    return
  }
  selectedIds.value = Array.from(new Set([...selectedIds.value, ...filteredAccountIds.value]))
}

function clearSelection() {
  selectedIds.value = []
}

function selectIssueAccounts() {
  selectedIds.value = Array.from(new Set([...selectedIds.value, ...issueAccountIds.value]))
}

function verifyLabel(account) {
  const status = account.last_verify_status
  if (!status) return '未验证'
  if (status === 'original_ok') return '原图正常'
  if (status === 'login_invalid') return '登录失效'
  if (status === 'quota_exhausted') return '免费配额耗尽'
  if (status === 'vip_original_denied') return 'VIP 权限异常'
  if (status === 'login_valid') return '登录正常'
  return '状态待确认'
}

function verifyTagClass(account) {
  const status = account.last_verify_status
  if (status === 'original_ok' || status === 'login_valid') return 'tag--ok'
  if (status === 'login_invalid' || status === 'vip_original_denied') return 'tag--err'
  if (status === 'quota_exhausted' || status === 'verify_unknown') return 'tag--warn'
  return 'tag--grey'
}

function truncate(value, max) {
  if (!value) return ''
  return value.length > max ? `${value.slice(0, max)}...` : value
}

async function verifyQuota(id, silent = false) {
  verifyingId.value = id
  try {
    const res = await accountsApi.verifyQuota(id)
    if (!silent) {
      if (res.auth_valid === false) showToast('warn', `账号 #${id} 登录失效，${res.msg}`)
      else if (res.can_download_original === true) showToast('ok', `账号 #${id} 原图权限正常，${res.msg}`)
      else if (res.can_download_original === false) showToast('warn', `账号 #${id} 当前无法下载原图，${res.msg}`)
      else showToast('info', `账号 #${id} 验证未完成：${res.msg}`)
    }
    await loadAccounts()
    return res
  } catch (error) {
    if (!silent) showToast('err', `账号 #${id} 验证失败，${error.message}`)
    throw error
  } finally {
    verifyingId.value = null
  }
}

async function batchVerify() {
  if (selectedCount.value === 0) return showToast('warn', '请先选中至少一个账号。')
  batchVerifying.value = true
  try {
    const res = await accountsApi.verifyBatch(selectedIds.value)
    await loadAccounts()
    const { auth_invalid, original_ok, original_denied, unknown } = res.summary
    showToast('ok', `批量验证完成：原图正常 ${original_ok}，原图受限 ${original_denied}，登录失效 ${auth_invalid}，待确认 ${unknown}`)
  } catch (error) {
    showToast('err', `批量验证失败，${error.message}`)
  } finally {
    batchVerifying.value = false
  }
}

async function batchSetType(accountType) {
  if (selectedCount.value === 0) return showToast('warn', '请先选中至少一个账号。')
  const typeLabel = accountType === 'vip' ? 'VIP' : '免费'
  if (!confirm(`确认将已选 ${selectedCount.value} 个账号批量改为${typeLabel}账号吗？`)) return
  batchUpdatingType.value = true
  try {
    const affectedCount = selectedCount.value
    await accountsApi.batchUpdateType(selectedIds.value, accountType)
    await loadAccounts()
    showToast('ok', `已将 ${affectedCount} 个账号批量改为${typeLabel}账号。`)
  } catch (error) {
    showToast('err', `批量修改失败，${error.message}`)
  } finally {
    batchUpdatingType.value = false
  }
}

async function submitAdd() {
  const res = await accountsApi.add({
    nickname: addForm.value.nickname.trim() || addCookieForm.value.detectedName || '未命名账号',
    account_type: addForm.value.account_type,
    cookie: buildCookie(addCookieForm.value),
  })
  closeAdd()
  await loadAccounts()
  const verifyRes = await verifyQuota(res.account.id, true).catch(() => null)
  await loadAccounts()
  if (verifyRes?.can_download_original === true) showToast('ok', `账号 #${res.account.id} 已添加，原图权限正常。`)
  else if (verifyRes?.auth_valid === false) showToast('warn', `账号 #${res.account.id} 已添加，但登录态已失效。`)
  else if (verifyRes?.can_download_original === false) showToast('warn', `账号 #${res.account.id} 已添加，但当前不能下载原图。`)
  else showToast('ok', `账号 #${res.account.id} 已添加。`)
}

async function submitEdit() {
  if (!editTarget.value) return
  const nickname = editForm.value.nickname.trim()
  if (!nickname) return showToast('warn', '备注名不能为空。')
  await accountsApi.update(editTarget.value.id, { nickname, account_type: editForm.value.account_type })
  const accountId = editTarget.value.id
  closeEdit()
  await loadAccounts()
  await verifyQuota(accountId, true).catch(() => null)
  await loadAccounts()
  showToast('ok', '账号信息已更新。')
}

async function submitRefresh() {
  if (!refreshTarget.value) return
  const accountId = refreshTarget.value.id
  await accountsApi.refreshCookie(accountId, buildCookie(refreshCookieForm.value))
  closeRefresh()
  await loadAccounts()
  const verifyRes = await verifyQuota(accountId, true).catch(() => null)
  await loadAccounts()
  if (verifyRes?.can_download_original === true) showToast('ok', `账号 #${accountId} Cookie 已更新，原图权限正常。`)
  else if (verifyRes?.auth_valid === false) showToast('warn', `账号 #${accountId} Cookie 已更新，但登录态仍无效。`)
  else if (verifyRes?.can_download_original === false) showToast('warn', `账号 #${accountId} Cookie 已更新，但当前不能下载原图。`)
  else showToast('ok', `账号 #${accountId} Cookie 已更新。`)
}

async function deleteAccount(id) {
  if (!confirm('确认删除此账号吗？')) return
  await accountsApi.delete(id)
  await loadAccounts()
  showToast('ok', `账号 #${id} 已删除。`)
}

async function checkOne(id) {
  const res = await accountsApi.checkOne(id)
  await loadAccounts()
  if (res.valid) showToast('ok', `账号 #${id} 登录态有效。`)
  else showToast('warn', `账号 #${id} 登录态已失效。`)
  if (res.synced) showToast('info', `账号 #${id} 已同步今日原图计数：${res.today_db_count}`)
}

async function checkAll() {
  checking.value = true
  try {
    await accountsApi.checkAll()
    await loadAccounts()
    showToast('ok', '批量检测完成。')
  } finally {
    checking.value = false
  }
}

async function submitQuota() {
  if (!quotaTarget.value || quotaEditValue.value < 0) return
  await accountsApi.updateDailyUsed(quotaTarget.value.id, quotaEditValue.value)
  closeQuotaEdit()
  await loadAccounts()
  showToast('ok', '配额已校正。')
}

function getRemainingQuota(account) {
  return Math.max(0, Number(account.remaining_quota ?? account.daily_limit - account.daily_used) || 0)
}

function getRemainingQuotaPercent(account) {
  if (!account.daily_limit) return 0
  return Math.min(100, Math.max(0, (getRemainingQuota(account) / account.daily_limit) * 100))
}

function formatDate(value) {
  if (!value) return '--'
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

onMounted(loadAccounts)
</script>

<style scoped>
.page-subtitle,.stat-lbl,.muted,.quota-meta,.verify-time,.batch-meta,.cookie-example,.cookie-meta,.modal-tip{color:var(--text-3)}
.header-actions,.toolbar-filters,.action-row,.modal-footer,.batch-toolbar__actions{display:flex;gap:8px;flex-wrap:wrap}
.pool-stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.stat-box,.cookie-editor,.cookie-guide,.batch-toolbar{border:1px solid var(--border);border-radius:var(--radius);background:var(--bg-card)}
.stat-box{padding:16px 20px}
.stat-box--warn{border-color:var(--red)}
.stat-num{font-size:28px;font-weight:700;font-family:var(--font-ui);color:var(--accent)}
.stat-box--warn .stat-num{color:var(--red)}
.stat-lbl{font-size:11px;margin-top:4px;text-transform:uppercase;letter-spacing:.04em}
.toolbar{display:flex;justify-content:space-between;gap:12px;margin-bottom:12px}
.toolbar-search{max-width:320px}
.batch-toolbar{display:flex;justify-content:space-between;align-items:center;padding:12px 14px;margin-bottom:16px;background:linear-gradient(135deg,rgba(255,255,255,.02),rgba(0,173,181,.08))}
.batch-toolbar__summary,.select-all{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.batch-pill{display:inline-flex;align-items:center;border-radius:999px;padding:6px 10px;font-size:12px;background:rgba(0,173,181,.12);color:var(--accent)}
.chip{border:1px solid var(--border);background:var(--bg-card);color:var(--text-2);border-radius:999px;padding:8px 12px;font-size:12px;cursor:pointer}
.chip--active{border-color:var(--accent);color:var(--accent)}
.table-check{text-align:center;width:42px}
.row-selected{background:rgba(0,173,181,.06)}
.mono,.cookie-example code{font-family:var(--font-ui)}
.vip-label{color:var(--orange)}
.quota-bar{display:inline-block;position:relative;width:40px;height:4px;background:var(--bg-base);border-radius:2px;margin-left:6px;vertical-align:middle;overflow:hidden}
.quota-fill{position:absolute;inset:0 auto 0 0;background:var(--accent);border-radius:2px}
.verify-cell{min-width:180px}
.verify-msg{font-size:12px;color:var(--text-2);margin-top:2px;line-height:1.4}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:100}
.modal{width:540px;max-width:92vw;border:1px solid var(--border-hi);border-radius:var(--radius);background:var(--bg-panel)}
.modal--wide{width:720px}
.modal-header{padding:16px 20px;border-bottom:1px solid var(--border);font-weight:600}
.modal-body{padding:20px}
.modal-footer{padding:14px 20px;border-top:1px solid var(--border);justify-content:flex-end}
.form-grid,.cookie-split{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.cookie-guide{padding:14px 16px;margin-bottom:16px;background:var(--bg-base);font-size:12px}
.guide-title{font-weight:600;color:var(--text-1);margin-bottom:10px}
.guide-steps{margin:0 0 12px;padding-left:18px;color:var(--text-2);line-height:1.8}
.guide-steps a{color:var(--accent)}
.cookie-example{font-size:11px;line-height:1.6}
.cookie-example code{background:var(--bg-card);padding:2px 6px;border-radius:3px;word-break:break-all}
.cookie-editor{padding:14px 16px;background:var(--bg-base)}
.cookie-editor__header{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}
.cookie-mode{display:inline-flex;gap:4px;padding:4px;border-radius:999px;background:var(--bg-card);border:1px solid var(--border)}
.cookie-mode__btn{border:0;background:transparent;color:var(--text-3);padding:6px 12px;border-radius:999px;cursor:pointer;font-size:12px}
.cookie-mode__btn--active,.btn--verify:hover:not(:disabled){background:var(--accent);color:#fff}
.cookie-issues{margin-top:12px;padding:10px 12px;border-radius:8px;border:1px solid rgba(255,153,0,.3);background:rgba(255,153,0,.08);color:var(--orange);font-size:12px;line-height:1.7}
.btn--verify{background:var(--bg-card);border-color:var(--accent);color:var(--accent)}
.btn--verify:disabled{opacity:.55;cursor:not-allowed}
.toast{position:fixed;right:24px;bottom:24px;z-index:9999;max-width:420px;padding:12px 20px;border-radius:var(--radius);font-size:13px;line-height:1.5;box-shadow:0 4px 16px rgba(0,0,0,.35);border-left:4px solid transparent;background:var(--bg-panel);color:var(--text-1);animation:toast-in .2s ease}
.toast--ok{border-color:#4caf50}.toast--warn{border-color:var(--orange)}.toast--err{border-color:var(--red)}.toast--info{border-color:var(--accent)}
@keyframes toast-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
@media (max-width:960px){.pool-stats{grid-template-columns:repeat(2,1fr)}.toolbar,.form-grid,.cookie-split,.batch-toolbar,.cookie-editor__header,.batch-toolbar__summary,.batch-toolbar__actions{flex-direction:column;grid-template-columns:1fr;align-items:stretch}.toolbar-search{max-width:none}}
@media (max-width:640px){.header-actions{width:100%;justify-content:stretch}.header-actions .btn{flex:1}.pool-stats{grid-template-columns:1fr}}
</style>
