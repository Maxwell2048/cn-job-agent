import { Fragment, useState } from "react";
import { ApiError, api, type MaterialsData, type RunDetail } from "../api";
import { useData, useEventStream } from "../hooks";
import { Badge, Card, Empty, ErrorBox, Loading } from "../components";
import { formatTime } from "../labels";

/** The materials agent's output for a run: Chinese resume and BOSS 直聘 greeting,
 *  every line with the experience sections it cites. */
export default function Materials({ run }: { run: RunDetail | null }) {
  const runId = run?.status === "done" ? run.id : null;
  const materials = useData(async () => {
    if (!runId) return null;
    try {
      return await api.materials(runId);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }
  }, [runId]);
  const [job, setJob] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const events = useEventStream(job ? `/api/jobs/${job}/events` : null, !!job, () => {
    setJob(null);
    void materials.reload();
  });
  const failed = events.find((e) => e.node === "__error__") as { error?: string } | undefined;

  if (!run || run.status !== "done") {
    return <Empty>先完成一次证据匹配（运行状态为"已完成"），才能生成申请材料</Empty>;
  }

  async function generate() {
    setError(null);
    try {
      setJob((await api.generateMaterials(run!.id)).job);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const m = materials.data;
  return (
    <div className="stack">
      <div className="row spread">
        <p className="muted" style={{ margin: 0 }}>
          材料 Agent 只用经历库里的原文写作，每条要点都标出引用；原文里没有的工具名和数字会被程序拦下重写。
          姓名、联系方式和教育背景在本机从简历底稿填入，不发给模型。
        </p>
        <button className="primary" onClick={generate} disabled={!!job}>
          {job ? <><span className="pulse" /> 生成中…</> : m ? "重新生成" : "生成中文简历和打招呼语"}
        </button>
      </div>
      <ErrorBox error={error ?? failed?.error ?? materials.error} />
      {materials.loading && !m ? <Loading /> : m ? <MaterialsView m={m} runId={run.id} /> : !job && (
        <Empty>还没有生成过申请材料</Empty>
      )}
    </div>
  );
}

function MaterialsView({ m, runId }: { m: MaterialsData; runId: string }) {
  const d = m.draft;
  const [copied, setCopied] = useState(false);
  const greeting = d.greeting.text;

  return (
    <>
      <div className="row small muted">
        版本 {m.version} · {formatTime(m.created_at)} · {m.model}
        {m.files.includes("resume_zh.docx") && <a className="button" href={api.materialFile(runId, "resume_zh.docx")}>下载 Word</a>}
        {m.files.includes("resume_zh.md") && <a className="button" href={api.materialFile(runId, "resume_zh.md")}>下载 Markdown</a>}
      </div>
      {m.warnings.length > 0 && (
        <div className="notice warn">{m.warnings.map((w, i) => <div key={i}>{w}</div>)}</div>
      )}

      <Card title="BOSS 直聘打招呼语" actions={<>
        <span className={greeting.length > 150 ? "badge tone-bad" : "muted small"}>{greeting.length} 字</span>
        <button onClick={async () => { await navigator.clipboard.writeText(greeting); setCopied(true); }}>
          {copied ? "已复制" : "复制"}
        </button>
      </>}>
        {greeting ? <p style={{ margin: 0 }}>{greeting}</p> : <Empty>打招呼语没有通过校验，请重新生成</Empty>}
        <Cites ids={d.greeting.cites} m={m} />
      </Card>

      <Card title="定制简历">
        <div className="stack" style={{ gap: 14 }}>
          {d.target_title && <div><strong>求职意向：</strong>{d.target_title.replace(/^求职意向[:：]\s*/, "")}</div>}
          {d.summary.text && <div>
            <h3>个人简介</h3>
            <p style={{ margin: "4px 0 0" }}>{d.summary.text}</p>
            <Cites ids={d.summary.cites} m={m} />
          </div>}
          <div>
            <h3>项目经历</h3>
            {d.projects.map((p) => (
              <article key={p.project_id} className="requirement" style={{ marginTop: 8 }}>
                <div className="row spread">
                  <strong>{p.title}</strong>
                  <span className="muted small">{[p.role, p.period].filter(Boolean).join(" · ")}</span>
                </div>
                <ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>
                  {p.bullets.map((b, i) => (
                    <li key={i} style={{ marginBottom: 6 }}>
                      <strong>{b.label}：</strong>{b.text}
                      <Cites ids={b.cites} m={m} />
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
          {m.skills.length > 0 && <div>
            <h3>专业技能 <span className="muted small">（底稿里你确认过的条目，按这份 JD 的相关度排序）</span></h3>
            <dl className="kv" style={{ marginTop: 6 }}>
              {m.skills.map(([group, items]) => <Fragment key={group}><dt>{group}</dt><dd>{items}</dd></Fragment>)}
            </dl>
          </div>}
        </div>
      </Card>

      {m.gaps.length > 0 && (
        <Card title="这份 JD 里还缺证据的要求" actions={<span className="muted small">面试前准备怎么回答</span>}>
          <ul style={{ margin: 0, paddingLeft: 18 }}>{m.gaps.map((g) => <li key={g}>{g}</li>)}</ul>
        </Card>
      )}
    </>
  );
}

function Cites({ ids, m }: { ids: string[]; m: MaterialsData }) {
  if (!ids.length) return null;
  return (
    <div className="row" style={{ gap: 4, marginTop: 4 }}>
      {ids.map((id) => {
        const c = m.citations[id];
        return (
          <Badge key={id} tone="neutral">
            <span title={c ? `${c.project} / ${c.section}（${c.source}:${c.line_start}-${c.line_end}）` : id}>
              {id}{c ? ` · ${c.section.replace(/^我的(工作|贡献)\s*/, "")}` : ""}
            </span>
          </Badge>
        );
      })}
    </div>
  );
}
