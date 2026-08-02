from __future__ import annotations

from typing import Final, Literal, TypedDict


class TraditionalReferenceSource(TypedDict):
    level: Literal["index_only", "upstream_summary", "upstream_excerpt"]
    label: str
    url: str | None
    note: str


class TraditionalReferenceBook(TypedDict):
    id: str
    title: str
    alias: str
    focus: str
    tradition: str
    source: TraditionalReferenceSource


_INDEX_ONLY: Final[TraditionalReferenceSource] = {
    "level": "index_only",
    "label": "仅索引",
    "url": None,
    "note": "Council 只记录书名、主题和流派元数据，未载入原文。",
}
_BAZI_SUMMARY: Final[TraditionalReferenceSource] = {
    "level": "upstream_summary",
    "label": "上游规则摘要",
    "url": "https://github.com/jinchenma94/bazi-skill/blob/bdd7f863d4450bf0e2fac84579ad6b45cfdfa25c/references/classical-texts.md",
    "note": "上游文件是九部典籍的规则摘要和示例，不是经校勘的完整原文；本项目未复制其正文。",
}
_ZIWEI_EXCERPT: Final[TraditionalReferenceSource] = {
    "level": "upstream_excerpt",
    "label": "上游精选片段",
    "url": "https://github.com/Renhuai123/ziwei-doushu/blob/88194a404242bfe5c6d5cc512e4117e3e245cdd5/lib/classics/data/quanshu.ts",
    "note": "上游是结构化精选片段，不是完整古籍原文；本项目未把片段注入模型上下文。",
}


# This catalog describes provenance without bundling or quoting source texts.
TRADITIONAL_REFERENCE_BOOKS: Final[tuple[TraditionalReferenceBook, ...]] = (
    {
        "id": "qiong_tong_bao_dian",
        "title": "《穷通宝典》",
        "alias": "常见作《穷通宝鉴》",
        "focus": "论日主调候",
        "tradition": "子平命理",
        "source": _BAZI_SUMMARY,
    },
    {"id": "san_ming_tong_hui", "title": "《三命通会》", "alias": "", "focus": "论格局神煞", "tradition": "子平命理", "source": _BAZI_SUMMARY},
    {"id": "di_tian_sui", "title": "《滴天髓》", "alias": "", "focus": "论五行旺衰", "tradition": "子平命理", "source": _BAZI_SUMMARY},
    {"id": "yuan_hai_zi_ping", "title": "《渊海子平》", "alias": "", "focus": "论十神六亲", "tradition": "子平命理", "source": _BAZI_SUMMARY},
    {"id": "qian_li_ming_gao", "title": "《千里命稿》", "alias": "", "focus": "论命例实证", "tradition": "子平命理", "source": _BAZI_SUMMARY},
    {
        "id": "xie_ji_bian_fang_shu",
        "title": "《协纪辨方书》",
        "alias": "",
        "focus": "论择日神煞",
        "tradition": "历法择日",
        "source": _BAZI_SUMMARY,
    },
    {"id": "guo_lao_xing_zong", "title": "《果老星宗》", "alias": "", "focus": "论星命合参", "tradition": "星命术", "source": _BAZI_SUMMARY},
    {"id": "zi_ping_zhen_quan", "title": "《子平真诠》", "alias": "", "focus": "论用神格局", "tradition": "子平命理", "source": _BAZI_SUMMARY},
    {"id": "shen_feng_tong_kao", "title": "《神峰通考》", "alias": "", "focus": "论命理辨误", "tradition": "子平命理", "source": _BAZI_SUMMARY},
    {"id": "zhou_yi", "title": "《周易》", "alias": "", "focus": "论卦象与象数", "tradition": "经学象数", "source": _INDEX_ONLY},
    {
        "id": "ziwei_doushu_quan_shu",
        "title": "《紫微斗数全书》",
        "alias": "",
        "focus": "论星曜与宫位",
        "tradition": "紫微斗数",
        "source": _ZIWEI_EXCERPT,
    },
    {"id": "xing_ping_hui_hai", "title": "《星平会海》", "alias": "", "focus": "论星命合参与格局", "tradition": "星命术", "source": _INDEX_ONLY},
    {"id": "ming_li_yue_yan", "title": "《命理约言》", "alias": "", "focus": "论取用与格局", "tradition": "子平命理", "source": _INDEX_ONLY},
    {"id": "zao_hua_yuan_yuan", "title": "《造化元钥》", "alias": "", "focus": "论调候与五行气势", "tradition": "子平命理", "source": _INDEX_ONLY},
    {"id": "bu_shi_zheng_zong", "title": "《卜筮正宗》", "alias": "", "focus": "论六爻卦法", "tradition": "卜筮", "source": _INDEX_ONLY},
)

TRADITIONAL_REFERENCE_BOOKS_BY_ID: Final[dict[str, TraditionalReferenceBook]] = {
    item["id"]: item for item in TRADITIONAL_REFERENCE_BOOKS
}
TRADITIONAL_REFERENCE_BOOK_IDS: Final[frozenset[str]] = frozenset(TRADITIONAL_REFERENCE_BOOKS_BY_ID)
