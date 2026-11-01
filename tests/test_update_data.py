import datetime as dt
import json
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from update_data import parse_pubmed_xml,parse_clinical_trial,classify_disease,classify_topic
from curate_papers import (assess_paper,extract_sample_size,balance_select,merge_curated,
                           MAX_PAPERS_PER_DAY,MAX_DISPLAYED_PAPERS)

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

    def test_balance_and_daily_cap(self):
        rows=[]
        for i in range(20):
            rows.append({'id':str(9000+i),'title':f'Paper {i}', 'priority_score':10+(i%3),
                         'pubmed_entry_date':'2026-11-01','disease':'ad' if i%4 else 'dlb',
                         'topic':'treatment' if i%3 else 'biomarker','research_type':'trial'})
        today='2026-11-01'
        selected,added=merge_curated([],rows,today=today,bootstrap=False)
        self.assertEqual(added,MAX_PAPERS_PER_DAY)
        self.assertEqual(len(selected),MAX_PAPERS_PER_DAY)
        selected_again,added_again=merge_curated(selected,rows,today=today,bootstrap=False)
        self.assertEqual(added_again,3)
        self.assertEqual(len({r['id'] for r in selected_again}),6)
        self.assertTrue(all('selected_on' in r for r in selected_again))
        past=[{'id':str(10000+i),'priority_score':8,'selected_on':'2026-09-01','title':'x'} for i in range(50)]
        archive,added=merge_curated(past,[],today=today,bootstrap=False)
        self.assertEqual(len(archive),MAX_DISPLAYED_PAPERS)

    def test_no_old_papers_promoted_daily(self):
        old={'id':'1','priority_score':100,'pubmed_entry_date':'2026-09-01',
             'date':'2026-09-01','topic':'treatment','disease':'ad'}
        selected,added=merge_curated([], [old],today='2026-11-01',bootstrap=False)
        self.assertEqual(added,0)
        self.assertEqual(selected,[])

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
