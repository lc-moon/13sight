/**
 * search.js
 * 검색 결과 페이지 로직
 *
 * 동작 흐름:
 * 1. URL 파라미터 q 값을 읽는다
 * 2. data/institutions.json을 fetch한다
 * 3. name_en, name_ko, cik 필드와 대소문자 무관 비교
 * 4. 일치하는 기관이 있으면 institution.html?cik=...로 이동
 * 5. 없으면 안내 메시지를 표시한다
 */

// JSON 데이터 경로 (web/data/ 하위에 위치)
const DATA_URL = 'data/institutions.json';

/**
 * 헤더 검색창에 현재 검색어를 채운다
 */
function populateHeaderSearch(query) {
  const input = document.getElementById('header-search-input');
  if (input) input.value = query;
}

/**
 * "결과 없음" 메시지를 렌더링한다
 */
function showNoResult(query, container) {
  container.innerHTML = `
    <div class="no-result-box">
      <h2>검색 결과가 없습니다</h2>
      <p>
        '<strong>${escapeHtml(query)}</strong>'에 대한 검색 결과가 없습니다.<br/>
        상위 100개 기관의 영어명, 한글명, 또는 CIK 번호로 검색해주세요.
      </p>
    </div>
  `;
}

/**
 * 에러 메시지를 렌더링한다
 */
function showError(msg, container) {
  container.innerHTML = `
    <div class="no-result-box">
      <h2>오류가 발생했습니다</h2>
      <p>${escapeHtml(msg)}</p>
    </div>
  `;
}

/**
 * XSS 방지용 HTML 이스케이프
 */
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/**
 * CIK 정규화: 앞 0을 제거한 숫자 문자열 반환
 */
function normalizeCIK(cik) {
  return String(cik).replace(/^0+/, '');
}

/**
 * 메인 검색 실행 함수
 */
async function runSearch() {
  const container = document.getElementById('search-container');
  if (!container) return;

  // URL 파라미터에서 검색어 추출
  const params = new URLSearchParams(window.location.search);
  const query  = (params.get('q') || '').trim();

  // 헤더 검색창에 현재 검색어 표시
  populateHeaderSearch(query);

  // 검색어가 없으면 안내 메시지
  if (!query) {
    showNoResult('', container);
    container.querySelector('.no-result-box h2').textContent = '검색어를 입력하세요';
    container.querySelector('.no-result-box p').textContent =
      '기관명(영문/한글) 또는 CIK 번호로 검색할 수 있습니다.';
    return;
  }

  // JSON 데이터 로드
  let data;
  try {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    showError(`데이터를 불러오지 못했습니다: ${err.message}`, container);
    return;
  }

  const institutions = data.institutions || [];
  const qLower       = query.toLowerCase();
  const qCIK         = normalizeCIK(query);

  // 검색 조건:
  // - 영문명 부분 일치 (대소문자 무관)
  // - 한글명 부분 일치
  // - CIK 완전 일치 (앞 0 제거 후 비교)
  const matches = institutions.filter(inst => {
    const nameEnMatch = inst.name_en && inst.name_en.toLowerCase().includes(qLower);
    const nameKoMatch = inst.name_ko && inst.name_ko.includes(query);
    const cikMatch    = normalizeCIK(inst.cik) === qCIK;
    return nameEnMatch || nameKoMatch || cikMatch;
  });

  if (matches.length === 0) {
    // 결과 없음
    showNoResult(query, container);
    return;
  }

  if (matches.length === 1) {
    // 단일 결과 → 바로 기관 분석 페이지로 이동
    window.location.href = `institution.html?cik=${encodeURIComponent(matches[0].cik)}`;
    return;
  }

  // 복수 결과 → 목록 표시 (가장 많은 AUM 기준 상위 표시)
  renderResultList(matches, query, container);
}

/**
 * 복수 검색 결과 목록을 렌더링한다
 */
function renderResultList(institutions, query, container) {
  const items = institutions.map(inst => {
    // 최신 분기 AUM 가져오기
    const latestFiling = inst.filings && inst.filings[inst.filings.length - 1];
    const aum = latestFiling ? formatAUM(latestFiling.total_aum) : '-';

    return `
      <div class="result-item"
           onclick="location.href='institution.html?cik=${encodeURIComponent(inst.cik)}'"
           role="link" tabindex="0"
           onkeydown="if(event.key==='Enter')location.href='institution.html?cik=${encodeURIComponent(inst.cik)}'">
        <div>
          <div style="font-weight:600; color:var(--color-primary-dark); margin-bottom:2px;">
            ${escapeHtml(inst.name_en)}
          </div>
          ${inst.name_ko ? `<div style="font-size:0.85rem; color:#555;">${escapeHtml(inst.name_ko)}</div>` : ''}
        </div>
        <div style="text-align:right; flex-shrink:0; margin-left:16px;">
          <div style="font-size:0.9rem; font-weight:600; color:var(--color-primary);">${aum}</div>
          <div style="font-size:0.75rem; color:#888;">CIK ${escapeHtml(inst.cik)}</div>
        </div>
      </div>
    `;
  }).join('');

  container.innerHTML = `
    <div class="search-results">
      <p style="margin-bottom:16px; font-size:0.9rem; color:#555;">
        '<strong>${escapeHtml(query)}</strong>' 검색 결과 ${institutions.length}건
      </p>
      ${items}
    </div>
  `;
}

/**
 * AUM 값(천달러)을 읽기 쉬운 형식으로 변환한다
 * 예: 7400000000 → "$7.40T"
 */
function formatAUM(valueInThousands) {
  const usd = valueInThousands * 1000;
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(2)}T`;
  if (usd >= 1e9)  return `$${(usd / 1e9).toFixed(1)}B`;
  if (usd >= 1e6)  return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toLocaleString()}`;
}

// 페이지 로드 시 검색 실행
runSearch();
