/**
 * 校勘记体例生成（F4 / TECH_DESIGN §6）—— 纯规则，不调模型，离线可用。
 *
 * 体例模板：
 *   讹字：「X」，底本误作「Y」，{理由}，今据{参校本}改。
 *   衍文：「X」下衍「Y」字，今删。
 *   脱文：「X」下脱「Y」，{理由}，今补。
 *   通假：「X」通「Y」，{释义}。          （只标注，不改动原文）
 *   异文：「X」，一作「Y」，{取舍理由}。
 *
 * X / Y 由 original 与 suggested 的最小差异段推出：模型给的片段可能带上下文字，
 * 直接整段塞进模板会读成「「学而时习之」，底本误作「日学而时习之」」这种别扭句子。
 */

const DIGITS = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九']

/** 阿拉伯数字转中文序数（条目编号用「一、二、三……」）。 */
export function chineseNumeral(value) {
  const n = Number(value)
  if (!Number.isInteger(n) || n <= 0 || n > 999) return String(value)
  if (n < 10) return DIGITS[n]
  if (n === 10) return '十'
  if (n < 20) return `十${DIGITS[n % 10]}`
  if (n < 100) return `${DIGITS[Math.floor(n / 10)]}十${n % 10 ? DIGITS[n % 10] : ''}`
  const hundreds = Math.floor(n / 100)
  const rest = n % 100
  if (!rest) return `${DIGITS[hundreds]}百`
  return `${DIGITS[hundreds]}百${rest < 10 ? `零${DIGITS[rest]}` : chineseNumeral(rest)}`
}

function commonPrefixLength(a, b) {
  let i = 0
  while (i < a.length && i < b.length && a[i] === b[i]) i += 1
  return i
}

function commonSuffixLength(a, b, remaining) {
  let i = 0
  while (i < remaining && a[a.length - 1 - i] === b[b.length - 1 - i]) i += 1
  return i
}

/**
 * 求 original 与 suggested 的最小差异段。
 * @returns {{before: string, originalMiddle: string, suggestedMiddle: string, after: string}}
 */
export function diffFragments(original, suggested) {
  const from = String(original ?? '')
  const to = String(suggested ?? '')
  const prefix = commonPrefixLength(from, to)
  const suffix = commonSuffixLength(from, to, Math.min(from.length, to.length) - prefix)
  return {
    before: from.slice(0, prefix),
    originalMiddle: from.slice(prefix, from.length - suffix),
    suggestedMiddle: to.slice(prefix, to.length - suffix),
    after: suffix ? from.slice(from.length - suffix) : '',
  }
}

/** 理由并入句子：去掉尾部标点，空理由则整段略去，避免出现「，。」。 */
function withReason(reason) {
  const cleaned = String(reason ?? '')
    .trim()
    .replace(/[，。；;、,.\s]+$/, '')
  return cleaned ? `，${cleaned}` : ''
}

const TYPE_RENDERERS = {
  讹字(item, edition) {
    const { originalMiddle, suggestedMiddle } = diffFragments(item.original, item.suggested)
    const wrong = originalMiddle || item.original
    const right = suggestedMiddle || item.suggested
    return `「${right}」，底本误作「${wrong}」${withReason(item.reason)}，今据${edition}改。`
  },
  衍文(item) {
    const { originalMiddle } = diffFragments(item.original, item.suggested)
    const extra = originalMiddle || item.original
    return `「${item.suggested}」下衍「${extra}」字${withReason(item.reason)}，今删。`
  },
  脱文(item) {
    const { suggestedMiddle } = diffFragments(item.original, item.suggested)
    const missing = suggestedMiddle || item.suggested
    return `「${item.original}」下脱「${missing}」${withReason(item.reason)}，今补。`
  },
  通假(item) {
    return `「${item.original}」通「${item.suggested}」${withReason(item.reason)}。`
  },
  异文(item) {
    return `「${item.original}」，一作「${item.suggested}」${withReason(item.reason)}。`
  },
}

/** 单条建议 -> 一行校勘记。类型未知时退回「原文 -> 建议」的可读形式。 */
export function renderEntry(item, referenceEdition = '通行本') {
  const renderer = TYPE_RENDERERS[item?.type]
  if (!renderer) return `「${item?.original}」改作「${item?.suggested}」。`
  return renderer(item, referenceEdition)
}

/**
 * 生成完整校勘记文本。
 * @param {{items: Array, referenceEdition?: string, title?: string}} params
 *        items 只传**已采纳**的条目，顺序即原文顺序。
 */
export function buildCollationNote({ items = [], referenceEdition = '通行本', title = '' } = {}) {
  const head = title ? `校勘记——${title}` : '校勘记'
  if (!items.length) return `${head}\n（无采纳的校勘条目）\n`

  const entries = items.map((item, index) => `${chineseNumeral(index + 1)}、${renderEntry(item, referenceEdition)}`)
  return [`${head}\n`, ...entries.map((line) => `${line}\n`), `\n以上共${chineseNumeral(items.length)}条。\n`].join('')
}

/** 带时间戳的导出文件名（数据红线：修改写入新文件，不覆盖原文件）。 */
export function noteFilename(prefix = '校勘记', date = new Date()) {
  const pad = (value) => String(value).padStart(2, '0')
  const stamp =
    `${date.getFullYear()}${pad(date.getMonth() + 1)}${pad(date.getDate())}` +
    `-${pad(date.getHours())}${pad(date.getMinutes())}`
  return `${prefix}_${stamp}.txt`
}

/** 触发浏览器下载。 */
export function downloadTextFile(filename, text) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}
