import datetime as dt
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from update_data import parse_pubmed_xml,parse_clinical_trial,classify_disease,classify_topic
from curate_papers import assess_paper, extract_sample_size, balance_select, merge_curated

class PipelineTests(unittest.TestCase):
    def test_local_data(self):
        for kind in ('papers','trials','articles'):
            data=json.loads((ROOT/'public'/'data'/f'{kind}.json').read_text(encoding='utf-8'))
            self.assertTrue(data['items'])
        self.assertIn('window.DEMENTIA_DATA = ',(ROOT/'public'/'data'/'site-data.js').read_text(encoding='utf-8'))

    def test_pubmed_xml(self):
        sample=b'''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>99910000</PMID><Article><ArticleTitle>Randomized trial of plasma biomarkers in Alzheimer disease</ArticleTitle><Journal><Title>Imaginary Journal</Title><JournalIssue><PubDate><Year>2026</Year><Month>Oct</Month><Day>15</Day></PubDate></JournalIssue></Journal><PublicationTypeList><PublicationType>Randomized Controlled Trial</PublicationType></PublicationTypeList><Abstract><AbstractText>Patients were randomized to intervention or placebo. A total of 1,200 patients were enrolled.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><History><PubMedPubDate PubStatus="entrez"><Year>2026</Year><Month>10</Month><Day>16</Day></PubMedPubDate></History><ArticleIdList><ArticleId IdType="doi">10.1016/example</ArticleId></ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'''
        records=parse_pubmed_xml(sample)
        self.assertEqual(len(records),1)
        row=records[0]
        self.assertEqual(row['id'],'99910000')
        self.assertEqual(row['date'],'2026-10-15')
        self.assertEqual(row['pubmed_entry_date'],'2026-10-16')
        self.assertEqual(row['research_type'],'trial')
        self.assertGreater(row['priority_score'],7)
        self.assertIn('rct',row['selection_signals'])
        self.assertEqual(row['doi'],'10.1016/example')
        self.assertNotIn('abstract',row)

    def test_screen_out_editorials_protocols_reviews(self):
        self.assertIsNone(assess_paper('Alzheimer randomized trial protocol','', ['Journal Article'],'','Brain'))
        self.assertIsNone(assess_paper('Alzheimer disease overview','', ['Review'],'','Brain'))
        self.assertIsNone(assess_paper('Clinical trial of Alzheimer disease', '', ['Letter'],'','Brain'))
        self.assertIsNone(assess_paper('Discovery in Alzheimer disease mouse model', '', ['Journal Article'],'','Brain'))

    def test_trial_guideline_meta(self):
        self.assertEqual(assess_paper('Randomized clinical trial in Alzheimer disease','', ['Journal Article'],'','Journal X')['research_type'],'trial')
        self.assertEqual(assess_paper('Guidelines for diagnosis of Alzheimer disease','', ['Practice Guideline'],'','Journal X')['research_type'],'guideline')
        self.assertEqual(assess_paper('Systematic review of dementia interventions','', ['Systematic Review'],'','Journal X')['research_type'],'systematic')

    def test_large_cohort_external_validation(self):
        self.assertEqual(extract_sample_size('A prospective cohort of 12,453 participants.'),12453)
        row=assess_paper('Longitudinal Alzheimer disease cohort','Included 1,560 participants and cognitive outcomes.',['Journal Article'],'','Journal X')
        self.assertIsNotNone(row)
        self.assertEqual(row['research_type'],'cohort')
        row=assess_paper('External validation of Alzheimer blood biomarkers','We validated in an independent cohort of 553 patients.',['Journal Article'],'','Journal X')
        self.assertEqual(row['research_type'],'validation')

    def test_append_only_and_idempotent(self):
        rows = []
        for i in range(25):
            rows.append({
                'id': str(9000 + i), 'title': f'Paper {i}',
                'priority_score': 10, 'pubmed_entry_date': '2026-11-01',
                'disease': 'ad', 'topic': 'treatment', 'research_type': 'trial'
            })
        selected, added = merge_curated([], rows, today='2026-11-02')
        self.assertEqual(added, 25)
        self.assertEqual(len(selected), 25)
        selected_again, added_again = merge_curated(
            selected, rows, today='2026-11-02'
        )
        self.assertEqual(added_again, 0)
        self.assertEqual(len({r['id'] for r in selected_again}), 25)
        self.assertTrue(all(r['selected_on'] == '2026-11-02' for r in selected_again))

    def test_more_than_100_and_older_records_survive(self):
        previous = [
            {'id': str(10000 + i), 'title': 'Historical',
             'priority_score': 8, 'pubmed_entry_date': '2025-02-01',
             'selected_on': '2025-02-01'}
            for i in range(125)
        ]
        incoming = [
            {'id': str(20000 + i), 'title': 'New',
             'priority_score': 9, 'pubmed_entry_date': '2026-11-01'}
            for i in range(20)
        ]
        archive, added = merge_curated(previous, incoming, today='2026-11-02')
        self.assertEqual(added, 20)
        self.assertEqual(len(archive), 145)
        self.assertTrue({r['id'] for r in previous}.issubset({r['id'] for r in archive}))

    def test_existing_metadata_updates_without_resetting_selection_date(self):
        previous = [{
            'id': '999', 'title': 'Old title', 'priority_score': 8,
            'selected_on': '2026-10-01', 'date': '2026-10-01'
        }]
        incoming = [{
            'id': '999', 'title': 'Updated title', 'priority_score': 10,
            'pubmed_entry_date': '2026-10-01'
        }]
        archive, added = merge_curated(previous, incoming, today='2026-11-02')
        self.assertEqual((len(archive), added), (1, 0))
        self.assertEqual(archive[0]['title'], 'Updated title')
        self.assertEqual(archive[0]['selected_on'], '2026-10-01')

    def test_low_priority_or_future_records_not_added(self):
        bad = [
            {'id': '1', 'priority_score': 3},
            {'id': '2', 'priority_score': 10, 'pubmed_entry_date': '2026-12-01'},
        ]
        selected, added = merge_curated([], bad, today='2026-11-02')
        self.assertEqual((selected, added), ([], 0))

    def test_pubmed_esearch_pages_and_fails_on_truncation(self):
        from unittest.mock import patch
        from urllib.parse import urlparse, parse_qs
        from update_data import pubmed_esearch
        ids = [str(i + 10000) for i in range(505)]
        calls = []

        def fake_fetch(url, **kwargs):
            params = parse_qs(urlparse(url).query)
            start = int(params['retstart'][0])
            size = int(params['retmax'][0])
            calls.append(start)
            return {'esearchresult': {
                'count': str(len(ids)), 'idlist': ids[start:start + size]
            }}

        with patch('update_data.fetch', side_effect=fake_fetch):
            self.assertEqual(pubmed_esearch('alzheimer', 600), ids)
        self.assertEqual(calls, [0, 500])
        with patch('update_data.fetch', side_effect=fake_fetch):
            with self.assertRaisesRegex(RuntimeError, 'configured maximum'):
                pubmed_esearch('alzheimer', 500)

    def test_schedule(self):
        w=(ROOT/'.github'/'workflows'/'update.yml').read_text(encoding='utf-8')
        self.assertIn("cron: '0 0 * * *'",w)
        self.assertIn("timezone: 'Asia/Tokyo'",w)

    def test_trial_japan(self):
        row={'protocolSection':{
            'identificationModule':{'nctId':'NCT01234567','briefTitle':'Alzheimer treatment trial'},
            'designModule':{'studyType':'INTERVENTIONAL','phases':['PHASE3']},
            'statusModule':{'overallStatus':'RECRUITING','lastUpdatePostDateStruct':{'date':'2026-10-29'}},
            'conditionsModule':{'conditions':['Alzheimer Disease']},
            'contactsLocationsModule':{'locations':[{'country':'Japan','status':'NOT_YET_RECRUITING'},{'country':'United States','status':'RECRUITING'}]},
            'armsInterventionsModule':{'interventions':[{'name':'Lecanemab','type':'DRUG'},{'name':'Placebo','type':'DRUG'}]}}}
        trial=parse_clinical_trial(row)
        self.assertTrue(trial['has_japan_site'])
        self.assertTrue(trial['japan_recruiting'])
        self.assertFalse(trial['japan_recruiting_now'])
        self.assertEqual(trial['updated'],'2026-10-29')
        row['protocolSection']['designModule']['studyType']='OBSERVATIONAL'
        self.assertIsNone(parse_clinical_trial(row))

    def test_classify_priority(self):
        self.assertEqual(classify_disease('Dementia with Lewy bodies and Alzheimer amyloid pathology'),'dlb')
        self.assertEqual(classify_disease('Frontotemporal dementia trial'),'ftd')
        self.assertEqual(classify_topic('caregiver burden'),'care')

if __name__=='__main__': unittest.main()
