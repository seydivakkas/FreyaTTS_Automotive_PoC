"""
Asterisk Manager Interface (AMI) Client.

Giden cagrilar (outbound calls) baslatmak icin Asterisk AMI protokolunu (TCP 5038)
asenkron olarak yonetir. Testler ve yerel kullanim icin MockAMIClient sunar.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Protocol, Optional, Dict, Any
from uuid import uuid4
from backend.config import settings

logger = logging.getLogger("automotive_voice.ami")


class AMIClientProtocol(Protocol):
    async def originate(
        self,
        channel: str,
        context: str,
        exten: str,
        callerid: str,
        variables: Optional[Dict[str, str]] = None,
        timeout_ms: int = 30000,
        action_id: Optional[str] = None,
    ) -> dict:
        """Asterisk Originate eylemi baslatir."""
        ...

    async def redirect(
        self,
        channel: str,
        context: str,
        exten: str,
        priority: int = 1,
        extra_channel: Optional[str] = None,
        action_id: Optional[str] = None,
    ) -> dict:
        """Aktif cagriyi baska bir dahiliye veya hedefe yonlendirir (Redirect/Transfer)."""
        ...

    async def setvar(
        self,
        channel: str,
        variable: str,
        value: str,
        action_id: Optional[str] = None,
    ) -> dict:
        """Cagri kanalina veya SIP basliklarina degisken yazar (Screen-Pop / Setvar)."""
        ...

    async def bridge(
        self,
        channel1: str,
        channel2: str,
        tone: bool = True,
        action_id: Optional[str] = None,
    ) -> dict:
        """Iki ayri ses kanalini birbirine baglar (Bridge)."""
        ...

    async def hangup(
        self,
        channel: str,
        cause: int = 16,
        action_id: Optional[str] = None,
    ) -> dict:
        """Cagriyi sonlandirir."""
        ...

    async def ping(self) -> bool:
        """AMI baglantisini test eder."""
        ...


class MockAMIClient:
    """Birim testler ve Asterisk baglantisi olmayan yerel calisma icin mock AMI client."""

    def __init__(self):
        self.calls: list[dict] = []
        self.redirects: list[dict] = []
        self.variables: list[dict] = []
        self.bridges: list[dict] = []
        self.hangups: list[dict] = []
        self.fail_next: bool = False
        self.fail_reason: str = "Asterisk AMI connection refused (127.0.0.1:5038)"

    async def originate(
        self,
        channel: str,
        context: str,
        exten: str,
        callerid: str,
        variables: Optional[Dict[str, str]] = None,
        timeout_ms: int = 30000,
        action_id: Optional[str] = None,
    ) -> dict:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError(self.fail_reason)
        act_id = action_id or f"ami-act-{uuid4().hex[:8]}"
        record = {
            "action_id": act_id,
            "channel": channel,
            "context": context,
            "exten": exten,
            "callerid": callerid,
            "variables": variables or {},
            "timeout_ms": timeout_ms,
            "response": "Success",
            "message": "Originate successfully queued",
        }
        self.calls.append(record)
        return record

    async def redirect(
        self,
        channel: str,
        context: str,
        exten: str,
        priority: int = 1,
        extra_channel: Optional[str] = None,
        action_id: Optional[str] = None,
    ) -> dict:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError(self.fail_reason)
        act_id = action_id or f"ami-redir-{uuid4().hex[:8]}"
        record = {
            "action_id": act_id,
            "channel": channel,
            "context": context,
            "exten": exten,
            "priority": priority,
            "extra_channel": extra_channel,
            "response": "Success",
            "message": "Redirect successfully queued",
        }
        self.redirects.append(record)
        return record

    async def setvar(
        self,
        channel: str,
        variable: str,
        value: str,
        action_id: Optional[str] = None,
    ) -> dict:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError(self.fail_reason)
        act_id = action_id or f"ami-setvar-{uuid4().hex[:8]}"
        record = {
            "action_id": act_id,
            "channel": channel,
            "variable": variable,
            "value": value,
            "response": "Success",
        }
        self.variables.append(record)
        return record

    async def bridge(
        self,
        channel1: str,
        channel2: str,
        tone: bool = True,
        action_id: Optional[str] = None,
    ) -> dict:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError(self.fail_reason)
        act_id = action_id or f"ami-bridge-{uuid4().hex[:8]}"
        record = {
            "action_id": act_id,
            "channel1": channel1,
            "channel2": channel2,
            "tone": tone,
            "response": "Success",
            "message": "Bridge successfully executed",
        }
        self.bridges.append(record)
        return record

    async def hangup(
        self,
        channel: str,
        cause: int = 16,
        action_id: Optional[str] = None,
    ) -> dict:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError(self.fail_reason)
        act_id = action_id or f"ami-hangup-{uuid4().hex[:8]}"
        record = {
            "action_id": act_id,
            "channel": channel,
            "cause": cause,
            "response": "Success",
            "message": "Channel hung up",
        }
        self.hangups.append(record)
        return record

    async def ping(self) -> bool:
        if self.fail_next:
            return False
        return True

    def clear(self):
        self.calls.clear()
        self.redirects.clear()
        self.variables.clear()
        self.bridges.clear()
        self.hangups.clear()
        self.fail_next = False


class AsteriskAMIClient:
    """Gercek TCP tabanli Asterisk Manager Interface (AMI) client."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        secret: str | None = None,
    ):
        self.host = host or settings.ami_host
        self.port = port or settings.ami_port
        self.username = username or settings.ami_username
        self.secret = secret or settings.ami_secret

    async def _execute_action(
        self, action_dict: dict[str, Any], timeout: float = 10.0
    ) -> dict[str, str]:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=timeout
        )
        try:
            banner = await asyncio.wait_for(reader.readline(), timeout=timeout)
            if not banner.startswith(b"Asterisk Call Manager"):
                raise RuntimeError(
                    f"Gecersiz AMI basligi: {banner.decode(errors='ignore')}"
                )

            # Login
            login_payload = (
                f"Action: Login\r\n"
                f"Username: {self.username}\r\n"
                f"Secret: {self.secret}\r\n"
                f"ActionID: login-{uuid4().hex[:6]}\r\n\r\n"
            )
            writer.write(login_payload.encode("utf-8"))
            await writer.drain()

            login_resp = await self._read_response_block(reader, timeout=timeout)
            if login_resp.get("Response") != "Success":
                raise PermissionError(
                    f"AMI Giris basarisiz: {login_resp.get('Message', 'Unknown')}"
                )

            # Action
            lines = []
            for k, v in action_dict.items():
                if k == "Variable" and isinstance(v, dict):
                    for var_k, var_v in v.items():
                        lines.append(f"Variable: {var_k}={var_v}")
                else:
                    lines.append(f"{k}: {v}")
            lines.append("\r\n")
            writer.write("\r\n".join(lines).encode("utf-8"))
            await writer.drain()

            resp = await self._read_response_block(reader, timeout=timeout)
            return resp
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _read_response_block(
        self, reader: asyncio.StreamReader, timeout: float = 10.0
    ) -> dict[str, str]:
        headers: dict[str, str] = {}
        while True:
            line_bytes = await asyncio.wait_for(reader.readline(), timeout=timeout)
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").strip()
            if not line:
                if headers:
                    break
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        return headers

    async def originate(
        self,
        channel: str,
        context: str,
        exten: str,
        callerid: str,
        variables: Optional[Dict[str, str]] = None,
        timeout_ms: int = 30000,
        action_id: Optional[str] = None,
    ) -> dict:
        act_id = action_id or f"ami-orig-{uuid4().hex[:8]}"
        payload = {
            "Action": "Originate",
            "Channel": channel,
            "Context": context,
            "Exten": exten,
            "Priority": "1",
            "Timeout": str(timeout_ms),
            "CallerID": callerid,
            "Async": "true",
            "ActionID": act_id,
        }
        if variables:
            payload["Variable"] = variables
        resp = await self._execute_action(payload)
        return {
            "action_id": act_id,
            "channel": channel,
            "response": resp.get("Response", "Error"),
            "message": resp.get("Message", ""),
        }

    async def redirect(
        self,
        channel: str,
        context: str,
        exten: str,
        priority: int = 1,
        extra_channel: Optional[str] = None,
        action_id: Optional[str] = None,
    ) -> dict:
        act_id = action_id or f"ami-redir-{uuid4().hex[:8]}"
        payload = {
            "Action": "Redirect",
            "Channel": channel,
            "Context": context,
            "Exten": exten,
            "Priority": str(priority),
            "ActionID": act_id,
        }
        if extra_channel:
            payload["ExtraChannel"] = extra_channel
        resp = await self._execute_action(payload)
        return {
            "action_id": act_id,
            "channel": channel,
            "response": resp.get("Response", "Error"),
            "message": resp.get("Message", ""),
        }

    async def setvar(
        self,
        channel: str,
        variable: str,
        value: str,
        action_id: Optional[str] = None,
    ) -> dict:
        act_id = action_id or f"ami-setvar-{uuid4().hex[:8]}"
        payload = {
            "Action": "Setvar",
            "Channel": channel,
            "Variable": variable,
            "Value": value,
            "ActionID": act_id,
        }
        resp = await self._execute_action(payload)
        return {
            "action_id": act_id,
            "channel": channel,
            "response": resp.get("Response", "Error"),
            "message": resp.get("Message", ""),
        }

    async def bridge(
        self,
        channel1: str,
        channel2: str,
        tone: bool = True,
        action_id: Optional[str] = None,
    ) -> dict:
        act_id = action_id or f"ami-bridge-{uuid4().hex[:8]}"
        payload = {
            "Action": "Bridge",
            "Channel1": channel1,
            "Channel2": channel2,
            "Tone": "yes" if tone else "no",
            "ActionID": act_id,
        }
        resp = await self._execute_action(payload)
        return {
            "action_id": act_id,
            "channel1": channel1,
            "channel2": channel2,
            "response": resp.get("Response", "Error"),
            "message": resp.get("Message", ""),
        }

    async def hangup(
        self,
        channel: str,
        cause: int = 16,
        action_id: Optional[str] = None,
    ) -> dict:
        act_id = action_id or f"ami-hangup-{uuid4().hex[:8]}"
        payload = {
            "Action": "Hangup",
            "Channel": channel,
            "Cause": str(cause),
            "ActionID": act_id,
        }
        resp = await self._execute_action(payload)
        return {
            "action_id": act_id,
            "channel": channel,
            "response": resp.get("Response", "Error"),
            "message": resp.get("Message", ""),
        }

    async def ping(self) -> bool:
        try:
            resp = await self._execute_action({"Action": "Ping"}, timeout=3.0)
            return resp.get("Response") == "Success"
        except Exception:
            return False


_active_ami: AMIClientProtocol = MockAMIClient()


def get_ami_client() -> AMIClientProtocol:
    global _active_ami
    return _active_ami


def set_ami_client(client: AMIClientProtocol) -> None:
    global _active_ami
    _active_ami = client

