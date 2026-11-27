import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Match, type PostingDetail as Detail, type RunDetail } from "../api";
import { useData } from "../hooks";
import Materials from "./Materials";
import { Badge, Card, Empty, ErrorBox, Loading, Modal, Quote, Score, Tabs } from "../components";
import {
  CATEGORY, CHANNEL, COHORT, DECISION, IMPORTANCE, RUN_STATUS, SEVERITY, SOURCE, VERDICT,
  formatTime, label,
} from "../labels";

type Tab = "matches" | "materials" | "screening" | "company" | "jd" | "runs";

export default function PostingDetail() {
  const { id } = useParams();
  const posting = useData(() => api.posting(id!), [id]);
  const [tab, setTab] = useState<Tab>("matches");
  const p = posting.data;

  if (posting.loading && !p) return <Loading />;
  if (!p) return <ErrorBox error={posting.error ?? "没有这个岗位"} />;
  const run = p.latest;

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <div className="muted small"><Link to="/postings">岗位</Link> / {p.id}</div>
          <h1>{p.title}</h1>
          <p>
            {p.company || "未填公司"} · {p.city || "城市未填"} · {label(CHANNEL, p.channel)} · {label(SOURCE, p.source)}
            {p.url && <> · <a href={p.url} target="_blank" rel="noreferrer">原文链接</a></>}
          </p>
        </div>
        <Actions posting={p} run={run} onChanged={() => void posting.reload()} />
      </div>
      <ErrorBox error={posting.error} />

      {run && <Summary run={run} />}

      <Card>
        <Tabs<Tab> active={tab} onChange={setTab} tabs={[
          { key: "matches", label: `逐条要求${run?.matches.length ? `（${run.matches.length}）` : ""}` },
          { key: "materials", label: "申请材料" },
          { key: "screening", label: "筛选结果" },
          { key: "company", label: "企业校招窗口" },
          { key: "jd", label: "JD 原文" },
          { key: "runs", label: `运行记录（${p.runs.length}）` },
        ]} />
        {tab === "matches" && (run?.matches.length ? <Requirements matches={run.matches} />
          : <Empty>{run ? "这次运行没有做证据匹配（被筛掉、等确认或失败）" : "还没有运行 Agent"}</Empty>)}
        {tab === "materials" && <Materials run={run} />}
        {tab === "screening" && <Screening run={run} />}
        {tab === "company" && <CompanyPrograms posting={p} />}
        {tab === "jd" && <pre className="jd">{p.jd_text}</pre>}
        {tab === "runs" && <RunList posting={p} />}
      </Card>
    </div>
  );
}

function Actions({ posting, run, onChanged }: { posting: Detail; run: RunDetail | null; onChanged: () => void }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<string | null>(null);

  async function act(work: () => Promise<{ run_id: string }>) {
    setBusy(true);
    setError(null);
    try {
      const { run_id } = await work();
      navigate(`/runs/${run_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
      onChanged();
    }
  }

  return (
    <div className="stack" style={{ gap: 8, alignItems: "flex-end" }}>
      <div className="row">
        {run?.status === "running" && <Link className="button" to={`/runs/${run.id}`}><span className="pulse" /> 查看实时轨迹</Link>}
        {run?.status === "interrupted" && <>
          <button className="good" disabled={busy} onClick={() => act(() => api.resume(run.id, true))}>批准，继续匹配</button>
          <button className="danger" disabled={busy} onClick={() => act(() => api.resume(run.id, false))}>放弃</button>
        </>}
        {run?.status === "failed" && <button disabled={busy} onClick={() => act(() => api.resume(run.id, null))}>从断点重试</button>}
        {run?.has_report && <button onClick={async () => setReport(await api.report(run.id))}>查看报告</button>}
        {(!run || ["done", "rejected", "failed"].includes(run.status)) && (
          <button className={run ? "" : "primary"} disabled={busy}
                  onClick={() => act(() => api.startRun(posting.id, { force: run?.status === "rejected" }))}>
            {run ? (run.status === "rejected" ? "强制匹配" : "重新运行") : "运行 Agent"}
          </button>
        )}
      </div>
      <ErrorBox error={error} />
      {report !== null && <Modal title="匹配报告（Markdown）" onClose={() => setReport(null)}><pre className="report">{report}</pre></Modal>}
    </div>
  );
}

function Summary({ run }: { run: RunDetail }) {
  const c = run.counts;
  return (
    <div className="stats">
      <div className="stat">
        <div className="stat-label">最近一次运行</div>
        <div className="row" style={{ marginTop: 6 }}>
          <Badge value={run.status}>{label(RUN_STATUS, run.status)}</Badge>
          {run.decision && <Badge value={run.decision}>筛选：{label(DECISION, run.decision)}</Badge>}
        </div>
        <div className="stat-hint"><Link to={`/runs/${run.id}`}>Agent 轨迹</Link> · {formatTime(run.started_at)}</div>
      </div>
      <div className="stat">
        <div className="stat-label">证据覆盖</div>
        <div style={{ marginTop: 8 }}><Score score={run.score} label={run.label} /></div>
        <div className="stat-hint">不是录用概率</div>
      </div>
      <div className="stat">
        <div className="stat-value">{run.required_total ? `${run.required_covered}/${run.required_total}` : "—"}</div>
        <div className="stat-label">必需条件有证据</div>
      </div>
      {c && <div className="stat">
        <div className="row" style={{ gap: 6 }}>
          <Badge value="direct">直接 {c.direct}</Badge><Badge value="related">相关 {c.related}</Badge>
          <Badge value="insufficient">不足 {c.insufficient}</Badge>{c.error > 0 && <Badge value="error">失败 {c.error}</Badge>}
        </div>
        <div className="stat-label" style={{ marginTop: 6 }}>逐条判断</div>
      </div>}
    </div>
  );
}

const ORDER: Record<string, number> = { required: 0, unspecified: 1, preferred: 2 };

function Requirements({ matches }: { matches: Match[] }) {
  const [filter, setFilter] = useState("all");
  const [showDuties, setShowDuties] = useState(false);
  const rows = useMemo(() => matches
    .filter((m) => showDuties || m.category !== "responsibility")
    .filter((m) => filter === "all" || (m.verdict ?? "error") === filter)
    .sort((a, b) => ORDER[a.importance] - ORDER[b.importance] || a.requirement_id.localeCompare(b.requirement_id)),
  [matches, filter, showDuties]);

  return (
    <div>
      <div className="row spread" style={{ marginBottom: 12 }}>
        <div className="row">
          {["all", "direct", "related", "insufficient"].map((v) => (
            <button key={v} className={filter === v ? "primary" : ""} onClick={() => setFilter(v)}>
              {v === "all" ? "全部" : label(VERDICT, v)}
            </button>
          ))}
        </div>
        <label className="row small muted">
          <input type="checkbox" style={{ width: "auto" }} checked={showDuties} onChange={(e) => setShowDuties(e.target.checked)} />
          显示岗位职责类要求
        </label>
      </div>
      {rows.length ? rows.map((m) => <Requirement key={m.requirement_id} m={m} />) : <Empty>没有符合筛选的要求</Empty>}
    </div>
  );
}

function Requirement({ m }: { m: Match }) {
  return (
    <article className="requirement">
      <h3>
        <span className="muted mono small">{m.requirement_id}</span>
        <Badge value={m.verdict ?? "error"}>{label(VERDICT, m.verdict ?? "error")}</Badge>
        <Badge tone={m.importance === "required" ? "accent" : "neutral"}>{label(IMPORTANCE, m.importance)}</Badge>
        <span>{m.text}</span>
        <span className="muted small">{label(CATEGORY, m.category)}</span>
      </h3>
      {m.reason && <p className="reason">{m.reason}</p>}
      {m.evidence.map((e) => (
        <Quote key={e.candidate_id + e.quote}
               source={`${e.project} / ${e.section}（${e.source}:${e.line_start}-${e.line_end}）`}>{e.quote}</Quote>
      ))}
      {m.missing_aspects.length > 0 && <p className="missing">未覆盖：{m.missing_aspects.join("；")}</p>}
      {m.questions_for_user.length > 0 && <p className="reason">可以向你确认：{m.questions_for_user.join("；")}</p>}
      {m.errors.length > 0 && <p className="reason small">处理提示：{m.errors.join("；")}</p>}
    </article>
  );
}

function Screening({ run }: { run: RunDetail | null }) {
  const flags = run?.screening.flags ?? [];
  if (!run) return <Empty>还没有运行 Agent</Empty>;
  if (!flags.length) return <Empty>没有需要注意的条件</Empty>;
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>级别</th><th>说明</th><th>JD 原文</th></tr></thead>
        <tbody>
          {flags.map((f, i) => (
            <tr key={i}>
              <td><Badge value={f.severity}>{label(SEVERITY, f.severity)}</Badge></td>
              <td>{f.message}</td>
              <td className="muted small">{f.quote || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CompanyPrograms({ posting }: { posting: Detail }) {
  const company = posting.company_detail;
  if (!company) return <Empty>这个岗位没有关联到已收录的企业</Empty>;
  return (
    <div className="stack" style={{ gap: 10 }}>
      <div className="muted">{company.name} · 渠道 {company.portal || "—"}</div>
      {company.programs.length ? company.programs.map((program) => (
        <article key={program.title} className="requirement">
          <h3><Badge value={program.verdict}>{label(COHORT, program.verdict)}</Badge>{program.title}</h3>
          <p className="reason">{program.verdict_reason}</p>
          <dl className="kv" style={{ marginTop: 8 }}>
            <dt>毕业窗口</dt><dd>{program.window_text || "—"}</dd>
            <dt>状态</dt><dd>{program.status_text || "—"}</dd>
            {program.apply_limit && <><dt>投递限制</dt><dd>{program.apply_limit}</dd></>}
            {program.requirements.length > 0 && <><dt>条件</dt><dd>{program.requirements.join("；")}</dd></>}
          </dl>
        </article>
      )) : <Empty>没有收录校招窗口</Empty>}
    </div>
  );
}

function RunList({ posting }: { posting: Detail }) {
  if (!posting.runs.length) return <Empty>还没有运行</Empty>;
  return (
    <table>
      <thead><tr><th>运行</th><th>状态</th><th>筛选</th><th>证据覆盖</th><th>开始时间</th></tr></thead>
      <tbody>
        {posting.runs.map((r) => (
          <tr key={r.id}>
            <td><Link className="mono small" to={`/runs/${r.id}`}>{r.id}</Link></td>
            <td><Badge value={r.status}>{label(RUN_STATUS, r.status)}</Badge></td>
            <td>{label(DECISION, r.decision)}</td>
            <td><Score score={r.score} /></td>
            <td className="small muted">{formatTime(r.started_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

