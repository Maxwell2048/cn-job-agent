import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";
import { api } from "../api";
import { useData } from "../hooks";
import { Badge, Card, Empty, ErrorBox, Loading, Score, Stat } from "../components";
import { CATEGORY, RUN_STATUS, VERDICT, formatTime, label } from "../labels";
import StartCollection from "./StartCollection";

export default function Overview() {
  const overview = useData(() => api.overview());
  const model = useData(() => api.model());
  const insights = useData(() => api.insights());
  const navigate = useNavigate();
  const [starting, setStarting] = useState(false);

  if (overview.loading && !overview.data) return <Loading />;
  const o = overview.data;
  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>概览</h1>
          <p>搜索规划 Agent 采集岗位 → 筛选 Agent 判断能不能投 → 匹配 Agent 逐条找经历证据</p>
        </div>
        <div className="row">
          <button onClick={() => navigate("/postings?add=1")}>添加 JD</button>
          <button className="primary" onClick={() => setStarting(true)}>开始采集</button>
        </div>
      </div>
      <ErrorBox error={overview.error} />
      {starting && <StartCollection onClose={() => setStarting(false)} />}

      {o && (
        <div className="stats">
          <Stat label="待处理" value={o.postings.new ?? 0} hint="还没运行 Agent" />
          <Stat label="等你确认" value={o.postings.review ?? 0} tone={(o.postings.review ?? 0) > 0 ? "warn" : undefined} />
          <Stat label="已匹配" value={o.postings.matched ?? 0} tone="good" />
          <Stat label="已筛掉" value={o.postings.screened_out ?? 0} />
          <Stat label="企业 / 校招项目" value={`${o.companies} / ${o.programs}`} hint="2027 届窗口" />
        </div>
      )}

      <div className="grid grid-2">
        <Card title="语言模型">
          {model.data?.ok ? (
            <div className="stack" style={{ gap: 8 }}>
              <div className="row">
                <strong>{model.data.label}</strong>
                <span className="mono">{model.data.model}</span>
                <Badge tone={model.data.cloud ? "warn" : "good"}>{model.data.cloud ? "云端 API" : "本机"}</Badge>
              </div>
              <div className={model.data.cloud ? "notice warn" : "notice"}>{model.data.privacy}</div>
            </div>
          ) : model.data ? (
            <div className="error-box">模型不可用（{model.data.provider}）：{model.data.error}</div>
          ) : <Loading />}
        </Card>
        <Card title="求职画像">
          {o?.profile ? (
            <dl className="kv">
              <dt>岗位</dt><dd>{o.profile.roles.map((r) => r.label).join("、")}</dd>
              <dt>城市</dt><dd>{o.profile.cities.join("、")}</dd>
              <dt>渠道</dt><dd>{o.profile.channels.join("、")}</dd>
            </dl>
          ) : <Empty>还没有求职画像：运行 cn-agent profile</Empty>}
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="最近的 Agent 运行" actions={<Link to="/runs">全部</Link>}>
          {o?.recent_runs.length ? (
            <table>
              <tbody>
                {o.recent_runs.map((run) => (
                  <tr key={run.id}>
                    <td className="title-cell"><Link to={`/runs/${run.id}`}>{run.posting_title}</Link>
                      <div className="muted small">{formatTime(run.started_at)}</div></td>
                    <td><Badge value={run.status}>{label(RUN_STATUS, run.status)}</Badge></td>
                    <td className="nowrap"><Score score={run.score} compact /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <Empty>还没有运行</Empty>}
        </Card>

        <Card title="最常缺证据的要求" actions={<span className="muted small">所有已匹配岗位合计</span>}>
          {insights.data?.top_gaps.length ? (
            <ol className="stack" style={{ gap: 6, margin: 0, paddingLeft: 20 }}>
              {insights.data.top_gaps.slice(0, 8).map((gap) => (
                <li key={gap.text}>{gap.text} <span className="muted small">× {gap.count}</span></li>
              ))}
            </ol>
          ) : <Empty>匹配过的岗位多了，这里会列出最常出现的证据缺口</Empty>}
          {insights.data && Object.keys(insights.data.by_category).length > 0 && (
            <CategoryBars data={insights.data.by_category} />
          )}
        </Card>
      </div>

      <Card title="最近的采集" actions={<Link to="/collections">全部</Link>}>
        {o?.recent_collections.length ? (
          <table>
            <tbody>
              {o.recent_collections.map((c) => (
                <tr key={c.id}>
                  <td><Link to={`/collections/${c.id}`} className="mono">{c.id}</Link></td>
                  <td><Badge value={c.status === "done" ? "done" : c.status}>{c.mode === "agent" ? "Agent 模式" : "规则模式"}</Badge></td>
                  <td className="muted">搜索 {c.stats.searches ?? 0} 次 · 新保存 {c.stats.saved ?? 0} 个</td>
                  <td className="muted small nowrap">{formatTime(c.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty>还没有采集过</Empty>}
      </Card>
    </div>
  );
}

const COLORS: Record<string, string> = { direct: "var(--good)", related: "var(--warn)", insufficient: "var(--bad)", error: "var(--muted)" };

function CategoryBars({ data }: { data: Record<string, Record<string, number | undefined>> }) {
  const rows = Object.entries(data).filter(([category]) => category !== "responsibility");
  return (
    <div className="stack" style={{ gap: 8, marginTop: 16 }}>
      {rows.map(([category, verdicts]) => {
        const total = Object.values(verdicts).reduce<number>((a, b) => a + (b ?? 0), 0);
        return (
          <div key={category}>
            <div className="row spread small"><span>{label(CATEGORY, category)}</span><span className="muted">{total}</span></div>
            <div className="verdict-bar" aria-label={`${label(CATEGORY, category)}的判断分布`}>
              {["direct", "related", "insufficient", "error"].map((v) =>
                verdicts[v] ? <span key={v} style={{ width: `${(100 * (verdicts[v] ?? 0)) / total}%`, background: COLORS[v] }}
                                    title={`${label(VERDICT, v)} ${verdicts[v]}`} /> : null)}
            </div>
          </div>
        );
      })}
      <div className="legend">
        {["direct", "related", "insufficient"].map((v) => <span key={v}><i style={{ background: COLORS[v] }} />{label(VERDICT, v)}</span>)}
      </div>
    </div>
  );
}
