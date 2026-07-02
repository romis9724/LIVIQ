"""Gmail MCP 메일 발송."""

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from .config import GMAIL_MCP


async def send_gmail(to: str, subject: str, body: str) -> str:
    async with stdio_client(GMAIL_MCP) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "send_email",
                {"to": to, "subject": subject, "body": body},
            )
            return result.content[0].text if result.content else "발송 완료"
