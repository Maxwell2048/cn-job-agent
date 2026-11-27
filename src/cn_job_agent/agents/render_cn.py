"""Write the materials: materials.json (with citations), resume_zh.md,
resume_zh.docx and greeting.txt. Header and education come from the private
base resume, unchanged; nothing here calls a model."""
import json
from pathlib import Path


def education(base):
    for section in (base or {}).get("sections", []):
        if "教育" in section.get("title", ""):
            return section.get("entries", [])
    return []


def header(materials, base):
    base = base or {}
    target = materials.data.get("target_title") or base.get("target", "")
    if target and not target.startswith("求职意向"):
        target = f"求职意向：{target}"
    return base.get("name", ""), base.get("contact", ""), target


def markdown(materials, base):
    name, contact, target = header(materials, base)
    d = materials.data
    lines = [f"# {name or '简历'}", ""]
    lines += [line for line in (contact, target) if line]
    if d.get("summary", {}).get("text"):
        lines += ["", "## 个人简介", "", d["summary"]["text"]]
    entries = education(base)
    if entries:
        lines += ["", "## 教育背景", ""]
        for e in entries:
            lines.append(f"**{e.get('left', '')}**　{e.get('mid', '')}　{e.get('right', '')}")
            lines += [f"- {note}" for note in e.get("notes", [])]
    if d.get("projects"):
        lines += ["", "## 项目经历", ""]
        for p in d["projects"]:
            meta = "　".join(x for x in (p.get("role", ""), p.get("period", "")) if x)
            lines.append(f"### {p['title']}" + (f"　{meta}" if meta else ""))
            lines += [f"- **{b['label']}**：{b['text']}" for b in p["bullets"]]
            lines.append("")
    if materials.skills:
        lines += ["## 专业技能", ""] + [f"- **{group}**：{items}" for group, items in materials.skills]
    return "\n".join(lines).strip() + "\n"


def docx(materials, base, path):
    from docx import Document
    from docx.enum.text import WD_TAB_ALIGNMENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    name, contact, target = header(materials, base)
    doc = Document()
    for section in doc.sections:
        section.top_margin = section.bottom_margin = Cm(1.6)
        section.left_margin = section.right_margin = Cm(1.8)
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Microsoft YaHei", Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    normal.paragraph_format.space_after = Pt(2)
    width = doc.sections[0].page_width - doc.sections[0].left_margin - doc.sections[0].right_margin

    def para(text="", size=None, bold=False, color=None, space_before=0):
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(space_before)
        if text:
            run = p.add_run(text)
            run.bold = bold
            if size:
                run.font.size = Pt(size)
            if color:
                run.font.color.rgb = RGBColor.from_string(color)
        return p

    def heading(text):
        p = para(text, size=12, bold=True, color="1F3A8A", space_before=8)
        border = OxmlElement("w:pBdr")
        bottom = OxmlElement("w:bottom")
        for key, value in (("w:val", "single"), ("w:sz", "6"), ("w:space", "1"), ("w:color", "9CA3AF")):
            bottom.set(qn(key), value)
        border.append(bottom)
        p._p.get_or_add_pPr().append(border)

    def row(left, middle, right):
        p = para()
        p.paragraph_format.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)
        p.add_run(left).bold = True
        if middle:
            p.add_run(f"　{middle}")
        if right:
            r = p.add_run(f"\t{right}")
            r.font.color.rgb = RGBColor.from_string("4B5563")

    def bullet(label, text):
        p = doc.add_paragraph(style="List Bullet")
        p.paragraph_format.space_after = Pt(1)
        if label:
            p.add_run(f"{label}：").bold = True
        p.add_run(text)

    para(name or "简历", size=18, bold=True)
    if contact:
        para(contact, size=9.5, color="4B5563")
    if target:
        para(target, size=10.5, bold=True)
    d = materials.data
    if d.get("summary", {}).get("text"):
        heading("个人简介")
        para(d["summary"]["text"])
    entries = education(base)
    if entries:
        heading("教育背景")
        for e in entries:
            row(e.get("left", ""), e.get("mid", ""), e.get("right", ""))
            for note in e.get("notes", []):
                bullet("", note)
    if d.get("projects"):
        heading("项目经历")
        for p in d["projects"]:
            row(p["title"], p.get("role", ""), p.get("period", ""))
            for b in p["bullets"]:
                bullet(b["label"], b["text"])
    if materials.skills:
        heading("专业技能")
        for group, items in materials.skills:
            bullet(group, items)
    doc.save(path)


def save(materials, base, folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    materials.folder = str(folder)
    (folder / "materials.json").write_text(json.dumps(materials.as_json(), ensure_ascii=False, indent=2),
                                           encoding="utf-8")
    (folder / "resume_zh.md").write_text(markdown(materials, base), encoding="utf-8")
    (folder / "greeting.txt").write_text(materials.data.get("greeting", {}).get("text", ""), encoding="utf-8")
    docx(materials, base, folder / "resume_zh.docx")
    return folder
