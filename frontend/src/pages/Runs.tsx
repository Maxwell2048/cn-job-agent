import { Link } from "react-router-dom";
import { api } from "../api";
import { useData } from "../hooks";
import { Badge, Card, Empty, ErrorBox, Loading, Score } from "../components";
import { DECISION, RUN_STATUS, duration, formatTime, label } from "../labels";

export default function Runs() {
  const runs = useData(() => api.runs());
  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>Agent 运行</h1>
          <p>每次运行是一个 LangGraph 线程：检查点存在 PostgreSQL，暂停或失败的运行可以从断点继续</p>
        </div>
      </div>
      <Card>
        <ErrorBox error={runs.error} />
        {runs.loading && !runs.data ? <Loading /> : runs.data?.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>岗位</th><th>状态</th><th>筛选</th><th>证据覆盖</th><th>开始</th><th>用时</th></tr></thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.id}>
                    <td className="title-cell"><Link to={`/runs/${r.id}`}>{r.posting_title}</Link>
                      <div className="muted small mono">{r.id}</div></td>
                    <td><Badge value={r.status}>{label(RUN_STATUS, r.status)}</Badge></td>
                    <td>{label(DECISION, r.decision)}</td>
                    <td><Score score={r.score} /></td>
                    <td className="small muted nowrap">{formatTime(r.started_at)}</td>
                    <td className="small muted nowrap">{duration(r.started_at, r.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>还没有运行</Empty>}
      </Card>
    </div>
  );
}
