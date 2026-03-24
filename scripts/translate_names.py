"""
translate_names.py
------------------
기관명을 영어 → 한국어로 번역하는 1회성 스크립트.

우선순위:
  1. 하드코딩된 상위 기관 번역 사전 (API 키 없어도 동작)
  2. DeepL Free API (TRANSLATE_API_KEY가 DeepL 형식이면 사용)
  3. Google Cloud Translation v2 REST API (그 외)

번역 결과는 db/name_translations.json에 캐시하여 재실행 시 건너뜀.
"""

import json
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
import process_data

# 환경변수에서 API 키 로드
TRANSLATE_API_KEY = os.environ.get('TRANSLATE_API_KEY', '')

# 캐시 파일 경로 (db/name_translations.json)
CACHE_PATH = os.path.join(os.path.dirname(__file__), '..', 'db', 'name_translations.json')

# ── 하드코딩 번역 사전 (상위 50개 기관) ─────────────────────────────────────
HARDCODED = {
    'VANGUARD GROUP INC':                           '뱅가드 그룹',
    'BlackRock, Inc.':                              '블랙록',
    'BLACKROCK INC':                                '블랙록',
    'STATE STREET CORP':                            '스테이트 스트리트',
    'STATE STREET CORPORATION':                     '스테이트 스트리트',
    'BERKSHIRE HATHAWAY INC':                       '버크셔 해서웨이',
    'CHARLES SCHWAB INVESTMENT MANAGEMENT':         '찰스 슈왑 자산운용',
    'CHARLES SCHWAB INVESTMENT MANAGEMENT INC':     '찰스 슈왑 자산운용',
    'FIDELITY MANAGEMENT & RESEARCH':               '피델리티 운용',
    'FIDELITY MANAGEMENT & RESEARCH CO LLC':        '피델리티 운용',
    'CAPITAL RESEARCH GLOBAL INVESTORS':            '캐피탈 리서치',
    'CAPITAL WORLD INVESTORS':                      '캐피탈 월드',
    'WELLINGTON MANAGEMENT GROUP LLP':              '웰링턴 운용',
    'GEODE CAPITAL MANAGEMENT LLC':                 '지오드 캐피탈',
    'NORTHERN TRUST CORP':                          '노던 트러스트',
    'JPMORGAN CHASE & CO':                          'JP모건 체이스',
    'T. ROWE PRICE ASSOCIATES INC':                 'T. 로우 프라이스',
    'T ROWE PRICE ASSOCIATES INC':                  'T. 로우 프라이스',
    'INVESCO LTD':                                  '인베스코',
    'BANK OF AMERICA CORP':                         '뱅크오브아메리카',
    'MORGAN STANLEY':                               '모건 스탠리',
    'GOLDMAN SACHS GROUP INC':                      '골드만 삭스',
    'WELLS FARGO & COMPANY':                        '웰스 파고',
    'DIMENSIONAL FUND ADVISORS LP':                 '디멘셔널 펀드',
    'PRICE T ROWE ASSOCIATES INC /MD/':             'T. 로우 프라이스',
    'NUVEEN ASSET MANAGEMENT LLC':                  '누빈 자산운용',
    'AMERICAN CENTURY INVESTMENT MANAGEMENT INC':   '아메리칸 센추리',
    'PARNASSUS INVESTMENTS':                        '파르나서스',
    'PARAMETRIC PORTFOLIO ASSOCIATES LLC':          '파라메트릭',
    'FRANKLIN ADVISERS INC':                        '프랭클린 어드바이저스',
    'FRANKLIN TEMPLETON INSTITUTIONAL LLC':         '프랭클린 템플턴',
    'DODGE & COX':                                  '다지 앤 콕스',
    'CALVERT RESEARCH AND MANAGEMENT':              '칼버트 리서치',
    'PIMCO':                                        '핌코',
    'COLUMBIA THREADNEEDLE INVESTMENTS':            '컬럼비아 스레드니들',
    'NEUBERGER BERMAN INVESTMENT ADVISERS LLC':     '노이버거 버먼',
    'PRINCIPAL FINANCIAL GROUP INC':                '프린시펄 파이낸셜',
    'COATUE MANAGEMENT LLC':                        '코아튀 매니지먼트',
    'TIGER GLOBAL MANAGEMENT LLC':                  '타이거 글로벌',
    'RENAISSANCE TECHNOLOGIES LLC':                 '르네상스 테크놀로지',
    'TWO SIGMA INVESTMENTS LP':                     '투 시그마',
    'CITADEL ADVISORS LLC':                         '시타델',
    'D E SHAW & CO LP':                             'D.E. 쇼',
    'AQR CAPITAL MANAGEMENT LLC':                   'AQR 캐피탈',
    'BRIDGEWATER ASSOCIATES LP':                    '브리지워터',
    'BAUPOST GROUP LLC':                            '바우포스트 그룹',
    'GREENLIGHT CAPITAL INC':                       '그린라이트 캐피탈',
    'PERSHING SQUARE CAPITAL MANAGEMENT':           '퍼싱 스퀘어',
    'THIRD POINT LLC':                              '서드 포인트',
    'DRUCKENMILLER FAMILY FUND LLC':               '드러켄밀러',
}


def load_cache() -> dict:
    """번역 캐시 파일을 로드한다. 없으면 빈 딕셔너리 반환."""
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_cache(cache: dict):
    """번역 캐시를 파일에 저장한다."""
    os.makedirs(os.path.dirname(os.path.abspath(CACHE_PATH)), exist_ok=True)
    with open(CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def _translate_deepl(name: str) -> str:
    """DeepL Free API로 번역한다."""
    url = 'https://api-free.deepl.com/v2/translate'
    resp = requests.post(
        url,
        data={
            'auth_key': TRANSLATE_API_KEY,
            'text':     name,
            'source_lang': 'EN',
            'target_lang': 'KO',
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()['translations'][0]['text']


def _translate_google(name: str) -> str:
    """Google Cloud Translation v2 REST API로 번역한다."""
    url = 'https://translation.googleapis.com/language/translate/v2'
    resp = requests.post(
        url,
        json={
            'q':      name,
            'source': 'en',
            'target': 'ko',
            'key':    TRANSLATE_API_KEY,
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()['data']['translations'][0]['translatedText']


def translate_name(name: str, cache: dict) -> str:
    """
    기관명을 한국어로 번역한다.
    우선순위: 캐시 → 하드코딩 사전 → API (없으면 원문 반환)
    """
    # 1. 캐시 확인
    if name in cache:
        return cache[name]

    # 2. 하드코딩 사전 확인
    if name in HARDCODED:
        return HARDCODED[name]

    # 대소문자 무관 검색
    name_upper = name.upper()
    for key, val in HARDCODED.items():
        if key.upper() == name_upper:
            return val

    # 3. API 없으면 원문 반환
    if not TRANSLATE_API_KEY:
        return name

    # 4. API 번역 시도
    try:
        time.sleep(0.2)  # API Rate Limit
        # DeepL: auth_key는 보통 UUID 형식 (8-4-4-4-12)
        import re
        if re.match(r'^[0-9a-f\-]{36}$', TRANSLATE_API_KEY.lower()):
            return _translate_deepl(name)
        else:
            return _translate_google(name)
    except Exception as e:
        print(f'  [경고] 번역 실패 ({name}): {e}', file=sys.stderr)
        return name


def translate_all(conn):
    """
    DB에서 name_ko가 비어있는 기관을 모두 번역하여 DB를 갱신한다.
    번역 결과는 캐시에도 저장한다.
    """
    cache = load_cache()
    updated = 0

    # name_ko가 없는 기관 조회
    rows = conn.execute(
        'SELECT cik, name_en FROM institutions WHERE name_ko IS NULL'
    ).fetchall()

    if not rows:
        print('번역할 기관이 없습니다 (모두 번역 완료).')
        return

    print(f'{len(rows)}개 기관 번역 시작...')

    for row in rows:
        cik     = row['cik']
        name_en = row['name_en']
        name_ko = translate_name(name_en, cache)

        if name_ko != name_en:
            conn.execute(
                'UPDATE institutions SET name_ko = ? WHERE cik = ?',
                (name_ko, cik)
            )
            cache[name_en] = name_ko
            updated += 1

    conn.commit()
    save_cache(cache)
    print(f'번역 완료: {updated}개 기관 한국어명 갱신')


if __name__ == '__main__':
    conn = process_data.get_db()
    translate_all(conn)
    conn.close()
