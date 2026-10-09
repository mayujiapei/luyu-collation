/**
 * 分段工具测试：切分必须**首尾相接、不重叠、不丢字**，否则原文标记会错位、
 * 句子会被切断。这组用例把这三条不变量钉死。
 */

import { describe, expect, it } from 'vitest'

import {
  DEFAULT_TARGET,
  MAX_CHUNKS,
  mergeCollationItems,
  rebaseItems,
  splitTextIntoChunks,
} from './textChunks'

const 长文 =
  '十年春，齐师伐我。公将战，曹刿请见。其乡人曰：「肉食者谋之，又何间焉？」刿曰：「肉食者鄙，未能远谋。」乃入见。' +
  '问：「何以战？」公曰：「衣食所安，弗敢专也，必以分人。」对曰：「小惠未遍，民弗从也。」' +
  '公曰：「牺牲玉帛，弗敢加也，必以信。」对曰：「小信未孚，神弗福也。」' +
  '公曰：「小大之狱，虽不能察，必以情。」对曰：「忠之属也，可以一战。战则请从。」'

function 断言无缝拼接(text, chunks) {
  expect(chunks.length).toBeGreaterThan(0)
  expect(chunks[0].start).toBe(0)
  expect(chunks[chunks.length - 1].end).toBe(text.length)
  for (let i = 1; i < chunks.length; i += 1) {
    expect(chunks[i].start).toBe(chunks[i - 1].end) // 首尾相接、无重叠
  }
  expect(chunks.map((c) => c.text).join('')).toBe(text) // 拼回去必须与原文逐字相同
}

describe('splitTextIntoChunks', () => {
  it('短文本不切，仍是单段', () => {
    const chunks = splitTextIntoChunks('十年春，齐师伐我。')
    expect(chunks).toHaveLength(1)
    expect(chunks[0].text).toBe('十年春，齐师伐我。')
  })

  it('不足目标字数的文本保持单段（默认目标 100 字）', () => {
    const 短文 = '十年春，齐师伐我。'.repeat(8) // 9 字 × 8 = 72 字
    expect(短文.length).toBeLessThan(DEFAULT_TARGET)
    expect(splitTextIntoChunks(短文)).toHaveLength(1)
  })

  it('超过目标字数就分段，且无缝拼接（不丢字、不重叠）', () => {
    const chunks = splitTextIntoChunks(长文, { target: 80 })
    expect(chunks.length).toBeGreaterThan(1)
    断言无缝拼接(长文, chunks)
  })

  it('切点落在句读之后，不会把句子劈成两半', () => {
    const chunks = splitTextIntoChunks(长文, { target: 80 })
    for (const chunk of chunks.slice(0, -1)) {
      expect('。！？；\n'.includes(chunk.text.at(-1))).toBe(true)
    }
  })

  it('段数不超过上限（受后端限流约束）', () => {
    const 超长 = 长文.repeat(20) // 约 4800 字
    const chunks = splitTextIntoChunks(超长)
    expect(chunks.length).toBeLessThanOrEqual(MAX_CHUNKS)
    断言无缝拼接(超长, chunks)
  })

  it('段数上限生效时，段大小随之放大而不是切得更碎', () => {
    const 超长 = 长文.repeat(20)
    const chunks = splitTextIntoChunks(超长)
    const 平均 = 超长.length / chunks.length
    expect(平均).toBeGreaterThan(DEFAULT_TARGET)
  })

  it('无标点的超长串会退化到逗号级切分', () => {
    const 无句号 = '甲乙丙丁，'.repeat(300)
    const chunks = splitTextIntoChunks(无句号)
    expect(chunks.length).toBeGreaterThan(1)
    断言无缝拼接(无句号, chunks)
  })

  it('空文本与纯空白返回空数组', () => {
    expect(splitTextIntoChunks('')).toEqual([])
    expect(splitTextIntoChunks('   \n ')).toEqual([])
    expect(splitTextIntoChunks(null)).toEqual([])
  })

  it('保留原文不做 trim，避免偏移错位', () => {
    const text = '  十年春，齐师伐我。  '
    const chunks = splitTextIntoChunks(text)
    expect(chunks[0].start).toBe(0)
    断言无缝拼接(text, chunks)
  })
})

describe('rebaseItems', () => {
  it('把段内偏移搬到全文坐标系', () => {
    const rebased = rebaseItems([{ id: 1, offset: 6, original: '代' }], 100)
    expect(rebased[0].offset).toBe(106)
    expect(rebased[0].original).toBe('代')
  })

  it('偏移缺失或非法时按段首处理，不产生 NaN 标记', () => {
    expect(rebaseItems([{ id: 1 }], 50)[0].offset).toBe(50)
    expect(rebaseItems([{ id: 1, offset: null }], 50)[0].offset).toBe(50)
  })

  it('空输入安全', () => {
    expect(rebaseItems(undefined, 10)).toEqual([])
  })
})

describe('mergeCollationItems', () => {
  it('按全文偏移排序', () => {
    const merged = mergeCollationItems([
      [{ id: 1, type: '讹字', original: '乙', suggested: '丙', offset: 80 }],
      [{ id: 2, type: '讹字', original: '甲', suggested: '丁', offset: 10 }],
    ])
    expect(merged.map((item) => item.offset)).toEqual([10, 80])
  })

  it('段边界处重复的同一条建议只保留一条', () => {
    const dup = { type: '讹字', original: '代', suggested: '伐', offset: 6 }
    const merged = mergeCollationItems([[dup], [{ ...dup, offset: 200 }]])
    expect(merged).toHaveLength(1)
  })

  it('空输入安全', () => {
    expect(mergeCollationItems([])).toEqual([])
    expect(mergeCollationItems(undefined)).toEqual([])
  })
})
