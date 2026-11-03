import argparse

import hashlib

from io import BytesIO

import json

import os

from pathlib import Path

import re

import sys

import time

from datetime import datetime, timezone

from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

from bs4 import BeautifulSoup

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent

ROLE = re.compile(r"강사|비전임|겸임|초빙교원|초빙교수|객원|강의교수")

HIRING = re.compile(r"채용|초빙|모집|임용")

EXCLUDE = re.compile(r"합격자|결과\s*발표|채용\s*결과|모집\s*결과|직원|조교|입찰")

def compact(value):
    return re.sub(r"\s+", "", value).lower()

def candidate(title):
    return bool((ROLE.search(title) or re.search(r"(?:교원|교수)\s*(?:\([^)]*\))?\s*(?:신규|공개)?\s*(?:채용|초빙|모집)", title))
                and HIRING.search(title) and not EXCLUDE.search(title))

def classify(title, body, groups, review_general=True):
    if not candidate(title):
        return None
    if not ROLE.search(title) and not ROLE.search(body):
        return None  # Mixed faculty advertisements must actually include lecturer roles.
    text = compact(title + " " + body)
    hits = {group: [word for word in words if compact(word) in text]
            for group, words in groups.items()}
    hits = {group: words for group, words in hits.items() if words}
    if hits:
        return {"category": "관련 키워드 발견", "matches": hits}
    # A named unrelated department is not a general university-wide announcement.
    specific = re.search(r"[가-힣A-Za-z]+(?:학과|학부|전공|대학원|교육원|교육센터|어학원|어학당|병원|사업단|연구소|센터|고등학교)", title)
    if review_general and not specific:
        return {"category": "전공 확인 필요", "matches": {}}
    return None

def with_query(url, **updates):
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({key: str(value) for key, value in updates.items()})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))

def canonical(url):
    parts = urlsplit(url)
    # Keep identifiers; remove only observed list-navigation parameters.
    query = sorted((k, v) for k, v in parse_qsl(parts.query)
                   if k not in {"pagenumber", "page_number", "page", "Page", "PageSize", "pageIndex", "currentPageNo", "article.offset", "articleLimit", "term", "etc1", "notice"})
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))

def parse_list(html, source):
    soup = BeautifulSoup(html, "html.parser")
    items = {}
    if source.get("kind") == "jinhak":
        node = soup.select_one("#__NUXT_DATA__")
        if node is None:
            raise ValueError("진학프로 공개 채용 목록 데이터 없음")
        data = json.loads(node.string or node.get_text())
        records = [x for x in data if isinstance(x, dict) and "recruitIdx" in x]
        if not records:
            raise ValueError("진학프로 채용 목록 0건 또는 구조 변경")
        for record in records:
            role = data[record["recruitTypeCode"]]
            if role not in {"L", "T"}:
                continue
            idx = data[record["recruitIdx"]]
            title = data[record["recruitTitle"]]
            org = data[record["organName"]]
            if not isinstance(idx, int) or not isinstance(title, str) or not isinstance(org, str):
                raise ValueError("진학프로 공고 필드 형식 변경")
            url = f"https://www.jinhakpro.com/recruit/{idx}"
            key = hashlib.sha256(url.encode()).hexdigest()[:24]
            title = f'{"강사" if role == "L" else "비전임교원"} · {org} · {title}'
            items[key] = {"id": key, "title": title, "url": url, "source": source["name"]}
        if not items:
            raise ValueError("진학프로 강사·비전임 목록 0건: 분류 구조 확인 필요")
        return items
    if source.get("kind") == "page":
        node = soup.select_one(source["selector"])
        if node is None or len(node.get_text(strip=True)) < 30:
            raise ValueError("채용 안내 영역을 찾지 못함")
        body = node.get_text(" ", strip=True)
        key = hashlib.sha256(canonical(source["url"]).encode()).hexdigest()[:24]
        return {key: {"id": key, "title": source["title"], "url": source["url"],
                      "source": source["name"], "body": body,
                      "revision": hashlib.sha256(body.encode()).hexdigest()}}
    for a in soup.select(source["selector"]):
        title_node = a.select_one(source["title_selector"]) if source.get("title_selector") else a
        if title_node is None:
            continue
        title_node = BeautifulSoup(str(title_node), "html.parser")
        for badge in title_node.select(source.get("strip_selector", ".newArtcl, .b-status")):
            badge.decompose()
        title = re.sub(r"\s+", " ", title_node.get_text(" ", strip=True))
        if source["kind"] == "dongduk":
            match = re.search(r"fn_goView\('([0-9]+)'", a.get("onclick", ""))
            if not match:
                continue
            url = with_query(source["url"], schM="view", id=match.group(1))
        elif source.get("link_regex"):
            match = re.search(source["link_regex"], a.get(source.get("link_attribute", "href"), ""))
            if not match:
                continue
            url = source["detail_template"].format(*match.groups())
        else:
            href = a.get("href", "")
            if not re.search(source.get("href_pattern", "."), href):
                continue
            url = urljoin(source["url"], href)
        if not title or urlsplit(url).scheme not in {"http", "https"}:
            continue
        url = canonical(url)
        if source.get("canonical_pattern"):
            match = re.search(source["canonical_pattern"], url)
            if not match:
                continue
            url = source["canonical_template"].format(*match.groups())
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        items[key] = {"id": key, "title": title, "url": url, "source": source["name"]}
    if not items:
        raise ValueError("게시글 0개: 게시판 구조 변경 또는 접근 오류 확인 필요")
    return items

class Fetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Mozilla/5.0 (compatible; LecturerWatch/1.0; personal public recruitment monitor)"
        self.session.headers["Accept"] = "text/html"
        self.last_request = 0

    def get(self, url):
        time.sleep(max(0, 1 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        response = self.session.get(url, timeout=(10, 30))
        response.raise_for_status()
        if "text/html" not in response.headers.get("Content-Type", ""):
            raise ValueError("HTML 게시판 응답이 아님")
        # Legacy Korean boards still use EUC-KR; prefer the document's declared encoding.
        encoding = re.search(br'charset\s*=\s*["\x27]?([\w-]+)', response.content[:10000], re.I)
        response.encoding = encoding.group(1).decode("ascii") if encoding else "utf-8"
        try:
            response.content.decode(response.encoding, errors="strict")
        except (UnicodeDecodeError, LookupError):
            response.encoding = response.apparent_encoding
        return response.text

    def pdf_text(self, url):
        time.sleep(max(0, 1 - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        with self.session.get(url, timeout=(10, 30), stream=True) as response:
            response.raise_for_status()
            data = bytearray()
            for chunk in response.iter_content(65536):
                data.extend(chunk)
                if len(data) > 12 * 1024 * 1024:
                    raise ValueError("공고 PDF 크기 제한 초과")
        reader = PdfReader(BytesIO(data))
        if len(reader.pages) > 60:
            raise ValueError("공고 PDF 페이지 제한 초과")
        return "\n".join(page.extract_text() or "" for page in reader.pages)

def load_list(fetcher, source):
    items = {}
    page_ids = set()
    for page in range(1, source.get("pages", 1) + 1):
        if source.get("page_template"):
            url = source["url"] if page == 1 else source["page_template"].format(page=page)
        elif source.get("page_param"):
            url = with_query(source["url"], **{source["page_param"]: page})
        else:
            url = source["url"]
        found = parse_list(fetcher.get(url), source)
        signature = tuple(sorted(found))
        if signature in page_ids:
            raise ValueError("페이지 이동 실패: 같은 목록이 반복됨")
        page_ids.add(signature)
        items.update(found)
    return items

def detail(fetcher, item, source):
    if "body" in item:
        return item["body"]
    soup = BeautifulSoup(fetcher.get(item["url"]), "html.parser")
    node = soup.select_one(source["body_selector"])
    if node is None:
        raise ValueError("본문 영역을 찾지 못함")
    pdf_text = ""
    if source.get("embedded_pdf"):
        urls = set(re.findall(r"https://attachment\.hibrain\.io/[^'\"<>\n]+\.pdf", str(node)))
        for url in sorted(urls):
            extracted = fetcher.pdf_text(url)
            if len(compact(extracted)) < 20:
                raise ValueError("이미지 PDF: 전공 텍스트 추출 불가")
            pdf_text += "\n" + extracted
    for tag in node.select("script, style"):
        tag.decompose()
    has_media = bool(node.select("img, a[href]"))
    for tag in node.select("img[alt]"):
        if not tag.contents:
            tag.replace_with(tag["alt"])
    text = node.get_text(" ", strip=True) + pdf_text
    if len(text) < 20:
        if source.get("image_notice") and has_media:
            return "이미지 또는 첨부파일 공고: 원문에서 모집 전공 확인 필요"
        raise ValueError("본문이 비어 있거나 지나치게 짧음")
    return text

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

def scan(config, state, fetcher, preview=False):
    report = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "sources": [], "items": [], "errors": []}
    for source in config["sources"]:
        sid = source["id"]
        try:
            items = load_list(fetcher, source)
            first = sid not in state["sources"]
            old = state["sources"].get(sid, {})
            new = dict(old)
            for key, item in items.items():
                revision = item.get("revision", item["title"])
                if not preview and first:
                    new[key] = revision
                    continue
                if not preview and old.get(key) == revision:
                    continue
                if candidate(item["title"]):
                    try:
                        body = detail(fetcher, item, source)
                        result = classify(item["title"], body, config["groups"],
                                          source.get("review_general", False))
                    except Exception as exc:
                        report["errors"].append(f'{source["name"]}: {item["url"]}: {type(exc).__name__}')
                        continue  # Keep unseen so next run retries failed detail fetches.
                    if result:
                        item.update(result)
                        report["items"].append(item)
                        if not preview:
                            event_id = key + hashlib.sha256(revision.encode()).hexdigest()[:12]
                            state["pending"][event_id] = item
                new[key] = revision
            if not preview:
                state["sources"][sid] = new
            report["sources"].append({"name": source["name"], "count": len(items),
                                       "baseline": first and not preview})
        except Exception as exc:
            report["errors"].append(f'{source["name"]}: {type(exc).__name__}: {str(exc)[:180]}')
    return report
