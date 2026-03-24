"""
process_data.py
---------------
SQLite 데이터베이스 스키마 생성 및 데이터 저장/갱신 함수 모음.
모든 금액은 천 달러(thousands USD) 단위로 저장한다.
"""

import os
import sqlite3
from datetime import datetime

# 데이터베이스 파일 기본 경로
DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'db', '13sight.db')


def get_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    """
    SQLite 연결을 반환한다.
    - db 디렉토리가 없으면 자동 생성 (GitHub Actions 환경 대응)
    - WAL 모드로 동시성 향상
    - 스키마가 없으면 자동 생성
    """
    # db 디렉토리 자동 생성
    db_dir = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # 컬럼명으로 접근 가능하게 설정
    conn.execute('PRAGMA journal_mode=WAL')  # WAL 모드 활성화
    conn.execute('PRAGMA foreign_keys=ON')   # 외래키 제약 활성화

    _create_schema(conn)
    return conn


def _create_schema(conn: sqlite3.Connection):
    """데이터베이스 테이블 스키마를 생성한다."""
    conn.executescript("""
        -- 기관 정보 테이블
        CREATE TABLE IF NOT EXISTS institutions (
            cik          TEXT PRIMARY KEY,
            name_en      TEXT NOT NULL,
            name_ko      TEXT,
            last_updated TEXT NOT NULL
        );

        -- 13F 보고서 테이블
        -- period: "2025-09-30" 형식의 보고 기간 종료일
        -- total_aum: 단위 천 달러 (thousands USD)
        CREATE TABLE IF NOT EXISTS filings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            cik         TEXT    NOT NULL REFERENCES institutions(cik),
            period      TEXT    NOT NULL,
            filed_date  TEXT    NOT NULL,
            total_aum   INTEGER NOT NULL,
            UNIQUE(cik, period)
        );

        -- 보유 종목 테이블
        -- value: 단위 천 달러 (thousands USD)
        -- shares: 보유 주수
        CREATE TABLE IF NOT EXISTS holdings (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            filing_id        INTEGER NOT NULL REFERENCES filings(id),
            name             TEXT    NOT NULL,
            ticker           TEXT,
            cusip            TEXT    NOT NULL,
            shares           INTEGER NOT NULL,
            value            INTEGER NOT NULL,
            investment_type  TEXT    NOT NULL DEFAULT 'SH',
            sector           TEXT    NOT NULL DEFAULT 'Unknown'
        );

        -- 조회 성능을 위한 인덱스
        CREATE INDEX IF NOT EXISTS idx_holdings_filing ON holdings(filing_id);
        CREATE INDEX IF NOT EXISTS idx_filings_cik     ON filings(cik);
    """)
    conn.commit()


def upsert_institution(conn: sqlite3.Connection, cik: str, name_en: str, name_ko: str = None):
    """
    기관 정보를 삽입하거나 갱신한다.
    - 신규 기관: INSERT
    - 기존 기관: last_updated만 갱신 (name_ko가 있으면 함께 갱신)
    """
    now = datetime.utcnow().strftime('%Y-%m-%d')
    conn.execute("""
        INSERT INTO institutions (cik, name_en, name_ko, last_updated)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cik) DO UPDATE SET
            last_updated = excluded.last_updated,
            name_ko = COALESCE(excluded.name_ko, institutions.name_ko)
    """, (cik, name_en, name_ko, now))


def upsert_filing(conn: sqlite3.Connection, cik: str, period: str,
                  filed_date: str, total_aum: int) -> int:
    """
    13F 보고서를 삽입하거나 갱신한다.
    반환값: filing_id (정수)
    """
    conn.execute("""
        INSERT INTO filings (cik, period, filed_date, total_aum)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(cik, period) DO UPDATE SET
            filed_date = excluded.filed_date,
            total_aum  = excluded.total_aum
    """, (cik, period, filed_date, total_aum))

    # 삽입/갱신된 filing의 id 조회
    row = conn.execute(
        'SELECT id FROM filings WHERE cik = ? AND period = ?',
        (cik, period)
    ).fetchone()
    return row['id']


def replace_holdings(conn: sqlite3.Connection, filing_id: int, holdings: list):
    """
    특정 filing의 보유 종목을 교체한다.
    기존 데이터를 삭제하고 새 데이터를 일괄 삽입한다 (멱등성 보장).

    holdings: [
        {
          'name': str, 'ticker': str|None, 'cusip': str,
          'shares': int, 'value': int,
          'investment_type': str, 'sector': str
        },
        ...
    ]
    """
    # 기존 보유 종목 삭제
    conn.execute('DELETE FROM holdings WHERE filing_id = ?', (filing_id,))

    # 새 보유 종목 일괄 삽입
    conn.executemany("""
        INSERT INTO holdings
            (filing_id, name, ticker, cusip, shares, value, investment_type, sector)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [
        (
            filing_id,
            h['name'],
            h.get('ticker'),
            h['cusip'],
            h['shares'],
            h['value'],
            h.get('investment_type', 'SH'),
            h.get('sector', 'Unknown'),
        )
        for h in holdings
    ])


def store_all(conn: sqlite3.Connection, fetch_result: dict):
    """
    fetch_edgar.py가 반환한 데이터를 DB에 일괄 저장한다.

    fetch_result 구조:
    {
      period: {
        cik: {
          'name_en': str,
          'filed_date': str,
          'total_aum': int,
          'holdings': [...]
        }
      }
    }
    """
    with conn:  # 트랜잭션 자동 커밋/롤백
        for period, institutions in fetch_result.items():
            for cik, data in institutions.items():
                upsert_institution(conn, cik, data['name_en'])
                filing_id = upsert_filing(
                    conn, cik, period,
                    data['filed_date'], data['total_aum']
                )
                replace_holdings(conn, filing_id, data['holdings'])


if __name__ == '__main__':
    # 직접 실행 시 스키마만 생성하고 종료
    conn = get_db()
    print(f'데이터베이스 초기화 완료: {DEFAULT_DB_PATH}')
    conn.close()
