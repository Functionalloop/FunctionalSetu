"""Exports (plan 11.2): a list or a report written as Excel (.xlsx) or PDF by the worker (job kind "export").

POST /exports checks the request with `parse` and queues a job; the worker (`run_export`) checks it again
with the user's area as it is then, builds the rows, writes the file into app.files (kind export) and
marks the export done. The phone or portal polls GET /exports/{id} and downloads the file.

Kinds:
  voter_list   the voters GET /voters lists with the same `filter` (same keys, same rows, roll order);
               `columns` from COLUMNS (empty = DEFAULT_COLUMNS). options.group_by_house: by house within
               each part (PDF: a line per house). At most MAX_ROWS voters (more: the job fails).
  mobile_list  the same with has_mobile always true (has_mobile false: 422); default columns with mobiles.
  report       options.report = survey_progress (default), colour_tags or demographics: the table of
               GET /reports/<that>; filter ward_id (demographics also booth_id).
  turnout      GET /reports/turnout: by area and by Indian hour; filter ward_id.
Options: paper a4 / legal, text_size small / normal / large, header (a line on top, up to 200
characters), group_by_house, report. Unknown keys, columns or options: 422. Areas outside the user's
area: 404 at POST, a failed job when the area is no longer theirs by the time it runs.

Language (mr / en / hi) picks the headings and, per voter, the name in that language (the other one
when it is missing). PDF: Noto Sans with Noto Sans Devanagari for Marathi and Hindi (app/fonts, SIL
Open Font Licence), shaped by HarfBuzz (uharfbuzz) so joined letters print correctly.
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import Connection, text

from .deps import Principal
from .errors import ApiError
from .routers.files import store_file
from .routers.reports import areas_in, colour_tags, demographics, survey_progress, turnout_report
from .routers.voters import _SORT, VoterFilter, voter_where
from .schemas import Role
from .schemas_admin import FileKind
from .schemas_roll import ExportFormat, ExportIn, ExportKind
from .scope import Scope, load_scope, require_area
from .worker import Job, JobFailed, register

KIND = "export"
MAX_ROWS = 50_000
IST = ZoneInfo("Asia/Kolkata")
FONT_DIR = Path(__file__).parent / "fonts"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF_MIME = "application/pdf"
LANG_INDEX = {"en": 0, "mr": 1, "hi": 2}

# words in (English, Marathi, Hindi)
WORDS: dict[str, tuple[str, str, str]] = {
    "voter_list": ("Voter list", "मतदार यादी", "मतदाता सूची"),
    "mobile_list": ("Mobile numbers", "मोबाईल क्रमांक यादी", "मोबाइल नंबर सूची"),
    "survey_progress": ("Survey progress", "सर्वेक्षण प्रगती", "सर्वेक्षण प्रगति"),
    "colour_tags": ("Colour tags", "रंग टॅग", "रंग टैग"),
    "demographics": ("Age and gender", "वय आणि लिंग", "आयु और लिंग"),
    "turnout": ("Turnout", "मतदान टक्केवारी", "मतदान प्रतिशत"),
    "by_hour": ("Turnout by hour", "तासानुसार मतदान", "घंटेवार मतदान"),
    "ward": ("Village Panchayat", "ग्रामपंचायत", "ग्राम पंचायत"),
    "booth": ("Part", "भाग", "भाग"),
    "total": ("Total", "एकूण", "कुल"),
    "surveyed": ("Surveyed", "सर्वेक्षण झाले", "सर्वेक्षण हुआ"),
    "voted": ("Voted", "मतदान केले", "मतदान किया"),
    "no_tag": ("No tag", "टॅग नाही", "टैग नहीं"),
    "age": ("Age", "वय", "आयु"),
    "M": ("Male", "पुरुष", "पुरुष"),
    "F": ("Female", "स्त्री", "महिला"),
    "O": ("Other", "इतर", "अन्य"),
    "hour": ("Hour", "वेळ", "समय"),
    "so_far": ("Total so far", "आतापर्यंत", "अब तक"),
    "yes": ("Yes", "होय", "हाँ"),
    "no": ("No", "नाही", "नहीं"),
    "house": ("House No.", "घर क्र.", "मकान नं."),
    "printed": ("Printed", "छपाई", "मुद्रित"),
    "voters": ("voters", "मतदार", "मतदाता"),
    "page": ("Page", "पान", "पृष्ठ"),
    "unknown": ("Unknown", "माहीत नाही", "अज्ञात"),
}


def word(key: str, lang: str) -> str:
    return WORDS[key][LANG_INDEX[lang]]


def pick(lang: str, en: Any, mr: Any, hi: Any = None) -> Any:
    """The value in the language, else another one."""
    order = {"en": (en, mr, hi), "mr": (mr, en, hi), "hi": (hi, mr, en)}[lang]
    return next((v for v in order if v not in (None, "")), None)


# --- voter list columns ----------------------------------------------------------------------------
@dataclass(frozen=True)
class VoterColumn:
    words: tuple[str, str, str]
    weight: float                      # relative width
    align: str                         # L, R or C
    value: Any                         # (row, lang) -> cell value


def _gender(r: Any, lang: str) -> str:
    return word(r["gender"], lang)


COLUMNS: dict[str, VoterColumn] = {
    "part_no": VoterColumn(("Part", "भाग", "भाग"), 1, "R", lambda r, lang: r["part_no"]),
    "serial_no": VoterColumn(("Sr. No.", "अनु. क्र.", "क्र. सं."), 1.1, "R", lambda r, lang: r["serial_no"]),
    "name": VoterColumn(("Name", "नाव", "नाम"), 4.5, "L", lambda r, lang: pick(lang, r["name_en"], r["name_mr"])),
    "relative_name": VoterColumn(("Relative", "नातेवाईक", "संबंधी"), 3.5, "L",
                                 lambda r, lang: pick(lang, r["relative_name_en"], r["relative_name_mr"])),
    "gender": VoterColumn(("Gender", "लिंग", "लिंग"), 1.4, "C", _gender),
    "age": VoterColumn(("Age", "वय", "आयु"), 0.9, "R", lambda r, lang: r["age"]),
    "house_no": VoterColumn(("House No.", "घर क्र.", "मकान नं."), 1.6, "L", lambda r, lang: r["house_no"]),
    "epic_no": VoterColumn(("EPIC", "EPIC क्र.", "EPIC नं."), 2.2, "L", lambda r, lang: r["epic_no"]),
    "mobile": VoterColumn(("Mobile", "मोबाईल", "मोबाइल"), 2.6, "L",
                          lambda r, lang: ", ".join(m for m in (r["mobile_1"], r["mobile_2"]) if m) or None),
    "colour_tag": VoterColumn(("Colour", "रंग", "रंग"), 1.6, "L",
                              lambda r, lang: pick(lang, r["tag_en"], r["tag_mr"], r["tag_hi"])),
    "surveyed": VoterColumn(("Surveyed", "सर्वेक्षण", "सर्वेक्षण"), 1.3, "C",
                            lambda r, lang: word("yes" if r["is_surveyed"] else "no", lang)),
    "caste": VoterColumn(("Caste", "जात", "जाति"), 2, "L",
                         lambda r, lang: pick(lang, r["caste_en"], r["caste_mr"], r["caste_hi"])),
    "address": VoterColumn(("Address", "पत्ता", "पता"), 4, "L", lambda r, lang: pick(lang, r["address_en"], r["address_mr"])),
}
DEFAULT_COLUMNS = {
    ExportKind.voter_list: ["part_no", "serial_no", "name", "relative_name", "gender", "age", "house_no", "epic_no"],
    ExportKind.mobile_list: ["part_no", "serial_no", "name", "age", "house_no", "mobile"],
}
VOTER_KINDS = frozenset(DEFAULT_COLUMNS)


# --- the request -----------------------------------------------------------------------------------
class ExportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paper: Literal["a4", "legal"] = "a4"
    text_size: Literal["small", "normal", "large"] = "normal"
    group_by_house: bool = False
    header: str | None = Field(None, max_length=200)
    report: Literal["survey_progress", "colour_tags", "demographics"] | None = None


class AreaFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ward_id: uuid.UUID | None = None
    booth_id: uuid.UUID | None = None


@dataclass
class Spec:
    kind: ExportKind
    format: ExportFormat
    language: str
    voters: VoterFilter | None = None      # voter_list, mobile_list
    areas: AreaFilter | None = None        # report, turnout
    columns: list[str] = field(default_factory=list)
    options: ExportOptions = field(default_factory=ExportOptions)

    def stored(self) -> dict[str, Any]:
        """The normalised filter, columns and options, as kept on the export row."""
        f = self.voters if self.voters is not None else self.areas
        return {"filter": f.model_dump(mode="json", exclude_none=True) if f else {},
                "columns": self.columns, "options": self.options.model_dump(mode="json", exclude_none=True)}


def _invalid(prefix: str, err: ValidationError) -> ApiError:
    e = err.errors()[0]
    where = ".".join(str(p) for p in (prefix, *e["loc"]))
    return ApiError(422, "validation_error", f"{where}: {e['msg']}")


def parse(conn: Connection, scope: Scope, body: ExportIn) -> Spec:
    """Check an export request inside the user's area (422 / 404) and normalise it."""
    try:
        options = ExportOptions(**body.options)
    except ValidationError as e:
        raise _invalid("options", e) from None
    spec = Spec(kind=body.kind, format=body.format, language=body.language, options=options)

    if body.kind in VOTER_KINDS:
        try:
            spec.voters = VoterFilter(**body.filter)
        except ValidationError as e:
            raise _invalid("filter", e) from None
        if body.kind == ExportKind.mobile_list:
            if spec.voters.has_mobile is False:
                raise ApiError(422, "validation_error", "filter.has_mobile: a mobile list holds only voters with a mobile.")
            spec.voters.has_mobile = True
        unknown = [c for c in body.columns if c not in COLUMNS]
        if unknown or len(set(body.columns)) != len(body.columns):
            raise ApiError(422, "validation_error", f"columns: each once, from {', '.join(COLUMNS)}.")
        spec.columns = list(body.columns) or list(DEFAULT_COLUMNS[body.kind])
        if options.report is not None:
            raise ApiError(422, "validation_error", "options.report: only for kind report.")
        voter_where(conn, scope, spec.voters)   # areas outside the user's area: 404
        return spec

    if body.columns:
        raise ApiError(422, "validation_error", "columns: only for voter and mobile lists.")
    if body.kind == ExportKind.report:
        options.report = options.report or "survey_progress"
    elif options.report is not None:
        raise ApiError(422, "validation_error", "options.report: only for kind report.")
    try:
        spec.areas = AreaFilter(**body.filter)
    except ValidationError as e:
        raise _invalid("filter", e) from None
    if spec.areas.booth_id is not None and options.report != "demographics":
        raise ApiError(422, "validation_error", "filter.booth_id: only for the demographics report (use ward_id).")
    for area in (spec.areas.ward_id, spec.areas.booth_id):
        if area is not None:
            require_area(conn, scope, area)
    return spec


# --- the document ----------------------------------------------------------------------------------
@dataclass
class Column:
    heading: str
    weight: float = 1.0
    align: str = "L"


@dataclass
class Section:
    columns: list[Column]
    rows: list[list[Any]]
    title: str | None = None
    groups: dict[int, str] = field(default_factory=dict)    # row index -> a heading line printed before it
    bold: set[int] = field(default_factory=set)             # row indexes printed bold (totals)


@dataclass
class Document:
    title: str
    lines: list[str]
    sections: list[Section]
    row_count: int
    file_stem: str


def _house_key(house: str | None) -> tuple[Any, ...]:
    """Natural order: 2 before 10, 10A after 10; no house number last."""
    if not house:
        return ((2, ""),)
    return tuple((0, int(p)) if p.isdigit() else (1, p.lower()) for p in re.split(r"(\d+)", house) if p)


def _voter_section(conn: Connection, scope: Scope, spec: Spec) -> Section:
    assert spec.voters is not None
    where, params = voter_where(conn, scope, spec.voters)
    rows = conn.execute(text(f"""
        SELECT v.part_no, v.booth_no, v.booth_id, v.serial_no, nullif(v.full_name_mr, '') AS name_mr,
               nullif(v.full_name_en, '') AS name_en, v.relative_name_mr, v.relative_name_en, v.gender::text AS gender,
               v.age, v.house_no, v.epic_no, v.address_mr, v.address_en, s.mobile_1, s.mobile_2,
               coalesce(s.is_surveyed, false) AS is_surveyed, c.label_mr AS tag_mr, c.label_en AS tag_en,
               c.label_hi AS tag_hi, ca.name_mr AS caste_mr, ca.name_en AS caste_en, ca.name_hi AS caste_hi
          FROM app.voters v
          LEFT JOIN app.voter_surveys s ON s.tenant_id = v.tenant_id AND s.voter_id = v.id
          LEFT JOIN app.color_tags c ON c.tenant_id = s.tenant_id AND c.id = s.color_tag_id
          LEFT JOIN app.castes ca ON ca.tenant_id = s.tenant_id AND ca.id = s.caste_id
         WHERE {' AND '.join(where)}
         ORDER BY {_SORT}
         LIMIT :n"""), {**params, "n": MAX_ROWS + 1}).mappings().all()
    if len(rows) > MAX_ROWS:
        raise JobFailed(f"More than {MAX_ROWS:,} voters: choose a Village Panchayat or part, or more filters.")
    lang, cols = spec.language, [COLUMNS[c] for c in spec.columns]
    section = Section(columns=[Column(c.words[LANG_INDEX[lang]], c.weight, c.align) for c in cols], rows=[])
    if spec.options.group_by_house:
        rows = sorted(rows, key=lambda r: (r["part_no"], r["booth_no"] or 0, _house_key(r["house_no"]), r["serial_no"]))
    last = None
    for r in rows:
        if spec.options.group_by_house and (r["booth_id"], r["house_no"]) != last:
            last = (r["booth_id"], r["house_no"])
            section.groups[len(section.rows)] = (f"{word('booth', lang)} {r['part_no']} · "
                                                 f"{word('house', lang)} {r['house_no'] or '-'}")
        section.rows.append([c.value(r, lang) for c in cols])
    return section


def _area_cells(level: str, name: str) -> list[str | None]:
    return [name, None] if level == "ward" else [None, name]


def _area_columns(lang: str) -> list[Column]:
    return [Column(word("ward", lang), 3), Column(word("booth", lang), 3)]


def _report_sections(conn: Connection, user: Principal, scope: Scope, spec: Spec) -> list[Section]:
    lang, areas = spec.language, spec.areas or AreaFilter()
    n = Column  # short
    if spec.kind == ExportKind.turnout:
        t = turnout_report(conn, user, scope, areas.ward_id)
        rows = [[*_area_cells(a.level, a.name), a.total, a.done, a.percent] for a in t.by_area]
        rows.append([word("total", lang), None, t.total, t.voted, t.percent])
        sections = [Section([*_area_columns(lang), n(word("total", lang), 1.5, "R"), n(word("voted", lang), 1.5, "R"),
                             n("%", 1, "R")], rows, bold={len(rows) - 1})]
        if t.by_hour:
            sections.append(Section([n(word("hour", lang), 2), n(word("voted", lang), 1.5, "R"),
                                     n(word("so_far", lang), 1.5, "R")],
                                    [[f"{h.hour:02d}:00-{h.hour + 1:02d}:00", h.voted, h.cumulative] for h in t.by_hour],
                                    title=word("by_hour", lang)))
        return sections

    report = spec.options.report
    if report == "survey_progress":
        s = survey_progress(conn, user, scope, areas.ward_id)
        rows = [[*_area_cells(a.level, a.name), a.total, a.done, a.percent] for a in s.by_area]
        rows.append([word("total", lang), None, s.total, s.surveyed, s.percent])
        return [Section([*_area_columns(lang), n(word("total", lang), 1.5, "R"), n(word("surveyed", lang), 1.5, "R"),
                         n("%", 1, "R")], rows, bold={len(rows) - 1})]

    if report == "colour_tags":
        c = colour_tags(conn, user, scope, areas.ward_id)
        labels = {r.id: pick(lang, r.label_en, r.label_mr, r.label_hi) for r in conn.execute(
            text("SELECT id, label_mr, label_en, label_hi FROM app.color_tags"))}
        tags = [x.color_tag_id for x in c.by_tag]
        heads = [n(labels.get(t, "?") if t else word("no_tag", lang), 1.5, "R") for t in tags]

        def counts(items: list[Any]) -> list[int]:
            got = {x.color_tag_id: x.count for x in items}
            return [got.get(t, 0) for t in tags] + [sum(got.values())]

        rows = [[*_area_cells(a["level"], a["name"]), *counts(c.by_area[str(a["id"])])]
                for a in areas_in(conn, scope, areas.ward_id)]
        rows.append([word("total", lang), None, *counts(c.by_tag)])
        return [Section([*_area_columns(lang), *heads, n(word("total", lang), 1.5, "R")], rows, bold={len(rows) - 1})]

    d = demographics(conn, user, scope, areas.ward_id, areas.booth_id)
    rows = [[word("unknown", lang) if b.band == "unknown" else b.band, b.male, b.female, b.other,
             b.male + b.female + b.other] for b in d.age_bands]
    rows.append([word("total", lang), d.male, d.female, d.other, d.total])
    return [Section([n(word("age", lang), 2), *(n(word(g, lang), 1.5, "R") for g in "MFO"),
                     n(word("total", lang), 1.5, "R")], rows, bold={len(rows) - 1})]


def _area_line(conn: Connection, area: uuid.UUID | None, lang: str) -> str | None:
    if area is None:
        return None
    g = conn.execute(text("SELECT level::text AS level, name_en, name_mr FROM app.geo_units WHERE id = :id"),
                     {"id": area}).mappings().one()
    level = "ward" if g["level"] == "ward" else "booth" if g["level"] == "booth" else None
    name = pick(lang, g["name_en"], g["name_mr"])
    return f"{word(level, lang)}: {name}" if level else name


def build(conn: Connection, user: Principal, scope: Scope, spec: Spec) -> Document:
    lang = spec.language
    if spec.kind in VOTER_KINDS:
        sections = [_voter_section(conn, scope, spec)]
        count = len(sections[0].rows)
        stem, title = spec.kind.value, word(spec.kind.value, lang)
        f = spec.voters
        area_ids = (f.ward_id, f.booth_id) if f else ()
    else:
        sections = _report_sections(conn, user, scope, spec)
        count = sum(len(s.rows) for s in sections)
        stem = spec.kind.value if spec.kind == ExportKind.turnout else spec.options.report or "report"
        title = word(stem, lang)
        a = spec.areas or AreaFilter()
        area_ids = (a.ward_id, a.booth_id)
    now = datetime.now(IST)
    lines = [x for x in (spec.options.header, *(_area_line(conn, i, lang) for i in area_ids)) if x]
    printed = f"{word('printed', lang)}: {now:%d-%m-%Y %H:%M}"
    lines.append(f"{printed} · {count} {word('voters', lang)}" if spec.kind in VOTER_KINDS else printed)
    return Document(title=title, lines=lines, sections=sections, row_count=count,
                    file_stem=f"{stem}-{now:%Y%m%d-%H%M}")


# --- writers ---------------------------------------------------------------------------------------
TEXT_SIZES = {"small": 7, "normal": 9, "large": 11}


def write_xlsx(doc: Document) -> bytes:
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook(write_only=True)
    ws = wb.create_sheet(re.sub(r"[\[\]:*?/\\]", " ", doc.title)[:31])
    widest = max(doc.sections, key=lambda s: len(s.columns))
    for i, c in enumerate(widest.columns, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(8, c.weight * 7)
    if len(doc.sections) == 1:
        ws.freeze_panes = f"A{len(doc.lines) + 4}"   # below the headings

    def cell(value: Any, bold: bool = False, size: int | None = None, fill: bool = False, align: str = "L"):
        c = WriteOnlyCell(ws, value=value)
        if bold or size:
            c.font = Font(bold=bold, size=size)
        if fill:
            c.fill = PatternFill("solid", fgColor="E6E6E6")
        if align != "L":
            c.alignment = Alignment(horizontal={"R": "right", "C": "center"}[align])
        return c

    ws.append([cell(doc.title, bold=True, size=14)])
    for line in doc.lines:
        ws.append([line])
    for s in doc.sections:
        ws.append([])
        if s.title:
            ws.append([cell(s.title, bold=True)])
        ws.append([cell(c.heading, bold=True, fill=True, align=c.align) for c in s.columns])
        for i, row in enumerate(s.rows):
            bold = i in s.bold
            ws.append([cell(v, bold=bold, align=c.align) if bold or c.align != "L" else v
                       for v, c in zip(row, s.columns, strict=True)])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


_DEVANAGARI = re.compile("[ऀ-ॿ]")


def write_pdf(doc: Document, options: ExportOptions, lang: str) -> tuple[bytes, int]:
    """One line per row, cells never wrap: text too long for its column is cut with "…". The headings
    repeat on every page. fpdf2's table() lays every cell out twice: ~200 s for the whole constituency.

    Shaping (HarfBuzz) is most of the time and Latin text needs none, so only text with Devanagari is
    shaped: in family "body" (Noto Sans, Noto Sans Devanagari as fallback, always shaped); all other
    text in family "latn" (the same Noto Sans file, never shaped). Two families, because fpdf2 2.9 mixes
    up glyphs when one font is used both shaped and unshaped ("99" printed as "22"). Whole constituency,
    English names: ~25 s."""
    from fpdf import FPDF

    size = TEXT_SIZES[options.text_size]
    h = size * 0.55                       # row height, mm
    widest = max(sum(c.weight for c in s.columns) for s in doc.sections)
    page_word = word("page", lang)

    class Pdf(FPDF):
        def footer(self) -> None:
            self.set_y(-10)
            self.set_font("body", size=7)
            put(0, 5, f"{doc.title} · {page_word} {self.page_no()}", align="C")

    pdf = Pdf(orientation="L" if widest > 17 else "P", format="A4" if options.paper == "a4" else "Legal")
    pdf.set_margins(10, 10, 10)
    pdf.set_auto_page_break(True, margin=14)
    for family, stem in (("body", "NotoSans"), ("deva", "NotoSansDevanagari"), ("latn", "NotoSans")):
        pdf.add_font(family, "", FONT_DIR / f"{stem}-Regular.ttf")
        pdf.add_font(family, "B", FONT_DIR / f"{stem}-Bold.ttf")
    pdf.set_fallback_fonts(["deva"])

    def put(w: float, height: float, value: Any, align: str = "L", border: int = 0, fill: bool = False,
            ln: bool = False) -> None:
        """A cell in the current style and size (set with family "body"); the family is picked here."""
        txt = "" if value is None else str(value)
        deva = bool(_DEVANAGARI.search(txt))
        pdf.set_font("body" if deva else "latn", pdf.font_style, pdf.font_size_pt)
        pdf.set_text_shaping(deva)
        room = (w or pdf.epw) - 2 * pdf.c_margin
        # no glyph is wider than 1 em (font_size, mm): shorter text needs no measuring
        if len(txt) * pdf.font_size > room and pdf.get_string_width(txt) > room:
            while txt and pdf.get_string_width(txt + "…") > room:
                txt = txt[:-1]
            txt += "…"
        pdf.cell(w, height, txt, border=border, align=align, fill=fill,
                 new_x="LMARGIN" if ln else "RIGHT", new_y="NEXT" if ln else "TOP")

    pdf.add_page()
    pdf.set_font("body", "B", size + 5)
    put(0, (size + 5) * 0.55, doc.title, ln=True)
    pdf.set_font("body", size=size)
    for line in doc.lines:
        put(0, h, line, ln=True)

    for s in doc.sections:
        total = sum(c.weight for c in s.columns)
        widths = [pdf.epw * c.weight / total for c in s.columns]

        def headings() -> None:
            pdf.set_font("body", "B", size)
            pdf.set_fill_color(230, 230, 230)
            for c, w in zip(s.columns, widths, strict=True):
                put(w, h, c.heading, c.align, border=1, fill=True)
            pdf.ln(h)
            pdf.set_font("body", size=size)

        pdf.ln(size * 0.4)
        if pdf.get_y() + 3 * h > pdf.page_break_trigger:
            pdf.add_page()
        if s.title:
            pdf.set_font("body", "B", size + 1)
            put(0, h + 1, s.title, ln=True)
        headings()
        for i, row in enumerate(s.rows):
            need = 2 * h if i in s.groups else h
            if pdf.get_y() + need > pdf.page_break_trigger:
                pdf.add_page()
                headings()
            if i in s.groups:
                pdf.set_font("body", "B", size)
                pdf.set_fill_color(245, 245, 245)
                put(0, h, s.groups[i], border=1, fill=True, ln=True)
                pdf.set_font("body", size=size)
            if i in s.bold:
                pdf.set_font("body", "B", size)
            for v, c, w in zip(row, s.columns, widths, strict=True):
                put(w, h, v, c.align, border=1)
            pdf.ln(h)
            if i in s.bold:
                pdf.set_font("body", size=size)
    return bytes(pdf.output()), pdf.pages_count


# --- the job ---------------------------------------------------------------------------------------
def _creator(conn: Connection, tenant: uuid.UUID, user_id: uuid.UUID) -> Principal:
    u = conn.execute(text("""SELECT username, role::text AS role, local_body_id, is_active, deleted_at
                               FROM app.users WHERE id = :id"""), {"id": user_id}).mappings().first()
    if u is None or not u["is_active"] or u["deleted_at"] is not None:
        raise JobFailed("The account that asked for this export is switched off.")
    return Principal(user_id=user_id, tenant_id=tenant, session_id=uuid.UUID(int=0), device_id=None,
                     role=Role(u["role"]), username=u["username"], local_body_id=u["local_body_id"],
                     must_change_password=False, device_status=None)


def make_file(conn: Connection, user: Principal, body: ExportIn) -> tuple[dict, Document, int | None]:
    """Check the request again with the user's area as it is now, build and store the file:
    (app.files row, document, page count or None)."""
    scope = load_scope(conn, user)
    try:
        spec = parse(conn, scope, body)
        doc = build(conn, user, scope, spec)
    except ApiError as e:   # the user's area changed since the request
        raise JobFailed("A Village Panchayat or part of this export is no longer in your area."
                        if e.status == 404 else e.message) from None
    pages: int | None = None
    if spec.format == ExportFormat.xlsx:
        data, mime = write_xlsx(doc), XLSX_MIME
    else:
        (data, pages), mime = write_pdf(doc, spec.options, spec.language), PDF_MIME
    stored = store_file(conn, user, FileKind.export, data, f"{doc.file_stem}.{spec.format.value}", mime)
    return stored, doc, pages


def run_export(conn: Connection, job: Job) -> None:
    e = conn.execute(text("""SELECT id, kind, format, language::text AS language, filter, columns, options, status::text
                               AS status, created_by FROM app.exports WHERE id = :id FOR UPDATE"""),
                     {"id": job.ref_id}).mappings().first()
    if e is None or e["status"] != "queued":
        return
    body = ExportIn(kind=e["kind"], format=e["format"], language=e["language"], filter=e["filter"] or {},
                    columns=list(e["columns"] or []), options=e["options"] or {})
    stored, doc, pages = make_file(conn, _creator(conn, job.tenant_id, e["created_by"]), body)
    conn.execute(text("""UPDATE app.exports SET status = 'done', file_id = :f, row_count = :rows, page_count = :pages,
                                               error = NULL, finished_at = now() WHERE id = :id"""),
                 {"id": e["id"], "f": stored["id"], "rows": doc.row_count, "pages": pages})


def fail_export(conn: Connection, job: Job, message: str) -> None:
    conn.execute(text("""UPDATE app.exports SET status = 'failed', error = :e, finished_at = now()
                          WHERE id = :id AND status IN ('queued', 'running')"""), {"id": job.ref_id, "e": message})


register(KIND, run_export, fail_export)
