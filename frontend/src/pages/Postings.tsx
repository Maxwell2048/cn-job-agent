import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, type PostingBrief } from "../api";
import { useData } from "../hooks";
import { Badge, Card, Empty, ErrorBox, Loading, Modal, Score, Tabs } from "../components";
import { CHANNEL, POSTING_STATUS, SOURCE, label } from "../labels";

const FILTERS = [
  { key: "", label: "全部" }, { key: "review", label: "等你确认" }, { key: "matched", label: "已匹配" },
  { key: "new", label: "待处理" }, { key: "screened_out", label: "已筛掉" }, { key: "failed", label: "失败" },
];

export default function Postings() {
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "";
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"score" | "newest">("score");
  const postings = useData(() => api.postings({ status }), [status]);
  const adding = params.get("add") === "1";

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = (postings.data ?? []).filter((p) =>
      !q || [p.title, p.company, p.city].some((v) => v?.toLowerCase().includes(q)));
    return sort === "score"
      ? [...list].sort((a, b) => (b.latest_run?.score ?? -1) - (a.latest_run?.score ?? -1))
      : list;
  }, [postings.data, query, sort]);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next);
  };

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>岗位</h1>
          <p>证据覆盖分数只说明经历库里找到了多少证据，不是录用概率</p>
        </div>
        <button className="primary" onClick={() => setParam("add", "1")}>添加 JD</button>
      </div>
      {adding && <AddPosting onClose={() => setParam("add", "")} onAdded={() => void postings.reload()} />}

      <Card>
        <Tabs tabs={FILTERS} active={status} onChange={(key) => setParam("status", key)} />
        <div className="row spread" style={{ marginBottom: 12 }}>
          <input className="search" placeholder="搜索岗位、公司、城市" value={query} onChange={(e) => setQuery(e.target.value)}
                 aria-label="搜索岗位" />
          <select value={sort} onChange={(e) => setSort(e.target.value as "score" | "newest")}
                  style={{ width: "auto" }} aria-label="排序">
            <option value="score">按证据分数</option>
            <option value="newest">按添加时间</option>
          </select>
        </div>
        <ErrorBox error={postings.error} />
        {postings.loading && !postings.data ? <Loading /> : rows.length ? <PostingTable rows={rows} /> : <Empty>没有岗位</Empty>}
      </Card>
    </div>
  );
}

function PostingTable({ rows }: { rows: PostingBrief[] }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr><th>岗位</th><th>城市</th><th>状态</th><th>证据覆盖</th><th>必需条件</th><th>来源</th></tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.id}>
              <td className="title-cell">
                <Link to={`/postings/${p.id}`}>{p.title}</Link>
                <div className="muted small">{p.company || "未填公司"} · {label(CHANNEL, p.channel)}</div>
              </td>
              <td className="small">{shortCities(p.city)}</td>
              <td><Badge value={p.status}>{label(POSTING_STATUS, p.status)}</Badge></td>
              <td><Score score={p.latest_run?.score} label={p.latest_run?.label} /></td>
              <td className="nowrap">
                {p.latest_run?.required_total ? `${p.latest_run.required_covered}/${p.latest_run.required_total}` : "—"}
              </td>
              <td className="small muted nowrap">{label(SOURCE, p.source)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function AddPosting({ onClose, onAdded }: { onClose: () => void; onAdded: () => void }) {
  const [form, setForm] = useState({ text: "", title: "", company: "", city: "", url: "", channel: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  async function submit(run: boolean) {
    setBusy(true);
    setError(null);
    try {
      const { posting, created } = await api.addPosting(form);
      onAdded();
      if (run) {
        const { run_id } = await api.startRun(posting.id);
        navigate(`/runs/${run_id}`);
      } else {
        navigate(`/postings/${posting.id}`);
      }
      if (!created) setError("这个 JD 已经存在，已打开原来的岗位");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Modal title="添加 JD" onClose={onClose}>
      <ErrorBox error={error} />
      <div className="stack" style={{ gap: 12 }}>
        <label className="field">JD 全文（必填）
          <textarea value={form.text} onChange={set("text")} placeholder="把岗位描述和任职要求整段粘贴进来" autoFocus />
        </label>
        <div className="form-grid">
          <label className="field">岗位名称<input value={form.title} onChange={set("title")} placeholder="不填则用第一行" /></label>
          <label className="field">公司<input value={form.company} onChange={set("company")} /></label>
          <label className="field">城市<input value={form.city} onChange={set("city")} placeholder="如 深圳" /></label>
          <label className="field">渠道
            <select value={form.channel} onChange={set("channel")}>
              <option value="">自动识别</option><option value="campus">校招</option><option value="social">社招</option>
            </select>
          </label>
        </div>
        <label className="field">原文链接<input value={form.url} onChange={set("url")} placeholder="https://" /></label>
      </div>
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
        <button onClick={onClose}>取消</button>
        <button onClick={() => submit(false)} disabled={busy || form.text.trim().length < 20}>只保存</button>
        <button className="primary" onClick={() => submit(true)} disabled={busy || form.text.trim().length < 20}>
          保存并运行 Agent
        </button>
      </div>
    </Modal>
  );
}

/** "深圳、北京、上海、广州、成都" -> "深圳、北京、上海 等 5 地" */
function shortCities(city: string) {
  if (!city) return "—";
  const parts = city.split("、");
  return parts.length > 3 ? `${parts.slice(0, 3).join("、")} 等 ${parts.length} 地` : city;
}
