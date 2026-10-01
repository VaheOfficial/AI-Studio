# PDFs: creating (reportlab), reading (pdfplumber) and editing (pypdf)

Use `run_python`. Save into the working directory with a descriptive name; the user gets a download button.

## Create
```python
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak

styles = getSampleStyleSheet()
doc = SimpleDocTemplate("Report.pdf", pagesize=A4, leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm,
                        bottomMargin=2*cm, title="Report")
story = [Paragraph("Title", styles["Title"]), Paragraph("Intro …", styles["BodyText"]), Spacer(1, 12)]
t = Table([["Item", "Qty"], ["Widget", "2"]], hAlign="LEFT")
t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4F46E5")),
                       ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.5, colors.grey)]))
story += [t, Spacer(1, 12), Image("chart.png", width=16*cm, height=9*cm)]
doc.build(story)
```
- Use Paragraph styles (Title, Heading1-3, BodyText) rather than hand-placed text; `PageBreak()` between parts.
- Letter size for US users, A4 otherwise (use what you know about the user).
- Only the built-in fonts cover Latin text; for other scripts register a TTF font from `C:/Windows/Fonts`.

## Read
```python
import pdfplumber
with pdfplumber.open("in.pdf") as pdf:
    for i, page in enumerate(pdf.pages[:5]):
        print(i + 1, (page.extract_text() or "")[:1500])
        for table in page.extract_tables(): print(table[:5])
```
Scanned PDFs have no text layer: say so (OCR is a last resort and English-only).

## Edit
`pypdf` merges, splits, rotates and fills forms: `PdfWriter`, `writer.append(reader)`, `page.rotate(90)`,
`writer.update_page_form_field_values(writer.pages[0], {"Name": "…"})`. Write to a new file.

## Check before you answer
Reopen the result with pdfplumber and print the page count and the first lines of page 1.
