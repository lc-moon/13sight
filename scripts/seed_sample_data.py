"""
seed_sample_data.py
-------------------
프론트엔드 테스트용 샘플 데이터를 SQLite DB에 삽입하고
data/institutions.json을 생성한다.

실제 EDGAR 수집 없이 웹 페이지를 테스트할 수 있게 한다.
- 5개 기관, 각 2개 분기 데이터
- 분기 간 차이: 신규매수 3종목, 완전매도 3종목, 비중변화 10종목 포함
"""

import os
import sys

# 상위 디렉토리를 모듈 경로에 추가
sys.path.insert(0, os.path.dirname(__file__))

import process_data

# 프로젝트 루트 경로
ROOT = os.path.join(os.path.dirname(__file__), '..')

# ── 샘플 기관 목록 ──────────────────────────────────────────────────────────
INSTITUTIONS = [
    {'cik': '0000102909', 'name_en': 'VANGUARD GROUP INC',                    'name_ko': '뱅가드 그룹'},
    {'cik': '0001364742', 'name_en': 'BlackRock, Inc.',                        'name_ko': '블랙록'},
    {'cik': '0000093751', 'name_en': 'STATE STREET CORP',                      'name_ko': '스테이트 스트리트'},
    {'cik': '0001067983', 'name_en': 'BERKSHIRE HATHAWAY INC',                 'name_ko': '버크셔 해서웨이'},
    {'cik': '0000884546', 'name_en': 'CHARLES SCHWAB INVESTMENT MANAGEMENT',   'name_ko': '찰스 슈왑 자산운용'},
]

# ── 섹터 매핑 ────────────────────────────────────────────────────────────────
SECTOR_MAP = {
    'AAPL': 'Technology',       'MSFT': 'Technology',
    'NVDA': 'Technology',       'AVGO': 'Technology',
    'CRM':  'Technology',       'ORCL': 'Technology',
    'AMZN': 'Consumer Discretionary', 'TSLA': 'Consumer Discretionary',
    'HD':   'Consumer Discretionary', 'COST': 'Consumer Discretionary',
    'GOOGL':'Communication Services', 'META': 'Communication Services',
    'NFLX': 'Communication Services',
    'JPM':  'Financials',       'V':    'Financials',
    'MA':   'Financials',       'BAC':  'Financials',
    'BRK':  'Financials',
    'UNH':  'Healthcare',       'JNJ':  'Healthcare',
    'ABBV': 'Healthcare',       'LLY':  'Healthcare',
    'TMO':  'Healthcare',       'PFE':  'Healthcare',
    'XOM':  'Energy',           'CVX':  'Energy',
    'PG':   'Consumer Staples', 'WMT':  'Consumer Staples',
    'KO':   'Consumer Staples', 'MCD':  'Consumer Staples',
}

# ── 종목 마스터 (28개, CUSIP은 가상의 8자리 코드 사용) ──────────────────────
# (name, ticker, cusip, sector)
STOCKS = [
    ('APPLE INC',               'AAPL',  '037833100', 'Technology'),
    ('MICROSOFT CORP',          'MSFT',  '594918104', 'Technology'),
    ('NVIDIA CORP',             'NVDA',  '67066G104', 'Technology'),
    ('BROADCOM INC',            'AVGO',  '11135F101', 'Technology'),
    ('SALESFORCE INC',          'CRM',   '79466L302', 'Technology'),
    ('ORACLE CORP',             'ORCL',  '68389X105', 'Technology'),
    ('AMAZON COM INC',          'AMZN',  '023135106', 'Consumer Discretionary'),
    ('TESLA INC',               'TSLA',  '88160R101', 'Consumer Discretionary'),
    ('HOME DEPOT INC',          'HD',    '437076102', 'Consumer Discretionary'),
    ('COSTCO WHOLESALE',        'COST',  '22160K105', 'Consumer Discretionary'),
    ('ALPHABET INC',            'GOOGL', '02079K305', 'Communication Services'),
    ('META PLATFORMS INC',      'META',  '30303M102', 'Communication Services'),
    ('NETFLIX INC',             'NFLX',  '64110L106', 'Communication Services'),
    ('JPMORGAN CHASE & CO',     'JPM',   '46625H100', 'Financials'),
    ('VISA INC',                'V',     '92826C839', 'Financials'),
    ('MASTERCARD INC',          'MA',    '57636Q104', 'Financials'),
    ('BANK OF AMERICA CORP',    'BAC',   '060505104', 'Financials'),
    ('BERKSHIRE HATHAWAY CL B', 'BRK.B', '084670702', 'Financials'),
    ('UNITEDHEALTH GROUP INC',  'UNH',   '91324P102', 'Healthcare'),
    ('JOHNSON & JOHNSON',       'JNJ',   '478160104', 'Healthcare'),
    ('ABBVIE INC',              'ABBV',  '00287Y109', 'Healthcare'),
    ('ELI LILLY & CO',          'LLY',   '532457108', 'Healthcare'),
    ('THERMO FISHER SCIENTIFIC','TMO',   '883556102', 'Healthcare'),
    ('PFIZER INC',              'PFE',   '717081103', 'Healthcare'),
    ('EXXON MOBIL CORP',        'XOM',   '30231G102', 'Energy'),
    ('CHEVRON CORP',            'CVX',   '166764100', 'Energy'),
    ('PROCTER & GAMBLE CO',     'PG',    '742718109', 'Consumer Staples'),
    ('WALMART INC',             'WMT',   '931142103', 'Consumer Staples'),
]

def make_holdings_for_period(total_aum_thousands: int, is_q2: bool) -> list:
    """
    분기별 보유 종목 목록을 생성한다.
    Q2와 Q3의 차이를 만들어 섹션3 탭 UI가 작동하도록 한다:
      - Q2 전용 종목 (Q3에서 완전매도): NFLX, ORCL, PFE  (인덱스 5, 12, 23)
      - Q3 전용 종목 (Q2에서 신규매수): COST, BRK.B, WMT (인덱스 9, 17, 27)
      - 공통 종목 22개: 나머지 (비중 변화 포함)
    """
    # Q2 전용 종목 인덱스
    q2_only = {5, 12, 23}    # ORCL, NFLX, PFE
    # Q3 전용 종목 인덱스
    q3_only = {9, 17, 27}    # COST, BRK.B, WMT

    selected = []
    for i, stock in enumerate(STOCKS):
        if is_q2 and i in q3_only:
            continue  # Q2에는 Q3 전용 종목 제외
        if not is_q2 and i in q2_only:
            continue  # Q3에는 Q2 전용 종목 제외
        selected.append((i, stock))

    # 비중 배분 (합계 = 100%)
    # 앞 5개 대형주에 많은 비중, 나머지는 균등 분배
    n = len(selected)
    weights = []
    for rank, (i, _) in enumerate(selected):
        if rank == 0:   base = 8.5
        elif rank == 1: base = 7.2
        elif rank == 2: base = 6.1
        elif rank == 3: base = 5.3
        elif rank == 4: base = 4.8
        else:           base = (100 - 8.5 - 7.2 - 6.1 - 5.3 - 4.8) / (n - 5)

        # Q3에서 일부 종목 비중 변화 (비중 증가/감소 Top10 테스트용)
        if not is_q2:
            # 비중 증가 그룹 (인덱스 0~4: AAPL, MSFT, NVDA, AVGO, CRM)
            if i in {0, 1, 2, 3, 4} and rank < 5:
                base *= 1.15  # 15% 증가
            # 비중 감소 그룹 (인덱스 6~10: AMZN, TSLA, HD, GOOGL, META)
            elif i in {6, 7, 8, 10, 11} and 5 <= rank < 12:
                base *= 0.85  # 15% 감소
        weights.append(base)

    # 합계를 100%로 정규화
    total_weight = sum(weights)
    weights = [w / total_weight * 100 for w in weights]

    holdings = []
    for (i, stock), weight in zip(selected, weights):
        name, ticker, cusip, sector = stock
        value = int(total_aum_thousands * weight / 100)
        # 주가 추정 (가상): value(천달러) / 주가(달러) = 주수
        # 적당한 주가를 사용해 주수를 계산
        price_map = {
            'AAPL': 185, 'MSFT': 415, 'NVDA': 875, 'AVGO': 1750, 'CRM': 310,
            'ORCL': 135, 'AMZN': 190, 'TSLA': 250, 'HD': 370, 'COST': 780,
            'GOOGL': 175, 'META': 545, 'NFLX': 675, 'JPM': 205, 'V': 280,
            'MA': 490, 'BAC': 42, 'BRK.B': 370, 'UNH': 520, 'JNJ': 155,
            'ABBV': 175, 'LLY': 860, 'TMO': 545, 'PFE': 28, 'XOM': 115,
            'CVX': 155, 'PG': 165, 'WMT': 95,
        }
        price = price_map.get(ticker, 100)
        shares = int(value * 1000 / price)  # value는 천달러이므로 *1000으로 달러 변환

        holdings.append({
            'name': name,
            'ticker': ticker,
            'cusip': cusip,
            'shares': shares,
            'value': value,
            'investment_type': 'SH',
            'sector': sector,
        })

    return holdings


def seed(db_path: str = None):
    """샘플 데이터를 DB에 삽입한다."""
    if db_path is None:
        db_path = process_data.DEFAULT_DB_PATH

    conn = process_data.get_db(db_path)

    # 분기 정의
    periods = [
        {'period': '2025-06-30', 'filed_date': '2025-08-14', 'is_q2': True},
        {'period': '2025-09-30', 'filed_date': '2025-11-14', 'is_q2': False},
    ]

    # AUM (천달러 단위)
    # 뱅가드 $7.4T → 7,400,000,000 (천달러)
    aum_map = {
        '0000102909': [7_100_000_000, 7_400_000_000],  # 뱅가드
        '0001364742': [5_800_000_000, 6_100_000_000],  # 블랙록
        '0000093751': [3_500_000_000, 3_700_000_000],  # 스테이트 스트리트
        '0001067983': [  290_000_000,   304_000_000],  # 버크셔 ($290B, $304B)
        '0000884546': [  450_000_000,   480_000_000],  # 찰스 슈왑 ($450B, $480B)
    }

    with conn:
        for inst in INSTITUTIONS:
            cik = inst['cik']
            process_data.upsert_institution(conn, cik, inst['name_en'], inst['name_ko'])

            for idx, p in enumerate(periods):
                total_aum = aum_map[cik][idx]
                filing_id = process_data.upsert_filing(
                    conn, cik, p['period'], p['filed_date'], total_aum
                )
                holdings = make_holdings_for_period(total_aum, p['is_q2'])
                process_data.replace_holdings(conn, filing_id, holdings)

    conn.close()
    print(f'샘플 데이터 삽입 완료: {len(INSTITUTIONS)}개 기관, 2개 분기')


if __name__ == '__main__':
    seed()

    # export_json.py를 import해서 바로 JSON도 생성
    import export_json
    output_path = os.path.join(ROOT, 'web', 'data', 'institutions.json')
    export_json.export(output_path=output_path)
    print(f'institutions.json 생성 완료: {output_path}')
