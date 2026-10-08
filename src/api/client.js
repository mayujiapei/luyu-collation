/**
 * 后端 API 封装：统一 baseURL、超时与错误结构。
 *
 * 契约见 docs/API.md —— 错误一律是 { error: { code, message } }，
 * 这里把它转成 ApiError（带 code / status），让调用方按码分支而不是解析文案。
 */

const BASE_URL = (import.meta.env.VITE_API_BASE || 'http://localhost:3001').replace(/\/+$/, '')

// 后端自己的大模型超时是 30 秒（PRD §5）。前端留 35 秒，让后端先返回带明确
// code 的 LLM_TIMEOUT，用户看到的才是「模型超时」而不是笼统的「请求超时」。
const COLLATE_TIMEOUT_MS = 35_000
const HEALTH_TIMEOUT_MS = 5_000

/** 前端自定义码（后端错误码之外的网络层失败，同一命名空间便于 UI 统一分支） */
export const NETWORK_ERROR = 'NETWORK_ERROR'

export class ApiError extends Error {
  constructor(code, message, status = 0) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

async function readJson(response) {
  try {
    return await response.json()
  } catch {
    return null
  }
}

async function request(path, { method = 'GET', body, timeoutMs = COLLATE_TIMEOUT_MS } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw new ApiError('LLM_TIMEOUT', `请求超时（超过 ${Math.round(timeoutMs / 1000)} 秒），请稍后重试或缩短文本`)
    }
    throw new ApiError(NETWORK_ERROR, '无法连接校勘服务：请确认后端已启动（npm run dev:server）')
  } finally {
    clearTimeout(timer)
  }

  const payload = await readJson(response)

  if (!response.ok) {
    const detail = payload?.error
    throw new ApiError(
      detail?.code || 'HTTP_ERROR',
      detail?.message || `服务返回 HTTP ${response.status}`,
      response.status,
    )
  }
  if (payload === null) {
    throw new ApiError('HTTP_ERROR', '服务返回的内容不是 JSON', response.status)
  }
  return payload
}

/**
 * 智能校勘（F2/F5）。
 * @param {string} text 待校勘原文
 * @param {object} [options] 见 API.md §2；省略时由后端取默认值
 */
export function collate(text, options) {
  return request('/api/v1/collate', {
    method: 'POST',
    body: options ? { text, options } : { text },
  })
}

/** 冒烟检查（API.md §5），演示前跑一条。 */
export function health() {
  return request('/api/v1/health', { timeoutMs: HEALTH_TIMEOUT_MS })
}
