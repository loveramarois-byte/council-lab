from __future__ import annotations

from typing import Final, TypedDict


class TraditionalReferenceBook(TypedDict):
    id: str
    title: str
    alias: str
    focus: str
    tradition: str


# This is a metadata index only. Council does not bundle or quote the source texts.
TRADITIONAL_REFERENCE_BOOKS: Final[tuple[TraditionalReferenceBook, ...]] = (
    {
        "id": "qiong_tong_bao_dian",
        "title": "《穷通宝典》",
        "alias": "常见作《穷通宝鉴》",
        "focus": "论日主调候",
        "tradition": "子平命理",
    },
    {"id": "san_ming_tong_hui", "title": "《三命通会》", "alias": "", "focus": "论格局神煞", "tradition": "子平命理"},
    {"id": "di_tian_sui", "title": "《滴天髓》", "alias": "", "focus": "论五行旺衰", "tradition": "子平命理"},
    {"id": "yuan_hai_zi_ping", "title": "《渊海子平》", "alias": "", "focus": "论十神六亲", "tradition": "子平命理"},
    {"id": "qian_li_ming_gao", "title": "《千里命稿》", "alias": "", "focus": "论命例实证", "tradition": "子平命理"},
    {
        "id": "xie_ji_bian_fang_shu",
        "title": "《协纪辨方书》",
        "alias": "",
        "focus": "论择日神煞",
        "tradition": "历法择日",
    },
    {"id": "guo_lao_xing_zong", "title": "《果老星宗》", "alias": "", "focus": "论星命合参", "tradition": "星命术"},
    {"id": "zi_ping_zhen_quan", "title": "《子平真诠》", "alias": "", "focus": "论用神格局", "tradition": "子平命理"},
    {"id": "shen_feng_tong_kao", "title": "《神峰通考》", "alias": "", "focus": "论命理辨误", "tradition": "子平命理"},
    {"id": "zhou_yi", "title": "《周易》", "alias": "", "focus": "论卦象与象数", "tradition": "经学象数"},
    {
        "id": "ziwei_doushu_quan_shu",
        "title": "《紫微斗数全书》",
        "alias": "",
        "focus": "论星曜与宫位",
        "tradition": "紫微斗数",
    },
    {"id": "xing_ping_hui_hai", "title": "《星平会海》", "alias": "", "focus": "论星命合参与格局", "tradition": "星命术"},
    {"id": "ming_li_yue_yan", "title": "《命理约言》", "alias": "", "focus": "论取用与格局", "tradition": "子平命理"},
    {"id": "zao_hua_yuan_yuan", "title": "《造化元钥》", "alias": "", "focus": "论调候与五行气势", "tradition": "子平命理"},
    {"id": "bu_shi_zheng_zong", "title": "《卜筮正宗》", "alias": "", "focus": "论六爻卦法", "tradition": "卜筮"},
)

TRADITIONAL_REFERENCE_BOOKS_BY_ID: Final[dict[str, TraditionalReferenceBook]] = {
    item["id"]: item for item in TRADITIONAL_REFERENCE_BOOKS
}
TRADITIONAL_REFERENCE_BOOK_IDS: Final[frozenset[str]] = frozenset(TRADITIONAL_REFERENCE_BOOKS_BY_ID)
