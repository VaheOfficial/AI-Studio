"""Structured document operations in the CPU document environment."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from xml.sax.saxutils import escape


def replace_formatted(paragraph, old, replacement):
    """Replace text across runs without resetting unaffected character formatting."""
    runs=paragraph.runs
    text=''.join(run.text for run in runs)
    if paragraph.text != text:
        raise ValueError('This paragraph contains hyperlinks or unsupported inline structures; use a live editor for this replacement')
    positions=[];offset=0
    for run in runs:
        positions.append((offset,offset+len(run.text)));offset+=len(run.text)
    starts=[];offset=0
    while (offset:=text.find(old,offset))>=0:
        starts.append(offset);offset+=len(old)
    for start in reversed(starts):
        end=start+len(old)
        affected=[i for i,(low,high) in enumerate(positions) if low<end and high>start]
        for i in affected:
            if any(node.tag.rsplit('}',1)[-1] not in ('rPr','t','tab','br','cr') for node in runs[i]._r):
                raise ValueError('Affected run contains non-text content; use a live editor')
        first,last=affected[0],affected[-1]
        prefix=runs[first].text[:start-positions[first][0]]
        suffix=runs[last].text[end-positions[last][0]:]
        runs[first].text=prefix+replacement+(suffix if first==last else '')
        for i in affected[1:]: runs[i].text=suffix if i==last else ''


def rectangular(rows):
    if not isinstance(rows,list) or len(rows) > 1000 or any(not isinstance(row,list) for row in rows):
        raise ValueError('Provide at most 1,000 rows')
    if rows and (len(rows[0]) > 1000 or any(len(row) != len(rows[0]) for row in rows) or len(rows)*len(rows[0]) > 100000):
        raise ValueError('Provide a rectangular table under 100,000 cells')
    return rows


def execute(request):
    action, options = request['action'], request.get('options',{})
    source = Path(request['source']) if request.get('source') else None
    directory = Path(request['directory']); directory.mkdir(parents=True,exist_ok=True)
    assets = request.get('assets',[])
    import re
    name = re.sub(r'[^\w.-]','_',Path(request.get('name') or 'result').stem)[:120].strip('.') or 'result'
    def asset(index):
        if isinstance(index,bool) or not isinstance(index,int) or not 0 <= index < len(assets): raise ValueError('Image asset index is out of bounds')
        from PIL import Image
        with Image.open(assets[index]) as image:
            if image.width * image.height > 20000000: raise ValueError('Image exceeds 20 megapixels')
            image.verify()
        return assets[index]
    def destination(extension): return directory / (name + extension)
    result, outputs = {}, []
    if source:
        if source.suffix.lower() not in ('.docx','.xlsx','.pptx','.pdf'): raise ValueError('Choose a DOCX, XLSX, PPTX or PDF source')
        if source.stat().st_size > 32*1024*1024: raise ValueError('Source exceeds 32 MiB')
        result['source_hash'] = hashlib.sha256(source.read_bytes()).hexdigest()
        if source.suffix.lower() in ('.docx','.xlsx','.pptx'):
            import zipfile
            with zipfile.ZipFile(source) as archive:
                if sum(entry.file_size for entry in archive.infolist()) > 100*1024*1024:
                    raise ValueError('Expanded document exceeds 100 MiB')
    if action == 'inspect':
        if not source: raise ValueError('inspect needs a source')
        suffix = source.suffix.lower()
        if suffix == '.docx':
            from docx import Document
            doc = Document(source)
            result.update(paragraphs=[p.text for p in doc.paragraphs][:2000], tables=[[[c.text for c in row.cells] for row in list(table.rows)[:200]] for table in doc.tables[:50]])
        elif suffix == '.xlsx':
            from openpyxl import load_workbook
            book = load_workbook(source,read_only=True,data_only=bool(options.get('cached_values')))
            result['sheets'] = [{'name':sheet.title,'rows':sheet.max_row,'columns':sheet.max_column,
                'preview':list(sheet.iter_rows(max_row=min(sheet.max_row,100),max_col=min(sheet.max_column,50),values_only=True))} for sheet in book.worksheets]
            book.close()
        elif suffix == '.pptx':
            from pptx import Presentation
            presentation = Presentation(source)
            result['slides'] = [{'index':i,'text':[shape.text for shape in slide.shapes if shape.has_text_frame]} for i,slide in enumerate(presentation.slides)][:200]
        elif suffix == '.pdf':
            from pypdf import PdfReader
            pdf = PdfReader(source)
            result.update(pages=len(pdf.pages),text=[{'page':i+1,'text':(page.extract_text() or '')[:12000]} for i,page in enumerate(pdf.pages) if i < 100])
        else: raise ValueError('Supported source formats: DOCX, XLSX, PPTX and PDF')
    elif action in ('create_document','edit_document'):
        from docx import Document
        doc = Document(source) if action == 'edit_document' and source else Document()
        if action == 'edit_document':
            old, replacement = options['old'], options['replacement']
            if not old: raise ValueError('Original passage cannot be empty')
            paragraphs = [*doc.paragraphs,*[p for table in doc.tables for row in table.rows for cell in row.cells for p in cell.paragraphs]]
            count = sum(p.text.count(old) for p in paragraphs)
            if count != int(options.get('expected_count',1)): raise ValueError('Passage count differs from expected_count')
            for paragraph in paragraphs:
                if old in paragraph.text: replace_formatted(paragraph,old,replacement)
            result.update(replacements=count,replaced_paragraph_inline_formatting='Unchanged runs retained; replacement inherits the first matched run')
        for block in options.get('blocks',[])[:1000]:
            if block['type'] == 'heading': doc.add_heading(str(block['text']),max(1,min(int(block.get('level',1)),4)))
            elif block['type'] == 'paragraph': doc.add_paragraph(str(block['text']))
            elif block['type'] == 'bullet': doc.add_paragraph(str(block['text']),style='List Bullet')
            elif block['type'] == 'table':
                rows = rectangular(block['rows'])
                if not rows: continue
                table = doc.add_table(rows=len(rows),cols=len(rows[0])); table.style = 'Table Grid'
                for i,row in enumerate(rows):
                    for j,value in enumerate(row): table.cell(i,j).text = str(value if value is not None else '')
            elif block['type'] == 'image':
                from docx.shared import Inches
                doc.add_picture(asset(block['asset_index']),width=Inches(max(0.5,min(float(block.get('width_inches',5)),7))))
            else: raise ValueError('Unknown document block')
        target = destination('.docx'); doc.save(target); outputs.append(target)
    elif action in ('create_sheet','write_cells','format_cells','sort_rows','add_chart'):
        from openpyxl import Workbook, load_workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.chart import BarChart, LineChart, PieChart, Reference
        from openpyxl.utils.cell import range_boundaries
        book = load_workbook(source) if source else Workbook()
        sheet_name = options.get('sheet') or book.active.title
        if not source and sheet_name not in book.sheetnames: book.active.title = sheet_name
        sheet = book[sheet_name] if sheet_name in book.sheetnames else book.create_sheet(sheet_name)
        if action in ('create_sheet','write_cells'):
            values = rectangular(options['rows'])
            start_row, start_column = int(options.get('start_row',1)), int(options.get('start_column',1))
            if start_row < 1 or start_column < 1 or start_row+len(values) > 1048577 or start_column+max((len(row) for row in values),default=0) > 16385: raise ValueError('Cells exceed workbook bounds')
            for i,row in enumerate(values):
                for j,value in enumerate(row):
                    cell = sheet.cell(start_row+i,start_column+j); cell.value = value
                    if isinstance(value,str) and value.startswith('=') and not options.get('allow_formulas'): cell.data_type = 's'
            result['written_cells'] = sum(len(row) for row in values)
            result['formula_values'] = 'Calculated by the spreadsheet application when opened'
        elif action == 'format_cells':
            low_column,low_row,high_column,high_row = range_boundaries(options['range'])
            if (high_column-low_column+1)*(high_row-low_row+1) > 100000: raise ValueError('Formatting range exceeds 100,000 cells')
            for row in sheet.iter_rows(min_row=low_row,max_row=high_row,min_col=low_column,max_col=high_column):
                for cell in row:
                    if 'bold' in options: cell.font = Font(name=cell.font.name,size=cell.font.sz,bold=bool(options['bold']),italic=cell.font.i)
                    if options.get('number_format'): cell.number_format = options['number_format']
                    if options.get('fill'): cell.fill = PatternFill('solid',fgColor=options['fill'].lstrip('#'))
                    if options.get('wrap'): cell.alignment = Alignment(wrap_text=True)
        elif action == 'sort_rows':
            if sheet.max_row*sheet.max_column > 100000: raise ValueError('Sort exceeds 100,000 cells')
            typed = [[(cell.value,cell.data_type) for cell in row] for row in sheet.iter_rows()]
            rows = typed; start = 1 if options.get('headers',True) else 0; column = int(options.get('column',0))
            if not 0 <= column < sheet.max_column: raise ValueError('Sort key is outside the sheet')
            rows[start:] = sorted(rows[start:],key=lambda row:(row[column][0] is None,0 if isinstance(row[column][0],(int,float)) else 1,row[column][0] if isinstance(row[column][0],(int,float)) else str(row[column][0]).casefold()),reverse=bool(options.get('descending')))
            for i,row in enumerate(rows,1):
                for j,(value,data_type) in enumerate(row,1):
                    cell = sheet.cell(i,j); cell.value = value; cell.data_type = data_type
            result['formatting'] = 'Cell positions retained; row values reordered'
        elif action == 'add_chart':
            low_column,low_row,high_column,high_row = range_boundaries(options['range'])
            chart_type = options.get('chart','bar')
            if chart_type not in ('bar','line','pie'): raise ValueError('Chart type must be bar, line or pie')
            chart = {'bar':BarChart,'line':LineChart,'pie':PieChart}[chart_type](); chart.title = options.get('title','Chart')
            chart.add_data(Reference(sheet,min_col=low_column+1,max_col=high_column,min_row=low_row,max_row=high_row),titles_from_data=True)
            chart.set_categories(Reference(sheet,min_col=low_column,min_row=low_row+1,max_row=high_row)); sheet.add_chart(chart,options.get('anchor','H2'))
        target = destination('.xlsx'); book.save(target); book.close(); outputs.append(target)
    elif action in ('create_slides','replace_slide_text'):
        from pptx import Presentation
        from pptx.util import Inches, Pt
        presentation = Presentation(source) if source else Presentation()
        if not source: presentation.slide_width = Inches(13.333); presentation.slide_height = Inches(7.5)
        if action == 'replace_slide_text':
            index = int(options['slide'])
            if not 0 <= index < len(presentation.slides): raise ValueError('Slide index is out of bounds')
            old,replacement = options['old'],options['replacement']
            if not old: raise ValueError('Original passage cannot be empty')
            shapes = [shape for shape in presentation.slides[index].shapes if shape.has_text_frame and old in shape.text]
            if sum(paragraph.text.count(old) for shape in shapes for paragraph in shape.text_frame.paragraphs) != int(options.get('expected_count',1)): raise ValueError('Slide passage count changed')
            for shape in shapes:
                for paragraph in shape.text_frame.paragraphs:
                    if old in paragraph.text: paragraph.text = paragraph.text.replace(old,replacement)
        for descriptor in options.get('slides',[])[:100]:
            slide = presentation.slides.add_slide(presentation.slide_layouts[6])
            def text_box(text,x,y,w,h,size,bold=False):
                shape = slide.shapes.add_textbox(Inches(x),Inches(y),Inches(w),Inches(h)); shape.text_frame.word_wrap = True
                paragraph = shape.text_frame.paragraphs[0]; paragraph.text = text; paragraph.font.size = Pt(size); paragraph.font.bold = bold
                return shape
            text_box(str(descriptor.get('title','')),0.6,0.45,12,1,30,True)
            text_box('\n'.join(str(item) for item in descriptor.get('bullets',[])),6.5 if descriptor.get('asset_index') is not None else 0.7,1.6,6.0 if descriptor.get('asset_index') is not None else 11.8,4.7,22)
            if descriptor.get('notes'): slide.notes_slide.notes_text_frame.text = descriptor['notes']
            if descriptor.get('asset_index') is not None: slide.shapes.add_picture(asset(descriptor['asset_index']),Inches(0.8),Inches(2),width=Inches(5))
        target = destination('.pptx'); presentation.save(target); outputs.append(target); result['slides'] = len(presentation.slides)
    elif action == 'create_pdf':
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from matplotlib.font_manager import findfont
        pdfmetrics.registerFont(TTFont('DocumentSans',findfont('DejaVu Sans')))
        styles = getSampleStyleSheet()
        for style in styles.byName.values(): style.fontName = 'DocumentSans'
        story = []
        for block in options.get('blocks',[])[:1000]:
            kind = block['type']
            if kind in ('heading','paragraph','bullet'):
                style = styles['Heading1' if kind == 'heading' else 'BodyText']; text = escape(str(block['text'])).replace('\n','<br/>')
                story.append(Paragraph(('• ' if kind == 'bullet' else '')+text,style)); story.append(Spacer(1,10))
            elif kind == 'table':
                values = rectangular(block['rows'])
                table = Table([[Paragraph(escape(str(value if value is not None else '')),styles['BodyText']) for value in row] for row in values],repeatRows=1)
                table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),0.5,colors.grey),('VALIGN',(0,0),(-1,-1),'TOP')])); story.append(table); story.append(Spacer(1,10))
            elif kind == 'image': story.append(Image(asset(block['asset_index']),width=360,height=240,kind='proportional'))
            else: raise ValueError('Unknown PDF block')
        target = destination('.pdf'); SimpleDocTemplate(str(target),title=options.get('title',name)).build(story); outputs.append(target)
    elif action in ('merge_pdf','extract_pdf'):
        from pypdf import PdfReader, PdfWriter
        writer = PdfWriter()
        if action == 'merge_pdf':
            pages = 0
            for item in request.get('sources',[]):
                reader = PdfReader(item); pages += len(reader.pages)
                if pages > 1000: raise ValueError('Merged PDF exceeds 1,000 pages')
                writer.append(reader)
        else:
            if not source: raise ValueError('extract_pdf needs a source')
            reader = PdfReader(source)
            for page in options['pages']:
                if not 0 <= int(page) < len(reader.pages): raise ValueError('Page index is out of bounds')
                writer.add_page(reader.pages[int(page)])
        target = destination('.pdf'); writer.write(target); writer.close(); outputs.append(target)
    elif action == 'render_pdf':
        import pymupdf as fitz
        if not source: raise ValueError('render_pdf needs a source')
        pdf = fitz.open(source); pages = options.get('pages',list(range(min(len(pdf),8))))
        if len(pages) > 20: raise ValueError('Render at most 20 pages per call')
        scale = max(36,min(int(options.get('dpi',120)),200))/72
        for index in pages:
            if not 0 <= int(index) < len(pdf): raise ValueError('Page index is out of bounds')
            page = pdf[int(index)]
            if page.rect.width*page.rect.height*scale*scale > 20000000: raise ValueError('Rendered page would exceed 20 megapixels')
            target = directory / f'{name}-page-{int(index)+1}.png'; page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).save(target); outputs.append(target)
        result['pages'] = len(pdf); pdf.close()
    elif action == 'fill_pdf':
        from pypdf import PdfReader, PdfWriter
        reader=PdfReader(source);available=reader.get_fields() or {}
        values=options.get('fields',{})
        if not isinstance(values,dict) or not 1<=len(values)<=1000: raise ValueError('Supply 1–1,000 named PDF fields')
        if values.keys()-available.keys(): raise ValueError('Unknown PDF form fields: '+', '.join(sorted(values.keys()-available.keys())))
        acro=reader.trailer['/Root'].get('/AcroForm')
        if acro and '/XFA' in acro.get_object(): raise ValueError('XFA forms require a compatible live PDF editor')
        for key,value in values.items():
            if available[key].get('/FT') not in ('/Tx','/Ch'): raise ValueError('Only text and choice fields are supported; signatures and button fields require a live editor')
            if not isinstance(value,str) or len(value)>32000: raise ValueError('PDF field values must be bounded text')
        writer=PdfWriter();writer.append(reader)
        for page in writer.pages:
            if page.get('/Annots'): writer.update_page_form_field_values(page,values,auto_regenerate=False)
        target=destination('.pdf');writer.write(target);outputs.append(target)
        observed=PdfReader(target).get_fields() or {}
        if any(str(observed.get(key,{}).get('/V',''))!=value for key,value in values.items()):
            raise ValueError('PDF form readback did not match requested values')
        result['fields']=values
    elif action == 'ocr_pdf':
        import shutil,subprocess,re,sys,os
        import pymupdf as fitz
        executable=shutil.which('tesseract')
        language=options.get('language','eng')
        if not isinstance(language,str) or not re.fullmatch(r'[a-zA-Z0-9_+]{1,60}',language): raise ValueError('Invalid OCR language identifier')
        tessdata=Path(os.environ.get('TESSDATA_PREFIX') or Path(sys.prefix)/'share'/'tessdata')
        integrated=all((tessdata/(code+'.traineddata')).is_file() for code in language.split('+'))
        if not integrated and not executable: raise ValueError('Run setup_document_ocr for English, or install the requested Tesseract language data locally')
        pdf=fitz.open(source);pages=options.get('pages',list(range(min(len(pdf),20))))
        if not isinstance(pages,list) or len(pages)>20: raise ValueError('OCR at most 20 explicit pages')
        text=[]
        for index in pages:
            if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(pdf): raise ValueError('OCR page index is out of bounds')
            page=pdf[index];scale=2
            if page.rect.width*page.rect.height*scale*scale>20000000: raise ValueError('OCR page exceeds 20 megapixels')
            if integrated:
                tp=page.get_textpage_ocr(language=language,dpi=144,full=True,tessdata=str(tessdata))
                text.append(f'Page {index+1}\n'+page.get_text(textpage=tp))
                continue
            image=directory/f'{name}-ocr-{index+1}.png';page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).save(image)
            command=[executable,str(image),'stdout','-l',language]
            completed=subprocess.run(command,capture_output=True,timeout=60,creationflags=0x08000000 if __import__('os').name=='nt' else 0)
            if completed.returncode: raise ValueError('Local OCR failed: '+completed.stderr.decode(errors='replace')[:1000])
            text.append(f'Page {index+1}\n'+completed.stdout.decode('utf-8',errors='replace'))
            image.unlink()
        pdf.close();target=directory/(name+'.txt');target.write_text('\n\n'.join(text),encoding='utf-8');outputs.append(target);result['pages']=len(pages);result['engine']='pymupdf-tesseract' if integrated else 'tesseract-cli'
    elif action in ('recalculate_sheet','export_office_pdf'):
        import os,shutil,subprocess
        executable=shutil.which('soffice') or shutil.which('libreoffice')
        if not executable and os.name=='nt':
            candidate=Path(os.environ.get('PROGRAMFILES',''))/'LibreOffice/program/soffice.com'
            if candidate.is_file(): executable=str(candidate)
        if not executable: raise ValueError('Install local LibreOffice for calculation and document PDF export')
        if action=='recalculate_sheet' and source.suffix.lower()!='.xlsx': raise ValueError('recalculate_sheet requires XLSX')
        profile=directory/'office-profile';profile.mkdir()
        (profile/'user').mkdir()
        # A separate profile prevents attaching to or changing the user's running editor.
        (profile/'user/registrymodifications.xcu').write_text('<?xml version="1.0" encoding="UTF-8"?><oor:items xmlns:oor="http://openoffice.org/2001/registry"><item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item></oor:items>',encoding='utf-8')
        output=directory/'converted';output.mkdir()
        extension='xlsx:Calc MS Excel 2007 XML' if action=='recalculate_sheet' else 'pdf'
        command=[executable,'-env:UserInstallation='+profile.resolve().as_uri(),'--headless','--nologo','--nodefault','--norestore','--convert-to',extension,'--outdir',str(output),str(source)]
        completed=subprocess.run(command,capture_output=True,timeout=90,creationflags=0x08000000 if os.name=='nt' else 0)
        target=output/(source.stem+('.xlsx' if action=='recalculate_sheet' else '.pdf'))
        if completed.returncode or not target.is_file(): raise ValueError('Local office conversion failed: '+completed.stderr.decode(errors='replace')[:1000])
        outputs.append(target)
        if action=='recalculate_sheet':
            from openpyxl import load_workbook
            formula=load_workbook(target,data_only=False);cached=load_workbook(target,data_only=True)
            result['formula_readback']=[{'sheet':sheet.title,'cell':cell.coordinate,'formula':cell.value,'value':cached[sheet.title][cell.coordinate].value} for sheet in formula for row in sheet for cell in row if cell.data_type=='f'][:1000]
        else:
            import fitz
            with fitz.open(target) as pdf: result['pages']=len(pdf)
    else: raise ValueError('Unknown office file operation')
    result.update(operation=action,outputs=[{'path':str(path),'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in outputs])
    return result


if __name__ == '__main__':
    try:
        result = execute(json.load(__import__('sys').stdin))
        print(json.dumps({'ok':True,'result':result},ensure_ascii=False,default=str))
    except Exception as error:
        print(json.dumps({'ok':False,'error':type(error).__name__ + ': ' + str(error)},ensure_ascii=False))
