import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useData } from "../hooks";
import { Badge, Card, Empty, ErrorBox, Loading } from "../components";
import { duration, formatTime } from "../labels";
import StartCollection from "./StartCollection";

export default function Collections() {
  const collections = useData(() => api.collections());
  const [starting, setStarting] = useState(false);
  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>采集</h1>
          <p>搜索规划 Agent：用 list_sources、search_jobs、save_jobs 三个工具在校招官网上找岗位</p>
        </div>
        <button className="primary" onClick={() => setStarting(true)}>开始采集</button>
      </div>
      {starting && <StartCollection onClose={() => setStarting(false)} />}
      <Card>
        <ErrorBox error={collections.error} />
        {collections.loading && !collections.data ? <Loading /> : collections.data?.length ? (
          <div className="table-wrap">
            <table>
              <thead><tr><th>采集</th><th>模式</th><th>状态</th><th>搜索</th><th>看到</th><th>新保存</th><th>开始</th><th>用时</th></tr></thead>
              <tbody>
                {collections.data.map((c) => (
                  <tr key={c.id}>
                    <td><Link className="mono small" to={`/collections/${c.id}`}>{c.id}</Link></td>
                    <td>{c.mode === "agent" ? "Agent 模式" : c.mode === "rules" ? "规则模式" : c.mode}</td>
                    <td><Badge value={c.status}>{c.status === "done" ? "完成" : c.status === "running" ? "运行中" : "失败"}</Badge></td>
                    <td>{c.stats.searches ?? 0}</td>
                    <td>{c.stats.seen ?? 0}</td>
                    <td><strong>{c.stats.saved ?? 0}</strong></td>
                    <td className="small muted nowrap">{formatTime(c.started_at)}</td>
                    <td className="small muted nowrap">{duration(c.started_at, c.finished_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <Empty>还没有采集过</Empty>}
      </Card>
    </div>
  );
}
