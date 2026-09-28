import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from sqlmodel import Session

from Tools.price_alerts.models import (
    PRICE_ALERT_ADMIN_EMAIL,
    PriceAlertRole,
    TesterAccount,
    normalize_email,
    upsert_tester_account,
)


TESTER_ACCOUNTS_JSON_ENV = "TESTER_ACCOUNTS_JSON"
MCP_AUTH_ISSUER_URL_ENV = "MCP_AUTH_ISSUER_URL"
MCP_AUTH_RESOURCE_URL_ENV = "MCP_AUTH_RESOURCE_URL"
DEFAULT_ACTIVE_ALERT_LIMIT = 5
DEFAULT_MANUAL_CHECK_DAILY_LIMIT = 3
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TesterConfig:
    token: str
    owner_id: str
    token_hash: str
    recipient_email: str
    role: PriceAlertRole
    active_alert_limit: int
    manual_check_daily_limit: int


@dataclass(frozen=True)
class TesterContext:
    owner_id: str
    recipient_email: str
    role: PriceAlertRole

    @property
    def is_admin(self) -> bool:
        return self.role == PriceAlertRole.admin


def _env_paths():
    paths = [PROJECT_ROOT / ".env", Path.cwd() / ".env"]
    paths.extend(parent / ".env" for parent in Path.cwd().parents)

    seen = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        yield resolved


def load_env_file() -> None:
    for env_path in _env_paths():
        if not env_path.exists():
            continue

        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"'")
            if key and key not in os.environ:
                os.environ[key] = value


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def owner_id_from_token(token: str) -> str:
    return f"owner_{token_hash(token)[:16]}"


def _positive_int(value: Any, default: int) -> int:
    if value is None:
        return default
    return max(0, int(value))


def _tester_config_from_mapping(item: dict[str, Any]) -> TesterConfig:
    token = str(item.get("token", "")).strip()
    if not token:
        raise ValueError("Each tester account requires a non-empty token")

    recipient_email = normalize_email(str(item.get("recipient_email", "")))
    role = (
        PriceAlertRole.admin
        if recipient_email == PRICE_ALERT_ADMIN_EMAIL
        else PriceAlertRole.user
    )
    return TesterConfig(
        token=token,
        owner_id=owner_id_from_token(token),
        token_hash=token_hash(token),
        recipient_email=recipient_email,
        role=role,
        active_alert_limit=_positive_int(
            item.get("active_alert_limit"),
            DEFAULT_ACTIVE_ALERT_LIMIT,
        ),
        manual_check_daily_limit=_positive_int(
            item.get("manual_check_daily_limit"),
            DEFAULT_MANUAL_CHECK_DAILY_LIMIT,
        ),
    )


def load_tester_configs() -> list[TesterConfig]:
    load_env_file()
    raw_config = os.getenv(TESTER_ACCOUNTS_JSON_ENV, "").strip()
    if not raw_config:
        return []

    parsed = json.loads(raw_config)
    if not isinstance(parsed, list):
        raise ValueError(f"{TESTER_ACCOUNTS_JSON_ENV} must be a JSON array")

    configs = []
    seen_tokens = set()
    for item in parsed:
        if not isinstance(item, dict):
            raise ValueError(f"{TESTER_ACCOUNTS_JSON_ENV} entries must be objects")
        config = _tester_config_from_mapping(item)
        if config.token_hash in seen_tokens:
            raise ValueError("Each tester must have a unique bearer token")
        seen_tokens.add(config.token_hash)
        configs.append(config)
    return configs


def sync_tester_accounts(session: Session) -> list[TesterAccount]:
    accounts = []
    for config in load_tester_configs():
        accounts.append(
            upsert_tester_account(
                session,
                TesterAccount(
                    owner_id=config.owner_id,
                    token_hash=config.token_hash,
                    recipient_email=config.recipient_email,
                    role=config.role,
                    active_alert_limit=config.active_alert_limit,
                    manual_check_daily_limit=config.manual_check_daily_limit,
                ),
            )
        )
    return accounts


class EnvBearerTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        for config in load_tester_configs():
            if token_hash(token) != config.token_hash:
                continue
            return AccessToken(
                token=token,
                client_id=config.owner_id,
                subject=config.owner_id,
                scopes=["price-alerts"],
                claims={
                    "owner_id": config.owner_id,
                    "recipient_email": config.recipient_email,
                    "role": config.role.value,
                },
            )
        return None


def get_mcp_auth_settings() -> AuthSettings:
    load_env_file()
    issuer_url = os.getenv(MCP_AUTH_ISSUER_URL_ENV, "https://price-alert.local")
    resource_url = os.getenv(
        MCP_AUTH_RESOURCE_URL_ENV,
        "https://price-checker-mcp-production.up.railway.app/mcp",
    )
    return AuthSettings(
        issuer_url=issuer_url,
        resource_server_url=resource_url,
        required_scopes=["price-alerts"],
        validate_token_resource=False,
    )


def get_current_tester_context() -> TesterContext | None:
    access_token = get_access_token()
    if access_token is None or access_token.claims is None:
        return None

    owner_id = str(access_token.claims.get("owner_id", "")).strip()
    recipient_email = str(access_token.claims.get("recipient_email", "")).strip()
    role = str(access_token.claims.get("role", PriceAlertRole.user.value)).strip()
    if not owner_id or not recipient_email:
        return None
    return TesterContext(
        owner_id=owner_id,
        recipient_email=normalize_email(recipient_email),
        role=PriceAlertRole(role),
    )
