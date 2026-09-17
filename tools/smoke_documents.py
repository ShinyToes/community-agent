"""Generate fictional format fixtures, run real local OCR and optional model extraction."""
from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app
from app.services.imports.parsers import parse_document, _ocr
from PIL import Image, ImageDraw, ImageFont
from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

if __name__ == '__main__':
    app = create_app()
    folder = Path(app.instance_path) / 'document-fixtures'
    folder.mkdir(parents=True, exist_ok=True)
    app.config['DOCUMENT_FOLDER'] = str(folder)
    text_lines = ['student_id daily_score midterm_score final_score', 'S2027001 80 85 90']
    workbook = Workbook()
    workbook.active.append(text_lines[0].split())
    workbook.active.append(['S2027001', 80, 85, 90])
    workbook.save(folder/'grades.xlsx')
    canvas = Image.new('RGB', (1500, 300), 'white')
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.truetype('C:/Windows/Fonts/consola.ttf', 38)
    for index, line in enumerate(text_lines):
        draw.text((30, 35 + 80 * index), line, fill='black', font=font)
    canvas.save(folder/'grades.png')
    canvas.save(folder/'scan.pdf', 'PDF', resolution=120)
    writer = PdfWriter()
    page = writer.add_blank_page(width=650, height=250)
    font_dict = DictionaryObject({NameObject('/Type'):NameObject('/Font'), NameObject('/Subtype'):NameObject('/Type1'), NameObject('/BaseFont'):NameObject('/Courier')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font_dict)})})
    stream = DecodedStreamObject()
    stream.set_data(('BT /F1 12 Tf 20 180 Td ('+text_lines[0]+') Tj 0 -30 Td ('+text_lines[1]+') Tj ET').encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(folder/'text.pdf')
    results = []
    with app.app_context():
        ocr = _ocr(folder/'grades.png')
        results.append({'format':'ocr_local', 'passed':'S2027001' in ocr and '90' in ocr})
        for name in ('grades.xlsx', 'grades.png', 'scan.pdf', 'text.pdf'):
            try:
                rows = parse_document(folder/name, 'grades', {})
                candidate = rows[0]['candidate']
                ok = len(rows) == 1 and candidate.get('student_id') == 'S2027001' and str(candidate.get('final_score')) == '90'
                results.append({'format':name, 'passed':ok, 'rows':len(rows), 'candidate':candidate,
                                'source':rows[0]['source']})
            except Exception as error:
                results.append({'format':name, 'passed':False, 'error':str(error)})
    (folder/'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(results, ensure_ascii=True))
    raise SystemExit(0 if all(r['passed'] for r in results) else 1)
