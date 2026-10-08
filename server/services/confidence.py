"""置信度规则修正（TECH_DESIGN §5、HANDOFF §5「置信度经规则修正」）。

模型自评的置信度不作最终值：命中形近字表 / 通假字表时 +0.1。
这是「规则引擎 + 模型」结合的第一处落点，也是答辩时解释「置信度如何可信」的抓手。

字表是**种子集**，覆盖古籍高频易混对，后续按回归集与对比实验的错误样本继续扩表；
不要在此追求大而全的字典，规则只负责「命中即加分」，不负责判定正误。
"""

from __future__ import annotations

from ..utils.schemas import ModelItem

CONFIDENCE_BOOST = 0.1

# 形近字对：讹字类建议命中则加分（如「日 / 曰」）
_SIMILAR_FORM_PAIRS: tuple[tuple[str, str], ...] = (
    ("日", "曰"), ("己", "已"), ("已", "巳"), ("未", "末"), ("土", "士"), ("大", "太"),
    ("人", "入"), ("干", "千"), ("王", "玉"), ("白", "自"), ("天", "夭"), ("侯", "候"),
    ("折", "拆"), ("拨", "拔"), ("茶", "荼"), ("刺", "剌"), ("祟", "崇"), ("戊", "戌"),
    ("戌", "戍"), ("亳", "毫"), ("祗", "祇"), ("微", "徽"), ("嬴", "羸"), ("辨", "辩"),
    ("籍", "藉"), ("灸", "炙"), ("汩", "汨"), ("惟", "唯"), ("代", "伐"), ("弋", "戈"),
    ("母", "毋"),
)

# 通假字对：通假类建议命中则加分（如「说 / 悦」）
_LOAN_CHAR_PAIRS: tuple[tuple[str, str], ...] = (
    ("说", "悦"), ("女", "汝"), ("知", "智"), ("反", "返"), ("蚤", "早"), ("亡", "无"),
    ("见", "现"), ("坐", "座"), ("直", "值"), ("莫", "暮"), ("尊", "樽"), ("冯", "凭"),
    ("矢", "屎"), ("熙", "嬉"), ("距", "拒"), ("陪", "倍"), ("归", "馈"), ("畔", "叛"),
    ("得", "德"), ("而", "耐"), ("有", "又"), ("卒", "猝"), ("陈", "阵"), ("唱", "倡"),
    ("从", "纵"), ("尔", "迩"), ("共", "供"), ("取", "娶"), ("适", "嫡"), ("孙", "逊"),
    ("希", "稀"), ("锡", "赐"), ("详", "佯"), ("刑", "型"), ("要", "邀"), ("由", "犹"),
    ("与", "欤"), ("章", "彰"), ("属", "嘱"), ("质", "锧"),
)

_SIMILAR_FORM_TABLE = frozenset(frozenset(pair) for pair in _SIMILAR_FORM_PAIRS)
_LOAN_TABLE = frozenset(frozenset(pair) for pair in _LOAN_CHAR_PAIRS)

# 校勘类型 -> 适用字表
_TABLE_BY_TYPE = {
    "讹字": _SIMILAR_FORM_TABLE,
    "通假": _LOAN_TABLE,
}


def _table_hit(original: str, suggested: str, table: frozenset[frozenset[str]]) -> bool:
    """建议是否命中字表。

    优先整片段比对；片段长度一致时再逐字对位比对（「不亦说乎」「不亦悦乎」命中通假表）。
    """
    if not original or not suggested or original == suggested:
        return False
    if frozenset((original, suggested)) in table:
        return True
    if len(original) == len(suggested):
        return any(frozenset((x, y)) in table for x, y in zip(original, suggested))
    return False


def correct_confidence(item: ModelItem) -> ModelItem:
    """按字表修正单条建议的置信度，返回新对象（不就地改动入参）。"""
    table = _TABLE_BY_TYPE.get(item.type)
    if table is None or not _table_hit(item.original, item.suggested, table):
        return item

    boosted = round(min(1.0, item.confidence + CONFIDENCE_BOOST), 4)
    if boosted == item.confidence:
        return item
    return item.model_copy(update={"confidence": boosted})
