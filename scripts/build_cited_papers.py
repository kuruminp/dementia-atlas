#!/usr/bin/env python3
"""Publish PubMed-verified citation pages and reciprocal links for free note essays.

This archive is SEPARATE from the 100 automatically selected recent articles.
Its purpose is to make the papers cited in the user's own essays accessible.
Reference identities are exact PMIDs; no semantic or approximate linking.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PUB = ROOT / 'public'
DATA = PUB / 'data'
ARTICLES = PUB / 'articles'
PAPERS = PUB / 'papers'
SITE = 'https://dementia-atlas.pages.dev'
NCBI = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi'
PAGE_MARKER = '<!-- DEMENTIA_ATLAS_PUBMED_CITATION_PAGE_V1 -->'
HOME_MARKER = '<!-- DEMENTIA_ATLAS_CITED_PAPERS_LINK_V1 -->'
INJECTED_CLASS = 'atlas-paper-inline'


def normalized_pmid(value):
    value = str(value or '').strip()
    return value if re.fullmatch(r'\d{6,10}', value) else None


def escape(value):
    return html.escape(str(value or ''), quote=True)


def text_of(element):
    return ' '.join(''.join(element.itertext()).split()) if element is not None else ''


def parse_pubmed_records(xml_bytes, wanted):
    root = ET.fromstring(xml_bytes)
    records = {}
    for article in root.findall('.//PubmedArticle'):
        pmid = text_of(article.find('./MedlineCitation/PMID'))
        if pmid not in wanted:
            continue
        title = text_of(article.find('./MedlineCitation/Article/ArticleTitle'))
        if not title:
            continue
        journal = text_of(article.find('./MedlineCitation/Article/Journal/Title'))
        publication = article.find('./MedlineCitation/Article/Journal/JournalIssue/PubDate')
        year = publication.findtext('Year') if publication is not None else None
        if not year and publication is not None:
            match = re.search(r'\b(19\d\d|20\d\d)\b', publication.findtext('MedlineDate') or '')
            year = match.group(1) if match else ''
        if not year:
            date = article.find('./MedlineCitation/Article/ArticleDate')
            year = date.findtext('Year') if date is not None else ''
        doi = ''
        for node in article.findall('./PubmedData/ArticleIdList/ArticleId'):
            if node.get('IdType') == 'doi':
                doi = text_of(node)
                break
        records[pmid] = {
            'id': pmid,
            'title': title,
            'journal': journal,
            'year': year or '',
            'doi': doi,
            'pubmed_url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
            'local_url': f'./papers/{pmid}.html',
        }
    return records


def get_pubmed_records(pmids, *, fetcher=None):
    """Get verified metadata from the official PubMed E-utilities API.

    Hard-fail on transport errors, rather than publishing invented metadata.
    Missing or invalid PMIDs are intentionally omitted and logged.
    """
    ordered = sorted(set(pmids), key=int)
    fetcher = fetcher or fetch_url
    results = {}
    for start in range(0, len(ordered), 60):
        portion = ordered[start:start + 60]
        params = {'db': 'pubmed', 'retmode': 'xml', 'id': ','.join(portion), 'tool': 'dementia_atlas'}
        if os.getenv('NCBI_EMAIL'):
            params['email'] = os.environ['NCBI_EMAIL']
        payload = fetcher(NCBI + '?' + urlencode(params))
        parsed = parse_pubmed_records(payload, set(portion))
        results.update(parsed)
        if start + 60 < len(ordered):
            time.sleep(0.45)
    if not results:
        raise RuntimeError('PubMed returned zero verified cited records; preserving existing publication')
    for invalid in sorted(set(ordered) - set(results), key=int):
        print(f'[WARN] PMID {invalid} is not present in verified PubMed responses', file=sys.stderr)
    return results


def fetch_url(url, attempts=3):
    for attempt in range(attempts):
        try:
            req = Request(url, headers={
                'User-Agent': 'DementiaAtlas/1.0 (literature cross-reference)',
                'Accept': 'application/xml,text/xml,*/*',
            })
            with urlopen(req, timeout=40) as response:
                return response.read()
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            if attempt + 1 == attempts:
                raise RuntimeError(f'PubMed metadata request failed: {error}') from error
            time.sleep(2 ** attempt)


def citations_from_notes(articles):
    """Match by exact PMID only. A related topic is not a citation."""
    cited_by = defaultdict(list)
    for article in articles:
        local = str(article.get('local_url') or '')
        if article.get('access') != 'free':
            continue
        if not re.fullmatch(r'\./articles/n[a-z0-9]{10,20}\.html', local, re.I):
            continue
        key = local.split('/')[-1].removesuffix('.html')
        if not (ARTICLES / (key + '.html')).exists():
            continue
        if article.get('category') == '試験対策' or re.search(r'認知症専門医|専門医試験|試験対策', article.get('title') or ''):
            continue
        for pmid in dict.fromkeys(article.get('related_pmids') or []):
            pmid = normalized_pmid(pmid)
            if pmid:
                cited_by[pmid].append(article)
    return cited_by


def paper_html(meta, note_articles):
    pid = meta['id']
    title = escape(meta['title'])
    journal = escape(meta['journal'])
    year = escape(meta['year'])
    doi = escape(meta['doi'])
    url = escape(meta['pubmed_url'])
    article_links = '\n'.join(
        '<li><a href="../articles/' + escape(a['local_url'].split('/')[-1]) + '">' +
        escape(a['title']) + '</a></li>'
        for a in sorted(note_articles, key=lambda a: a.get('date') or '', reverse=True)
    )
    doi_html = ('<p><a target="_blank" rel="noopener noreferrer" href="https://doi.org/' + doi + '">DOI: ' + doi + ' ↗</a></p>') if meta['doi'] else ''
    return f'''<!doctype html>
{PAGE_MARKER}
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}｜参照論文｜Dementia Atlas</title>
<meta name="description" content="{escape(meta['title'][:130])} の書誌情報と，この研究に言及した日本語解説記事．">
<link rel="canonical" href="{SITE}/papers/{pid}.html">
<link rel="stylesheet" href="../styles.css">
<style>
.paper-shell{{max-width:880px;margin:54px auto 88px}}
.paper-shell h1{{font-size:clamp(23px,3.5vw,36px);line-height:1.45;margin:16px 0 22px}}
.paper-shell h2{{font-size:21px;margin-top:42px}}
.paper-shell p,.paper-shell li{{font-size:15px;line-height:1.95}}
.paper-shell a{{color:#256b61;text-underline-offset:3px}}
.paper-shell .muted{{color:#65767a}}
.paper-shell .paper-panel{{border:1px solid #dce7df;padding:24px;border-radius:14px;background:#f8faf7}}
.paper-shell .paper-panel li{{padding:8px 0}}
</style></head>
<body><div class="topline"><div class="page-shell topline-inner"><span class="topline-brand">DEMENTIA ATLAS</span><span>参考論文</span></div></div>
<header class="site-header"><div class="page-shell header-inner"><a href="../index.html" class="brand"><span class="brand-mark">D</span><span class="brand-copy"><strong>Dementia Atlas</strong><small>認知症リサーチ・アトラス</small></span></a><a href="./index.html" class="header-note-link">参考論文一覧 ↗</a></div></header>
<main class="page-shell paper-shell">
<p class="muted"><a href="../index.html">トップ</a> ／ <a href="./index.html">解説記事で引用された論文</a> ／ PMID {pid}</p>
<h1>{title}</h1>
<p class="muted">{journal}{' ／ ' + year if year else ''} ／ PMID {pid}</p>
<p><a href="{url}" target="_blank" rel="noopener noreferrer">PubMedで原文情報を確認 ↗</a></p>
{doi_html}
<section class="paper-panel"><h2>この論文を紹介・引用した日本語記事</h2>
<ul>{article_links}</ul></section>
<p class="muted">このページはmerry_lilyの記事で参照されたPubMed論文を整理したものです．新着論文100件の自動選定とは別の引用文献アーカイブであり，論文の質や治療効果を保証するものではありません．</p>
</main><footer class="site-footer"><div class="page-shell footer-bottom">Dementia Atlas © 2026　<a href="../about.html">このサイトについて</a> ／ <a href="../privacy.html">プライバシーポリシー</a></div></footer>
</body></html>'''


def paper_index_html(metas, cited_by):
    entries = sorted(metas.values(), key=lambda m: (m['year'], m['id']), reverse=True)
    cards = '\n'.join('''<li data-search="'''+escape(m['title']+' '+m['journal']+' '+m['id']).lower()+'''">
<a href="./'''+m['id']+'''.html">'''+escape(m['title'])+'''</a>
<div class="muted">'''+escape(m['journal'])+''' ／ '''+escape(m['year'])+''' ／ PMID '''+m['id']+''' ／ 解説記事 '''+str(len(cited_by[m['id']]))+'''件</div></li>'''
        for m in entries)
    return f'''<!doctype html>
{PAGE_MARKER}
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>解説記事の参考論文｜Dementia Atlas</title>
<meta name="description" content="Dementia Atlasの日本語研究解説で引用されたPubMed論文を探す．">
<link rel="canonical" href="{SITE}/papers/">
<link rel="stylesheet" href="../styles.css"><style>
.papers-main{{margin:46px auto 80px;max-width:980px}}.papers-main h1{{font-size:34px;margin:18px 0}}
.papers-main input{{width:100%;padding:14px 18px;border:1px solid #b5c7bc;border-radius:10px;font-size:16px}}
.papers-main ul{{list-style:none;padding:0}}.papers-main li{{border-bottom:1px solid #e0e7e0;padding:18px 5px}}
.papers-main li a{{font-size:16px;font-weight:650;line-height:1.65;color:#265e55}}
.muted{{color:#6c7d7b;font-size:13px;margin-top:6px}}.papers-main p{{line-height:1.9}}
</style></head><body>
<div class="topline"><div class="page-shell topline-inner"><span class="topline-brand">DEMENTIA ATLAS</span></div></div>
<header class="site-header"><div class="page-shell header-inner"><a class="brand" href="../index.html"><span class="brand-mark">D</span><span class="brand-copy"><strong>Dementia Atlas</strong><small>認知症リサーチ・アトラス</small></span></a><a class="header-note-link" href="../index.html#articles">研究解説に戻る ↗</a></div></header>
<main class="page-shell papers-main"><p><a href="../index.html">トップページ</a> ／ 参考論文</p>
<h1>日本語解説記事の参考論文</h1>
<p>merry_lilyの無料研究記事でPMIDが示された論文のうち，PubMedで存在を確認できた{len(entries)}件を掲載しています．新着論文100件の一覧とは別のアーカイブです．</p>
<label for="paper-search">この参考論文から検索</label>
<input id="paper-search" type="search" placeholder="論文タイトル・雑誌名・PMID" aria-label="参考論文の検索">
<p id="paper-count" class="muted">{len(entries)}件の論文</p>
<ul id="paper-list">{cards}</ul></main>
<script>
const box=document.getElementById('paper-search'), li=[...document.querySelectorAll('#paper-list li')];
box.addEventListener('input',()=>{{const term=box.value.normalize('NFKC').toLowerCase().trim();let shown=0;for(const p of li){{const visible=p.dataset.search.normalize('NFKC').includes(term);p.hidden=!visible;if(visible)shown++;}}document.getElementById('paper-count').textContent=shown+'件の論文';}});
</script>
<footer class="site-footer"><div class="page-shell footer-bottom">Dementia Atlas © 2026　<a href="../about.html">このサイトについて</a></div></footer>
</body></html>'''


def enrich_article_html(content, available_pmids):
    """Add a local PubMed page link beside verified cited PMID links.

    Change only the citation block, never modify the author's article text.
    Idempotent when run repeatedly, and after the note sync regenerates pages.
    """
    split_marker = '<section class="article-references">'
    if split_marker not in content:
        return content
    front, after_marker = content.split(split_marker, 1)
    refs, closing, tail = after_marker.partition('</section>')
    if not closing:
        return content
    refs = re.sub(r'\s*<a class="atlas-paper-inline" href="\.\./papers/\d+\.html">.*?</a>', '', refs, flags=re.S)
    def replace(match):
        pmid = match.group(1)
        if pmid not in available_pmids:
            return match.group(0)
        return match.group(0) + '　<a class="atlas-paper-inline" href="../papers/' + pmid + '.html">Dementia Atlasの論文ページで見る ↗</a>'
    refs = re.sub(r'<a\b[^>]*href="https://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)/"[^>]*>.*?</a>', replace, refs, flags=re.S)
    return front + split_marker + refs + closing + tail


def add_home_archive_link(source):
    if HOME_MARKER in source:
        return source
    target = '<div class="footer-links">'
    if target not in source:
        raise RuntimeError('Cannot locate home footer to add paper archive link')
    source = source.replace(target,
        target + '\n        ' + HOME_MARKER + '\n        <a href="./papers/index.html">解説記事の参考論文</a>', 1)
    search_section = '<div class="source-links">'
    if search_section in source:
        source = source.replace(search_section,
            search_section + '\n            <a href="./papers/index.html">解説記事で引用した論文 ↗</a>', 1)
    return source


def update_sitemap(metas):
    path = PUB / 'sitemap.xml'
    if not path.exists():
        print('[WARN] sitemap.xml missing; skipping', file=sys.stderr)
        return
    try:
        tree = ET.parse(path)
    except ET.ParseError as error:
        print(f'[WARN] invalid sitemap: {error}', file=sys.stderr)
        return
    root = tree.getroot()
    ns = 'http://www.sitemaps.org/schemas/sitemap/0.9'
    if root.tag != '{' + ns + '}urlset':
        print('[WARN] unknown sitemap format; skipping', file=sys.stderr)
        return
    ET.register_namespace('', ns)
    for el in list(root):
        loc = el.find('{' + ns + '}loc')
        if loc is not None and str(loc.text or '').startswith(SITE + '/papers/'):
            root.remove(el)
    urls = [SITE + '/papers/'] + [SITE + '/papers/' + pmid + '.html' for pmid in sorted(metas, key=int)]
    for url in urls:
        elem = ET.SubElement(root, '{' + ns + '}url')
        ET.SubElement(elem, '{' + ns + '}loc').text = url
    if hasattr(ET, 'indent'):
        ET.indent(tree, space='  ')
    tree.write(path, encoding='utf-8', xml_declaration=True)


def main():
    article_path = DATA / 'articles.json'
    if not article_path.is_file():
        raise RuntimeError('articles.json missing')
    articles = json.loads(article_path.read_text(encoding='utf-8')).get('items', [])
    if not articles:
        raise RuntimeError('No local article metadata found')
    cited_by = citations_from_notes(articles)
    if not cited_by:
        raise RuntimeError('No PMID citations present; refusing to replace existing archive')
    metas = get_pubmed_records(cited_by.keys())
    matched_cited_by = {pmid: cited_by[pmid] for pmid in metas}
    PAPERS.mkdir(parents=True, exist_ok=True)
    # Remove only generated paper pages; never touch manually authored pages.
    for prior in PAPERS.glob('*.html'):
        if prior.name == 'index.html' or not normalized_pmid(prior.stem):
            continue
        if PAGE_MARKER in prior.read_text(encoding='utf-8')[:250] and prior.stem not in metas:
            prior.unlink()
    for pmid, meta in metas.items():
        (PAPERS / (pmid + '.html')).write_text(paper_html(meta, cited_by[pmid]), encoding='utf-8')
    (PAPERS / 'index.html').write_text(paper_index_html(metas, matched_cited_by), encoding='utf-8')
    for article in articles:
        local = str(article.get('local_url') or '')
        if article.get('access') != 'free' or not re.fullmatch(r'\./articles/n[a-z0-9]{10,20}\.html', local, re.I):
            continue
        page = ARTICLES / local.split('/')[-1]
        if not page.exists():
            continue
        before = page.read_text(encoding='utf-8')
        after = enrich_article_html(before, set(metas))
        if before != after:
            page.write_text(after, encoding='utf-8')
    home_path = PUB / 'index.html'
    home_path.write_text(add_home_archive_link(home_path.read_text(encoding='utf-8')), encoding='utf-8')
    (DATA / 'cited_papers.json').write_text(json.dumps({
        'meta': {'source': 'PubMed E-utilities', 'role': "references cited in the site's free author-written essays",
                 'last_updated': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
                 'separate_from_new_100': True},
        'items': [{**meta, 'article_keys': [a['key'] for a in cited_by[meta['id']]]} for meta in metas.values()]},
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    update_sitemap(metas)
    print(f'[OK] Verified cited PubMed papers: {len(metas)} out of {len(cited_by)} candidate PMIDs')
    def has_verified_reference(a):
        local = str(a.get('local_url') or '')
        return (a.get('access') == 'free' and
                re.fullmatch(r'\./articles/n[a-z0-9]{10,20}\.html', local, re.I) and
                bool(set(a.get('related_pmids') or []) & set(metas)))
    print(f'[OK] Free article pages with verified internal paper links: {sum(bool(has_verified_reference(a)) for a in articles)} / {len(articles)}')
    print(f'[OK] Bibliographic archive ready: public/papers/index.html')


if __name__ == '__main__':
    main()
