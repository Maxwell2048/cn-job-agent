import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { ErrorBox, Modal } from "../components";

const MODES = [
  { key: "auto", title: "自动", text: "模型可用且支持工具调用就用 Agent 模式，否则改用规则模式" },
  { key: "agent", title: "Agent 模式", text: "模型自己决定在哪个网站搜什么、读标题后挑选并说明理由" },
  { key: "rules", title: "规则模式", text: "按画像关键词和城市固定执行，不调用模型" },
];

export default function StartCollection({ onClose }: { onClose: () => void }) {
  const [mode, setMode] = useState("auto");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function start() {
    setBusy(true);
    try {
      const { collection_id } = await api.startCollection(mode);
      navigate(`/collections/${collection_id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Modal title="从校招官网采集岗位" onClose={onClose}>
      <p className="muted" style={{ marginTop: 0 }}>
        搜索腾讯、科大讯飞、传音的校招官网（公开接口，每个网站每秒最多 1 次请求），把符合画像的岗位存进列表。
      </p>
      <ErrorBox error={error} />
      <div className="stack" style={{ gap: 8 }}>
        {MODES.map((m) => (
          <label key={m.key} className="requirement row" style={{ cursor: "pointer", alignItems: "flex-start" }}>
            <input type="radio" name="mode" checked={mode === m.key} onChange={() => setMode(m.key)}
                   style={{ width: "auto", marginTop: 4 }} />
            <span><strong>{m.title}</strong><div className="muted small">{m.text}</div></span>
          </label>
        ))}
      </div>
      <div className="row" style={{ justifyContent: "flex-end", marginTop: 16 }}>
        <button onClick={onClose}>取消</button>
        <button className="primary" onClick={start} disabled={busy}>{busy ? "正在开始…" : "开始采集"}</button>
      </div>
    </Modal>
  );
}
