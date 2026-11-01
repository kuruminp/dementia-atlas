(() => {
  'use strict';

  const DATA = window.DEMENTIA_DATA || null;
  const DISEASES = {all:'すべて',ad:'アルツハイマー病',mci:'軽度認知障害',dlb:'レビー小体型認知症',ftd:'前頭側頭葉変性症',vascular:'血管性・その他',other:'その他'};
  const TOPICS = {treatment:'治療',biomarker:'バイオマーカー',imaging:'画像',diagnosis:'診断',prevention:'予防',care:'ケア・生活',pathology:'病態',other:'その他'};
  const STATUS = {
    RECRUITING:['募集中','recruiting'],NOT_YET_RECRUITING:['募集開始前','pending'],
    ENROLLING_BY_INVITATION:['招待者のみ','pending'],ACTIVE_NOT_RECRUITING:['実施中・募集終了','closed'],
    COMPLETED:['終了','closed'],SUSPENDED:['一時中断','closed'],TERMINATED:['中止','closed'],
    WITHDRAWN:['撤回','closed'], UNKNOWN:['確認が必要','closed']
  };
  const MECHANISMS = {amyloid:'抗Aβ',tau:'抗タウ',symptomatic:'認知・行動症状',inflammation:'炎症・免疫',gene:'遺伝子・核酸',non_drug:'非薬物・機器',other:'その他'};
  const RESEARCH_TYPES = {
    all:'\u3059\u3079\u3066',trial:'\u81e8\u5e8a\u8a66\u9a13',
    guideline:'\u8a3a\u7642\u6307\u91dd',systematic:'\u7cfb\u7d71\u7684\u30ec\u30d3\u30e5\u30fc\u30fb\u30e1\u30bf\u89e3\u6790',
    validation:'\u5916\u90e8\u691c\u8a3c\u30fb\u591a\u65bd\u8a2d',cohort:'\u30b3\u30db\u30fc\u30c8',
    discovery:'\u57fa\u790e\u30fb\u63a2\u7d22',other:'\u305d\u306e\u4ed6'
  };
  const REASONS = {
    rct:'\u30e9\u30f3\u30c0\u30e0\u5316\u6bd4\u8f03\u8a66\u9a13',
    clinical_trial:'\u81e8\u5e8a\u8a66\u9a13',
    guideline:'\u8a3a\u7642\u6307\u91dd',
    systematic:'\u7cfb\u7d71\u7684\u30ec\u30d3\u30e5\u30fc\u30fb\u30e1\u30bf\u89e3\u6790',
    validation:'\u5916\u90e8\u691c\u8a3c',
    multicenter:'\u591a\u65bd\u8a2d\u7814\u7a76',
    independent:'\u72ec\u7acb\u30b3\u30db\u30fc\u30c8\u3067\u691c\u8a3c',
    large_sample:'\u5927\u898f\u6a21\u30b5\u30f3\u30d7\u30eb',
    cohort:'\u7e26\u65ad\u30fb\u30b3\u30db\u30fc\u30c8',
    discovery:'\u63a2\u7d22\u7684\u7814\u7a76'
  };
  const TITLES = {
    papers:{label:'CURATED RESEARCH',title:'\u6ce8\u76ee\u306e\u65b0\u7740\u8ad6\u6587',sub:'PubMed\u306e\u8ad6\u6587\u304b\u3089\u7814\u7a76\u30c7\u30b6\u30a4\u30f3\u30fb\u898f\u6a21\u30fb\u95a2\u9023\u6027\u3067\u81ea\u52d5\u9078\u5b9a\uff0e1\u65e5\u6700\u59273\u4ef6\uff0c\u76f4\u8fd130\u4ef6\u307e\u3067\uff0e',source:'PubMed / metadata-based screening'},
    trials:{label:'CLINICAL TRIAL TRACKER',title:'臨床試験・治験',sub:'介入試験の登録状況を疾患・Phase・実施地域から探せます．',source:'ClinicalTrials.gov'},
    articles:{label:'EDITORIAL & GUIDES',title:'解説・note',sub:'公開済みの学習記事や研究の読みものをまとめています．',source:'note / merry_lily'}
  };
  const $ = (id) => document.getElementById(id);
  const q = (s) => document.querySelector(s);
  const qa = (s) => [...document.querySelectorAll(s)];
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g,(x)=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[x]));
  const dateFormat = (value) => {
    const m = String(value||'').match(/^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?/);
    if (!m) return '日付未登録';
    return `${m[1]}年${m[2] ? `${Number(m[2])}月` : ''}${m[3] ? `${Number(m[3])}日` : ''}`;
  };
  const fetchTime = (value) => value ? dateFormat(value.slice(0,10)) : '初期サンプル';
  const topicName = (x) => TOPICS[x] || TOPICS.other;
  const diseaseName = (x) => DISEASES[x] || DISEASES.other;
  const matchesDisease = (x,selected) => selected === 'all' || (selected === 'vascular' ? !['ad','mci','dlb','ftd'].includes(x.disease) : x.disease === selected);
  const normalize = (s) => String(s||'').normalize('NFKC').toLocaleLowerCase();
  const state = {tab:'papers', disease:'all',topic:'all',research_type:'all',status:'all',phase:'all',mechanism:'all',japan:false,search:'',sort:'recent',visible:8};
  let filtered = [];

  function dataItems(type) {
    return (DATA && DATA[type] && Array.isArray(DATA[type].items)) ? DATA[type].items : [];
  }
  function syncCounts() {
    ['papers','trials','articles'].forEach(type => { $('tab-count-'+type).textContent = dataItems(type).length.toLocaleString('ja-JP'); });
    $('stat-papers').textContent = dataItems('papers').length.toLocaleString('ja-JP');
    $('stat-trials').textContent = dataItems('trials').length.toLocaleString('ja-JP');
    $('stat-japan').textContent = dataItems('trials').filter(r => r.has_japan_site === true).length.toLocaleString('ja-JP');
    const p = DATA.papers?.meta, t = DATA.trials?.meta;
    const api = p?.mode === 'api' && t?.mode === 'api';
    $('data-mode').textContent = api ? '公式APIデータ' : '初期サンプルを表示中';
    $('data-mode').classList.toggle('sample', !api);
    const ds = [p?.fetched_at,t?.fetched_at].filter(Boolean).sort();
    $('data-updated').textContent = api ? `毎日0時（日本時間）に更新予約 ／ 最終取得 ${fetchTime(ds[0])}` : '毎日0時更新は公開・設定後に有効化';
    updateDiseaseCounts();
  }
  function updateDiseaseCounts() {
    const items = dataItems(state.tab==='articles'?'papers':state.tab);
    ['all','ad','mci','dlb','ftd','vascular'].forEach(d => {
      const el = $('disease-count-'+d);
      if (el) el.textContent = `${items.filter(x=>matchesDisease(x,d)).length} 件`;
    });
  }
  function updateDictionaries() {
    const notes = state.tab === 'articles';
    q('#disease-select').closest('.filter-block').hidden = notes;
    $('topic-filter').hidden = false;
    $('studytype-filter').hidden = state.tab !== 'papers';
    $('research-type-select').value = state.research_type;
    $('status-filter').hidden = state.tab !== 'trials';
    $('phase-filter').hidden = state.tab !== 'trials';
    $('mechanism-filter').hidden = state.tab !== 'trials';
    $('japan-filter').hidden = state.tab !== 'trials';
    $('trial-advisory').hidden = state.tab !== 'trials';
    const opts = notes
      ? [['all','すべてのカテゴリ'],['試験対策','試験対策'],['研究の読みもの','研究の読みもの'],['バイオマーカー','バイオマーカー'],['診療・生活','診療・生活'],['治療','治療'],['予防・生活','予防・生活']]
      : [['all','すべてのテーマ'],['treatment','治療・治験'],['biomarker','バイオマーカー'],['imaging','脳画像'],['diagnosis','診断・評価'],['prevention','予防・生活習慣'],['care','ケア・社会'],['pathology','病態・基礎'],['other','その他']];
    $('topic-select').innerHTML = opts.map(([v,label])=>`<option value="${esc(v)}">${esc(label)}</option>`).join('');
    $('topic-select').value = state.topic;
    $('disease-select').value = state.disease;
    $('status-select').value = state.status;
    $('phase-select').value = state.phase;
    $('mechanism-select').value = state.mechanism;
    $('japan-only').checked = state.japan;
    const t=TITLES[state.tab];
    $('results-kicker').textContent=t.label;
    $('results-title').textContent=t.title;
    $('results-subtitle').textContent=t.sub;
    $('source-footnote').textContent=`Source: ${t.source}`;
    $('search').placeholder=state.tab==='papers' ? '論文タイトル・PMID・雑誌名で検索' : state.tab==='trials' ? '試験名・薬剤・NCT番号で検索' : '記事タイトル・テーマで検索';
    const m = DATA[state.tab]?.meta;
    $('last-updated-detail').textContent=m?.mode==='api' ? `API取得：${fetchTime(m.fetched_at)}` : m?.mode==='curated' ? '公開済みの記事のみ掲載' : '初期サンプル：2026年11月1日時点';
    qa('.tab-button').forEach(el=>{const on=el.dataset.tab===state.tab;el.classList.toggle('active',on);el.setAttribute('aria-selected',String(on));});
    qa('.nav-link').forEach(el=>el.classList.toggle('active',el.dataset.nav===state.tab));
    qa('.disease-card').forEach(el=>el.classList.toggle('selected',el.dataset.disease===state.disease));
  }
  function chooseTab(tab, scroll=true) {
    if (!TITLES[tab]) return;
    const was = state.tab;
    state.tab=tab;
    state.visible=8;
    state.topic='all';state.status='all';state.phase='all';state.mechanism='all';state.japan=false;
    state.disease='all';
    $('sort-select').value=state.sort;
    // Search terms are not silently carried across unrelated data collections.
    if (was!==tab) { state.search=''; $('search').value=''; }
    updateDictionaries();updateDiseaseCounts();render();
    if(scroll) $('explore').scrollIntoView({behavior:'smooth',block:'start'});
    const mobile=$('mobile-menu'); mobile.hidden=true;
    $('mobile-menu-button').setAttribute('aria-expanded','false');
  }
  function filterRecords() {
    let records=dataItems(state.tab).slice();
    if(state.tab!=='articles'){
      records=records.filter(row=>matchesDisease(row,state.disease));
      if(state.topic!=='all') records=records.filter(row=>row.topic===state.topic);
    }else if(state.topic!=='all'){
      records=records.filter(row=>row.category===state.topic);
    }
    if(state.tab==='papers' && state.research_type!=='all') records=records.filter(row=>row.research_type===state.research_type);
    if(state.tab==='trials'){
      if(state.status!=='all') records=records.filter(row=>row.status===state.status);
      if(state.phase!=='all') records=records.filter(row=>(row.phases||[]).includes(state.phase));
      if(state.mechanism!=='all') records=records.filter(row=>row.mechanism===state.mechanism);
      if(state.japan) records=records.filter(row=>row.has_japan_site===true);
    }
    if(state.search.trim()) {
      const tokens=normalize(state.search).split(/\s+/).filter(Boolean);
      records=records.filter(row=>{
        const joined=normalize([row.title,row.id,row.journal,row.category,row.description, ...(row.interventions||[]),row.status, row.disease, row.topic].join(' '));
        return tokens.every(token=>joined.includes(token));
      });
    }
    if(state.sort==='title') records.sort((a,b)=>a.title.localeCompare(b.title,'ja'));
    else records.sort((a,b)=>{
      const aDate=(state.tab==='papers'?a.selected_on:null)||a.date||a.updated||'';const bDate=(state.tab==='papers'?b.selected_on:null)||b.date||b.updated||'';
      return (state.sort==='recent' ? bDate.localeCompare(aDate) : aDate.localeCompare(bDate)) || String(a.id||'').localeCompare(String(b.id||''));
    });
    return records;
  }
  function paperCard(row,index) {
    const id=String(row.id||''); if(!/^\d+$/.test(id)) return '';
    const tags=`<span class="tag">${esc(diseaseName(row.disease))}</span><span class="tag tag-alt">${esc(topicName(row.topic))}</span>`;
    const kind=DATA.papers?.meta?.mode==='api' ? (RESEARCH_TYPES[row.research_type]||RESEARCH_TYPES.other) : '\u521d\u671f\u30b5\u30f3\u30d7\u30eb';
    const signals=(row.selection_signals||[]).slice(0,2).map(v=>REASONS[v]).filter(Boolean);
    const reason=signals.length ? signals.join(' / ') : '\u81ea\u52d5\u9078\u5b9a\u524d\u306e\u521d\u671f\u30b5\u30f3\u30d7\u30eb';
    return `<article class="record-card"><div class="record-head"><div class="record-tags"><span class="tag tag-impact">${esc(kind)}</span>${tags}</div><span class="record-number">PMID ${esc(id)}</span></div><h4 class="record-title">${esc(row.title)}</h4><p class="record-meta"><span>${esc(row.journal||'')}</span><span class="meta-sep">\u2022</span><span>${esc(dateFormat(row.date))}</span></p><p class="record-desc">\u9078\u5b9a\u306e\u624b\u304c\u304b\u308a\uff1a${esc(reason)}\uff08\u6a5f\u68b0\u5224\u5b9a\uff09</p><div class="record-bottom"><small>PubMed \uff0f \u63b2\u8f09\u306f\u7814\u7a76\u306e\u8cea\u3092\u4fdd\u8a3c\u3057\u307e\u305b\u3093</small><a href="https://pubmed.ncbi.nlm.nih.gov/${id}/" target="_blank" rel="noopener noreferrer" aria-label="PMID ${id} PubMed">PubMed \u3067\u8aad\u3080 \u2197</a></div></article>`;
  }
  function trialCard(row) {
    const id=String(row.id||'');if(!/^NCT\d{8}$/.test(id))return '';
    const [status,statusStyle]=STATUS[row.status]||STATUS.UNKNOWN;
    const phase=(row.phases||[]).map(x => x==='NA' ? 'Phase 該当なし' : x.replace('PHASE','Phase ')).join(' / ');
    const mech=MECHANISMS[row.mechanism] || MECHANISMS.other;
    const jp=row.has_japan_site===true ? `<span class="trial-japan">🇯🇵 ${row.japan_recruiting_now===true?'日本の施設で募集中':'日本に実施施設あり'}</span>` : row.has_japan_site===null ? '<span class="trial-japan unknown">実施国は公式記録で確認</span>' : '';
    const intr=(row.interventions||[]).slice(0,3).join(' / ');
    return `<article class="record-card"><div class="record-head"><div class="record-tags"><span class="tag tag-status ${esc(statusStyle)}">${esc(status)}</span><span class="tag">${esc(diseaseName(row.disease))}</span><span class="tag tag-alt">${esc(phase)}</span><span class="tag tag-neutral">${esc(mech)}</span></div><span class="record-number">${esc(id)}</span></div><h4 class="record-title">${esc(row.title)}</h4><p class="record-meta"><span>${esc(intr || '介入内容は公式記録参照')}</span><span class="meta-sep">•</span><span>登録情報の最終更新 ${esc(dateFormat(row.updated))}</span></p><div class="record-bottom"><div class="record-pillbox">${jp}<small>ClinicalTrials.gov 登録情報</small></div><a href="https://clinicaltrials.gov/study/${id}" target="_blank" rel="noopener noreferrer" aria-label="${id} の公式登録情報を見る">試験の詳細 ↗</a></div></article>`;
  }
  function noteCard(row,index) {
    const url=String(row.url||'');
    if(!/^https:\/\/note\.com\/merry_lily\/n\/n[a-z0-9]+$/i.test(url))return '';
    return `<article class="record-card"><div class="record-head"><div class="record-tags"><span class="tag">${esc(row.category)}</span><span class="tag tag-neutral">merry_lilyのnote</span></div><span class="record-number">ARTICLE / ${String(index+1).padStart(2,'0')}</span></div><h4 class="record-title">${esc(row.title)}</h4><p class="record-desc">${esc(row.description||'')}</p><div class="record-bottom"><small>${esc(dateFormat(row.date))} 公開</small><a href="${esc(url)}" target="_blank" rel="noopener noreferrer">noteで読む ↗</a></div></article>`;
  }
  function render() {
    if(!DATA){ $('record-list').innerHTML='<div class="empty-state"><strong>データを読み込めませんでした</strong><p>公開ファイルに data/site-data.js があるか確認してください．</p></div>';return; }
    filtered=filterRecords();
    $('result-total').textContent = `${filtered.length.toLocaleString('ja-JP')} 件`; 
    const visible=filtered.slice(0,state.visible);
    $('record-list').innerHTML=visible.length ? visible.map((item,i)=>state.tab==='papers'?paperCard(item,i):state.tab==='trials'?trialCard(item):noteCard(item,i)).join('') : '<div class="empty-state"><strong>該当する情報がありません</strong><p>条件を減らすか，キーワードを変えて検索してください．</p><button id="empty-reset" type="button">すべての条件を解除する</button></div>';
    $('more-wrap').hidden=filtered.length<=state.visible;
    const reset=$('empty-reset');if(reset)reset.addEventListener('click',resetFilters);
  }
  function resetFilters() {
    state.disease='all';state.topic='all';state.research_type='all';state.status='all';state.phase='all';state.mechanism='all';state.japan=false;state.search='';state.sort='recent';state.visible=8;
    $('search').value='';$('sort-select').value='recent';updateDictionaries();updateDiseaseCounts();render();
  }
  qa('[data-tab]').forEach(el=>el.addEventListener('click',()=>chooseTab(el.dataset.tab,false)));
  qa('[data-nav]').forEach(el=>el.addEventListener('click',()=>chooseTab(el.dataset.nav,true)));
  qa('[data-disease]').forEach(el=>el.addEventListener('click',()=>{
    if(state.tab==='articles') chooseTab('papers',false);
    state.disease=el.dataset.disease;state.visible=8;
    updateDictionaries();updateDiseaseCounts();render();
    $('explore').scrollIntoView({behavior:'smooth',block:'start'});
  }));
  [['disease-select','disease'],['topic-select','topic'],['status-select','status'],['phase-select','phase'],['mechanism-select','mechanism'],['research-type-select','research_type'],['sort-select','sort']].forEach(([id,key])=>{
    $(id).addEventListener('change',(e)=>{state[key]=e.target.value;state.visible=8;if(key==='disease')updateDictionaries();render();});
  });
  $('japan-only').addEventListener('change',(e)=>{state.japan=e.target.checked;state.visible=8;render();});
  $('search').addEventListener('input',(e)=>{state.search=e.target.value;state.visible=8;render();});
  $('clear-filters').addEventListener('click',resetFilters);
  $('load-more').addEventListener('click',()=>{state.visible+=8;render();});
  $('mobile-menu-button').addEventListener('click',()=>{const menu=$('mobile-menu');menu.hidden=!menu.hidden;$('mobile-menu-button').setAttribute('aria-expanded',String(!menu.hidden));});
  syncCounts();updateDictionaries();render();
  if(location.hash==='#trials')chooseTab('trials',false);
  else if(location.hash==='#articles')chooseTab('articles',false);
})();
