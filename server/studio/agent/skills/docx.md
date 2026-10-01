# Word documents (.docx) with python-docx

Use `run_python` with `docx` (python-docx). Save into the working directory with a descriptive file name
(`Q3-report.docx`, not `output.docx`); the user gets a download button for every file you create.

## Build
```python
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH

doc = Document()
style = doc.styles["Normal"]; style.font.name = "Calibri"; style.font.size = Pt(11)
doc.add_heading("Title", level=0)            # the document title
doc.add_paragraph("Intro paragraph …")
doc.add_heading("Section", level=1)
doc.add_paragraph("A point", style="List Bullet")
doc.add_paragraph("A step", style="List Number")
t = doc.add_table(rows=1, cols=3); t.style = "Light Grid Accent 1"
for cell, text in zip(t.rows[0].cells, ["Item", "Qty", "Price"]): cell.text = text
row = t.add_row().cells; row[0].text = "Widget"; row[1].text = "2"; row[2].text = "$4.00"
doc.add_picture("chart.png", width=Inches(6))  # save a matplotlib chart first if you need one
doc.save("Report.docx")
```
- Headings with `add_heading` (level 0 = title, 1–3 sections) so Word's navigation pane and table of contents work.
- Real lists via the `List Bullet` / `List Number` styles, not typed dashes.
- Page breaks: `doc.add_page_break()`. Margins: `doc.sections[0].left_margin = Inches(1)`.
- Headers/footers: `doc.sections[0].header.paragraphs[0].text = "…"`.
- Bold/italic runs: `p = doc.add_paragraph(); r = p.add_run("bold"); r.bold = True`.

## Editing an existing file
Open with `Document("in.docx")`, change paragraphs/runs (keep run formatting: edit `run.text`, not
`paragraph.text`, when styling matters), save under a new name unless the user asked to overwrite.

## Check before you answer
Re-open the saved file and print the headings and the first lines of each section to confirm the content, then tell
the user what's in it in a sentence or two. Don't paste the whole document into the chat.
