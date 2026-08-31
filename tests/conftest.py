"""테스트가 쓸 가짜 시크릿 — **CI 에는 `.env` 가 없다.**

`app.core.config` 는 import 되는 순간 `Settings()` 를 만들고, 시크릿이 비었거나
알려진 기본값이면 거기서 죽는다(`_guard_secrets`, fail-closed). 그래서 CI 에서
`pytest` 가 **수집 단계에서** 멈췄다 — 테스트를 하나도 못 돌리고 끝났다.

```
tests/test_attendance_status.py → app.api.staff.attendance
                                → app.core.deps → app.core.config → 죽음
```

여기서 값을 채워 준다. `conftest.py` 는 테스트 모듈보다 **먼저** 읽히므로
`app` 을 부르기 전에 환경이 갖춰진다.

**가드를 약하게 만들지 않는다.** 검사는 그대로 두고 테스트에만 '기본값이 아닌
값'을 준다 — 운영에서 `.env` 를 빠뜨리면 예전처럼 그 자리에서 죽는다.

이 파일이 없어서 안 돌던 것이지, 테스트가 시크릿을 쓰는 것은 아니다.
여기 있는 테스트는 전부 순수 계산이다 (`tests/__init__.py` 참고).
"""

import os

# `setdefault` 라 진짜 값이 이미 있으면 안 건드린다 (로컬에서 env 를 넣고 도는 경우)
os.environ.setdefault("JWT_SECRET", "test-only-jwt-secret")
os.environ.setdefault("ACCOUNT_MASTER_KEY", "11" * 32)  # hex 64자 — 기본값('00'…)만 아니면 된다
os.environ.setdefault("KINDNESS_WEBHOOK_SECRET", "test-only-webhook-secret")
