"""Deterministic first-pass prioritization of PubMed citations.

This is a discovery filter, not a critical appraisal or evidence grading.
No proprietary JIF data, LLMs, or patient information are required.
"""
import datetime as dt
import re

MAX_PAPERS_PER_DAY = 3
MAX_PAPERS_ON_FIRST_RUN = 100
MAX_DISPLAYED_PAPERS = 100
FRESH_ENTRY_DAYS = 4
MIN_PRIORITY_SCORE = 7

DEMENTIA_TERMS = re.compile(
    r'alzheimer|dementia|mild cognitive impairment|frontotemporal|'
    r'fronto.temporal|\bftld\b|\bftd\b|\bdlb\b|lewy bod|'
    r'vascular cognitive impairment|amyloid.?beta|\bp.tau(181|217|231)\b', re.I)
EXCLUDE_TITLE = re.compile(
    r'\b(?:study protocol|trial protocol|protocol for a|correction|erratum|'
    r'commentary|letter to the editor|retraction notice|case report)\b', re.I)
EXCLUDE_TYPES = {
    'case reports', 'editorial', 'letter', 'comment', 'preprint',
    'retracted publication', 'retraction notice', 'published erratum',
    'clinical trial protocol', 'news', 'conference proceedings',
}
PRIORITY_JOURNALS = {
    # Small tie-break bonus; NOT an impact-factor filter.
    'nature medicine', 'the new england journal of medicine',
    'the lancet neurology', 'jama neurology', 'brain',
    "alzheimer's & dementia", 'annals of neurology', 'nature aging',
    'science translational medicine', 'nature neuroscience',
}


def extract_sample_size(text):
    """A conservative hint; a number in an abstract is not proof of study N."""
    patterns = [
        r'\b[nN]\s*=\s*(\d[\d,]{2,})\b',
        r'\b(\d[\d,]{2,})\s+(?:participants|individuals|patients|subjects|adults)\b',
        r'\b(?:sample|cohort)\s+(?:of|included)\s+(\d[\d,]{2,})\b',
    ]
    values = []
    for pattern in patterns:
        for m in re.finditer(pattern, text or '', re.I):
            n = int(m.group(1).replace(',', ''))
            if 100 <= n <= 5_000_000:
                values.append(n)
    return max(values, default=0)


def assess_paper(title, abstract, pub_types, mesh, journal):
    """Return a metadata-based screening result; never interpret outcomes."""
    t = title or ''
    a = abstract or ''
    m = mesh or ''
    low_types = {str(x).lower().strip() for x in pub_types or []}
    combined = ' '.join([t, a, m]).lower()
    direct = DEMENTIA_TERMS.search(t+' '+m)
    indirect = DEMENTIA_TERMS.search(a) and re.search(
        r'biomarker|tau|amyloid|cognit|neurodegener|pet|mri|therap|trial',t,re.I)
    if not (direct or indirect):
        return None
    if low_types.intersection(EXCLUDE_TYPES) or EXCLUDE_TITLE.search(t):
        return None
    if 'review' in low_types and not (
        {'systematic review', 'meta-analysis', 'network meta-analysis'} & low_types
    ) and not re.search(r'systematic review|meta.analysis',t,re.I):
        return None
    if re.search(r'\b(protocol|scoping review|narrative review)\b', t, re.I):
        return None
    if re.search(r'\b(mouse|mice|murine|rodent|rat model|in vitro only)\b', t, re.I):
        return None
    if re.search(r'\banimals\b',m,re.I) and not re.search(r'\bhumans\b',m,re.I):
        return None

    rct = ('randomized controlled trial' in low_types or 'pragmatic clinical trial' in low_types
           or bool(re.search(r'\brandomi[sz]ed\b.{0,55}\btrial\b|\bphase (ii|iii|iv|2|3|4) trial\b',t,re.I)))
    interventional = rct or bool(
        {'clinical trial', 'clinical trial, phase ii', 'clinical trial, phase iii',
         'controlled clinical trial'} & low_types
        or re.search(r'\bplacebo.controlled (?:trial|study)\b',t,re.I))
    systematic = bool(
        {'systematic review', 'meta-analysis', 'network meta-analysis'} & low_types
        or re.search(r'\bsystematic review\b|\bmeta.analysis\b',t,re.I))
    guideline = bool(
        {'practice guideline', 'guideline', 'consensus statement'} & low_types
        or re.search(r'\b(?:clinical practice guidelines?|consensus recommendations?)\b',t,re.I))
    validation = bool('validation study' in low_types or re.search(
        r'\bexternal(?:ly)? validat|independent validation|validat.{0,25}independent cohort',combined,re.I))
    multicenter = bool('multicenter study' in low_types or re.search(
        r'\bmulti.cent(?:er|re)|\bmultisite\b|\bmulti.site\b',combined,re.I))
    cohort = bool(re.search(
        r'\bcohort\b|\blongitudinal\b|\bprospective\b|population.based|\bregistry.based\b',
        t+' '+a,re.I))
    # Some major human studies do not carry finalized PubMed publication types.
    discovery = bool(re.search(
        r'genome.wide association|single.cell|spatial transcriptom|proteomic|'
        r'genetic risk|molecular mechanism|target engagement',t,re.I))
    independent = bool(re.search(r'\bindependent cohort|external(?:ly)? validat|replicat',combined,re.I))
    n = extract_sample_size(a)
    score = 2 if direct else 1
    signals = []
    design = 'other'
    if guideline:
        score += 8
        design = 'guideline'
        signals.append('guideline')
    elif systematic:
        score += 7
        design = 'systematic'
        signals.append('systematic')
    elif rct:
        score += 8
        design = 'trial'
        signals.append('rct')
    elif interventional:
        score += 6
        design = 'trial'
        signals.append('clinical_trial')
    elif validation:
        score += 5
        design = 'validation'
        signals.append('validation')
    elif cohort:
        score += 3
        design = 'cohort'
        signals.append('cohort')
    elif discovery:
        score += 3
        design = 'discovery'
        signals.append('discovery')
    else:
        return None

    if multicenter:
        score += 2
        signals.append('multicenter')
    if independent:
        score += 2
        signals.append('independent')
    if n >= 1000:
        score += 3
        signals.append('large_sample')
    elif n >= 500:
        score += 1
    if design == 'discovery' and not (multicenter or independent or n >= 1000):
        return None
    # IF intentionally not used. Journal only breaks otherwise equal scores.
    journal_tie = 1 if (journal or '').strip().lower() in PRIORITY_JOURNALS else 0
    if score < MIN_PRIORITY_SCORE:
        return None
    return {
        'research_type': design,
        'selection_signals': signals[:3],
        'priority_score': score,
        'journal_tiebreak': journal_tie,
    }


def _date(d):
    try:
        return dt.date.fromisoformat((d or '')[:10])
    except ValueError:
        return None


def balance_select(candidates, count, *, day):
    """Top evidence indicators with modest topic/disease diversity.

    Diversity never bypasses the minimum metadata threshold.
    """
    day_date = _date(day) or dt.date.today()
    scored = [r for r in candidates if r.get('priority_score', 0) >= MIN_PRIORITY_SCORE]
    ranked = sorted(scored, key=lambda x:(
        -x['priority_score'], -x.get('journal_tiebreak', 0),
        -(int((_date(x.get('pubmed_entry_date')) or day_date).strftime('%Y%m%d'))),
        -int(x['id']) if str(x.get('id','')).isdigit() else 0,
    ))
    chosen = []
    topics = {}
    diseases = {}
    research_types = {}
    used = set()
    while ranked and len(chosen) < count:
        options = []
        for r in ranked:
            if r['id'] in used:
                continue
            topic_count = topics.get(r.get('topic'),0)
            disease_count = diseases.get(r.get('disease'),0)
            type_count = research_types.get(r.get('research_type'),0)
            # Penalize overrepresented topics, but never promote a failing study.
            diversification = 3 * topic_count + 1.5 * disease_count + 0.6 * type_count
            options.append((r['priority_score'] - diversification,
                            r.get('journal_tiebreak',0), r.get('pubmed_entry_date') or '', r))
        if not options:
            break
        options.sort(key=lambda p:(p[0],p[1],p[2]),reverse=True)
        target = options[0][3]
        used.add(target['id'])
        topics[target.get('topic')] = topics.get(target.get('topic'),0)+1
        diseases[target.get('disease')] = diseases.get(target.get('disease'),0)+1
        research_types[target.get('research_type')] = research_types.get(target.get('research_type'),0)+1
        chosen.append(target)
        ranked = [r for r in ranked if r['id'] not in used]
    return chosen


def merge_curated(previous, candidates, *, today, last_fetched_at=None, bootstrap=False):
    """At most 3 additions on normal days; keep a 30-paper display archive."""
    today_date = _date(today) or dt.date.today()
    previous = [dict(p) for p in previous if p.get('id')]
    seen = {p['id'] for p in previous}
    fresh = []
    for p in candidates:
        if p.get('id') in seen or p.get('priority_score',0) < MIN_PRIORITY_SCORE:
            continue
        entered = _date(p.get('pubmed_entry_date')) or _date(p.get('date'))
        if not bootstrap and (not entered or (today_date-entered).days > FRESH_ENTRY_DAYS):
            continue
        if entered and entered > today_date + dt.timedelta(days=1):
            continue
        fresh.append(p)
    quota = MAX_PAPERS_ON_FIRST_RUN if bootstrap else max(0, MAX_PAPERS_PER_DAY - sum(p.get('selected_on') == today for p in previous))
    if bootstrap:
        # Initial import should be more recent than the 120-day search window.
        fresh = [p for p in fresh if not (_date(p.get('pubmed_entry_date')) or _date(p.get('date'))) or
                 (today_date - (_date(p.get('pubmed_entry_date')) or _date(p.get('date')))).days <= 120]
    selected = balance_select(fresh,quota,day=today)
    for p in selected:
        p['selected_on'] = today
    records = selected + previous
    unique = {}
    for p in records:
        if p['id'] not in unique:
            unique[p['id']] = p
    result = sorted(unique.values(),key=lambda x:(x.get('selected_on') or x.get('date') or '',
                                                        x.get('pubmed_entry_date') or '',x['id']),reverse=True)
    return result[:MAX_DISPLAYED_PAPERS],len(selected)
