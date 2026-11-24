"""자기소개서 파일에서 글 뽑기 (services/doc_text.py · POST /api/interviews/resume-text)."""

import zipfile
from io import BytesIO

import pytest

from education.services import doc_text


def _zip(files: dict[str, str]) -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in files.items():
            z.writestr(name, body)
    return buf.getvalue()


DOCX = _zip({"word/document.xml": (
    '<w:document><w:body>'
    '<w:p><w:pPr><w:jc w:val="left"/></w:pPr><w:r><w:t>지원 동기</w:t></w:r></w:p>'
    '<w:p><w:r><w:t xml:space="preserve">물류 데이터를 </w:t></w:r><w:r><w:t>분석해 비용을 12% 줄였습니다 &amp; 팀과 공유</w:t></w:r></w:p>'
    '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>표</w:t><w:tab/><w:t>안</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
    '</w:body></w:document>')})

HWPX = _zip({
    "Contents/section1.xml": "<hs:sec><hp:p><hp:run><hp:t>둘째 구역</hp:t></hp:run></hp:p></hs:sec>",
    "Contents/section0.xml": "<hs:sec><hp:p><hp:run><hp:t>성장 과정</hp:t></hp:run></hp:p><hp:p><hp:run><hp:t>동아리 회장</hp:t></hp:run></hp:p></hs:sec>",
})


def test_docx_paragraphs_runs_and_entities():
    text = doc_text.extract("자기소개서.DOCX", DOCX)
    assert text.splitlines() == ["지원 동기", "물류 데이터를 분석해 비용을 12% 줄였습니다 & 팀과 공유", "표\t안"]


def test_hwpx_sections_in_order():
    assert doc_text.extract("a.hwpx", HWPX).splitlines() == ["성장 과정", "동아리 회장", "둘째 구역"]


def _pdf(line: bytes) -> bytes:
    """글 한 줄이 든 가장 작은 PDF"""
    s = b"BT /F1 12 Tf 72 720 Td (" + line + b") Tj ET"
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(s) + s + b"\nendstream", b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offs)
    return out + b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, x)


def test_pdf_text():
    assert doc_text.extract("cv.pdf", _pdf(b"Hello resume")) == "Hello resume"


def test_text_files_utf8_and_cp949():
    assert doc_text.extract("a.txt", "안녕하세요\r\n\r\n\r\n\r\n끝".encode()) == "안녕하세요\n\n끝"
    assert doc_text.extract("a.md", "한글 메모장".encode("cp949")) == "한글 메모장"


@pytest.mark.parametrize(("name", "data", "msg"), [
    ("a.hwp", b"x", ".hwpx 나 PDF"),
    ("a.exe", b"x", "PDF · Word"),
    ("a.txt", b"", "빈 파일"),
    ("a.txt", b"x" * (doc_text.MAX_BYTES + 1), "5MB"),
    ("a.docx", b"not a zip", "손상"),
    ("a.docx", _zip({"other.xml": "<x/>"}), "내용을 찾지"),
    ("a.pdf", b"%PDF-broken", "PDF 를 읽지"),
    ("a.txt", b"   \n\n ", "글자를 찾지"),
], ids=["hwp", "exe", "empty", "too-big", "bad-zip", "no-body", "bad-pdf", "blank"])
def test_rejects_with_reason(name, data, msg):
    with pytest.raises(doc_text.DocTextError, match=msg):
        doc_text.extract(name, data)


def test_endpoint_returns_text_and_errors(client, auth):
    r = client.post("/api/interviews/resume-text", files={"file": ("cv.docx", DOCX)}, headers=auth)
    assert r.status_code == 200 and r.json()["name"] == "cv.docx" and r.json()["text"].startswith("지원 동기")
    bad = client.post("/api/interviews/resume-text", files={"file": ("cv.hwp", b"x")}, headers=auth)
    assert bad.status_code == 422 and ".hwpx" in bad.json()["detail"]
    assert client.post("/api/interviews/resume-text", files={"file": ("cv.txt", b"hi")}).status_code == 401
