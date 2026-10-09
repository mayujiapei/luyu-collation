<template>
  <div class="workspace-container">
    <!-- 顶部工具栏 -->
    <div class="toolbar">
      <div class="tool-group">
        <span class="label">排版：</span>
        <button class="btn-toggle" :class="{ active: layoutMode === 'vertical' }" @click="layoutMode = 'vertical'">竖排</button>
        <button class="btn-toggle" :class="{ active: layoutMode === 'horizontal' }" @click="layoutMode = 'horizontal'">横排</button>
      </div>
      <div class="tool-group">
        <span class="label">字体：</span>
        <button class="btn-toggle" :class="{ active: charMode === 'simplified' }" @click="charMode = 'simplified'">简体</button>
        <button class="btn-toggle" :class="{ active: charMode === 'traditional' }" @click="charMode = 'traditional'">繁体</button>
      </div>
      <div class="tool-spacer"></div>
      <button v-if="hasAnyState" class="btn-toggle" @click="restart">重新开始</button>
    </div>

    <!-- 状态屏：加载中 / 失败 / 未提交。
         注意判据是 showsWorkspace 而不是 isReady —— 分段进行中一旦有结果到货，
         就该切到工作台显示"已出来的那部分"，而不是继续整屏转圈。 -->
    <div v-if="!store.showsWorkspace" class="state-screen">
      <template v-if="isLoading">
        <div class="state-icon spinner">⏳</div>
        <h3 class="state-title">正在调用大模型校勘…</h3>
        <p class="state-text">
          {{ store.progressText || '单次调用通常在 30 秒内返回。' }}
          <template v-if="store.progressText">长文本按句读分段提交，每段返回即显示。</template>
        </p>
      </template>

      <template v-else-if="hasError">
        <div class="state-icon">⚠️</div>
        <h3 class="state-title">校勘未能完成：{{ store.error.message }}</h3>
        <p v-if="store.error.hint" class="state-text">{{ store.error.hint }}</p>
        <p class="state-text dim">错误码：{{ store.error.code }}</p>
        <div class="state-actions">
          <button class="btn-primary" @click="restart">返回首页重试</button>
        </div>
      </template>

      <template v-else>
        <div class="state-icon">📄</div>
        <h3 class="state-title">还没有待校勘的文本</h3>
        <p class="state-text">请先在首页粘贴古籍原文并提交，校勘结果会显示在这里。</p>
        <div class="state-actions">
          <button class="btn-primary" @click="restart">去首页粘贴原文</button>
        </div>
      </template>
    </div>

    <template v-else>
      <!-- 分段进度 / 部分失败提示：有结果时也保留在工作台上方 -->
      <div v-if="store.isLoading" class="progress-banner">
        <span class="spinner-inline">⏳</span>
        正在逐段校勘…{{ store.progressText }}
        （已收到 {{ store.items.length }} 条建议，可先查看处理）
      </div>
      <div v-else-if="hasError" class="progress-banner is-error">
        ⚠️ {{ store.error.message }}
        <span v-if="store.error.hint" class="banner-hint">{{ store.error.hint }}</span>
      </div>

      <!-- 核心双栏对照区 -->
      <div class="comparison-grid">
        <!-- 左侧：原文展示区 -->
        <div class="panel source-panel">
          <div class="panel-header">
            <div class="header-left">
              <span class="title-bar"></span>
              <span class="title-text">原文</span>
            </div>
            <span class="tag-ai">待校勘原文 · {{ store.sourceText.length }} 字</span>
          </div>

          <div class="text-content" :class="layoutMode">
            <p>
              <template v-for="(segment, index) in renderedSourceSegments" :key="index">
                <span v-if="segment.type === 'text'" class="plain-text">{{ segment.content }}</span>
                <span
                  v-else
                  class="marked-word"
                  :class="[segment.type === 'note' ? 'is-note' : 'is-error', `is-${segment.status}`]"
                >
                  {{ segment.content }}
                  <span class="custom-tooltip" :class="{ 'is-vertical': layoutMode === 'vertical' }">
                    <span class="tooltip-title">{{ segment.type === 'note' ? '📖 标注' : '✏️ 校勘' }} · {{ segment.rawType }}</span>
                    <span class="tooltip-body">{{ segment.noteContent }}</span>
                  </span>
                </span>
              </template>
            </p>
          </div>
        </div>

        <!-- 右侧：AI校勘结果区 -->
        <div class="panel result-panel">
          <div class="panel-header">
            <div class="header-left">
              <span class="title-bar"></span>
              <span class="title-text">AI校勘结果</span>
              <span class="tag-count">待处理 {{ store.pendingItems.length }} 处</span>
            </div>
            <div class="header-actions">
              <button class="btn-outline btn-success" :disabled="!store.acceptableCount" @click="store.acceptAll()">
                全部采纳{{ store.acceptableCount ? `（${store.acceptableCount}）` : '' }}
              </button>
              <button class="btn-outline btn-default" :disabled="!store.pendingItems.length" @click="store.rejectAll()">
                一键还原
              </button>
            </div>
          </div>

          <!-- 结果来源与可靠性元信息（模型/耗时/被丢弃条数） -->
          <div class="result-meta">
            <span>模型 {{ store.meta.model || '未知' }}</span>
            <span>{{ (store.meta.elapsedMs / 1000).toFixed(1) }}s</span>
            <span>参校本「{{ store.meta.referenceEdition }}」</span>
            <span v-if="store.meta.droppedCount" class="meta-warn" title="模型输出未通过契约校验或被原文定位淘汰，已拦截未渲染">
              丢弃 {{ store.meta.droppedCount }} 条不合契约建议
            </span>
          </div>

          <div class="collation-list">
            <!-- 空态：模型未发现问题 -->
            <div v-if="!store.items.length" class="empty-result">
              <div class="empty-icon">✓</div>
              <p class="empty-title">本段未发现需要校勘的问题</p>
              <p class="empty-text">
{{ store.meta.droppedCount ? `另有 ${store.meta.droppedCount} 条模型建议未通过契约校验，已被拦截。` : '可以切到「文白对照」查看译文。' }}
              </p>
            </div>

            <template v-else>
              <!-- 高置信建议：参与「全部采纳」 -->
              <div
                v-for="item in renderedHighConfidence"
                :key="item.id"
                class="collation-card"
                :class="item.status"
              >
                <div class="card-head">
                  <span class="type-badge" :class="typeClass(item.type)">{{ item.type }}</span>
                  <span class="confidence" :style="{ color: confidenceColor(item.confidence) }">
                    置信度 {{ Math.round(item.confidence * 100) }}%
                  </span>
                </div>
                <div class="card-main">
                  <div class="text-block original"><span class="block-label">原文</span><span class="content">{{ item.original }}</span></div>
                  <div class="arrow">➔</div>
                  <div class="text-block suggested"><span class="block-label">建议</span><span class="content">{{ item.suggested }}</span></div>
                </div>
                <div class="card-footer">
                  <div class="reason-box">
                    <span class="reason-text">{{ item.reason }}</span>
                  </div>
                  <div class="action-btns">
                    <button class="mini-btn ok" :disabled="item.status === 'accepted'" @click="store.accept(item.id)">采纳</button>
                    <button class="mini-btn back" :disabled="item.status === 'rejected'" @click="store.reject(item.id)">还原</button>
                  </div>
                </div>
              </div>

              <!-- 低置信建议：折叠且不参与一键采纳（API.md §2） -->
              <div v-if="store.lowConfidenceItems.length" class="low-confidence-group">
                <button class="group-toggle" @click="showLowConfidence = !showLowConfidence">
                  {{ showLowConfidence ? '▾' : '▸' }} 低置信建议 {{ store.lowConfidenceItems.length }} 条
                  <span class="group-hint">置信度低于 {{ Math.round(lowConfidenceThreshold * 100) }}%，不参与「全部采纳」</span>
                </button>
                <template v-if="showLowConfidence">
                  <div
                    v-for="item in renderedLowConfidence"
                    :key="item.id"
                    class="collation-card low"
                    :class="item.status"
                  >
                    <div class="card-head">
                      <span class="type-badge" :class="typeClass(item.type)">{{ item.type }}</span>
                      <span class="confidence" :style="{ color: confidenceColor(item.confidence) }">
                        置信度 {{ Math.round(item.confidence * 100) }}%
                      </span>
                    </div>
                    <div class="card-main">
                      <div class="text-block original"><span class="block-label">原文</span><span class="content">{{ item.original }}</span></div>
                      <div class="arrow">➔</div>
                      <div class="text-block suggested"><span class="block-label">建议</span><span class="content">{{ item.suggested }}</span></div>
                    </div>
                    <div class="card-footer">
                      <div class="reason-box">
                        <span class="reason-text">{{ item.reason }}</span>
                      </div>
                      <div class="action-btns">
                        <button class="mini-btn ok" :disabled="item.status === 'accepted'" @click="store.accept(item.id)">采纳</button>
                        <button class="mini-btn back" :disabled="item.status === 'rejected'" @click="store.reject(item.id)">还原</button>
                      </div>
                    </div>
                  </div>
                </template>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 底部功能区 -->
      <div class="bottom-section">
        <div class="tab-header">
          <div class="tab-item" :class="{ active: activeTab === 'translation' }" @click="activeTab = 'translation'">文白对照</div>
          <div class="tab-item" :class="{ active: activeTab === 'timeline' }" @click="activeTab = 'timeline'">
            修改记录时间线（{{ store.timeline.length }}）
          </div>
          <div style="flex: 1"></div>
          <span v-if="exportNotice" class="export-notice" :class="exportNotice.level">{{ exportNotice.message }}</span>
          <button
            class="btn-export"
            :disabled="!store.canExport"
            :title="store.canExport ? '按文献学体例导出校勘记' : '请先采纳需要写入校勘记的条目'"
            @click="exportReport"
          >
            📥 导出校勘记
          </button>
        </div>

        <div class="tab-content">
          <div v-if="activeTab === 'translation'" class="translation-view">
            <p v-if="renderedTranslation" class="translation-text">{{ renderedTranslation }}</p>
            <p v-else class="empty-tip">本次未生成白话译文（提交时可勾选译文，或后端未返回译文）。</p>
          </div>
          <div v-else class="timeline-view">
            <div v-if="!store.timeline.length" class="empty-tip">暂无修改记录</div>
            <div v-for="(record, index) in renderedTimeline" :key="index" class="timeline-item">
              <div class="time-badge">{{ record.time }}</div>
              <div class="record-body">
                <span class="user-tag">{{ record.actor }}</span>
                <span class="action-text">{{ record.action }}</span>
                <span v-if="record.type" class="type-chip">{{ record.type }}</span>
                <span class="detail-box">“{{ record.from }}” → “{{ record.to }}”</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <TranslatorWidget />
    </template>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import OpenCC from 'opencc-js'

import TranslatorWidget from '@/components/TranslatorWidget.vue'
import { LOW_CONFIDENCE_THRESHOLD, useCollationStore } from '@/stores/collation'

const router = useRouter()
const store = useCollationStore()

const layoutMode = ref('vertical')
const charMode = ref('traditional')
const activeTab = ref('translation')
const showLowConfidence = ref(false)
const exportNotice = ref(null)

const lowConfidenceThreshold = LOW_CONFIDENCE_THRESHOLD

const converter = OpenCC.Converter({ from: 'cn', to: 'tw' })
/** 视图层统一做繁简转换；store 里始终保存原文，不因展示而改写数据 */
const convert = (text) => (charMode.value === 'simplified' ? text : converter(text ?? ''))

const isLoading = computed(() => store.isLoading)
const hasError = computed(() => store.status === 'error' && !!store.error)
const hasAnyState = computed(() => store.status !== 'idle' || store.items.length > 0)

/** 原文按建议位置切段，命中处做成可悬停的标记 */
const sourceSegments = computed(() => {
  const text = store.sourceText
  if (!text) return []

  const marks = store.items
    .filter((item) => {
      const { offset, original } = item
      return Number.isInteger(offset) && offset >= 0 && offset + original.length <= text.length
    })
    .sort((a, b) => a.offset - b.offset)

  const segments = []
  let cursor = 0
  for (const item of marks) {
    if (item.offset < cursor) continue // 与前一处重叠，跳过以免切段错乱
    if (item.offset > cursor) {
      segments.push({ type: 'text', content: text.slice(cursor, item.offset) })
    }
    segments.push({
      type: item.type === '通假' || item.type === '异文' ? 'note' : 'error',
      rawType: item.type,
      status: item.status,
      content: text.slice(item.offset, item.offset + item.original.length),
      noteContent: `${item.reason}（置信度 ${Math.round(item.confidence * 100)}%）`,
    })
    cursor = item.offset + item.original.length
  }
  if (cursor < text.length) {
    segments.push({ type: 'text', content: text.slice(cursor) })
  }
  return segments
})

const renderedSourceSegments = computed(() =>
  sourceSegments.value.map((segment) => ({
    ...segment,
    content: convert(segment.content),
    noteContent: convert(segment.noteContent),
  })),
)

function renderItems(source) {
  return source.map((item) => ({
    ...item,
    original: convert(item.original),
    suggested: convert(item.suggested),
    reason: convert(item.reason),
  }))
}

const renderedHighConfidence = computed(() => renderItems(store.highConfidenceItems))
const renderedLowConfidence = computed(() => renderItems(store.lowConfidenceItems))
const renderedTranslation = computed(() => convert(store.translation))
const renderedTimeline = computed(() =>
  store.timeline.map((record) => ({
    ...record,
    from: convert(record.from),
    to: convert(record.to),
  })),
)

const TYPE_CLASS = {
  讹字: 'type-ezi',
  衍文: 'type-yanwen',
  脱文: 'type-tuowen',
  通假: 'type-tongjia',
  异文: 'type-yiwen',
}
const typeClass = (type) => TYPE_CLASS[type] || 'type-unknown'

const confidenceColor = (score) => {
  if (score >= 0.9) return '#2e8b57'
  if (score >= LOW_CONFIDENCE_THRESHOLD) return '#daa520'
  return '#b06a2c'
}

function exportReport() {
  const result = store.exportNote()
  exportNotice.value = result.ok
    ? { level: 'ok', message: `已导出 ${result.filename}` }
    : { level: 'warn', message: result.message }
}

function restart() {
  store.reset()
  router.push('/')
}
</script>

<style scoped>
/* ================= 全局布局 ================= */
.workspace-container {
  display: flex;
  flex-direction: column;
  /* 占满「视口 − 顶栏 − main-content 上下内边距」的可用高度。
     App.vue 里顶栏 70px（含 1px 下边框）、main-content 上下内边距各 40px；
     若直接写 100vh，整个工作台会比可用区域高，工具栏被挤出首屏，
     加载/错误状态屏也会偏出可视区。 */
  height: calc(100vh - 70px - 1px - 80px);
  min-height: 480px;
  background: #f7f7f7;
}

.toolbar {
  padding: 10px 20px;
  background: #fff;
  border-bottom: 1px solid #eee;
  display: flex;
  gap: 20px;
  align-items: center;
  z-index: 20;
}

.tool-spacer { flex: 1; }

/* 分段进度 / 部分失败横条：有结果时也显示在工作台上方 */
.progress-banner {
  flex-shrink: 0;
  padding: 9px 20px;
  font-size: 13px;
  color: #7a5b1e;
  background: #fdf8ec;
  border-bottom: 1px solid #f0e6cf;
}
.progress-banner.is-error {
  color: #8a2b22;
  background: #fdf3f2;
  border-bottom-color: #f0d9d6;
}
.progress-banner .banner-hint { color: #7a5b1e; margin-left: 8px; }
.spinner-inline { display: inline-block; animation: pulse 1.6s ease-in-out infinite; }

.btn-toggle {
  padding: 4px 12px;
  border: 1px solid #ddd;
  background: #fff;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.btn-toggle.active {
  background: #8b1a1a;
  color: #fff;
  border-color: #8b1a1a;
}

/* ================= 状态屏（加载 / 失败 / 未提交） ================= */
.state-screen {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px;
  gap: 8px;
}
.state-icon { font-size: 40px; margin-bottom: 8px; }
.state-icon.spinner { animation: pulse 1.6s ease-in-out infinite; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.state-title { margin: 0; font-size: 18px; color: #2b2b2b; max-width: 640px; line-height: 1.7; }
.state-text { margin: 0; font-size: 14px; color: #666; max-width: 640px; line-height: 1.7; }
.state-text.dim { color: #999; font-family: monospace; font-size: 12px; }
.state-actions { margin-top: 16px; }
.btn-primary {
  background: #8b1a1a;
  color: #fff;
  border: none;
  padding: 10px 28px;
  border-radius: 22px;
  cursor: pointer;
  font-size: 15px;
  box-shadow: 0 4px 10px rgba(139, 26, 26, 0.25);
}
.btn-primary:hover { background: #6d1414; }

.comparison-grid {
  display: flex;
  flex: 1;
  overflow: hidden;
  gap: 1px;
  background: #e0e0e0;
}

.panel {
  background: #fff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

.source-panel { flex: 1; }
.result-panel { flex: 1; min-width: 400px; }

.panel-header {
  padding: 15px 20px;
  border-bottom: 1px solid #eee;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  z-index: 10;
  flex-shrink: 0;
}

.header-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.title-bar {
  width: 4px;
  height: 16px;
  background: #8b1a1a;
  display: inline-block;
  margin-right: 8px;
  vertical-align: middle;
}

.title-text { font-weight: bold; color: #333; }
.tag-ai { font-size: 12px; color: #999; }
.tag-count { font-size: 12px; color: #8b1a1a; background: #fdf1f1; padding: 2px 8px; border-radius: 10px; }

/* ================= 原文区 ================= */
.text-content {
  flex: 1;
  padding: 40px;
  font-family: "KaiTi", "STKaiti", serif;
  font-size: 24px;
  line-height: 2;
  position: relative;
  overflow: auto;
  height: 100%;
}

.text-content.vertical {
  writing-mode: vertical-rl;
  text-orientation: upright;
  overflow-x: auto;
  overflow-y: hidden;
  white-space: normal;
  max-height: 100%;
  text-align: left;
}

.text-content.horizontal {
  writing-mode: horizontal-tb;
  overflow-y: auto;
  overflow-x: hidden;
  white-space: normal;
}

/* 命中标记：讹/衍/脱 用红色（改动类），通假/异文 用蓝色（标注类） */
.marked-word {
  position: relative;
  cursor: help;
  display: inline-block;
  border-bottom-width: 2px;
  border-bottom-style: dashed;
}
.marked-word.is-error { color: #d9534f; border-bottom-color: #d9534f; }
.marked-word.is-note { color: #1e90ff; border-bottom-style: dashed; border-bottom-color: #1e90ff; }
.marked-word.is-accepted { color: #2e8b57; border-bottom-style: solid; border-bottom-color: #2e8b57; }
.marked-word.is-rejected { color: #999; border-bottom-color: #ccc; text-decoration: line-through; }

/* 悬停气泡 */
.custom-tooltip {
  display: none;
  position: absolute;
  z-index: 100;
  background: #fff;
  border: 1px solid #eee;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  padding: 10px;
  font-size: 14px;
  line-height: 1.5;
  white-space: normal;
  min-width: 120px;
  max-width: 300px;
  color: #333;
  border-radius: 6px;
  text-align: left;
}
.marked-word:hover .custom-tooltip { display: block; }

.text-content.vertical .marked-word .custom-tooltip.is-vertical {
  right: 100%;
  top: 50%;
  transform: translateY(-50%);
  margin-right: 15px;
  writing-mode: horizontal-tb;
}
.text-content.horizontal .marked-word .custom-tooltip {
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  margin-top: 8px;
  writing-mode: horizontal-tb;
}

.tooltip-title { display: block; font-weight: bold; color: #8b1a1a; margin-bottom: 4px; font-size: 13px; }
.tooltip-body { display: block; }

/* 滚动条美化 */
.text-content::-webkit-scrollbar { width: 6px; height: 6px; }
.text-content::-webkit-scrollbar-track { background: transparent; }
.text-content::-webkit-scrollbar-thumb { background: #555; border-radius: 3px; }
.text-content::-webkit-scrollbar-thumb:hover { background: #888; }

/* ================= 校勘结果区 ================= */
.header-actions { display: flex; gap: 10px; }

.btn-outline {
  padding: 6px 16px;
  border-radius: 4px;
  border: 1px solid #ddd;
  cursor: pointer;
  background: #fff;
  transition: all 0.2s;
}
.btn-outline:disabled { opacity: 0.45; cursor: not-allowed; }

.btn-success { border-color: #2e8b57; color: #2e8b57; }
.btn-success:hover:not(:disabled) { background: #2e8b57; color: #fff; }

.btn-default { border-color: #999; color: #666; }
.btn-default:hover:not(:disabled) { background: #999; color: #fff; }

.result-meta {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  padding: 8px 20px;
  font-size: 12px;
  color: #888;
  background: #fafafa;
  border-bottom: 1px solid #f0f0f0;
  flex-shrink: 0;
}
.result-meta .meta-warn { color: #b06a2c; }

.collation-list {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 15px;
}

.empty-result {
  text-align: center;
  padding: 50px 20px;
  color: #666;
}
.empty-icon { font-size: 32px; color: #2e8b57; margin-bottom: 12px; }
.empty-title { font-size: 16px; color: #333; margin: 0 0 8px 0; }
.empty-text { font-size: 13px; color: #888; margin: 0; line-height: 1.7; }

.collation-card {
  border: 1px solid #e6e2d8;
  border-radius: 6px;
  padding: 15px;
  background: #fffcfc;
}

.collation-card.low { background: #fbfbfb; border-style: dashed; }
.collation-card.accepted { border-color: #b7d4b0; background: #f3f9f1; opacity: 0.85; }
.collation-card.rejected { opacity: 0.6; }

.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.type-badge {
  display: inline-block;
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 10px;
  border: 1px solid currentColor;
}
.type-ezi { color: #c0392b; background: #fdf2f1; }
.type-yanwen { color: #b7791f; background: #fdf8ec; }
.type-tuowen { color: #2b6cb0; background: #eff6fd; }
.type-tongjia { color: #6b46c1; background: #f4f1fd; }
.type-yiwen { color: #2c7a7b; background: #eefaf9; }
.type-unknown { color: #777; background: #f4f4f4; }

.card-main {
  display: flex;
  align-items: center;
  gap: 15px;
  margin-bottom: 12px;
  font-family: "KaiTi", serif;
  font-size: 20px;
}

.text-block { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.block-label { font-size: 11px; color: #aaa; font-family: sans-serif; }
.text-block.original .content { color: #c0392b; }
.text-block.suggested .content { color: #2e8b57; }
.arrow { color: #ccc; font-size: 16px; }

.card-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px dashed #eee;
  padding-top: 10px;
  gap: 12px;
}

.reason-box { min-width: 0; }
.confidence { font-size: 12px; font-weight: bold; }
.reason-text { font-size: 13px; color: #666; display: block; margin-top: 4px; line-height: 1.6; }

.action-btns { display: flex; flex-shrink: 0; }

.mini-btn {
  padding: 4px 12px;
  border-radius: 4px;
  border: 1px solid #ddd;
  background: #fff;
  cursor: pointer;
  margin-left: 8px;
  font-size: 12px;
}
.mini-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.mini-btn.ok { color: #2e8b57; border-color: #2e8b57; }
.mini-btn.ok:hover:not(:disabled) { background: #2e8b57; color: #fff; }
.mini-btn.back { color: #666; }
.mini-btn.back:hover:not(:disabled) { background: #eee; }

/* 低置信折叠组 */
.low-confidence-group { display: flex; flex-direction: column; gap: 15px; }
.group-toggle {
  text-align: left;
  background: #fafafa;
  border: 1px dashed #ddd;
  border-radius: 6px;
  padding: 10px 14px;
  cursor: pointer;
  font-size: 13px;
  color: #666;
}
.group-toggle:hover { background: #f4f4f4; }
.group-hint { color: #aaa; margin-left: 8px; font-size: 12px; }

/* ================= 底部功能区 ================= */
.bottom-section {
  height: 220px;
  background: #fff;
  border-top: 1px solid #eee;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
}

.tab-header {
  display: flex;
  align-items: center;
  padding: 0 20px;
  border-bottom: 1px solid #eee;
  background: #fafafa;
}

.tab-item {
  padding: 12px 20px;
  cursor: pointer;
  font-size: 14px;
  color: #666;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.tab-item.active {
  color: #8b1a1a;
  font-weight: bold;
  border-bottom-color: #8b1a1a;
  background: #fff;
}

.tab-content {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
}

.export-notice { font-size: 12px; color: #2e8b57; margin-right: 12px; }
.export-notice.warn { color: #b06a2c; }

.btn-export {
  padding: 6px 15px;
  background: #fff;
  border: 1px solid #8b1a1a;
  color: #8b1a1a;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}
.btn-export:hover:not(:disabled) { background: #8b1a1a; color: #fff; }
.btn-export:disabled { border-color: #ddd; color: #bbb; cursor: not-allowed; }

.timeline-item {
  display: flex;
  gap: 15px;
  margin-bottom: 12px;
  font-size: 13px;
  align-items: center;
  border-left: 2px solid #eee;
  padding-left: 15px;
}

.time-badge { color: #999; font-family: monospace; width: 70px; flex-shrink: 0; }
.record-body { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.user-tag { color: #8b1a1a; font-weight: bold; }
.action-text { color: #444; }
.type-chip {
  font-size: 11px;
  color: #666;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 0 6px;
  background: #fafafa;
}
.detail-box {
  background: #f0f0f0;
  padding: 2px 6px;
  border-radius: 4px;
  color: #555;
}

.empty-tip { color: #999; font-size: 14px; }

.translation-text {
  line-height: 1.8;
  color: #444;
  font-size: 15px;
  margin: 0;
}
</style>
