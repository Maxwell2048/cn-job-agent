import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type CollectionDetail as Detail } from "../api";
import { useData, useEventStream } from "../hooks";
import { Badge, Card, Empty, ErrorBox, Loading, Stat } from "../components";
import { SOURCE, duration, formatTime, label } from "../labels";

export default function CollectionDetail() {
  const { id } = useParams();
  const collection = useData(() => api.collection(id!), [id]);
  const [streaming, setStreaming] = useState(true);
  const live = collection.data?.status === "running" && streaming;
  const events = useEventStream(`/api/collections/${id}/events`, live, () => {
    setStreaming(false);
    void collection.reload();
  });
  const c = collection.data;
  if (collection.loading && !c) return <Loading />;
  if (!c) return <ErrorBox error={collection.error ?? "没有这次采集"} />;

  const searches = live ? events.filter((e) => e.node === "search") : [];
  const saves = live ? events.filter((e) => e.node === "save") : [];

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <div className="muted small"><Link to="/collections">采集</Link> / <span className="mono">{c.id}</span></div>
          <h1>{c.mode === "agent" ? "Agent 模式采集" : c.mode === "rules" ? "规则模式采集" : "采集"}</h1>
          <p>开始于 {formatTime(c.started_at)}{c.finished_at && <> · 用时 {duration(c.started_at, c.finished_at)}</>}</p>
        </div>
        {live ? <span className="row small"><span className="pulse" /> 采集中</span>
              : <Badge value={c.status}>{c.status === "done" ? "完成" : c.status}</Badge>}
      </div>
      <ErrorBox error={c.error || null} />

      <div className="stats">
        <Stat label="搜索次数" value={live ? searches.length : c.stats.searches ?? 0} />
        <Stat label="看到的岗位" value={c.stats.seen ?? "—"} />
        <Stat label="新保存" value={live ? saves.length : c.stats.saved ?? 0} tone="good" />
        <Stat label="已存在" value={c.stats.duplicates ?? 0} />
      </div>

      <div className="grid grid-2">
        <Card title="保存的岗位">
          <Saved items={live ? saves.map((e) => ({ posting_id: e.posting_id!, id: "", title: e.title ?? "",
                                                   reason: "", source: e.source ?? "" })) : c.saved} />
        </Card>
        <Card title={c.mode === "agent" ? "Agent 的工具调用" : "执行过程"}>
          <AgentTrace detail={c} />
        </Card>
      </div>

      <Card title="搜索计划">
        {(live ? searches : c.plan).length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>网站</th><th>关键词</th><th>结果</th><th>在目标城市</th></tr></thead>
              <tbody>
                {(live ? searches : c.plan).map((row, i) => (
                  <tr key={i}>
                    <td>{label(SOURCE, row.source ?? "")}</td>
                    <td>{row.keyword}</td>
                    <td>{row.hits ?? 0}</td>
                    <td>{"in_target_city" in row ? (row as { in_target_city?: number }).in_target_city ?? "—" : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>还没有搜索</Empty>}
      </Card>
    </div>
  );
}

function Saved({ items }: { items: Detail["saved"] }) {
  if (!items.length) return <Empty>这次没有新保存的岗位</Empty>;
  return (
    <ul className="stack" style={{ gap: 10, margin: 0, padding: 0, listStyle: "none" }}>
      {items.map((s) => (
        <li key={s.posting_id}>
          <Link to={`/postings/${s.posting_id}`}><strong>{s.title}</strong></Link>
          <span className="muted small"> · {label(SOURCE, s.source)}</span>
          {s.reason && <div className="muted small">{s.reason}</div>}
        </li>
      ))}
    </ul>
  );
}

function AgentTrace({ detail }: { detail: Detail }) {
  if (!detail.trace.length) return <Empty>完成后显示</Empty>;
  return (
    <ul className="timeline">
      {detail.trace.map((step, i) => (
        <li key={i}>
          <span className="time">{i + 1}</span>
          <strong>{step.type === "tool_call" ? `调用 ${step.tool}` : step.type === "tool_result" ? `${step.tool} 返回`
            : step.type === "answer" ? "Agent 总结" : step.type === "fallback" ? "改用规则" : "规则计划"}</strong>
          <span className="muted small" style={{ wordBreak: "break-all" }}>
            {step.args ? JSON.stringify(step.args) : step.text ?? (step.keywords ?? []).join("、")}
          </span>
        </li>
      ))}
    </ul>
  );
}
