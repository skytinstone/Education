"""올린 문서에서 글만 뽑기 — AI 면접 자기소개서 '내 컴퓨터에서 불러오기'.

PDF · Word(.docx) · 한글(.hwpx) · 텍스트(.txt · .md)를 받는다. 파일은 어디에도 저장하지 않고 글만 돌려준다.
.docx · .hwpx 는 zip 안의 XML 이라 XML 파서 없이 정규식으로 문단과 글자만 꺼낸다 (외부 엔티티 같은 위험이 없다).
"""

from __future__ import annotations

import html
import re
import zipfile
from io import BytesIO
from pathlib import PurePath

from pypdf import PdfReader

MAX_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 30
MAX_XML_BYTES = 20 * 1024 * 1024  # zip 안에서 풀린 크기 (압축 폭탄 막기)
MAX_CHARS = 20000
EXTS = (".pdf", ".docx", ".hwpx", ".txt", ".md")


class DocTextError(ValueError):
    """사용자에게 그대로 보여 줄 수 있는 이유"""


def _xml_text(xml: str, para: str, run: str) -> str:
    """문단(para) 마다 한 줄, 그 안의 글자 조각(run)을 이어 붙인다"""
    lines = []
    for p in re.findall(rf"<{para}[\s>].*?</{para}>", xml, flags=re.S):
        p = re.sub(r"<w:tab/>|<hp:tab[^>]*/>", "\t", p)
        p = re.sub(r"<w:br[^>]*/>|<hp:lineBreak[^>]*/>", "\n", p)
        parts = re.findall(rf"<{run}(?:\s[^>]*)?>(.*?)</{run}>|(\t|\n)", p, flags=re.S)
        lines.append("".join(html.unescape(t) or ws for t, ws in parts))
    return "\n".join(lines)


def _zip_xml(data: bytes, pattern: str) -> list[str]:
    try:
        z = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as e:
        raise DocTextError("파일이 손상됐거나 형식이 맞지 않아요") from e
    names = sorted((n for n in z.namelist() if re.fullmatch(pattern, n)), key=lambda n: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", n)])
    if not names:
        raise DocTextError("문서 내용을 찾지 못했어요")
    if sum(z.getinfo(n).file_size for n in names) > MAX_XML_BYTES:
        raise DocTextError("문서가 너무 커요")
    return [z.read(n).decode("utf-8", "replace") for n in names]


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def extract(filename: str, data: bytes) -> str:
    """파일 이름의 확장자로 형식을 정하고 글을 뽑는다. 읽을 수 없으면 DocTextError"""
    ext = PurePath(filename or "").suffix.lower()
    if ext == ".hwp":
        raise DocTextError("한글(.hwp) 파일은 바로 읽을 수 없어요. 한글에서 '다른 이름으로 저장'으로 .hwpx 나 PDF 로 저장해 올려 주세요")
    if ext not in EXTS:
        raise DocTextError("PDF · Word(.docx) · 한글(.hwpx) · 텍스트(.txt) 파일을 올려 주세요")
    if not data:
        raise DocTextError("빈 파일이에요")
    if len(data) > MAX_BYTES:
        raise DocTextError("5MB 이하 파일만 올릴 수 있어요")
    if ext == ".pdf":
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise DocTextError("암호가 걸린 PDF 는 읽을 수 없어요")
            pages = reader.pages[:MAX_PDF_PAGES]
            text = "\n\n".join((p.extract_text() or "").strip() for p in pages)
        except DocTextError:
            raise
        except Exception as e:  # pypdf 는 깨진 파일에 여러 종류의 예외를 낸다
            raise DocTextError("PDF 를 읽지 못했어요. 파일이 손상됐는지 확인해 주세요") from e
    elif ext == ".docx":
        text = "\n".join(_xml_text(x, "w:p", "w:t") for x in _zip_xml(data, r"word/document\.xml"))
    elif ext == ".hwpx":
        text = "\n".join(_xml_text(x, "hp:p", "hp:t") for x in _zip_xml(data, r"Contents/section\d+\.xml"))
    else:
        text = _decode(data)
    text = re.sub(r"[ \t ]+\n", "\n", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise DocTextError("글자를 찾지 못했어요. 스캔한 이미지 PDF 라면 글을 복사해 붙여 넣어 주세요")
    return text[:MAX_CHARS]
