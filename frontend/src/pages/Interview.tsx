import { useState } from "react";
import { ApiError, api, type InterviewData, type MaterialsData, type RunDetail } from "../api";
import { useData, useEventStream } from "../hooks";
import { Badge, Card, Empty, ErrorBox, Loading } from "../components";
import { formatTime } from "../labels";

/** The interview-prep agent's output for a run: self introduction, project deep dives,
 *  technical questions, gap questions and questions to ask, personal claims cited. */
export default function Interview({ run }: { run: RunDetail | null }) {
  const runId = run?.status === "done" ? run.id : null;
  const prep = useData(async () => {
    if (!runId) return null;
    try {
      return await api.interview(runId);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  }, [runId]);
  const [job, setJob] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const events = useEventStream(job ? `/api/jobs/${job}/events` : null, !!job, () => {
    setJob(null);
    void prep.reload();
  });
  const failed = events.find((e) => e.node === "__error__") as { error?: string } | undefined;

  if (!run || run.status !== "done") return <Empty>先完成一次证据匹配，才能准备面试</Empty>;

  async function generate() {
    setError(null);
    try {
      setJob((await api.generateInterview(run!.id)).job);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const d = prep.data;
  return (
    <div className="stack">
      <div className="row spread">
        <p className="muted" style={{ margin: 0 }}>
          面试准备 Agent 按这份 JD 预测面试官会问什么；讲个人经历的回答要点都引用经历库原文，原理题只给提纲。
        </p>
        <button className="primary" onClick={generate} disabled={!!job}>
          {job ? <><span className="pulse" /> 准备中…</> : d ? "重新生成" : "准备面试"}
        </button>
      </div>
      <ErrorBox error={error ?? failed?.error ?? prep.error} />
      {prep.loading && !d ? <Loading /> : d ? <InterviewView d={d} runId={run.id} /> : !job && <Empty>还没有准备过面试</Empty>}
    </div>
  );
}

function InterviewView({ d, runId }: { d: InterviewData; runId: string }) {
  const draft = d.draft;
  return (
    <>
      <div className="row small muted">
        版本 {d.version} · {formatTime(d.created_at)} · {d.model}
        <a className="button" href={api.interviewFile(runId)}>下载 Markdown</a>
      </div>
      {d.warnings.length > 0 && <div className="notice warn">{d.warnings.map((w, i) => <div key={i}>{w}</div>)}</div>}

      {draft.self_intro.text && (
        <Card title="1 分钟自我介绍">
          <p style={{ margin: 0 }}>{draft.self_intro.text}</p>
          <Cites ids={draft.self_intro.cites} c={d.citations} />
        </Card>
      )}

      {draft.project_questions.length > 0 && (
        <Card title="项目深挖">
          {draft.project_questions.map((q, i) => (
            <article key={i} className="requirement">
              <div className="muted small">{d.project_titles[q.project_id] ?? q.project_id}</div>
              <h3>{q.question}</h3>
              <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                {q.answer_points.map((p, j) => <li key={j}>{p.text}<Cites ids={p.cites} c={d.citations} /></li>)}
              </ul>
            </article>
          ))}
        </Card>
      )}

      {draft.technical_questions.length > 0 && (
        <Card title="技术与原理">
          {draft.technical_questions.map((q, i) => (
            <article key={i} className="requirement">
              <h3>{q.question} <span className="muted small mono">{q.requirement_id}</span></h3>
              <p className="reason">{q.answer_outline}</p>
              {q.my_experience.text && <>
                <p style={{ margin: "6px 0 0" }}><Badge tone="good">我的相关经历</Badge> {q.my_experience.text}</p>
                <Cites ids={q.my_experience.cites} c={d.citations} />
              </>}
            </article>
          ))}
        </Card>
      )}

      {draft.gap_questions.length > 0 && (
        <Card title="缺口题怎么答" actions={<span className="muted small">没有直接证据的要求</span>}>
          {draft.gap_questions.map((q, i) => (
            <article key={i} className="requirement">
              <h3>{q.question}</h3>
              <p className="reason">{q.strategy.text}</p>
              <Cites ids={q.strategy.cites} c={d.citations} />
            </article>
          ))}
        </Card>
      )}

      {draft.questions_to_ask.length > 0 && (
        <Card title="可以反问的问题">
          <ul style={{ margin: 0, paddingLeft: 18 }}>{draft.questions_to_ask.map((q) => <li key={q}>{q}</li>)}</ul>
        </Card>
      )}
    </>
  );
}

function Cites({ ids, c }: { ids: string[]; c: MaterialsData["citations"] }) {
  if (!ids.length) return null;
  return (
    <div className="row" style={{ gap: 4, marginTop: 4 }}>
      {ids.map((id) => (
        <Badge key={id} tone="neutral">
          <span title={c[id] ? `${c[id].project} / ${c[id].section}（${c[id].source}:${c[id].line_start}-${c[id].line_end}）` : id}>
            {id}{c[id] ? ` · ${c[id].section.replace(/^我的(工作|贡献)\s*/, "")}` : ""}
          </span>
        </Badge>
      ))}
    </div>
  );
}
