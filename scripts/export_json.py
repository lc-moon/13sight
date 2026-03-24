"""
export_json.py
--------------
SQLite DB에서 데이터를 읽어 웹에서 사용할 data/institutions.json을 생성한다.

모든 금액은 DB에서 천달러(thousands USD) 단위로 읽으며,
JSON에도 그대로 저장한다. 화면 표시 변환은 JavaScript에서 수행한다.
"""

import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import process_data

# 기본 출력 경로 (web/data/ 하위 — 브라우저에서 직접 접근 가능)
DEFAULT_OUTPUT = os.path.join(
    os.path.dirname(__file__), '..', 'web', 'data', 'institutions.json'
)


def _period_label(period_str: str) -> str:
    """
    "2025-09-30" 형식을 "2025 Q3" 형식으로 변환한다.
    월 기준: Q1=03, Q2=06, Q3=09, Q4=12
    """
    try:
        month = int(period_str[5:7])
        year = period_str[:4]
        quarter = {3: 'Q1', 6: 'Q2', 9: 'Q3', 12: 'Q4'}.get(month, '?')
        return f'{year} {quarter}'
    except (IndexError, ValueError):
        return period_str


def export(db_path: str = None, output_path: str = DEFAULT_OUTPUT):
    """
    DB 데이터를 읽어 institutions.json을 생성한다.

    JSON 구조:
    {
      "last_updated": "2025-11-14",
      "institutions": [
        {
          "cik": "...", "name_en": "...", "name_ko": "...",
          "filings": [
            {
              "period": "2025-09-30",
              "period_label": "2025 Q3",
              "filed_date": "...",
              "total_aum": 7400000000,
              "holdings": [{...}],
              "sector_breakdown": {"Technology": 32.5, ...}
            }
          ]
        }
      ]
    }
    """
    if db_path is None:
        db_path = process_data.DEFAULT_DB_PATH

    conn = process_data.get_db(db_path)

    # 1. 기관 목록 조회 (최신 AUM 내림차순 정렬)
    institutions_rows = conn.execute("""
        SELECT i.cik, i.name_en, i.name_ko
        FROM institutions i
        JOIN (
            SELECT cik, MAX(total_aum) AS max_aum
            FROM filings
            GROUP BY cik
        ) f ON i.cik = f.cik
        ORDER BY f.max_aum DESC
    """).fetchall()

    institutions_out = []

    for inst_row in institutions_rows:
        cik = inst_row['cik']

        # 2. 해당 기관의 분기별 보고서 조회 (오래된 것 → 최신 순서)
        filing_rows = conn.execute("""
            SELECT id, period, filed_date, total_aum
            FROM filings
            WHERE cik = ?
            ORDER BY period ASC
        """, (cik,)).fetchall()

        filings_out = []

        for f_row in filing_rows:
            filing_id  = f_row['id']
            total_aum  = f_row['total_aum']  # 천달러 단위

            # 3. 보유 종목 조회 (평가금액 내림차순)
            holding_rows = conn.execute("""
                SELECT name, ticker, cusip, shares, value, investment_type, sector
                FROM holdings
                WHERE filing_id = ?
                ORDER BY value DESC
            """, (filing_id,)).fetchall()

            # 섹터별 합계 계산 (비중 %)
            sector_totals: dict[str, int] = {}
            holdings_out = []

            for h in holding_rows:
                # 개별 종목 비중 계산
                weight_pct = round(h['value'] / total_aum * 100, 2) if total_aum else 0.0

                holdings_out.append({
                    'name':            h['name'],
                    'ticker':          h['ticker'],
                    'cusip':           h['cusip'],
                    'shares':          h['shares'],
                    'value':           h['value'],
                    'investment_type': h['investment_type'],
                    'weight_pct':      weight_pct,
                    'sector':          h['sector'],
                })

                # 섹터 합계 누적
                sector = h['sector'] or 'Unknown'
                sector_totals[sector] = sector_totals.get(sector, 0) + h['value']

            # 섹터 비중(%) 계산 및 정렬 (비중 내림차순)
            sector_breakdown = {}
            if total_aum:
                sorted_sectors = sorted(
                    sector_totals.items(), key=lambda x: x[1], reverse=True
                )
                for sector, val in sorted_sectors:
                    sector_breakdown[sector] = round(val / total_aum * 100, 2)

            filings_out.append({
                'period':           f_row['period'],
                'period_label':     _period_label(f_row['period']),
                'filed_date':       f_row['filed_date'],
                'total_aum':        total_aum,
                'holdings':         holdings_out,
                'sector_breakdown': sector_breakdown,
            })

        institutions_out.append({
            'cik':     cik,
            'name_en': inst_row['name_en'],
            'name_ko': inst_row['name_ko'],
            'filings': filings_out,
        })

    conn.close()

    # 출력 디렉토리 생성
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

    # JSON 파일 저장
    result = {
        'last_updated': datetime.utcnow().strftime('%Y-%m-%d'),
        'institutions': institutions_out,
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total_institutions = len(institutions_out)
    total_filings = sum(len(i['filings']) for i in institutions_out)
    total_holdings = sum(
        len(fi['holdings']) for i in institutions_out for fi in i['filings']
    )
    print(
        f'JSON 내보내기 완료: {total_institutions}개 기관, '
        f'{total_filings}개 보고서, {total_holdings}개 종목 → {output_path}'
    )


if __name__ == '__main__':
    export()
