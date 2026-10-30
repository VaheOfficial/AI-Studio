"""Real document roundtrips in the CPU document environment; no model inference."""
import hashlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('office_file_worker',Path(__file__).resolve().parents[1]/'office_file_worker.py')
worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)


class OfficeFileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='studio-office-files-')
        self.root = Path(self.temporary.name)
        self.sequence = 0

    def tearDown(self): self.temporary.cleanup()

    def run_action(self,action,options=None,**kwargs):
        self.sequence += 1
        return worker.execute({'action':action,'options':options or {},'directory':str(self.root/str(self.sequence)),**kwargs})

    def test_word_exact_replacement_preserves_original_file(self):
        created = self.run_action('create_document',{'blocks':[{'type':'heading','text':'Results'},{'type':'paragraph','text':'The measured count was three.'},{'type':'table','rows':[['Metric','Count'],['A',3]]}]})
        source = created['outputs'][0]['path']; original = Path(source).read_bytes()
        edited = self.run_action('edit_document',{'old':'three','replacement':'four','expected_count':1},source=source)
        read = self.run_action('inspect',source=edited['outputs'][0]['path'])
        self.assertIn('The measured count was four.',read['paragraphs'])
        self.assertEqual(Path(source).read_bytes(),original)
        with self.assertRaises(ValueError): self.run_action('edit_document',{'old':'missing','replacement':'x'},source=source)

    def test_word_cross_run_replacement_retains_unaffected_formatting(self):
        from docx import Document
        doc=Document();paragraph=doc.add_paragraph()
        paragraph.add_run('Before ').bold=True
        paragraph.add_run('old ').italic=True
        paragraph.add_run('passage').underline=True
        paragraph.add_run(' after').bold=True
        source=self.root/'formatted.docx';doc.save(source)
        changed=self.run_action('edit_document',{'old':'old passage','replacement':'new value','expected_count':1},source=str(source))
        observed=Document(changed['outputs'][0]['path']).paragraphs[0]
        self.assertEqual(observed.text,'Before new value after')
        self.assertTrue(observed.runs[0].bold);self.assertTrue(observed.runs[1].italic);self.assertTrue(observed.runs[-1].bold)

    def test_pdf_form_fill_has_readback_and_rejects_unknown_fields(self):
        from reportlab.pdfgen import canvas
        from pypdf import PdfReader
        source=self.root/'form.pdf';c=canvas.Canvas(str(source));c.drawString(30,760,'Name')
        c.acroForm.textfield(name='name',x=30,y=700,width=250,height=25);c.showPage();c.save()
        changed=self.run_action('fill_pdf',{'fields':{'name':'Test recipient'}},source=str(source))
        self.assertEqual(PdfReader(changed['outputs'][0]['path']).get_form_text_fields()['name'],'Test recipient')
        self.assertEqual(PdfReader(source).get_form_text_fields()['name'],'')
        with self.assertRaisesRegex(ValueError,'Unknown'):
            self.run_action('fill_pdf',{'fields':{'absent':'Value'}},source=str(source))

    def test_spreadsheet_sort_chart_formula_and_clear(self):
        from openpyxl import load_workbook
        value = self.run_action('create_sheet',{'sheet':'Results','rows':[['Name','Count','Literal'],['B',2,'=A1'],['A',1,None]]})
        sorted_value = self.run_action('sort_rows',{'sheet':'Results','column':1},source=value['outputs'][0]['path'])
        chart = self.run_action('add_chart',{'sheet':'Results','range':'A1:B3','title':'Counts'},source=sorted_value['outputs'][0]['path'])
        cleared = self.run_action('write_cells',{'sheet':'Results','rows':[[None]],'start_row':3,'start_column':2},source=chart['outputs'][0]['path'])
        book = load_workbook(cleared['outputs'][0]['path'])
        self.assertEqual(book.sheetnames,['Results']); self.assertEqual(book.active['A2'].value,'A')
        self.assertEqual(book.active['C3'].data_type,'s'); self.assertEqual(book.active['C3'].value,'=A1')
        self.assertIsNone(book.active['B3'].value); self.assertEqual(len(book.active._charts),1); book.close()

    def test_scanned_pdf_ocr_reads_pixels_without_text_layer(self):
        import io,sys,os
        import pymupdf
        from PIL import Image,ImageDraw,ImageFont
        tessdata=Path(os.environ.get('TESSDATA_PREFIX') or Path(sys.prefix)/'share'/'tessdata')
        if not (tessdata/'eng.traineddata').is_file(): self.skipTest('English OCR language data is not installed')
        image=Image.new('RGB',(1200,400),'white')
        font_path=Path('C:/Windows/Fonts/arial.ttf')
        font=ImageFont.truetype(str(font_path) if font_path.is_file() else 'DejaVuSans.ttf',48)
        ImageDraw.Draw(image).text((40,100),'Verified inventory total 714',font=font,fill='black')
        pixels=io.BytesIO();image.save(pixels,format='PNG')
        source=self.root/'scanned.pdf';pdf=pymupdf.open();page=pdf.new_page(width=600,height=200)
        page.insert_image(page.rect,stream=pixels.getvalue());pdf.save(source);pdf.close()
        with pymupdf.open(source) as observed: self.assertEqual(observed[0].get_text(),'')
        value=self.run_action('ocr_pdf',source=str(source))
        self.assertEqual(value['engine'],'pymupdf-tesseract')
        self.assertIn('Verified inventory total 714',Path(value['outputs'][0]['path']).read_text(encoding='utf-8'))
        with self.assertRaisesRegex(ValueError,'bounds'): self.run_action('ocr_pdf',{'pages':[1]},source=str(source))

    def test_presentation_notes_and_replacement(self):
        from pptx import Presentation
        created = self.run_action('create_slides',{'slides':[{'title':'Findings','bullets':['Measured outcome'],'notes':'Explain the measurements.'}]})
        edited = self.run_action('replace_slide_text',{'slide':0,'old':'Measured','replacement':'Verified'},source=created['outputs'][0]['path'])
        slides = Presentation(edited['outputs'][0]['path'])
        self.assertIn('Verified outcome',' '.join(shape.text for shape in slides.slides[0].shapes if shape.has_text_frame))
        self.assertIn('Explain the measurements.',slides.slides[0].notes_slide.notes_text_frame.text)

    def test_pdf_text_render_merge_extract_and_asset_bounds(self):
        from PIL import Image
        pdf = self.run_action('create_pdf',{'title':'Results','blocks':[{'type':'heading','text':'Verified results'},{'type':'paragraph','text':'Three checks passed.'}]})
        source = pdf['outputs'][0]['path']
        text = self.run_action('inspect',source=source)
        self.assertIn('Three checks passed.',text['text'][0]['text'])
        rendered = self.run_action('render_pdf',{'pages':[0],'dpi':100},source=source)
        with Image.open(rendered['outputs'][0]['path']) as image: self.assertGreater(image.width,500)
        merged = self.run_action('merge_pdf',sources=[source,source])
        self.assertEqual(self.run_action('inspect',source=merged['outputs'][0]['path'])['pages'],2)
        extracted = self.run_action('extract_pdf',{'pages':[1]},source=merged['outputs'][0]['path'])
        self.assertEqual(self.run_action('inspect',source=extracted['outputs'][0]['path'])['pages'],1)
        with self.assertRaises(ValueError): self.run_action('create_document',{'blocks':[{'type':'image','asset_index':-1}]},assets=[rendered['outputs'][0]['path']])
        self.assertEqual(pdf['outputs'][0]['sha256'],hashlib.sha256(Path(source).read_bytes()).hexdigest())


if __name__ == '__main__': unittest.main()
