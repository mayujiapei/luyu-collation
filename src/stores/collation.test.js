/**
 * 校勘仓库状态逻辑测试。
 *
 * 重点是 API.md §2 的硬规则：confidence < 0.7 的条目不参与「全部采纳」，
 * 以及 F3 要求的每次决策都写进修改时间线。
 */

import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { LOW_CONFIDENCE_THRESHOLD, useCollationStore } from './collation'

function item(overrides) {
  return {
    id: 1,
    type: '讹字',
    original: '代',
    suggested: '伐',
    reason: '形近而讹',
    confidence: 1,
    offset: 2,
    status: 'pending',
    ...overrides,
  }
}

function seed(store, items) {
  store.sourceText = '齐师代我。肉食者鄙。'
  store.items = items.map((entry) => ({ ...entry }))
  store.translation = '译文'
  store.status = 'ready'
  store.history = []
}

describe('低置信建议不参与「全部采纳」', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useCollationStore()
    seed(store, [
      item({ id: 1, confidence: 0.95 }),
      item({ id: 2, type: '异文', original: '鄙', suggested: '陋', confidence: LOW_CONFIDENCE_THRESHOLD }),
      item({ id: 3, type: '脱文', original: '其名鲲', suggested: '其名为鲲', confidence: 0.55 }),
    ])
  })

  it('阈值取闭区间下界：0.7 属于高置信，0.55 属于低置信', () => {
    expect(store.highConfidenceItems.map((entry) => entry.id)).toEqual([1, 2])
    expect(store.lowConfidenceItems.map((entry) => entry.id)).toEqual([3])
  })

  it('acceptAll 只采纳高置信条目', () => {
    store.acceptAll()
    expect(store.items.find((entry) => entry.id === 1).status).toBe('accepted')
    expect(store.items.find((entry) => entry.id === 2).status).toBe('accepted')
    expect(store.items.find((entry) => entry.id === 3).status).toBe('pending')
  })

  it('低置信条目仍可单独采纳', () => {
    store.accept(3)
    expect(store.items.find((entry) => entry.id === 3).status).toBe('accepted')
  })

  it('高置信都采纳后「全部采纳」不可再用，低置信不为其续命', () => {
    expect(store.acceptableCount).toBe(2)
    store.acceptAll()
    expect(store.acceptableCount).toBe(0)
  })
})

describe('决策写入时间线（F3 留痕）', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useCollationStore()
    seed(store, [item({ id: 1 }), item({ id: 2, original: '说', suggested: '悦', type: '通假' })])
  })

  it('采纳与还原各记一条，且带原文/建议', () => {
    store.accept(1)
    store.reject(2)
    expect(store.history).toHaveLength(2)
    expect(store.history[0]).toMatchObject({ action: '采纳建议', from: '代', to: '伐', type: '讹字' })
    expect(store.history[1]).toMatchObject({ action: '还原原文', from: '悦', to: '说' })
  })

  it('重复采纳同一条不重复记账', () => {
    store.accept(1)
    store.accept(1)
    expect(store.history).toHaveLength(1)
  })

  it('一键还原把全部条目置为已还原', () => {
    store.accept(1)
    store.rejectAll()
    expect(store.items.every((entry) => entry.status === 'rejected')).toBe(true)
  })

  it('时间线最新在前', () => {
    store.accept(1)
    store.reject(2)
    expect(store.timeline[0].action).toBe('还原原文')
  })
})

describe('导出前置条件', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useCollationStore()
    seed(store, [item({ id: 1 })])
  })

  it('没有采纳条目时不可导出，并给出原因', () => {
    expect(store.canExport).toBe(false)
    const result = store.exportNote()
    expect(result.ok).toBe(false)
    expect(result.message).toContain('尚无采纳的校勘建议')
  })

  it('采纳后即可导出', () => {
    store.accept(1)
    expect(store.canExport).toBe(true)
  })
})

describe('本地入参校验', () => {
  let store

  beforeEach(() => {
    setActivePinia(createPinia())
    store = useCollationStore()
  })

  it('空文本不发请求，直接给降级提示', async () => {
    const ok = await store.submitText('   ')
    expect(ok).toBe(false)
    expect(store.error.code).toBe('INVALID_REQUEST')
    expect(store.status).toBe('error')
  })

  it('超长文本本地拦截，错误码与后端一致', async () => {
    const ok = await store.submitText('字'.repeat(5001))
    expect(ok).toBe(false)
    expect(store.error.code).toBe('TEXT_TOO_LONG')
  })

  it('超长文本除错误码外还给「怎么办」的提示', async () => {
    await store.submitText('字'.repeat(5001))
    expect(store.error.hint).toContain('分段')
  })

  it('空文本的提示本身已可操作，不再叠加多余建议', async () => {
    await store.submitText('  ')
    expect(store.error.message).toContain('请先粘贴古籍原文')
    expect(store.error.hint).toBe('')
  })
})
