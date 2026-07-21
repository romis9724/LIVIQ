"""메일 발송 어댑터 — console(local) · smtp(STARTTLS) (ADR-0014).

외부 프로바이더는 Mailer Protocol 뒤로 둔다(파일럿=Gmail SMTP, 초과 시 SES 등으로 교체).
발송 실패는 예외로 전파 — 호출부가 트랜잭션 롤백·응답 코드를 결정한다.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config import get_settings


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleMailer:
    """local 기본 — 실 발송 없이 본문·링크를 로그로 출력(ADR-0014).

    검증·재설정 링크(토큰 포함)를 개발자가 확인하는 용도라 토큰이 로그에 남는다 —
    console 백엔드는 local 전용이고 운영은 smtp를 쓴다(운영 로그엔 토큰 미노출).
    """

    def send(self, to: str, subject: str, body: str) -> None:
        # logging이 아닌 stdout — uvicorn 기본 로깅 설정에서 앱 로거 INFO는 묻힌다.
        print(f"[ConsoleMailer] to={to} subject={subject}\n{body}", flush=True)  # noqa: T201


class SmtpMailer:
    """SMTP STARTTLS 발송(파일럿=Gmail). 앱 비밀번호는 env로만 주입(하드코딩 금지)."""

    def __init__(self, host: str, port: int, user: str, password: str, sender: str) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._sender = sender

    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._sender
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
            smtp.starttls()
            smtp.login(self._user, self._password)
            smtp.send_message(msg)


def get_mailer() -> Mailer:  # pragma: no cover — env 배선(테스트는 오버라이드)
    """MAIL_BACKEND로 어댑터 선택(기본 console). smtp는 SMTP_* 설정 필수(fail-closed)."""
    s = get_settings()
    if s.mail_backend == "smtp":
        if not (s.smtp_host and s.smtp_user and s.smtp_password and s.smtp_from):
            raise RuntimeError("MAIL_BACKEND=smtp이면 SMTP_HOST/USER/PASSWORD/FROM 필수")
        # Gmail 앱 비밀번호는 "xxxx xxxx …"로 표시돼 복사 시 공백(NBSP 포함)이 섞인다 —
        # SMTP AUTH는 공백 없는 원문만 받으므로 유니코드 공백을 전부 제거.
        password = "".join(s.smtp_password.split())
        return SmtpMailer(s.smtp_host, s.smtp_port, s.smtp_user, password, s.smtp_from)
    return ConsoleMailer()
