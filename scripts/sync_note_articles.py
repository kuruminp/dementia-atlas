#!/usr/bin/env python3
"""Generate local pages for verified public/free merry_lily note essays.

Run AFTER existing 'Update note article links' and before data commit.
Public read-only note endpoints are undocumented and may change. Fail closed:
never publish a note unless its public detail confirms price=0, status=published.
No login credentials, draft endpoints or premium contents are requested.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'public' / 'data'
PUBLIC = ROOT / 'public'
PAGES = PUBLIC / 'articles'
ACCOUNT = 'merry_lily'
SITE_URL = 'https://dementia-atlas.pages.dev'
NOTE_KEY = re.compile(r'^n[a-z0-9]{10,20}$', re.I)
PMID_URL = re.compile(r'(?:https?://)?(?:www\.)?pubmed\.ncbi\.nlm\.nih\.gov/(\d{6,10})(?:/|\b)', re.I)
PMID_TEXT = re.compile(r'\bPMID\s*[:：#]?\s*(\d{6,10})\b', re.I)
DOI_REGEX = re.compile(r'10\.\d{4,9}/[-._;()/:A-Za-z0-9]+', re.I)
EXCLUDE = re.compile(r'認知症専門医|専門医試験|専門医の勉強|専門医対策|試験対策', re.I)
SOURCE_NOTE = re.compile(r'^https://note\.com/merry_lily/n/(n[a-z0-9]{10,20})/?$', re.I)
PER_NOTE_SLEEP = 0.2
GENERATED_MARKER = '<!-- DEMENTIA_ATLAS_GENERATED_FREE_NOTE -->'


def normalize_doi(value: str) -> str:
    return str(value or '').strip().lower().removeprefix('https://doi.org/').rstrip('.,;:!?)]}。．，')


class SafeNoteHTML(HTMLParser):
    """Allowlist sanitizer for *public* note HTML. Never pass through scripts."""
    ALLOWED = {'p', 'h2', 'h3', 'h4', 'strong', 'b', 'em', 'i', 'u', 's', 'a',
               'ul', 'ol', 'li', 'blockquote', 'pre', 'code', 'br', 'hr',
               'figure', 'figcaption', 'img', 'div', 'span',
               'table', 'thead', 'tbody', 'tr', 'th', 'td', 'sup', 'sub'}
    VOID = {'img', 'br', 'hr'}
    DROP_CONTENT = {'script', 'style', 'iframe', 'object', 'embed', 'svg',
                    'form', 'button', 'input', 'template', 'noscript'}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.open_tags: list[str] = []
        self.drop_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if self.drop_depth or tag in self.DROP_CONTENT:
            if tag in self.DROP_CONTENT:
                self.drop_depth += 1
            return
        if tag not in self.ALLOWED:
            return
        attrs = dict(attrs)
        safe: list[tuple[str, str]] = []
        if tag == 'a':
            url = str(attrs.get('href') or '').strip()
            if url.startswith(('https://', 'http://')):
                safe.extend([('href', url), ('target', '_blank'), ('rel', 'noopener noreferrer')])
        if tag == 'img':
            url = str(attrs.get('src') or attrs.get('data-src') or '').strip()
            if not url.startswith('https://'):
                return
            safe.extend([('src', url), ('alt', str(attrs.get('alt') or '')[:250]), ('loading', 'lazy')])
        at = ''.join(f' {k}="{html.escape(v, quote=True)}"' for k, v in safe)
        self.output.append(f'<{tag}{at}>')
        if tag not in self.VOID:
            self.open_tags.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self.drop_depth:
            if tag in self.DROP_CONTENT:
                self.drop_depth -= 1
            return
        if tag in self.ALLOWED and tag in self.open_tags:
            while self.open_tags:
                last = self.open_tags.pop()
                self.output.append(f'</{last}>')
                if last == tag:
                    break

    def handle_data(self, data):
        if not self.drop_depth:
            self.output.append(html.escape(data))

    def get_html(self):
        while self.open_tags:
            self.output.append(f'</{self.open_tags.pop()}>')
        return ''.join(self.output)


def sanitize_body(raw: str) -> str:
    raw = str(raw or '')
    if '<' not in raw or '>' not in raw:
        blocks = [p.strip() for p in re.split(r'\n\s*\n', raw) if p.strip()]
        return '\n'.join('<p>' + html.escape(p).replace('\n', '<br>') + '</p>' for p in blocks)
    parser = SafeNoteHTML()
    parser.feed(raw)
    return parser.get_html()


def public_url(url: str) -> str | None:
    match = SOURCE_NOTE.fullmatch(str(url or '').strip())
    return f'https://note.com/{ACCOUNT}/n/{match.group(1)}' if match else None


def is_excluded(item: dict) -> bool:
    title = str(item.get('title') or item.get('name') or '')
    return bool(EXCLUDE.search(title) or item.get('category') == '試験対策')


def is_public_free(note: dict, key: str) -> bool:
    """Do not publish if ANY required free/public signal is ambiguous."""
    if not isinstance(note, dict):
        return False
    if note.get('status') != 'published':
        return False
    if str(note.get('key') or '') != key:
        return False
    price = note.get('price')
    if isinstance(price, bool) or price is None:
        return False
    if str(price).strip() != '0':
        return False
    if note.get('separator') not in (None, ''):
        return False
    if note.get('pay_body') not in (None, ''):
        return False
    if any(note.get(k) for k in ('is_limited', 'isLimited', 'is_members_only',
                                 'isMembershipOnly', 'circle_permissions')):
        return False
    owner = note.get('user') or note.get('creator') or {}
    if isinstance(owner, dict) and owner.get('urlname') not in (None, ACCOUNT):
        return False
    body = note.get('body')
    if not isinstance(body, str) or len(re.sub(r'<[^>]+>', '', body).strip()) < 80:
        return False
    return True


def fetch_public_listing(max_pages: int = 30) -> list[dict]:
    """Add newly published notes without waiting for the other update workflow.

    This is a public, undocumented endpoint. Failure falls back to prior links.
    """
    collected = {}
    for page in range(1, max_pages + 1):
        url = f'https://note.com/api/v2/creators/{ACCOUNT}/contents?' + urlencode({'kind': 'note', 'page': page})
        req = Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; DementiaAtlas/1.0)',
            'Accept': 'application/json',
        })
        with urlopen(req, timeout=18) as response:
            payload = json.load(response)
        data = payload.get('data') or {}
        rows = data.get('contents') or []
        if not rows:
            break
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get('key') or row.get('noteKey') or '')
            link = public_url(row.get('noteUrl') or f'https://note.com/{ACCOUNT}/n/{key}')
            title = str(row.get('name') or row.get('title') or '').strip()
            if link and title:
                collected[link] = {
                    'url': link, 'title': title,
                    'date': str(row.get('publishAt') or row.get('publish_at') or '')[:10],
                    'price': row.get('price'),
                }
        if data.get('isLastPage') or data.get('is_last_page'):
            break
        time.sleep(PER_NOTE_SLEEP)
    return list(collected.values())


def request_note(key: str, *, attempts: int = 2, sleep=PER_NOTE_SLEEP) -> dict:
    # Public, unauthenticated, read-only endpoint. Never request draft or paid endpoints.
    url = f'https://note.com/api/v3/notes/{key}'
    for n in range(attempts):
        try:
            req = Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; DementiaAtlas/1.0)',
                'Accept': 'application/json',
            })
            with urlopen(req, timeout=18) as response:
                response_data = json.load(response)
            result = response_data.get('data') or {}
            time.sleep(sleep)
            return result
        except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
            if n == attempts - 1:
                raise RuntimeError(f'{key}: {type(exc).__name__}: {exc}') from exc
            time.sleep(1.25)
    return {}


def extract_citations(body: str, papers_by_doi: dict[str, dict], papers_by_id: dict[str, dict]):
    text = html.unescape(body or '')
    pmids = list(dict.fromkeys(PMID_URL.findall(text) + PMID_TEXT.findall(text)))
    dois = [normalize_doi(d) for d in DOI_REGEX.findall(text)]
    dois = list(dict.fromkeys(d for d in dois if d))
    for doi in dois:
        row = papers_by_doi.get(doi)
        if row and row['id'] not in pmids:
            pmids.append(row['id'])
    # Exact full-title references are accepted; thematic/semantic guesses are not.
    plain = re.sub(r'\s+', ' ', re.sub(r'<[^>]*>', ' ', text)).casefold()
    for pmid, paper in papers_by_id.items():
        title = re.sub(r'\s+', ' ', str(paper.get('title') or '')).strip().casefold()
        if len(title) >= 30 and title in plain and pmid not in pmids:
            pmids.append(pmid)
    references = []
    for pmid in pmids[:30]:
        row = papers_by_id.get(pmid)
        references.append({
            'pmid': pmid, 'title': row.get('title') if row else '',
            'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
            'doi': row.get('doi') if row else '',
            'in_catalog': bool(row),
        })
    pmid_dois = {normalize_doi(r.get('doi')) for r in references if r.get('doi')}
    for doi in dois:
        if doi not in pmid_dois and doi not in papers_by_doi:
            references.append({'pmid': '', 'title': '',
                               'url': f'https://doi.org/{doi}', 'doi': doi, 'in_catalog': False})
    return pmids[:30], references[:35]


def make_page(item: dict, body: str, refs: list[dict]) -> str:
    key = item['key']
    title = html.escape(item['title'])
    original = html.escape(item['url'], quote=True)
    description = html.escape(item.get('description') or item['title'], quote=True)
    date = html.escape(item.get('date') or '')
    citation_links = ''
    for ref in refs:
        refurl = html.escape(ref['url'], quote=True)
        reftitle = html.escape(ref.get('title') or ('PMID ' + ref['pmid'] if ref['pmid'] else 'DOI ' + ref['doi']))
        inside = ''
        if ref.get('pmid') and ref.get('in_catalog'):
            pmid = html.escape(ref['pmid'])
            inside = f'　<a href="../index.html?paper={pmid}#papers">サイト内の論文一覧で見る ↗</a>'
        citation_links += f'<li><a target="_blank" rel="noopener noreferrer" href="{refurl}">{reftitle}</a>{inside}</li>' 
    refs_html = (f'<section class="article-references"><h2>記事から参照できる研究</h2>'
                 f'<p class="note-muted">PMID・DOIの記載から機械的に抽出しています．</p>'
                 f'<ol>{citation_links}</ol></section>') if citation_links else ''
    return f'''<!doctype html>
{GENERATED_MARKER}
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}｜Dementia Atlas</title>
<meta name="description" content="{description[:180]}">
<meta property="og:title" content="{title}"><meta property="og:type" content="article">
<link rel="canonical" href="{SITE_URL}/articles/{key}.html">
<link rel="stylesheet" href="../styles.css"><link rel="stylesheet" href="./article.css">
</head><body>
<div class="topline"><div class="page-shell topline-inner"><span class="topline-brand">DEMENTIA ATLAS</span><span>研究解説</span></div></div>
<header class="site-header"><div class="page-shell header-inner"><a class="brand" href="../index.html"><span class="brand-mark">D</span><span class="brand-copy"><strong>Dementia Atlas</strong><small>認知症リサーチ・アトラス</small></span></a><a class="header-note-link" href="../index.html#articles">解説一覧へ ←</a></div></header>
<main class="page-shell article-shell"><nav class="article-breadcrumb"><a href="../index.html">トップ</a> ／ <a href="../index.html#articles">研究解説</a></nav>
<article><header class="article-heading"><p class="article-kicker">医学・研究の解説</p><h1>{title}</h1>
<p class="note-muted">{date} 公開 ／ 執筆：<a href="https://note.com/{ACCOUNT}" target="_blank" rel="noopener noreferrer">merry_lily</a></p></header>
<div class="article-body">{body}</div></article>
{refs_html}
<section class="source-panel"><h2>元の記事</h2><p>この記事は執筆者がnoteで公開した無料記事を，Dementia Atlasにも掲載したものです．</p>
<p><a class="source-button" href="{original}" target="_blank" rel="noopener noreferrer">元の記事をnoteで読む ↗</a></p></section>
<p class="article-disclaimer">研究情報の紹介を目的とした記事です．診療・治療方針の決定には一次資料と担当医の判断をご確認ください．</p>
</main><footer class="site-footer"><div class="page-shell footer-bottom">Dementia Atlas © 2026　<a href="../about.html">サイトについて</a>　<a href="../privacy.html">プライバシーポリシー</a></div></footer>
</body></html>'''


def derive_excerpt(markup: str, original: str) -> str:
    plain = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', ' ', markup))).strip()
    # Existing hand-written descriptions are preferred to generic placeholders.
    old = str(original or '')
    if old and old != 'noteで公開した記事を読む．':
        return old
    return plain[:105] + ('…' if len(plain) > 105 else '')


def synchronize(candidates: list[dict], get_detail, papers: list[dict]):
    papers_by_id = {str(p['id']): p for p in papers if str(p.get('id', '')).isdigit()}
    papers_by_doi = {normalize_doi(p.get('doi')): p for p in papers if p.get('doi')}
    entries, pages, skipped = [], {}, {'excluded': 0, 'paid_or_unverified': 0, 'fetch_error': 0}
    for row in candidates:
        if is_excluded(row):
            skipped['excluded'] += 1
            continue
        source = public_url(row.get('url'))
        if not source:
            continue
        key = source.rstrip('/').split('/')[-1]
        if not NOTE_KEY.fullmatch(key):
            continue
        if row.get('price') not in (None, 0, '0'):
            skipped['paid_or_unverified'] += 1
            continue
        try:
            detail = get_detail(key)
        except Exception as exc:
            print(f'[WARN] public note detail: {exc}', file=sys.stderr, flush=True)
            skipped['fetch_error'] += 1
            continue
        if not is_public_free(detail, key):
            skipped['paid_or_unverified'] += 1
            continue
        title = str(detail.get('name') or row.get('title') or '').strip()
        if is_excluded({'title': title, 'category': row.get('category')}):
            skipped['excluded'] += 1
            continue
        raw = detail['body']
        body = sanitize_body(raw)
        if not body.strip():
            skipped['paid_or_unverified'] += 1
            continue
        pmids, refs = extract_citations(raw, papers_by_doi, papers_by_id)
        date = str(row.get('date') or detail.get('publish_at') or detail.get('publishAt') or '')[:10]
        item = {
            'key': key, 'title': title, 'url': source, 'date': date,
            'category': row.get('category') or '研究の読みもの',
            'description': derive_excerpt(body, row.get('description', '')),
            'tag': 'research', 'local_url': f'./articles/{key}.html',
            'related_pmids': pmids, 'references': refs,
            'source': 'note/merry_lily', 'access': 'free',
        }
        pages[key] = make_page(item, body, refs)
        entries.append(item)
    entries.sort(key=lambda x: (x['date'], x['key']), reverse=True)
    return entries, pages, skipped


def main():
    from update_data import read_json, save_json, build_site_data
    notes = read_json('articles')
    papers = read_json('papers')
    candidates = {public_url(item.get('url')): item for item in notes.get('items', []) if public_url(item.get('url'))}
    try:
        fresh = fetch_public_listing()
        for entry in fresh:
            old = candidates.get(entry['url'], {})
            candidates[entry['url']] = {**old, **entry,
                'description': old.get('description') or 'noteで公開した記事を読む．',
                'category': old.get('category') or '研究の読みもの'}
        print(f'[OK] public note listing: {len(fresh)} entries', flush=True)
    except Exception as exc:
        print(f'[WARN] public note listing unavailable; using prior links: {exc}', file=sys.stderr, flush=True)
    if not candidates:
        raise RuntimeError('No note source links; refusing to overwrite the archive')
    entries, pages, skipped = synchronize(list(candidates.values()), request_note, papers['items'])
    if not entries:
        raise RuntimeError('No confirmed free notes; prior files remain unchanged')
    PAGES.mkdir(parents=True, exist_ok=True)
    for path in PAGES.glob('n*.html'):
        if NOTE_KEY.fullmatch(path.stem) and GENERATED_MARKER in path.read_text(encoding='utf-8')[:200]:
            if path.stem not in pages:
                path.unlink()
    for key, markup in pages.items():
        path = PAGES / (key + '.html')
        if not path.exists() or path.read_text(encoding='utf-8') != markup:
            path.write_text(markup, encoding='utf-8')
    save_json('articles', {'meta': {
        'mode': 'curated', 'source': 'note',
        'description': 'Verified free published note essays copied with author permission',
        'fetched_at': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'policy': 'price=0; published; non-exam; public details only',
    }, 'items': entries})
    counts = build_site_data()
    # Search engines can discover the new native article pages.
    import xml.etree.ElementTree as ET
    urlset = ET.Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
    for path, date in [('',''), ('about.html',''), ('privacy.html','')] + [
        (f'articles/{a["key"]}.html', a.get('date') or '') for a in entries
    ]:
        url = ET.SubElement(urlset, 'url')
        ET.SubElement(url, 'loc').text = SITE_URL + '/' + path
        if date:
            ET.SubElement(url, 'lastmod').text = date
    xml = ET.tostring(urlset, encoding='unicode', xml_declaration=False)
    (PUBLIC / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + xml + '\n', encoding='utf-8')
    robots = PUBLIC / 'robots.txt'
    previous_robots = robots.read_text(encoding='utf-8') if robots.exists() else 'User-agent: *\nAllow: /\n'
    sitemap_line = 'Sitemap: ' + SITE_URL + '/sitemap.xml'
    if sitemap_line not in previous_robots:
        robots.write_text(previous_robots.rstrip() + '\n\n' + sitemap_line + '\n', encoding='utf-8')
    print(f'[OK] local full-text articles: {len(entries)}; excluded: {skipped}', flush=True)
    print(f'[OK] site data: {counts}', flush=True)


if __name__ == '__main__':
    main()
