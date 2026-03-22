<template>
  <div>
    <div class="page-header">
      <div>
        <h1 class="page-title">自动驾驶</h1>
        <div class="page-subtitle">全自动下载 → 转换 → 上传，按时段节奏持续运行，无需人工干预</div>
      </div>
      <div class="header-right">
        <div class="tz-clock">
          <span class="tz-name">{{ status.current_tz_name || 'Asia/Shanghai' }}</span>
          <span class="tz-time">{{ status.current_tz_time || '--:--' }}</span>
          <span class="tz-badge" :class="status.is_active_hour ? 'tz-badge--active' : 'tz-badge--sleep'">
            {{ status.is_active_hour ? '活跃时段' : '休眠时段' }}
          </span>
        </div>
        <span class="tag" :class="statusTag.cls">{{ statusTag.text }}</span>
      </div>
    </div>

    <div class="ap-body">
      <!-- ── 左栏：状态面板 ── -->
      <div class="ap-status">

        <!-- 启停按钮 -->
        <div class="power-card">
          <button
            class="power-btn"
            :class="running ? 'power-btn--on' : 'power-btn--off'"
            :disabled="toggling"
            @click="togglePower"
          >
            <span class="power-icon">⏻</span>
            <span class="power-label">{{ running ? '点击停止' : '一键启动' }}</span>
          </button>
          <div class="power-hint">
            {{ running ? '配置将在下一轮会话生效，随时可安全停止。' : '启动后自动按配置节奏执行下载流程。' }}
          </div>
        </div>

        <!-- 今日统计 -->
        <div class="card">
          <div class="card-header">今日统计</div>
          <div class="stat-grid">
            <div class="stat-item">
              <div class="stat-num" :class="nextSessionClass">{{ nextSessionLabel }}</div>
              <div class="stat-lbl">下次会话</div>
            </div>
            <div class="stat-item">
              <div class="stat-num">{{ status.today?.sessions ?? 0 }}</div>
              <div class="stat-lbl">完成会话</div>
            </div>
            <div class="stat-item">
              <div class="stat-num">{{ status.today?.downloaded ?? 0 }}</div>
              <div class="stat-lbl">下载图片</div>
            </div>
            <div class="stat-item">
              <div class="stat-num">{{ remainingLimitDisplay }}</div>
              <div class="stat-lbl">今日剩余</div>
            </div>
          </div>
        </div>

        <!-- 运行阶段（仅运行时） -->
        <div class="card phase-card" v-if="running">
          <div class="phase-row">
            <span class="phase-label">{{ phaseLabel }}</span>
            <span class="phase-mode" v-if="status.mode">
              {{ status.mode === 'active' ? '活跃' : '非活跃' }}
            </span>
          </div>
          <div class="hour-grid">
            <div
              v-for="h in 24"
              :key="h - 1"
              class="hour-cell"
              :class="hourCellClass(h - 1)"
              :title="String(h - 1).padStart(2, '0') + ':00'"
            >{{ h - 1 }}</div>
          </div>
          <div class="hour-legend">
            <span><span class="legend-dot legend-dot--active"></span>活跃</span>
            <span><span class="legend-dot legend-dot--inactive"></span>轻量</span>
            <span><span class="legend-dot legend-dot--now"></span>当前</span>
          </div>
        </div>

        <!-- 运行日志 -->
        <div class="card log-card">
          <div class="card-header">
            运行日志
            <button class="btn btn--sm" @click="logs = []">清空</button>
          </div>
          <div class="log-body" ref="logEl">
            <div v-if="logs.length === 0" class="log-empty">
              暂无日志，启动后这里会显示会话、等待和异常信息。
            </div>
            <div
              v-for="(line, index) in logs"
              :key="index"
              class="log-line"
              :class="logLineClass(line)"
            >{{ line }}</div>
          </div>
        </div>
      </div>

      <!-- ── 右栏：配置面板 ── -->
      <div class="ap-config">
        <div class="card cfg-card">

          <!-- Tab 导航 -->
          <div class="cfg-tabs">
            <button
              v-for="tab in configTabs"
              :key="tab.key"
              class="cfg-tab"
              :class="{ 'cfg-tab--active': activeConfigTab === tab.key }"
              @click="activeConfigTab = tab.key"
            >{{ tab.label }}</button>
          </div>

          <!-- ── Tab：节奏时段 ── -->
          <div v-if="activeConfigTab === 'rhythm'" class="cfg-pane">

            <div class="cfg-section">
              <div class="cfg-section-title">时区与活跃时段</div>
              <div class="cfg-grid-3">
                <div class="form-row">
                  <label>时区</label>
                  <select class="select" v-model="cfg.timezone" @change="onCfgChange">
                    <option v-for="tz in supportedTimezones" :key="tz" :value="tz">{{ tz }}</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>开始时间</label>
                  <select class="select" v-model.number="cfg.active_start" @change="onCfgChange">
                    <option v-for="h in 24" :key="'s' + (h - 1)" :value="h - 1">{{ String(h - 1).padStart(2, '0') }}:00</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>结束时间</label>
                  <select class="select" v-model.number="cfg.active_end" @change="onCfgChange">
                    <option v-for="h in 24" :key="'e' + (h - 1)" :value="h - 1">{{ String(h - 1).padStart(2, '0') }}:00</option>
                  </select>
                </div>
              </div>
              <div class="time-desc">
                活跃时段：{{ String(cfg.active_start).padStart(2, '0') }}:00 — {{ String(cfg.active_end).padStart(2, '0') }}:00
                <span v-if="cfg.active_start > cfg.active_end" class="tag tag--warn">跨天</span>
              </div>
            </div>

            <div class="cfg-divider"></div>

            <div class="cfg-section">
              <div class="cfg-section-title">每日下载上限</div>
              <div class="cfg-grid">
                <div class="form-row">
                  <label>上限策略</label>
                  <select class="select" v-model="cfg.daily_limit_mode" @change="onDailyLimitModeChange">
                    <option value="auto">自动选择</option>
                    <option value="manual">手动指定</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>手动上限</label>
                  <input
                    v-if="cfg.daily_limit_mode === 'manual'"
                    class="input" type="number" min="1" max="500"
                    v-model.number="cfg.manual_daily_limit"
                    placeholder="1-500"
                    @change="onCfgChange"
                  />
                  <div v-else class="inline-note inline-note--muted">自动模式，当前值 {{ dailyLimitDisplay }} 张</div>
                </div>
              </div>
              <div class="form-help">{{ dailyLimitHint }}</div>
            </div>

            <div class="cfg-divider"></div>

            <div class="cfg-section">
              <div class="cfg-section-title mode-title mode-title--active">活跃时段 — 每轮下载</div>
              <div class="cfg-grid">
                <div class="form-row">
                  <label>单次最少</label>
                  <input class="input" type="number" min="1" max="200" v-model.number="cfg.active_session_min" @change="onCfgChange" />
                </div>
                <div class="form-row">
                  <label>单次最多</label>
                  <input class="input" type="number" min="1" max="200" v-model.number="cfg.active_session_max" @change="onCfgChange" />
                </div>
                <div class="form-row">
                  <label>最短间隔（分钟）</label>
                  <input class="input" type="number" min="1" v-model.number="activeIntervalMinMin" @change="onActiveIntervalChange" />
                </div>
                <div class="form-row">
                  <label>最长间隔（分钟）</label>
                  <input class="input" type="number" min="1" v-model.number="activeIntervalMaxMin" @change="onActiveIntervalChange" />
                </div>
              </div>
              <div class="mode-hint">
                每轮 {{ cfg.active_session_min }}–{{ cfg.active_session_max }} 张，间隔 {{ activeIntervalMinMin }}–{{ activeIntervalMaxMin }} 分钟
              </div>
            </div>

            <div class="cfg-divider"></div>

            <div class="cfg-section">
              <div class="mode-title-row">
                <div class="cfg-section-title mode-title mode-title--inactive">非活跃时段</div>
                <label class="toggle">
                  <input type="checkbox" v-model="cfg.inactive_enabled" @change="onCfgChange" />
                  <span class="toggle-track"></span>
                </label>
                <span class="toggle-label">{{ cfg.inactive_enabled ? '轻量下载' : '完全休眠' }}</span>
              </div>
              <template v-if="cfg.inactive_enabled">
                <div class="cfg-grid section-top-gap">
                  <div class="form-row">
                    <label>单次最少</label>
                    <input class="input" type="number" min="1" max="100" v-model.number="cfg.inactive_session_min" @change="onCfgChange" />
                  </div>
                  <div class="form-row">
                    <label>单次最多</label>
                    <input class="input" type="number" min="1" max="100" v-model.number="cfg.inactive_session_max" @change="onCfgChange" />
                  </div>
                  <div class="form-row">
                    <label>最短间隔（分钟）</label>
                    <input class="input" type="number" min="1" v-model.number="inactiveIntervalMinMin" @change="onInactiveIntervalChange" />
                  </div>
                  <div class="form-row">
                    <label>最长间隔（分钟）</label>
                    <input class="input" type="number" min="1" v-model.number="inactiveIntervalMaxMin" @change="onInactiveIntervalChange" />
                  </div>
                </div>
                <div class="mode-hint mode-hint--inactive">深夜策略建议保守，间隔设长一些。</div>
              </template>
            </div>

          </div>

          <!-- ── Tab：下载内容 ── -->
          <div v-if="activeConfigTab === 'content'" class="cfg-pane">

            <div class="cfg-section">
              <div class="cfg-section-title">基础参数</div>
              <div class="cfg-grid">
                <div class="form-row">
                  <label>图片类型</label>
                  <select class="select" v-model="cfg.wallpaper_type" @change="onCfgChange">
                    <option value="static">静态图</option>
                    <option value="dynamic">动态图</option>
                    <option value="all">全部</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>屏幕方向</label>
                  <select class="select" v-model="cfg.screen_orientation" @change="onCfgChange">
                    <option value="all">全部</option>
                    <option value="landscape">横屏</option>
                    <option value="portrait">竖屏</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>排序方式</label>
                  <select class="select" v-model="cfg.sort_by" @change="onCfgChange">
                    <option value="yesterday_hot">昨日热门</option>
                    <option value="3days_hot">近三天热门</option>
                    <option value="7days_hot">上周热门</option>
                    <option value="latest">最新</option>
                    <option value="most_views">推荐</option>
                  </select>
                </div>
                <div class="form-row">
                  <label>最低热度</label>
                  <input class="input" type="number" min="0" v-model.number="cfg.min_hot_score" @change="onCfgChange" />
                </div>
              </div>
              <div class="toggle-list">
                <label class="toggle-row">
                  <span class="toggle-row-label">仅限 VIP 账号资源</span>
                  <label class="toggle">
                    <input type="checkbox" v-model="cfg.vip_only" @change="onCfgChange" />
                    <span class="toggle-track"></span>
                  </label>
                </label>
              </div>
            </div>

            <div class="cfg-divider"></div>

            <div class="cfg-section">
              <div class="cfg-section-title">内容筛选</div>
              <div class="form-row form-row--full" style="margin-bottom:10px">
                <label>分类轮询</label>
                <input class="input" v-model="categoriesInput" placeholder="动漫, 二次元, 风景（逗号分隔；多分类会自动轮询）" @change="onCategoriesChange" />
              </div>
              <div class="form-row form-row--full" style="margin-bottom:10px">
                <label>色系筛选</label>
                <input class="input" v-model="colorsInput" placeholder="蓝色, 紫色（留空不限）" @change="onColorsChange" />
              </div>
              <div class="form-row form-row--full">
                <label>黑名单标签</label>
                <input class="input" v-model="blacklistInput" placeholder="nsfw, blood（命中即跳过）" @change="onBlacklistChange" />
              </div>
            </div>

            <div class="cfg-divider"></div>

            <div class="cfg-section">
              <div class="cfg-section-title">分辨率门槛</div>
              <div class="cfg-grid">
                <div class="form-row">
                  <label>最小宽度</label>
                  <input class="input" type="number" min="0" v-model.number="cfg.min_width" placeholder="不限" @change="onCfgChange" />
                </div>
                <div class="form-row">
                  <label>最小高度</label>
                  <input class="input" type="number" min="0" v-model.number="cfg.min_height" placeholder="不限" @change="onCfgChange" />
                </div>
              </div>
              <div class="preset-row">
                <button class="preset-btn" @click="applyResolutionPreset(1920, 1080)">FHD 1080p</button>
                <button class="preset-btn" @click="applyResolutionPreset(2560, 1440)">QHD 1440p</button>
                <button class="preset-btn" @click="applyResolutionPreset(3840, 2160)">4K 2160p</button>
                <button class="preset-btn" @click="clearResolutionPreset()">不限</button>
              </div>
            </div>

          </div>

          <!-- ── Tab：处理上传 ── -->
          <div v-if="activeConfigTab === 'upload'" class="cfg-pane">

            <div class="cfg-section">
              <div class="cfg-section-title">图床上传</div>
              <div class="toggle-list">
                <label class="toggle-row">
                  <span class="toggle-row-label">下载完成后自动上传到图床</span>
                  <label class="toggle">
                    <input type="checkbox" v-model="cfg.use_imgbed_upload" @change="onCfgChange" />
                    <span class="toggle-track"></span>
                  </label>
                </label>
              </div>
              <template v-if="cfg.use_imgbed_upload">
                <div class="cfg-grid section-top-gap">
                  <div class="form-row">
                    <label>上传 Profile</label>
                    <select class="select" v-model="uploadSettings.task_profile" @change="onCfgChange">
                      <option v-for="profile in uploadSettings.profiles" :key="profile.key" :value="profile.key">
                        {{ profile.name }} / {{ profile.channel }}
                      </option>
                    </select>
                  </div>
                  <div class="form-row">
                    <label>策略摘要</label>
                    <div class="inline-note">{{ uploadProfileModeLabel }}</div>
                  </div>
                </div>
                <div v-if="selectedAutoUploadProfile" class="cfg-grid section-top-gap">
                  <div class="form-row form-row--full">
                    <label>路径模板</label>
                    <input class="input" v-model="selectedAutoUploadProfile.folder_pattern" placeholder="bg/{type}/{year}/{month}（留空用下方固定目录）" @change="onCfgChange" />
                    <div class="form-help">支持 {type}、{category}、{year}、{month}、{date}；优先级高于固定目录</div>
                  </div>
                  <div class="form-row">
                    <label>横图目录</label>
                    <input class="input" v-model="selectedAutoUploadProfile.folder_landscape" placeholder="bg/pc" @change="onCfgChange" />
                  </div>
                  <div class="form-row">
                    <label>竖图目录</label>
                    <input class="input" v-model="selectedAutoUploadProfile.folder_portrait" placeholder="bg/mb" @change="onCfgChange" />
                  </div>
                  <div class="form-row">
                    <label>动态图目录</label>
                    <input class="input" v-model="selectedAutoUploadProfile.folder_dynamic" placeholder="bg/dynamic" @change="onCfgChange" />
                  </div>
                  <div class="form-row">
                    <label>上传最小宽度</label>
                    <input class="input" type="number" min="0"
                      :value="selectedAutoUploadProfile.upload_filter.min_width || ''"
                      @change="selectedAutoUploadProfile.upload_filter.min_width = $event.target.value ? +$event.target.value : null; onCfgChange()" />
                  </div>
                  <div class="form-row">
                    <label>上传最小高度</label>
                    <input class="input" type="number" min="0"
                      :value="selectedAutoUploadProfile.upload_filter.min_height || ''"
                      @change="selectedAutoUploadProfile.upload_filter.min_height = $event.target.value ? +$event.target.value : null; onCfgChange()" />
                  </div>
                  <div class="form-row">
                    <label>服务端压缩</label>
                    <input type="checkbox" v-model="selectedAutoUploadProfile.server_compress" class="chk" @change="onCfgChange" />
                  </div>
                  <div class="form-row">
                    <label>本地预处理</label>
                    <input type="checkbox" v-model="selectedAutoUploadProfile.image_processing.enabled" class="chk" @change="onCfgChange" />
                  </div>
                  <div class="form-row form-row--full">
                    <label class="toggle-row toggle-row--compact">
                      <span class="toggle-row-label">仅上传原图（跳过预览图）</span>
                      <label class="toggle">
                        <input type="checkbox" v-model="selectedAutoUploadProfile.upload_filter.only_original" @change="onCfgChange" />
                        <span class="toggle-track"></span>
                      </label>
                    </label>
                  </div>
                </div>
              </template>
            </div>

            <div class="cfg-divider"></div>

            <div class="cfg-section">
              <div class="cfg-section-title">静态图格式转换</div>
              <div class="toggle-list">
                <label class="toggle-row">
                  <span class="toggle-row-label">下载完成后自动转换格式</span>
                  <label class="toggle">
                    <input type="checkbox" v-model="mediaSettings.auto_convert" @change="onCfgChange" />
                    <span class="toggle-track"></span>
                  </label>
                </label>
              </div>
              <template v-if="mediaSettings.auto_convert">
                <div class="cfg-grid section-top-gap">
                  <div class="form-row">
                    <label>输出格式</label>
                    <select class="select" v-model="mediaSettings.image.output_format" @change="onCfgChange">
                      <option value="webp">WebP</option>
                      <option value="jpg">JPEG</option>
                      <option value="png">PNG</option>
                    </select>
                  </div>
                  <div class="form-row">
                    <label>压缩质量</label>
                    <input class="input" type="number" min="1" max="100" v-model.number="mediaSettings.image.quality" @change="onCfgChange" />
                  </div>
                  <div class="form-row">
                    <label>超时（秒）</label>
                    <input class="input" type="number" min="10" v-model.number="mediaSettings.image.timeout_seconds" @change="onCfgChange" />
                  </div>
                  <div class="form-row">
                    <label>转换后删除原图</label>
                    <input type="checkbox" v-model="mediaSettings.image.delete_original" class="chk" @change="onCfgChange" />
                  </div>
                </div>
              </template>
              <div class="sub-card section-top-gap">
                <div class="sub-card__title">动态图转换（已关闭）</div>
                <div class="inline-note">AutoPilot 仅支持静态图自动转换；动态图请在"转换"页面手动处理。</div>
              </div>
            </div>

          </div>

          <!-- ── Tab：存储管理 ── -->
          <div v-if="activeConfigTab === 'storage'" class="cfg-pane">

            <div class="cfg-section">
              <div class="cfg-section-title">本地存储概况</div>
              <div v-if="storageInfo" class="storage-stat-bar">
                <span class="stat-pill">本地 <strong>{{ storageInfo.total_local }}</strong> 张</span>
                <span class="stat-pill stat-pill--ok">已上传 <strong>{{ storageInfo.uploaded_local }}</strong> 张</span>
                <span class="stat-pill stat-pill--warn" v-if="storageInfo.pending_upload > 0">待上传 <strong>{{ storageInfo.pending_upload }}</strong> 张</span>
                <span class="stat-pill">图床总计 <strong>{{ storageInfo.total_uploaded }}</strong> 张</span>
              </div>
              <div v-else class="inline-note inline-note--muted">点击"刷新统计"加载</div>
              <div class="storage-actions">
                <button class="btn btn--sm" @click="loadStorageStats" :disabled="cleaningUp">刷新统计</button>
              </div>
              <div class="form-help">本地文件夹只是暂存区，图片最终归宿是图床。建议定期清理以释放磁盘空间。</div>
            </div>

            <div class="cfg-divider"></div>

            <div class="cfg-section">
              <div class="cfg-section-title">自动清理</div>
              <div class="toggle-list">
                <label class="toggle-row">
                  <span class="toggle-row-label">每次下载会话结束后自动清理本地文件</span>
                  <label class="toggle">
                    <input type="checkbox" v-model="cfg.storage_auto_clean" @change="onCfgChange" />
                    <span class="toggle-track"></span>
                  </label>
                </label>
              </div>
              <template v-if="cfg.storage_auto_clean">
                <div class="cfg-grid section-top-gap">
                  <div class="form-row">
                    <label>清理策略</label>
                    <select class="select" v-model="cfg.storage_strategy" @change="onCfgChange">
                      <option value="keep_count">保留最新 N 张，删除更老的</option>
                      <option value="keep_days">保留最近 N 天的文件</option>
                      <option value="upload_and_delete">每次删除所有已上传文件</option>
                    </select>
                  </div>
                  <div class="form-row" v-if="cfg.storage_strategy === 'keep_count'">
                    <label>最多保留（张）</label>
                    <input class="input" type="number" min="50" max="9999" v-model.number="cfg.storage_max_count" @change="onCfgChange" />
                  </div>
                  <div class="form-row" v-if="cfg.storage_strategy === 'keep_days'">
                    <label>保留最近（天）</label>
                    <input class="input" type="number" min="1" max="365" v-model.number="cfg.storage_keep_days" @change="onCfgChange" />
                  </div>
                </div>
                <div class="toggle-list section-top-gap">
                  <label class="toggle-row">
                    <span class="toggle-row-label">只清理已成功上传到图床的文件（推荐，防误删）</span>
                    <label class="toggle">
                      <input type="checkbox" v-model="cfg.storage_uploaded_only" @change="onCfgChange" />
                      <span class="toggle-track"></span>
                    </label>
                  </label>
                </div>
                <div class="storage-actions">
                  <button class="btn btn--sm" @click="previewCleanup" :disabled="cleaningUp">
                    {{ cleaningUp ? '计算中...' : '预览将删除什么' }}
                  </button>
                  <button class="btn btn--sm btn--danger" @click="runCleanupNow" :disabled="cleaningUp">立即清理</button>
                </div>
                <div v-if="cleanupPreview" class="cleanup-preview">
                  <div class="cleanup-preview__row"><span>符合条件</span><strong>{{ cleanupPreview.total_eligible }}</strong></div>
                  <div class="cleanup-preview__row"><span>将删除</span><strong class="text-red">{{ cleanupPreview.deleted }}</strong></div>
                  <div class="cleanup-preview__row"><span>清理后剩余</span><strong>{{ cleanupPreview.remaining }}</strong></div>
                  <div class="cleanup-preview__paths" v-if="cleanupPreview.deleted_paths?.length">
                    <div style="font-size:11px;color:var(--text-3);margin-bottom:4px">将删除的文件（前50条）</div>
                    <div v-for="p in cleanupPreview.deleted_paths" :key="p" class="path-item">{{ p }}</div>
                  </div>
                </div>
              </template>
            </div>

          </div>

          <!-- 底部操作栏 -->
          <div class="cfg-footer">
            <button class="btn btn--primary btn--sm" @click="saveConfig">保存配置</button>
            <span v-if="savedHint" class="saved-hint">已保存 ✓</span>
            <span class="cfg-hint" v-if="running">运行中修改将在下一轮会话生效</span>
          </div>

        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { autopilotApi, galleryApi, settingsApi } from '../api'
import { applyCompressedUploadProfile, applyLosslessUploadProfile, isLosslessUploadProfile, normalizeUploadSettings } from '../utils/uploadProfiles'
const createDefaultAutoPilotConfig=()=>({timezone:'Asia/Shanghai',active_start:8,active_end:23,daily_limit_mode:'auto',manual_daily_limit:null,active_session_min:5,active_session_max:15,active_interval_min:1800,active_interval_max:7200,inactive_enabled:false,inactive_session_min:2,inactive_session_max:5,inactive_interval_min:7200,inactive_interval_max:14400,wallpaper_type:'static',screen_orientation:'all',sort_by:'yesterday_hot',min_hot_score:0,vip_only:false,categories:[],color_themes:[],tag_blacklist:[],min_width:null,min_height:null,use_imgbed_upload:false,storage_auto_clean:false,storage_max_count:500,storage_strategy:'keep_count',storage_keep_days:30,storage_uploaded_only:true})
const createDefaultMediaSettings=()=>({auto_convert:false,max_concurrent:1,video:{enabled:false,output_format:'webp',fps:0,max_frames:0,width:0,max_width:0,quality:100,delete_original:false,timeout_seconds:300,cpu_nice:5},image:{enabled:false,output_format:'webp',quality:100,delete_original:false,timeout_seconds:120,cpu_nice:5}})
const normalizeMediaSettings=(remote={})=>{const defaults=createDefaultMediaSettings();return{...defaults,...remote,video:{...defaults.video,...(remote.video||{})},image:{...defaults.image,...(remote.image||{})}}}
const parseCsvInput=value=>value?value.split(',').map(item=>item.trim()).filter(Boolean):[]
const clampNumber=(value,fallback,min)=>{const numeric=Number(value);if(!Number.isFinite(numeric))return fallback;return Math.max(min,Math.round(numeric))}
const normalizeRange=(minValue,maxValue,fallbackMin,fallbackMax,minLimit)=>{const safeMin=clampNumber(minValue,fallbackMin,minLimit),safeMax=clampNumber(maxValue,fallbackMax,minLimit);return safeMin<=safeMax?[safeMin,safeMax]:[safeMax,safeMin]}
const normalizeAutoPilotConfig=remote=>{const merged={...createDefaultAutoPilotConfig(),...(remote||{})};merged.daily_limit_mode=String(merged.daily_limit_mode||'auto').toLowerCase()==='manual'?'manual':'auto';merged.manual_daily_limit=merged.manual_daily_limit?Math.min(500,Math.max(1,Number(merged.manual_daily_limit)||0)):null;[merged.active_session_min,merged.active_session_max]=normalizeRange(merged.active_session_min,merged.active_session_max,5,15,1);[merged.inactive_session_min,merged.inactive_session_max]=normalizeRange(merged.inactive_session_min,merged.inactive_session_max,2,5,1);merged.active_interval_min=clampNumber(merged.active_interval_min,1800,60);merged.active_interval_max=clampNumber(merged.active_interval_max,7200,60);merged.inactive_interval_min=clampNumber(merged.inactive_interval_min,7200,60);merged.inactive_interval_max=clampNumber(merged.inactive_interval_max,14400,60);merged.min_hot_score=clampNumber(merged.min_hot_score,0,0);merged.storage_auto_clean=Boolean(merged.storage_auto_clean);merged.storage_max_count=Math.max(1,Math.min(99999,Number(merged.storage_max_count)||500));merged.storage_keep_days=Math.max(1,Math.min(3650,Number(merged.storage_keep_days)||30));merged.storage_uploaded_only=Boolean(merged.storage_uploaded_only!==false);const strategy=String(merged.storage_strategy||'keep_count').toLowerCase();merged.storage_strategy=['keep_count','keep_days','upload_and_delete'].includes(strategy)?strategy:'keep_count';return merged}
const cloneUploadProfiles=profiles=>(profiles||[]).map(profile=>({...profile,image_processing:{...(profile.image_processing||{})},upload_filter:{...(profile.upload_filter||{})}}))
const status=ref({}),toggling=ref(false),logs=ref([]),logEl=ref(null),savedHint=ref(false),supportedTimezones=ref(['Asia/Shanghai']),cfg=ref(createDefaultAutoPilotConfig()),uploadSettings=ref(normalizeUploadSettings()),mediaSettings=ref(createDefaultMediaSettings()),systemInfo=ref(null),categoriesInput=ref(''),colorsInput=ref(''),blacklistInput=ref(''),activeIntervalMinMin=ref(30),activeIntervalMaxMin=ref(120),inactiveIntervalMinMin=ref(120),inactiveIntervalMaxMin=ref(240),currentHour=ref(new Date().getHours()),storageInfo=ref(null),cleaningUp=ref(false),cleanupPreview=ref(null),activeConfigTab=ref('rhythm')
const running=computed(()=>status.value.status==='running')
const selectedAutoUploadProfile=computed(()=>{const profiles=uploadSettings.value.profiles||[];return profiles.find(profile=>profile.key===uploadSettings.value.task_profile)||profiles[0]||null})
const uploadProfileModeLabel=computed(()=>{const profile=selectedAutoUploadProfile.value;if(!profile)return'未找到可用上传 Profile';const mode=isLosslessUploadProfile(profile)?'原图直传':'本地 WebP 预处理';const folderSummary=profile.folder_pattern?`路径模板 ${profile.folder_pattern}`:[profile.folder_landscape,profile.folder_portrait,profile.folder_dynamic].filter(Boolean).join(' / ');return[mode,profile.channel,folderSummary].filter(Boolean).join(' · ')})
const backendLimitReady=computed(()=>Number.isFinite(Number(status.value.today?.daily_limit))&&Number.isFinite(Number(status.value.today?.remaining)))
const dailyLimitDisplay=computed(()=>backendLimitReady.value?status.value.today.daily_limit:'待刷新')
const remainingLimitDisplay=computed(()=>backendLimitReady.value?status.value.today.remaining:'待刷新')
const dailyLimitHint=computed(()=>{const effectiveLimit=status.value.today?.daily_limit;const remaining=status.value.today?.remaining;if(!backendLimitReady.value)return'当前后台还没有返回今日统计数据，通常是刚启动或网络异常。正常运行后会显示自动值和剩余数取值。';if(cfg.value.daily_limit_mode==='manual'){const manualLimit=cfg.value.manual_daily_limit||effectiveLimit||'--';return`手动模式：今天的硬上限，当前有效 ${manualLimit} 张，剩余 ${remaining??'--'} 张。如当天已触达上限，AutoPilot 将停止下载直到翌日。`}return`自动模式：当前有效 ${effectiveLimit} 张，今日剩余 ${remaining??'--'} 张。自动值基于当前账号池的每日配额，实际可用量会随账号变动。`})
const statusTag=computed(()=>!running.value?{cls:'tag--grey',text:'IDLE'}:({session:{cls:'tag--ok',text:'SESSION'},waiting:{cls:'tag--info',text:'WAITING'},sleeping:{cls:'tag--warn',text:'SLEEPING'},daily_limit:{cls:'tag--warn',text:'DAILY LIMIT'},starting:{cls:'tag--info',text:'STARTING'}}[status.value.phase]||{cls:'tag--ok',text:'RUNNING'}))
const phaseLabel=computed(()=>({session:'正在执行下载会话',waiting:'会话间等待中',sleeping:'等待活跃时段开始',daily_limit:'今日配额已用完，等待明天',starting:'初始化中...'}[status.value.phase]||'运行中'))
const nextSessionLabel=computed(()=>{if(!running.value)return'—';if(status.value.phase==='session')return'进行中';if(!status.value.next_session_at)return'即将开始';const diff=Math.max(0,Math.floor((new Date(status.value.next_session_at)-Date.now())/1000));if(diff<60)return`${diff}s`;if(diff<3600)return`${Math.floor(diff/60)}min`;return`${Math.floor(diff/3600)}h ${Math.floor((diff%3600)/60)}min`})
const nextSessionClass=computed(()=>status.value.phase==='session'?'stat-num--active':'')
let savedHintTimer=null,pollTimer=null,configLoaded=false
const syncFilterInputsFromConfig=()=>{categoriesInput.value=(cfg.value.categories||[]).join(', ');colorsInput.value=(cfg.value.color_themes||[]).join(', ');blacklistInput.value=(cfg.value.tag_blacklist||[]).join(', ')}
const applyConfig=remote=>{cfg.value=normalizeAutoPilotConfig(remote);activeIntervalMinMin.value=Math.round((cfg.value.active_interval_min??1800)/60);activeIntervalMaxMin.value=Math.round((cfg.value.active_interval_max??7200)/60);inactiveIntervalMinMin.value=Math.round((cfg.value.inactive_interval_min??7200)/60);inactiveIntervalMaxMin.value=Math.round((cfg.value.inactive_interval_max??14400)/60);syncFilterInputsFromConfig()}
const isHourActive=hour=>{const start=cfg.value.active_start,end=cfg.value.active_end;return start<=end?hour>=start&&hour<end:hour>=start||hour<end}
const isHourInactive=hour=>!isHourActive(hour)&&cfg.value.inactive_enabled
const hourCellClass=hour=>hour===currentHour.value?'hour-cell--now':isHourActive(hour)?'hour-cell--active':isHourInactive(hour)?'hour-cell--inactive':'hour-cell--sleep'
const syncIntervalInputsToConfig=()=>{[activeIntervalMinMin.value,activeIntervalMaxMin.value]=normalizeRange(activeIntervalMinMin.value,activeIntervalMaxMin.value,30,120,1);[inactiveIntervalMinMin.value,inactiveIntervalMaxMin.value]=normalizeRange(inactiveIntervalMinMin.value,inactiveIntervalMaxMin.value,120,240,1);cfg.value.active_interval_min=activeIntervalMinMin.value*60;cfg.value.active_interval_max=activeIntervalMaxMin.value*60;cfg.value.inactive_interval_min=inactiveIntervalMinMin.value*60;cfg.value.inactive_interval_max=inactiveIntervalMaxMin.value*60}
const normalizeConfigState=()=>{syncIntervalInputsToConfig();cfg.value=normalizeAutoPilotConfig(cfg.value)}
const buildPayload=()=>{normalizeConfigState();return{...cfg.value,categories:parseCsvInput(categoriesInput.value),color_themes:parseCsvInput(colorsInput.value),tag_blacklist:parseCsvInput(blacklistInput.value)}}
const buildUploadSettingsPayload=()=>{const normalized=normalizeUploadSettings(uploadSettings.value);return{task_profile:normalized.task_profile,gallery_default_format:normalized.gallery_default_format,profiles:cloneUploadProfiles(normalized.profiles)}}
const buildMediaSettingsPayload=()=>{const normalized=normalizeMediaSettings(mediaSettings.value);return{auto_convert:!!normalized.auto_convert,max_concurrent:normalized.max_concurrent||1,video:{...normalized.video,enabled:false},image:{...normalized.image}}}
const applyResolutionPreset=(width,height)=>{cfg.value.min_width=width;cfg.value.min_height=height;onCfgChange()}
const clearResolutionPreset=()=>{cfg.value.min_width=null;cfg.value.min_height=null;onCfgChange()}
const onActiveIntervalChange=()=>{syncIntervalInputsToConfig();onCfgChange()}
const onInactiveIntervalChange=()=>{syncIntervalInputsToConfig();onCfgChange()}
const onDailyLimitModeChange=()=>{if(cfg.value.daily_limit_mode==='manual'&&!cfg.value.manual_daily_limit)cfg.value.manual_daily_limit=status.value.today?.daily_limit||45;onCfgChange()}
const applyAutoUploadLossless=()=>{if(!selectedAutoUploadProfile.value)return;applyLosslessUploadProfile(selectedAutoUploadProfile.value);onCfgChange()}
const applyAutoUploadCompressed=()=>{if(!selectedAutoUploadProfile.value)return;applyCompressedUploadProfile(selectedAutoUploadProfile.value);onCfgChange()}
const showSavedHint=()=>{savedHint.value=true;clearTimeout(savedHintTimer);savedHintTimer=setTimeout(()=>{savedHint.value=false},2000)}
const loadAutomationSettings=async()=>{const [uploadsResult,mediaResult,systemInfoResult]=await Promise.allSettled([settingsApi.getUploads(),settingsApi.getMediaConvert(),settingsApi.getSystemInfo()]);uploadSettings.value=uploadsResult.status==='fulfilled'?normalizeUploadSettings(uploadsResult.value):normalizeUploadSettings();mediaSettings.value=mediaResult.status==='fulfilled'?normalizeMediaSettings(mediaResult.value):createDefaultMediaSettings();if(systemInfoResult.status==='fulfilled')systemInfo.value=systemInfoResult.value}
const persistAutomationSettings=async({showHint=true,silent=false}={})=>{try{const [configRes,uploadRes,mediaRes]=await Promise.all([autopilotApi.saveConfig(buildPayload()),settingsApi.setUploads(buildUploadSettingsPayload()),settingsApi.setMediaConvert(buildMediaSettingsPayload())]);if(configRes?.config)applyConfig(configRes.config);if(uploadRes?.uploads)uploadSettings.value=normalizeUploadSettings(uploadRes.uploads);if(mediaRes?.media_convert)mediaSettings.value=normalizeMediaSettings(mediaRes.media_convert);if(showHint)showSavedHint()}catch(error){if(!silent)throw error}}
const onCfgChange=()=>{normalizeConfigState();persistAutomationSettings({showHint:true,silent:true})}
const onCategoriesChange=()=>{cfg.value.categories=parseCsvInput(categoriesInput.value);onCfgChange()}
const onColorsChange=()=>{cfg.value.color_themes=parseCsvInput(colorsInput.value);onCfgChange()}
const onBlacklistChange=()=>{cfg.value.tag_blacklist=parseCsvInput(blacklistInput.value);onCfgChange()}
const poll=async()=>{try{const data=await autopilotApi.status();status.value=data;if(data.supported_timezones?.length)supportedTimezones.value=data.supported_timezones;if(!configLoaded&&data.config){applyConfig(data.config);configLoaded=true}const remoteLogs=data.logs||[];if(remoteLogs.length<logs.value.length){logs.value=remoteLogs}else if(remoteLogs.length>logs.value.length){logs.value.push(...remoteLogs.slice(logs.value.length));await nextTick();scrollLogs()}currentHour.value=new Date().getHours()}catch{}}
const togglePower=async()=>{toggling.value=true;try{if(running.value){await autopilotApi.stop()}else{logs.value=[];await persistAutomationSettings({showHint:false,silent:false});const startRes=await autopilotApi.start(buildPayload());if(startRes?.config)applyConfig(startRes.config)}await poll()}catch(error){alert('操作失败: '+(error?.message||error))}finally{toggling.value=false}}
const saveConfig=async()=>{try{await persistAutomationSettings({showHint:true,silent:false})}catch(error){alert('保存配置失败: '+(error?.message||error))}}
const scrollLogs=()=>{if(logEl.value)logEl.value.scrollTop=logEl.value.scrollHeight}
const loadStorageStats=async()=>{try{storageInfo.value=await galleryApi.storageStats()}catch{}}
const runCleanupNow=async()=>{if(cleaningUp.value)return;if(!confirm('确认立即清理？将按当前策略删除符合条件的本地文件，操作不可撤销。'))return;cleaningUp.value=true;cleanupPreview.value=null;try{const r=await galleryApi.cleanupLocal({strategy:cfg.value.storage_strategy,max_count:cfg.value.storage_max_count,keep_days:cfg.value.storage_keep_days,uploaded_only:cfg.value.storage_uploaded_only,dry_run:false});alert(`清理完成：删除 ${r.deleted} 张，剩余 ${r.remaining} 张`);await loadStorageStats()}catch(e){alert('清理失败：'+(e?.message||e))}finally{cleaningUp.value=false}}
const previewCleanup=async()=>{if(cleaningUp.value)return;cleaningUp.value=true;try{const r=await galleryApi.cleanupLocal({strategy:cfg.value.storage_strategy,max_count:cfg.value.storage_max_count,keep_days:cfg.value.storage_keep_days,uploaded_only:cfg.value.storage_uploaded_only,dry_run:true});cleanupPreview.value=r}catch(e){alert('预览失败：'+(e?.message||e))}finally{cleaningUp.value=false}}
const logLineClass=line=>{if(line.includes('失败')||line.includes('异常')||line.includes('错误'))return'log-err';if(line.includes('警告')||line.includes('上限'))return'log-warn';if(line.includes('完成')||line.includes('成功'))return'log-ok';if(line.includes('[活跃]')||line.includes('会话')||line.includes('开始'))return'log-accent';if(line.includes('[非活跃]'))return'log-inactive';return''}
const configTabs=[{key:'rhythm',label:'节奏时段'},{key:'content',label:'下载内容'},{key:'upload',label:'处理上传'},{key:'storage',label:'存储管理'}]
onMounted(async()=>{await Promise.all([poll(),loadAutomationSettings(),loadStorageStats()]);pollTimer=setInterval(poll,3000)})
onUnmounted(()=>{clearInterval(pollTimer);clearTimeout(savedHintTimer)})
</script>

<style scoped>
/* ── 布局 ── */
.ap-body {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 16px;
  align-items: start;
}
.ap-status {
  display: flex;
  flex-direction: column;
  gap: 12px;
  position: sticky;
  top: 16px;
}
.ap-config {
  min-width: 0;
}

/* ── 页头 ── */
.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.tz-clock {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.tz-name { color: var(--text-3); }
.tz-time { font-family: var(--font-ui); font-weight: 600; }
.tz-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 500;
}
.tz-badge--active { background: var(--green-dim, #d4f7e8); color: var(--green); }
.tz-badge--sleep  { background: var(--bg-hover); color: var(--text-3); }

/* ── 启停卡片 ── */
.power-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px 16px 16px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.power-btn {
  width: 100%;
  padding: 14px;
  border-radius: 8px;
  border: none;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: opacity .15s, transform .1s;
}
.power-btn:disabled { opacity: .5; cursor: not-allowed; }
.power-btn:not(:disabled):active { transform: scale(.97); }
.power-btn--off { background: var(--green); color: #fff; }
.power-btn--on  { background: var(--red, #e74c3c); color: #fff; }
.power-icon { font-size: 18px; }
.power-label { letter-spacing: .02em; }
.power-hint {
  font-size: 12px;
  color: var(--text-3);
  text-align: center;
  line-height: 1.5;
}

/* ── 统计网格 ── */
.stat-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1px;
  background: var(--border);
}
.stat-item {
  padding: 14px 16px;
  background: var(--bg-card);
  text-align: center;
}
.stat-num {
  font-size: 22px;
  font-family: var(--font-ui);
  font-weight: 600;
}
.stat-num--active { color: var(--green); }
.stat-lbl {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 3px;
}

/* ── 运行阶段 ── */
.phase-card { padding: 14px 16px; }
.phase-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.phase-label { font-size: 13px; font-weight: 500; }
.phase-mode {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-hover);
  color: var(--text-3);
}
.hour-grid {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 2px;
}
.hour-cell {
  font-size: 9px;
  text-align: center;
  padding: 4px 2px;
  border-radius: 3px;
  background: var(--bg-hover);
  color: var(--text-3);
  cursor: default;
}
.hour-cell--active   { background: var(--green); color: #fff; }
.hour-cell--inactive { background: var(--blue, #3498db); color: #fff; opacity: .65; }
.hour-cell--sleep    { background: var(--bg-hover); color: var(--text-3); }
.hour-cell--now      { background: var(--accent); color: #fff; }
.hour-legend {
  display: flex;
  gap: 12px;
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-3);
}
.legend-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 3px;
  vertical-align: middle;
}
.legend-dot--active   { background: var(--green); }
.legend-dot--inactive { background: var(--blue, #3498db); opacity: .65; }
.legend-dot--now      { background: var(--accent); }

/* ── 日志 ── */
.log-card { display: flex; flex-direction: column; }
.log-body {
  height: 260px;
  overflow-y: auto;
  padding: 10px 14px;
  font-family: var(--font-mono, monospace);
  font-size: 11.5px;
  line-height: 1.6;
}
.log-empty { color: var(--text-3); font-style: italic; }
.log-line  { white-space: pre-wrap; word-break: break-all; }
.log-err     { color: var(--red, #e74c3c); }
.log-warn    { color: var(--orange, #f39c12); }
.log-ok      { color: var(--green); }
.log-accent  { color: var(--accent); }
.log-inactive{ color: var(--text-3); }

/* ── 配置卡片 ── */
.cfg-card { display: flex; flex-direction: column; }

/* Tab 导航 */
.cfg-tabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  padding: 0 16px;
  gap: 0;
}
.cfg-tab {
  padding: 12px 16px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-3);
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  transition: color .15s, border-color .15s;
  white-space: nowrap;
}
.cfg-tab:hover { color: var(--text-1); }
.cfg-tab--active {
  color: var(--accent);
  border-bottom-color: var(--accent);
}

/* Tab 内容 */
.cfg-pane {
  padding: 20px 20px 8px;
}

/* 配置区块 */
.cfg-section { margin-bottom: 4px; }
.cfg-section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: .04em;
  margin-bottom: 12px;
}
.cfg-divider {
  height: 1px;
  background: var(--border);
  margin: 16px 0;
}
.cfg-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 20px;
}
.cfg-grid-3 {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 10px 16px;
}

/* 表单行 */
.form-row {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.form-row label {
  font-size: 12px;
  color: var(--text-2);
  font-weight: 500;
}
.form-row--full { grid-column: 1 / -1; }
.form-help {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 4px;
  line-height: 1.5;
}
.section-top-gap { margin-top: 12px; }

/* inline-note */
.inline-note {
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 4px;
  background: var(--bg-hover);
  color: var(--text-2);
}
.inline-note--muted { color: var(--text-3); }

/* 时间描述 */
.time-desc {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 模式标题 */
.mode-title { display: inline; }
.mode-title--active   { color: var(--green); }
.mode-title--inactive { color: var(--text-3); }
.mode-title-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}
.mode-hint {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 8px;
}
.mode-hint--inactive { color: var(--text-3); opacity: .8; }

/* Toggle */
.toggle {
  position: relative;
  display: inline-flex;
  width: 36px;
  height: 20px;
  flex-shrink: 0;
}
.toggle input { opacity: 0; width: 0; height: 0; }
.toggle-track {
  position: absolute;
  inset: 0;
  background: var(--border);
  border-radius: 10px;
  cursor: pointer;
  transition: background .2s;
}
.toggle input:checked + .toggle-track { background: var(--green); }
.toggle-track::after {
  content: '';
  position: absolute;
  width: 14px;
  height: 14px;
  left: 3px;
  top: 3px;
  background: #fff;
  border-radius: 50%;
  transition: transform .2s;
}
.toggle input:checked + .toggle-track::after { transform: translateX(16px); }
.toggle-label { font-size: 12px; color: var(--text-2); }
.toggle-list { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
.toggle-row {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}
.toggle-row-label { font-size: 13px; color: var(--text-1); flex: 1; }
.toggle-row--compact .toggle-row-label { font-size: 12px; }

/* preset 按钮 */
.preset-row {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}
.preset-btn {
  font-size: 11px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-hover);
  cursor: pointer;
  color: var(--text-2);
  transition: background .15s;
}
.preset-btn:hover { background: var(--border); }

/* sub-card */
.sub-card {
  background: var(--bg-hover);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px 14px;
}
.sub-card__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  margin-bottom: 6px;
}

/* checkbox */
.chk { width: 16px; height: 16px; cursor: pointer; }

/* 存储统计 */
.storage-stat-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 8px;
}
.stat-pill {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 12px;
  background: var(--bg-hover);
  border: 1px solid var(--border);
  color: var(--text-2);
}
.stat-pill--ok   { border-color: var(--green); color: var(--green); }
.stat-pill--warn { border-color: var(--orange, #f39c12); color: var(--orange, #f39c12); }
.storage-actions {
  display: flex;
  gap: 8px;
  margin: 10px 0;
  flex-wrap: wrap;
}

/* 清理预览 */
.cleanup-preview {
  margin-top: 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}
.cleanup-preview__row {
  display: flex;
  justify-content: space-between;
  padding: 8px 14px;
  font-size: 13px;
  border-bottom: 1px solid var(--border);
}
.cleanup-preview__row:last-child { border-bottom: none; }
.cleanup-preview__paths {
  padding: 10px 14px;
  background: var(--bg-hover);
  max-height: 180px;
  overflow-y: auto;
}
.path-item {
  font-size: 11px;
  font-family: var(--font-mono, monospace);
  color: var(--text-3);
  padding: 2px 0;
  word-break: break-all;
}
.text-red { color: var(--red, #e74c3c); }

/* 底部操作栏 */
.cfg-footer {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 20px;
  border-top: 1px solid var(--border);
  margin-top: auto;
}
.cfg-hint { font-size: 11px; color: var(--text-3); margin-left: auto; }
.saved-hint { font-size: 12px; color: var(--green); font-weight: 500; }

/* 策略说明 */
.strategy-note {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 10px;
  line-height: 1.5;
}

/* 响应式 */
@media (max-width: 1100px) {
  .ap-body { grid-template-columns: 1fr; }
  .ap-status { position: static; }
  .cfg-grid-3 { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 680px) {
  .cfg-grid, .cfg-grid-3 { grid-template-columns: 1fr; }
  .cfg-tabs { overflow-x: auto; }
  .header-right { flex-direction: column; align-items: flex-end; gap: 6px; }
}
</style>
