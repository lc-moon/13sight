/**
 * institution.js
 * 기관 분석 페이지 전체 렌더링 로직
 *
 * 동작 흐름:
 * 1. URL 파라미터 cik를 읽는다
 * 2. data/institutions.json을 fetch한다
 * 3. 해당 기관 데이터를 찾아 각 섹션을 렌더링한다
 *    - 기관 기본 정보 헤더
 *    - 섹션1: AUM 추이 막대 차트
 *    - 섹션2: 섹터 배분 도넛 차트 (이전/최신 분기 비교)
 *    - 섹션3: 분기 간 변화 탭 UI (신규매수/완전매도/비중증가/비중감소)
 *    - 섹션4: 보유 종목 전체 테이블 (정렬/페이지네이션)
 */

// JSON 데이터 경로 (web/data/ 하위에 위치)
const DATA_URL = 'data/institutions.json';

// 페이지당 표시 종목 수
const PAGE_SIZE = 20;

// ── 전역 상태 ──────────────────────────────────────────────────────────────
let _allHoldings   = [];   // 현재 분기 전체 보유 종목 (정렬 전 원본 순서 유지)
let _sortedHoldings = [];  // 현재 정렬 기준으로 정렬된 종목 배열
let _currentPage   = 1;    // 현재 페이지 번호
let _sortCol       = 'value';     // 현재 정렬 컬럼
let _sortDir       = 'desc';      // 정렬 방향 ('asc' | 'desc')
let _prevHoldingsMap = {};  // 이전 분기 종목 맵 {cusip: holding}

// ── 유틸리티 ────────────────────────────────────────────────────────────────

/**
 * XSS 방지용 HTML 이스케이프
 */
function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * AUM 값(천달러)을 읽기 쉬운 형식으로 변환한다.
 * 예: 7400000000 → "$7.40T"
 */
function formatAUM(valueInThousands) {
  const usd = valueInThousands * 1000;
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(2)}T`;
  if (usd >= 1e9)  return `$${(usd / 1e9).toFixed(1)}B`;
  if (usd >= 1e6)  return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toLocaleString()}`;
}

/**
 * 평가금액(천달러)을 축약 형식으로 변환한다.
 * 예: 182000 → "$182.0M"
 */
function formatValue(valueInThousands) {
  const usd = valueInThousands * 1000;
  if (usd >= 1e9)  return `$${(usd / 1e9).toFixed(2)}B`;
  if (usd >= 1e6)  return `$${(usd / 1e6).toFixed(1)}M`;
  if (usd >= 1e3)  return `$${(usd / 1e3).toFixed(0)}K`;
  return `$${usd.toLocaleString()}`;
}

/**
 * 숫자를 세 자리 콤마 형식으로 포맷한다.
 */
function formatNumber(num) {
  return Number(num).toLocaleString();
}

/**
 * "2025-09-30" 형식을 "2025 Q3" 형식으로 변환한다.
 */
function periodToLabel(period) {
  try {
    const month = parseInt(period.slice(5, 7), 10);
    const year  = period.slice(0, 4);
    const qMap  = { 3: 'Q1', 6: 'Q2', 9: 'Q3', 12: 'Q4' };
    return `${year} ${qMap[month] || '?'}`;
  } catch {
    return period;
  }
}

// ── 로딩/에러 상태 제어 ──────────────────────────────────────────────────────

function showLoading()  { document.getElementById('loading').style.display = 'flex'; }
function hideLoading()  { document.getElementById('loading').style.display = 'none'; }

function showError(msg) {
  document.getElementById('error-msg').textContent = msg;
  document.getElementById('error-area').style.display = 'block';
}

function showContent() {
  document.getElementById('inst-content').style.display = 'block';
}

// ── 기관 기본 정보 헤더 렌더링 ───────────────────────────────────────────────

function renderHeader(inst, latestFiling) {
  document.getElementById('inst-name-en').textContent = inst.name_en || '';
  document.getElementById('inst-name-ko').textContent = inst.name_ko || '';
  document.getElementById('inst-aum').textContent     = formatAUM(latestFiling.total_aum);
  document.getElementById('inst-period').textContent  =
    latestFiling.period_label || periodToLabel(latestFiling.period);
  document.getElementById('inst-filed-date').textContent = latestFiling.filed_date || '-';
  document.getElementById('inst-cik').textContent     = inst.cik || '';

  // 페이지 제목 업데이트
  document.title = `${inst.name_en} — 13Sight`;
}

// ── 섹션1: AUM 추이 막대 차트 ────────────────────────────────────────────────

function renderAUMChart(filings) {
  // oled 순서 (가장 오래된 → 최신)
  const labels = filings.map(f => f.period_label || periodToLabel(f.period));
  const values = filings.map(f => f.total_aum);
  createAUMChart('aum-chart', labels, values);
}

// ── 섹션2: 섹터 배분 도넛 차트 ──────────────────────────────────────────────

function renderSectorCharts(filings) {
  const section = document.getElementById('sector-section');

  if (filings.length === 0) {
    section.style.display = 'none';
    return;
  }

  // 분기가 1개만 있을 경우: 이전 분기 자리를 빈 상태로 처리
  const latestFiling = filings[filings.length - 1];
  const prevFiling   = filings.length >= 2 ? filings[filings.length - 2] : null;

  const latestLabel = latestFiling.period_label || periodToLabel(latestFiling.period);
  const prevLabel   = prevFiling
    ? (prevFiling.period_label || periodToLabel(prevFiling.period))
    : null;

  document.getElementById('curr-donut-title').textContent = latestLabel;

  if (prevFiling && prevLabel) {
    document.getElementById('prev-donut-title').textContent = prevLabel;
    createSectorDonut('prev-sector-chart', prevFiling.sector_breakdown || {});
  } else {
    // 이전 분기 없으면 왼쪽 차트 숨김
    const prevWrap = document.getElementById('prev-donut-title').closest('.donut-chart-wrap');
    if (prevWrap) prevWrap.style.display = 'none';
  }

  createSectorDonut('curr-sector-chart', latestFiling.sector_breakdown || {});
}

// ── 섹션3: 분기 간 변화 탭 UI ────────────────────────────────────────────────

/**
 * 이전 분기 종목 맵을 생성한다. {cusip: holding}
 */
function buildHoldingsMap(holdings) {
  const map = {};
  for (const h of (holdings || [])) {
    if (h.cusip) map[h.cusip] = h;
  }
  return map;
}

/**
 * 분기 간 변화를 계산한다.
 * 반환: { newBuys, fullSells, weightUp, weightDown }
 */
function computeChanges(prevMap, currHoldings) {
  const currMap  = buildHoldingsMap(currHoldings);
  const newBuys  = [];  // 이전 분기 없고 현재 분기 존재
  const fullSells = []; // 이전 분기 존재하고 현재 분기 없음
  const changed   = []; // 공통 종목 (비중 변화)

  // 신규 매수 + 공통 종목 추출
  for (const h of (currHoldings || [])) {
    const prev = prevMap[h.cusip];
    if (!prev) {
      newBuys.push({ ...h, changePct: null, changeVal: null });
    } else {
      const changeVal = h.value - prev.value;
      const changePct = prev.value > 0
        ? ((h.value - prev.value) / prev.value) * 100
        : 0;
      changed.push({ ...h, changePct, changeVal, prevValue: prev.value });
    }
  }

  // 완전 매도: 이전 분기에 있었지만 현재 분기에 없는 종목
  for (const [cusip, prev] of Object.entries(prevMap)) {
    if (!currMap[cusip]) {
      fullSells.push({ ...prev });
    }
  }

  // 비중 증가/감소 Top10
  const weightUp   = [...changed]
    .filter(h => h.changePct > 0)
    .sort((a, b) => b.changePct - a.changePct)
    .slice(0, 10);

  const weightDown = [...changed]
    .filter(h => h.changePct < 0)
    .sort((a, b) => a.changePct - b.changePct)
    .slice(0, 10);

  return { newBuys, fullSells, weightUp, weightDown };
}

/**
 * 변화 탭 테이블 HTML을 생성한다.
 * type: 'new-buy' | 'full-sell' | 'change-up' | 'change-down'
 */
function buildChangeTable(holdings, type) {
  if (!holdings || holdings.length === 0) {
    return '<div class="empty-state">해당 데이터가 없습니다.</div>';
  }

  const isChange = type === 'change-up' || type === 'change-down';

  let thead = `
    <thead>
      <tr>
        <th>종목명</th>
        <th>티커</th>
        <th>평가금액</th>
        ${isChange ? '<th>변화금액</th><th>변화율</th>' : ''}
      </tr>
    </thead>
  `;

  const rows = holdings.map(h => {
    const changeHtml = isChange
      ? `<td>${formatValue(h.changeVal)}</td>
         <td>${h.changePct >= 0
           ? `<span class="change-up">▲ +${h.changePct.toFixed(1)}%</span>`
           : `<span class="change-down">▼ ${h.changePct.toFixed(1)}%</span>`
         }</td>`
      : '';

    return `
      <tr>
        <td>${escapeHtml(h.name)}</td>
        <td class="td-ticker">${escapeHtml(h.ticker || '-')}</td>
        <td class="td-value">${formatValue(h.value)}</td>
        ${changeHtml}
      </tr>
    `;
  }).join('');

  return `<div class="table-wrap"><table>${thead}<tbody>${rows}</tbody></table></div>`;
}

/**
 * 섹션3 전체를 렌더링한다.
 */
function renderChanges(filings) {
  const section = document.getElementById('changes-section');

  if (filings.length < 2) {
    section.style.display = 'none';
    return;
  }

  const latestFiling = filings[filings.length - 1];
  const prevFiling   = filings[filings.length - 2];

  _prevHoldingsMap = buildHoldingsMap(prevFiling.holdings);
  const { newBuys, fullSells, weightUp, weightDown } =
    computeChanges(_prevHoldingsMap, latestFiling.holdings);

  document.getElementById('tab-new-buys').innerHTML    = buildChangeTable(newBuys,   'new-buy');
  document.getElementById('tab-full-sells').innerHTML  = buildChangeTable(fullSells, 'full-sell');
  document.getElementById('tab-weight-up').innerHTML   = buildChangeTable(weightUp,  'change-up');
  document.getElementById('tab-weight-down').innerHTML = buildChangeTable(weightDown,'change-down');
}

// ── 탭 UI 이벤트 바인딩 ──────────────────────────────────────────────────────

function initTabs() {
  const tabBtns = document.querySelectorAll('.tab-btn');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      // 모든 탭 비활성화
      tabBtns.forEach(b => { b.classList.remove('active'); b.setAttribute('aria-selected', 'false'); });
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      // 클릭한 탭 활성화
      btn.classList.add('active');
      btn.setAttribute('aria-selected', 'true');
      const tabId = `tab-${btn.dataset.tab}`;
      const pane = document.getElementById(tabId);
      if (pane) pane.classList.add('active');
    });
  });
}

// ── 섹션4: 보유 종목 전체 테이블 ─────────────────────────────────────────────

/**
 * 현재 분기 대비 전분기 변화 HTML을 생성한다.
 */
function buildChangeCell(h) {
  // 이전 분기 종목 맵에서 같은 CUSIP 탐색
  const prev = _prevHoldingsMap[h.cusip];

  if (!prev) {
    // 신규 종목
    return '<span class="change-new">NEW</span>';
  }

  const changePct = prev.value > 0
    ? ((h.value - prev.value) / prev.value) * 100
    : 0;

  if (Math.abs(changePct) < 0.05) {
    // 변화 없음 (0.05% 미만)
    return '<span style="color:#888;">-</span>';
  }

  if (changePct > 0) {
    return `<span class="change-up">▲ +${changePct.toFixed(1)}%</span>`;
  } else {
    return `<span class="change-down">▼ ${changePct.toFixed(1)}%</span>`;
  }
}

/**
 * 종목 테이블 tbody를 렌더링한다 (현재 페이지 기준).
 */
function renderHoldingsTable() {
  const tbody = document.getElementById('holdings-tbody');
  if (!tbody) return;

  const startIdx = (_currentPage - 1) * PAGE_SIZE;
  const pageItems = _sortedHoldings.slice(startIdx, startIdx + PAGE_SIZE);

  if (pageItems.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="empty-state">보유 종목 데이터가 없습니다.</td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = pageItems.map((h, idx) => {
    const rank = startIdx + idx + 1;
    return `
      <tr>
        <td class="td-rank">${rank}</td>
        <td>${escapeHtml(h.name)}</td>
        <td class="td-ticker">${escapeHtml(h.ticker || '-')}</td>
        <td class="td-value">${formatNumber(h.shares)}</td>
        <td class="td-value">${formatValue(h.value)}</td>
        <td class="td-weight">${(h.weight_pct || 0).toFixed(2)}%</td>
        <td>${buildChangeCell(h)}</td>
      </tr>
    `;
  }).join('');
}

/**
 * 페이지네이션 버튼을 렌더링한다.
 */
function renderPagination() {
  const container = document.getElementById('pagination');
  if (!container) return;

  const totalPages = Math.ceil(_sortedHoldings.length / PAGE_SIZE);

  if (totalPages <= 1) {
    container.innerHTML = '';
    return;
  }

  // 표시할 페이지 번호 범위 계산 (현재 페이지 기준 ±2)
  const delta   = 2;
  const rangeStart = Math.max(1, _currentPage - delta);
  const rangeEnd   = Math.min(totalPages, _currentPage + delta);

  let buttons = '';

  // 이전 버튼
  buttons += `
    <button class="page-btn" data-page="${_currentPage - 1}"
      ${_currentPage === 1 ? 'disabled' : ''}>&#8249;</button>
  `;

  // 첫 페이지
  if (rangeStart > 1) {
    buttons += `<button class="page-btn" data-page="1">1</button>`;
    if (rangeStart > 2) buttons += `<span style="padding:0 4px;line-height:36px;color:#888;">…</span>`;
  }

  // 범위 내 페이지 번호
  for (let p = rangeStart; p <= rangeEnd; p++) {
    buttons += `
      <button class="page-btn ${p === _currentPage ? 'active' : ''}" data-page="${p}">${p}</button>
    `;
  }

  // 마지막 페이지
  if (rangeEnd < totalPages) {
    if (rangeEnd < totalPages - 1) buttons += `<span style="padding:0 4px;line-height:36px;color:#888;">…</span>`;
    buttons += `<button class="page-btn" data-page="${totalPages}">${totalPages}</button>`;
  }

  // 다음 버튼
  buttons += `
    <button class="page-btn" data-page="${_currentPage + 1}"
      ${_currentPage === totalPages ? 'disabled' : ''}>&#8250;</button>
  `;

  container.innerHTML = buttons;

  // 클릭 이벤트 (이벤트 위임)
  container.onclick = (e) => {
    const btn = e.target.closest('.page-btn');
    if (!btn || btn.disabled) return;
    const page = parseInt(btn.dataset.page, 10);
    if (!isNaN(page) && page !== _currentPage) {
      _currentPage = page;
      renderHoldingsTable();
      renderPagination();
      // 테이블 상단으로 스크롤
      document.getElementById('holdings-table')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };
}

/**
 * 정렬 함수: 컬럼 이름과 방향으로 _sortedHoldings를 정렬한다.
 */
function sortHoldings(col, dir) {
  _sortedHoldings = [..._allHoldings].sort((a, b) => {
    let av = a[col];
    let bv = b[col];

    // 숫자형 컬럼
    if (col === 'value' || col === 'shares' || col === 'weight_pct') {
      av = Number(av) || 0;
      bv = Number(bv) || 0;
    } else {
      // 문자열 컬럼 (대소문자 무관)
      av = String(av || '').toLowerCase();
      bv = String(bv || '').toLowerCase();
    }

    if (av < bv) return dir === 'asc' ? -1 : 1;
    if (av > bv) return dir === 'asc' ? 1  : -1;
    return 0;
  });
}

/**
 * 테이블 헤더 정렬 표시를 업데이트한다.
 */
function updateSortIndicators(activeCol, dir) {
  document.querySelectorAll('#holdings-table thead th.sortable').forEach(th => {
    th.classList.remove('sort-asc', 'sort-desc');
    if (th.dataset.col === activeCol) {
      th.classList.add(dir === 'asc' ? 'sort-asc' : 'sort-desc');
    }
  });
}

/**
 * 정렬 가능한 헤더 클릭 이벤트를 바인딩한다.
 */
function initSortableHeaders() {
  document.querySelectorAll('#holdings-table thead th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const col = th.dataset.col;
      if (_sortCol === col) {
        // 같은 컬럼 → 방향 전환
        _sortDir = _sortDir === 'asc' ? 'desc' : 'asc';
      } else {
        // 다른 컬럼 → 내림차순으로 시작
        _sortCol = col;
        _sortDir = 'desc';
      }
      sortHoldings(_sortCol, _sortDir);
      updateSortIndicators(_sortCol, _sortDir);
      _currentPage = 1;
      renderHoldingsTable();
      renderPagination();
    });
  });
}

/**
 * 섹션4 전체를 초기화한다.
 */
function renderHoldingsSection(latestFiling) {
  _allHoldings    = latestFiling.holdings || [];
  _currentPage    = 1;
  _sortCol        = 'value';
  _sortDir        = 'desc';

  sortHoldings(_sortCol, _sortDir);
  updateSortIndicators(_sortCol, _sortDir);
  renderHoldingsTable();
  renderPagination();
}

// ── 헤더 검색창 초기화 ───────────────────────────────────────────────────────

function initHeaderSearch() {
  const input = document.getElementById('header-search-input');
  if (input) input.value = '';
}

// ── 메인 진입점 ──────────────────────────────────────────────────────────────

async function init() {
  // URL 파라미터에서 CIK 추출
  const params = new URLSearchParams(window.location.search);
  const cik    = (params.get('cik') || '').trim();

  if (!cik) {
    hideLoading();
    showError('URL에 cik 파라미터가 없습니다. 검색 페이지로 돌아가세요.');
    return;
  }

  // JSON 데이터 로드
  let data;
  try {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    hideLoading();
    showError(`데이터를 불러오지 못했습니다: ${err.message}`);
    return;
  }

  // CIK로 기관 탐색 (앞 0 제거 후 비교)
  const normCIK = String(cik).replace(/^0+/, '');
  const inst = (data.institutions || []).find(i =>
    String(i.cik).replace(/^0+/, '') === normCIK
  );

  if (!inst) {
    hideLoading();
    showError(`CIK "${cik}"에 해당하는 기관을 찾을 수 없습니다.`);
    return;
  }

  const filings = inst.filings || [];

  if (filings.length === 0) {
    hideLoading();
    showError('해당 기관의 보고서 데이터가 없습니다.');
    return;
  }

  const latestFiling = filings[filings.length - 1];

  // 이전 분기 보유 종목 맵 생성 (전분기 대비 컬럼 계산에 사용)
  if (filings.length >= 2) {
    _prevHoldingsMap = buildHoldingsMap(filings[filings.length - 2].holdings);
  } else {
    _prevHoldingsMap = {};
  }

  // 각 섹션 렌더링
  renderHeader(inst, latestFiling);
  renderAUMChart(filings);
  renderSectorCharts(filings);
  renderChanges(filings);
  renderHoldingsSection(latestFiling);

  // 이벤트 바인딩
  initTabs();
  initSortableHeaders();
  initHeaderSearch();

  // 로딩 숨기고 콘텐츠 표시
  hideLoading();
  showContent();
}

// 페이지 로드 시 실행
init();
