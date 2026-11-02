import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sync_note_articles import (
    is_public_free, is_excluded, sanitize_body, extract_citations,
    synchronize, normalize_doi, public_url, make_page,
)

KEY = 'nabcdef1234567'
BODY = '<h2>研究の背景</h2><p>' + ('アルツハイマー病の研究結果を慎重に読み解きます．' * 8) + '</p>' + '<p>PMID: 42965691 DOI: 10.1007/s00330-026-13016-2</p>'


def detail(*, price=0, status='published', title='脳画像による認知症研究', body=BODY, **kw):
    return {'key': KEY, 'price': price, 'status': status, 'name': title,
            'body': body, 'separator': None, 'user': {'urlname': 'merry_lily'}, **kw}


class NoteIntegrationTests(unittest.TestCase):
    def test_free_public_passes(self):
        self.assertTrue(is_public_free(detail(), KEY))

    def test_paid_draft_membership_and_uncertain_blocked(self):
        self.assertFalse(is_public_free(detail(price=500), KEY))
        self.assertFalse(is_public_free(detail(price=None), KEY))
        self.assertFalse(is_public_free(detail(status='draft'), KEY))
        self.assertFalse(is_public_free(detail(separator='paragraph-id'), KEY))
        self.assertFalse(is_public_free(detail(pay_body='<p>Paid material</p>'), KEY))
        self.assertFalse(is_public_free(detail(circle_permissions=[12]), KEY))
        self.assertFalse(is_public_free(detail(user={'urlname': 'someone-else'}), KEY))
        self.assertFalse(is_public_free({'price': 0, 'body': BODY, 'status': 'published'}, KEY))

    def test_specialist_articles_excluded(self):
        for title in ('認知症専門医試験の勉強方法', 'レカネマブを専門医試験目線で解説', '専門医対策記事'):
            self.assertTrue(is_excluded({'title': title}))
        self.assertTrue(is_excluded({'title': '一般タイトル', 'category': '試験対策'}))
        self.assertFalse(is_excluded({'title': '血液p-tau217の研究'}))

    def test_only_merry_lily_urls(self):
        self.assertEqual(public_url(f'https://note.com/merry_lily/n/{KEY}'), f'https://note.com/merry_lily/n/{KEY}')
        self.assertIsNone(public_url(f'https://note.com/unrelated/n/{KEY}'))
        self.assertIsNone(public_url(f'https://evil.example/n/{KEY}'))

    def test_html_sanitization(self):
        source = '<h2>安全な見出し</h2><script>bad()</script><p onclick="bad()">本文<a href="javascript:alert(1)">危険</a></p><a href="https://pubmed.ncbi.nlm.nih.gov/42965691/">論文</a><img src="javascript:bad()"><img src="https://assets.st-note.com/x.png" onerror="bad()">'
        result = sanitize_body(source)
        for unwanted in ('<script', 'bad()', 'onclick=', 'javascript:', 'onerror='):
            self.assertNotIn(unwanted, result)
        self.assertIn('安全な見出し', result)
        self.assertIn('https://pubmed.ncbi.nlm.nih.gov/42965691/', result)
        self.assertIn('https://assets.st-note.com/x.png', result)

    def test_pmid_doi_exact_links(self):
        p = {'id': '42965691', 'title': 'Original paper title', 'doi': '10.1007/s00330-026-13016-2'}
        ids, refs = extract_citations(BODY, {normalize_doi(p['doi']): p}, {'42965691': p})
        self.assertEqual(ids, ['42965691'])
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]['title'], 'Original paper title')

    def test_sync_free_only_and_create_local_page(self):
        rows = [
            {'url': f'https://note.com/merry_lily/n/{KEY}', 'title': '脳画像による認知症研究', 'date': '2026-10-01', 'category': '研究の読みもの'},
            {'url': 'https://note.com/merry_lily/n/n1111111111111', 'title': '専門医試験対策', 'category': '試験対策'},
            {'url': 'https://note.com/merry_lily/n/n2222222222222', 'title': '有料の研究', 'price': 500, 'category': '研究の読みもの'},
        ]
        paper = {'id': '42965691', 'title': 'Original paper title', 'doi': '10.1007/s00330-026-13016-2'}
        got, pages, skipped = synchronize(rows, lambda key: detail(), [paper])
        self.assertEqual(len(got), 1)
        self.assertEqual(skipped['excluded'], 1)
        self.assertEqual(skipped['paid_or_unverified'], 1)
        self.assertEqual(got[0]['local_url'], f'./articles/{KEY}.html')
        self.assertEqual(got[0]['related_pmids'], ['42965691'])
        self.assertIn('元の記事をnoteで読む', pages[KEY])
        self.assertIn('Original paper title', pages[KEY])
        self.assertIn('https://pubmed.ncbi.nlm.nih.gov/42965691/', pages[KEY])

    def test_premium_detail_cannot_publish(self):
        rows = [{'url': f'https://note.com/merry_lily/n/{KEY}', 'title': '認知症の最新研究'}]
        got, pages, skipped = synchronize(rows, lambda key: detail(price=1500), [])
        self.assertEqual(got, [])
        self.assertEqual(pages, {})
        self.assertEqual(skipped['paid_or_unverified'], 1)


if __name__ == '__main__':
    unittest.main()
