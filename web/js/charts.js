/**
 * charts.js
 * Chart.js 차트 생성 팩토리 함수 모음
 *
 * 허용 컬러 팔레트:
 *   #112D4E (primary-dark), #3F72AF (primary)
 *   + 명도 변형으로 10가지 섹터 색상 생성
 */

// ── 섹터 차트용 색상 팔레트 (10색) ───────────────────────────────────────────
const SECTOR_COLORS = [
  '#3F72AF',  // primary
  '#112D4E',  // primary-dark
  '#5B93C8',  // 밝은 블루
  '#2D5F8A',  // 중간 네이비
  '#7EB3D8',  // 연한 블루
  '#1A3D60',  // 진한 네이비
  '#4E84BB',  // 중간 블루
  '#8BBFDD',  // 매우 연한 블루
  '#264D73',  // 어두운 블루
  '#A5CDE8',  // 가장 연한 블루
];

// 기존 차트 인스턴스를 저장 (중복 생성 방지)
const _chartInstances = {};

/**
 * 기존 차트를 파괴하고 새 인스턴스를 등록한다
 */
function _destroyIfExists(canvasId) {
  if (_chartInstances[canvasId]) {
    _chartInstances[canvasId].destroy();
    delete _chartInstances[canvasId];
  }
}

/**
 * AUM 추이 막대 차트를 생성한다.
 *
 * @param {string} canvasId - 렌더링할 canvas 요소의 id
 * @param {string[]} labels - X축 레이블 배열 (예: ["2025 Q2", "2025 Q3"])
 * @param {number[]} values - AUM 값 배열 (단위: 천달러)
 */
function createAUMChart(canvasId, labels, values) {
  _destroyIfExists(canvasId);

  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  // 천달러 → 억달러 변환: 1억달러 = 100,000천달러
  const valuesInHundredMillion = values.map(v => +(v / 100000).toFixed(1));

  const chart = new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label: 'AUM (억달러)',
        data: valuesInHundredMillion,
        backgroundColor: '#3F72AF',
        borderColor: '#2D5F8A',
        borderWidth: 1,
        borderRadius: 4,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            // 툴팁에 원래 AUM을 읽기 쉬운 형식으로 표시
            label: (ctx) => {
              const originalVal = values[ctx.dataIndex];
              return ` ${formatAUMChart(originalVal)}`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            font: { family: "'Inter', sans-serif", size: 12 },
            color: '#333',
          },
        },
        y: {
          beginAtZero: false,
          grid: { color: 'rgba(17,45,78,0.06)' },
          ticks: {
            font: { family: "'Inter', sans-serif", size: 11 },
            color: '#555',
            callback: (val) => {
              // 억달러 단위로 표시
              if (val >= 10000) return `${(val / 10000).toFixed(1)}조`;
              return `${val.toLocaleString()}억`;
            },
          },
        },
      },
    },
  });

  _chartInstances[canvasId] = chart;
  return chart;
}

/**
 * 섹터 배분 도넛 차트를 생성한다.
 *
 * @param {string} canvasId - 렌더링할 canvas 요소의 id
 * @param {Object} sectorData - {섹터명: 비중(%)} 형태의 객체
 */
function createSectorDonut(canvasId, sectorData) {
  _destroyIfExists(canvasId);

  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const labels = Object.keys(sectorData);
  const values = Object.values(sectorData);

  // 섹터 수에 맞춰 색상 배열 생성 (순환)
  const colors = labels.map((_, i) => SECTOR_COLORS[i % SECTOR_COLORS.length]);

  const chart = new Chart(canvas, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data: values,
        backgroundColor: colors,
        borderColor: '#ffffff',
        borderWidth: 2,
        hoverBorderWidth: 3,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '60%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: {
            font: { family: "'Inter', sans-serif", size: 11 },
            color: '#333',
            padding: 10,
            boxWidth: 12,
            usePointStyle: true,
            pointStyleWidth: 10,
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => ` ${ctx.label}: ${ctx.parsed.toFixed(1)}%`,
          },
        },
      },
    },
  });

  _chartInstances[canvasId] = chart;
  return chart;
}

/**
 * AUM 값(천달러)을 읽기 쉬운 형식으로 변환한다.
 * 차트 툴팁 전용 (institution.js의 formatAUM과 동일 로직)
 */
function formatAUMChart(valueInThousands) {
  const usd = valueInThousands * 1000;
  if (usd >= 1e12) return `$${(usd / 1e12).toFixed(2)}T`;
  if (usd >= 1e9)  return `$${(usd / 1e9).toFixed(1)}B`;
  if (usd >= 1e6)  return `$${(usd / 1e6).toFixed(0)}M`;
  return `$${usd.toLocaleString()}`;
}
