"""런타임 접속 롤 수렴·검증 (H10-2 — docs/03 §5.1, 06 §3).

**RLS 이중 방어 2층은 "정책이 걸려 있다"가 아니라 "접속 롤이 정책을 받는다"로 성립한다.**
정책이 `ENABLE`+`FORCE`여도 접속 롤이 superuser·`BYPASSRLS`면 무조건 통과한다.

배포의 `migrate` 스텝이 `alembic upgrade head` 직후 **owner 접속**으로 실행한다:

    python -m liviq_db.runtime_roles

하는 일 —
1. `liviq_app`·`liviq_worker`에 LOGIN + 비밀번호 부여(멱등 → 매 배포 재실행 = 비밀번호 회전 반영).
   비밀번호의 단일 출처는 env(`APP_DATABASE_URL`·`WORKER_DATABASE_URL`)다. 마이그레이션·VCS엔 없다.
2. 각 런타임 롤로 **실제 접속해** superuser·`BYPASSRLS`가 아님을 확인.
3. 같은 접속으로 tenant 컨텍스트 없이 업무 테이블을 읽어 **0행**임을 확인(2층 실동작 프로브).

2·3 중 하나라도 실패하면 비영점 종료 → **배포 중단**(fail-closed). 런타임 env를 owner URL로
되돌리는 회귀(H10-1 스모크에서 발견된 그 상태)를 배포 시점에 잡는 지점이다.
"""

from __future__ import annotations

import asyncio
import os

from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from .config import get_settings

# 런타임 롤 → 접속 URL을 담는 env 키. 마이그레이션(eaf86de665b0)이 만든 롤 이름과 일치해야 한다.
RUNTIME_ROLE_ENV: dict[str, str] = {
    "liviq_app": "APP_DATABASE_URL",
    "liviq_worker": "WORKER_DATABASE_URL",
}
# 격리 프로브 대상. 조건 3개를 만족해야 한다 —
#  ① 표준 tenant 격리 정책이 걸린 업무 테이블(예외 정책 없음)
#  ② **두 런타임 롤 모두 SELECT 권한**이 있다
#     (`households`로 뒀다가 liviq_worker에 권한이 없어 실패했다 — 실측)
#  ③ 실배포라면 비어 있지 않다(부트스트랩 SYS_ADMIN 행) → 프로브가 공허하게 통과하지 않는다
PROBE_TABLE = "users"


class RuntimeRoleError(RuntimeError):
    """접속 롤 계약 위반 — 배포·기동 중단 사유(fail-closed)."""


async def assert_no_rls_bypass(conn: AsyncConnection) -> None:
    """접속 롤이 RLS를 우회하지 않음을 보장. 위반 시 RuntimeRoleError.

    `is_superuser` GUC는 롤 상속을 통한 실효 superuser까지 반영하므로 `rolsuper`보다 넓다.
    """
    role, is_superuser, bypass_rls = (
        await conn.execute(
            text(
                "SELECT current_user::text, current_setting('is_superuser') = 'on', "
                "coalesce((SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user), false)"
            )
        )
    ).one()
    if is_superuser or bypass_rls:
        raise RuntimeRoleError(
            f"접속 롤 '{role}'이 RLS를 우회한다"
            f"(superuser={is_superuser}, bypassrls={bypass_rls}) — "
            f"런타임은 {' · '.join(RUNTIME_ROLE_ENV)}로 접속해야 한다(docs/03 §5.1)."
        )


async def assert_isolation_probe(conn: AsyncConnection, *, baseline_rows: int) -> None:
    """tenant 컨텍스트 없이 업무 테이블이 0행으로 보이는지 확인. 위반 시 RuntimeRoleError.

    `baseline_rows`(owner가 본 행 수)가 0이면 빈 DB라 프로브가 무의미하므로 건너뛴다 —
    롤 속성 검사(`assert_no_rls_bypass`)가 그 경우의 게이트다.
    """
    if baseline_rows == 0:
        return
    visible = await conn.scalar(text(f"SELECT count(*) FROM {PROBE_TABLE}"))
    if visible:
        raise RuntimeRoleError(
            f"tenant 컨텍스트 없이 {PROBE_TABLE} {visible}행이 보인다 — "
            "RLS 이중 방어 2층이 비활성이다(docs/06 §3)."
        )


def _read_targets() -> list[tuple[str, URL]]:
    """env에서 (롤, 접속 URL) 목록 읽기 — 누락·롤 불일치·비밀번호 없음은 즉시 실패."""
    targets: list[tuple[str, URL]] = []
    for role, env_key in RUNTIME_ROLE_ENV.items():
        raw = os.environ.get(env_key)
        if not raw:
            raise RuntimeRoleError(f"{env_key} 미설정 — {role} 접속 URL이 필요하다.")
        url = make_url(raw)
        if url.username != role:
            raise RuntimeRoleError(
                f"{env_key}의 사용자가 '{url.username}'이다 — '{role}'이어야 한다"
                "(owner URL을 런타임에 쓰면 RLS가 무력화된다)."
            )
        if not url.password:
            raise RuntimeRoleError(f"{env_key}에 비밀번호가 없다 — {role}은 접속 롤이다.")
        targets.append((role, url))
    return targets


async def _grant_login(owner_conn: AsyncConnection, role: str, password: str) -> None:
    """런타임 롤에 LOGIN + 비밀번호 부여(멱등). 우회 속성은 명시적으로 박탈해 굳힌다.

    비밀번호를 DDL 문자열에 직접 끼우지 않는다 — GUC로 넘겨 서버 `format('%L')`이 인용하게
    한다(직접 이스케이프는 인젝션 실수의 단골이고, DDL은 바인드 파라미터를 못 받는다).
    """
    await owner_conn.execute(
        text(
            "SELECT set_config('liviq.role', :role, true), set_config('liviq.pw', :pw, true)"
        ).bindparams(role=role, pw=password)
    )
    await owner_conn.execute(
        text(
            "DO $$ BEGIN EXECUTE format("
            "'ALTER ROLE %I WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE "
            "PASSWORD %L', current_setting('liviq.role'), current_setting('liviq.pw')"
            "); END $$"
        )
    )


async def _verify(url: URL, *, baseline_rows: int) -> None:
    """런타임 URL로 실제 접속해 롤 속성·격리 프로브 확인."""
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            await assert_no_rls_bypass(conn)
            await assert_isolation_probe(conn, baseline_rows=baseline_rows)
    finally:
        await engine.dispose()


async def converge_and_verify() -> list[str]:
    """수렴 + 검증. 성공 시 처리한 롤 이름 목록, 실패 시 RuntimeRoleError."""
    targets = _read_targets()
    owner_engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    try:
        async with owner_engine.begin() as conn:
            for role, url in targets:
                await _grant_login(conn, role, url.password or "")
            baseline_rows = await conn.scalar(text(f"SELECT count(*) FROM {PROBE_TABLE}")) or 0
    finally:
        await owner_engine.dispose()

    for _role, url in targets:
        await _verify(url, baseline_rows=baseline_rows)
    return [role for role, _ in targets]


def main() -> None:  # pragma: no cover — CLI 진입점
    try:
        roles = asyncio.run(converge_and_verify())
    except RuntimeRoleError as exc:
        print(f"[runtime_roles] 실패: {exc}")
        raise SystemExit(1) from exc
    print(f"[runtime_roles] 접속 롤 수렴·검증 완료: {', '.join(roles)}")


if __name__ == "__main__":  # pragma: no cover — CLI 진입점
    main()
