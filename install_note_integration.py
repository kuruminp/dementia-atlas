#!/usr/bin/env python3
"""Apply the free-note crosslink integration to an existing dementia-atlas checkout.

Run from the dementia-atlas repository root. Package's scripts/ and
public/articles/article.css must be copied before running this installer.
"""
from pathlib import Path
import sys

ROOT = Path.cwd()
APP = ROOT / 'public' / 'app.js'
SENTINEL = 'DEMENTIA_ATLAS_NATIVE_NOTE_V1'


def replace_once(text, old, new, label):
    if old not in text:
        raise RuntimeError(f'Cannot find expected {label}; stop rather than damage existing site')
    if text.count(old) != 1:
        raise RuntimeError(f'Found ambiguous {label}: {text.count(old)} copies')
    return text.replace(old, new, 1)


def patch_app(content):
    if SENTINEL in content:
        return content
    # Only change article display and exact PMID crosslinks; existing searches remain.
    start_paper = content.index('  function paperCard(row) {')
    start_trial = content.index('  function trialCard(row) {', start_paper)
    part = content[start_paper:start_trial]

    anchor = "    return `\n      <article class=\"record-card\">"
    if anchor not in part:
        raise RuntimeError('Cannot patch paper cards in this app.js version')
    with_links = '''    const linked = dataItems('articles')
      .filter(a => Array.isArray(a.related_pmids)
        && a.related_pmids.some(pmid => String(pmid) === id)
        && /^\\.\\/articles\\/n[a-z0-9]{10,20}\\.html$/i.test(a.local_url || ''))
      .slice(0, 3);
    const noteLinks = linked.length ? `
      <div class="record-note-links"><strong>この論文に言及した日本語記事</strong>
      ${linked.map(a => `<a href="${esc(a.local_url)}">${esc(a.title)} ↗</a>`).join('')}
      </div>` : '';

'''
    part = replace_once(part, anchor, with_links + anchor, 'paper card return')
    part = replace_once(part, '''        </div>
      </article>
    `;''', '''        </div>
        ${noteLinks}
      </article>
    `;''', 'paper card footer')
    content = content[:start_paper] + part + content[start_trial:]

    start_note = content.index('  function noteCard(row, index) {')
    end_note = content.index('  function render() {', start_note)
    replacement = '''  // DEMENTIA_ATLAS_NATIVE_NOTE_V1
  function noteCard(row, index) {
    const source = String(row.url || '');
    if (!/^https:\\/\\/note\\.com\\/merry_lily\\/n\\/n[a-z0-9]+$/i.test(source)) return '';
    if (row.category === '試験対策' || /認知症専門医|専門医試験|試験対策/.test(row.title || '')) return '';
    const hasLocal = /^\\.\\/articles\\/n[a-z0-9]{10,20}\\.html$/i.test(row.local_url || '');
    if (!hasLocal || row.access !== 'free') return '';
    const href = row.local_url;
    const label = '全文を読む';
    const meta = '<span class="tag tag-alt">このサイトで全文公開</span>';
    const linkProps = '';
    return `
      <article class="record-card">
        <div class="record-head">
          <div class="record-tags"><span class="tag">${esc(row.category || '研究解説')}</span>${meta}</div>
          <span class="record-number">解説 ${String(index + 1).padStart(2, '0')}</span>
        </div>
        <h4 class="record-title">${esc(row.title)}</h4>
        <p class="record-desc">${esc(row.description || '')}</p>
        <div class="record-bottom">
          <small>${esc(dateFormat(row.date))} 公開</small>
          <div class="record-links">
            <a href="${esc(href)}" ${linkProps}>${label} ↗</a>
            ${hasLocal ? `<a href="${esc(source)}" target="_blank" rel="noopener noreferrer">元のnote ↗</a>` : ''}
          </div>
        </div>
      </article>
    `;
  }

'''
    content = content[:start_note] + replacement + content[end_note:]
    content = content.replace("sub: '公開済みのnote記事をまとめています．'", "sub: 'merry_lilyが公開した無料記事を，Dementia Atlas内でも全文掲載しています．'")
    content = content.replace("          ['試験対策', '試験対策'],\n", '')
    # Hide paid/unverified links if the original paper workflow refreshes all note links.
    old_data = """  function dataItems(type) {
    return DATA &&
      DATA[type] &&
      Array.isArray(DATA[type].items)
      ? DATA[type].items
      : [];
  }"""
    safe_data = r"""  function dataItems(type) {
    const rows = DATA && DATA[type] && Array.isArray(DATA[type].items)
      ? DATA[type].items : [];
    return type === 'articles' ? rows.filter(row =>
      row.access === 'free' && /^\.\/articles\/n[a-z0-9]{10,20}\.html$/i.test(row.local_url || '')) : rows;
  }"""
    content = replace_once(content, old_data, safe_data, 'free-only article data')
    # Open the exact PubMed record when arriving from a local explanatory article.
    original = "  if (location.hash === '#trials') {"
    deep_link = r"""  const articlePmid = new URLSearchParams(location.search).get('paper');
  if (/^\d{6,10}$/.test(articlePmid || '')) {
    state.tab = 'papers';
    state.search = articlePmid;
    $('search').value = articlePmid;
    updateDictionaries();
    updateDiseaseCounts();
    render();
    $('explore').scrollIntoView({block: 'start'});
  } else if (location.hash === '#trials') {"""
    content = replace_once(content, original, deep_link, 'PubMed deep link')
    return content


def patch_about(source):
    marker = 'merry_lilyが無料公開した研究記事'
    if marker in source:
        return source
    anchor = '<h2>解説記事について</h2>'
    addition = '''<h2>解説記事について</h2>
      <p>merry_lilyが無料公開した研究記事は，執筆者の了承のもとDementia Atlasにも全文を掲載しています．有料記事，認知症専門医試験の対策記事は掲載対象外です．</p>
      <p>論文へのリンクは，記事に記載されたPMID・DOIとの厳密な一致から自動生成しています．掲載論文にないものは原典に直接リンクします．自動照合には限界があるため，出典は原文で確認してください．</p>'''
    return replace_once(source, anchor, addition, 'about article policy')


def patch_privacy(source):
    marker = '<!-- DEMENTIA_ATLAS_PRIVACY_AD_READY_V1 -->'
    if marker in source:
        return source
    start = source.index('      <h2>Cookie・アクセス解析・広告</h2>')
    end = source.index('      <h2>外部サイトへのリンク</h2>', start)
    replacement = '''      <!-- DEMENTIA_ATLAS_PRIVACY_AD_READY_V1 -->
      <h2>Cookie・アクセス解析・広告について</h2>
      <p>本サイトでは，今後Google AdSenseによる広告配信を導入する場合があります．導入した場合，Googleおよび第三者広告配信事業者がCookieや識別子を利用し，広告の配信や効果測定などを行うことがあります．</p>
      <p>Googleが広告配信のために利用する情報については，<a href="https://policies.google.com/technologies/partner-sites?hl=ja" target="_blank" rel="noopener noreferrer">Googleのパートナーサイトでのデータ利用</a>をご覧ください．広告のパーソナライズは<a href="https://myadcenter.google.com/" target="_blank" rel="noopener noreferrer">マイアドセンター</a>で管理できます．</p>
      <p>現在の広告・解析機能の導入状況に応じて本ポリシーを更新し，必要な場合は同意管理を実装します．広告と医学的な編集内容は独立しており，広告掲載は特定の商品・治療を推奨するものではありません．</p>
      <p>記事中に外部サイトが提供する画像やリンクが含まれる場合，その配信元で通信情報が処理される可能性があります．</p>

'''
    return source[:start] + replacement + source[end:]


def patch_styles(source):
    marker = '/* DEMENTIA_ATLAS_NATIVE_NOTE_V1 */'
    if marker in source:
        return source
    return source.rstrip() + '\n\n' + '''/* DEMENTIA_ATLAS_NATIVE_NOTE_V1 */
.record-note-links{margin-top:14px;padding:13px 16px;background:#eef5ed;border:1px solid #d2e3d1;border-radius:9px;display:flex;flex-direction:column;gap:7px;font-size:13px}
.record-note-links strong{color:#265b52;font-weight:700}
.record-note-links a{color:#266f63;text-decoration:underline;text-underline-offset:3px}
'''


def main():
    for p in (APP, ROOT / 'scripts' / 'sync_note_articles.py',
              ROOT / 'public' / 'articles' / 'article.css'):
        if not p.is_file():
            raise SystemExit(f'Missing {p}; copy the package files into repository first.')
    app_old = APP.read_text(encoding='utf-8')
    about = ROOT / 'public' / 'about.html'
    privacy = ROOT / 'public' / 'privacy.html'
    styles = ROOT / 'public' / 'styles.css'
    app_new = patch_app(app_old)
    other = {about: patch_about(about.read_text(encoding='utf-8')),
             privacy: patch_privacy(privacy.read_text(encoding='utf-8')),
             styles: patch_styles(styles.read_text(encoding='utf-8'))}
    # Do not change any file until all patches have been verified.
    APP.write_text(app_new, encoding='utf-8')
    for path, content in other.items():
        path.write_text(content, encoding='utf-8')
    print('Updated app.js, about.html, privacy.html, styles.css')
    print('Now run: python -m unittest discover -s tests -v')
    print('The separate note workflow handles future daily syncs.')


if __name__ == '__main__':
    main()
