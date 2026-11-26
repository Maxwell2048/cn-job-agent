"""cn-agent: command line for the P0 pieces.

    cn-agent doctor                 check configuration, job_rag_starter, experiences, database
    cn-agent db upgrade             create / migrate the schema (also installs pgvector)
    cn-agent seed                   load data/seed/campus_2027.yaml
    cn-agent profile                load the search profile (profile.local.yaml)
    cn-agent index                  embed the experiences library into pgvector
    cn-agent search "RAG 检索"      search the stored library
    cn-agent parity "q1" "q2"       compare pgvector results with job_rag_starter's in-memory retriever
    cn-agent companies [--city 武汉] [--all]   programmes with cohort eligibility for the profile
    cn-agent setup                  db upgrade + seed + profile + index

    cn-agent jd add [--file F | --stdin | --clipboard] [--title --company --city --url --channel]
    cn-agent jd list | jd show ID
    cn-agent run ID [--approve-review] [--force]      screen + match one posting (LangGraph)
    cn-agent run --resume RUN_ID [--approve | --decline]
    cn-agent runs                   recent runs
    cn-agent graph                  the job graph as Mermaid
    cn-agent llm check              is the local model reachable?
"""
import argparse
import json
import subprocess
import sys
from datetime import date

from sqlalchemy import func, select

from . import eligibility, geo
from .config import PROJECT_ROOT, get_settings


def _out(*parts):
    print(*parts, flush=True)


# ---------------------------------------------------------------- helpers
def _embedder(settings):
    from .rag import bridge
    from .rag.embedder import E5Embedder
    return E5Embedder(bridge.search_module(settings.job_rag_home).MODEL, offline=settings.offline)


def _profile_row(session, name="default"):
    from .db.models import SearchProfile
    row = session.scalar(select(SearchProfile).where(SearchProfile.name == name))
    if row is None:
        raise SystemExit("数据库里还没有求职画像；先运行 cn-agent profile")
    return row


# ---------------------------------------------------------------- commands
def cmd_doctor(args, settings):
    from .db.session import database_status
    from .rag import bridge
    ok = True
    _out(f"项目目录        {PROJECT_ROOT}")
    try:
        module = bridge.search_module(settings.job_rag_home)
        _out(f"job_rag_starter {settings.job_rag_home}  (检索模型 {module.MODEL})")
    except bridge.BridgeError as exc:
        ok = False
        _out(f"job_rag_starter 失败：{exc}")
    files = sorted(p for p in settings.experiences.glob("*.md")) if settings.experiences.is_dir() else []
    ok &= bool(files)
    _out(f"经历库          {settings.experiences}  ({len(files)} 个 .md 文件)")
    profile = settings.profile_file
    _out(f"求职画像        {profile}  ({'存在' if profile.is_file() else '不存在：复制 profile.example.yaml'})")
    db_ok, message = database_status(settings.database_url)
    ok &= db_ok
    _out(f"数据库          {message}")
    return 0 if ok else 1


def cmd_db_upgrade(args, settings):
    from alembic import command
    from alembic.config import Config
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["database_url"] = settings.database_url
    command.upgrade(config, "head")
    from .agents.runner import setup_checkpointer
    setup_checkpointer(settings)
    _out("数据库已迁移到最新版本（含 LangGraph 检查点表）")
    return 0


def cmd_seed(args, settings):
    from .db.session import session_scope
    from .seed.loader import load_seed, read_seed
    seed = read_seed(args.file or settings.seed_path)
    with session_scope(settings.database_url) as session:
        counts = load_seed(session, seed)
    _out(f"已导入 {counts['companies']} 家企业、{counts['programs']} 个招聘项目"
         f"（删除 {counts['programs_removed']} 个已不在文件里的项目）；资料核对日期 {seed.checked_on}")
    return 0


def cmd_profile(args, settings):
    from .db.session import session_scope
    from .seed.loader import load_profile, read_profile
    profile = read_profile(args.file or settings.profile_file)
    with session_scope(settings.database_url) as session:
        load_profile(session, profile)
    _out(f"已保存求职画像 {profile.name}：岗位 {'、'.join(r.label for r in profile.roles)}；"
         f"城市 {'、'.join(profile.cities)}；渠道 {'、'.join(profile.channels)}")
    return 0


def cmd_index(args, settings):
    from .db.session import session_scope
    from .rag import bridge, store
    embedder = _embedder(settings)
    chunks = bridge.experience_chunks(settings.job_rag_home, settings.experiences, embedder.tokenizer,
                                      all_sections=args.all_sections)
    with session_scope(settings.database_url) as session:
        counts = store.index_chunks(session, embedder, chunks)
    _out(f"经历库入库完成：共 {counts['total']} 个片段；新编码 {counts['added']}，"
         f"沿用 {counts['kept']}，删除 {counts['removed']}")
    return 0


def _print_results(results):
    for rank, r in enumerate(results, 1):
        snippet = " ".join(r["matched_text"].split())[:90]
        _out(f"{rank}. [{r['score']:.4f}] {r['project']} / {r['section']}  "
             f"({r['source']}:{r['line_start']}-{r['line_end']})")
        _out(f"   {snippet}")


def cmd_search(args, settings):
    from .db.session import session_scope
    from .rag import bridge, store
    embedder = _embedder(settings)
    rank_sections = bridge.search_module(settings.job_rag_home).rank_sections
    with session_scope(settings.database_url) as session:
        if not session.scalar(select(func.count()).select_from(store.KbChunk)):
            raise SystemExit("向量库是空的；先运行 cn-agent index")
        results = store.search(session, embedder, rank_sections, args.query, top_k=args.top_k)
    _print_results(results)
    return 0


def cmd_parity(args, settings):
    """Same queries through job_rag_starter's in-memory ExperienceRetriever and
    through pgvector: the section order and scores should agree."""
    from .db.session import session_scope
    from .rag import bridge, store
    module = bridge.search_module(settings.job_rag_home)
    embedder = _embedder(settings)
    memory = module.ExperienceRetriever(settings.experiences, offline=settings.offline)
    memory._load_model = lambda: embedder.model   # reuse the loaded model instead of loading it twice
    memory.build()
    failures = 0
    for query in args.queries:
        expected = memory.search(query, top_k=args.top_k)
        with session_scope(settings.database_url) as session:
            actual = store.search(session, embedder, module.rank_sections, query, top_k=args.top_k)
        same_order = [r["section_id"] for r in expected] == [r["section_id"] for r in actual]
        max_delta = max((abs(a["score"] - e["score"]) for a, e in zip(actual, expected)), default=0.0)
        ok = same_order and max_delta < 1e-3
        failures += not ok
        _out(f"{'一致' if ok else '不一致'}  {query}  (前 {args.top_k} 名顺序{'相同' if same_order else '不同'}，"
             f"最大分差 {max_delta:.5f})")
    return 1 if failures else 0


def cmd_companies(args, settings):
    from .db.models import CampusProgram, Company
    from .db.session import session_scope
    today = date.today()
    with session_scope(settings.database_url) as session:
        profile = _profile_row(session)
        cities = args.city or profile.cities
        programs = session.scalars(select(CampusProgram).join(Company)).all()
        rows = []
        for program in programs:
            kind, matched = geo.match(program.cities, cities)
            if kind is None and not args.all:
                continue
            verdict = eligibility.judge(program, profile)
            if verdict.status == eligibility.INELIGIBLE and not args.all:
                continue
            closed = program.deadline is not None and program.deadline < today
            rows.append((eligibility.ORDER.index(verdict.status), closed, program.company.name, program, verdict,
                         kind, matched, closed))
        rows.sort(key=lambda r: (r[0], r[1], r[2]))
        for _, _, name, program, verdict, kind, matched, closed in rows:
            where = f"{geo.LABELS[kind]}：{'、'.join(matched)}" if kind else "城市不匹配"
            deadline = "已截止" if closed else (program.deadline_text or (program.deadline.isoformat()
                                                                         if program.deadline else ""))
            _out(f"[{verdict.label}] {name} · {program.title}  |  {where}  |  {deadline or '未写截止'}")
            _out(f"    {verdict.reason}")
            if program.roles:
                _out(f"    岗位：{'、'.join(program.roles)}")
            if program.status_text:
                _out(f"    状态：{program.status_text}")
        total = session.scalar(select(func.count()).select_from(Company))
    _out(f"\n共 {len(rows)} 个项目（数据库里共 {total} 家企业）；城市：{'、'.join(cities)}"
         f"{'；含不符合和城市不匹配的项目' if args.all else ''}")
    return 0


def _read_jd(args):
    if args.file:
        from pathlib import Path
        return Path(args.file).read_bytes().decode("utf-8-sig"), "file"
    if args.clipboard:
        command = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"
        done = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True)
        return done.stdout.decode("utf-8-sig", errors="replace"), "clipboard"
    return sys.stdin.buffer.read().decode("utf-8-sig"), "stdin"


def cmd_jd_add(args, settings):
    from .agents.postings import add_posting
    from .db.session import session_scope
    text, source = _read_jd(args)
    with session_scope(settings.database_url) as session:
        posting, created = add_posting(session, text, source=source, title=args.title or "",
                                       company_name=args.company or "", city=args.city or "",
                                       url=args.url or "", channel=args.channel or "")
        company = posting.company.name if posting.company else "未关联已知企业"
        _out(f"{'已保存' if created else '已存在相同 JD'}：岗位 {posting.id} · {posting.title}"
             f" · {company} · 渠道 {posting.channel}")
    return 0


def cmd_jd_list(args, settings):
    from .db.models import JobPosting
    from .db.session import session_scope
    with session_scope(settings.database_url) as session:
        for p in session.scalars(select(JobPosting).order_by(JobPosting.id.desc()).limit(args.limit)):
            _out(f"{p.id:>4}  [{p.status}]  {p.title}  ·  {p.company_name or (p.company.name if p.company else '')}"
                 f"  ·  {p.city}  ·  {p.channel}")
    return 0


def cmd_jd_show(args, settings):
    from .db.models import JobPosting
    from .db.session import session_scope
    with session_scope(settings.database_url) as session:
        posting = session.get(JobPosting, args.id)
        if posting is None:
            raise SystemExit(f"没有编号为 {args.id} 的岗位")
        _out(f"{posting.title}  ·  {posting.company_name}  ·  {posting.city}  ·  {posting.channel}  ·  {posting.status}")
        for run in posting.runs:
            score = run.summary.get("score") if run.summary else None
            _out(f"  运行 {run.id}  [{run.status}]  分数 {score if score is not None else '-'}  {run.report_path}")
        _out("")
        _out(posting.jd_text)
    return 0


def _print_outcome(outcome):
    from .agents.report import DECISION, SEVERITY
    decision = outcome.screening.get("decision")
    if decision:
        _out(f"筛选：{DECISION.get(decision, decision)}")
        for f in outcome.screening.get("flags", []):
            if f["severity"] != "info":
                _out(f"  [{SEVERITY[f['severity']]}] {f['message']}" + (f"  「{f['quote']}」" if f["quote"] else ""))
    if outcome.status == "interrupted":
        _out(f"\n运行 {outcome.run_id} 已暂停，等你确认。继续：cn-agent run --resume {outcome.run_id} --approve"
             f"\n不继续：cn-agent run --resume {outcome.run_id} --decline")
        return 0
    if outcome.status == "failed":
        _out(f"\n运行 {outcome.run_id} 失败：{outcome.error or '见报告'}"
             + (f"\n报告：{outcome.report_path}" if outcome.report_path else "")
             + f"\n修好原因后重试：cn-agent run --resume {outcome.run_id}")
        return 1
    if outcome.summary:
        s = outcome.summary
        score = "无法评分" if s.get("score") is None else f"{s['score']} 分（{s['label']}）"
        _out(f"证据覆盖：{score}；必需条件有证据 {s['required_covered']}/{s['required_total']}；"
             f"直接 {s['counts']['direct']} · 相关 {s['counts']['related']} · 不足 {s['counts']['insufficient']}"
             f" · 失败 {s['counts']['error']}")
    _out(f"运行 {outcome.run_id}：{outcome.status}\n报告：{outcome.report_path}")
    return 0


def cmd_run(args, settings):
    from .agents import runner
    toolkit = runner.Toolkit(settings)
    if args.pending:
        return _run_pending(args, settings, toolkit)
    with runner.postgres_checkpointer(settings) as saver:
        if args.resume:
            approve = True if args.approve else False if args.decline else None
            outcome = runner.resume(toolkit, saver, args.resume, approve)
        else:
            if args.posting_id is None:
                raise SystemExit("给出岗位编号，或用 --resume 继续一个运行")
            outcome = runner.start(toolkit, saver, args.posting_id, force=args.force,
                                   auto_approve=args.approve_review)
    return _print_outcome(outcome)


def _run_pending(args, settings, toolkit):
    from .agents import runner
    if not runner.pending_postings(toolkit.database_url, 1):
        _out("没有待处理的新岗位")
        return 0
    try:
        toolkit.get_llm()
    except Exception as exc:  # noqa: BLE001
        _out(f"本地模型不可用，先不处理新岗位：{exc}")
        return 0
    with runner.postgres_checkpointer(settings) as saver:
        outcomes = runner.process_pending(toolkit, saver, limit=args.limit, auto_approve=args.approve_review,
                                          on_start=lambda pid: _out(f"\n—— 岗位 {pid}"))
        for _, outcome in outcomes:
            _print_outcome(outcome)
    return 0


def cmd_collect(args, settings):
    from .agents.collect import collect
    _out(f"开始采集（模式 {args.mode}）……")
    outcome = collect(settings, mode=args.mode, max_saves=args.max_saves, max_searches=args.max_searches)
    _out(f"采集 {outcome.run_id}：{outcome.status}，实际模式 {outcome.mode}")
    s = outcome.stats
    _out(f"搜索 {s['searches']} 次，看到 {s['seen']} 个岗位，新保存 {s['saved']} 个，已存在 {s['duplicates']} 个，"
         f"出错 {s['errors']} 次")
    for item in outcome.saved:
        _out(f"  岗位 {item['posting_id']} · {item['title']}  [{item['source']}]  {item.get('reason') or ''}")
    if outcome.error:
        _out(f"错误：{outcome.error}")
    if outcome.saved:
        _out("处理新岗位：cn-agent run --pending")
    return 0 if outcome.status == "done" else 1


def cmd_collections(args, settings):
    from .db.models import CollectionRun
    from .db.session import session_scope
    with session_scope(settings.database_url) as session:
        for run in session.scalars(select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(args.limit)):
            stats = run.stats or {}
            _out(f"{run.id}  [{run.status}]  模式 {run.mode}  搜索 {stats.get('searches', 0)}  "
                 f"新保存 {stats.get('saved', 0)}" + (f"  错误：{run.error[:80]}" if run.error else ""))
            if args.trace:
                for step in run.trace or []:
                    detail = step.get("args") or step.get("text") or step.get("keywords")
                    _out(f"    {step['type']:<11} {step.get('tool', '')} {json.dumps(detail, ensure_ascii=False)[:160]}")
    return 0


TASK_NAME = "cn-job-agent-collect"


def _schedule_script(settings):
    exe = PROJECT_ROOT / ".venv" / "Scripts" / "cn-agent.exe"
    log = settings.state_dir / "scheduled.log"
    script = settings.state_dir / "scheduled_collect.cmd"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("\r\n".join([
        "@echo off",
        "chcp 65001 > nul",
        f'cd /d "{PROJECT_ROOT}"',
        f'echo ==== %date% %time% >> "{log}"',
        f'"{exe}" collect --mode auto >> "{log}" 2>&1',
        f'"{exe}" run --pending --limit 5 >> "{log}" 2>&1',
    ]) + "\r\n", encoding="utf-8")
    return script


def cmd_schedule(args, settings):
    if args.action == "show":
        done = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/V", "/FO", "LIST"], capture_output=True)
        _out(done.stdout.decode("gbk", errors="replace") if done.returncode == 0 else "没有安装定时采集")
        return 0
    if args.action == "remove":
        done = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True)
        _out("已删除定时采集" if done.returncode == 0 else done.stderr.decode("gbk", errors="replace"))
        return done.returncode
    script = _schedule_script(settings)
    done = subprocess.run(["schtasks", "/Create", "/SC", "DAILY", "/TN", TASK_NAME, "/TR", f'"{script}"',
                           "/ST", args.time, "/F"], capture_output=True)
    if done.returncode:
        _out(done.stderr.decode("gbk", errors="replace"))
        return done.returncode
    _out(f"已安装：每天 {args.time} 采集并处理最多 5 个新岗位；日志 {settings.state_dir / 'scheduled.log'}")
    return 0


def cmd_runs(args, settings):
    from .db.models import AgentRun
    from .db.session import session_scope
    with session_scope(settings.database_url) as session:
        for run in session.scalars(select(AgentRun).order_by(AgentRun.started_at.desc()).limit(args.limit)):
            score = (run.summary or {}).get("score")
            _out(f"{run.id}  [{run.status}]  岗位 {run.posting_id} · {run.posting.title}  ·  "
                 f"分数 {score if score is not None else '-'}")
    return 0


def cmd_graph(args, settings):
    from .agents.graph import build_graph
    from .agents.runner import Toolkit
    _out(build_graph(Toolkit(settings)).get_graph().draw_mermaid())
    return 0


def cmd_llm_check(args, settings):
    from .agents.matching import build_llm
    try:
        llm = build_llm(settings)
    except Exception as exc:  # noqa: BLE001
        _out(f"本地模型不可用：{exc}")
        return 1
    _out(f"本地模型可用：{getattr(llm, 'model', '')}（配置 {settings.llm_config_file}）")
    return 0


def cmd_setup(args, settings):
    for step in (cmd_db_upgrade, cmd_seed, cmd_profile, cmd_index):
        code = step(argparse.Namespace(file=None, all_sections=False), settings)
        if code:
            return code
    return 0


def build_parser():
    parser = argparse.ArgumentParser(prog="cn-agent", description="国内求职 Agent（P0）")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="检查配置、经历库和数据库").set_defaults(func=cmd_doctor)
    db = sub.add_parser("db", help="数据库").add_subparsers(dest="db_command", required=True)
    db.add_parser("upgrade", help="迁移到最新版本").set_defaults(func=cmd_db_upgrade)
    seed = sub.add_parser("seed", help="导入校招种子数据")
    seed.add_argument("--file")
    seed.set_defaults(func=cmd_seed)
    profile = sub.add_parser("profile", help="导入求职画像")
    profile.add_argument("--file")
    profile.set_defaults(func=cmd_profile)
    index = sub.add_parser("index", help="经历库向量入库")
    index.add_argument("--all-sections", action="store_true", help="也收录派生的 CV/STAR 章节")
    index.set_defaults(func=cmd_index)
    search = sub.add_parser("search", help="检索经历库")
    search.add_argument("query")
    search.add_argument("--top-k", type=int, default=5)
    search.set_defaults(func=cmd_search)
    parity = sub.add_parser("parity", help="与 job_rag_starter 的内存检索对比")
    parity.add_argument("queries", nargs="+")
    parity.add_argument("--top-k", type=int, default=5)
    parity.set_defaults(func=cmd_parity)
    companies = sub.add_parser("companies", help="按求职画像列出校招项目和届别判断")
    companies.add_argument("--city", action="append", help="覆盖画像里的城市，可重复")
    companies.add_argument("--all", action="store_true", help="也列出不符合和城市不匹配的项目")
    companies.set_defaults(func=cmd_companies)
    sub.add_parser("setup", help="迁移、导入种子和画像、入库经历").set_defaults(func=cmd_setup)

    jd = sub.add_parser("jd", help="岗位 JD").add_subparsers(dest="jd_command", required=True)
    add = jd.add_parser("add", help="保存一个 JD（默认从标准输入读取）")
    source = add.add_mutually_exclusive_group()
    source.add_argument("--file")
    source.add_argument("--clipboard", action="store_true")
    source.add_argument("--stdin", action="store_true")
    for name in ("title", "company", "city", "url"):
        add.add_argument(f"--{name}")
    add.add_argument("--channel", choices=["campus", "social", "unknown"])
    add.set_defaults(func=cmd_jd_add)
    jd_list = jd.add_parser("list", help="最近的岗位")
    jd_list.add_argument("--limit", type=int, default=30)
    jd_list.set_defaults(func=cmd_jd_list)
    show = jd.add_parser("show", help="岗位详情和运行记录")
    show.add_argument("id", type=int)
    show.set_defaults(func=cmd_jd_show)

    run = sub.add_parser("run", help="对一个岗位运行筛选和匹配（LangGraph）")
    run.add_argument("posting_id", type=int, nargs="?")
    run.add_argument("--force", action="store_true", help="硬性不符也继续匹配")
    run.add_argument("--approve-review", action="store_true", help="需人工确认时直接继续，不暂停")
    run.add_argument("--resume", metavar="RUN_ID", help="继续一个暂停或失败的运行")
    run.add_argument("--pending", action="store_true", help="依次处理还没运行过的新岗位")
    run.add_argument("--limit", type=int, default=5, help="--pending 时最多处理几个")
    answer = run.add_mutually_exclusive_group()
    answer.add_argument("--approve", action="store_true")
    answer.add_argument("--decline", action="store_true")
    run.set_defaults(func=cmd_run)
    runs = sub.add_parser("runs", help="最近的运行")
    runs.add_argument("--limit", type=int, default=20)
    runs.set_defaults(func=cmd_runs)
    sub.add_parser("graph", help="打印 Agent 图（Mermaid）").set_defaults(func=cmd_graph)
    collect = sub.add_parser("collect", help="搜索规划 Agent：从校招官网采集岗位")
    collect.add_argument("--mode", choices=["auto", "agent", "rules"], default="auto")
    collect.add_argument("--max-saves", type=int, default=30)
    collect.add_argument("--max-searches", type=int, default=100)
    collect.set_defaults(func=cmd_collect)
    collections = sub.add_parser("collections", help="最近的采集记录")
    collections.add_argument("--limit", type=int, default=10)
    collections.add_argument("--trace", action="store_true", help="显示 Agent 的工具调用过程")
    collections.set_defaults(func=cmd_collections)
    schedule = sub.add_parser("schedule", help="Windows 定时采集（任务计划程序）")
    schedule.add_argument("action", choices=["show", "install", "remove"])
    schedule.add_argument("--time", default="09:00", help="每天几点运行，HH:MM")
    schedule.set_defaults(func=cmd_schedule)
    llm = sub.add_parser("llm", help="本地模型").add_subparsers(dest="llm_command", required=True)
    llm.add_parser("check", help="检查本地模型能否连接").set_defaults(func=cmd_llm_check)
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args, get_settings())


if __name__ == "__main__":
    raise SystemExit(main())
