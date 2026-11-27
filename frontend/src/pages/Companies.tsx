import { useMemo, useState } from "react";
import { api } from "../api";
import { useData } from "../hooks";
import { Badge, Card, Empty, ErrorBox, Loading } from "../components";
import { COHORT, SECTOR, label } from "../labels";

const ORDER = ["eligible", "boundary", "likely", "conditional", "unknown", "ineligible"];
const SECTOR_ORDER = ["internet", "hardware", "bank", "soe", "foreign"];   // as in the campus handbook

export default function Companies() {
  const overview = useData(() => api.overview());
  const profileCities = overview.data?.profile?.cities ?? [];
  const [cities, setCities] = useState<string[] | null>(null);
  const [showAll, setShowAll] = useState(false);
  const selected = cities ?? profileCities;
  const companies = useData(() => api.companies(selected, showAll), [selected.join(","), showAll]);

  const grouped = useMemo(() => {
    const out: Record<string, NonNullable<typeof companies.data>> = {};
    for (const sector of SECTOR_ORDER) out[sector] = [];
    for (const company of companies.data ?? []) (out[company.sector] ??= []).push(company);
    return Object.fromEntries(Object.entries(out).filter(([, rows]) => rows.length));
  }, [companies.data]);

  const toggle = (city: string) =>
    setCities(selected.includes(city) ? selected.filter((c) => c !== city) : [...selected, city]);

  return (
    <div className="stack">
      <div className="page-header">
        <div>
          <h1>企业校招窗口</h1>
          <p>2027 届毕业时间窗口，按你的学位证月份判断能不能投（资料核对于 2026-11-21，投递前以官网公告为准）</p>
        </div>
      </div>
      <Card>
        <div className="row spread">
          <div className="row">
            <span className="muted small">城市</span>
            {profileCities.map((city) => (
              <button key={city} className={selected.includes(city) ? "primary" : ""} onClick={() => toggle(city)}>{city}</button>
            ))}
          </div>
          <label className="row small muted">
            <input type="checkbox" style={{ width: "auto" }} checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />
            也显示不符合和其他城市的项目
          </label>
        </div>
      </Card>
      <ErrorBox error={companies.error} />
      {companies.loading && !companies.data ? <Loading /> : Object.keys(grouped).length === 0 ? <Empty>没有符合条件的校招项目</Empty> : (
        Object.entries(grouped).map(([sector, rows]) => (
          <Card key={sector} title={label(SECTOR, sector)}>
            <div className="table-wrap">
              <table>
                <thead><tr><th>企业 · 项目</th><th>届别</th><th>毕业窗口</th><th>城市</th><th>状态 / 截止</th></tr></thead>
                <tbody>
                  {rows.flatMap((company) => [...company.programs]
                    .sort((a, b) => ORDER.indexOf(a.verdict ?? "unknown") - ORDER.indexOf(b.verdict ?? "unknown"))
                    .map((program) => (
                      <tr key={company.key + program.title}>
                        <td className="title-cell"><strong>{company.name}</strong><div className="muted small">{program.title}</div>
                          {program.roles.length > 0 && <div className="small">{program.roles.slice(0, 6).join("、")}</div>}</td>
                        <td><Badge value={program.verdict}>{label(COHORT, program.verdict)}</Badge></td>
                        <td className="small" title={program.verdict_reason ?? ""}>{program.window_text || "—"}</td>
                        <td className="small">{program.matched_cities?.length ? program.matched_cities.join("、") : program.cities.slice(0, 4).join("、") || "—"}</td>
                        <td className="small">{program.status_text || "—"}{program.deadline_text && <div className="muted">截止 {program.deadline_text}</div>}
                          {program.sources[0] && <div><a href={program.sources[0].url} target="_blank" rel="noreferrer">来源</a></div>}</td>
                      </tr>
                    )))}
                </tbody>
              </table>
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
