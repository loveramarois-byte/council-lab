from __future__ import annotations

import hashlib
import io
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx


MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_FETCH_BYTES = 2 * 1024 * 1024
MAX_EXTRACTED_CHARS = 200_000
ALLOWED_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".pdf", ".docx"}


class _ReadableHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "h4", "blockquote"} and not self.skip:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def clean_text(value: str) -> str:
    value = value.replace("\x00", "")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()[:MAX_EXTRACTED_CHARS]


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def extract_file_text(filename: str, content: bytes) -> tuple[str, str]:
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("单个文件不能超过 10 MB")
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise ValueError("支持 TXT、Markdown、CSV、JSON、PDF 和 DOCX 文件")
    if suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            raise ValueError("暂不支持加密 PDF")
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages[:200])
        media_type = "application/pdf"
    elif suffix == ".docx":
        from docx import Document

        document = Document(io.BytesIO(content))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    else:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("gb18030", errors="replace")
        media_type = "application/json" if suffix == ".json" else "text/plain"
    text = clean_text(text)
    if not text:
        raise ValueError("文件中没有提取到可读文字")
    return text, media_type


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("网页地址必须使用 http 或 https")
    hostname = parsed.hostname.lower().rstrip(".")
    if hostname in {"localhost", "metadata.google.internal"}:
        raise ValueError("网页资料只允许公开互联网地址")
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            records = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"无法解析网页地址：{hostname}") from exc
        addresses = list({ipaddress.ip_address(record[4][0]) for record in records})
    if not addresses:
        raise ValueError(f"无法解析网页地址：{hostname}")
    for address in addresses:
        if (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_unspecified
            or address.is_multicast
            or address.is_reserved
        ):
            raise ValueError("网页资料不能访问本机、内网、云元数据或保留地址")


async def fetch_webpage(url: str) -> tuple[str, str, str]:
    current = url.strip()
    async with httpx.AsyncClient(timeout=15, headers={"User-Agent": "Council-Lab/0.3 (+local evidence import)"}) as client:
        for _ in range(5):
            validate_public_url(current)
            async with client.stream("GET", current, follow_redirects=False) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("网页重定向缺少目标地址")
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get("content-type", "").lower()
                if "text/html" not in content_type and "text/plain" not in content_type:
                    raise ValueError("网页资料目前只支持 HTML 或纯文本")
                chunks: list[bytes] = []
                total = 0
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > MAX_FETCH_BYTES:
                        raise ValueError("网页正文超过 2 MB，未导入")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                body = raw.decode(encoding, errors="replace")
                if "text/html" in content_type:
                    parser = _ReadableHTML()
                    parser.feed(body)
                    text = clean_text("".join(parser.parts))
                    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
                    title = clean_text(title_match.group(1))[:160] if title_match else urlparse(current).hostname or current
                else:
                    text = clean_text(body)
                    title = urlparse(current).hostname or current
                if not text:
                    raise ValueError("网页中没有提取到可读正文")
                return current, title, text
        raise ValueError("网页重定向次数过多")
