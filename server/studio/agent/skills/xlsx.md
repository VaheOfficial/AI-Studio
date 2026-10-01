# Spreadsheets (.xlsx) with openpyxl (and pandas)

Use `run_python`. For data, build a pandas DataFrame and write it; use openpyxl for formatting, formulas and
charts. Save into the working directory with a descriptive name; the user gets a download button.

## Build
```python
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference

df.to_excel("Budget.xlsx", sheet_name="Data", index=False)
wb = load_workbook("Budget.xlsx"); ws = wb["Data"]
for cell in ws[1]:                                   # header row
    cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor="4F46E5")
ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
for col in ws.columns:                               # sensible widths
    width = max(len(str(c.value or "")) for c in col) + 2
    ws.column_dimensions[get_column_letter(col[0].column)].width = min(width, 50)
last = ws.max_row
ws[f"C{last + 1}"] = f"=SUM(C2:C{last})"; ws[f"C{last + 1}"].font = Font(bold=True)
for row in ws.iter_rows(min_row=2, min_col=3, max_col=3):
    for c in row: c.number_format = '#,##0.00'
chart = BarChart(); chart.title = "Spend by category"
chart.add_data(Reference(ws, min_col=3, min_row=1, max_row=last), titles_from_data=True)
chart.set_categories(Reference(ws, min_col=1, min_row=2, max_row=last))
ws.add_chart(chart, f"E2")
wb.save("Budget.xlsx")
```
- Keep live formulas (`=SUM(...)`) where the user will keep editing, instead of pasting computed numbers.
- Number formats for money, percentages (`0.0%`) and dates (`yyyy-mm-dd`).
- One table per sheet, header in row 1, no merged cells inside data.
- Don't use LibreOffice or the Word/PDF approach for spreadsheets.

## Reading
`pd.read_excel("file.xlsx", sheet_name=None)` gives every sheet; show `df.head()` and `df.describe()` first.

## Check before you answer
Reload with `load_workbook(..., data_only=False)` and print the sheet names, dimensions and a few cells (formulas
aren't calculated until Excel opens the file - say so if the user expects values).
