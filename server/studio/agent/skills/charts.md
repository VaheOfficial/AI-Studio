# Charts with matplotlib

Use `run_python`. Every figure still open at the end of a call is shown to the user automatically, so don't call
`plt.show()`; call `plt.savefig("name.png")` only when the chart also goes into a document or the user wants the
file.

## Rules
- matplotlib only (not seaborn), one chart per figure (no subplots) unless the user asks for a grid.
- Don't set colors or styles unless the user asks: the defaults are consistent and readable.
- Always a title, axis labels with units, and a legend when there is more than one series.
- Readable at a glance: `figsize=(8, 4.5)`, rotate long tick labels, format big numbers
  (`matplotlib.ticker.FuncFormatter(lambda v, _: f"{v/1e6:.1f}M")`), dates with `fig.autofmt_xdate()`.
- Pick the chart for the question: line for trends over time, bar for comparing categories, histogram for a
  distribution, scatter for a relationship. No pie charts with more than ~5 slices, no 3D.

```python
import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(8, 4.5))
ax.plot(df["date"], df["sales"], label="Sales")
ax.set_title("Monthly sales"); ax.set_xlabel("Month"); ax.set_ylabel("USD"); ax.legend()
fig.autofmt_xdate()
```

## Tables
To show data as a table in the chat, make the DataFrame the last line of the code (only the first 50 rows are
shown). Summarize what the numbers mean in your reply.
