# 13Sight

미국 기관 투자자들의 SEC 13F 보고서를 수집·분석·시각화하는 정적 웹사이트.

상위 100개 기관 투자자의 포트폴리오를 분기별로 추적하고,
AUM 추이·섹터 배분·종목 변화를 시각적으로 확인할 수 있습니다.

---

## 프로젝트 구조

```
13sight/
├── .github/
│   └── workflows/
│       └── update_data.yml        # GitHub Actions 자동화 (매일 UTC 00:00 실행)
├── data/
│   └── institutions.json          # Python이 생성하는 최종 JSON 데이터
├── scripts/
│   ├── fetch_edgar.py             # EDGAR에서 13F 데이터 수집
│   ├── process_data.py            # SQLite 저장 및 가공
│   ├── export_json.py             # JSON 파일 내보내기
│   ├── translate_names.py         # 기관명 한글 번역
│   ├── seed_sample_data.py        # 테스트용 샘플 데이터 삽입
│   └── main.py                    # 파이프라인 진입점
├── db/
│   └── 13sight.db                 # SQLite DB (gitignore 처리)
├── web/
│   ├── index.html                 # 메인 페이지 (검색)
│   ├── search.html                # 검색 결과 페이지
│   ├── institution.html           # 기관 분석 페이지
│   ├── css/
│   │   └── style.css
│   └── js/
│       ├── search.js
│       ├── institution.js
│       └── charts.js
└── requirements.txt
```

---

## 설치 방법

### 요구사항

- Python 3.11 이상
- (선택) 번역 API 키: Google Cloud Translation 또는 DeepL

### 1. 저장소 클론

```bash
git clone https://github.com/your-username/13sight.git
cd 13sight
```

### 2. 가상환경 생성 및 패키지 설치

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## 실행 방법

### 샘플 데이터로 바로 테스트 (권장)

EDGAR API 호출 없이 샘플 데이터로 웹 페이지를 즉시 확인합니다.

```bash
python scripts/seed_sample_data.py
```

실행 후 `data/institutions.json`이 생성됩니다.
`web/index.html`을 브라우저에서 열어 확인하세요.

> **Note**: `fetch` API 사용으로 인해 로컬에서는 간단한 HTTP 서버가 필요합니다.
> ```bash
> cd web
> python -m http.server 8000
> # http://localhost:8000 접속
> ```

### 실제 EDGAR 데이터 수집

```bash
python scripts/main.py
```

- 새 분기 데이터가 있으면 수집 후 `data/institutions.json` 업데이트 → `UPDATED` 출력
- 이미 최신 데이터면 `NO_UPDATE` 출력 후 종료

### 개별 스크립트 실행

```bash
# 1. EDGAR 데이터 수집 (단독 실행 테스트)
python scripts/fetch_edgar.py

# 2. DB 스키마 생성만
python scripts/process_data.py

# 3. DB → JSON 내보내기
python scripts/export_json.py

# 4. 기관명 한글 번역 (API 키 없으면 사전 기반으로만 동작)
TRANSLATE_API_KEY=your_key python scripts/translate_names.py
```

---

## 번역 API 설정 (선택)

기관명 한글 번역을 위해 API 키를 설정할 수 있습니다.
API 키가 없어도 50개 이상의 주요 기관은 내장 사전으로 번역됩니다.

### Google Cloud Translation

```bash
export TRANSLATE_API_KEY="your-google-api-key"
```

### DeepL

```bash
export TRANSLATE_API_KEY="your-deepl-auth-key"  # UUID 형식이면 자동 감지
```

---

## GitHub Actions 자동화

`.github/workflows/update_data.yml`이 매일 UTC 00:00 (KST 09:00)에 실행됩니다.

### 설정 방법

1. GitHub 저장소 Settings → Secrets and variables → Actions
2. `TRANSLATE_API_KEY` 시크릿 추가 (번역 API 키, 선택)
3. GitHub Pages를 `main` 브랜치 `/web` 폴더(또는 루트)로 설정

### 자동화 흐름

```
매일 09:00 KST
  → main.py 실행
  → UPDATED: data/institutions.json 커밋 & 푸시
  → NO_UPDATE: 종료
```

---

## 웹 페이지 기능

| 페이지 | 설명 |
|--------|------|
| `index.html` | 기관명·CIK로 검색 |
| `search.html` | 검색 결과 표시, 단일 결과 시 자동 이동 |
| `institution.html` | AUM 추이·섹터 배분·분기 변화·보유 종목 전체 |

### institution.html 주요 기능

- **AUM 추이**: 분기별 운용자산 막대 차트
- **섹터 배분**: 이전/최신 분기 도넛 차트 비교
- **분기 간 변화**: 신규매수 / 완전매도 / 비중증가 Top10 / 비중감소 Top10 탭
- **보유 종목**: 컬럼 정렬, 20개씩 페이지네이션, 전분기 대비 표시

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| 데이터 수집/가공 | Python 3.11 |
| 데이터 저장 | SQLite |
| 프론트엔드 | HTML + CSS + Vanilla JS |
| 차트 | Chart.js 4.x (CDN) |
| 배포 | GitHub Pages |
| 자동화 | GitHub Actions |

---

## 라이선스

MIT License
