# Slide decks (.pptx) with python-pptx

Use `run_python` with `pptx`. Save into the working directory with a descriptive name; the user gets a download
button.

## Build
```python
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor

prs = Presentation(); prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)   # 16:9
title = prs.slides.add_slide(prs.slide_layouts[0])
title.shapes.title.text = "Deck title"; title.placeholders[1].text = "Subtitle · date"

s = prs.slides.add_slide(prs.slide_layouts[1])           # title + content
s.shapes.title.text = "One idea per slide"
body = s.placeholders[1].text_frame; body.text = "First point"
for line in ["Second point", "Third point"]:
    p = body.add_paragraph(); p.text = line; p.level = 0
s.notes_slide.notes_text_frame.text = "Speaker notes …"

pic = prs.slides.add_slide(prs.slide_layouts[5]); pic.shapes.title.text = "Results"
pic.shapes.add_picture("chart.png", Inches(1), Inches(1.5), height=Inches(5.5))
prs.save("Deck.pptx")
```
- One message per slide; at most ~5 bullets of a few words each. Put detail in speaker notes.
- A title slide, a short agenda for decks over ~6 slides, and a closing/summary slide.
- Charts: make them with matplotlib (large fonts, no clutter), save PNG, add as a picture.
- Consistent layout: reuse the same layouts and positions; don't mix font sizes on a slide.

## Check before you answer
Reopen the file and print each slide's title and bullet count. Tell the user how many slides and what they cover.
