import { NavLink, Route, Routes, useLocation } from "react-router-dom";
import { useEffect } from "react";
import { STATIC_DEMO, api } from "./api";
import { useData } from "./hooks";
import Overview from "./pages/Overview";
import Postings from "./pages/Postings";
import PostingDetail from "./pages/PostingDetail";
import Runs from "./pages/Runs";
import RunTrace from "./pages/RunTrace";
import Collections from "./pages/Collections";
import CollectionDetail from "./pages/CollectionDetail";
import Companies from "./pages/Companies";
import { Empty } from "./components";

const NAV = [
  { to: "/", label: "概览", end: true },
  { to: "/postings", label: "岗位" },
  { to: "/runs", label: "Agent 运行" },
  { to: "/collections", label: "采集" },
  { to: "/companies", label: "企业校招" },
];

export default function App() {
  const location = useLocation();
  const overview = useData(() => api.overview(), []);
  // Refresh the sidebar counters whenever the page changes.
  useEffect(() => { void overview.reload(); }, [location.pathname]); // eslint-disable-line react-hooks/exhaustive-deps
  const waiting = overview.data?.postings.review ?? 0;

  return (
    <div className="layout">
      <nav className="sidebar" aria-label="主导航">
        <div className="brand">
          <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" />
          <div>国内求职 Agent<small>LangGraph · RAG · pgvector</small></div>
        </div>
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.end}
                   className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
            {item.label}
            {item.to === "/postings" && waiting > 0 && <span className="nav-count">{waiting} 待确认</span>}
          </NavLink>
        ))}
        <div className="sidebar-footer">
          只在本机运行 · 数据存在本机 PostgreSQL
        </div>
      </nav>
      <main className="main">
        {STATIC_DEMO && (
          <div className="notice warn" style={{ marginBottom: 16 }}>
            公开演示版：候选人资料是虚构的，岗位来自企业官网的公开招聘信息；所有结果由真实流水线（LangGraph + DeepSeek）预先生成，
            页面只读。完整功能请克隆 <a href="https://github.com/Maxwell2048/cn-job-agent">cn-job-agent</a> 在本机运行。
          </div>
        )}
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/postings" element={<Postings />} />
          <Route path="/postings/:id" element={<PostingDetail />} />
          <Route path="/runs" element={<Runs />} />
          <Route path="/runs/:id" element={<RunTrace />} />
          <Route path="/collections" element={<Collections />} />
          <Route path="/collections/:id" element={<CollectionDetail />} />
          <Route path="/companies" element={<Companies />} />
          <Route path="*" element={<Empty>没有这个页面</Empty>} />
        </Routes>
      </main>
    </div>
  );
}
