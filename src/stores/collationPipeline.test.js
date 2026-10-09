/**
 * 分段流水线测试：验证「校勘一部分就出来一部分」这个行为本身。
 *
 * 用 mock 精确控制每段何时返回，才能断言"第一段到货时就已经出现在界面上、
 * 而整体仍在 loading"——这正是用户要的渐进呈现，靠真实模型是测不准的。
 */

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const { collateMock } = vi.hoisted(() => ({ collateMock: vi.fn() }))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, collate: collateMock }
})

const { useCollationStore } = await import('./collation')
const { splitTextIntoChunks } = await import('@/utils/textChunks')

/** 约 400 字，超过默认 220 字目标，必然切成两段。 */
const 长文 = '十年春，齐师伐我。'.repeat(40)

const tick = () => new Promise((resolve) => setTimeout(resolve, 0))

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function response(items, overrides = {}) {
  return {
    requestId: 'req_test',
    model: 'fake-model',
    elapsedMs: 100,
    items,
    translation: '',
    droppedCount: 0,
    ...overrides,
  }
}

function item(overrides = {}) {
  return {
    id: 1,
    type: '讹字',
    original: '代',
    suggested: '伐',
    reason: '形近而讹',
    confidence: 0.95,
    offset: 3,
    ...overrides,
  }
}

describe('分段流水线', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useCollationStore()
    collateMock.mockReset()
  })

  it('短文本只发一次调用，不显示分段进度', async () => {
    collateMock.mockResolvedValueOnce(response([item()]))
    await store.submitText('十年春，齐师伐我。')

    expect(collateMock).toHaveBeenCalledTimes(1)
    expect(store.status).toBe('ready')
    expect(store.meta.chunkCount).toBe(1)
    expect(store.progressText).toBe('')
  })

  it('长文本切成多段并分别调用', async () => {
    collateMock.mockResolvedValue(response([]))
    await store.submitText(长文)

    expect(collateMock.mock.calls.length).toBeGreaterThan(1)
    expect(store.meta.chunkCount).toBe(collateMock.mock.calls.length)
    // 每段发出去的都是该段文本，而不是整篇
    for (const [chunkText] of collateMock.mock.calls) {
      expect(chunkText.length).toBeLessThan(长文.length)
    }
  })

  it('第一段到货就渲染出结果，此时整体仍在 loading', async () => {
    const chunks = splitTextIntoChunks(长文)
    const pending = chunks.map(() => deferred())
    let call = 0
    collateMock.mockImplementation(() => {
      const promise = pending[call].promise
      call += 1
      return promise
    })

    const done = store.submitText(长文)
    await tick()
    // 并发度取 min(3, 段数)
    expect(collateMock).toHaveBeenCalledTimes(Math.min(3, chunks.length))

    // 只把第一段放回来
    pending[0].resolve(response([item({ offset: 3 })]))
    await tick()

    expect(store.items).toHaveLength(1)
    expect(store.status).toBe('loading')
    expect(store.hasPartialResult).toBe(true)
    expect(store.showsWorkspace).toBe(true) // 视图据此从加载屏切到部分结果
    expect(store.progressText).toBe(`已完成 1/${chunks.length} 段`)

    // 其余段各给一条**不同**的建议，否则会被跨段去重合并掉
    pending.slice(1).forEach((entry, index) => {
      entry.resolve(response([item({ type: '通假', original: `原文${index}`, suggested: `建议${index}`, offset: 5 })]))
    })
    await done

    expect(store.status).toBe('ready')
    expect(store.items).toHaveLength(chunks.length)
    expect(store.hasPartialResult).toBe(false)
  })

  it('合并时把段内偏移搬到全文坐标系并按位置排序', async () => {
    const chunks = splitTextIntoChunks(长文)
    // 按调用顺序编号（不能按段文本查下标：重复文本会让多段内容相同）
    let call = 0
    collateMock.mockImplementation(() => {
      const index = call
      call += 1
      return Promise.resolve(
        response([item({ original: `原文${index}`, suggested: `建议${index}`, offset: 5 })]),
      )
    })
    await store.submitText(长文)

    // 每段段内偏移 5 都要加上该段起点，且整体按全文位置升序
    expect(store.items.map((entry) => entry.offset)).toEqual(chunks.map((entry) => 5 + entry.start))
  })

  it('跨段重复的同一建议只保留一条', async () => {
    const 同一条 = item({ offset: 2 })
    collateMock.mockResolvedValue(response([同一条]))
    await store.submitText(长文)

    expect(collateMock.mock.calls.length).toBeGreaterThan(1)
    expect(store.items).toHaveLength(1)
  })

  it('译文按段拼接', async () => {
    const chunks = splitTextIntoChunks(长文)
    let call = 0
    collateMock.mockImplementation(() => {
      const index = call
      call += 1
      return Promise.resolve(response([], { translation: `第 ${index + 1} 段译文。` }))
    })
    await store.submitText(长文)

    expect(store.translation).toBe(chunks.map((_, index) => `第 ${index + 1} 段译文。`).join('\n'))
  })

  it('某段失败时保留已到货结果，并说明完成到第几段', async () => {
    const chunks = splitTextIntoChunks(长文)
    let call = 0
    collateMock.mockImplementation(() => {
      call += 1
      // 第一次返回结果，之后的段全部失败
      return call === 1
        ? Promise.resolve(response([item({ offset: 3 })]))
        : Promise.reject(new Error('上游炸了'))
    })

    const ok = await store.submitText(长文)

    expect(ok).toBe(false)
    expect(store.status).toBe('error')
    expect(store.items).toHaveLength(1) // 部分结果不丢
    expect(store.error.message).toContain(`已完成 1/${chunks.length} 段`)
  })

  it('累计各段耗时与丢弃条数', async () => {
    collateMock.mockResolvedValue(response([], { elapsedMs: 100, droppedCount: 1 }))
    await store.submitText(长文)

    const 段数 = store.meta.chunkCount
    expect(段数).toBeGreaterThan(1)
    expect(store.meta.elapsedMs).toBe(100 * 段数)
    expect(store.meta.droppedCount).toBe(段数)
  })

  it('重新提交会清掉上一轮结果，不出现新旧混杂', async () => {
    collateMock.mockResolvedValue(response([item()]))
    await store.submitText('十年春，齐师伐我。')
    expect(store.items).toHaveLength(1)

    collateMock.mockResolvedValue(response([]))
    await store.submitText('公将战，曹刿请见。')
    expect(store.items).toHaveLength(0)
    expect(store.sourceText).toBe('公将战，曹刿请见。')
  })
})
