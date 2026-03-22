<template>
  <div>
    <div class="page-header">
      <div class="page-hero">
        <div class="page-hero__main">
          <div>
        <h1 class="page-title">图床整理</h1>
        <div class="page-subtitle">根据本地数据库记录，自动将文件整理到正确目录，并同步元数据标签</div>
          </div>
          <div class="page-hero__badges">
            <span class="badge badge--info" v-if="activeProfile">{{ activeProfile.name }}</span>
            <span class="badge" v-if="activeProfile">{{ activeProfile.folder_pattern ? '模板目录模式' : '固定目录模式' }}</span>
            <span class="badge badge--warn" v-if="!profileReady">Profile 未就绪</span>
          </div>
        </div>
        <div class="page-workflow">
          <div
            v-for="step in pageWorkflowSteps"
            :key="step.key"
            class="page-workflow__item"
            :class="{ 'page-workflow__item--done': step.done }"
          >
            <span class="page-workflow__index">{{ step.done ? '✓' : '·' }}</span>
            <div class="page-workflow__content">
              <strong>{{ step.label }}</strong>
              <span>{{ step.text }}</span>
            </div>
          </div>
        </div>
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
        <span class="profile-dirs" v-if="activeProfile">{{ profileRuleSummary }}</span>
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
          <div class="card-desc">扫描指定目录，对比本地数据库，将位置错误的文件自动移到正确目录</div>
          <!-- 当前目录规则提示 -->
          <div class="dir-rule" v-if="activeProfile">
            <template v-if="activeProfile.folder_pattern">
              <span class="dir-rule-label">目录模板</span>
              <code class="dir-rule-code">{{ activeProfile.folder_pattern }}</code>
              <span class="hint">（路径模板非空时优先，按元数据自动分类）</span>
            </template>
            <template v-else>
              <span class="dir-rule-label">固定目录</span>
              <span class="dir-rule-item">横屏 → <code class="dir-rule-code">{{ activeProfile.folder_landscape || 'bg/pc' }}</code></span>
              <span class="dir-rule-sep">·</span>
              <span class="dir-rule-item">竖屏 → <code class="dir-rule-code">{{ activeProfile.folder_portrait || 'bg/mb' }}</code></span>
              <template v-if="activeProfile.folder_dynamic">
                <span class="dir-rule-sep">·</span>
                <span class="dir-rule-item">动态 → <code class="dir-rule-code">{{ activeProfile.folder_dynamic }}</code></span>
              </template>
            </template>
          </div>
        </div>
      </div>
      <div class="overview-facts">
        <div v-for="item in organizeOverviewFacts" :key="item.label" class="overview-fact-card">
          <span class="overview-fact-card__label">{{ item.label }}</span>
          <strong class="overview-fact-card__value">{{ item.value }}</strong>
          <span class="overview-fact-card__hint">{{ item.hint }}</span>
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

        <!-- 待移动文件列表（默认展开） -->
        <div class="target-overview" v-if="organizeTargetGroups.length > 0">
          <div class="move-list-title">本次整理的目标目录总览</div>
          <div class="target-group-list">
            <div v-for="group in organizeTargetGroups" :key="group.dir" class="target-group-item">
              <span class="target-group-item__label">目标目录</span>
              <code class="dir-rule-code">{{ group.dir }}</code>
              <span class="badge">{{ group.count }} 项</span>
            </div>
          </div>
        </div>
        <div class="move-preview" v-if="organizeResult.needsMove.length > 0">
          <div class="move-list-title">待移动文件（{{ organizeResult.needsMove.length }} 张）</div>
          <div class="move-table">
            <div class="move-table-head">
              <span>文件名</span>
              <span>当前目录 → 目标目录</span>
              <span>尺寸 / 方向</span>
            </div>
            <div v-for="item in organizeResult.needsMove" :key="item.path" class="move-row">
              <span class="move-file" :title="item.path">{{ item.filename }}</span>
              <span class="move-dirs">
                <span class="move-from">{{ item.currentDir || '/' }}</span>
                <span class="move-arrow">→</span>
                <span class="move-to">{{ item.targetDir }}</span>
              </span>
              <span class="move-hint">
                <template v-if="item.meta.width && item.meta.height">{{ item.meta.width }}×{{ item.meta.height }} · </template>
                {{ item.meta.orientation === 'portrait' ? '竖屏' : '横屏' }}
              </span>
            </div>
          </div>
        </div>

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
        <span class="browser-summary-meta">
          <span class="badge">{{ remoteFiles.length }} 张</span>
          <span class="badge badge--info">{{ selectedPaths.length }} 已选</span>
        </span>
      </summary>

      <div class="browser-body" v-if="browserOpen">
        <div class="notice notice--error" v-if="remoteError">{{ remoteError }}</div>
        <div class="notice notice--ok" v-if="remoteNotice">{{ remoteNotice }}</div>
        <div class="overview-facts overview-facts--compact">
          <div v-for="item in browserOverviewFacts" :key="item.label" class="overview-fact-card overview-fact-card--compact">
            <span class="overview-fact-card__label">{{ item.label }}</span>
            <strong class="overview-fact-card__value">{{ item.value }}</strong>
            <span class="overview-fact-card__hint">{{ item.hint }}</span>
          </div>
        </div>

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
            <div class="file-table-toolbar">
              <div class="file-table-toolbar__title">
                <strong>当前目录文件</strong>
                <span class="hint">{{ remoteQuery.dir || '/' }}</span>
              </div>
              <div class="file-table-toolbar__meta">
                <span class="badge">{{ remoteFiles.length }} 张</span>
                <span class="badge badge--info">{{ selectedPaths.length }} 已选</span>
              </div>
            </div>
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
              <div class="action-empty__lead">从左侧选择一张图片后，这里会显示“当前目录、推荐目录、最终执行目录”和完整迁移操作。</div>
              <div class="dir-bucket" v-for="b in directoryBuckets.slice(0, 8)" :key="b.path">
                <button class="bucket-path" @click="openDirectory(b.path)">{{ b.path || '/' }}</button>
                <span class="bucket-count">{{ b.count }}</span>
              </div>
              <div class="action-empty__tips">
                <span class="badge">1. 先选图片</span>
                <span class="badge">2. 确认目录</span>
                <span class="badge">3. 应用到当前或批量</span>
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
              <div class="file-workbench-hero">
                <div class="file-workbench-hero__media">
                  <img class="file-preview-img" :src="buildRemoteFileUrl(selectedFile.name)" :alt="selectedFile.name"
                    @error="$event.target.style.display='none'" />
                </div>
                <div class="file-workbench-hero__content">
                  <span class="file-workbench-hero__eyebrow">迁移工作台</span>
                  <div class="file-workbench-hero__title">{{ getFileBaseName(selectedFile.name) }}</div>
                  <div class="file-workbench-hero__path">{{ selectedFile.name }}</div>
                  <div class="file-workbench-hero__status">
                    <span
                      class="badge"
                      :class="{
                        'badge--ok': selectedFileMoveState.tone === 'ok',
                        'badge--warn': selectedFileMoveState.tone === 'warn',
                        'badge--info': selectedFileMoveState.tone === 'info',
                      }"
                    >
                      {{ selectedFileMoveState.tag }}
                    </span>
                    <span class="badge badge--info" v-if="currentTargetMatchInfo">{{ currentTargetMatchInfo.tag }}</span>
                    <span class="badge" v-if="activeProfile?.folder_pattern">模板驱动</span>
                  </div>
                  <div class="file-workbench-hero__desc">{{ selectedFileMoveState.text }}</div>
                </div>
              </div>

              <div class="file-workbench-flow">
                <div class="file-flow-card">
                  <span class="file-flow-card__label">当前所在</span>
                  <code class="file-flow-card__path">{{ selectedFileCurrentDirectory || '/' }}</code>
                  <span class="file-flow-card__hint">图床里的当前目录</span>
                </div>
                <div class="file-workbench-flow__arrow">→</div>
                <div class="file-flow-card">
                  <span class="file-flow-card__label">推荐落点</span>
                  <code class="file-flow-card__path">{{ suggestedDirectory || '/' }}</code>
                  <span class="file-flow-card__hint">{{ activeProfile?.folder_pattern ? '由路径模板展开' : '由固定目录规则计算' }}</span>
                </div>
                <div class="file-workbench-flow__arrow">→</div>
                <div class="file-flow-card file-flow-card--accent">
                  <span class="file-flow-card__label">最终执行</span>
                  <code class="file-flow-card__path">{{ effectiveTargetDirectory || '/' }}</code>
                  <span class="file-flow-card__hint">{{ targetDirectoryMatchesSuggestion ? '与推荐一致' : '已手动覆盖推荐目录' }}</span>
                </div>
              </div>

              <div class="file-workbench-tags">
                <div class="file-tag-panel">
                  <span class="hint">当前标签</span>
                  <div class="file-tag-panel__chips" v-if="selectedCurrentTags.length">
                    <span class="tag-chip" v-for="t in selectedCurrentTags" :key="'current-' + t">{{ t }}</span>
                  </div>
                  <div class="hint" v-else>当前文件还没有图床标签</div>
                </div>
                <div class="file-tag-panel">
                  <span class="hint">应用后标签</span>
                  <div class="file-tag-panel__chips" v-if="previewTags.length">
                    <span class="tag-chip" v-for="t in previewTags" :key="'preview-' + t">{{ t }}</span>
                  </div>
                  <div class="hint" v-else>还没有可写入的标签</div>
                </div>
              </div>

              <div class="reclassify-form">
                <div class="form-section-title">重新分类</div>
                <div class="file-meta-grid">
                  <div v-for="item in fileWorkbenchFacts" :key="item.label" class="file-meta-card">
                    <span class="file-meta-card__label">{{ item.label }}</span>
                    <strong class="file-meta-card__value">{{ item.value }}</strong>
                    <span class="file-meta-card__hint">{{ item.hint }}</span>
                  </div>
                </div>

                <div class="file-panel-section">
                  <div class="file-panel-section__head">
                    <span class="form-section-title" style="margin-bottom:0">元数据编辑</span>
                    <span class="hint">这些值会直接影响目录推荐和标签写入</span>
                  </div>

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
                    <div class="dir-input-wrap">
                      <input class="input input--sm" v-model="assistantForm.customTags" placeholder="逗号分隔" />
                      <button
                        class="btn btn--xs"
                        :class="{ 'dir-lock-inline-btn--active': isTemplateFieldLocked('customTags') }"
                        type="button"
                        @click="toggleTemplateFieldLock('customTags')"
                      >
                        {{ isTemplateFieldLocked('customTags') ? '标签已锁定' : '锁定标签' }}
                      </button>
                    </div>
                  </div>
                </div>

                <div class="file-panel-section file-panel-section--soft">
                  <div class="file-panel-section__head">
                    <span class="form-section-title" style="margin-bottom:0">目标目录</span>
                    <span class="hint">你可以直接输入，也可以点击下面的候选目录和层级节点</span>
                  </div>

                  <div class="form-row-h">
                    <label>目标目录</label>
                    <div class="dir-input-wrap">
                      <input class="input input--sm" :value="assistantForm.targetDirectory" @input="handleTargetDirectoryInput" placeholder="目标目录" />
                      <button class="btn btn--xs" @click="restoreSuggestedDirectory" title="重置为推荐目录">↺</button>
                    </div>
                  </div>

                  <div class="dir-preview-card">
                  <div class="dir-preview-head">
                    <span class="form-section-title" style="margin-bottom:0">项目目录预览</span>
                    <span class="badge badge--ok" v-if="activeProfile?.folder_pattern">路径模板优先</span>
                    <span class="badge" v-else>固定目录回退</span>
                  </div>
                  <div class="dir-preview-row">
                    <span class="hint">推荐目录</span>
                    <code class="dir-preview-code">{{ suggestedDirectory || '/' }}</code>
                  </div>
                  <div class="dir-preview-row">
                    <span class="hint">当前输入</span>
                    <code class="dir-preview-code">{{ normalizedTargetDirectory || '/' }}</code>
                  </div>
                  <div v-if="activeFolderPattern" class="dir-template-panel">
                    <div class="dir-template-head">
                      <span class="hint">模板解析</span>
                      <code class="dir-template-pattern">{{ activeFolderPattern }}</code>
                    </div>
                    <div class="dir-template-resolved">
                      <span class="hint">展开结果</span>
                      <code class="dir-preview-code">{{ templateResolvedDirectory || '/' }}</code>
                    </div>
                    <div class="dir-template-vars" v-if="templatePreviewEntries.length">
                      <button
                        v-for="entry in templatePreviewEntries"
                        :key="entry.key"
                        class="dir-template-chip"
                        type="button"
                        @click="applyDirectoryPreset(entry.previewPath)"
                      >
                        <span class="dir-template-chip__key">{&#123;{{ entry.key }}&#125;}</span>
                        <span class="dir-template-chip__value">{{ entry.value }}</span>
                        <span class="dir-template-chip__source">{{ entry.sourceLabel }}</span>
                        <span class="dir-template-chip__hint">{{ entry.sourceText }}</span>
                      </button>
                    </div>
                    <div class="dir-template-warning" v-if="unsupportedTemplateKeys.length">
                      <span class="hint">未识别变量</span>
                      <span class="badge badge--warn" v-for="key in unsupportedTemplateKeys" :key="key">{&#123;{{ key }}&#125;}</span>
                    </div>
                  </div>
                    <div class="dir-template-quick" v-if="activeFolderPattern && templateQuickGroups.length">
                      <div class="dir-template-quick__head">
                        <span class="hint">变量速调</span>
                        <span class="hint">点击后会立即刷新模板展开和目录建议</span>
                      </div>
                      <div class="dir-template-helper-stats">
                        <span class="badge">{{ lockedTemplateFieldSummaries.length }} 个锁定</span>
                        <span class="badge badge--info">{{ pinnedTemplateLockPresets.length }} 个常用预设</span>
                        <span class="badge">{{ regularTemplateLockPresets.length }} 个其他预设</span>
                      </div>
                      <div class="dir-template-overview">
                        <div class="dir-template-overview__row">
                          <span class="hint">当前预设</span>
                          <span class="badge badge--info">{{ activeTemplateLockPreset?.name || '手动组合' }}</span>
                        </div>
                        <div class="dir-template-overview__row" v-if="activeTemplateLockPreset">
                          <span class="hint">预设内容</span>
                          <span class="dir-template-overview__text">{{ formatTemplateLockPresetMeta(activeTemplateLockPreset) }}</span>
                        </div>
                        <div class="dir-template-overview__row">
                          <span class="hint">锁定字段</span>
                          <span class="dir-template-overview__text">
                            {{ lockedTemplateFieldSummaries.length ? lockedTemplateFieldSummaries.map((item) => item.label + ':' + item.value).join(' / ') : '当前未锁定字段' }}
                          </span>
                        </div>
                        <div class="dir-template-overview__row">
                          <span class="hint">当前目录</span>
                          <code class="dir-preview-code">{{ normalizedTargetDirectory || suggestedDirectory || '/' }}</code>
                        </div>
                      </div>
                      <div class="dir-template-toolbar">
                        <button
                          class="btn btn--xs"
                          type="button"
                          :disabled="!canSaveTemplateLockPreset"
                          @click="saveCurrentTemplateLockPreset"
                        >
                          保存当前锁定
                        </button>
                        <button
                          class="btn btn--xs"
                          type="button"
                          :disabled="!lockedTemplateFieldSummaries.length"
                          @click="clearAllTemplateFieldLocks"
                        >
                          清空锁定
                        </button>
                        <button
                          class="btn btn--xs"
                          type="button"
                          :disabled="!templateLockPresets.length"
                          @click="exportTemplateLockPresets"
                        >
                          导出预设
                        </button>
                        <button
                          class="btn btn--xs"
                          type="button"
                          @click="templateLockPresetImportOpen = !templateLockPresetImportOpen"
                        >
                          {{ templateLockPresetImportOpen ? '收起导入' : '导入预设' }}
                        </button>
                      </div>
                      <div class="dir-template-locks" v-if="lockedTemplateFieldSummaries.length">
                        <button
                          v-for="item in lockedTemplateFieldSummaries"
                          :key="'lock-' + item.field"
                          class="dir-template-lock-summary"
                          type="button"
                          @click="toggleTemplateFieldLock(item.field)"
                        >
                          <span class="dir-template-lock-summary__label">{{ item.label }}</span>
                          <span class="dir-template-lock-summary__value">{{ item.value }}</span>
                          <span class="dir-template-lock-summary__action">已锁定</span>
                        </button>
                        <button class="dir-template-lock-clear" type="button" @click="clearAllTemplateFieldLocks">
                          清空全部锁定
                        </button>
                      </div>
                      <div class="dir-template-preset-bar">
                        <input
                          class="input input--sm"
                          v-model="templateLockPresetDraftName"
                          placeholder="预设名称，可留空自动生成"
                        />
                        <input
                          class="input input--sm dir-template-preset-search"
                          v-model="templateLockPresetSearch"
                          placeholder="搜索预设名称或字段值"
                        />
                        <button
                          class="btn btn--xs"
                          type="button"
                          :disabled="!canSaveTemplateLockPreset"
                          @click="saveCurrentTemplateLockPreset"
                        >
                          保存当前锁定
                        </button>
                        <button class="btn btn--xs" type="button" @click="exportTemplateLockPresets">
                          导出预设
                        </button>
                        <button class="btn btn--xs" type="button" @click="templateLockPresetImportOpen = !templateLockPresetImportOpen">
                          {{ templateLockPresetImportOpen ? '收起导入' : '导入预设' }}
                        </button>
                      </div>
                      <div class="dir-template-preset-import" v-if="templateLockPresetImportOpen">
                        <textarea
                          class="textarea"
                          v-model="templateLockPresetImportText"
                          rows="6"
                          placeholder="粘贴导出的预设 JSON"
                        />
                        <div class="dir-template-preset-import__actions">
                          <button class="btn btn--xs" type="button" @click="importTemplateLockPresets">确认导入</button>
                          <button class="btn btn--xs" type="button" @click="templateLockPresetImportText = ''">清空文本</button>
                        </div>
                        <div class="dir-template-preset-import-preview" v-if="templateLockPresetImportText.trim()">
                          <div class="dir-template-preset-import-preview__badges" v-if="!templateLockPresetImportPreview.error">
                            <span class="badge badge--info">已识别 {{ templateLockPresetImportPreview.items.length }} 个预设</span>
                            <span class="badge" v-if="templateLockPresetImportPreview.conflicts.length">同名冲突 {{ templateLockPresetImportPreview.conflicts.length }} 个</span>
                            <span class="badge" v-else>无同名冲突</span>
                          </div>
                          <span class="hint" v-if="templateLockPresetImportPreview.error">
                            解析失败：{{ templateLockPresetImportPreview.error }}
                          </span>
                          <span class="hint" v-else-if="templateLockPresetImportPreview.conflicts.length">
                            导入后会覆盖当前 Profile 的同名预设：{{ templateLockPresetImportPreview.conflicts.join(' / ') }}
                          </span>
                          <span class="hint" v-else>
                            当前没有同名冲突，可以直接追加到当前 Profile。
                          </span>
                          <div class="dir-template-preset-import-preview__badges" v-if="templateLockPresetImportPreview.items.length">
                            <span
                              v-for="(item, index) in templateLockPresetImportPreview.items"
                              :key="'import-preview-' + item.name + '-' + index"
                              class="badge"
                            >
                              {{ item.name }}
                            </span>
                          </div>
                        </div>
                      </div>
                      <div class="dir-template-preset-order-hint" v-if="templateLockPresets.length">
                        <span class="hint">预设已按置顶优先、最近更新排序，悬停可先看目录变化。当前显示 {{ filteredTemplateLockPresets.length }} / {{ templateLockPresets.length }} 个预设。</span>
                      </div>
                      <div class="dir-template-preset-empty" v-if="!templateLockPresets.length">
                        <span class="hint">还没有锁定预设。先锁定常用字段，再点“保存当前锁定”就能在这里直接复用。</span>
                      </div>
                      <div class="dir-template-preset-empty" v-else-if="!filteredTemplateLockPresets.length">
                        <span class="hint">没有搜索到匹配的预设，可以换一个关键词，或直接保存当前锁定组合。</span>
                      </div>
                      <div class="dir-template-preset-list" v-else>
                        <div
                          v-for="preset in filteredTemplateLockPresets"
                          :key="preset.id"
                          class="dir-template-preset-card"
                        >
                          <template v-if="templateLockPresetEditingId === preset.id">
                            <div class="dir-template-preset-card__editor">
                              <input
                                class="input input--sm"
                                v-model="templateLockPresetEditingName"
                                placeholder="输入新的预设名称"
                              />
                              <div class="dir-template-preset-card__editor-actions">
                                <button class="btn btn--xs" type="button" @click="saveTemplateLockPresetRename(preset.id)">保存</button>
                                <button class="btn btn--xs" type="button" @click="cancelTemplateLockPresetRename">取消</button>
                              </div>
                            </div>
                          </template>
                          <template v-else>
                            <button
                              class="dir-template-preset-card__main"
                              type="button"
                              @mouseenter="previewTemplateLockPreset(preset)"
                              @focus="previewTemplateLockPreset(preset)"
                              @mouseleave="clearTemplateLockPresetPreview"
                              @blur="clearTemplateLockPresetPreview"
                              @click="applyTemplateLockPreset(preset)"
                            >
                              <span class="dir-template-preset-card__title">
                                {{ preset.name }}
                                <span class="badge badge--info" v-if="preset.pinned">置顶</span>
                              </span>
                              <span class="dir-template-preset-card__meta">
                                {{ formatTemplateLockPresetMeta(preset) }}
                              </span>
                              <span class="badge badge--info">点按套用</span>
                            </button>
                            <div class="dir-template-preset-card__side">
                              <button
                                class="dir-template-preset-card__action"
                                type="button"
                                @click="toggleTemplateLockPresetPin(preset.id)"
                              >
                                {{ preset.pinned ? '取消置顶' : '置顶' }}
                              </button>
                              <button
                                class="dir-template-preset-card__action"
                                type="button"
                                @click="startTemplateLockPresetRename(preset)"
                              >
                                重命名
                              </button>
                              <button
                                class="dir-template-preset-card__delete"
                                type="button"
                                @click="deleteTemplateLockPreset(preset.id)"
                              >
                                删除
                              </button>
                            </div>
                          </template>
                        </div>
                      </div>
                      <div class="dir-template-quick__list">
                        <div
                          v-for="group in templateQuickGroups"
                          :key="group.key"
                          class="dir-template-quick__group"
                        >
                          <div class="dir-template-quick__group-head">
                            <span class="dir-template-quick__label">{{ group.label }}</span>
                            <button
                              class="dir-template-lock-btn"
                              :class="{ 'dir-template-lock-btn--active': isTemplateFieldLocked(group.key) }"
                              type="button"
                              @click="toggleTemplateFieldLock(group.key)"
                            >
                              {{ isTemplateFieldLocked(group.key) ? '已锁定当前值' : '锁定当前值' }}
                            </button>
                          </div>
                          <div class="dir-template-quick__chips">
                            <button
                              v-for="option in group.options"
                              :key="group.key + '-' + option.value"
                              class="dir-template-quick__chip"
                              :class="{ 'dir-template-quick__chip--active': option.value === group.currentValue }"
                              type="button"
                              @mouseenter="previewTemplateQuickOption(group, option)"
                              @focus="previewTemplateQuickOption(group, option)"
                              @mouseleave="clearTemplateQuickPreview"
                              @blur="clearTemplateQuickPreview"
                              @click="applyTemplateQuickOption(group.key, option.value)"
                            >
                              {{ option.label }}
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                    <div class="dir-template-compare" v-if="activeFolderPattern">
                      <div class="dir-template-compare__head">
                        <span class="hint">切换预估</span>
                        <span class="badge badge--info" v-if="activeTemplatePreview">{{ activeTemplatePreview.title }}</span>
                        <span class="hint" v-else>悬停变量按钮可先看目录变化</span>
                      </div>
                      <div class="dir-template-compare__actions" v-if="activeTemplatePreview">
                        <button class="btn btn--xs" type="button" @click="applyActiveTemplatePreview">直接套用这个预估</button>
                        <button class="btn btn--xs" type="button" @click="clearTemplateQuickPreview(); clearTemplateLockPresetPreview()">清除预估</button>
                      </div>
                      <div class="dir-template-compare__row">
                        <span class="hint">当前目录</span>
                        <code class="dir-preview-code">{{ templateResolvedDirectory || '/' }}</code>
                      </div>
                      <template v-if="activeTemplatePreview">
                        <div class="dir-template-compare__row">
                          <span class="hint">预估目录</span>
                          <code class="dir-preview-code dir-preview-code--accent">{{ activeTemplatePreview.directory || '/' }}</code>
                        </div>
                        <div class="dir-template-compare__diff" v-if="activeTemplatePreview.changes.length">
                          <span class="dir-template-compare__label">命中变量变化</span>
                          <div class="dir-template-compare__chips">
                            <span
                              v-for="change in activeTemplatePreview.changes"
                              :key="change.key"
                              class="dir-template-compare__chip"
                            >
                              <span class="dir-template-compare__chip-key">{&#123;{{ change.key }}&#125;}</span>
                              <span>{{ change.from }}</span>
                              <span>→</span>
                              <strong>{{ change.to }}</strong>
                            </span>
                          </div>
                        </div>
                        <div class="hint" v-else>
                          这次速调不会影响当前模板路径，只会更新表单字段本身。
                        </div>
                      </template>
                    </div>
                  <div class="dir-preview-actions">
                    <button
                      v-if="!targetDirectoryMatchesSuggestion"
                      class="btn btn--xs"
                      type="button"
                      @click="restoreSuggestedDirectory"
                    >
                      使用推荐目录
                    </button>
                    <button
                      v-if="normalizedTargetDirectory"
                      class="btn btn--xs"
                      type="button"
                      @click="applyDirectoryPreset('')"
                    >
                      清空目录
                    </button>
                  </div>
                  <details class="dir-candidate-group" v-if="recentDirectoryCandidates.length" open>
                    <summary class="dir-candidate-group__summary">
                      <span>最近使用</span>
                      <span class="dir-candidate-group__meta">
                        <span class="badge">{{ recentDirectoryCandidates.length }}</span>
                        <button class="btn btn--xs" type="button" @click.stop.prevent="clearRecentDirectories">清空最近</button>
                      </span>
                    </summary>
                    <div class="dir-candidate-list">
                      <button
                        v-for="candidate in recentDirectoryCandidates"
                        :key="'recent-' + candidate.path"
                        class="dir-candidate-card"
                        :class="{ 'dir-candidate-card--active': candidate.path === normalizedTargetDirectory }"
                        type="button"
                        @click="applyDirectoryPreset(candidate.path)"
                      >
                        <span class="dir-candidate-card__title">{{ candidate.label }}</span>
                        <span class="dir-candidate-card__meta">
                          <span class="badge badge--info">{{ candidate.reasonTag }}</span>
                        </span>
                        <code class="dir-candidate-card__path">{{ candidate.path }}</code>
                        <span class="dir-candidate-card__desc">{{ candidate.description }}</span>
                        <span class="dir-candidate-card__why">{{ candidate.reasonText }}</span>
                      </button>
                    </div>
                  </details>
                  <details class="dir-candidate-group" v-if="primaryDirectoryCandidates.length" open>
                    <summary class="dir-candidate-group__summary">
                      <span>核心建议</span>
                      <span class="badge">{{ primaryDirectoryCandidates.length }}</span>
                    </summary>
                    <div class="dir-candidate-list">
                      <button
                        v-for="candidate in primaryDirectoryCandidates"
                        :key="'primary-' + candidate.path"
                        class="dir-candidate-card"
                        :class="{ 'dir-candidate-card--active': candidate.path === normalizedTargetDirectory }"
                        type="button"
                        @click="applyDirectoryPreset(candidate.path)"
                      >
                        <span class="dir-candidate-card__title">{{ candidate.label }}</span>
                        <span class="dir-candidate-card__meta">
                          <span class="badge badge--info">{{ candidate.reasonTag }}</span>
                        </span>
                        <code class="dir-candidate-card__path">{{ candidate.path }}</code>
                        <span class="dir-candidate-card__desc">{{ candidate.description }}</span>
                        <span class="dir-candidate-card__why">{{ candidate.reasonText }}</span>
                      </button>
                    </div>
                  </details>
                  <details class="dir-candidate-group" v-if="secondaryDirectoryCandidates.length">
                    <summary class="dir-candidate-group__summary">
                      <span>快捷候选</span>
                      <span class="badge">{{ secondaryDirectoryCandidates.length }}</span>
                    </summary>
                    <div class="dir-candidate-list">
                      <button
                        v-for="candidate in secondaryDirectoryCandidates"
                        :key="'secondary-' + candidate.path"
                        class="dir-candidate-card"
                        :class="{ 'dir-candidate-card--active': candidate.path === normalizedTargetDirectory }"
                        type="button"
                        @click="applyDirectoryPreset(candidate.path)"
                      >
                        <span class="dir-candidate-card__title">{{ candidate.label }}</span>
                        <span class="dir-candidate-card__meta">
                          <span class="badge badge--info">{{ candidate.reasonTag }}</span>
                        </span>
                        <code class="dir-candidate-card__path">{{ candidate.path }}</code>
                        <span class="dir-candidate-card__desc">{{ candidate.description }}</span>
                        <span class="dir-candidate-card__why">{{ candidate.reasonText }}</span>
                      </button>
                    </div>
                  </details>
                  <div class="dir-hit-panel" v-if="currentTargetMatchInfo">
                    <div class="dir-hit-panel__head">
                      <span class="hint">当前命中说明</span>
                      <span class="badge badge--info">{{ currentTargetMatchInfo.tag }}</span>
                    </div>
                    <div class="dir-hit-panel__text">{{ currentTargetMatchInfo.text }}</div>
                  </div>
                  <div class="dir-breadcrumb-group">
                    <span class="hint">推荐层级</span>
                    <div class="dir-breadcrumbs">
                      <button
                        v-for="item in suggestedDirectoryBreadcrumbs"
                        :key="'suggested-' + item.path"
                        class="dir-crumb"
                        type="button"
                        @click="applyDirectoryPreset(item.path)"
                      >
                        {{ item.label }}
                      </button>
                    </div>
                  </div>
                  <div class="dir-breadcrumb-group">
                    <span class="hint">当前层级</span>
                    <div class="dir-breadcrumbs">
                      <button
                        v-for="item in targetDirectoryBreadcrumbs"
                        :key="'target-' + item.path"
                        class="dir-crumb"
                        :class="{ 'dir-crumb--active': item.path === normalizedTargetDirectory }"
                        type="button"
                        @click="applyDirectoryPreset(item.path)"
                      >
                        {{ item.label }}
                      </button>
                    </div>
                  </div>
                  <div class="hint" v-if="targetDirectoryMatchesSuggestion">
                    当前目标目录与推荐目录一致，会直接按当前规则落到该路径。
                  </div>
                  <div class="hint" v-else>
                    当前目标目录已手动覆盖推荐目录，执行时将以当前输入为准。
                  </div>
                  <div class="dir-tree">
                    <div class="dir-tree-node dir-tree-node--root">
                      <button
                        class="dir-tree-label dir-tree-label--button"
                        :class="{ 'dir-tree-label--active': !normalizedTargetDirectory }"
                        type="button"
                        @click="applyDirectoryPreset('')"
                      >
                        项目根目录
                      </button>
                    </div>
                    <div v-if="targetDirectoryTreeNodes.length">
                      <div
                        v-for="node in targetDirectoryTreeNodes"
                        :key="node.path"
                        class="dir-tree-node"
                        :style="{ paddingLeft: node.depth * 18 + 'px' }"
                      >
                        <button
                          class="dir-tree-label dir-tree-label--button"
                          :class="{ 'dir-tree-label--active': node.path === normalizedTargetDirectory }"
                          type="button"
                          @click="applyDirectoryPreset(node.path)"
                        >
                          {{ node.label }}
                        </button>
                      </div>
                    </div>
                    <div v-else class="dir-tree-empty">当前未设置目标目录</div>
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

const RECENT_DIRECTORY_STORAGE_KEY = 'imgbed-manager-recent-directories'
const RECENT_DIRECTORY_LIMIT = 8
const TEMPLATE_LOCK_PRESET_STORAGE_KEY = 'imgbed-manager-template-lock-presets'
const TEMPLATE_LOCK_PRESET_LIMIT = 12
const TEMPLATE_LOCK_STATE_STORAGE_KEY = 'imgbed-manager-template-lock-states'
const TEMPLATE_LOCK_STATE_LIMIT = 12

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
const recentDirectoryHistory = ref([])
const templateQuickPreview = ref(null)
const templateFieldLocks = ref(createTemplateFieldLocks())
const templateLockPresetDraftName = ref('')
const templateLockPresetHistory = ref([])
const templateLockStateHistory = ref([])
const templateLockPresetEditingId = ref('')
const templateLockPresetEditingName = ref('')
const templateLockPresetSearch = ref('')
const templateLockPresetImportOpen = ref(false)
const templateLockPresetImportText = ref('')
const templateLockPresetPreview = ref(null)

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
// 按目标目录分组，用于展示整理后的文件夹树
const organizeTargetGroups = computed(() => {
  if (!organizeResult.value?.needsMove) return []
  const counter = new Map()
  for (const item of organizeResult.value.needsMove) {
    counter.set(item.targetDir, (counter.get(item.targetDir) || 0) + 1)
  }
  return [...counter.entries()]
    .map(([dir, count]) => ({ dir, count }))
    .sort((a, b) => a.dir.localeCompare(b.dir))
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
const activeFolderPattern = computed(() => String(activeProfile.value?.folder_pattern || '').trim())
const templatePreviewValues = computed(() => buildTemplateValues(assistantForm.value, selectedFile.value?.name || ''))
const templatePreviewSources = computed(() => buildTemplateValueSources(assistantForm.value, selectedFile.value?.name || ''))
const templatePatternKeys = computed(() => extractPatternKeys(activeFolderPattern.value))
const unsupportedTemplateKeys = computed(() => templatePatternKeys.value.filter((key) => !(key in templatePreviewValues.value)))
const templatePreviewEntries = computed(() => templatePatternKeys.value.map((key) => ({
  key,
  value: templatePreviewValues.value[key] ?? 'unknown',
  previewPath: resolveTemplateUntilKey(activeFolderPattern.value, templatePreviewValues.value, key),
  sourceLabel: templatePreviewSources.value[key]?.label || '来源未知',
  sourceText: templatePreviewSources.value[key]?.text || '当前变量没有来源说明。',
})))
const templateQuickGroups = computed(() => buildTemplateQuickGroups({
  form: assistantForm.value,
  categories: categoryOptions.value,
  colors: colorOptions.value,
}))
const lockedTemplateFieldSummaries = computed(() => buildLockedTemplateFieldSummaries(assistantForm.value, templateFieldLocks.value))
const templateLockPresets = computed(() => {
  const profileKey = activeProfile.value?.key || ''
  return templateLockPresetHistory.value
    .filter((item) => item?.profileKey && (!profileKey || item.profileKey === profileKey))
    .sort((a, b) => {
      if (Boolean(a.pinned) !== Boolean(b.pinned)) return a.pinned ? -1 : 1
      return (b.updatedAt || 0) - (a.updatedAt || 0)
    })
    .slice(0, 6)
})
const filteredTemplateLockPresets = computed(() => {
  const keyword = String(templateLockPresetSearch.value || '').trim().toLowerCase()
  if (!keyword) return templateLockPresets.value
  return templateLockPresets.value.filter((item) => {
    const name = String(item?.name || '').toLowerCase()
    const meta = String(formatTemplateLockPresetMeta(item) || '').toLowerCase()
    return name.includes(keyword) || meta.includes(keyword)
  })
})
const pinnedTemplateLockPresets = computed(() => templateLockPresets.value.filter((item) => item.pinned))
const regularTemplateLockPresets = computed(() => templateLockPresets.value.filter((item) => !item.pinned))
const canSaveTemplateLockPreset = computed(() => lockedTemplateFieldSummaries.value.length > 0)
const activeTemplatePreview = computed(() => templateLockPresetPreview.value || templateQuickPreview.value)
const activeTemplateLockPreset = computed(() => templateLockPresets.value.find((item) => isTemplateLockPresetMatch(item, assistantForm.value, templateFieldLocks.value)) || null)
const templateLockPresetImportPreview = computed(() => summarizeTemplateLockPresetImport({
  text: templateLockPresetImportText.value,
  profileKey: activeProfile.value?.key || '',
  existingPresets: templateLockPresets.value,
}))
const templateResolvedDirectory = computed(() => activeFolderPattern.value
  ? resolveFolderPattern(activeFolderPattern.value, templatePreviewValues.value)
  : '')
const fixedFallbackDirectory = computed(() => computeFixedDirectory(activeProfile.value, assistantForm.value))
const suggestedDirectory = computed(() => computeSuggestedDirectory(activeProfile.value, assistantForm.value, selectedFile.value?.name || ''))
const normalizedTargetDirectory = computed(() => normalizeRemotePath(assistantForm.value.targetDirectory))
const recentDirectoryCandidates = computed(() => {
  const profileKey = activeProfile.value?.key || ''
  return recentDirectoryHistory.value
    .filter((item) => item.path && (!profileKey || item.profileKey === profileKey))
    .slice(0, 6)
    .map((item, index) => ({
      label: index === 0 ? '刚刚使用' : `最近使用 ${index + 1}`,
      path: item.path,
      description: item.note || '来自你最近一次目录操作',
      reasonTag: '最近使用',
      reasonText: item.note || '这个目录来自你最近一次实际选择或应用。',
    }))
})
const directoryCandidates = computed(() => buildDirectoryCandidates({
  hasPattern: Boolean(activeFolderPattern.value),
  templateValues: templatePreviewValues.value,
  suggestedDirectory: suggestedDirectory.value,
  fixedDirectory: fixedFallbackDirectory.value,
}))
const primaryDirectoryCandidates = computed(() => {
  const primaryCount = fixedFallbackDirectory.value && fixedFallbackDirectory.value !== suggestedDirectory.value ? 2 : 1
  return directoryCandidates.value.slice(0, primaryCount).map((item, index) => ({
    ...item,
    reasonTag: index === 0 ? (activeFolderPattern.value ? '命中路径模板' : '命中固定规则') : '固定目录回退',
    reasonText: index === 0
      ? (activeFolderPattern.value ? '当前目录由路径模板直接展开得到。' : '当前目录由固定目录规则直接计算得到。')
      : '当模板不合适时，可以一键回退到固定目录。',
  }))
})
const secondaryDirectoryCandidates = computed(() => {
  const primaryCount = fixedFallbackDirectory.value && fixedFallbackDirectory.value !== suggestedDirectory.value ? 2 : 1
  return directoryCandidates.value.slice(primaryCount).map((item) => ({
    ...item,
    reasonTag: describeSecondaryCandidateTag(item),
    reasonText: describeSecondaryCandidateReason(item),
  }))
})
const suggestedDirectoryBreadcrumbs = computed(() => buildDirectoryBreadcrumbs(suggestedDirectory.value))
const targetDirectoryBreadcrumbs = computed(() => buildDirectoryBreadcrumbs(normalizedTargetDirectory.value))
const targetDirectoryTreeNodes = computed(() => buildDirectoryNodes(normalizedTargetDirectory.value))
const targetDirectoryMatchesSuggestion = computed(() => normalizedTargetDirectory.value === suggestedDirectory.value)
const currentTargetMatchInfo = computed(() => resolveCurrentTargetMatchInfo({
  currentPath: normalizedTargetDirectory.value,
  recentCandidates: recentDirectoryCandidates.value,
  primaryCandidates: primaryDirectoryCandidates.value,
  secondaryCandidates: secondaryDirectoryCandidates.value,
}))
const selectedFileCurrentDirectory = computed(() => normalizeRemotePath(getDirectoryName(selectedFile.value?.name || '')))
const effectiveTargetDirectory = computed(() => normalizedTargetDirectory.value || suggestedDirectory.value || '')
const selectedFileMoveState = computed(() => {
  if (!selectedFile.value) {
    return { tag: '未选择文件', text: '先从左侧选择一张图片，再决定目录和标签。', tone: 'info' }
  }
  if (!effectiveTargetDirectory.value) {
    return { tag: '等待目标目录', text: '当前还没有执行目录，先选择推荐目录或手动输入。', tone: 'warn' }
  }
  if (selectedFileCurrentDirectory.value === effectiveTargetDirectory.value) {
    return { tag: '目录已对齐', text: '当前文件已经在目标目录中，你可以只同步标签。', tone: 'ok' }
  }
  return {
    tag: '准备迁移',
    text: `将从 ${selectedFileCurrentDirectory.value || '/'} 移动到 ${effectiveTargetDirectory.value}`,
    tone: 'info',
  }
})
const fileWorkbenchFacts = computed(() => ([
  {
    label: '类型',
    value: formatTemplateLockValue('wallpaperType', assistantForm.value.wallpaperType),
    hint: activeFolderPattern.value ? '参与模板目录展开' : '参与固定目录计算',
  },
  {
    label: '方向',
    value: formatTemplateLockValue('orientation', assistantForm.value.orientation),
    hint: activeFolderPattern.value ? '参与模板目录展开' : '参与固定目录计算',
  },
  {
    label: '分类',
    value: formatTemplateLockValue('category', assistantForm.value.category),
    hint: assistantForm.value.category ? '已参与目录推荐' : '可补充后细分目录',
  },
  {
    label: '色系',
    value: formatTemplateLockValue('colorTheme', assistantForm.value.colorTheme),
    hint: assistantForm.value.colorTheme ? '可参与目录或标签推荐' : '可选字段',
  },
  {
    label: '附加标签',
    value: splitTags(assistantForm.value.customTags).join(' / ') || '未填写',
    hint: previewTags.value.length ? `整理后共 ${previewTags.value.length} 个标签` : '可选补充',
  },
]))
const profileRuleSummary = computed(() => {
  if (!activeProfile.value) return '未选择图床 Profile'
  if (activeProfile.value.folder_pattern) return `路径模板：${activeProfile.value.folder_pattern}`
  const parts = [
    `横屏：${activeProfile.value.folder_landscape || 'bg/pc'}`,
    `竖屏：${activeProfile.value.folder_portrait || 'bg/mb'}`,
  ]
  if (activeProfile.value.folder_dynamic) parts.push(`动态：${activeProfile.value.folder_dynamic}`)
  return parts.join(' / ')
})
const pageWorkflowSteps = computed(() => ([
  {
    key: 'profile',
    label: '选择图床',
    text: activeProfile.value?.name || '先选择可用 Profile',
    done: Boolean(profileReady.value),
  },
  {
    key: 'organize',
    label: '分析目录',
    text: organizeResult.value ? `已分析 ${organizeScanDir.value || '/'} 目录` : '从目录分析开始整理',
    done: Boolean(organizeResult.value),
  },
  {
    key: 'file',
    label: '处理文件',
    text: selectedFile.value ? getFileBaseName(selectedFile.value.name) : '在浏览器里挑选单个文件',
    done: Boolean(selectedFile.value),
  },
]))
const organizeOverviewFacts = computed(() => ([
  {
    label: '扫描目录',
    value: organizeScanDir.value || '/',
    hint: '支持只分析某个子目录，也可以留空扫描全部',
  },
  {
    label: '目标规则',
    value: activeProfile.value?.folder_pattern ? '路径模板优先' : '固定目录回退',
    hint: activeProfile.value ? profileRuleSummary.value : '请先选择可用 Profile',
  },
  {
    label: '本次待移动',
    value: organizeResult.value ? `${organizeResult.value.needsMove.length} 张` : '尚未分析',
    hint: organizeResult.value ? '分析后会列出所有待移动文件' : '点击“开始分析”后生成结果',
  },
]))
const browserOverviewFacts = computed(() => ([
  { label: '当前目录', value: remoteQuery.value.dir || '/', hint: remoteDirectories.value.length ? `${remoteDirectories.value.length} 个子目录` : '当前层级' },
  { label: '当前列表', value: `${remoteFiles.value.length} 张`, hint: remoteSummary.value || '当前返回的文件数量' },
  { label: '已选文件', value: `${selectedPaths.value.length} 张`, hint: selectedFile.value ? `当前焦点：${getFileBaseName(selectedFile.value.name)}` : '可勾选多张进行批量处理' },
]))
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

function createTemplateFieldLocks() {
  return { wallpaperType: false, orientation: false, category: false, colorTheme: false, customTags: false }
}

function createTemplateLockPresetId() {
  return 'preset-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8)
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

function uniqueOptionItems(items) {
  const seen = new Set()
  const result = []
  for (const item of items || []) {
    const value = String(item?.value ?? '').trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    result.push({ value, label: String(item?.label ?? value).trim() || value })
  }
  return result
}

function buildQuickOptionItems(values, { emptyLabel, limit = 6 } = {}) {
  const normalized = uniqueOptionItems(
    (values || []).map((value) => ({ value: String(value || '').trim(), label: String(value || '').trim() })),
  ).slice(0, limit)
  if (emptyLabel) normalized.push({ value: '', label: emptyLabel })
  return normalized
}

function buildTemplateQuickGroups({ form, categories, colors }) {
  return [
    {
      key: 'wallpaperType',
      label: '类型',
      currentValue: form.wallpaperType || 'static',
      options: [
        { value: 'static', label: '静态图' },
        { value: 'dynamic', label: '动态图' },
      ],
    },
    {
      key: 'orientation',
      label: '方向',
      currentValue: form.orientation || 'landscape',
      options: [
        { value: 'landscape', label: '横图' },
        { value: 'portrait', label: '竖图' },
      ],
    },
    {
      key: 'category',
      label: '分类',
      currentValue: form.category || '',
      options: buildQuickOptionItems([form.category, ...(categories || [])], { emptyLabel: '清空分类' }),
    },
    {
      key: 'colorTheme',
      label: '颜色',
      currentValue: form.colorTheme || '',
      options: buildQuickOptionItems([form.colorTheme, ...(colors || [])], { emptyLabel: '清空颜色' }),
    },
  ].filter((group) => {
    if (!Array.isArray(group.options) || !group.options.length) return false
    if (group.key === 'wallpaperType' || group.key === 'orientation') return true
    return group.options.some((option) => option.value)
  })
}

function formatTemplateLockValue(field, value) {
  if (field === 'wallpaperType') return value === 'dynamic' ? '动态图' : '静态图'
  if (field === 'orientation') return ORIENTATION_LABELS[value] || ORIENTATION_LABELS.unknown
  if (field === 'category') return value || '空分类'
  if (field === 'colorTheme') return value || '空颜色'
  if (field === 'customTags') return value || '空标签'
  return value || '空值'
}

function buildLockedTemplateFieldSummaries(form, locks) {
  return Object.entries(locks || {})
    .filter(([, locked]) => locked)
    .map(([field]) => ({
      field,
      label: getTemplateQuickFieldLabel(field),
      value: formatTemplateLockValue(field, form?.[field]),
    }))
}

function buildTemplateLockPresetName(summaries) {
  const list = Array.isArray(summaries) ? summaries : []
  if (!list.length) return '锁定组合'
  return list
    .slice(0, 3)
    .map((item) => `${item.label}:${item.value}`)
    .join(' / ')
}

function normalizeTemplateLockPresetName(value, fallback) {
  return String(value || '').trim() || String(fallback || '').trim() || '锁定组合'
}

function extractLockedTemplateValues(form, locks) {
  return Object.entries(locks || {}).reduce((acc, [field, locked]) => {
    if (!locked) return acc
    acc[field] = form?.[field] ?? ''
    return acc
  }, {})
}

function isTemplateLockPresetMatch(preset, form, locks) {
  const presetLocks = { ...createTemplateFieldLocks(), ...(preset?.locks || {}) }
  const currentLocks = { ...createTemplateFieldLocks(), ...(locks || {}) }
  for (const field of Object.keys(currentLocks)) {
    if (Boolean(presetLocks[field]) !== Boolean(currentLocks[field])) return false
    if (presetLocks[field] && String(preset?.values?.[field] ?? '') !== String(form?.[field] ?? '')) return false
  }
  return true
}

function formatTemplateLockPresetMeta(preset) {
  return Object.entries(preset?.values || {})
    .map(([field, value]) => `${getTemplateQuickFieldLabel(field)}:${formatTemplateLockValue(field, value)}`)
    .join(' / ')
}

function summarizeTemplateLockPresetImport({ text, profileKey, existingPresets }) {
  const rawText = String(text || '').trim()
  if (!rawText) return { items: [], conflicts: [], error: '' }
  try {
    const parsed = JSON.parse(rawText)
    const sourceList = Array.isArray(parsed) ? parsed : Array.isArray(parsed?.presets) ? parsed.presets : []
    const existingNames = new Set(
      (existingPresets || [])
        .map((item) => normalizeTemplateLockPresetName(item?.name, ''))
        .filter(Boolean),
    )
    const items = sourceList
      .map((item) => normalizeImportedTemplateLockPreset(item, profileKey))
      .filter((item) => Object.keys(item.values || {}).length > 0)
      .map((item) => ({
        name: item.name,
        meta: formatTemplateLockPresetMeta(item),
        pinned: Boolean(item.pinned),
      }))
    const conflicts = [...new Set(items.filter((item) => existingNames.has(item.name)).map((item) => item.name))]
    return { items, conflicts, error: '' }
  } catch (err) {
    return { items: [], conflicts: [], error: err?.message || String(err) }
  }
}

function normalizeImportedTemplateLockPreset(rawPreset, profileKey) {
  const locks = { ...createTemplateFieldLocks(), ...(rawPreset?.locks || {}) }
  const values = extractLockedTemplateValues(rawPreset?.values || {}, locks)
  const name = normalizeTemplateLockPresetName(rawPreset?.name, buildTemplateLockPresetName(
    buildLockedTemplateFieldSummaries(values, locks),
  ))
  return {
    id: createTemplateLockPresetId(),
    profileKey,
    name,
    values,
    locks,
    pinned: Boolean(rawPreset?.pinned),
    updatedAt: Date.now(),
  }
}

function applyAssistantLocks(nextForm, currentForm, locks) {
  const merged = { ...(nextForm || {}) }
  for (const [field, locked] of Object.entries(locks || {})) {
    if (!locked) continue
    if (Object.prototype.hasOwnProperty.call(currentForm || {}, field)) {
      merged[field] = currentForm[field]
    }
  }
  return merged
}

function getTemplateQuickFieldLabel(field) {
  if (field === 'wallpaperType') return '类型'
  if (field === 'orientation') return '方向'
  if (field === 'category') return '分类'
  if (field === 'colorTheme') return '颜色'
  if (field === 'customTags') return '标签'
  return field
}

function getTemplateQuickOptionLabel(field, value) {
  if (field === 'wallpaperType') return value === 'dynamic' ? '动态图' : '静态图'
  if (field === 'orientation') return value === 'portrait' ? '竖图' : '横图'
  if (field === 'category') return value || '清空分类'
  if (field === 'colorTheme') return value || '清空颜色'
  return value || '空值'
}

function buildTemplateQuickPreviewState({ field, value, pattern, form, fileName, profile }) {
  const nextForm = { ...form, [field]: value }
  const nextValues = buildTemplateValues(nextForm, fileName)
  const nextDirectory = computeSuggestedDirectory(profile, nextForm, fileName)
  const keys = extractPatternKeys(pattern)
  const changes = keys
    .filter((key) => templatePreviewValues.value[key] !== nextValues[key])
    .map((key) => ({
      key,
      from: templatePreviewValues.value[key] ?? 'unknown',
      to: nextValues[key] ?? 'unknown',
    }))

  return {
    field,
    value,
    title: `${getTemplateQuickFieldLabel(field)} → ${getTemplateQuickOptionLabel(field, value)}`,
    directory: nextDirectory,
    mode: 'quick',
    changes,
  }
}

function buildTemplateLockPresetPreviewState({ preset, pattern, form, fileName, profile }) {
  const nextLocks = { ...createTemplateFieldLocks(), ...(preset?.locks || {}) }
  const nextForm = { ...form }
  for (const [field, locked] of Object.entries(nextLocks)) {
    if (!locked) continue
    nextForm[field] = preset?.values?.[field] ?? nextForm[field]
  }
  const nextValues = buildTemplateValues(nextForm, fileName)
  const keys = extractPatternKeys(pattern)
  const changes = keys
    .filter((key) => templatePreviewValues.value[key] !== nextValues[key])
    .map((key) => ({
      key,
      from: templatePreviewValues.value[key] ?? 'unknown',
      to: nextValues[key] ?? 'unknown',
    }))
  return {
    title: `预设预估 → ${preset?.name || '未命名预设'}`,
    directory: computeSuggestedDirectory(profile, nextForm, fileName),
    mode: 'preset',
    preset,
    changes,
  }
}

function buildTemplateValueSources(form, fileName) {
  const customTags = splitTags(form.customTags).filter(Boolean)
  const resourceName = getFileNameWithoutExt(fileName || '')
  const hasFileName = Boolean(resourceName)
  return {
    type: {
      label: '来自类型字段',
      text: `取自“类型”字段，当前按${form.wallpaperType === 'dynamic' ? '动态图' : '静态图'}展开。`,
    },
    orientation: {
      label: '来自方向字段',
      text: `取自“方向”字段，当前按${ORIENTATION_LABELS[form.orientation] || ORIENTATION_LABELS.unknown}展开。`,
    },
    category: {
      label: '来自分类字段',
      text: form.category ? `取自“分类”字段，当前值为 ${form.category}。` : '“分类”为空，已回退为 uncategorized。',
    },
    type_id: {
      label: '来自分类字段',
      text: form.category ? `沿用“分类”字段作为 type_id，当前值为 ${form.category}。` : '“分类”为空，type_id 已回退为 unknown-type。',
    },
    color: {
      label: '来自颜色字段',
      text: form.colorTheme ? `取自“颜色”字段，当前值为 ${form.colorTheme}。` : '“颜色”为空，已回退为 uncolored。',
    },
    color_id: {
      label: '来自颜色字段',
      text: form.colorTheme ? `沿用“颜色”字段作为 color_id，当前值为 ${form.colorTheme}。` : '“颜色”为空，color_id 已回退为 unknown-color。',
    },
    color_theme: {
      label: '来自颜色字段',
      text: form.colorTheme ? `取自“颜色”字段，当前值为 ${form.colorTheme}。` : '“颜色”为空，color_theme 已回退为 uncolored。',
    },
    tag: {
      label: '来自自定义标签',
      text: customTags[0] ? `取自第一个自定义标签，当前值为 ${customTags[0]}。` : '未填写自定义标签，已回退为 untagged。',
    },
    primary_tag: {
      label: '来自自定义标签',
      text: customTags[0] ? `与 tag 一致，取自第一个自定义标签 ${customTags[0]}。` : '未填写自定义标签，primary_tag 已回退为 untagged。',
    },
    tags: {
      label: '来自自定义标签',
      text: customTags.length ? `由前 ${Math.min(customTags.length, 5)} 个自定义标签拼接生成。` : '未填写自定义标签，tags 已回退为 untagged。',
    },
    originality: {
      label: '固定值',
      text: '当前实现固定写入 original，用于保持模板变量完整。',
    },
    resource_id: {
      label: '来自文件名',
      text: hasFileName ? `取自当前文件名去扩展名后的结果：${resourceName}。` : '当前未选中文件，已回退为 unknown-resource。',
    },
    filename: {
      label: '来自文件名',
      text: hasFileName ? `取自当前文件名去扩展名后的结果：${resourceName}。` : '当前未选中文件，已回退为 unknown-resource。',
    },
    year: {
      label: '来自当前日期',
      text: '按当前系统日期实时生成年份。',
    },
    month: {
      label: '来自当前日期',
      text: '按当前系统日期实时生成两位月份。',
    },
    date: {
      label: '来自当前日期',
      text: '按当前系统日期实时生成 YYYYMMDD。',
    },
  }
}

function safePathSegment(value, fallback) {
  const cleaned = String(value || '').replace(/[^\w\u4e00-\u9fa5\-_.]/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '').trim()
  return cleaned || (fallback || 'unknown')
}

function splitDirectorySegments(path) {
  return normalizeRemotePath(path).split('/').filter(Boolean)
}

function buildDirectoryBreadcrumbs(path) {
  const segments = splitDirectorySegments(path)
  const breadcrumbs = [{ label: '项目根目录', path: '' }]
  let currentPath = ''
  for (const segment of segments) {
    currentPath = currentPath ? `${currentPath}/${segment}` : segment
    breadcrumbs.push({ label: segment, path: currentPath })
  }
  return breadcrumbs
}

function buildDirectoryNodes(path) {
  return buildDirectoryBreadcrumbs(path)
    .slice(1)
    .map((item, index) => ({ ...item, depth: index + 1 }))
}

function describeSecondaryCandidateTag(item) {
  const label = String(item?.label || '')
  if (label.includes('标签')) return '标签维度'
  if (label.includes('颜色')) return '颜色维度'
  if (label.includes('方向')) return '方向维度'
  if (label.includes('分类')) return '分类维度'
  if (label.includes('类型')) return '类型维度'
  return '快捷候选'
}

function describeSecondaryCandidateReason(item) {
  const label = String(item?.label || '')
  if (label.includes('标签')) return '适合你想先按标签归档，再看具体分类的场景。'
  if (label.includes('颜色')) return '适合需要按色系统一整理素材时快速切换。'
  if (label.includes('方向')) return '适合先区分横竖屏，再进入分类目录。'
  if (label.includes('分类')) return '适合优先保持分类结构稳定，再细分其它维度。'
  if (label.includes('类型')) return '适合先区分静态图和动态图，再继续整理。'
  return '这是基于当前元数据生成的备选目录方案。'
}

function resolveCurrentTargetMatchInfo({ currentPath, recentCandidates, primaryCandidates, secondaryCandidates }) {
  const normalized = normalizeRemotePath(currentPath)
  if (!normalized) {
    return { tag: '未设置目录', text: '当前还没有目录落点，执行时不会同步目录。' }
  }

  const recent = (recentCandidates || []).find((item) => item.path === normalized)
  if (recent) return { tag: recent.reasonTag, text: recent.reasonText }

  const primary = (primaryCandidates || []).find((item) => item.path === normalized)
  if (primary) return { tag: primary.reasonTag, text: primary.reasonText }

  const secondary = (secondaryCandidates || []).find((item) => item.path === normalized)
  if (secondary) return { tag: secondary.reasonTag, text: secondary.reasonText }

  return { tag: '手动覆盖', text: '当前目录不是推荐候选之一，属于你手动输入或单独调整的结果。' }
}

function loadRecentDirectories() {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(RECENT_DIRECTORY_STORAGE_KEY)
    const parsed = JSON.parse(raw || '[]')
    return Array.isArray(parsed) ? parsed.filter((item) => item?.path) : []
  } catch {
    return []
  }
}

function saveRecentDirectories(items) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(
    RECENT_DIRECTORY_STORAGE_KEY,
    JSON.stringify(Array.isArray(items) ? items.slice(0, RECENT_DIRECTORY_LIMIT) : []),
  )
}

function rememberRecentDirectory(path, note = '来自你最近一次目录操作') {
  const normalized = normalizeRemotePath(path)
  const profileKey = activeProfile.value?.key || ''
  if (!normalized) return
  const next = [
    { path: normalized, profileKey, note, updatedAt: Date.now() },
    ...recentDirectoryHistory.value.filter((item) => !(item.path === normalized && item.profileKey === profileKey)),
  ].slice(0, RECENT_DIRECTORY_LIMIT)
  recentDirectoryHistory.value = next
  saveRecentDirectories(next)
}

function clearRecentDirectories() {
  recentDirectoryHistory.value = []
  saveRecentDirectories([])
}

function loadTemplateLockPresets() {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(TEMPLATE_LOCK_PRESET_STORAGE_KEY)
    const parsed = JSON.parse(raw || '[]')
    return Array.isArray(parsed) ? parsed.filter((item) => item?.id && item?.profileKey) : []
  } catch {
    return []
  }
}

function saveTemplateLockPresets(items) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(
    TEMPLATE_LOCK_PRESET_STORAGE_KEY,
    JSON.stringify(Array.isArray(items) ? items.slice(0, TEMPLATE_LOCK_PRESET_LIMIT) : []),
  )
}

function loadTemplateLockStates() {
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(TEMPLATE_LOCK_STATE_STORAGE_KEY)
    const parsed = JSON.parse(raw || '[]')
    return Array.isArray(parsed) ? parsed.filter((item) => item?.profileKey) : []
  } catch {
    return []
  }
}

function saveTemplateLockStates(items) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(
    TEMPLATE_LOCK_STATE_STORAGE_KEY,
    JSON.stringify(Array.isArray(items) ? items.slice(0, TEMPLATE_LOCK_STATE_LIMIT) : []),
  )
}

function buildDirectoryCandidates({ hasPattern, templateValues, suggestedDirectory, fixedDirectory }) {
  const values = templateValues || {}
  const candidates = []
  const seen = new Set()
  const pushCandidate = (label, path, description, group = 'secondary') => {
    const normalized = normalizeRemotePath(path)
    if (!normalized || seen.has(normalized)) return
    seen.add(normalized)
    candidates.push({ label, path: normalized, description, group })
  }

  pushCandidate(hasPattern ? '模板推荐' : '当前推荐', suggestedDirectory, hasPattern ? '按当前路径模板展开' : '按当前固定目录规则')
  if (fixedDirectory && fixedDirectory !== suggestedDirectory) {
    pushCandidate('固定目录', fixedDirectory, '忽略路径模板，直接回退固定目录')
  }

  pushCandidate('类型 / 方向 / 分类', `wallpaper/${values.type}/${values.orientation}/${values.category}`, '适合按当前维度细分目录')
  pushCandidate('类型 / 分类', `wallpaper/${values.type}/${values.category}`, '保留类型和分类两层')
  pushCandidate('方向 / 分类', `wallpaper/${values.orientation}/${values.category}`, '更适合只区分横竖屏')
  pushCandidate('分类优先', `wallpaper/${values.category}`, '只按分类归档')

  if (values.primary_tag && values.primary_tag !== 'untagged') {
    pushCandidate('标签优先', `wallpaper/${values.type}/${values.primary_tag}/${values.category}`, '适合以标签作为主目录')
  }
  if (values.color && values.color !== 'uncolored') {
    pushCandidate('颜色优先', `wallpaper/${values.type}/${values.color}/${values.category}`, '适合按颜色归档')
  }

  return candidates
}

function extractPatternKeys(pattern) {
  const matches = String(pattern || '').match(/\{([a-z_]+)\}/gi) || []
  const seen = new Set()
  return matches
    .map((item) => item.slice(1, -1))
    .filter((key) => {
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
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

function buildTemplateValues(form, fileName) {
  const now = new Date()
  const customTags = splitTags(form.customTags).map((tag) => safePathSegment(tag, '')).filter(Boolean)
  const resourceName = safePathSegment(getFileNameWithoutExt(fileName || ''), 'unknown-resource')
  return {
    type: form.wallpaperType === 'dynamic' ? 'dynamic' : 'static',
    orientation: form.orientation || 'unknown',
    category: safePathSegment(form.category, 'uncategorized'),
    type_id: safePathSegment(form.category, 'unknown-type'),
    color: safePathSegment(form.colorTheme, 'uncolored'),
    color_id: safePathSegment(form.colorTheme, 'unknown-color'),
    color_theme: safePathSegment(form.colorTheme, 'uncolored'),
    tag: customTags[0] || 'untagged',
    primary_tag: customTags[0] || 'untagged',
    tags: customTags.slice(0, 5).join('_') || 'untagged',
    originality: 'original',
    resource_id: resourceName,
    filename: resourceName,
    year: String(now.getFullYear()),
    month: (now.getMonth() + 1 + '').padStart(2, '0'),
    date: now.getFullYear() + (now.getMonth() + 1 + '').padStart(2, '0') + (now.getDate() + '').padStart(2, '0'),
  }
}

function resolveFolderPattern(pattern, values) {
  return normalizeRemotePath(
    String(pattern || '').replace(/\{([a-z_]+)\}/gi, (_, key) => values[key] ?? 'unknown'),
  )
}

function resolveTemplateUntilKey(pattern, values, stopKey) {
  const segments = String(pattern || '').split('/').filter(Boolean)
  const resolvedSegments = []
  for (const segment of segments) {
    const resolved = segment.replace(/\{([a-z_]+)\}/gi, (_, key) => values[key] ?? 'unknown')
    resolvedSegments.push(resolved)
    if (segment.includes(`{${stopKey}}`)) {
      break
    }
  }
  return normalizeRemotePath(resolvedSegments.join('/'))
}

function computeFixedDirectory(profile, form) {
  const p = profile || {}
  if (form.wallpaperType === 'dynamic') return normalizeRemotePath(p.folder_dynamic || 'bg/dynamic')
  if (form.orientation === 'portrait') return normalizeRemotePath(p.folder_portrait || 'bg/mb')
  return normalizeRemotePath(p.folder_landscape || 'bg/pc')
}

function computeSuggestedDirectory(profile, form, fileName) {
  const p = profile || {}
  const folderPattern = String(p.folder_pattern || '').trim()
  if (folderPattern) {
    return resolveFolderPattern(folderPattern, buildTemplateValues(form, fileName))
  }
  return computeFixedDirectory(p, form)
}

function restoreSuggestedDirectory() {
  setTargetDirectoryValue(suggestedDirectory.value, false)
}

function handleTargetDirectoryInput(event) {
  assistantForm.value.targetDirectory = event.target.value
  targetDirectoryManuallyEdited.value = true
}

function setTargetDirectoryValue(path, manual = true) {
  assistantForm.value.targetDirectory = normalizeRemotePath(path)
  targetDirectoryManuallyEdited.value = manual
}

function applyDirectoryPreset(path) {
  setTargetDirectoryValue(path, true)
  rememberRecentDirectory(path, '来自候选目录或层级点击')
}

function previewTemplateQuickOption(group, option) {
  if (!activeFolderPattern.value || !group?.key) return
  if (option?.value === group.currentValue) {
    templateQuickPreview.value = null
    return
  }
  templateQuickPreview.value = buildTemplateQuickPreviewState({
    field: group.key,
    value: option?.value ?? '',
    pattern: activeFolderPattern.value,
    form: assistantForm.value,
    fileName: selectedFile.value?.name || '',
    profile: activeProfile.value,
  })
}

function clearTemplateQuickPreview() {
  templateQuickPreview.value = null
}

function previewTemplateLockPreset(preset) {
  if (!activeFolderPattern.value || !preset) return
  templateLockPresetPreview.value = buildTemplateLockPresetPreviewState({
    preset,
    pattern: activeFolderPattern.value,
    form: assistantForm.value,
    fileName: selectedFile.value?.name || '',
    profile: activeProfile.value,
  })
}

function clearTemplateLockPresetPreview() {
  templateLockPresetPreview.value = null
}

function applyActiveTemplatePreview() {
  const preview = activeTemplatePreview.value
  if (!preview) return
  if (preview.mode === 'preset' && preview.preset) {
    applyTemplateLockPreset(preview.preset)
    return
  }
  if (preview.mode === 'quick') {
    applyTemplateQuickOption(preview.field, preview.value)
  }
}

function isTemplateFieldLocked(field) {
  return Boolean(templateFieldLocks.value?.[field])
}

function toggleTemplateFieldLock(field) {
  templateFieldLocks.value[field] = !templateFieldLocks.value[field]
}

function clearAllTemplateFieldLocks() {
  templateFieldLocks.value = createTemplateFieldLocks()
  clearTemplateQuickPreview()
  clearTemplateLockPresetPreview()
}

function saveCurrentTemplateLockPreset() {
  if (!canSaveTemplateLockPreset.value) return
  const profileKey = activeProfile.value?.key || ''
  if (!profileKey) return
  const summaries = lockedTemplateFieldSummaries.value
  const name = normalizeTemplateLockPresetName(templateLockPresetDraftName.value, buildTemplateLockPresetName(summaries))
  const values = extractLockedTemplateValues(assistantForm.value, templateFieldLocks.value)
  const locks = { ...templateFieldLocks.value }
  const existingIndex = templateLockPresetHistory.value.findIndex((item) => item.profileKey === profileKey && item.name === name)
  const nextItem = {
    id: existingIndex >= 0 ? templateLockPresetHistory.value[existingIndex].id : createTemplateLockPresetId(),
    profileKey,
    name,
    values,
    locks,
    pinned: existingIndex >= 0 ? Boolean(templateLockPresetHistory.value[existingIndex].pinned) : false,
    updatedAt: Date.now(),
  }
  const next = [...templateLockPresetHistory.value]
  if (existingIndex >= 0) next.splice(existingIndex, 1)
  templateLockPresetHistory.value = [nextItem, ...next].slice(0, TEMPLATE_LOCK_PRESET_LIMIT)
  saveTemplateLockPresets(templateLockPresetHistory.value)
  templateLockPresetDraftName.value = ''
}

function applyTemplateLockPreset(preset) {
  if (!preset) return
  templateFieldLocks.value = { ...createTemplateFieldLocks(), ...(preset.locks || {}) }
  const nextForm = { ...assistantForm.value }
  for (const [field, locked] of Object.entries(templateFieldLocks.value)) {
    if (!locked) continue
    nextForm[field] = preset.values?.[field] ?? nextForm[field]
  }
  assistantForm.value = nextForm
  clearTemplateQuickPreview()
  clearTemplateLockPresetPreview()
}

function toggleTemplateLockPresetPin(presetId) {
  templateLockPresetHistory.value = templateLockPresetHistory.value.map((item) => {
    if (item.id !== presetId) return item
    return { ...item, pinned: !item.pinned, updatedAt: Date.now() }
  })
  saveTemplateLockPresets(templateLockPresetHistory.value)
}

function startTemplateLockPresetRename(preset) {
  templateLockPresetEditingId.value = preset?.id || ''
  templateLockPresetEditingName.value = preset?.name || ''
}

function cancelTemplateLockPresetRename() {
  templateLockPresetEditingId.value = ''
  templateLockPresetEditingName.value = ''
}

function saveTemplateLockPresetRename(presetId) {
  const target = templateLockPresetHistory.value.find((item) => item.id === presetId)
  if (!target) {
    cancelTemplateLockPresetRename()
    return
  }
  const nextName = normalizeTemplateLockPresetName(templateLockPresetEditingName.value, target.name)
  templateLockPresetHistory.value = templateLockPresetHistory.value.map((item) => (
    item.id === presetId ? { ...item, name: nextName, updatedAt: Date.now() } : item
  ))
  saveTemplateLockPresets(templateLockPresetHistory.value)
  cancelTemplateLockPresetRename()
}

function deleteTemplateLockPreset(presetId) {
  templateLockPresetHistory.value = templateLockPresetHistory.value.filter((item) => item.id !== presetId)
  saveTemplateLockPresets(templateLockPresetHistory.value)
  if (templateLockPresetEditingId.value === presetId) cancelTemplateLockPresetRename()
}

async function exportTemplateLockPresets() {
  const profileKey = activeProfile.value?.key || ''
  if (!profileKey) return
  const payload = {
    version: 1,
    exportedAt: Date.now(),
    profileKey,
    presets: templateLockPresets.value.map((item) => ({
      name: item.name,
      values: item.values,
      locks: item.locks,
      pinned: Boolean(item.pinned),
    })),
  }
  const text = JSON.stringify(payload, null, 2)
  templateLockPresetImportText.value = text
  try {
    await navigator.clipboard?.writeText(text)
    globalNotice.value = '当前 Profile 的锁定预设已复制到剪贴板。'
  } catch {
    globalNotice.value = '已生成预设导出内容，剪贴板写入失败，可直接从下方文本框复制。'
  }
  globalError.value = ''
  templateLockPresetImportOpen.value = true
}

function importTemplateLockPresets() {
  const profileKey = activeProfile.value?.key || ''
  if (!profileKey) return
  try {
    const parsed = JSON.parse(String(templateLockPresetImportText.value || '').trim() || '[]')
    const sourceList = Array.isArray(parsed) ? parsed : Array.isArray(parsed?.presets) ? parsed.presets : []
    const imported = sourceList
      .map((item) => normalizeImportedTemplateLockPreset(item, profileKey))
      .filter((item) => Object.keys(item.values || {}).length > 0)
    if (!imported.length) {
      globalError.value = '没有识别到可导入的锁定预设，请检查 JSON 内容。'
      globalNotice.value = ''
      return
    }
    const existingOthers = templateLockPresetHistory.value.filter((item) => item.profileKey !== profileKey)
    const existingCurrent = templateLockPresetHistory.value.filter((preset) => preset.profileKey === profileKey)
    const mergedCurrent = [...imported]
    for (const item of existingCurrent) {
      if (!mergedCurrent.some((preset) => preset.name === item.name)) mergedCurrent.push(item)
    }
    templateLockPresetHistory.value = [...mergedCurrent.slice(0, TEMPLATE_LOCK_PRESET_LIMIT), ...existingOthers]
    saveTemplateLockPresets(templateLockPresetHistory.value)
    globalNotice.value = `已导入 ${imported.length} 个锁定预设。`
    globalError.value = ''
  } catch (err) {
    globalError.value = '导入预设失败：' + (err?.message || err)
    globalNotice.value = ''
  }
}

function persistCurrentTemplateLockState() {
  const profileKey = activeProfile.value?.key || ''
  if (!profileKey) return
  const nextItem = {
    profileKey,
    locks: { ...templateFieldLocks.value },
    values: extractLockedTemplateValues(assistantForm.value, templateFieldLocks.value),
    updatedAt: Date.now(),
  }
  const next = [
    nextItem,
    ...templateLockStateHistory.value.filter((item) => item.profileKey !== profileKey),
  ].slice(0, TEMPLATE_LOCK_STATE_LIMIT)
  templateLockStateHistory.value = next
  saveTemplateLockStates(next)
}

function restoreTemplateLockState(profileKey) {
  const key = String(profileKey || '')
  if (!key) {
    templateFieldLocks.value = createTemplateFieldLocks()
    return
  }
  const cached = templateLockStateHistory.value.find((item) => item.profileKey === key)
  if (!cached) {
    templateFieldLocks.value = createTemplateFieldLocks()
    return
  }
  templateFieldLocks.value = { ...createTemplateFieldLocks(), ...(cached.locks || {}) }
  const nextForm = { ...assistantForm.value }
  for (const [field, locked] of Object.entries(templateFieldLocks.value)) {
    if (!locked) continue
    nextForm[field] = cached.values?.[field] ?? nextForm[field]
  }
  assistantForm.value = nextForm
}

function applyTemplateQuickOption(field, value) {
  assistantForm.value[field] = value
  clearTemplateQuickPreview()
  clearTemplateLockPresetPreview()
}

function syncAssistantDirectory(force) {
  if (!targetDirectoryManuallyEdited.value || force) {
    setTargetDirectoryValue(suggestedDirectory.value, false)
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
  assistantForm.value = applyAssistantLocks(
    { wallpaperType: typeTag, orientation: orientTag, category, colorTheme, customTags: customTags.join(', '), targetDirectory: assistantForm.value.targetDirectory },
    assistantForm.value,
    templateFieldLocks.value,
  )
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
        path,
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
  if (successCount > 0) {
    const targetDirs = [...new Set((organizeResult.value?.needsMove || []).map((item) => item.targetDir).filter(Boolean))]
    for (const dir of targetDirs) {
      rememberRecentDirectory(dir, '来自批量整理执行')
    }
  }
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
    if (reclassifyOptions.value.syncDirectory && normalizedTargetDirectory.value) {
      rememberRecentDirectory(normalizedTargetDirectory.value, '来自当前文件应用')
    }
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
    if (reclassifyOptions.value.syncDirectory && normalizedTargetDirectory.value) {
      rememberRecentDirectory(normalizedTargetDirectory.value, '来自批量应用')
    }
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
    activeProfile.value?.key,
    assistantForm.value.wallpaperType,
    assistantForm.value.orientation,
    assistantForm.value.category,
    assistantForm.value.colorTheme,
    assistantForm.value.customTags,
    templateFieldLocks.value.wallpaperType,
    templateFieldLocks.value.orientation,
    templateFieldLocks.value.category,
    templateFieldLocks.value.colorTheme,
    templateFieldLocks.value.customTags,
    activeProfile.value?.folder_pattern,
    activeProfile.value?.folder_landscape,
    activeProfile.value?.folder_portrait,
    activeProfile.value?.folder_dynamic,
    selectedFile.value?.name,
  ],
  () => {
    syncAssistantDirectory()
    persistCurrentTemplateLockState()
  },
)

watch(activeKey, async () => {
  restoreTemplateLockState(activeKey.value)
  resetRemoteState()
  if (activeProfile.value?.key && profileReady.value && browserOpen.value) {
    await loadRemoteCapabilities()
    await loadRemoteList()
  }
})

onMounted(async () => {
  recentDirectoryHistory.value = loadRecentDirectories()
  templateLockPresetHistory.value = loadTemplateLockPresets()
  templateLockStateHistory.value = loadTemplateLockStates()
  await Promise.all([loadSettings(), loadGalleryMeta()])
  restoreTemplateLockState(activeKey.value)
  syncAssistantDirectory(true)
})
</script>

<style scoped>
/* 页面头部 */
.page-header { margin-bottom: 14px; }
.page-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
  gap: 16px;
  padding: 20px 22px;
  border-radius: 22px;
  border: 1px solid color-mix(in srgb, var(--border) 80%, #4f8ef7 20%);
  background:
    radial-gradient(circle at top right, rgba(79, 142, 247, 0.18), transparent 30%),
    linear-gradient(135deg, rgba(255, 255, 255, 0.72), rgba(255, 255, 255, 0.3)),
    var(--bg-card);
  box-shadow: 0 18px 36px rgba(15, 23, 42, 0.08);
}
.page-hero__main {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.page-hero__badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.page-workflow {
  display: grid;
  gap: 10px;
}
.page-workflow__item {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-card) 76%, white 24%);
}
.page-workflow__item--done {
  border-color: color-mix(in srgb, var(--primary, #4f8ef7) 48%, var(--border) 52%);
  background: color-mix(in srgb, var(--primary-light, #eef4ff) 72%, white 28%);
}
.page-workflow__index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 999px;
  background: var(--bg-subtle, #f4f4f4);
  color: var(--primary, #4f8ef7);
  font-weight: 700;
  flex-shrink: 0;
}
.page-workflow__content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.page-workflow__content strong {
  font-size: 13px;
  color: var(--text);
}
.page-workflow__content span {
  font-size: 12px;
  line-height: 1.5;
  color: var(--text-muted);
}
/* ── Profile 栏 ── */
.profile-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 16px;
  margin-bottom: 14px;
  flex-wrap: wrap;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}
.profile-dirs { font-size: 12px; color: var(--text-muted); background: var(--bg-subtle, #f4f4f4); padding: 6px 10px; border-radius: 999px; }
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
.overview-facts {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 14px;
}
.overview-facts--compact { margin-bottom: 12px; }
.overview-fact-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background:
    linear-gradient(180deg, rgba(79, 142, 247, 0.05), transparent 38%),
    color-mix(in srgb, var(--bg-card) 78%, white 22%);
}
.overview-fact-card--compact { padding: 12px; }
.overview-fact-card__label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 700;
  color: var(--text-muted);
}
.overview-fact-card__value {
  font-size: 15px;
  color: var(--text);
  line-height: 1.4;
  word-break: break-word;
}
.overview-fact-card__hint {
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-muted);
}

/* ── 操作行 ── */
.action-row { display: flex; align-items: center; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; }
.input--fill { flex: 1; min-width: 160px; }

/* ── 内联消息 ── */
.inline-msg { font-size: 13px; padding: 6px 10px; border-radius: 5px; margin-bottom: 10px; }
.inline-msg--error { background: #fdecea; color: #c0392b; }
.inline-msg--ok    { background: #eafaf1; color: #1e8449; }

/* ── 分析结果 ── */
.result-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: 16px; }
.result-cell {
  text-align: center;
  padding: 16px 12px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background:
    linear-gradient(180deg, rgba(79, 142, 247, 0.05), transparent 45%),
    color-mix(in srgb, var(--bg-card) 80%, white 20%);
}
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
.move-list-title { font-size: 13px; font-weight: 600; color: var(--text); padding: 4px 0 8px; }
.move-table { border: 1px solid var(--border); border-radius: 14px; overflow: hidden; font-size: 12px; max-height: 320px; overflow-y: auto; background: var(--bg-card); }
.move-table-head { display: grid; grid-template-columns: 1.8fr 3fr 1.2fr; background: var(--bg-subtle, #f4f4f4); padding: 6px 12px; font-weight: 600; color: var(--text-muted); gap: 8px; position: sticky; top: 0; }
.move-row { display: grid; grid-template-columns: 1.8fr 3fr 1.2fr; padding: 7px 12px; border-top: 1px solid var(--border); align-items: center; gap: 8px; }
.move-row:hover { background: var(--bg-hover, #f8f8f8); }
.move-file { font-family: monospace; font-size: 11px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.move-dirs { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; min-width: 0; }
.move-from { color: var(--text-muted); font-size: 11px; font-family: monospace; white-space: nowrap; }
.move-arrow { color: var(--text-muted); font-size: 11px; flex-shrink: 0; }
.move-to { color: #1e8449; font-weight: 600; font-size: 11px; font-family: monospace; white-space: nowrap; }
.move-hint { font-size: 11px; color: var(--text-muted); white-space: nowrap; }
.target-overview { margin-bottom: 14px; }
.target-group-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
.target-group-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--border);
  border-radius: 16px;
  background:
    linear-gradient(180deg, rgba(79, 142, 247, 0.05), transparent 42%),
    color-mix(in srgb, var(--bg-card) 78%, white 22%);
}
.target-group-item__label {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
}

/* ── 执行行 ── */
.execute-row { display: flex; flex-direction: column; gap: 8px; }
.btn--lg { padding: 10px 24px; font-size: 15px; font-weight: 600; }
.progress-wrap { height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--primary, #4f8ef7); border-radius: 2px; transition: width 0.2s ease; }

/* ── 标签同步 ── */
.tag-sync-result { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
.badge { display: inline-flex; align-items: center; font-size: 12px; padding: 2px 8px; border-radius: 10px; background: var(--bg-subtle, #eee); color: var(--text-muted); }
.badge--info { background: var(--primary-light, #eef4ff); color: var(--primary, #4f8ef7); }
.badge--ok   { background: #eafaf1; color: #1e8449; }
.badge--warn { background: #fef9e7; color: #b7950b; }

/* ── 文件浏览器折叠 ── */
.browser-section { background: var(--bg-card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin-bottom: 14px; }
.browser-summary { display: flex; align-items: center; gap: 10px; padding: 14px 20px; cursor: pointer; font-size: 15px; font-weight: 600; user-select: none; list-style: none; }
.browser-summary::-webkit-details-marker { display: none; }
.browser-summary::before { content: '▸'; font-size: 12px; transition: transform 0.2s; margin-right: 2px; }
details[open] .browser-summary::before { transform: rotate(90deg); }
.browser-summary-hint { font-size: 13px; font-weight: 400; color: var(--text-muted); }
.browser-summary-meta {
  display: inline-flex;
  gap: 6px;
  margin-left: auto;
  flex-wrap: wrap;
}
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

.batch-bar { display: flex; align-items: center; gap: 8px; padding: 10px 14px; background: var(--primary-light, #eef4ff); border: 1px solid var(--primary, #4f8ef7); border-radius: 14px; margin-bottom: 10px; flex-wrap: wrap; }
.batch-count { font-size: 13px; font-weight: 500; }
.list-status { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }

.browser-main { display: grid; grid-template-columns: minmax(0, 1fr) 420px; gap: 18px; align-items: start; }

/* ── 文件列表 ── */
.file-table-wrap { border: 1px solid var(--border); border-radius: 16px; overflow: hidden; background: var(--bg-card); box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04); }
.file-table-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-card) 72%, white 28%);
}
.file-table-toolbar__title {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.file-table-toolbar__title strong {
  font-size: 13px;
  color: var(--text);
}
.file-table-toolbar__meta {
  display: inline-flex;
  gap: 6px;
  flex-wrap: wrap;
}
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
.action-panel { position: sticky; top: 16px; max-height: calc(100vh - 32px); overflow-y: auto; }
.action-empty {
  background:
    radial-gradient(circle at top right, rgba(79, 142, 247, 0.1), transparent 32%),
    var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 18px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.06);
}
.action-empty__lead {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
  margin-bottom: 12px;
}
.action-empty__tips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.empty-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 10px; }
.dir-bucket { display: flex; justify-content: space-between; align-items: center; padding: 4px 0; border-bottom: 1px solid var(--border); }
.dir-bucket:last-of-type { border-bottom: none; }
.bucket-path { font-size: 12px; color: var(--primary, #4f8ef7); cursor: pointer; background: none; border: none; text-align: left; padding: 0; }
.bucket-count { font-size: 12px; color: var(--text-muted); }
.adv-ops { margin-top: 12px; }
.adv-btns { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
.adv-hint { margin-top: 6px; }

.file-panel {
  background:
    linear-gradient(180deg, rgba(79, 142, 247, 0.08), transparent 22%),
    linear-gradient(135deg, rgba(17, 24, 39, 0.02), transparent 45%),
    var(--bg-card);
  border: 1px solid color-mix(in srgb, var(--border) 82%, #4f8ef7 18%);
  border-radius: 20px;
  padding: 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: 0 18px 38px rgba(15, 23, 42, 0.08);
}
.file-preview-img { width: 100%; max-height: 220px; border-radius: 14px; object-fit: contain; background: var(--bg-subtle, #f4f4f4); }
.file-workbench-hero {
  display: grid;
  grid-template-columns: 132px minmax(0, 1fr);
  gap: 14px;
  align-items: start;
}
.file-workbench-hero__media {
  padding: 8px;
  border-radius: 18px;
  background: color-mix(in srgb, var(--bg-card) 70%, white 30%);
  border: 1px solid var(--border);
}
.file-workbench-hero__content {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.file-workbench-hero__eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--primary, #4f8ef7);
}
.file-workbench-hero__title {
  font-size: 18px;
  font-weight: 700;
  line-height: 1.25;
  color: var(--text);
  word-break: break-word;
}
.file-workbench-hero__path {
  font-size: 12px;
  color: var(--text-muted);
  word-break: break-all;
}
.file-workbench-hero__status {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.file-workbench-hero__desc {
  font-size: 13px;
  line-height: 1.6;
  color: var(--text);
}
.file-workbench-flow {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 10px;
  align-items: stretch;
}
.file-workbench-flow__arrow {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  color: var(--primary, #4f8ef7);
}
.file-flow-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-card) 72%, white 28%);
}
.file-flow-card--accent {
  border-color: color-mix(in srgb, var(--primary, #4f8ef7) 50%, var(--border) 50%);
  background: color-mix(in srgb, var(--primary-light, #eef4ff) 68%, white 32%);
}
.file-flow-card__label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.file-flow-card__path {
  display: block;
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
  word-break: break-all;
}
.file-flow-card__hint {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}
.file-workbench-tags {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.file-tag-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-card) 74%, white 26%);
}
.file-tag-panel__chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.reclassify-form { display: flex; flex-direction: column; gap: 12px; }
.form-section-title { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-muted); margin-bottom: 2px; }
.form-row-h { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.form-row-h > label { min-width: 56px; font-size: 12px; color: var(--text-muted); flex-shrink: 0; }
.file-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.file-meta-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  border-radius: 14px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-card) 76%, white 24%);
}
.file-meta-card__label {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.file-meta-card__value {
  font-size: 14px;
  line-height: 1.4;
  color: var(--text);
  word-break: break-word;
}
.file-meta-card__hint {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.5;
}
.file-panel-section {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid var(--border);
  background: color-mix(in srgb, var(--bg-card) 74%, white 26%);
}
.file-panel-section--soft {
  background:
    linear-gradient(180deg, rgba(79, 142, 247, 0.05), transparent 28%),
    color-mix(in srgb, var(--bg-card) 80%, white 20%);
}
.file-panel-section__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.seg-group { display: flex; border: 1px solid var(--border); border-radius: 5px; overflow: hidden; }
.seg-btn { flex: 1; padding: 4px 10px; font-size: 12px; background: var(--bg-card); border: none; cursor: pointer; color: var(--text); transition: background 0.12s; white-space: nowrap; }
.seg-btn + .seg-btn { border-left: 1px solid var(--border); }
.seg-btn:hover { background: var(--bg-hover, #f0f0f0); }
.seg-btn--active { background: var(--primary, #4f8ef7); color: #fff; }

.preview-box { background: var(--bg-subtle, #f4f4f4); border-radius: 5px; padding: 6px 10px; display: flex; gap: 4px; flex-wrap: wrap; align-items: center; font-size: 12px; }
.dir-input-wrap { display: flex; align-items: center; gap: 4px; flex: 1; }
.dir-preview-card {
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 12px;
  background: color-mix(in srgb, var(--bg-card) 72%, white 28%);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.dir-preview-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.dir-preview-row { display: flex; flex-direction: column; gap: 4px; }
.dir-template-panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dir-template-head,
.dir-template-resolved,
.dir-template-warning {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dir-template-pattern {
  display: block;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--bg-subtle, #f4f4f4);
  border: 1px dashed var(--border);
  font-size: 12px;
  word-break: break-all;
}
.dir-template-vars {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
}
.dir-template-chip {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 8px 10px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--bg-subtle, #f4f4f4);
  cursor: pointer;
  font-size: 12px;
  text-align: left;
}
.dir-template-chip:hover { background: var(--bg-hover, #f0f0f0); }
.dir-template-chip__key { color: var(--text-muted); }
.dir-template-chip__value { color: var(--text); font-weight: 600; }
.dir-template-chip__source {
  color: var(--primary, #4f8ef7);
  font-size: 11px;
}
.dir-template-chip__hint {
  color: var(--text-muted);
  font-size: 11px;
  line-height: 1.4;
}
.dir-template-quick {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 2px;
}
.dir-template-quick__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.dir-template-helper-stats {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-overview {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-card);
}
.dir-template-overview__row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dir-template-overview__text {
  font-size: 12px;
  color: var(--text);
  line-height: 1.5;
}
.dir-template-toolbar {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-locks {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-lock-summary {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--primary, #4f8ef7);
  background: var(--primary-light, #eef4ff);
  color: var(--primary, #4f8ef7);
  cursor: pointer;
  font-size: 11px;
}
.dir-template-lock-summary__label { font-weight: 600; }
.dir-template-lock-summary__value { color: var(--text); }
.dir-template-lock-summary__action { color: var(--primary, #4f8ef7); }
.dir-template-lock-clear {
  border: 1px dashed var(--border);
  background: var(--bg-card);
  color: var(--text-muted);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 11px;
  cursor: pointer;
}
.dir-template-lock-clear:hover { background: var(--bg-hover, #f0f0f0); }
.dir-template-preset-bar {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-preset-bar .input {
  flex: 1;
  min-width: 180px;
}
.dir-template-preset-search {
  min-width: 220px;
}
.dir-template-preset-import {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 8px 10px;
  border: 1px dashed var(--border);
  border-radius: 10px;
  background: var(--bg-card);
}
.dir-template-preset-import .textarea {
  width: 100%;
  min-height: 110px;
  resize: vertical;
}
.dir-template-preset-import__actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-preset-import-preview {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--bg-card) 76%, white 24%);
}
.dir-template-preset-import-preview__badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-preset-order-hint {
  display: flex;
  align-items: center;
  gap: 6px;
}
.dir-template-preset-empty {
  display: flex;
  align-items: center;
  min-height: 42px;
  padding: 8px 10px;
  border: 1px dashed var(--border);
  border-radius: 10px;
  background: var(--bg-card);
}
.dir-template-preset-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 8px;
}
.dir-template-preset-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dir-template-preset-card__editor {
  flex: 1;
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-card);
  flex-wrap: wrap;
}
.dir-template-preset-card__editor .input {
  flex: 1;
  min-width: 180px;
}
.dir-template-preset-card__editor-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-preset-card__main {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--bg-card);
  text-align: left;
  cursor: pointer;
}
.dir-template-preset-card__main:hover { background: var(--bg-hover, #f0f0f0); }
.dir-template-preset-card__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}
.dir-template-preset-card__meta {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
}
.dir-template-preset-card__side {
  display: flex;
  flex-direction: row;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-preset-card__action,
.dir-template-preset-card__delete {
  border: 1px solid var(--border);
  background: var(--bg-card);
  border-radius: 10px;
  padding: 5px 10px;
  font-size: 11px;
  cursor: pointer;
}
.dir-template-preset-card__action {
  color: var(--text);
}
.dir-template-preset-card__action:hover { background: var(--bg-hover, #f0f0f0); }
.dir-template-preset-card__delete {
  color: #c0392b;
}
.dir-template-preset-card__delete:hover { background: #fdecea; }
.dir-template-quick__list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dir-template-quick__group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dir-template-quick__group-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.dir-template-quick__label {
  font-size: 12px;
  color: var(--text-muted);
}
.dir-template-lock-btn {
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text-muted);
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 11px;
  cursor: pointer;
}
.dir-template-lock-btn:hover { background: var(--bg-hover, #f0f0f0); }
.dir-template-lock-btn--active {
  border-color: var(--primary, #4f8ef7);
  background: var(--primary-light, #eef4ff);
  color: var(--primary, #4f8ef7);
}
.dir-template-quick__chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-quick__chip {
  border: 1px solid var(--border);
  background: var(--bg-subtle, #f4f4f4);
  color: var(--text);
  border-radius: 999px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
.dir-template-quick__chip:hover { background: var(--bg-hover, #f0f0f0); }
.dir-template-quick__chip--active {
  background: var(--primary-light, #eef4ff);
  border-color: var(--primary, #4f8ef7);
  color: var(--primary, #4f8ef7);
}
.dir-template-compare {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-card);
}
.dir-template-compare__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.dir-template-compare__actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-compare__row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dir-template-compare__diff {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dir-template-compare__label {
  font-size: 12px;
  color: var(--text-muted);
}
.dir-template-compare__chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.dir-template-compare__chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: var(--bg-subtle, #f4f4f4);
  font-size: 12px;
  color: var(--text);
}
.dir-template-compare__chip-key { color: var(--text-muted); }
.dir-preview-code--accent {
  border-color: var(--primary, #4f8ef7);
  background: var(--primary-light, #eef4ff);
}
.dir-lock-inline-btn--active {
  background: var(--primary-light, #eef4ff);
  border-color: var(--primary, #4f8ef7);
  color: var(--primary, #4f8ef7);
}
.dir-preview-actions { display: flex; gap: 6px; flex-wrap: wrap; }
.dir-candidate-group {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--bg-card);
  overflow: hidden;
}
.dir-candidate-group + .dir-candidate-group { margin-top: 2px; }
.dir-candidate-group__summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px 10px;
  cursor: pointer;
  list-style: none;
  user-select: none;
  font-size: 12px;
  font-weight: 600;
}
.dir-candidate-group__summary::-webkit-details-marker { display: none; }
.dir-candidate-group__summary::before {
  content: '▸';
  font-size: 11px;
  color: var(--text-muted);
  margin-right: 6px;
}
.dir-candidate-group[open] .dir-candidate-group__summary::before { content: '▾'; }
.dir-candidate-group__meta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}
.dir-candidate-panel { display: flex; flex-direction: column; gap: 6px; }
.dir-candidate-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.dir-candidate-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 8px;
  padding: 0 10px 10px;
}
.dir-candidate-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--bg-card);
  cursor: pointer;
}
.dir-candidate-card:hover { background: var(--bg-hover, #f0f0f0); }
.dir-candidate-card--active {
  background: var(--primary-light, #eef4ff);
  border-color: var(--primary, #4f8ef7);
}
.dir-candidate-card__title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}
.dir-candidate-card__meta { display: flex; align-items: center; gap: 6px; }
.dir-candidate-card__path {
  font-size: 11px;
  color: var(--primary, #4f8ef7);
  word-break: break-all;
}
.dir-candidate-card__desc {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
}
.dir-candidate-card__why {
  font-size: 11px;
  color: var(--text);
  line-height: 1.4;
}
.dir-hit-panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 10px;
  background: var(--bg-card);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dir-hit-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.dir-hit-panel__text {
  font-size: 12px;
  color: var(--text);
  line-height: 1.5;
}
.dir-breadcrumb-group { display: flex; flex-direction: column; gap: 4px; }
.dir-breadcrumbs { display: flex; gap: 6px; flex-wrap: wrap; }
.dir-crumb {
  border: 1px solid var(--border);
  background: var(--bg-card);
  color: var(--text);
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 12px;
  cursor: pointer;
}
.dir-crumb:hover { background: var(--bg-hover, #f0f0f0); }
.dir-crumb--active {
  background: var(--primary-light, #eef4ff);
  border-color: var(--primary, #4f8ef7);
  color: var(--primary, #4f8ef7);
}
.dir-preview-code {
  display: block;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  font-size: 12px;
  word-break: break-all;
}
.dir-tree {
  border: 1px dashed var(--border);
  border-radius: 8px;
  padding: 8px;
  background: var(--bg-card);
}
.dir-tree-node {
  position: relative;
  min-height: 24px;
  display: flex;
  align-items: center;
}
.dir-tree-node:not(.dir-tree-node--root)::before {
  content: '';
  position: absolute;
  left: 6px;
  top: 50%;
  width: 10px;
  border-top: 1px solid var(--border);
}
.dir-tree-node--root { padding-left: 0 !important; }
.dir-tree-label {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--bg-subtle, #f4f4f4);
  border: 1px solid var(--border);
  font-size: 12px;
}
.dir-tree-label--button {
  cursor: pointer;
  color: var(--text);
}
.dir-tree-label--button:hover { background: var(--bg-hover, #f0f0f0); }
.dir-tree-label--active {
  background: var(--primary-light, #eef4ff);
  border-color: var(--primary, #4f8ef7);
  color: var(--primary, #4f8ef7);
}
.dir-tree-empty {
  padding: 4px 0 0;
  font-size: 12px;
  color: var(--text-muted);
}
.sync-options {
  display: flex;
  gap: 12px;
  padding: 8px 10px;
  border-radius: 12px;
  background: color-mix(in srgb, var(--bg-card) 72%, white 28%);
  border: 1px solid var(--border);
  flex-wrap: wrap;
}
.apply-btns { display: flex; gap: 8px; margin-top: 4px; flex-wrap: wrap; }

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

@media (max-width: 1200px) {
  .page-hero { grid-template-columns: 1fr; }
  .overview-facts { grid-template-columns: 1fr; }
  .browser-main { grid-template-columns: 1fr; }
  .action-panel { position: static; max-height: none; }
}

@media (max-width: 900px) {
  .browser-summary {
    flex-wrap: wrap;
  }
  .browser-summary-meta {
    margin-left: 0;
  }
  .file-table-toolbar {
    flex-direction: column;
    align-items: flex-start;
  }
  .file-workbench-hero { grid-template-columns: 1fr; }
  .file-workbench-flow {
    grid-template-columns: 1fr;
  }
  .file-workbench-flow__arrow {
    min-height: 20px;
    transform: rotate(90deg);
  }
  .file-workbench-tags,
  .file-meta-grid {
    grid-template-columns: 1fr;
  }
  .form-row-h {
    flex-direction: column;
    align-items: stretch;
  }
  .form-row-h > label {
    min-width: 0;
  }
}
</style>
