"""학교 검색 — 교육부 나이스(NEIS) 교육정보 개방 포털의 학교기본정보 API.

브라우저에서 바로 부르면 CORS 로 막히므로 서버가 대신 묻는다. 키(NEIS_API_KEY)가 없어도 쓸 수 있지만
그때는 한 번에 5개까지만 돌려준다 (https://open.neis.go.kr 에서 무료로 키를 받으면 더 많이).
초·중·고등학교만 있고 대학교는 없다.
"""

from __future__ import annotations

from functools import lru_cache

import httpx2
from pydantic import BaseModel

from education.config import get_settings

URL = "https://open.neis.go.kr/hub/schoolInfo"
KIND_ORDER = {"고등학교": 0, "중학교": 1, "각종학교(고)": 2, "특수학교": 3, "초등학교": 4}


class School(BaseModel):
    name: str
    kind: str  # 고등학교, 중학교 …
    region: str  # 서울특별시 …
    address: str | None


class SchoolSearchError(Exception):
    pass


@lru_cache(maxsize=512)
def search(query: str) -> tuple[School, ...]:
    key = get_settings().neis_api_key
    params = {"Type": "json", "pIndex": 1, "pSize": 20 if key else 5, "SCHUL_NM": query}
    if key:
        params["KEY"] = key
    try:
        with httpx2.Client(timeout=5) as http:
            res = http.get(URL, params=params)
            res.raise_for_status()
            data = res.json()
    except (httpx2.HTTPError, ValueError) as e:
        raise SchoolSearchError(f"학교 검색 실패: {e}") from e
    if "schoolInfo" not in data:  # 결과 없음은 {"RESULT": {"CODE": "INFO-200", ...}}
        return ()
    rows = next((part["row"] for part in data["schoolInfo"] if "row" in part), [])
    schools = [School(name=r["SCHUL_NM"], kind=r.get("SCHUL_KND_SC_NM") or "", region=r.get("LCTN_SC_NM") or "",
                      address=(r.get("ORG_RDNMA") or "").strip() or None) for r in rows]
    return tuple(sorted(schools, key=lambda s: (KIND_ORDER.get(s.kind, 9), s.name)))
