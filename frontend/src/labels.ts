// Display labels in Chinese for the values the API returns.

export const POSTING_STATUS: Record<string, string> = {
  new: "待处理", review: "待确认", screened_out: "已筛掉", matched: "已匹配", failed: "失败",
};

export const RUN_STATUS: Record<string, string> = {
  running: "运行中", interrupted: "等你确认", rejected: "已结束（未匹配）", done: "已完成", failed: "失败",
};

export const DECISION: Record<string, string> = {
  pass: "通过", review: "需人工确认", reject: "筛掉", error: "处理失败",
};

export const VERDICT: Record<string, string> = {
  direct: "直接支持", related: "相关但不足", insufficient: "证据不足", error: "处理失败",
};

export const IMPORTANCE: Record<string, string> = { required: "必需", preferred: "优先", unspecified: "未注明" };

export const SEVERITY: Record<string, string> = { hard: "硬性不符", soft: "需确认", info: "提示" };

export const CATEGORY: Record<string, string> = {
  technical_skill: "技术技能", responsibility: "岗位职责", experience: "经验", education: "学历",
  certification: "证书", work_authorization: "工作资格", location: "地点", other: "其他",
};

export const CHANNEL: Record<string, string> = { campus: "校招", social: "社招", unknown: "未识别" };

export const SECTOR: Record<string, string> = {
  internet: "互联网和科技", hardware: "通信、硬件和制造", bank: "银行和金融科技", soe: "运营商和央国企", foreign: "外企",
};

export const COHORT: Record<string, string> = {
  eligible: "符合", boundary: "卡在边界", likely: "大概率符合", conditional: "有条件", unknown: "待核实", ineligible: "不符合",
};

export const NODE: Record<string, string> = {
  __start__: "开始", __end__: "结束", __resume__: "继续运行", __interrupt__: "暂停等你确认",
  load_posting: "读取岗位", rule_screen: "规则筛选", extract: "提取要求", decide: "汇总决策",
  human_review: "人工确认", match_one: "证据匹配", summarize: "汇总评分", finalize: "报告入库",
  search: "搜索", save: "保存岗位",
};

export const SOURCE: Record<string, string> = {
  tencent: "腾讯校招", "zhiye:iflytek": "科大讯飞校招", "zhiye:transsion": "传音校招",
  manual: "手动", web: "网页添加", file: "文件", clipboard: "剪贴板", stdin: "粘贴",
};

export const label = (table: Record<string, string>, key: string | null | undefined) =>
  key == null ? "—" : table[key] ?? key;

export function formatTime(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

export function duration(start: string | null | undefined, end: string | null | undefined) {
  if (!start || !end) return "";
  const seconds = Math.round((new Date(end).getTime() - new Date(start).getTime()) / 1000);
  return seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
}
