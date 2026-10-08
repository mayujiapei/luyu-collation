/**
 * 校勘状态仓库（TECH_DESIGN §3）。
 *
 * 主链路的唯一数据来源：原文、AI 建议、译文、决策状态、修改时间线全部在这里，
 * 组件只读这里的数据，不再自带任何演示数据。
 */

import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { ApiError, NETWORK_ERROR, collate as collateRequest } from '@/api/client'
import { buildCollationNote, downloadTextFile, noteFilename } from '@/utils/collationNote'

/** 置信度低于此值的建议折叠为「低置信建议」，且不参与「全部采纳」（API.md §2）。 */
export const LOW_CONFIDENCE_THRESHOLD = 0.7

/** 单次校勘文本上限（PRD §5），与后端 MAX_TEXT_LEN 一致。 */
export const MAX_TEXT_LENGTH = 5000

export const ALL_CHECK_TYPES = ['讹字', '衍文', '脱文', '通假', '异文']

export const DEFAULT_REFERENCE_EDITION = '通行本'

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

export const useCollationStore = defineStore('collation', () => {
  // --- state ---
  const sourceText = ref('')
  /** 每条：{ id, type, original, suggested, reason, confidence, offset, status } */
  const items = ref([])
  const translation = ref('')
  const meta = ref({
    requestId: '',
    model: '',
    elapsedMs: 0,
    droppedCount: 0,
    referenceEdition: DEFAULT_REFERENCE_EDITION,
    checkTypes: [...ALL_CHECK_TYPES],
    produceTranslation: true,
  })
  /** 修改时间线：按时间正序存放，展示时倒序。 */
  const history = ref([])
  /** idle | loading | ready | error */
  const status = ref('idle')
  const error = ref(null)

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

  // --- internals ---
  function pushHistory({ action, from = '', to = '', type = '' }) {
    history.value.push({ time: nowTime(), actor: '当前用户', action, from, to, type })
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

  function applyResult(text, response, options) {
    sourceText.value = text
    items.value = (response.items ?? []).map((item) => ({ ...item, status: 'pending' }))
    translation.value = response.translation ?? ''
    meta.value = {
      requestId: response.requestId ?? '',
      model: response.model ?? '',
      elapsedMs: response.elapsedMs ?? 0,
      droppedCount: response.droppedCount ?? 0,
      referenceEdition: options.referenceEdition,
      checkTypes: options.checkTypes,
      produceTranslation: options.produceTranslation,
    }

    history.value = []
    pushHistory({
      action: 'AI 自动校勘',
      from: `${text.length} 字原文`,
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
  }

  // --- actions ---
  /**
   * 提交原文去校勘。
   * @returns {Promise<boolean>} 是否成功（失败时 error 已写好，调用方决定怎么提示）
   */
  async function submitText(rawText, options = {}) {
    const text = String(rawText ?? '')
    const invalid = validate(text)
    if (invalid) {
      error.value = invalid
      status.value = 'error'
      return false
    }

    status.value = 'loading'
    error.value = null
    const resolvedOptions = buildOptions(options)

    try {
      const response = await collateRequest(text, resolvedOptions)
      applyResult(text, response, resolvedOptions)
      return true
    } catch (caught) {
      error.value = toErrorInfo(caught)
      status.value = 'error'
      return false
    }
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

  /** 清空全部状态（首页重新开始时调用）。 */
  function reset() {
    sourceText.value = ''
    items.value = []
    translation.value = ''
    history.value = []
    status.value = 'idle'
    error.value = null
    meta.value = {
      requestId: '',
      model: '',
      elapsedMs: 0,
      droppedCount: 0,
      referenceEdition: DEFAULT_REFERENCE_EDITION,
      checkTypes: [...ALL_CHECK_TYPES],
      produceTranslation: true,
    }
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
