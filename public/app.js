
(() => {
  'use strict';

  const DATA = window.DEMENTIA_DATA || null;

  const DISEASES = {
    all: 'すべて',
    ad: 'アルツハイマー病',
    mci: '軽度認知障害',
    dlb: 'レビー小体型認知症',
    ftd: '前頭側頭葉変性症',
    vascular: '血管性認知症・その他',
    other: 'その他'
  };

  const TOPICS = {
    treatment: '治療',
    biomarker: 'バイオマーカー',
    imaging: '画像',
    diagnosis: '診断',
    prevention: '予防',
    care: 'ケア・生活',
    pathology: '病態',
    other: 'その他'
  };

  const STATUS = {
    RECRUITING: ['募集中', 'recruiting'],
    NOT_YET_RECRUITING: ['募集開始前', 'pending'],
    ENROLLING_BY_INVITATION: ['招待者のみ', 'pending'],
    ACTIVE_NOT_RECRUITING: ['実施中・募集終了', 'closed'],
    COMPLETED: ['終了', 'closed'],
    SUSPENDED: ['一時中断', 'closed'],
    TERMINATED: ['中止', 'closed'],
    WITHDRAWN: ['撤回', 'closed'],
    UNKNOWN: ['確認が必要', 'closed']
  };

  const MECHANISMS = {
    amyloid: '抗Aβ',
    tau: '抗タウ',
    symptomatic: '認知・行動症状',
    inflammation: '炎症・免疫',
    gene: '遺伝子・核酸',
    non_drug: '非薬物・機器',
    other: 'その他'
  };

  const RESEARCH_TYPES = {
    all: 'すべて',
    trial: '臨床試験',
    guideline: '診療指針',
    systematic: '系統的レビュー・メタ解析',
    validation: '外部検証・多施設',
    cohort: 'コホート',
    discovery: '基礎・探索',
    other: 'その他'
  };

  const TITLES = {
    papers: {
      label: '新着論文',
      title: '新着論文',
      sub: 'PubMedの書誌情報に基づいて自動抽出した論文を掲載しています．掲載は研究の質を評価したものではありません．',
      source: 'PubMed'
    },
    trials: {
      label: '臨床試験',
      title: '臨床試験・治験',
      sub: 'ClinicalTrials.govの介入試験を，疾患・Phase・募集状況などから探せます．',
      source: 'ClinicalTrials.gov'
    },
    articles: {
      label: '解説記事',
      title: '解説・note',
      sub: '公開済みのnote記事をまとめています．',
      source: 'note'
    }
  };

  const $ = (id) => document.getElementById(id);
  const q = (s) => document.querySelector(s);
  const qa = (s) => [...document.querySelectorAll(s)];

  const esc = (value) => String(value ?? '').replace(
    /[&<>"']/g,
    (x) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[x])
  );

  const dateFormat = (value) => {
    const m = String(value || '').match(
      /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?/
    );
    if (!m) return '日付未登録';
    return `${m[1]}年${m[2] ? `${Number(m[2])}月` : ''}${m[3] ? `${Number(m[3])}日` : ''}`;
  };

  const fetchTime = (value) => {
    if (!value) return '取得日時未登録';

    const d = new Date(value);
    if (Number.isNaN(d.getTime())) {
      return dateFormat(String(value).slice(0, 10));
    }

    return new Intl.DateTimeFormat('ja-JP', {
      timeZone: 'Asia/Tokyo',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    }).format(d) + '（日本時間）';
  };

  const topicName = (x) => TOPICS[x] || TOPICS.other;
  const diseaseName = (x) => DISEASES[x] || DISEASES.other;

  const matchesDisease = (x, selected) =>
    selected === 'all' ||
    (
      selected === 'vascular'
        ? !['ad', 'mci', 'dlb', 'ftd'].includes(x.disease)
        : x.disease === selected
    );

  const normalize = (s) =>
    String(s || '').normalize('NFKC').toLocaleLowerCase();

  const state = {
    tab: 'papers',
    disease: 'all',
    topic: 'all',
    research_type: 'all',
    status: 'all',
    phase: 'all',
    mechanism: 'all',
    japan: false,
    search: '',
    sort: 'recent',
    visible: 8
  };

  let filtered = [];

  function dataItems(type) {
    return DATA &&
      DATA[type] &&
      Array.isArray(DATA[type].items)
      ? DATA[type].items
      : [];
  }

  function syncCounts() {
    ['papers', 'trials', 'articles'].forEach(type => {
      $('tab-count-' + type).textContent =
        dataItems(type).length.toLocaleString('ja-JP');
    });

    $('stat-papers').textContent =
      dataItems('papers').length.toLocaleString('ja-JP');

    $('stat-trials').textContent =
      dataItems('trials').length.toLocaleString('ja-JP');

    $('stat-japan').textContent =
      dataItems('trials')
        .filter(r => r.has_japan_site === true)
        .length.toLocaleString('ja-JP');

    const p = DATA?.papers?.meta;
    const t = DATA?.trials?.meta;
    const api = p?.mode === 'api' && t?.mode === 'api';

    $('data-mode').textContent = api
      ? '公式APIから取得した情報'
      : '初期登録データを含みます';

    $('data-mode').classList.toggle('sample', !api);

    const parts = [
      p?.fetched_at
        ? `論文：${fetchTime(p.fetched_at)}`
        : null,
      t?.fetched_at
        ? `臨床試験：${fetchTime(t.fetched_at)}`
        : null
    ].filter(Boolean);

    $('data-updated').textContent = parts.length
      ? `最終取得 ／ ${parts.join(' ／ ')}`
      : '取得日時は未登録です';

    updateDiseaseCounts();
  }

  function updateDiseaseCounts() {
    const items = dataItems(
      state.tab === 'articles' ? 'papers' : state.tab
    );

    ['all', 'ad', 'mci', 'dlb', 'ftd', 'vascular'].forEach(d => {
      const el = $('disease-count-' + d);
      if (el) {
        el.textContent =
          `${items.filter(x => matchesDisease(x, d)).length} 件`;
      }
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
      ? [
          ['all', 'すべてのカテゴリ'],
          ['試験対策', '試験対策'],
          ['研究の読みもの', '研究の読みもの'],
          ['バイオマーカー', 'バイオマーカー'],
          ['診療・生活', '診療・生活'],
          ['治療', '治療'],
          ['予防・生活', '予防・生活']
        ]
      : [
          ['all', 'すべてのテーマ'],
          ['treatment', '治療・治験'],
          ['biomarker', 'バイオマーカー'],
          ['imaging', '脳画像'],
          ['diagnosis', '診断・評価'],
          ['prevention', '予防・生活習慣'],
          ['care', 'ケア・社会'],
          ['pathology', '病態・基礎'],
          ['other', 'その他']
        ];

    $('topic-select').innerHTML = opts
      .map(([v, label]) =>
        `<option value="${esc(v)}">${esc(label)}</option>`
      )
      .join('');

    $('topic-select').value = state.topic;
    $('disease-select').value = state.disease;
    $('status-select').value = state.status;
    $('phase-select').value = state.phase;
    $('mechanism-select').value = state.mechanism;
    $('japan-only').checked = state.japan;

    const t = TITLES[state.tab];

    $('results-kicker').textContent = t.label;
    $('results-title').textContent = t.title;
    $('results-subtitle').textContent = t.sub;
    $('source-footnote').textContent = `情報源：${t.source}`;

    $('search').placeholder =
      state.tab === 'papers'
        ? '論文タイトル・PMID・雑誌名で検索'
        : state.tab === 'trials'
          ? '試験名・薬剤・NCT番号で検索'
          : '記事タイトル・テーマで検索';

    const m = DATA?.[state.tab]?.meta;

    $('last-updated-detail').textContent =
      m?.mode === 'api'
        ? `最終取得：${fetchTime(m.fetched_at)}`
        : m?.mode === 'curated'
          ? '公開済みのnote記事を掲載'
          : '初期登録データ';

    qa('.tab-button').forEach(el => {
      const on = el.dataset.tab === state.tab;
      el.classList.toggle('active', on);
      el.setAttribute('aria-selected', String(on));
    });

    qa('.nav-link').forEach(el => {
      el.classList.toggle(
        'active',
        el.dataset.nav === state.tab
      );
    });

    qa('.disease-card').forEach(el => {
      el.classList.toggle(
        'selected',
        el.dataset.disease === state.disease
      );
    });
  }

  function chooseTab(tab, scroll = true) {
    if (!TITLES[tab]) return;

    const was = state.tab;
    state.tab = tab;
    state.visible = 8;

    state.topic = 'all';
    state.status = 'all';
    state.phase = 'all';
    state.mechanism = 'all';
    state.japan = false;
    state.disease = 'all';
    state.research_type = 'all';

    $('sort-select').value = state.sort;

    if (was !== tab) {
      state.search = '';
      $('search').value = '';
    }

    updateDictionaries();
    updateDiseaseCounts();
    render();

    if (scroll) {
      $('explore').scrollIntoView({
        behavior: 'smooth',
        block: 'start'
      });
    }

    const mobile = $('mobile-menu');
    mobile.hidden = true;

    $('mobile-menu-button').setAttribute(
      'aria-expanded',
      'false'
    );
  }

  function filterRecords() {
    let records = dataItems(state.tab).slice();

    if (state.tab !== 'articles') {
      records = records.filter(
        row => matchesDisease(row, state.disease)
      );

      if (state.topic !== 'all') {
        records = records.filter(
          row => row.topic === state.topic
        );
      }
    } else if (state.topic !== 'all') {
      records = records.filter(
        row => row.category === state.topic
      );
    }

    if (
      state.tab === 'papers' &&
      state.research_type !== 'all'
    ) {
      records = records.filter(
        row => row.research_type === state.research_type
      );
    }

    if (state.tab === 'trials') {
      if (state.status !== 'all') {
        records = records.filter(
          row => row.status === state.status
        );
      }

      if (state.phase !== 'all') {
        records = records.filter(
          row => (row.phases || []).includes(state.phase)
        );
      }

      if (state.mechanism !== 'all') {
        records = records.filter(
          row => row.mechanism === state.mechanism
        );
      }

      if (state.japan) {
        records = records.filter(
          row => row.has_japan_site === true
        );
      }
    }

    if (state.search.trim()) {
      const tokens = normalize(state.search)
        .split(/\s+/)
        .filter(Boolean);

      records = records.filter(row => {
        const joined = normalize([
          row.title,
          row.id,
          row.journal,
          row.category,
          row.description,
          ...(row.interventions || []),
          row.status,
          row.disease,
          row.topic
        ].join(' '));

        return tokens.every(
          token => joined.includes(token)
        );
      });
    }

    if (state.sort === 'title') {
      records.sort(
        (a, b) =>
          String(a.title || '').localeCompare(
            String(b.title || ''),
            'ja'
          )
      );
    } else {
      records.sort((a, b) => {
        const aDate = (
          state.tab === 'papers'
            ? a.pubmed_entry_date || a.date || a.selected_on
            : a.date || a.updated
        ) || '';

        const bDate = (
          state.tab === 'papers'
            ? b.pubmed_entry_date || b.date || b.selected_on
            : b.date || b.updated
        ) || '';

        return (
          state.sort === 'recent'
            ? bDate.localeCompare(aDate)
            : aDate.localeCompare(bDate)
        ) || String(a.id || '').localeCompare(
          String(b.id || '')
        );
      });
    }

    return records;
  }

  function paperCard(row) {
    const id = String(row.id || '');
    if (!/^\d+$/.test(id)) return '';

    const tags = `
      <span class="tag">${esc(diseaseName(row.disease))}</span>
      <span class="tag tag-alt">${esc(topicName(row.topic))}</span>
    `;

    const kind =
      RESEARCH_TYPES[row.research_type] || '研究論文';

    return `
      <article class="record-card">
        <div class="record-head">
          <div class="record-tags">
            <span class="tag tag-impact">${esc(kind)}</span>
            ${tags}
          </div>
          <span class="record-number">PMID ${esc(id)}</span>
        </div>

        <h4 class="record-title">${esc(row.title)}</h4>

        <p class="record-meta">
          <span>${esc(row.journal || '雑誌名未登録')}</span>
          <span class="meta-sep">•</span>
          <span>${esc(dateFormat(row.date))}</span>
        </p>

        <div class="record-bottom">
          <small>情報源：PubMed</small>
          <a
            href="https://pubmed.ncbi.nlm.nih.gov/${id}/"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="PMID ${id} の原文情報を見る"
          >PubMedで確認 ↗</a>
        </div>
      </article>
    `;
  }

  function trialCard(row) {
    const id = String(row.id || '');
    if (!/^NCT\d{8}$/.test(id)) return '';

    const [status, statusStyle] =
      STATUS[row.status] || STATUS.UNKNOWN;

    const phase = (row.phases || [])
      .map(x => {
        if (x === 'NA') return 'Phase対象外';
        if (x === 'EARLY_PHASE1') return '早期Phase 1';
        return x.replace('PHASE', 'Phase ');
      })
      .join(' / ') || 'Phase未登録';

    const mech =
      MECHANISMS[row.mechanism] || MECHANISMS.other;

    const jp = row.has_japan_site === true
      ? `<span class="trial-japan">🇯🇵 ${
          row.japan_recruiting_now === true
            ? '日本の施設で募集中'
            : '日本に実施施設あり'
        }</span>`
      : row.has_japan_site === null
        ? '<span class="trial-japan unknown">実施国は公式記録で確認</span>'
        : '';

    const intr = (row.interventions || [])
      .slice(0, 3)
      .join(' / ');

    return `
      <article class="record-card">
        <div class="record-head">
          <div class="record-tags">
            <span class="tag tag-status ${esc(statusStyle)}">${esc(status)}</span>
            <span class="tag">${esc(diseaseName(row.disease))}</span>
            <span class="tag tag-alt">${esc(phase)}</span>
            <span class="tag tag-neutral">${esc(mech)}</span>
          </div>
          <span class="record-number">${esc(id)}</span>
        </div>

        <h4 class="record-title">${esc(row.title)}</h4>

        <p class="record-meta">
          <span>${esc(intr || '介入内容は公式記録参照')}</span>
          <span class="meta-sep">•</span>
          <span>登録情報の最終更新 ${esc(dateFormat(row.updated))}</span>
        </p>

        <div class="record-bottom">
          <div class="record-pillbox">
            ${jp}
            <small>情報源：ClinicalTrials.gov</small>
          </div>
          <a
            href="https://clinicaltrials.gov/study/${id}"
            target="_blank"
            rel="noopener noreferrer"
          >試験の詳細 ↗</a>
        </div>
      </article>
    `;
  }

  function noteCard(row, index) {
    const url = String(row.url || '');

    if (
      !/^https:\/\/note\.com\/merry_lily\/n\/n[a-z0-9]+$/i.test(url)
    ) {
      return '';
    }

    return `
      <article class="record-card">
        <div class="record-head">
          <div class="record-tags">
            <span class="tag">${esc(row.category)}</span>
            <span class="tag tag-neutral">merry_lilyのnote</span>
          </div>
          <span class="record-number">記事 ${String(index + 1).padStart(2, '0')}</span>
        </div>

        <h4 class="record-title">${esc(row.title)}</h4>

        <p class="record-desc">${esc(row.description || '')}</p>

        <div class="record-bottom">
          <small>${esc(dateFormat(row.date))} 公開</small>
          <a
            href="${esc(url)}"
            target="_blank"
            rel="noopener noreferrer"
          >noteで読む ↗</a>
        </div>
      </article>
    `;
  }

  function render() {
    if (!DATA) {
      $('record-list').innerHTML = `
        <div class="empty-state">
          <strong>データを読み込めませんでした</strong>
          <p>時間をおいて再読み込みしてください．</p>
        </div>
      `;
      return;
    }

    filtered = filterRecords();

    $('result-total').textContent =
      `${filtered.length.toLocaleString('ja-JP')} 件`;

    const visible = filtered.slice(0, state.visible);

    $('record-list').innerHTML = visible.length
      ? visible.map((item, i) =>
          state.tab === 'papers'
            ? paperCard(item)
            : state.tab === 'trials'
              ? trialCard(item)
              : noteCard(item, i)
        ).join('')
      : `
        <div class="empty-state">
          <strong>該当する情報がありません</strong>
          <p>条件を減らすか，キーワードを変えて検索してください．</p>
          <button id="empty-reset" type="button">
            すべての条件を解除する
          </button>
        </div>
      `;

    $('more-wrap').hidden =
      filtered.length <= state.visible;

    const reset = $('empty-reset');
    if (reset) {
      reset.addEventListener('click', resetFilters);
    }
  }

  function resetFilters() {
    state.disease = 'all';
    state.topic = 'all';
    state.research_type = 'all';
    state.status = 'all';
    state.phase = 'all';
    state.mechanism = 'all';
    state.japan = false;
    state.search = '';
    state.sort = 'recent';
    state.visible = 8;

    $('search').value = '';
    $('sort-select').value = 'recent';

    updateDictionaries();
    updateDiseaseCounts();
    render();
  }

  qa('[data-tab]').forEach(el => {
    el.addEventListener(
      'click',
      () => chooseTab(el.dataset.tab, false)
    );
  });

  qa('[data-nav]').forEach(el => {
    el.addEventListener(
      'click',
      () => chooseTab(el.dataset.nav, true)
    );
  });

  qa('[data-disease]').forEach(el => {
    el.addEventListener('click', () => {
      if (state.tab === 'articles') {
        chooseTab('papers', false);
      }

      state.disease = el.dataset.disease;
      state.visible = 8;

      updateDictionaries();
      updateDiseaseCounts();
      render();

      $('explore').scrollIntoView({
        behavior: 'smooth',
        block: 'start'
      });
    });
  });

  [
    ['disease-select', 'disease'],
    ['topic-select', 'topic'],
    ['status-select', 'status'],
    ['phase-select', 'phase'],
    ['mechanism-select', 'mechanism'],
    ['research-type-select', 'research_type'],
    ['sort-select', 'sort']
  ].forEach(([id, key]) => {
    $(id).addEventListener('change', e => {
      state[key] = e.target.value;
      state.visible = 8;

      if (key === 'disease') {
        updateDictionaries();
      }

      render();
    });
  });

  $('japan-only').addEventListener('change', e => {
    state.japan = e.target.checked;
    state.visible = 8;
    render();
  });

  $('search').addEventListener('input', e => {
    state.search = e.target.value;
    state.visible = 8;
    render();
  });

  $('clear-filters').addEventListener(
    'click',
    resetFilters
  );

  $('load-more').addEventListener('click', () => {
    state.visible += 8;
    render();
  });

  $('mobile-menu-button').addEventListener(
    'click',
    () => {
      const menu = $('mobile-menu');
      menu.hidden = !menu.hidden;

      $('mobile-menu-button').setAttribute(
        'aria-expanded',
        String(!menu.hidden)
      );
    }
  );

  syncCounts();
  updateDictionaries();
  render();

  if (location.hash === '#trials') {
    chooseTab('trials', false);
  } else if (location.hash === '#articles') {
    chooseTab('articles', false);
  }
})();
