<template>
  <div>
    <div class="page-header">
      <h1 class="page-title">自动驾驶 <small>把下载、筛选、转换、上传收敛到一个持续运行的自动化面板</small></h1>
      <div class="header-right">
        <div class="tz-clock">
          <span class="tz-name">{{ status.current_tz_name || 'Asia/Shanghai' }}</span>
          <span class="tz-time">{{ status.current_tz_time || '--:--' }}</span>
          <span class="tz-badge" :class="status.is_active_hour ? 'tz-badge--active' : 'tz-badge--sleep'">{{ status.is_active_hour ? '活跃时段' : '休眠时段' }}</span>
        </div>
        <span class="tag" :class="statusTag.cls">{{ statusTag.text }}</span>
      </div>
    </div>

    <div class="page-body ap-layout">
      <div class="ap-left">
        <div class="card power-card">
          <button class="power-btn" :class="running ? 'power-btn--on' : 'power-btn--off'" :disabled="toggling" @click="togglePower">
            <span class="power-icon">⏻</span>
            <span class="power-label">{{ running ? '点击停止' : '一键启动' }}</span>
          </button>
          <div class="power-meta">
            <span class="power-mode" v-if="running && status.mode">当前模式：{{ status.mode === 'active' ? '活跃下载' : '非活跃下载' }}</span>
            <span class="power-hint">{{ running ? '配置会实时保存，点击可安全停止 AutoPilot。' : '启动后会按当前面板设置自动执行下载流程。' }}</span>
          </div>
        </div>

        <div class="card">
          <div class="card-header">今日统计</div>
          <div class="stat-grid">
            <div class="stat-item"><div class="stat-num">{{ status.today?.sessions ?? 0 }}</div><div class="stat-lbl">完成会话</div></div>
            <div class="stat-item"><div class="stat-num">{{ status.today?.downloaded ?? 0 }}</div><div class="stat-lbl">下载图片</div></div>
            <div class="stat-item stat-item--wide"><div class="stat-num" :class="nextSessionClass">{{ nextSessionLabel }}</div><div class="stat-lbl">下次会话</div></div>
          </div>
        </div>

        <div class="card phase-card" v-if="running">
          <div class="card-header">运行阶段</div>
          <div class="phase-body">
            <div class="phase-dot" :class="`phase-dot--${status.phase}`"></div>
            <div>
              <div class="phase-name">{{ phaseLabel }}</div>
              <div class="phase-sub" v-if="status.current_task_id">任务 <span class="mono">#{{ status.current_task_id }}</span><a class="link" href="/tasks">查看任务列表</a></div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">24 小时时段视图</div>
          <div class="hour-bar-wrap">
            <div class="hour-bar">
              <div v-for="h in 24" :key="h - 1" class="hour-cell" :class="hourCellClass(h - 1)" :title="`${String(h - 1).padStart(2, '0')}:00`"><span v-if="h - 1 === currentHour" class="hour-now">●</span></div>
            </div>
            <div class="hour-labels"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>
            <div class="hour-legend">
              <span class="legend-dot legend-dot--active"></span>活跃
              <span class="legend-dot legend-dot--inactive" v-if="cfg.inactive_enabled"></span><span v-if="cfg.inactive_enabled">非活跃下载</span>
              <span class="legend-dot legend-dot--sleep"></span>休眠
              <span class="legend-dot legend-dot--now"></span>当前
            </div>
          </div>
        </div>
      </div>

      <div class="ap-right">
        <div class="card">
          <div class="card-header">运行配置 <span class="cfg-hint">{{ running ? '运行中修改将在下一轮会话生效' : '启动时将使用以下完整自动化配置' }}</span></div>

          <div class="cfg-section">
            <div class="cfg-section-title">时区与活跃时段</div>
            <div class="cfg-grid-3">
              <div class="form-row"><label>时区</label><select class="select" v-model="cfg.timezone" @change="onCfgChange"><option v-for="tz in supportedTimezones" :key="tz" :value="tz">{{ tz }}</option></select></div>
              <div class="form-row"><label>开始时间</label><select class="select" v-model.number="cfg.active_start" @change="onCfgChange"><option v-for="h in 24" :key="`start-${h - 1}`" :value="h - 1">{{ String(h - 1).padStart(2, '0') }}:00</option></select></div>
              <div class="form-row"><label>结束时间</label><select class="select" v-model.number="cfg.active_end" @change="onCfgChange"><option v-for="h in 24" :key="`end-${h - 1}`" :value="h - 1">{{ String(h - 1).padStart(2, '0') }}:00</option></select></div>
            </div>
            <div class="time-desc">活跃时段：{{ String(cfg.active_start).padStart(2, '0') }}:00 - {{ String(cfg.active_end).padStart(2, '0') }}:00 <span v-if="cfg.active_start > cfg.active_end" class="tag tag--warn">跨天</span></div>
          </div>

          <div class="cfg-divider"></div>
          <div class="cfg-section">
            <div class="cfg-section-title mode-title mode-title--active">活跃时段下载模式</div>
            <div class="cfg-grid">
              <div class="form-row"><label>单次最少下载</label><input class="input" type="number" min="1" max="200" v-model.number="cfg.active_session_min" @change="onCfgChange" /></div>
              <div class="form-row"><label>单次最多下载</label><input class="input" type="number" min="1" max="200" v-model.number="cfg.active_session_max" @change="onCfgChange" /></div>
              <div class="form-row"><label>最短间隔（分钟）</label><input class="input" type="number" min="1" v-model.number="activeIntervalMinMin" @change="onActiveIntervalChange" /></div>
              <div class="form-row"><label>最长间隔（分钟）</label><input class="input" type="number" min="1" v-model.number="activeIntervalMaxMin" @change="onActiveIntervalChange" /></div>
            </div>
            <div class="mode-hint">每轮下载 {{ cfg.active_session_min }} - {{ cfg.active_session_max }} 张，间隔 {{ activeIntervalMinMin }} - {{ activeIntervalMaxMin }} 分钟。</div>
          </div>

          <div class="cfg-divider"></div>

          <div class="cfg-section">
            <div class="mode-title-row"><div class="cfg-section-title mode-title mode-title--inactive">非活跃时段下载模式</div><label class="toggle"><input type="checkbox" v-model="cfg.inactive_enabled" @change="onCfgChange" /><span class="toggle-track"></span></label><span class="toggle-label">{{ cfg.inactive_enabled ? '开启轻量下载' : '完全休眠' }}</span></div>
            <template v-if="cfg.inactive_enabled">
              <div class="cfg-grid section-top-gap">
                <div class="form-row"><label>单次最少下载</label><input class="input" type="number" min="1" max="100" v-model.number="cfg.inactive_session_min" @change="onCfgChange" /></div>
                <div class="form-row"><label>单次最多下载</label><input class="input" type="number" min="1" max="100" v-model.number="cfg.inactive_session_max" @change="onCfgChange" /></div>
                <div class="form-row"><label>最短间隔（分钟）</label><input class="input" type="number" min="1" v-model.number="inactiveIntervalMinMin" @change="onInactiveIntervalChange" /></div>
                <div class="form-row"><label>最长间隔（分钟）</label><input class="input" type="number" min="1" v-model.number="inactiveIntervalMaxMin" @change="onInactiveIntervalChange" /></div>
              </div>
              <div class="mode-hint mode-hint--inactive">深夜策略建议更保守，避免长时间高频抓取。</div>
            </template>
          </div>

          <div class="cfg-divider"></div>

          <div class="cfg-section">
            <div class="cfg-section-title">下载参数</div>
            <div class="cfg-grid">
              <div class="form-row"><label>图片类型</label><select class="select" v-model="cfg.wallpaper_type" @change="onCfgChange"><option value="static">静态图</option><option value="dynamic">动态图</option><option value="all">全部</option></select></div>
              <div class="form-row"><label>屏幕方向</label><select class="select" v-model="cfg.screen_orientation" @change="onCfgChange"><option value="all">全部</option><option value="landscape">横屏</option><option value="portrait">竖屏</option></select></div>
              <div class="form-row"><label>排序方式</label><select class="select" v-model="cfg.sort_by" @change="onCfgChange"><option value="yesterday_hot">昨日热门</option><option value="3days_hot">近三天热门</option><option value="7days_hot">近七天热门</option><option value="latest">最新上传</option><option value="most_views">最多浏览</option></select></div>
              <div class="form-row"><label>最低热度</label><input class="input" type="number" min="0" v-model.number="cfg.min_hot_score" @change="onCfgChange" /></div>
            </div>
            <div class="toggle-list"><label class="toggle-row"><span class="toggle-row-label">仅限 VIP 账号资源</span><label class="toggle"><input type="checkbox" v-model="cfg.vip_only" @change="onCfgChange" /><span class="toggle-track"></span></label></label></div>
          </div>

          <div class="cfg-divider"></div>

          <div class="cfg-section">
            <div class="cfg-section-title">内容筛选与质量门槛</div>
            <div class="cfg-grid">
              <div class="form-row form-row--full"><label>分类轮询策略</label><input class="input" v-model="categoriesInput" placeholder="动漫, 二次元, 风景" @change="onCategoriesChange" /><div class="form-help">多个分类用逗号分隔。配置多个分类时，AutoPilot 会按分类轮询，减少内容单一化。</div></div>
              <div class="form-row form-row--full"><label>色系筛选</label><input class="input" v-model="colorsInput" placeholder="蓝色, 紫色, 粉色" @change="onColorsChange" /><div class="form-help">可留空，适合持续维护统一风格的图库或品牌色主题。</div></div>
              <div class="form-row form-row--full"><label>黑名单标签</label><input class="input" v-model="blacklistInput" placeholder="nsfw, blood, watermark" @change="onBlacklistChange" /><div class="form-help">命中标题或标签即跳过，适合长期自动化运行时做内容风险兜底。</div></div>
              <div class="form-row"><label>最小宽度</label><input class="input" type="number" min="0" v-model.number="cfg.min_width" placeholder="不限" @change="onCfgChange" /></div>
              <div class="form-row"><label>最小高度</label><input class="input" type="number" min="0" v-model.number="cfg.min_height" placeholder="不限" @change="onCfgChange" /></div>
            </div>
            <div class="preset-row"><span class="preset-label">分辨率预设</span><div class="preset-actions"><button class="btn btn--sm" type="button" @click="applyResolutionPreset(1920, 1080)">1080p+</button><button class="btn btn--sm" type="button" @click="applyResolutionPreset(2560, 1440)">2K+</button><button class="btn btn--sm" type="button" @click="applyResolutionPreset(3840, 2160)">4K+</button><button class="btn btn--sm" type="button" @click="clearResolutionPreset">清除限制</button></div></div>
          </div>

          <div class="cfg-divider"></div>
          <div class="cfg-section">
            <div class="cfg-section-title">自动化产物与上传策略</div>
            <div class="strategy-summary"><span class="summary-pill">下载落地：原始文件</span><span class="summary-pill" :class="cfg.use_imgbed_upload ? 'summary-pill--ok' : ''">自动上传：{{ cfg.use_imgbed_upload ? '开启' : '关闭' }}</span><span class="summary-pill" :class="mediaSettings.auto_convert ? 'summary-pill--ok' : ''">自动转换：{{ mediaSettings.auto_convert ? '开启' : '关闭' }}</span><span class="summary-pill" v-if="selectedAutoUploadProfile">上传 Profile：{{ selectedAutoUploadProfile.name }}</span></div>
            <div class="strategy-note">下载阶段始终先保存原始文件。压缩、转码和上传路径都在这里集中控制，避免启动后再去多个页面调整。</div>
            <div class="toggle-list"><label class="toggle-row"><span class="toggle-row-label">下载完成后自动上传到图床</span><label class="toggle"><input type="checkbox" v-model="cfg.use_imgbed_upload" @change="onCfgChange" /><span class="toggle-track"></span></label></label></div>
            <template v-if="cfg.use_imgbed_upload">
              <div class="cfg-grid section-top-gap"><div class="form-row"><label>自动上传 Profile</label><select class="select" v-model="uploadSettings.task_profile" @change="onCfgChange"><option v-for="profile in uploadSettings.profiles" :key="profile.key" :value="profile.key">{{ profile.name }} / {{ profile.channel }}</option></select></div><div class="form-row"><label>上传策略摘要</label><div class="inline-note">{{ uploadProfileModeLabel }}</div></div></div>
              <div class="mode-row" v-if="selectedAutoUploadProfile"><button class="btn btn--sm" type="button" :class="{ 'btn--primary': isLosslessProfile(selectedAutoUploadProfile) }" @click="applyAutoUploadLossless">原图直传</button><button class="btn btn--sm" type="button" :class="{ 'btn--primary': !isLosslessProfile(selectedAutoUploadProfile) }" @click="applyAutoUploadCompressed">压缩 WebP</button><span class="mode-hint">{{ isLosslessProfile(selectedAutoUploadProfile) ? '上传时保持原始格式，不做本地压缩。' : '上传前做本地 WebP 预处理，更适合长时间自动运行。' }}</span></div>
              <div class="cfg-grid" v-if="selectedAutoUploadProfile">
                <div class="form-row"><label>服务端压缩</label><input type="checkbox" v-model="selectedAutoUploadProfile.server_compress" class="chk" @change="onCfgChange" /></div>
                <div class="form-row"><label>本地预处理</label><input type="checkbox" v-model="selectedAutoUploadProfile.image_processing.enabled" class="chk" @change="onCfgChange" /></div>
                <div class="form-row form-row--full"><label>路径模板</label><input class="input" v-model="selectedAutoUploadProfile.folder_pattern" placeholder="bg/{type}/{year}/{month}" @change="onCfgChange" /><div class="form-help">支持 {type}、{category}、{year}、{month}、{date} 等变量；留空则使用下方固定目录。</div></div>
                <div class="form-row"><label>横图目录</label><input class="input" v-model="selectedAutoUploadProfile.folder_landscape" placeholder="bg/pc" @change="onCfgChange" /></div>
                <div class="form-row"><label>竖图目录</label><input class="input" v-model="selectedAutoUploadProfile.folder_portrait" placeholder="bg/mb" @change="onCfgChange" /></div>
                <div class="form-row"><label>动态图目录</label><input class="input" v-model="selectedAutoUploadProfile.folder_dynamic" placeholder="bg/dynamic" @change="onCfgChange" /></div>
                <div class="form-row"><label>上传最小宽度</label><input class="input" type="number" min="0" :value="selectedAutoUploadProfile.upload_filter.min_width || ''" @change="selectedAutoUploadProfile.upload_filter.min_width = $event.target.value ? +$event.target.value : null; onCfgChange()" /></div>
                <div class="form-row"><label>上传最小高度</label><input class="input" type="number" min="0" :value="selectedAutoUploadProfile.upload_filter.min_height || ''" @change="selectedAutoUploadProfile.upload_filter.min_height = $event.target.value ? +$event.target.value : null; onCfgChange()" /></div>
                <div class="form-row form-row--full"><label class="toggle-row toggle-row--compact"><span class="toggle-row-label">仅上传原图（跳过预览图）</span><label class="toggle"><input type="checkbox" v-model="selectedAutoUploadProfile.upload_filter.only_original" @change="onCfgChange" /><span class="toggle-track"></span></label></label></div>
              </div>
            </template>
          </div>

          <div class="cfg-divider"></div>

          <div class="cfg-section">
            <div class="cfg-section-title">自动格式转换策略</div>
            <div class="toggle-list"><label class="toggle-row"><span class="toggle-row-label">下载完成后自动转换格式</span><label class="toggle"><input type="checkbox" v-model="mediaSettings.auto_convert" @change="onCfgChange" /><span class="toggle-track"></span></label></label></div>
            <div class="cfg-grid section-top-gap"><div class="form-row"><label>并发转换数</label><input class="input" type="number" min="1" max="4" v-model.number="mediaSettings.max_concurrent" @change="onCfgChange" /></div><div class="form-row"><label>机器建议</label><div class="inline-note" v-if="systemInfo && systemInfo.recommend">{{ systemInfo.tier }} / 建议 {{ systemInfo.recommend.max_frames }} 帧 / {{ systemInfo.recommend.max_width }}px / {{ systemInfo.recommend.fps }}fps</div></div></div>
            <div class="automation-grid">
              <div class="sub-card">
                <div class="sub-card__title">动态图转换</div>
                <div class="inline-note">已关闭动态图自动转换。AutoPilot 只保留静态图格式转换，动态图仅保存原始文件。</div>
              </div>
              <div class="sub-card"><div class="sub-card__title">静态图转换</div><label class="toggle-row toggle-row--compact"><span class="toggle-row-label">启用静态图自动转换</span><label class="toggle"><input type="checkbox" v-model="mediaSettings.image.enabled" @change="onCfgChange" /><span class="toggle-track"></span></label></label><div class="field-grid"><div class="form-row"><label>输出格式</label><select class="select" v-model="mediaSettings.image.output_format" @change="onCfgChange"><option value="webp">WebP</option><option value="jpg">JPG</option><option value="png">PNG</option></select></div><div class="form-row"><label>质量</label><input class="input" type="number" min="1" max="100" v-model.number="mediaSettings.image.quality" @change="onCfgChange" /></div><div class="form-row form-row--full"><label class="toggle-row toggle-row--compact"><span class="toggle-row-label">转换后删除原文件</span><label class="toggle"><input type="checkbox" v-model="mediaSettings.image.delete_original" @change="onCfgChange" /><span class="toggle-track"></span></label></label></div></div></div>
            </div>
          </div>

          <div class="cfg-footer"><button class="btn btn--primary btn--sm" @click="saveConfig">保存配置</button><span v-if="savedHint" class="saved-hint">已保存</span></div>
        </div>

        <div class="card"><div class="card-header">运行日志 <button class="btn btn--sm" style="margin-left:auto" @click="logs = []">清空</button></div><div class="log-body" ref="logEl"><div v-if="logs.length === 0" class="log-empty">暂无日志，启动后这里会显示会话、等待和异常信息。</div><div v-for="(line, index) in logs" :key="index" class="log-line" :class="logLineClass(line)">{{ line }}</div></div></div>
      </div>
    </div>
  </div>
</template>
<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { autopilotApi, settingsApi } from '../api'
import { applyCompressedUploadProfile, applyLosslessUploadProfile, isLosslessUploadProfile, normalizeUploadSettings } from '../utils/uploadProfiles'
const createDefaultAutoPilotConfig=()=>({timezone:'Asia/Shanghai',active_start:8,active_end:23,active_session_min:5,active_session_max:20,active_interval_min:1800,active_interval_max:7200,inactive_enabled:false,inactive_session_min:2,inactive_session_max:8,inactive_interval_min:7200,inactive_interval_max:14400,use_imgbed_upload:false,wallpaper_type:'static',sort_by:'yesterday_hot',categories:[],color_themes:[],vip_only:false,min_hot_score:0,tag_blacklist:[],min_width:null,min_height:null,screen_orientation:'all'})
const createDefaultMediaSettings=()=>({auto_convert:false,max_concurrent:1,video:{enabled:false,output_format:'webp',fps:0,max_frames:0,width:0,max_width:0,quality:100,delete_original:false,timeout_seconds:300,cpu_nice:5},image:{enabled:false,output_format:'webp',quality:100,delete_original:false,timeout_seconds:120,cpu_nice:5}})
const normalizeMediaSettings=(remote={})=>{const defaults=createDefaultMediaSettings();return{...defaults,...remote,video:{...defaults.video,...(remote.video||{})},image:{...defaults.image,...(remote.image||{})}}}
const parseCsvInput=value=>value?value.split(',').map(item=>item.trim()).filter(Boolean):[]
const cloneUploadProfiles=profiles=>(profiles||[]).map(profile=>({...profile,image_processing:{...(profile.image_processing||{})},upload_filter:{...(profile.upload_filter||{})}}))
const status=ref({}),toggling=ref(false),logs=ref([]),logEl=ref(null),savedHint=ref(false),supportedTimezones=ref(['Asia/Shanghai']),cfg=ref(createDefaultAutoPilotConfig()),uploadSettings=ref(normalizeUploadSettings()),mediaSettings=ref(createDefaultMediaSettings()),systemInfo=ref(null),categoriesInput=ref(''),colorsInput=ref(''),blacklistInput=ref(''),activeIntervalMinMin=ref(30),activeIntervalMaxMin=ref(120),inactiveIntervalMinMin=ref(120),inactiveIntervalMaxMin=ref(240),currentHour=ref(new Date().getHours())
const running=computed(()=>status.value.status==='running')
const selectedAutoUploadProfile=computed(()=>{const profiles=uploadSettings.value.profiles||[];return profiles.find(profile=>profile.key===uploadSettings.value.task_profile)||profiles[0]||null})
const uploadProfileModeLabel=computed(()=>{const profile=selectedAutoUploadProfile.value;if(!profile)return'未找到可用上传 Profile';const mode=isLosslessUploadProfile(profile)?'原图直传':'本地 WebP 预处理';const folderSummary=profile.folder_pattern?`路径模板 ${profile.folder_pattern}`:[profile.folder_landscape,profile.folder_portrait,profile.folder_dynamic].filter(Boolean).join(' / ');return[mode,profile.channel,folderSummary].filter(Boolean).join(' · ')})
const statusTag=computed(()=>!running.value?{cls:'tag--grey',text:'IDLE'}:({session:{cls:'tag--ok',text:'SESSION'},waiting:{cls:'tag--info',text:'WAITING'},sleeping:{cls:'tag--warn',text:'SLEEPING'},daily_limit:{cls:'tag--warn',text:'DAILY LIMIT'},starting:{cls:'tag--info',text:'STARTING'}}[status.value.phase]||{cls:'tag--ok',text:'RUNNING'}))
const phaseLabel=computed(()=>({session:'正在执行下载会话',waiting:'会话间等待中',sleeping:'等待活跃时段开始',daily_limit:'今日配额已用完，等待明天',starting:'初始化中...'}[status.value.phase]||'运行中'))
const nextSessionLabel=computed(()=>{if(!running.value)return'—';if(status.value.phase==='session')return'进行中';if(!status.value.next_session_at)return'即将开始';const diff=Math.max(0,Math.floor((new Date(status.value.next_session_at)-Date.now())/1000));if(diff<60)return`${diff}s`;if(diff<3600)return`${Math.floor(diff/60)}min`;return`${Math.floor(diff/3600)}h ${Math.floor((diff%3600)/60)}min`})
const nextSessionClass=computed(()=>status.value.phase==='session'?'stat-num--active':'')
let savedHintTimer=null,pollTimer=null,configLoaded=false
const syncFilterInputsFromConfig=()=>{categoriesInput.value=(cfg.value.categories||[]).join(', ');colorsInput.value=(cfg.value.color_themes||[]).join(', ');blacklistInput.value=(cfg.value.tag_blacklist||[]).join(', ')}
const applyConfig=remote=>{cfg.value={...createDefaultAutoPilotConfig(),...(remote||{})};activeIntervalMinMin.value=Math.round((cfg.value.active_interval_min??1800)/60);activeIntervalMaxMin.value=Math.round((cfg.value.active_interval_max??7200)/60);inactiveIntervalMinMin.value=Math.round((cfg.value.inactive_interval_min??7200)/60);inactiveIntervalMaxMin.value=Math.round((cfg.value.inactive_interval_max??14400)/60);syncFilterInputsFromConfig()}
const isHourActive=hour=>{const start=cfg.value.active_start,end=cfg.value.active_end;return start<=end?hour>=start&&hour<end:hour>=start||hour<end}
const isHourInactive=hour=>!isHourActive(hour)&&cfg.value.inactive_enabled
const hourCellClass=hour=>hour===currentHour.value?'hour-cell--now':isHourActive(hour)?'hour-cell--active':isHourInactive(hour)?'hour-cell--inactive':'hour-cell--sleep'
const buildPayload=()=>({...cfg.value,categories:parseCsvInput(categoriesInput.value),color_themes:parseCsvInput(colorsInput.value),tag_blacklist:parseCsvInput(blacklistInput.value),active_interval_min:activeIntervalMinMin.value*60,active_interval_max:activeIntervalMaxMin.value*60,inactive_interval_min:inactiveIntervalMinMin.value*60,inactive_interval_max:inactiveIntervalMaxMin.value*60})
const buildUploadSettingsPayload=()=>{const normalized=normalizeUploadSettings(uploadSettings.value);return{task_profile:normalized.task_profile,gallery_default_format:normalized.gallery_default_format,profiles:cloneUploadProfiles(normalized.profiles)}}
const buildMediaSettingsPayload=()=>{const normalized=normalizeMediaSettings(mediaSettings.value);return{auto_convert:!!normalized.auto_convert,max_concurrent:normalized.max_concurrent||1,video:{...normalized.video,enabled:false},image:{...normalized.image}}}
const autoConvertVideoSummary=computed(()=>{const video=mediaSettings.value.video||{};const fps=video.fps===0?'保留源帧率':`${video.fps}fps`;const width=video.max_width===0?'保留源分辨率':`最长 ${video.max_width}px`;const frames=video.max_frames===0?'保留完整时长 / 全帧':`最多 ${video.max_frames} 帧`;const quality=video.output_format==='webp'?`质量 ${video.quality}`:'GIF 时间轴输出';return`${fps} · ${width} · ${frames} · ${quality}`})
const applyAutoConvertVideoPreset=preset=>{const presets={original:{fps:0,max_frames:0,max_width:0,quality:100},balanced:{fps:30,max_frames:240,max_width:1920,quality:85},lite:{fps:15,max_frames:120,max_width:1280,quality:75}};Object.assign(mediaSettings.value.video,presets[preset]||presets.original);onCfgChange()}
const loadAutomationSettings=async()=>{const [uploadsResult,mediaResult,systemInfoResult]=await Promise.allSettled([settingsApi.getUploads(),settingsApi.getMediaConvert(),settingsApi.getSystemInfo()]);uploadSettings.value=uploadsResult.status==='fulfilled'?normalizeUploadSettings(uploadsResult.value):normalizeUploadSettings();mediaSettings.value=mediaResult.status==='fulfilled'?normalizeMediaSettings(mediaResult.value):createDefaultMediaSettings();if(systemInfoResult.status==='fulfilled')systemInfo.value=systemInfoResult.value}
const poll=async()=>{try{const data=await autopilotApi.status();status.value=data;if(data.supported_timezones?.length)supportedTimezones.value=data.supported_timezones;if(!configLoaded&&data.config){applyConfig(data.config);configLoaded=true}const remoteLogs=data.logs||[];if(remoteLogs.length<logs.value.length){logs.value=remoteLogs}else if(remoteLogs.length>logs.value.length){logs.value.push(...remoteLogs.slice(logs.value.length));nextTick(scrollLogs)}currentHour.value=data.current_tz_time?Number(data.current_tz_time.slice(0,2)):new Date().getHours()}catch{}}
const showSavedHint=()=>{savedHint.value=true;clearTimeout(savedHintTimer);savedHintTimer=setTimeout(()=>{savedHint.value=false},2000)}
const persistAutomationSettings=async({showHint=true,silent=false}={})=>{try{const [,uploadRes,mediaRes]=await Promise.all([autopilotApi.saveConfig(buildPayload()),settingsApi.setUploads(buildUploadSettingsPayload()),settingsApi.setMediaConvert(buildMediaSettingsPayload())]);if(uploadRes?.uploads)uploadSettings.value=normalizeUploadSettings(uploadRes.uploads);if(mediaRes?.media_convert)mediaSettings.value=normalizeMediaSettings(mediaRes.media_convert);if(showHint)showSavedHint()}catch(error){if(!silent)throw error}}
const onCfgChange=()=>{persistAutomationSettings({showHint:true,silent:true})}
const onCategoriesChange=()=>{cfg.value.categories=parseCsvInput(categoriesInput.value);onCfgChange()}
const onColorsChange=()=>{cfg.value.color_themes=parseCsvInput(colorsInput.value);onCfgChange()}
const onBlacklistChange=()=>{cfg.value.tag_blacklist=parseCsvInput(blacklistInput.value);onCfgChange()}
const applyResolutionPreset=(width,height)=>{cfg.value.min_width=width;cfg.value.min_height=height;onCfgChange()}
const clearResolutionPreset=()=>{cfg.value.min_width=null;cfg.value.min_height=null;onCfgChange()}
const onActiveIntervalChange=()=>{cfg.value.active_interval_min=activeIntervalMinMin.value*60;cfg.value.active_interval_max=activeIntervalMaxMin.value*60;onCfgChange()}
const onInactiveIntervalChange=()=>{cfg.value.inactive_interval_min=inactiveIntervalMinMin.value*60;cfg.value.inactive_interval_max=inactiveIntervalMaxMin.value*60;onCfgChange()}
const isLosslessProfile=profile=>isLosslessUploadProfile(profile)
const applyAutoUploadLossless=()=>{if(!selectedAutoUploadProfile.value)return;applyLosslessUploadProfile(selectedAutoUploadProfile.value);onCfgChange()}
const applyAutoUploadCompressed=()=>{if(!selectedAutoUploadProfile.value)return;applyCompressedUploadProfile(selectedAutoUploadProfile.value);onCfgChange()}
const togglePower=async()=>{toggling.value=true;try{if(running.value){await autopilotApi.stop()}else{logs.value=[];await persistAutomationSettings({showHint:false,silent:false});await autopilotApi.start(buildPayload())}await poll()}catch(error){alert('操作失败: '+(error?.message||error))}finally{toggling.value=false}}
const saveConfig=async()=>{try{await persistAutomationSettings({showHint:true,silent:false})}catch(error){alert('保存配置失败: '+(error?.message||error))}}
const scrollLogs=()=>{if(logEl.value)logEl.value.scrollTop=logEl.value.scrollHeight}
const logLineClass=line=>{if(line.includes('失败')||line.includes('异常')||line.includes('错误'))return'log-err';if(line.includes('警告')||line.includes('上限'))return'log-warn';if(line.includes('完成')||line.includes('成功'))return'log-ok';if(line.includes('[活跃]')||line.includes('会话')||line.includes('开始'))return'log-accent';if(line.includes('[非活跃]'))return'log-inactive';return''}
onMounted(async()=>{await Promise.all([poll(),loadAutomationSettings()]);pollTimer=setInterval(poll,3000)})
onUnmounted(()=>{clearInterval(pollTimer);clearTimeout(savedHintTimer)})
</script>
<style scoped>
.ap-layout{display:grid;grid-template-columns:300px 1fr;gap:20px;align-items:start}.ap-left,.ap-right{display:flex;flex-direction:column;gap:16px}.header-right{display:flex;align-items:center;gap:12px}.tz-clock{display:flex;align-items:center;gap:8px;padding:6px 12px;background:var(--bg-card);border:1px solid var(--border);border-radius:var(--radius);font-family:var(--font-ui)}.tz-name{font-size:11px;color:var(--text-3)}.tz-time{font-size:14px;color:var(--text-1);font-weight:600}.tz-badge{font-size:10px;padding:1px 6px;border-radius:4px;font-weight:500}.tz-badge--active{background:rgba(62,207,114,.15);color:var(--green)}.tz-badge--sleep{background:rgba(79,142,255,.12);color:var(--accent)}
.power-card{display:flex;flex-direction:column;align-items:center;padding:28px 20px 20px;gap:14px}.power-btn{width:96px;height:96px;border-radius:50%;border:3px solid var(--border-hi);background:var(--bg-base);cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;transition:all .25s}.power-btn--off:hover{border-color:var(--accent);background:var(--accent-glow)}.power-btn--on{border-color:var(--green);background:rgba(62,207,114,.08);animation:pulse-power 2.2s ease-in-out infinite}.power-btn:disabled{opacity:.45;cursor:not-allowed;animation:none}@keyframes pulse-power{0%,100%{box-shadow:0 0 0 0 rgba(62,207,114,.35)}50%{box-shadow:0 0 0 12px rgba(62,207,114,0)}}.power-icon{font-size:28px;color:var(--text-2);transition:color .25s}.power-btn--on .power-icon{color:var(--green)}.power-btn--off:hover .power-icon{color:var(--accent)}.power-label{font-size:11px;color:var(--text-3);font-family:var(--font-ui)}.power-meta{display:flex;flex-direction:column;align-items:center;gap:4px}.power-mode{font-size:12px;color:var(--green);font-family:var(--font-ui)}.power-hint{font-size:11px;color:var(--text-3);text-align:center;line-height:1.6}
.stat-grid{display:grid;grid-template-columns:1fr 1fr;gap:1px;background:var(--border)}.stat-item{padding:14px 16px;background:var(--bg-card);text-align:center}.stat-item--wide{grid-column:span 2}.stat-num{font-size:22px;font-family:var(--font-ui);font-weight:600}.stat-num--active{color:var(--green)}.stat-lbl{font-size:11px;color:var(--text-3);margin-top:3px}
.phase-body{display:flex;align-items:center;gap:12px;padding:14px 18px}.phase-dot{width:10px;height:10px;border-radius:50%;flex-shrink:0}.phase-dot--session{background:var(--green);box-shadow:0 0 8px var(--green);animation:blink 1.2s ease-in-out infinite}.phase-dot--waiting{background:var(--accent);box-shadow:0 0 6px var(--accent)}.phase-dot--sleeping{background:var(--orange)}.phase-dot--daily_limit{background:var(--red)}.phase-dot--starting{background:var(--text-3);animation:blink .8s ease-in-out infinite}@keyframes blink{0%,100%{opacity:1}50%{opacity:.25}}.phase-name{font-size:13px;color:var(--text-1)}.phase-sub{font-size:11px;color:var(--text-3);margin-top:4px}.mono{font-family:var(--font-ui)}.link{color:var(--accent);text-decoration:none;margin-left:8px}.link:hover{text-decoration:underline}
.hour-bar-wrap{padding:14px 18px 10px}.hour-bar{display:grid;grid-template-columns:repeat(24,1fr);gap:2px;margin-bottom:4px}.hour-cell{height:22px;border-radius:2px;position:relative;cursor:default}.hour-cell--active{background:rgba(62,207,114,.35)}.hour-cell--inactive{background:rgba(245,166,35,.25)}.hour-cell--sleep{background:var(--bg-hover)}.hour-cell--now{background:var(--accent);box-shadow:0 0 6px var(--accent)}.hour-now{position:absolute;bottom:-14px;left:50%;transform:translateX(-50%);font-size:8px;color:var(--accent)}.hour-labels{display:flex;justify-content:space-between;font-size:10px;color:var(--text-3);font-family:var(--font-ui);margin-top:16px;padding:0 2px}.hour-legend{display:flex;align-items:center;gap:8px;margin-top:10px;font-size:11px;color:var(--text-3);flex-wrap:wrap}.legend-dot{width:10px;height:10px;border-radius:2px;flex-shrink:0}.legend-dot--active{background:rgba(62,207,114,.35)}.legend-dot--inactive{background:rgba(245,166,35,.25)}.legend-dot--sleep{background:var(--bg-hover);border:1px solid var(--border-hi)}.legend-dot--now{background:var(--accent)}
.cfg-hint{margin-left:auto;font-size:11px;color:var(--text-3);text-transform:none;letter-spacing:0}.cfg-section{padding:16px 18px}.cfg-section-title{font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.05em;font-family:var(--font-ui);margin-bottom:12px}.cfg-divider{height:1px;background:var(--border)}.cfg-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.cfg-grid-3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.field-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.form-row--full{grid-column:1/-1}.time-desc{font-size:11px;color:var(--text-3);margin-top:10px;font-family:var(--font-ui)}.mode-title{display:inline}.mode-title--active{color:var(--green)}.mode-title--inactive{color:var(--orange)}.mode-title-row{display:flex;align-items:center;gap:10px}.mode-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:14px}.mode-hint{font-size:11px;color:var(--text-3);font-family:var(--font-ui)}.mode-hint--inactive{color:rgba(245,166,35,.75)}.section-top-gap{margin-top:14px}
.toggle{display:flex;align-items:center;cursor:pointer;flex-shrink:0}.toggle input{display:none}.toggle-track{width:36px;height:20px;border-radius:10px;background:var(--border-hi);position:relative;transition:background .2s}.toggle-track::after{content:'';position:absolute;top:3px;left:3px;width:14px;height:14px;border-radius:50%;background:var(--text-3);transition:transform .2s,background .2s}.toggle input:checked + .toggle-track{background:var(--accent)}.toggle input:checked + .toggle-track::after{transform:translateX(16px);background:#fff}.toggle-label{font-size:12px;color:var(--text-2)}.toggle-list{margin-top:14px;display:flex;flex-direction:column;gap:10px}.toggle-row{display:flex;align-items:center;justify-content:space-between;gap:12px}.toggle-row--compact{width:100%}.toggle-row-label{font-size:13px;color:var(--text-1)}
.form-help{margin-top:6px;font-size:11px;color:var(--text-3);line-height:1.6;font-family:var(--font-ui)}.preset-row{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-top:14px}.preset-label{font-size:11px;color:var(--text-3);text-transform:uppercase;letter-spacing:.05em;font-family:var(--font-ui)}.preset-actions{display:flex;gap:8px;flex-wrap:wrap}.strategy-summary{display:flex;gap:8px;flex-wrap:wrap}.summary-pill{padding:6px 10px;border-radius:999px;background:var(--bg-base);border:1px solid var(--border);font-size:11px;color:var(--text-2);font-family:var(--font-ui)}.summary-pill--ok{color:var(--green);border-color:rgba(62,207,114,.32);background:rgba(62,207,114,.08)}.strategy-note{margin-top:10px;font-size:12px;line-height:1.7;color:var(--text-3)}.inline-note{min-height:40px;display:flex;align-items:center;padding:0 12px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg-base);font-size:12px;color:var(--text-2);line-height:1.6}.automation-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}.sub-card{display:flex;flex-direction:column;gap:12px;padding:14px 16px;border:1px solid var(--border);border-radius:var(--radius);background:var(--bg-base)}.sub-card__title{font-size:12px;font-weight:600;color:var(--text-2);text-transform:uppercase;letter-spacing:.04em;font-family:var(--font-ui)}.chk{accent-color:var(--accent);width:15px;height:15px}
.cfg-footer{padding:12px 18px;border-top:1px solid var(--border);display:flex;align-items:center;gap:10px}.saved-hint{font-size:11px;color:var(--green);font-family:var(--font-ui)}.log-body{height:300px;overflow-y:auto;padding:10px 16px;font-family:var(--font-ui);font-size:12px;line-height:1.75}.log-empty{color:var(--text-3);text-align:center;padding:40px 0}.log-line{color:var(--text-2)}.log-ok{color:var(--green)}.log-err{color:var(--red)}.log-warn{color:var(--orange)}.log-accent{color:var(--accent)}.log-inactive{color:var(--orange);opacity:.8}
@media (max-width:1100px){.ap-layout{grid-template-columns:1fr}.automation-grid{grid-template-columns:1fr}}@media (max-width:760px){.cfg-grid,.cfg-grid-3,.field-grid{grid-template-columns:1fr}.header-right,.mode-row,.preset-row,.cfg-footer{align-items:flex-start}.strategy-summary{flex-direction:column}}
</style>
