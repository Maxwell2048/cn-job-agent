import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type LiveEvent, type RunDetail } from "../api";
import { useData, useEventStream } from "../hooks";
import GraphView, { type NodeState } from "../GraphView";
import { Badge, Card, Empty, ErrorBox, Loading, Modal, Score } from "../components";
import { DECISION, NODE, RUN_STATUS, SEVERITY, VERDICT, duration, formatTime, label } from "../labels";

export default function RunTrace() {
  const { id } = useParams();
  const run = useData(() => api.run(id!), [id]);
  const graph = useData(() => api.graph());
  const [streaming, setStreaming] = useState(true);
  const live = run.data?.status === "running" && streaming;
  const events = useEventStream(`/api/runs/${id}/events`, live, () => {
    setStreaming(false);
    void run.reload();
  });

  const state = useMemo(() => nodeState(run.data, events, live), [run.data, events, live]);
  const r = run.data;
  if (run.loading && !r) return <Loading />;
  if (!r) return <ErrorBox error={run.error ?? "没有这个运行"} />;

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <div className="muted small"><Link to="/runs">Agent 运行</Link> / <span className="mono">{r.id}</span></div>
          <h1>Agent 轨迹</h1>
          <p><Link to={`/postings/${r.posting_id}`}>{r.posting_title}</Link> · 开始于 {formatTime(r.started_at)}
            {r.finished_at && <> · 用时 {duration(r.started_at, r.finished_at)}</>}</p>
        </div>
        <div className="row">
          {live && <span className="row small"><span className="pulse" /> 实时更新中</span>}
          <Badge value={r.status}>{label(RUN_STATUS, r.status)}</Badge>
        </div>
      </div>
      <ErrorBox error={r.error || null} />
      {r.status === "interrupted" && <Review run={r} onResumed={() => { setStreaming(true); void run.reload(); }} />}

      <div className="grid grid-trace">
        <Card title="LangGraph 执行路径" actions={<span className="muted small">虚线是条件分支 · 蓝色是走过的路径</span>}>
          {graph.data ? <GraphView graph={graph.data} state={state} /> : <Loading />}
        </Card>
        <div className="stack">
          <Outcome run={r} />
          <Card title={live || events.length ? "实时事件" : "节点耗时"}>
            <Timeline run={r} events={events} />
          </Card>
        </div>
      </div>
    </div>
  );
}

function nodeState(run: RunDetail | null, events: LiveEvent[], live: boolean): NodeState {
  const visited = new Set<string>();
  const counts: Record<string, number> = {};
  const seconds: Record<string, number> = {};
  for (const step of run?.trace ?? []) {
    visited.add(step.node);
    counts[step.node] = (counts[step.node] ?? 0) + 1;
    if (step.seconds != null && step.node !== "match_one") seconds[step.node] = (seconds[step.node] ?? 0) + step.seconds;
  }
  const liveNodes = events.map((e) => e.node).filter((n) => !n.startsWith("__"));
  if (live) {
    for (const node of liveNodes) visited.add(node);
    const matched = liveNodes.filter((n) => n === "match_one").length;
    if (matched) counts.match_one = Math.max(counts.match_one ?? 0, matched);
  }
  if (visited.size || live) visited.add("__start__");
  if (run && ["done", "rejected"].includes(run.status)) visited.add("__end__");
  const order = [...(run?.trace ?? []).map((s) => s.node), ...(live ? liveNodes : [])];
  return {
    visited, counts, seconds, order,
    active: live ? liveNodes[liveNodes.length - 1] ?? "__start__" : null,
    waiting: run?.status === "interrupted" ? "human_review" : null,
  };
}

function Review({ run, onResumed }: { run: RunDetail; onResumed: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const flags = (run.screening.flags ?? []).filter((f) => f.severity !== "info");

  async function answer(approve: boolean) {
    setBusy(true);
    try {
      await api.resume(run.id, approve);
      onResumed();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Agent 暂停了，等你确认" className="review-card">
      <p className="muted" style={{ marginTop: 0 }}>筛选发现下面的条件需要你判断；批准后继续做逐条证据匹配，放弃则直接出报告。</p>
      <ul>
        {flags.map((f, i) => (
          <li key={i}><Badge value={f.severity}>{label(SEVERITY, f.severity)}</Badge> {f.message}
            {f.quote && <div className="muted small">JD 原文：{f.quote}</div>}</li>
        ))}
      </ul>
      <ErrorBox error={error} />
      <div className="row">
        <button className="good" disabled={busy} onClick={() => answer(true)}>批准，继续匹配</button>
        <button className="danger" disabled={busy} onClick={() => answer(false)}>放弃</button>
      </div>
    </Card>
  );
}

function Outcome({ run }: { run: RunDetail }) {
  const [report, setReport] = useState<string | null>(null);
  return (
    <Card title="结果" actions={run.has_report && <button onClick={async () => setReport(await api.report(run.id))}>查看报告</button>}>
      <dl className="kv">
        <dt>筛选</dt><dd>{run.decision ? <Badge value={run.decision}>{label(DECISION, run.decision)}</Badge> : "—"}</dd>
        <dt>证据覆盖</dt><dd><Score score={run.score} label={run.label} /></dd>
        <dt>必需条件</dt><dd>{run.required_total ? `${run.required_covered}/${run.required_total} 有证据` : "—"}</dd>
        <dt>逐条判断</dt><dd>{run.counts ? `直接 ${run.counts.direct} · 相关 ${run.counts.related} · 不足 ${run.counts.insufficient}` : "—"}</dd>
        <dt>模型</dt><dd className="mono small">{String(run.versions.model ?? "—")}{run.versions.provider ? ` · ${run.versions.provider}` : ""}</dd>
      </dl>
      {report !== null && <Modal title="匹配报告（Markdown）" onClose={() => setReport(null)}><pre className="report">{report}</pre></Modal>}
    </Card>
  );
}

function Timeline({ run, events }: { run: RunDetail; events: LiveEvent[] }) {
  if (events.length) {
    return (
      <ul className="timeline" aria-live="polite">
        {events.map((e, i) => (
          <li key={i}>
            <span className="time">{e.at ? new Date(e.at).toLocaleTimeString("zh-CN") : ""}</span>
            <strong>{label(NODE, e.node)}</strong>
            <span className="muted">{describe(e)}</span>
          </li>
        ))}
      </ul>
    );
  }
  if (!run.trace.length) return <Empty>还没有节点完成</Empty>;
  return (
    <ul className="timeline">
      {run.trace.map((step, i) => (
        <li key={i}>
          <span className="time">{step.seconds != null ? `${step.seconds.toFixed(1)} 秒` : ""}</span>
          <strong>{label(NODE, step.node)}</strong>
          <span className="muted mono small">{step.requirement ?? ""}</span>
        </li>
      ))}
    </ul>
  );
}

function describe(e: LiveEvent) {
  switch (e.node) {
    case "extract": return `提取出 ${e.requirements ?? 0} 条要求`;
    case "decide": return `筛选：${label(DECISION, e.decision)}`;
    case "match_one": return `${e.requirement_id} ${label(VERDICT, e.verdict ?? "error")} · ${e.text ?? ""}`;
    case "summarize": return e.score != null ? `${e.score} 分（${e.label}）` : "";
    case "__interrupt__": return e.question ?? "";
    case "__resume__": return e.approved ? "你批准了继续" : e.approved === false ? "你选择放弃" : "从断点重试";
    case "human_review": return e.approved ? "已批准" : "未批准";
    default: return "";
  }
}
