"""
fetch_edgar.py
--------------
SEC EDGAR에서 13F 데이터를 수집하는 스크립트.

수집 흐름:
  1. EDGAR 검색 API로 최근 분기(period) 목록 조회
  2. 각 분기의 13F-HR 제출 기관 목록 수집
  3. primary_doc.xml에서 총 AUM 파싱 → 상위 100개 선별
  4. 각 기관의 보유 종목 XML 파싱

주의:
  - 모든 HTTP 요청 후 0.5초 딜레이 (SEC Rate Limit 준수)
  - User-Agent 헤더 필수
  - 금액 단위: 모두 천 달러 (thousands USD)
"""

import sys
import time
import xml.etree.ElementTree as ET
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# SEC EDGAR API 기본 설정
EDGAR_BASE  = 'https://data.sec.gov'
EFTS_BASE   = 'https://efts.sec.gov'
USER_AGENT  = '13Sight contact@example.com'
REQUEST_DELAY = 0.5  # 초 (SEC Rate Limit 준수)

# 보유 종목 XML 네임스페이스
INFO_TABLE_NS = 'http://www.sec.gov/edgar/document/thirteenf/informationtable'

# 상위 N개 기관만 수집
TOP_N = 100

# EDGAR 검색에서 누락되더라도 반드시 포함할 기관 CIK 목록
MANDATORY_CIKS = [
    '0001067983',  # BERKSHIRE HATHAWAY INC
]


def get_session() -> requests.Session:
    """
    User-Agent와 재시도 설정이 포함된 HTTP 세션을 반환한다.
    SEC는 User-Agent 없으면 차단하므로 반드시 설정.
    """
    session = requests.Session()
    session.headers.update({'User-Agent': USER_AGENT, 'Accept-Encoding': 'gzip, deflate'})

    # 네트워크 오류 시 최대 3회 재시도 (지수 백오프)
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


def _get(session: requests.Session, url: str, **kwargs) -> requests.Response:
    """Rate Limit을 준수하며 GET 요청을 수행한다."""
    time.sleep(REQUEST_DELAY)
    resp = session.get(url, timeout=30, **kwargs)
    resp.raise_for_status()
    return resp


def get_latest_periods(session: requests.Session, n: int = 2) -> list[str]:
    """
    최근 n개 13F 보고 분기를 반환한다.
    방법1: EFTS 검색 API → 방법2(fallback): 뱅가드 submissions API
    반환 형식: ["2025-09-30", "2025-06-30"] (최신 → 오래된 순)
    """
    # 방법1: EFTS 검색 API
    try:
        periods = _get_periods_from_efts(session, n)
        if periods:
            return periods
        print('  EFTS 결과 없음, submissions API로 재시도...', file=sys.stderr)
    except Exception as e:
        print(f'  [경고] EFTS 조회 실패: {e} → submissions API로 재시도...', file=sys.stderr)

    # 방법2: 뱅가드(VANGUARD) submissions API (안정적 fallback)
    return _get_periods_from_submissions(session, n)


def _get_periods_from_efts(session: requests.Session, n: int) -> list[str]:
    """EFTS 검색 API로 최근 13F 분기를 조회한다."""
    url = f'{EFTS_BASE}/LATEST/search-index'
    params = {
        'q':     '13F-HR',      # 따옴표 없이 검색
        'forms': '13F-HR',
        'dateRange': 'custom',
        'startdt': '2024-01-01',
        'enddt':   '2099-12-31',
        'from':    0,
        'size':    100,
    }

    resp = _get(session, url, params=params)
    data = resp.json()

    periods = set()
    hits = data.get('hits', {}).get('hits', [])
    for hit in hits:
        src = hit.get('_source', {})
        # 가능한 필드명 모두 시도
        period = (src.get('period_of_report')
                  or src.get('periodOfReport')
                  or src.get('period'))
        if period:
            periods.add(period)

    return sorted(periods, reverse=True)[:n]


def _get_periods_from_submissions(session: requests.Session, n: int) -> list[str]:
    """
    뱅가드의 submissions API로 최근 13F 분기를 조회한다.
    EFTS가 실패할 때 사용하는 안정적인 fallback.
    """
    PROBE_CIK = '0000102909'  # VANGUARD GROUP INC
    url = f'{EDGAR_BASE}/submissions/CIK{PROBE_CIK}.json'

    resp = _get(session, url)
    data = resp.json()

    recent     = data.get('filings', {}).get('recent', {})
    form_types = recent.get('form', [])
    # 분기 종료일 필드명 후보
    period_dates = (recent.get('reportDate')
                    or recent.get('periodOfReport')
                    or [])

    periods = []
    seen    = set()
    for form, period in zip(form_types, period_dates):
        if form == '13F-HR' and period and period not in seen:
            seen.add(period)
            periods.append(period)
        if len(periods) >= n:
            break

    return periods


def discover_filers_for_period(session: requests.Session, period: str) -> list[dict]:
    """
    특정 분기에 13F-HR을 제출한 모든 기관 목록을 수집한다.
    반환: [{'cik': str, 'adsh': str, 'name': str}, ...]

    EDGAR EFTS 검색 API를 페이지네이션하며 순회한다.
    최대 200개 filer만 수집 (AUM 순위 결정용)
    """
    filers = []
    page_size = 100
    max_results = 200  # 너무 많으면 시간이 오래 걸림

    url = f'{EFTS_BASE}/LATEST/search-index'

    for offset in range(0, max_results, page_size):
        params = {
            'q':     '13F-HR',
            'forms': '13F-HR',
            'dateRange': 'custom',
            'startdt': _period_to_filing_window_start(period),
            'enddt':   _period_to_filing_window_end(period),
            'from':    offset,
            'size':    page_size,
        }

        try:
            resp = _get(session, url, params=params)
            data = resp.json()
        except Exception as e:
            print(f'  [경고] filer 목록 조회 실패 (offset={offset}): {e}', file=sys.stderr)
            break

        hits = data.get('hits', {}).get('hits', [])
        if not hits:
            break

        for hit in hits:
            src = hit.get('_source', {})
            cik = src.get('ciks', [''])[0] if src.get('ciks') else ''
            adsh = src.get('adsh', '')
            name = src.get('display_names', [''])[0] if src.get('display_names') else ''
            # 검색 결과에서 제출일 추출 (별도 API 호출 불필요)
            filed_date = (src.get('file_date')
                          or src.get('filed_at')
                          or src.get('filing_date')
                          or '')

            if cik and adsh:
                filers.append({
                    'cik':        cik.lstrip('0').zfill(10),
                    'adsh':       adsh,
                    'name':       name,
                    'filed_date': filed_date,
                })

        if len(hits) < page_size:
            break

    return filers


def _period_to_filing_window_start(period: str) -> str:
    """분기 종료일로부터 13F 제출 시작 가능 날짜를 추정한다 (분기 종료 후 45일)."""
    try:
        year  = int(period[:4])
        month = int(period[5:7])
        # 보고 기간 후 약 45일 뒤에 제출 시작
        # 단순하게 같은 분기 말에서 60일 후를 윈도우 중간으로 설정
        if month <= 3:   start_month, start_year = 4, year
        elif month <= 6: start_month, start_year = 7, year
        elif month <= 9: start_month, start_year = 10, year
        else:            start_month, start_year = 1, year + 1
        return f'{start_year}-{start_month:02d}-01'
    except (ValueError, IndexError):
        return '2024-01-01'


def _period_to_filing_window_end(period: str) -> str:
    """분기 제출 마감일을 추정한다 (분기 종료 후 90일)."""
    try:
        year  = int(period[:4])
        month = int(period[5:7])
        if month <= 3:   end_month, end_year = 6, year
        elif month <= 6: end_month, end_year = 9, year
        elif month <= 9: end_month, end_year = 12, year
        else:            end_month, end_year = 3, year + 1
        return f'{end_year}-{end_month:02d}-28'
    except (ValueError, IndexError):
        return '2099-12-31'


def get_aum_for_filer(session: requests.Session, cik: str, adsh: str) -> Optional[int]:
    """
    primary_doc.xml에서 총 AUM(tableValueTotal)을 파싱한다.
    반환: 천달러 단위 정수, 실패 시 None
    """
    # accession number에서 대시 제거 (아카이브 경로용)
    adsh_nodash = adsh.replace('-', '')
    cik_nodash  = cik.lstrip('0')

    url = (
        f'https://www.sec.gov/Archives/edgar/data/'
        f'{cik_nodash}/{adsh_nodash}/primary_doc.xml'
    )

    try:
        resp = _get(session, url)
        content = resp.content
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            try:
                from lxml import etree as lxml_et
                root = lxml_et.fromstring(content, lxml_et.XMLParser(recover=True))
            except Exception:
                return None
    except Exception as e:
        print(f'  [경고] primary_doc.xml 파싱 실패 ({cik}): {e}', file=sys.stderr)
        # primary_doc.xml 없으면 인덱스에서 다른 XML 시도
        return _get_aum_from_index(session, cik, adsh)

    # tableValueTotal 태그 검색 (네임스페이스 무관)
    for elem in root.iter():
        if elem.tag.endswith('tableValueTotal') and elem.text:
            try:
                val = int(elem.text.strip().replace(',', ''))
                if val > 0:
                    return val
            except ValueError:
                pass

    # tableValueTotal 없으면 인덱스에서 다른 XML 시도
    return _get_aum_from_index(session, cik, adsh)


def _get_aum_from_index(session: requests.Session, cik: str, adsh: str) -> Optional[int]:
    """인덱스 페이지에서 첫 번째 XML 파일을 읽어 AUM을 추출한다."""
    adsh_nodash = adsh.replace('-', '')
    cik_nodash  = cik.lstrip('0')
    base_url    = f'https://www.sec.gov/Archives/edgar/data/{cik_nodash}/{adsh_nodash}'
    index_url   = f'{base_url}/{adsh}-index.htm'
    try:
        resp = _get(session, index_url)
        import re
        xml_files = re.findall(r'href="([^"]+\.xml)"', resp.text, re.IGNORECASE)
        for fname in xml_files:
            if not fname.startswith('http'):
                fname = f'https://www.sec.gov{fname}' if fname.startswith('/') else f'{base_url}/{fname}'
            try:
                r2 = _get(session, fname)
                try:
                    root2 = ET.fromstring(r2.content)
                except ET.ParseError:
                    from lxml import etree as lxml_et
                    root2 = lxml_et.fromstring(r2.content, lxml_et.XMLParser(recover=True))
                for elem in root2.iter():
                    if elem.tag.endswith('tableValueTotal') and elem.text:
                        try:
                            val = int(elem.text.strip().replace(',', ''))
                            if val > 0:
                                return val
                        except ValueError:
                            pass
            except Exception:
                continue
    except Exception:
        pass
    return None


def _get_holdings_doc_url(session: requests.Session, cik: str, adsh: str) -> Optional[str]:
    """
    파일링 인덱스 페이지에서 보유 종목 XML 파일의 URL을 찾는다.
    INFORMATION TABLE을 포함하는 두 번째 XML 파일 탐색.
    """
    adsh_nodash = adsh.replace('-', '')
    cik_nodash  = cik.lstrip('0')
    base_url    = f'https://www.sec.gov/Archives/edgar/data/{cik_nodash}/{adsh_nodash}'

    # 인덱스 파일명은 대시 포함 형식 필요: XXXXXXXXXX-YY-NNNNNN
    if '-' in adsh:
        adsh_dashed = adsh
    else:
        adsh_dashed = f'{adsh_nodash[:10]}-{adsh_nodash[10:12]}-{adsh_nodash[12:]}'

    # 인덱스 HTML 파싱으로 XML 파일 목록 추출
    index_html_url = f'{base_url}/{adsh_dashed}-index.htm'
    try:
        resp = _get(session, index_html_url)
        # href에서 .xml 파일 경로 추출 (primary_doc.xml 제외)
        text = resp.text
        xml_files = []
        import re
        for match in re.finditer(r'href="([^"]+\.xml)"', text, re.IGNORECASE):
            fname = match.group(1)
            if 'primary_doc' not in fname.lower():
                xml_files.append(fname)

        # xslForm13F_X02 등 XSLT 변환 디렉토리 파일은 제외, 직접 경로 우선 선택
        direct_xml = [f for f in xml_files if '/' not in f.split('?')[0].lstrip('/').split('/', 3)[-1]]
        # 상대 경로가 단순 파일명인 것 (슬래시 없거나 1단계 경로만)
        preferred = []
        for f in xml_files:
            # xsl 변환 디렉토리 제외
            if 'xsl' in f.lower():
                continue
            preferred.append(f)

        candidates = preferred if preferred else xml_files
        if candidates:
            fname = candidates[0]
            # 상대 경로면 절대 경로로 변환
            if not fname.startswith('http'):
                if fname.startswith('/'):
                    fname = f'https://www.sec.gov{fname}'
                else:
                    fname = f'{base_url}/{fname}'
            return fname
    except Exception as e:
        print(f'  [경고] 인덱스 파싱 실패 ({cik}): {e}', file=sys.stderr)

    return None


def _build_ticker_map(session: requests.Session) -> dict[str, str]:
    """
    SEC의 company_tickers_exchange.json을 읽어
    {정규화된_회사명: ticker} 딕셔너리를 반환한다.
    """
    url = 'https://www.sec.gov/files/company_tickers_exchange.json'
    try:
        resp = _get(session, url)
        data = resp.json()
        # data 구조: {'fields': [...], 'data': [[cik, name, ticker, exchange], ...]}
        fields = data.get('fields', [])
        rows   = data.get('data', [])
        name_idx   = fields.index('name')   if 'name'   in fields else 1
        ticker_idx = fields.index('ticker') if 'ticker' in fields else 2

        ticker_map = {}
        for row in rows:
            name   = str(row[name_idx]).upper().strip()
            ticker = str(row[ticker_idx]).strip()
            if name and ticker:
                ticker_map[name] = ticker
        return ticker_map
    except Exception as e:
        print(f'  [경고] 티커 맵 로드 실패: {e}', file=sys.stderr)
        return {}


def _resolve_ticker(name: str, ticker_map: dict[str, str]) -> Optional[str]:
    """종목명으로 티커를 조회한다. 완전 일치 → 부분 일치 순서로 탐색."""
    import re
    normalized = re.sub(r'[^A-Z0-9 ]', '', name.upper()).strip()

    # 완전 일치
    if normalized in ticker_map:
        return ticker_map[normalized]

    # 짧은 접두사로 부분 일치 (최소 5글자)
    if len(normalized) >= 5:
        for key, ticker in ticker_map.items():
            if key.startswith(normalized[:min(len(normalized), 20)]):
                return ticker

    return None


def get_holdings_for_filer(session: requests.Session, cik: str, adsh: str,
                           ticker_map: dict) -> list[dict]:
    """
    보유 종목 XML(Information Table)을 파싱하여 종목 목록을 반환한다.

    반환: [
      {
        'name': str, 'ticker': str|None, 'cusip': str,
        'shares': int, 'value': int,  # value: 천달러
        'investment_type': str, 'sector': str
      },
      ...
    ]
    """
    holdings_url = _get_holdings_doc_url(session, cik, adsh)
    if not holdings_url:
        return []

    try:
        resp = _get(session, holdings_url)
        content = resp.content
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            # 불규칙한 XML은 lxml의 recover 모드로 직접 사용
            try:
                from lxml import etree as lxml_et
                root = lxml_et.fromstring(content, lxml_et.XMLParser(recover=True))
            except Exception as e2:
                print(f'  [경고] holdings XML 파싱 실패 ({cik}): {e2}', file=sys.stderr)
                return []
    except Exception as e:
        print(f'  [경고] holdings XML 파싱 실패 ({cik}): {e}', file=sys.stderr)
        return []

    # 실제 XML에서 네임스페이스를 동적으로 감지한다
    raw_tag = root.tag  # 예: '{http://www.sec.gov/...}informationTable' 또는 'informationTable'
    detected_ns = ''
    if raw_tag.startswith('{'):
        detected_ns = raw_tag[1:raw_tag.index('}')]

    def _find_all_tables(node):
        """네임스페이스에 관계없이 infoTable 요소를 재귀 탐색한다."""
        candidates = []
        for ns_uri in ([detected_ns, INFO_TABLE_NS] if detected_ns else [INFO_TABLE_NS, '']):
            tag = f'{{{ns_uri}}}infoTable' if ns_uri else 'infoTable'
            candidates = node.findall(f'.//{tag}')
            if candidates:
                return candidates, ns_uri
        return [], ''

    info_tables, active_ns = _find_all_tables(root)

    def _find_text(node, tag: str) -> str:
        """네임스페이스 포함/미포함으로 태그 텍스트를 재귀 조회한다."""
        full_tag = f'{{{active_ns}}}{tag}' if active_ns else tag
        el = node.find(f'.//{full_tag}')
        if el is None:
            el = node.find(f'.//{tag}')
        return (el.text or '').strip() if el is not None else ''

    holdings = []
    for item in info_tables:
        name      = _find_text(item, 'nameOfIssuer')
        cusip     = _find_text(item, 'cusip')
        value_str = _find_text(item, 'value')

        # shrsOrPrnAmt 하위의 sshPrnamt 탐색
        shares_str = _find_text(item, 'sshPrnamt')
        inv_type   = _find_text(item, 'sshPrnamtType') or 'SH'

        # 수량/금액 파싱
        try:
            shares = int(shares_str.replace(',', ''))
        except (ValueError, AttributeError):
            shares = 0
        try:
            value = int(value_str.replace(',', ''))
        except (ValueError, AttributeError):
            value = 0

        if not name and not cusip:
            continue  # 파싱 실패 레코드 건너뜀

        # 티커 조회
        ticker = _resolve_ticker(name, ticker_map) if ticker_map else None

        holdings.append({
            'name':            name,
            'ticker':          ticker,
            'cusip':           cusip,
            'shares':          shares,
            'value':           value,
            'investment_type': inv_type[:2] if inv_type else 'SH',
            'sector':          'Unknown',
        })

    # 평가금액 내림차순 정렬
    holdings.sort(key=lambda x: x['value'], reverse=True)
    return holdings


def fetch_all(session: requests.Session, periods: list[str]) -> dict:
    """
    최신 분기 AUM 기준 상위 TOP_N 기관을 먼저 선별한 뒤,
    해당 기관들의 모든 요청 분기 데이터를 수집한다.

    흐름:
      Step 1. 최신 분기 EFTS 검색 → AUM 조회 → 상위 TOP_N CIK 목록 확정
      Step 2. 확정된 CIK 목록으로 각 분기 submissions API 직접 조회 → holdings 수집

    반환:
    {
      period: {
        cik: {
          'name_en': str, 'filed_date': str,
          'total_aum': int,  # 천달러
          'holdings': [...]
        }
      }
    }
    """
    print('티커 맵 로드 중...', file=sys.stderr)
    ticker_map = _build_ticker_map(session)
    print(f'  → {len(ticker_map)}개 종목 로드됨', file=sys.stderr)

    # ── Step 1: 최신 분기 기준 상위 TOP_N 기관 선별 ──────────────────────
    latest_period = periods[0]
    print(f'\n[Step 1] {latest_period} 기준 상위 {TOP_N}개 기관 선별 중...', file=sys.stderr)

    filers = discover_filers_for_period(session, latest_period)
    print(f'  → {len(filers)}개 기관 발견', file=sys.stderr)

    aum_data = []
    for i, filer in enumerate(filers):
        print(
            f'  AUM 조회 중... [{i+1}/{len(filers)}] {filer["name"][:40]}',
            file=sys.stderr, end='\r'
        )
        aum = get_aum_for_filer(session, filer['cik'], filer['adsh'])
        if aum is not None:
            aum_data.append({**filer, 'aum': aum})

    print(f'\n  → AUM 조회 완료: {len(aum_data)}개 기관', file=sys.stderr)

    # MANDATORY_CIKS: EFTS 검색에서 누락될 수 있는 중요 기관 강제 포함
    for must_cik in MANDATORY_CIKS:
        if not any(f['cik'] == must_cik for f in aum_data):
            print(f'  [필수] {must_cik} 강제 포함 시도...', file=sys.stderr)
            filer_info = _get_mandatory_filer(session, must_cik, latest_period)
            if filer_info:
                aum = get_aum_for_filer(session, must_cik, filer_info['adsh'])
                if aum is not None:
                    aum_data.append({**filer_info, 'aum': aum})
                    print(f'  → {filer_info["name"]} 추가 완료', file=sys.stderr)

    aum_data.sort(key=lambda x: x['aum'], reverse=True)
    top_ciks  = [f['cik']  for f in aum_data[:TOP_N]]
    top_names = {f['cik']: f['name'] for f in aum_data[:TOP_N]}
    print(f'  → 상위 {len(top_ciks)}개 기관 확정', file=sys.stderr)

    # ── Step 2: 각 분기 데이터 수집 (submissions API 직접 조회) ──────────
    result = {}

    for period in periods:
        print(f'\n[Step 2] {period} 데이터 수집 중... ({len(top_ciks)}개 기관)', file=sys.stderr)
        period_result = {}

        for i, cik in enumerate(top_ciks):
            name = top_names.get(cik, cik)
            print(
                f'  [{i+1}/{len(top_ciks)}] {name[:40]}',
                file=sys.stderr, end='\r'
            )

            # submissions API로 해당 분기 13F-HR 제출 정보 조회
            filer_info = _get_mandatory_filer(session, cik, period)
            if filer_info is None:
                continue  # 해당 분기 미제출

            aum = get_aum_for_filer(session, cik, filer_info['adsh'])
            holdings = get_holdings_for_filer(
                session, cik, filer_info['adsh'], ticker_map
            )

            period_result[cik] = {
                'name_en':    filer_info['name'],
                'filed_date': filer_info['filed_date'],
                'total_aum':  aum or 0,
                'holdings':   holdings,
            }

        print(f'\n  → {period} 수집 완료: {len(period_result)}개 기관', file=sys.stderr)
        result[period] = period_result

    return result


def _get_mandatory_filer(session: requests.Session, cik: str, period: str) -> Optional[dict]:
    """
    특정 CIK의 특정 분기 13F-HR 제출 정보를 submissions API에서 직접 조회한다.
    MANDATORY_CIKS에 포함된 기관이 EDGAR 검색에서 누락된 경우 사용한다.
    """
    url = f'{EDGAR_BASE}/submissions/CIK{cik}.json'
    try:
        resp = _get(session, url)
        data = resp.json()
        name    = data.get('name', cik)
        recent  = data.get('filings', {}).get('recent', {})
        forms        = recent.get('form', [])
        accessions   = recent.get('accessionNumber', [])
        report_dates = recent.get('reportDate', [])
        filed_dates  = recent.get('filingDate', [])

        for form, acc, rdate, fdate in zip(forms, accessions, report_dates, filed_dates):
            if form == '13F-HR' and rdate == period:
                return {
                    'cik':        cik,
                    'adsh':       acc,  # 대시 포함 형식 유지 (인덱스 URL 구성에 필요)
                    'name':       name,
                    'filed_date': fdate,
                }
    except Exception as e:
        print(f'  [경고] {cik} 강제 포함 조회 실패: {e}', file=sys.stderr)
    return None


def _get_filed_date(session: requests.Session, cik: str, adsh: str) -> Optional[str]:
    """submissions API에서 특정 accession number의 제출일을 조회한다."""
    url = f'{EDGAR_BASE}/submissions/CIK{cik}.json'
    try:
        resp = _get(session, url)
        data = resp.json()
        filings = data.get('filings', {}).get('recent', {})
        accessions = filings.get('accessionNumber', [])
        dates      = filings.get('filedAt', filings.get('filedDate', []))

        for i, acc in enumerate(accessions):
            if acc.replace('-', '') == adsh.replace('-', ''):
                return dates[i] if i < len(dates) else None
    except Exception:
        pass
    return None


if __name__ == '__main__':
    # 단독 실행 테스트
    session = get_session()
    print('최근 분기 조회 중...')
    periods = get_latest_periods(session, n=2)
    print(f'최근 분기: {periods}')
