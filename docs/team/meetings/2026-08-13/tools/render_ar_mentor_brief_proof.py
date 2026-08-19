from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.table import Table
from docx.text.paragraph import Paragraph
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    PageBreak,
    PageTemplate,
    Paragraph as RLParagraph,
    Spacer,
    Table as RLTable,
    TableStyle,
)


DOCX = Path(r"C:\Users\jctx\Desktop\AR\output\meetings\2026-08-15_AR_第三周至今_学长会议系统汇报.docx")
PDF = Path(r"C:\Users\jctx\Desktop\AR\output\meetings\render_mentor_brief\mentor_brief_proof.pdf")
FIG = Path(r"C:\Users\jctx\Desktop\AR\output\meetings\2026-08-15_AR_三层系统与产品落地图.png")

pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>"))


def iter_block_items(doc):
    parent = doc.element.body
    for child in parent.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(child, doc)
        elif child.tag == qn("w:tbl"):
            yield Table(child, doc)


styles = {
    "Normal": ParagraphStyle("Normal", fontName="STSong-Light", fontSize=8.5, leading=11, textColor=colors.HexColor("#1F2937"), spaceAfter=4),
    "Title": ParagraphStyle("Title", fontName="STSong-Light", fontSize=21, leading=27, textColor=colors.HexColor("#17365D"), spaceAfter=10),
    "Subtitle": ParagraphStyle("Subtitle", fontName="STSong-Light", fontSize=11, leading=15, textColor=colors.HexColor("#5B6573"), spaceAfter=10),
    "Heading 1": ParagraphStyle("Heading 1", fontName="STSong-Light", fontSize=14, leading=18, textColor=colors.HexColor("#2E74B5"), spaceBefore=9, spaceAfter=6, keepWithNext=True),
    "Heading 2": ParagraphStyle("Heading 2", fontName="STSong-Light", fontSize=11.5, leading=15, textColor=colors.HexColor("#2E74B5"), spaceBefore=7, spaceAfter=4, keepWithNext=True),
    "Heading 3": ParagraphStyle("Heading 3", fontName="STSong-Light", fontSize=10.5, leading=14, textColor=colors.HexColor("#1F4D78"), spaceBefore=5, spaceAfter=3, keepWithNext=True),
    "Small Note": ParagraphStyle("Small Note", fontName="STSong-Light", fontSize=7.2, leading=9, textColor=colors.HexColor("#5B6573"), spaceAfter=3),
    "List Bullet": ParagraphStyle("List Bullet", fontName="STSong-Light", fontSize=8.5, leading=11, leftIndent=18, firstLineIndent=-9, bulletIndent=8, textColor=colors.HexColor("#1F2937"), spaceAfter=3),
    "List Number": ParagraphStyle("List Number", fontName="STSong-Light", fontSize=8.5, leading=11, leftIndent=18, firstLineIndent=-9, textColor=colors.HexColor("#1F2937"), spaceAfter=3),
}


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("STSong-Light", 7)
    canvas.setFillColor(colors.HexColor("#5B6573"))
    canvas.drawRightString(letter[0] - 0.84 * inch, letter[1] - 0.37 * inch, "INTERNAL · CURRENT-STATE BRIEF · 2026-08-15")
    canvas.drawRightString(letter[0] - 0.84 * inch, 0.35 * inch, f"AR · 学长会议汇报 | {doc.page}")
    canvas.restoreState()


def render():
    PDF.parent.mkdir(parents=True, exist_ok=True)
    d = Document(DOCX)
    page_w, page_h = letter
    frame = Frame(0.84 * inch, 0.63 * inch, page_w - 1.68 * inch, page_h - 1.25 * inch, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    template = PageTemplate("main", [frame], onPage=on_page)
    out = BaseDocTemplate(str(PDF), pagesize=letter, leftMargin=0.84 * inch, rightMargin=0.84 * inch, topMargin=0.63 * inch, bottomMargin=0.63 * inch)
    out.addPageTemplates([template])
    story = []
    list_counter = 0
    for block in iter_block_items(d):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            has_page_break = bool(block._p.xpath('.//w:br[@w:type="page"]'))
            has_drawing = bool(block._p.xpath('.//w:drawing'))
            if has_page_break:
                story.append(PageBreak())
                continue
            if has_drawing and FIG.exists():
                img = Image(str(FIG), width=6.45 * inch, height=3.58 * inch)
                img.hAlign = "CENTER"
                story.extend([img, Spacer(1, 4)])
                continue
            if not text:
                story.append(Spacer(1, 3))
                continue
            sname = block.style.name if block.style is not None else "Normal"
            style = styles.get(sname, styles["Normal"])
            if sname.startswith("List Bullet"):
                story.append(RLParagraph("• " + esc(text), style))
            elif sname.startswith("List Number"):
                list_counter += 1
                story.append(RLParagraph(f"{list_counter}. " + esc(text), style))
            else:
                if not sname.startswith("List"):
                    list_counter = 0
                story.append(RLParagraph(esc(text), style))
        else:
            grid = block._tbl.tblGrid
            widths = []
            for col in grid.gridCol_lst:
                widths.append(int(col.get(qn("w:w"))) / 20.0)
            data = []
            fills = []
            for ridx, row in enumerate(block.rows):
                line = []
                for cidx, cell in enumerate(row.cells):
                    line.append(RLParagraph(esc(cell.text), styles["Small Note"]))
                    shd = cell._tc.tcPr.find(qn("w:shd")) if cell._tc.tcPr is not None else None
                    if shd is not None and shd.get(qn("w:fill")) not in (None, "auto", "FFFFFF"):
                        fills.append((ridx, cidx, shd.get(qn("w:fill"))))
                data.append(line)
            rt = RLTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
            cmds = [
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D5DAE2")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F2F4F7")),
            ]
            for ridx, cidx, fill in fills:
                try:
                    cmds.append(("BACKGROUND", (cidx, ridx), (cidx, ridx), colors.HexColor("#" + fill)))
                except Exception:
                    pass
            rt.setStyle(TableStyle(cmds))
            story.extend([rt, Spacer(1, 5)])
    out.build(story)
    print(PDF)


if __name__ == "__main__":
    render()
