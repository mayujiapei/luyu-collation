/**
 * 校勘状态仓库（TECH_DESIGN §3）。
 *
 * 主链路的唯一数据来源：原文、AI 建议、译文、决策状态、修改时间线全部在这里，
 * 组件只读这里的数据，不再自带任何演示数据。
 *
 * 长文本走**分段流水线**（PRD §4）：按句读切段、限量并发、每段返回即刷新 items，
 * 于是"校勘一部分就出来一部分"。接口契约不变，仍是多次普通 /collate 调用。
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { ApiError, NETWORK_ERROR, collate as collateRequest } from '@/api/client'
import { buildCollationNote, downloadTextFile, noteFilename } from '@/utils/collationNote'
import {
  MAX_CONCURRENCY,
  mergeCollationItems,
  rebaseItems,
  splitTextIntoChunks,
} from '@/utils/textChunks'

/** 置信度低于此值的建议折叠为「低置信建议」，且不参与「全部采纳」（API.md §2）。 */
export const LOW_CONFIDENCE_THRESHOLD = 0.7

/** 单次**调用**的文本上限（PRD §5），与后端 MAX_TEXT_LEN 一致。 */
export const MAX_TEXT_LENGTH = 5000

export const ALL_CHECK_TYPES = ['讹字', '衍文', '脱文', '通假', '异文']

export const DEFAULT_REFERENCE_EDITION = '通行本'

/** 草稿键：仅存浏览器本地，刷新/切页不丢工作；不是服务端持久化（PRD §4「明确不做」）。 */
const DRAFT_KEY = 'guji:collation-draft:v1'

/** 错误码 -> 给用户的处理建议（message 用后端返回的那条，这里只补「怎么办」）。 */
const ERROR_HINTS = {
  // 这个码同时覆盖「缺密钥」与「上游不可用（密钥无效/余额不足/5xx）」，
  // 所以建议要把两种情况都点到，不能只说「去填密钥」——否则余额不足时用户会白找一遍
  PROVIDER_MISCONFIGURED: '请确认 .env 中的 LLM_API_KEY 已填写且有效，并确认模型账号的余额或额度充足（可参考 .env.example）。',
  LLM_TIMEOUT: '请稍后重试，或缩短待校勘文本。',
  LLM_BAD_JSON: '大模型输出未通过契约校验，已整条拦截、未渲染脏数据。请重试。',
  RATE_LIMITED: '请稍候再试。',
  [NETWORK_ERROR]: '请确认后端已启动，且 VITE_API_BASE 指向正确的地址。',
  TEXT_TOO_LONG: '请分段提交。',
  INVALID_REQUEST: '请检查输入后重试。',
  INTERNAL_ERROR: '请查看后端日志定位原因。',
}

function nowTime(date = new Date()) {
  const pad = (value) => String(value).padStart(2, '0')
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}

function toErrorInfo(error) {
  if (error instanceof ApiError) {
    return {
      code: error.code,
      message: error.message,
      hint: ERROR_HINTS[error.code] || '',
    }
  }
  return {
    code: 'UNKNOWN',
    message: error?.message || '发生未知错误',
    hint: '',
  }
}

/** 读本地草稿；任何异常都当作没有草稿，不能因为缓存坏了就打不开页面。 */
function readDraft() {
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY)
    if (!raw) return null
    const draft = JSON.parse(raw)
    return draft && typeof draft.sourceText === 'string' ? draft : null
  } catch {
    return null
  }
}

export const useCollationStore = defineStore('collation', () => {
  const draft = readDraft()

  /** 运行代次号：并发分段与「重新开始/再次提交」之间的竞态保护（见 runChunks）。 */
  let activeRun = 0

  // --- state ---
  const sourceText = ref(draft?.sourceText ?? '')
  /** 每条：{ id, type, original, suggested, reason, confidence, offset, status } */
  const items = ref(draft?.items ?? [])
  const translation = ref(draft?.translation ?? '')
  const meta = ref(
    draft?.meta ?? {
      requestId: '',
      model: '',
      elapsedMs: 0,
      droppedCount: 0,
      referenceEdition: DEFAULT_REFERENCE_EDITION,
      checkTypes: [...ALL_CHECK_TYPES],
      produceTranslation: true,
      chunkCount: 0,
    },
  )
  /** 修改时间线：按时间正序存放，展示时倒序。 */
  const history = ref(draft?.history ?? [])
  /** idle | loading | ready | error */
  const status = ref(draft ? 'ready' : 'idle')
  const error = ref(null)
  /** 分段进度：{ done, total }，total<=1 时视图不显示进度条 */
  const progress = ref({ done: 0, total: 0 })

  // --- getters ---
  const pendingItems = computed(() => items.value.filter((item) => item.status === 'pending'))
  const acceptedItems = computed(() => items.value.filter((item) => item.status === 'accepted'))
  const highConfidenceItems = computed(
    () => items.value.filter((item) => item.confidence >= LOW_CONFIDENCE_THRESHOLD),
  )
  const lowConfidenceItems = computed(
    () => items.value.filter((item) => item.confidence < LOW_CONFIDENCE_THRESHOLD),
  )
  /** 高置信建议里还有多少条没被采纳 —— 决定「全部采纳」按钮是否可用。 */
  const acceptableCount = computed(
    () => highConfidenceItems.value.filter((item) => item.status !== 'accepted').length,
  )
  const isReady = computed(() => status.value === 'ready')
  const isLoading = computed(() => status.value === 'loading')
  const canExport = computed(() => acceptedItems.value.length > 0)
  /** 时间线倒序（最新在前），供视图直接渲染。 */
  const timeline = computed(() => [...history.value].reverse())
  /** 分段进行中已有部分结果 —— 视图据此从「加载屏」切到「部分结果」。
   *  这是「校勘一部分就出来一部分」的开关。 */
  const hasPartialResult = computed(() => isLoading.value && items.value.length > 0)
  /** 是否应展示工作台（而不是加载/错误/空态整屏）。 */
  const showsWorkspace = computed(() => isReady.value || items.value.length > 0)
  const progressText = computed(() =>
    progress.value.total > 1 ? `已完成 ${progress.value.done}/${progress.value.total} 段` : '',
  )

  // --- internals ---
  function pushHistory({ action, from = '', to = '', type = '' }) {
    history.value.push({ time: nowTime(), actor: '当前用户', action, from, to, type })
    saveDraft()
  }

  /** 落草稿。只在有内容时写，避免把空态也存下来。 */
  function saveDraft() {
    try {
      if (!sourceText.value) {
        sessionStorage.removeItem(DRAFT_KEY)
        return
      }
      sessionStorage.setItem(
        DRAFT_KEY,
        JSON.stringify({
          sourceText: sourceText.value,
          items: items.value,
          translation: translation.value,
          meta: meta.value,
          history: history.value,
        }),
      )
    } catch {
      // 存不下（隐私模式/超额）也不能影响主流程，静默降级
    }
  }

  function clearDraft() {
    try {
      sessionStorage.removeItem(DRAFT_KEY)
    } catch {
      /* 忽略 */
    }
  }

  function validate(text) {
    if (!text.trim()) {
      return { code: 'INVALID_REQUEST', message: '请先粘贴古籍原文', hint: '' }
    }
    if (text.length > MAX_TEXT_LENGTH) {
      return {
        code: 'TEXT_TOO_LONG',
        message: `文本 ${text.length} 字，超过单次上限 ${MAX_TEXT_LENGTH} 字`,
        hint: ERROR_HINTS.TEXT_TOO_LONG,
      }
    }
    return null
  }

  function buildOptions(options) {
    return {
      checkTypes: options.checkTypes ? [...options.checkTypes] : [...ALL_CHECK_TYPES],
      produceTranslation: options.produceTranslation !== false,
      referenceEdition: options.referenceEdition || DEFAULT_REFERENCE_EDITION,
    }
  }

  function applyResult(text, options, chunkCount) {
    sourceText.value = text
    meta.value = { ...meta.value, referenceEdition: options.referenceEdition, checkTypes: options.checkTypes, produceTranslation: options.produceTranslation, chunkCount }
    history.value = []
    pushHistory({
      action: 'AI 自动校勘',
      from: `${text.length} 字原文${chunkCount > 1 ? `（${chunkCount} 段）` : ''}`,
      to: `返回 ${items.value.length} 条建议`,
    })
    if (meta.value.droppedCount > 0) {
      pushHistory({
        action: '输出可靠性控制',
        from: `${meta.value.droppedCount} 条模型建议`,
        to: '不合契约，已丢弃',
      })
    }
    status.value = 'ready'
    error.value = null
    saveDraft()
  }

  /**
   * 逐段跑完所有分段，限量并发；**每段到货就刷新 items**（这就是"一部分就出来一部分"）。
   * 某段失败时不再派新段，但已到货的结果保留，并把失败信息交给调用方。
   *
   * runId 用来作废过期结果：分段是并发的，用户中途「重新开始」或再次提交时，
   * 上一轮迟到的响应不能再写回 store，否则会把已清空的工作台又填上旧建议。
   */
  async function runChunks(chunks, options, runId) {
    const groups = new Array(chunks.length)
    const elapsed = []
    let nextIndex = 0
    let done = 0
    let firstError = null

    const isStale = () => runId !== activeRun
    progress.value = { done: 0, total: chunks.length }

    const publish = () => {
      if (isStale()) return
      items.value = mergeCollationItems(groups.filter(Boolean))
    }

    const worker = async () => {
      while (firstError === null && nextIndex < chunks.length && !isStale()) {
        const index = nextIndex
        nextIndex += 1
        const chunk = chunks[index]
        try {
          const response = await collateRequest(chunk.text, options)
          if (isStale()) return // 这一轮已被作废，丢弃响应
          groups[index] = rebaseItems(response.items, chunk.start)
          elapsed.push(response.elapsedMs ?? 0)
          if (!meta.value.requestId) meta.value.requestId = response.requestId ?? ''
          meta.value.model = response.model || meta.value.model
          meta.value.droppedCount += response.droppedCount ?? 0
          if (response.translation) {
            translation.value = translation.value ? `${translation.value}\n${response.translation}` : response.translation
          }
          done += 1
          progress.value = { done, total: chunks.length }
          publish() // 每段到货即渲染
        } catch (caught) {
          if (isStale()) return
          firstError = caught
        }
      }
    }

    await Promise.all(
      Array.from({ length: Math.min(MAX_CONCURRENCY, chunks.length) }, () => worker()),
    )

    if (isStale()) return { failed: null, done, total: chunks.length, stale: true }

    publish()
    meta.value.elapsedMs = elapsed.reduce((sum, value) => sum + value, 0)
    return { failed: firstError, done, total: chunks.length, stale: false }
  }

  // --- actions ---
  /**
   * 提交原文去校勘。
   * @returns {Promise<boolean>} 是否**全部**成功（部分成功时返回 false，但结果已进 store）
   */
  async function submitText(rawText, options = {}) {
    const text = String(rawText ?? '')
    const invalid = validate(text)
    if (invalid) {
      error.value = invalid
      status.value = 'error'
      return false
    }

    const resolvedOptions = buildOptions(options)
    const chunks = splitTextIntoChunks(text)
    activeRun += 1
    const runId = activeRun

    // 重新开始一次校勘：清掉上一轮结果，避免新旧混在一起
    items.value = []
    translation.value = ''
    history.value = []
    meta.value = {
      requestId: '',
      model: '',
      elapsedMs: 0,
      droppedCount: 0,
      referenceEdition: resolvedOptions.referenceEdition,
      checkTypes: resolvedOptions.checkTypes,
      produceTranslation: resolvedOptions.produceTranslation,
      chunkCount: chunks.length,
    }
    sourceText.value = text
    status.value = 'loading'
    error.value = null

    const { failed, done, total, stale } = await runChunks(chunks, resolvedOptions, runId)

    if (stale) return false // 这一轮已被「重新开始」或新提交取代，不要回写任何状态

    if (failed) {
      const info = toErrorInfo(failed)
      error.value = {
        ...info,
        message:
          total > 1
            ? `已完成 ${done}/${total} 段，后续分段失败：${info.message}`
            : info.message,
      }
      status.value = 'error'
      saveDraft() // 部分结果也存下来，别让用户白等
      return false
    }

    applyResult(text, resolvedOptions, chunks.length)
    return true
  }

  function accept(id) {
    const item = items.value.find((entry) => entry.id === id)
    if (!item || item.status === 'accepted') return
    item.status = 'accepted'
    pushHistory({ action: '采纳建议', from: item.original, to: item.suggested, type: item.type })
  }

  function reject(id) {
    const item = items.value.find((entry) => entry.id === id)
    if (!item || item.status === 'rejected') return
    item.status = 'rejected'
    pushHistory({ action: '还原原文', from: item.suggested, to: item.original, type: item.type })
  }

  /** 全部采纳：只覆盖高置信建议，低置信条目不参与（API.md §2）。 */
  function acceptAll() {
    const targets = highConfidenceItems.value.filter((item) => item.status !== 'accepted')
    if (!targets.length) return
    targets.forEach((item) => {
      item.status = 'accepted'
    })
    pushHistory({ action: '全部采纳（高置信）', from: '待处理建议', to: `${targets.length} 条` })
  }

  /** 一键还原：所有条目回到「未采纳」语义下的原文状态。 */
  function rejectAll() {
    const targets = items.value.filter((item) => item.status !== 'rejected')
    if (!targets.length) return
    targets.forEach((item) => {
      item.status = 'rejected'
    })
    pushHistory({ action: '一键还原', from: '全部建议', to: '回到原文' })
  }

  /**
   * 导出规范校勘记（F4）：纯规则生成，不调模型。
   * @returns {{ok: boolean, message?: string, noteText?: string, filename?: string}}
   */
  function exportNote(title = '') {
    if (!canExport.value) {
      return { ok: false, message: '尚无采纳的校勘建议，请先采纳需要写入校勘记的条目。' }
    }
    const accepted = [...acceptedItems.value].sort((a, b) => a.offset - b.offset)
    const noteText = buildCollationNote({
      items: accepted,
      referenceEdition: meta.value.referenceEdition,
      title,
    })
    const filename = noteFilename('校勘记')
    downloadTextFile(filename, noteText)
    pushHistory({ action: '导出校勘记', from: '—', to: filename })
    return { ok: true, noteText, filename }
  }

  /** 清空错误状态（用户重新提交或切回首页时调用）。 */
  function clearError() {
    error.value = null
    if (status.value === 'error') status.value = 'idle'
  }

  /** 清空全部状态（首页重新开始时调用），同时丢弃本地草稿并作废在途分段。 */
  function reset() {
    activeRun += 1 // 让并发中的分段结果失效，否则迟到的响应会把工作台又填上
    sourceText.value = ''
    items.value = []
    translation.value = ''
    history.value = []
    status.value = 'idle'
    error.value = null
    progress.value = { done: 0, total: 0 }
    meta.value = {
      requestId: '',
      model: '',
      elapsedMs: 0,
      droppedCount: 0,
      referenceEdition: DEFAULT_REFERENCE_EDITION,
      checkTypes: [...ALL_CHECK_TYPES],
      produceTranslation: true,
      chunkCount: 0,
    }
    clearDraft()
  }

  return {
    // state
    sourceText,
    items,
    translation,
    meta,
    history,
    status,
    error,
    progress,
    // getters
    pendingItems,
    acceptedItems,
    highConfidenceItems,
    lowConfidenceItems,
    acceptableCount,
    isReady,
    isLoading,
    canExport,
    timeline,
    hasPartialResult,
    showsWorkspace,
    progressText,
    // actions
    submitText,
    accept,
    reject,
    acceptAll,
    rejectAll,
    exportNote,
    clearError,
    reset,
  }
})
