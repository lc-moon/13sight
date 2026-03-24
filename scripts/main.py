"""
main.py
-------
13Sight 데이터 업데이트 파이프라인의 진입점.

실행 흐름:
  1. EDGAR에서 최신 분기 정보 확인
  2. DB에 저장된 최신 분기와 비교
  3. 변경 없으면 "NO_UPDATE" 출력 후 종료
  4. 변경 있으면:
     - EDGAR 데이터 수집 (fetch_edgar)
     - DB 저장 (process_data)
     - 한국어 번역 (translate_names)
     - JSON 내보내기 (export_json)
     - "UPDATED" 출력

GitHub Actions에서 stdout의 "UPDATED"/"NO_UPDATE"로 커밋 여부를 판단한다.
모든 진행 로그는 stderr로 출력한다.
"""

import os
import sys

# 스크립트 디렉토리를 모듈 경로에 추가
sys.path.insert(0, os.path.dirname(__file__))

import fetch_edgar
import process_data
import translate_names
import export_json

# 경로 설정
ROOT     = os.path.join(os.path.dirname(__file__), '..')
DB_PATH  = os.path.join(ROOT, 'db', '13sight.db')
JSON_OUT = os.path.join(ROOT, 'web', 'data', 'institutions.json')


def get_stored_latest_period(conn) -> str | None:
    """DB에 저장된 가장 최신 분기를 반환한다."""
    row = conn.execute('SELECT MAX(period) AS p FROM filings').fetchone()
    return row['p'] if row and row['p'] else None


def run():
    """메인 실행 함수."""
    print('=== 13Sight 데이터 업데이트 시작 ===', file=sys.stderr)

    # 1. HTTP 세션 생성
    session = fetch_edgar.get_session()

    # 2. EDGAR에서 최신 분기 확인
    print('EDGAR 최신 분기 조회 중...', file=sys.stderr)
    try:
        available_periods = fetch_edgar.get_latest_periods(session, n=2)
    except Exception as e:
        print(f'[오류] EDGAR 분기 조회 실패: {e}', file=sys.stderr)
        sys.exit(1)

    if not available_periods:
        print('[경고] 수집 가능한 분기 없음', file=sys.stderr)
        print('NO_UPDATE')
        return

    latest_remote = available_periods[0]
    print(f'EDGAR 최신 분기: {latest_remote}', file=sys.stderr)

    # 3. DB 최신 분기 확인
    conn = process_data.get_db(DB_PATH)
    latest_local = get_stored_latest_period(conn)
    print(f'DB 최신 분기: {latest_local}', file=sys.stderr)

    # 4. 변경 여부 비교
    if latest_remote == latest_local:
        print('최신 데이터 이미 보유 중 → 업데이트 불필요', file=sys.stderr)
        conn.close()
        print('NO_UPDATE')
        return

    print(
        f'새 데이터 감지: {latest_local} → {latest_remote}',
        file=sys.stderr
    )

    # 5. 데이터 수집
    print('\n[1/4] EDGAR 데이터 수집 중...', file=sys.stderr)
    try:
        fetch_result = fetch_edgar.fetch_all(session, available_periods)
    except Exception as e:
        print(f'[오류] 데이터 수집 실패: {e}', file=sys.stderr)
        conn.close()
        sys.exit(1)

    # 6. DB 저장
    print('\n[2/4] DB 저장 중...', file=sys.stderr)
    try:
        process_data.store_all(conn, fetch_result)
    except Exception as e:
        print(f'[오류] DB 저장 실패: {e}', file=sys.stderr)
        conn.close()
        sys.exit(1)

    # 7. 한국어 번역
    print('\n[3/4] 한국어 번역 중...', file=sys.stderr)
    try:
        translate_names.translate_all(conn)
    except Exception as e:
        print(f'[경고] 번역 일부 실패: {e}', file=sys.stderr)
        # 번역 실패는 치명적이지 않으므로 계속 진행

    # 8. JSON 내보내기
    print('\n[4/4] JSON 내보내기 중...', file=sys.stderr)
    try:
        export_json.export(db_path=DB_PATH, output_path=JSON_OUT)
    except Exception as e:
        print(f'[오류] JSON 내보내기 실패: {e}', file=sys.stderr)
        conn.close()
        sys.exit(1)

    conn.close()
    print('\n=== 업데이트 완료 ===', file=sys.stderr)

    # GitHub Actions에서 이 출력을 감지해 커밋 여부를 결정한다
    print('UPDATED')


if __name__ == '__main__':
    run()
