"""City matching between a programme's locations and the cities in a profile.

Programmes list cities ("杭州"), provinces ("浙江") or nationwide wording
("各省公司", "境内分行"). A province or nationwide entry is a weaker match:
the actual posting may be in another city of that province.
"""
NATIONWIDE = ("各省", "全国", "境内分行", "非京沪分行", "上海以外的省直分行")

PROVINCE = {
    "苏州": "江苏", "南京": "江苏", "无锡": "江苏",
    "武汉": "湖北",
    "深圳": "广东", "广州": "广东", "东莞": "广东", "佛山": "广东", "珠海": "广东", "惠州": "广东",
    "杭州": "浙江",
    "成都": "四川", "西安": "陕西", "合肥": "安徽", "长沙": "湖南", "重庆": "重庆",
    "厦门": "福建", "福州": "福建", "宁德": "福建",
}

CITY, IN_PROVINCE, NATION = "city", "province", "nationwide"
LABELS = {CITY: "城市", IN_PROVINCE: "同省", NATION: "全国性"}


def match(program_cities, wanted):
    """(kind, matched) for the strongest match, or (None, []) when none."""
    listed = list(program_cities or [])
    direct = [c for c in wanted if c in listed]
    if direct:
        return CITY, direct
    provinces = [c for c in wanted if PROVINCE.get(c) and any(PROVINCE[c] in entry for entry in listed)]
    if provinces:
        return IN_PROVINCE, provinces
    if any(token in entry for entry in listed for token in NATIONWIDE):
        return NATION, list(wanted)
    return None, []
