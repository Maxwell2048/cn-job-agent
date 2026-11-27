# 数据分析 Agent：自然语言查询销售数据

## 基本信息
- 项目类型：个人项目（虚构演示数据）。
- 时间：2026-01 至 2026-04。
- 团队规模：1 人。
- 技术栈：Python、LangGraph、LangChain、SQLite、pandas、matplotlib。

## 我的工作 工具调用 Agent 设计
我用 LangGraph 搭了一个数据分析 Agent：模型通过三个工具完成任务——查看表结构、执行只读 SQL 查询、生成图表。我限制 SQL 工具只能执行 SELECT 语句并限制返回行数，防止误改数据；查询出错时把错误信息交回模型重写。
结果：在 30 个自建的业务问题上，Agent 一次给出正确答案的有 24 个，加上一次纠错重试后为 27 个。
相关能力：LangGraph, LangChain tool calling, agent design, SQL, guardrails, error recovery.

## 我的工作 结果解释与可视化
我让 Agent 在回答里说明用了哪条 SQL、查询到多少行数据，并用 pandas 和 matplotlib 生成折线图或柱状图，方便非技术人员核对结论。
结果：每个回答都附带可复现的 SQL 和图表文件。
相关能力：pandas, matplotlib, data visualisation, explainability.
