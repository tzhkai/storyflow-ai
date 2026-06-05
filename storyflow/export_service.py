"""导出 TXT / DOCX / EPUB（纯标准库，无外部依赖）"""
import zipfile
import io
from datetime import datetime
from urllib.parse import quote


def escape_xml(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')


def generate_txt(text, title):
    safe_title = quote(f'{title}.txt')
    return text, 'text/plain;charset=utf-8', safe_title


def generate_docx(text, title):
    paragraphs = text.strip().split('\n')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>''')
        z.writestr('_rels/.rels', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>''')
        z.writestr('word/_rels/document.xml.rels', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>''')
        z.writestr('word/styles.xml', '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:pPr><w:spacing w:line="360" w:lineRule="auto"/></w:pPr>
    <w:rPr><w:sz w:val="24"/><w:rFonts w:eastAsia="SimSun"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:jc w:val="center"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="36"/></w:rPr>
  </w:style>
</w:styles>''')
        xml_parts = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">',
            '<w:body>'
        ]
        xml_parts.append(
            f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t xml:space="preserve">{escape_xml(title)}</w:t></w:r></w:p>')
        xml_parts.append('<w:p><w:r><w:t xml:space="preserve"> </w:t></w:r></w:p>')
        for para in paragraphs:
            para = para.strip()
            if not para:
                xml_parts.append('<w:p><w:r><w:t xml:space="preserve"> </w:t></w:r></w:p>')
            elif para.startswith('## '):
                xml_parts.append(
                    f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t xml:space="preserve">{escape_xml(para[3:])}</w:t></w:r></w:p>')
            elif para.startswith('# '):
                xml_parts.append(
                    f'<w:p><w:pPr><w:pStyle w:val="Title"/></w:pPr><w:r><w:t xml:space="preserve">{escape_xml(para[2:])}</w:t></w:r></w:p>')
            else:
                xml_parts.append(
                    f'<w:p><w:r><w:t xml:space="preserve">{escape_xml(para)}</w:t></w:r></w:p>')
        xml_parts.append('</w:body></w:document>')
        z.writestr('word/document.xml', ''.join(xml_parts))
    buf.seek(0)
    return buf.getvalue(), 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', quote(f'{title}.docx')


def generate_epub(text, title):
    now_str = datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('mimetype', 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', '''<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>''')
        chapters = []
        current_section = ''
        current_content = []
        for line in text.split('\n'):
            if line.startswith('## '):
                if current_section:
                    chapters.append((current_section, '\n'.join(current_content)))
                current_section = line[3:].strip()
                current_content = []
            elif line.startswith('# '):
                if current_section:
                    chapters.append((current_section, '\n'.join(current_content)))
                current_section = line[2:].strip()
                current_content = []
            else:
                current_content.append(line)
        if current_section:
            chapters.append((current_section, '\n'.join(current_content)))
        if not chapters:
            chapters = [('正文', text)]

        chapter_files = []
        for i, (sec_title, sec_content) in enumerate(chapters):
            fn = f'chapter_{i+1:03d}.xhtml'
            chapter_files.append((fn, sec_title))
            html_body = ''.join(
                f'<p>{escape_xml(line)}</p>' if line.strip() else '<p>&nbsp;</p>'
                for line in sec_content.split('\n')
            )
            z.writestr(f'OEBPS/{fn}', f'''<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{escape_xml(sec_title)}</title></head><body><h1>{escape_xml(sec_title)}</h1>{html_body}</body></html>''')

        manifest = '\n'.join(f'<item id="ch{i+1}" href="{fn}" media-type="application/xhtml+xml"/>' for i, (fn, _) in enumerate(chapter_files))
        spine = '\n'.join(f'<itemref idref="ch{i+1}"/>' for i in range(len(chapter_files)))
        z.writestr('OEBPS/content.opf', f'''<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="BookId">
  <metadata>
    <dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">{escape_xml(title)}</dc:title>
    <dc:language xmlns:dc="http://purl.org/dc/elements/1.1/">zh-CN</dc:language>
    <dc:date xmlns:dc="http://purl.org/dc/elements/1.1/">{now_str}</dc:date>
  </metadata>
  <manifest>
    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
{manifest}
  </manifest>
  <spine toc="ncx">
{spine}
  </spine>
</package>''')
        nav_points = '\n'.join(
            f'<navPoint id="nav{i+1}" playOrder="{i+1}"><navLabel><text>{escape_xml(st)}</text></navLabel><content src="{fn}"/></navPoint>'
            for i, (fn, st) in enumerate(chapter_files))
        z.writestr('OEBPS/toc.ncx', f'''<?xml version="1.0" encoding="UTF-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <head><meta name="dtb:uid" content="storyflow-{int(datetime.now().timestamp())}"/></head>
  <docTitle><text>{escape_xml(title)}</text></docTitle>
  <navMap>{nav_points}</navMap>
</ncx>''')
    buf.seek(0)
    return buf.getvalue(), 'application/epub+zip', quote(f'{title}.epub')
