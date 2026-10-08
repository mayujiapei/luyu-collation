/**
 * 校勘记体例生成器的单元测试（F4 / TECH_DESIGN §6）。
 *
 * 这里守的是导出物本身：模板套错、差异段切错、编号错，导出的校勘记会静默出错，
 * 而那是要交给文献学用户的成品，所以逐类型钉死期望文本。
 */

import { describe, expect, it } from 'vitest'

import {
  buildCollationNote,
  chineseNumeral,
  diffFragments,
  noteFilename,
  renderEntry,
} from './collationNote'

const 讹字 = { type: '讹字', original: '代', suggested: '伐', reason: '形近而讹' }
const 衍文 = { type: '衍文', original: '舍舍去', suggested: '舍去', reason: '' }
const 脱文 = { type: '脱文', original: '其名鲲', suggested: '其名为鲲', reason: '对文作「其名为鹏」' }
const 通假 = { type: '通假', original: '说', suggested: '悦', reason: '喜悦之义，只标注不替换' }
const 异文 = { type: '异文', original: '肉食者鄙', suggested: '肉食者陋', reason: '据通行本' }

describe('renderEntry 五类体例', () => {
  it('讹字：只取差异单字入引号，不把整段上下文塞进去', () => {
    // 「日学而时习之」-> 「学而时习之」：差异只在首字，校勘记应作「学而时习之」，底本误作「日」
    const entry = renderEntry(
      { type: '讹字', original: '日学而时习之', suggested: '学而时习之', reason: '形近而讹' },
      '通行本',
    )
    expect(entry).toBe('「学而时习之」，底本误作「日」，形近而讹，今据通行本改。')
  })

  it('讹字：参校本写入「今据…改」', () => {
    expect(renderEntry(讹字, '宋刻本')).toBe('「伐」，底本误作「代」，形近而讹，今据宋刻本改。')
  })

  it('衍文：指出所衍之字并作「今删」', () => {
    expect(renderEntry(衍文)).toBe('「舍去」下衍「舍」字，今删。')
  })

  it('脱文：指出所脱之字并作「今补」', () => {
    expect(renderEntry(脱文)).toBe('「其名鲲」下脱「为」，对文作「其名为鹏」，今补。')
  })

  it('通假：只标注本字，不带「今改」', () => {
    expect(renderEntry(通假)).toBe('「说」通「悦」，喜悦之义，只标注不替换。')
  })

  it('异文：作「一作」形式', () => {
    expect(renderEntry(异文)).toBe('「肉食者鄙」，一作「肉食者陋」，据通行本。')
  })

  it('理由尾部标点不叠加', () => {
    expect(renderEntry({ ...讹字, reason: '形近而讹。' })).toBe('「伐」，底本误作「代」，形近而讹，今据通行本改。')
  })

  it('理由缺失时整段略去，不留「，。」', () => {
    expect(renderEntry({ ...讹字, reason: '' })).toBe('「伐」，底本误作「代」，今据通行本改。')
  })

  it('未知类型退回可读形式而不是抛错', () => {
    expect(renderEntry({ type: '错别字', original: '甲', suggested: '乙' })).toBe('「甲」改作「乙」。')
  })
})

describe('diffFragments', () => {
  it('剥离公共前后缀', () => {
    expect(diffFragments('日学而时习之', '学而时习之')).toMatchObject({
      before: '',
      originalMiddle: '日',
      suggestedMiddle: '',
      after: '学而时习之',
    })
  })

  it('两侧都有公共部分时取中段', () => {
    expect(diffFragments('其名鲲', '其名为鲲')).toMatchObject({
      before: '其名',
      originalMiddle: '',
      suggestedMiddle: '为',
      after: '鲲',
    })
  })

  it('完全相同则中段都为空', () => {
    expect(diffFragments('甲', '甲')).toMatchObject({ originalMiddle: '', suggestedMiddle: '' })
  })
})

describe('chineseNumeral', () => {
  it('覆盖条目编号常见区间', () => {
    expect([1, 2, 3, 10, 11, 20, 21, 99, 100, 105].map(chineseNumeral)).toEqual([
      '一', '二', '三', '十', '十一', '二十', '二十一', '九十九', '一百', '一百零五',
    ])
  })
})

describe('buildCollationNote', () => {
  it('输出带标题、中文序号与末尾条数统计', () => {
    const note = buildCollationNote({ items: [讹字, 通假], referenceEdition: '通行本' })
    expect(note).toBe(
      '校勘记\n' +
        '一、「伐」，底本误作「代」，形近而讹，今据通行本改。\n' +
        '二、「说」通「悦」，喜悦之义，只标注不替换。\n' +
        '\n以上共二条。\n',
    )
  })

  it('带篇名时标题写作「校勘记——篇名」', () => {
    expect(buildCollationNote({ items: [讹字], title: '曹刿论战' })).toContain('校勘记——曹刿论战\n')
  })

  it('无采纳条目时给出明确说明而不是空白文件', () => {
    expect(buildCollationNote({ items: [] })).toBe('校勘记\n（无采纳的校勘条目）\n')
  })
})

describe('noteFilename', () => {
  it('带时间戳，不覆盖既有导出文件（数据红线）', () => {
    expect(noteFilename('校勘记', new Date(2026, 9, 7, 22, 5))).toBe('校勘记_20261007-2205.txt')
  })
})
