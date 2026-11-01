#!/usr/bin/env python3
"""Update a static dementia research digest from official APIs.

Uses PubMed E-utilities and ClinicalTrials.gov Data API v2. All fetching is
server-side on the scheduled GitHub workflow. No personal data is involved.
The NCT records are INTERVENTIONAL only. No scraping of jRCT/UMIN.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET
from curate_papers import (assess_paper, merge_curated, MAX_PAPERS_PER_DAY, MAX_DISPLAYED_PAPERS)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'public' / 'data'
NCBI = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
CTG = 'https://clinicaltrials.gov/api/v2/studies'
SOURCES = ('papers', 'trials', 'articles')
USER_AGENT = 'DementiaAtlas/1.0 (research metadata digest; contact: via source website)'
DISEASE_QUERIES = [
    'Alzheimer Disease',
    'Frontotemporal Dementia',
    'Lewy Body Dementia',
    'Mild Cognitive Impairment',
    'Vascular Dementia',
]
TRIAL_STATUSES = ','.join([
    'RECRUITING','NOT_YET_RECRUITING','ENROLLING_BY_INVITATION',
    'ACTIVE_NOT_RECRUITING','COMPLETED',
])


def fetch(url, *, expect='json', timeout=25, attempts=3):
    for attempt in range(attempts):
        try:
            req = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json,application/xml;q=0.9,*/*;q=0.7'})
            with urlopen(req, timeout=timeout) as res:
                payload = res.read()
            return json.loads(payload) if expect == 'json' else payload
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            if attempt == attempts - 1:
                raise RuntimeError(f'Official API unavailable: {type(exc).__name__}: {exc}') from exc
            time.sleep(2 ** attempt)


def squish(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def text(node):
    return squish(''.join(node.itertext())) if node is not None else ''


def pubmed_date(article):
    # E-publication date takes precedence over print month.
    date = article.find('./MedlineCitation/Article/ArticleDate')
    if date is None:
        date = article.find('./MedlineCitation/Article/Journal/JournalIssue/PubDate')
    if date is None:
        return ''
    year = date.findtext('Year') or ''
    month = date.findtext('Month') or ''
    day = date.findtext('Day') or ''
    if not year:
        val = date.findtext('MedlineDate') or ''
        match = re.search(r'\b(19\d{2}|20\d{2})\b', val)
        year = match.group(1) if match else ''
    if month and not month.isdigit():
        try:
            month = str(dt.datetime.strptime(month[:3], '%b').month)
        except ValueError:
            month = ''
    return year + ('-' + month.zfill(2) if year and month else '') + ('-' + day.zfill(2) if year and month and day else '')


def classify_disease(blob):
    s = blob.lower()
    # Avoid mistakenly classifying DLB/FTD records as generic Alzheimer's disease.
    if re.search(r'frontotemporal|fronto.temporal|ftld|\bbvftd\b|primary progressive aphasia', s):
        return 'ftd'
    if re.search(r'lewy bod|dementia with lewy|\bdlb\b', s):
        return 'dlb'
    if re.search(r'vascular dementia|vascular cognitive impairment', s):
        return 'vascular'
    if re.search(r'mild cognitive impairment|\bmci\b', s) and not re.search(r'alzheimer', s):
        return 'mci'
    if re.search(r'alzheimer|amyloid|tauopath', s):
        return 'ad'
    return 'other'


def classify_topic(blob):
    s = blob.lower()
    rules = [
        ('biomarker', r'plasma|blood.based|serum|biomarker|p.tau|neurofilament|cerebrospinal fluid|fluid biomarker'),
        ('imaging', r'pet.mri|neuroimag|magnetic resonance|\bmri\b|\bpet\b|diffusion tensor'),
        ('treatment', r'\btrial\b|\btherapy\b|therapeutic|treatm|lecanemab|donanemab|drug|intervention'),
        ('prevention', r'prevention|diet|lifestyle|exercise|sleep|risk reduction'),
        ('care', r'caregiv|burden|palliative|care home|family care|communication|ethical'),
        ('diagnosis', r'diagnos|detection|screening|criteria|clinical pathway'),
        ('pathology', r'pathology|mechanism|pathophysiology|genetic|genom|microglia'),
    ]
    return next((topic for topic,regex in rules if re.search(regex,s)), 'other')


def parse_pubmed_xml(payload):
    root = ET.fromstring(payload)
    records = []
    for row in root.findall('.//PubmedArticle'):
        pmid = text(row.find('./MedlineCitation/PMID'))
        title = text(row.find('./MedlineCitation/Article/ArticleTitle'))
        if not re.fullmatch(r'\d+',pmid or '') or not title:
            continue
        journal = text(row.find('./MedlineCitation/Article/Journal/Title'))
        if not journal:
            journal = text(row.find('./MedlineCitation/Article/Journal/ISOAbbreviation'))
        types = [text(x) for x in row.findall('./MedlineCitation/Article/PublicationTypeList/PublicationType')]
        # Use abstract/MeSH to classify but never expose or republish abstracts.
        extra = ' '.join(text(x) for x in row.findall('./MedlineCitation/Article/Abstract/AbstractText'))
        mesh = ' '.join(text(x) for x in row.findall('./MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName'))
        blob = title + ' ' + mesh + ' ' + extra
        doi = ''
        for node in row.findall('./PubmedData/ArticleIdList/ArticleId'):
            if node.attrib.get('IdType') == 'doi':
                doi = text(node)
                break
        selection = assess_paper(title,extra,types,mesh,journal)
        hist = row.findall('./PubmedData/History/PubMedPubDate')
        entered = ''
        for stage in ('entrez', 'pubmed'):
            match = next((x for x in hist if x.attrib.get('PubStatus') == stage), None)
            if match is not None:
                y,mo,d = match.findtext('Year'),match.findtext('Month'),match.findtext('Day')
                if y and mo and d:
                    entered = f'{y}-{mo.zfill(2)}-{d.zfill(2)}'
                    break
        record = {
            'id':pmid, 'title':title, 'journal':journal,
            'date':pubmed_date(row), 'pubmed_entry_date':entered,
            'disease':classify_disease(title + ' ' + mesh + ' ' + extra[:500]),
            'topic':classify_topic(title + ' ' + extra[:900]),
            'publication_types':types[:6], 'doi':doi,
            'url':f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/', 'source':'PubMed',
        }
        if selection:
            record.update(selection)
        else:
            record.update({'priority_score':0,'research_type':'other','selection_signals':[]})
        records.append(record)
    return records


def pubmed_esearch(query, limit):
    params = {'db':'pubmed','term':query,'sort':'pub_date','retmax':str(limit),'retmode':'json',
              'reldate':'120','datetype':'edat','tool':'dementia_atlas'}
    if os.getenv('NCBI_EMAIL'):
        params['email'] = os.environ['NCBI_EMAIL']
    response = fetch(NCBI+'esearch.fcgi?'+urlencode(params))
    return response.get('esearchresult',{}).get('idlist',[])


def fetch_pubmed(limit, priority_limit=260):
    # Broad discovery catches studies whose publication types have not yet been indexed.
    query = ('("Alzheimer Disease"[MeSH Terms] OR Alzheimer*[Title/Abstract] '
             'OR dementia[Title/Abstract] OR "mild cognitive impairment"[Title/Abstract] '
             'OR "frontotemporal dementia"[Title/Abstract] OR "Lewy body dementia"[Title/Abstract] '
             'OR "vascular cognitive impairment"[Title/Abstract]) '
             'NOT ("case reports"[Publication Type] OR "preprint"[Publication Type])')
    ids = pubmed_esearch(query,limit)
    if not ids:
        raise RuntimeError('PubMed returned no matching records; retain previous data')
    # Quality indicators in PubMed are not restricted to a fixed set of journals.
    evidence = ('("randomized controlled trial"[Publication Type] OR '
                '"meta-analysis"[Publication Type] OR "systematic review"[Publication Type] OR '
                '"practice guideline"[Publication Type] OR "validation study"[Publication Type] OR '
                '"multicenter study"[Publication Type] OR random*[Title/Abstract] OR '
                '"external validation"[Title/Abstract] OR "longitudinal cohort"[Title/Abstract] OR '
                '"population-based"[Title/Abstract] OR "multicenter"[Title/Abstract])')
    priority_ids = pubmed_esearch(f'({query}) AND {evidence}',priority_limit)
    # Rare diseases get a separate window to avoid being drowned out by AD papers.
    rare = ('("frontotemporal dementia"[Title/Abstract] OR "Lewy body dementia"[Title/Abstract] '
            'OR "dementia with lewy bodies"[Title/Abstract] OR "vascular dementia"[Title/Abstract])')
    rare_ids = pubmed_esearch(rare,100)
    ids = list(dict.fromkeys(ids+priority_ids+rare_ids))
    records = []
    for i in range(0,len(ids),60):
        chunk = ids[i:i+60]
        params = {'db':'pubmed','id':','.join(chunk),'retmode':'xml','tool':'dementia_atlas'}
        if os.getenv('NCBI_EMAIL'):
            params['email'] = os.environ['NCBI_EMAIL']
        xml = fetch(NCBI+'efetch.fcgi?'+urlencode(params),expect='xml')
        records.extend(parse_pubmed_xml(xml))
        if i+60<len(ids):
            time.sleep(0.5)
    byid = {p['id']:p for p in records}
    return [byid[pid] for pid in ids if pid in byid]


def classify_mechanism(title, interventions, types):
    blob = (title + ' ' + ' '.join(interventions)).lower()
    if re.search(r'lecanemab|donanemab|remternetug|gantenerumab|aducanumab|anti.?amyloid|amyloid.?beta|a.?beta antibody',blob):
        return 'amyloid'
    if re.search(r'anti.?tau|tau.target|tau antibody|tau immunotherapy',blob):
        return 'tau'
    if re.search(r'gene therap|antisense|progranulin|c9orf72|gene editing',blob):
        return 'gene'
    if re.search(r'neuroinflam|microglia|anti.inflamm|interleukin',blob):
        return 'inflammation'
    if re.search(r'agitation|psychosis|behavioral symptoms|mood|cognitive impairment|vortioxetine|karxt|ml.007c',blob):
        return 'symptomatic'
    if types and not any(t == 'DRUG' or t == 'BIOLOGICAL' for t in types):
        return 'non_drug'
    return 'other'


def parse_clinical_trial(record):
    p = record.get('protocolSection') or {}
    ident = p.get('identificationModule') or {}
    status = p.get('statusModule') or {}
    design = p.get('designModule') or {}
    cond = p.get('conditionsModule') or {}
    arms = p.get('armsInterventionsModule') or {}
    places = p.get('contactsLocationsModule') or {}
    nct = str(ident.get('nctId') or '')
    if not re.fullmatch(r'NCT\d{8}',nct):
        return None
    if design.get('studyType') != 'INTERVENTIONAL':
        return None
    locations = places.get('locations') or []
    countries = sorted({x.get('country') for x in locations if x.get('country')})
    japan_locations = [x for x in locations if x.get('country') == 'Japan']
    local_statuses = {'RECRUITING','NOT_YET_RECRUITING','ENROLLING_BY_INVITATION'}
    interventions = []
    intervention_types = []
    for x in arms.get('interventions') or []:
        if x.get('type'):
            intervention_types.append(x.get('type'))
        value = x.get('name') or ''
        if value and value.lower() not in {'placebo','placebo comparator'} and value not in interventions:
            interventions.append(value[:90])
    title = squish(ident.get('briefTitle') or ident.get('officialTitle') or '')
    blob = ' '.join([title,*cond.get('conditions',[]),*interventions])
    return {
        'id':nct, 'title':title, 'status':status.get('overallStatus','UNKNOWN'),
        'phases':design.get('phases') or ['NA'],
        'disease':classify_disease(blob), 'topic':classify_topic(title+' '+' '.join(interventions)),
        'interventions':interventions[:4], 'mechanism':classify_mechanism(title,interventions,intervention_types), 'updated':(status.get('studyFirstPostDateStruct') or {}).get('date','') if not status.get('lastUpdatePostDateStruct') else status['lastUpdatePostDateStruct'].get('date',''),
        'has_japan_site':bool(japan_locations),
        'japan_recruiting':any(x.get('status') in local_statuses for x in japan_locations),
        'japan_recruiting_now':any(x.get('status') == 'RECRUITING' for x in japan_locations),
        'countries':countries,
        'url':'https://clinicaltrials.gov/study/'+nct,'source':'ClinicalTrials.gov',
        'study_type':'INTERVENTIONAL',
    }


def fetch_clinical_trials(limit):
    records = {}
    for query in DISEASE_QUERIES:
        params = {'query.cond':query,'pageSize':'100','format':'json',
                  'filter.overallStatus':TRIAL_STATUSES, 'sort':'LastUpdatePostDate:desc'}
        response = fetch(CTG+'?'+urlencode(params))
        for raw in response.get('studies',[]):
            row = parse_clinical_trial(raw)
            if row:
                records[row['id']] = row
        time.sleep(0.45)
    if not records:
        raise RuntimeError('ClinicalTrials.gov returned no interventional records; retain previous data')
    return sorted(records.values(),key=lambda x:(x.get('updated') or '',x['id']),reverse=True)[:limit]


def read_json(name):
    return json.loads((DATA/f'{name}.json').read_text(encoding='utf-8'))


def save_json(name,value):
    (DATA/f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def build_site_data():
    combined = {name:read_json(name) for name in SOURCES}
    script = 'window.DEMENTIA_DATA = '+json.dumps(combined,ensure_ascii=False,separators=(',',':'))+';\n'
    (DATA/'site-data.js').write_text(script,encoding='utf-8')
    return {name:len(combined[name]['items']) for name in SOURCES}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--offline-check',action='store_true',help='Validate current data and rebuild the local JS bundle')
    ap.add_argument('--papers',type=int,default=450)
    ap.add_argument('--trials',type=int,default=200)
    args=ap.parse_args()
    DATA.mkdir(parents=True,exist_ok=True)
    if not args.offline_check:
        now = dt.datetime.now(dt.timezone.utc)
        now_iso = now.isoformat(timespec='seconds')
        today = (now + dt.timedelta(hours=9)).date().isoformat()
        try:
            previous = read_json('papers')
            bootstrap = (previous.get('meta',{}).get('mode') != 'api' or previous.get('meta',{}).get('display_limit',30) < MAX_DISPLAYED_PAPERS)
            candidates = fetch_pubmed(args.papers)
            items, added = merge_curated(
                [] if bootstrap else previous['items'], candidates,
                today=today, bootstrap=bootstrap,
                last_fetched_at=previous.get('meta',{}).get('fetched_at'))
            if not items:
                raise RuntimeError('No qualifying papers found on initial import')
            save_json('papers',{
                'meta':{
                    'mode':'api','fetched_at':now_iso,'verified_at':None,
                    'source':'PubMed','description':'Metadata-based research prioritization; not scientific appraisal.',
                    'selection_method':'metadata_quality_v1',
                    'daily_limit':MAX_PAPERS_PER_DAY,
                    'display_limit':MAX_DISPLAYED_PAPERS,
                    'newly_added':added,
                }, 'items':items})
            print(f'[OK] papers: {len(items)} shown; {added} added today',flush=True)
        except Exception as exc:
            print(f'[WARN] papers: {exc}; keeping previous records',file=sys.stderr,flush=True)
        try:
            trials=fetch_clinical_trials(args.trials)
            save_json('trials',{
                'meta':{'mode':'api','fetched_at':now_iso,'verified_at':None,'source':'ClinicalTrials.gov',
                        'description':'Official trial registration data; mechanical categorization.'},
                'items':trials})
            print(f'[OK] trials: {len(trials)} from official API',flush=True)
        except Exception as exc:
            print(f'[WARN] trials: {exc}; keeping previous records',file=sys.stderr,flush=True)
    lengths=build_site_data()
    for name,length in lengths.items():
        if length<=0:
            raise RuntimeError(f'No data for {name}')
    print('Website data ready:', lengths)

if __name__=='__main__':
    main()
