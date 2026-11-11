
#!/usr/bin/env python3
"""Update the Dementia Atlas dataset from PubMed and ClinicalTrials.gov.

PubMed entries are cumulative: previously archived PMIDs are never removed.
If ESearch lists a PMID that EFetch cannot return, retry it individually and
remember it for later runs rather than stopping the whole daily update.
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

from curate_papers import assess_paper, merge_curated

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
    'RECRUITING', 'NOT_YET_RECRUITING', 'ENROLLING_BY_INVITATION',
    'ACTIVE_NOT_RECRUITING', 'COMPLETED',
])


def fetch(url, *, expect='json', timeout=25, attempts=3):
    for attempt in range(attempts):
        try:
            req = Request(url, headers={
                'User-Agent': USER_AGENT,
                'Accept': 'application/json,application/xml;q=0.9,*/*;q=0.7',
            })
            with urlopen(req, timeout=timeout) as res:
                payload = res.read()
            return json.loads(payload) if expect == 'json' else payload
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            if attempt == attempts - 1:
                raise RuntimeError(
                    f'Official API unavailable: {type(exc).__name__}: {exc}'
                ) from exc
            time.sleep(2 ** attempt)


def squish(value):
    return re.sub(r'\s+', ' ', value or '').strip()


def text(node):
    return squish(''.join(node.itertext())) if node is not None else ''


def pubmed_date(article):
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
    return (year
            + ('-' + month.zfill(2) if year and month else '')
            + ('-' + day.zfill(2) if year and month and day else ''))


def classify_disease(blob):
    s = blob.lower()
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
    return next((topic for topic, regex in rules if re.search(regex, s)), 'other')


def parse_pubmed_xml(payload):
    root = ET.fromstring(payload)
    records = []
    for row in root.findall('.//PubmedArticle'):
        pmid = text(row.find('./MedlineCitation/PMID'))
        title = text(row.find('./MedlineCitation/Article/ArticleTitle'))
        if not re.fullmatch(r'\d+', pmid or '') or not title:
            continue
        journal = text(row.find('./MedlineCitation/Article/Journal/Title'))
        if not journal:
            journal = text(row.find('./MedlineCitation/Article/Journal/ISOAbbreviation'))
        types = [text(x) for x in row.findall(
            './MedlineCitation/Article/PublicationTypeList/PublicationType'
        )]
        # Abstract and MeSH are used only for classification, not republished.
        extra = ' '.join(text(x) for x in row.findall(
            './MedlineCitation/Article/Abstract/AbstractText'
        ))
        mesh = ' '.join(text(x) for x in row.findall(
            './MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName'
        ))
        doi = ''
        for node in row.findall('./PubmedData/ArticleIdList/ArticleId'):
            if node.attrib.get('IdType') == 'doi':
                doi = text(node)
                break
        selection = assess_paper(title, extra, types, mesh, journal)
        history = row.findall('./PubmedData/History/PubMedPubDate')
        entered = ''
        for stage in ('entrez', 'pubmed'):
            match = next((x for x in history if x.attrib.get('PubStatus') == stage), None)
            if match is not None:
                y, mo, d = match.findtext('Year'), match.findtext('Month'), match.findtext('Day')
                if y and mo and d:
                    entered = f'{y}-{mo.zfill(2)}-{d.zfill(2)}'
                    break
        record = {
            'id': pmid,
            'title': title,
            'journal': journal,
            'date': pubmed_date(row),
            'pubmed_entry_date': entered,
            'disease': classify_disease(title + ' ' + mesh + ' ' + extra[:500]),
            'topic': classify_topic(title + ' ' + extra[:900]),
            'publication_types': types[:6],
            'doi': doi,
            'url': f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/',
            'source': 'PubMed',
        }
        if selection:
            record.update(selection)
        else:
            record.update({
                'priority_score': 0,
                'research_type': 'other',
                'selection_signals': [],
            })
        records.append(record)
    return records


def pubmed_esearch(query, limit, *, lookback_days=14):
    """Retrieve all IDs within the EDAT window, with safe pagination."""
    if not 1 <= limit <= 9999:
        raise ValueError('PubMed ID retrieval limit must be between 1 and 9999')
    ids = []
    total = None
    while total is None or len(ids) < total:
        params = {
            'db': 'pubmed',
            'term': query,
            'sort': 'pub_date',
            'retmax': str(min(500, limit - len(ids))),
            'retstart': str(len(ids)),
            'retmode': 'json',
            'reldate': str(lookback_days),
            'datetype': 'edat',
            'tool': 'dementia_atlas',
        }
        if os.getenv('NCBI_EMAIL'):
            params['email'] = os.environ['NCBI_EMAIL']
        response = fetch(NCBI + 'esearch.fcgi?' + urlencode(params))
        payload = response.get('esearchresult', {})
        if total is None:
            total = int(payload.get('count', 0))
            if total > limit:
                raise RuntimeError(
                    f'PubMed returned {total} matches in the last '
                    f'{lookback_days} days (configured maximum {limit}). '
                    'No archive changes made; increase --papers or shorten the date window.'
                )
        page = payload.get('idlist') or []
        if not page and len(ids) < total:
            raise RuntimeError('PubMed ESearch returned an incomplete ID list')
        ids.extend(page)
        if len(ids) < total:
            time.sleep(0.45)
    if len(ids) != total:
        raise RuntimeError('PubMed ESearch pagination produced an incomplete list')
    return ids


def _efetch_ids(pmids):
    """Fetch and parse one batch of PubMed records."""
    params = {
        'db': 'pubmed',
        'id': ','.join(pmids),
        'retmode': 'xml',
        'tool': 'dementia_atlas',
    }
    if os.getenv('NCBI_EMAIL'):
        params['email'] = os.environ['NCBI_EMAIL']
    payload = fetch(NCBI + 'efetch.fcgi?' + urlencode(params), expect='xml')
    return parse_pubmed_xml(payload)


def fetch_pubmed(limit, lookback_days=14, pending_pmids=()):
    """Return (retrieved_records, missing_pmids_to_retry_later).

    A small incomplete EFetch response should not block all valid records.
    Missing IDs are attempted individually and stored for the next run.
    Large-scale missing results are treated as a pipeline failure.
    """
    query = ('("Alzheimer Disease"[MeSH Terms] OR Alzheimer*[Title/Abstract] '
             'OR dementia[Title/Abstract] OR "mild cognitive impairment"[Title/Abstract] '
             'OR "frontotemporal dementia"[Title/Abstract] OR "Lewy body dementia"[Title/Abstract] '
             'OR "vascular cognitive impairment"[Title/Abstract]) '
             'NOT ("case reports"[Publication Type] OR "preprint"[Publication Type])')
    recent_ids = pubmed_esearch(query, limit, lookback_days=lookback_days)
    if not recent_ids:
        raise RuntimeError('PubMed returned no matching records; retain previous data')

    # Retry IDs that have fallen outside the rolling 14-day search window.
    pending_ids = [
        str(pmid) for pmid in (pending_pmids or [])
        if re.fullmatch(r'\d+', str(pmid))
    ]
    ids = list(dict.fromkeys([*recent_ids, *pending_ids]))
    by_id = {}

    for i in range(0, len(ids), 60):
        chunk = ids[i:i + 60]
        for row in _efetch_ids(chunk):
            if row['id'] in chunk:
                by_id[row['id']] = row
        if i + 60 < len(ids):
            time.sleep(0.45)

    missing = [pmid for pmid in ids if pmid not in by_id]
    for pmid in missing:
        for attempt in range(3):
            try:
                recovered = next(
                    (row for row in _efetch_ids([pmid]) if row['id'] == pmid),
                    None,
                )
                if recovered is not None:
                    by_id[pmid] = recovered
                    break
            except (RuntimeError, ET.ParseError) as exc:
                print(
                    f'[WARN] PMID {pmid}: individual EFetch error: {exc}',
                    file=sys.stderr, flush=True,
                )
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))

    unresolved = [pmid for pmid in ids if pmid not in by_id]
    # Allow a small number of deferred records, not a broadly broken API.
    safety_limit = max(5, len(ids) // 100)
    if len(unresolved) > safety_limit:
        raise RuntimeError(
            f'PubMed EFetch missing {len(unresolved)} of {len(ids)} PMIDs '
            f'(safety limit {safety_limit}); previous data retained'
        )
    if unresolved:
        print(
            f'[WARN] PubMed: {len(unresolved)} unresolved PMID(s), '
            'will retry next run: ' + ', '.join(unresolved),
            file=sys.stderr, flush=True,
        )
    return [by_id[pmid] for pmid in ids if pmid in by_id], unresolved


def classify_mechanism(title, interventions, types):
    blob = (title + ' ' + ' '.join(interventions)).lower()
    if re.search(r'lecanemab|donanemab|remternetug|gantenerumab|aducanumab|anti.?amyloid|amyloid.?beta|a.?beta antibody', blob):
        return 'amyloid'
    if re.search(r'anti.?tau|tau.target|tau antibody|tau immunotherapy', blob):
        return 'tau'
    if re.search(r'gene therap|antisense|progranulin|c9orf72|gene editing', blob):
        return 'gene'
    if re.search(r'neuroinflam|microglia|anti.inflamm|interleukin', blob):
        return 'inflammation'
    if re.search(r'agitation|psychosis|behavioral symptoms|mood|cognitive impairment|vortioxetine|karxt|ml.007c', blob):
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
    if not re.fullmatch(r'NCT\d{8}', nct):
        return None
    if design.get('studyType') != 'INTERVENTIONAL':
        return None
    locations = places.get('locations') or []
    countries = sorted({x.get('country') for x in locations if x.get('country')})
    japan_locations = [x for x in locations if x.get('country') == 'Japan']
    local_statuses = {'RECRUITING', 'NOT_YET_RECRUITING', 'ENROLLING_BY_INVITATION'}
    interventions = []
    intervention_types = []
    for x in arms.get('interventions') or []:
        if x.get('type'):
            intervention_types.append(x.get('type'))
        value = x.get('name') or ''
        if value and value.lower() not in {'placebo', 'placebo comparator'} and value not in interventions:
            interventions.append(value[:90])
    title = squish(ident.get('briefTitle') or ident.get('officialTitle') or '')
    blob = ' '.join([title, *cond.get('conditions', []), *interventions])
    updated = ((status.get('lastUpdatePostDateStruct') or
                status.get('studyFirstPostDateStruct') or {}).get('date', ''))
    return {
        'id': nct,
        'title': title,
        'status': status.get('overallStatus', 'UNKNOWN'),
        'phases': design.get('phases') or ['NA'],
        'disease': classify_disease(blob),
        'topic': classify_topic(title + ' ' + ' '.join(interventions)),
        'interventions': interventions[:4],
        'mechanism': classify_mechanism(title, interventions, intervention_types),
        'updated': updated,
        'has_japan_site': bool(japan_locations),
        'japan_recruiting': any(x.get('status') in local_statuses for x in japan_locations),
        'japan_recruiting_now': any(x.get('status') == 'RECRUITING' for x in japan_locations),
        'countries': countries,
        'url': 'https://clinicaltrials.gov/study/' + nct,
        'source': 'ClinicalTrials.gov',
        'study_type': 'INTERVENTIONAL',
    }


def fetch_clinical_trials(limit):
    records = {}
    for query in DISEASE_QUERIES:
        params = {
            'query.cond': query,
            'pageSize': '100',
            'format': 'json',
            'filter.overallStatus': TRIAL_STATUSES,
            'sort': 'LastUpdatePostDate:desc',
        }
        response = fetch(CTG + '?' + urlencode(params))
        for raw in response.get('studies', []):
            row = parse_clinical_trial(raw)
            if row:
                records[row['id']] = row
        time.sleep(0.45)
    if not records:
        raise RuntimeError(
            'ClinicalTrials.gov returned no interventional records; retain previous data'
        )
    return sorted(
        records.values(), key=lambda x: (x.get('updated') or '', x['id']), reverse=True
    )[:limit]


def read_json(name):
    return json.loads((DATA / f'{name}.json').read_text(encoding='utf-8'))


def save_json(name, value):
    (DATA / f'{name}.json').write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )


def build_site_data():
    combined = {name: read_json(name) for name in SOURCES}
    script = ('window.DEMENTIA_DATA = '
              + json.dumps(combined, ensure_ascii=False, separators=(',', ':'))
              + ';\n')
    (DATA / 'site-data.js').write_text(script, encoding='utf-8')
    return {name: len(combined[name]['items']) for name in SOURCES}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        '--offline-check', action='store_true',
        help='Validate current data and rebuild the local JS bundle',
    )
    ap.add_argument('--papers', type=int, default=9000)
    ap.add_argument('--trials', type=int, default=200)
    args = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)

    if not args.offline_check:
        now = dt.datetime.now(dt.timezone.utc)
        now_iso = now.isoformat(timespec='seconds')
        today = (now + dt.timedelta(hours=9)).date().isoformat()
        try:
            previous = read_json('papers')
            previous_meta = previous.get('meta', {})
            bootstrap = previous_meta.get('mode') != 'api'
            lookback_days = 30 if bootstrap else 14
            candidates, pending = fetch_pubmed(
                args.papers,
                lookback_days=lookback_days,
                pending_pmids=previous_meta.get('pending_pmids', []),
            )
            items, added = merge_curated(
                previous.get('items', []), candidates, today=today, bootstrap=bootstrap
            )
            old_ids = {str(p['id']) for p in previous.get('items', [])}
            new_ids = {str(p['id']) for p in items}
            if not old_ids.issubset(new_ids):
                raise RuntimeError('Existing PMIDs disappeared; previous data retained')
            if not items:
                raise RuntimeError('No qualifying papers found on initial import')

            save_json('papers', {
                'meta': {
                    'mode': 'api',
                    'fetched_at': now_iso,
                    'verified_at': None,
                    'source': 'PubMed',
                    'description': 'Metadata-based research prioritization; not scientific appraisal.',
                    'selection_method': 'metadata_quality_v1',
                    'archive_count':len(items),
                    'lookback_days': lookback_days,
                    'newly_added': added,
                    'pending_pmids': pending,
                },
                'items': items,
            })
            print(
                f'[OK] papers: {len(items)} archived; {added} new records; '
                f'{len(pending)} pending PMID(s)', flush=True,
            )
        except Exception as exc:
            print(
                f'[WARN] papers: {exc}; keeping previous records',
                file=sys.stderr, flush=True,
            )

        try:
            trials = fetch_clinical_trials(args.trials)
            save_json('trials', {
                'meta': {
                    'mode': 'api',
                    'fetched_at': now_iso,
                    'verified_at': None,
                    'source': 'ClinicalTrials.gov',
                    'description': 'Official trial registration data; mechanical categorization.',
                },
                'items': trials,
            })
            print(f'[OK] trials: {len(trials)} from official API', flush=True)
        except Exception as exc:
            print(
                f'[WARN] trials: {exc}; keeping previous records',
                file=sys.stderr, flush=True,
            )

    lengths = build_site_data()
    for name, length in lengths.items():
        if length <= 0:
            raise RuntimeError(f'No data for {name}')
    print('Website data ready:', lengths)


if __name__ == '__main__':
    main()
