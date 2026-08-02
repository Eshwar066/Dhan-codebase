"""
Kotak Neo environment credentials and unattended session bootstrap.

Env vars:
  KOTAK_CONSUMER_KEY, KOTAK_CONSUMER_SECRET
  KOTAK_MOBILE, KOTAK_UCC, KOTAK_MPIN
  KOTAK_TOTP_SECRET  (preferred — generates current TOTP)
  or KOTAK_TOTP      (one-shot 6-digit code; expires quickly)
  KOTAK_ENVIRONMENT  (prod | uat; default prod)
  KOTAK_NEO_FIN_KEY  (optional tracking key)
  KOTAK_ACCESS_TOKEN (optional: skip TOTP if already logged in)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class KotakCredentials:
    consumer_key: str
    consumer_secret: str
    mobile: str
    ucc: str
    mpin: str
    totp_secret: str = ""
    totp: str = ""
    environment: str = "prod"
    neo_fin_key: str = ""
    access_token: str = ""


def get_kotak_credentials() -> KotakCredentials:
    """Load Kotak Neo credentials from environment. Raises ValueError if incomplete."""
    consumer_key = (os.getenv("KOTAK_CONSUMER_KEY") or "").strip()
    consumer_secret = (os.getenv("KOTAK_CONSUMER_SECRET") or "").strip()
    mobile = (os.getenv("KOTAK_MOBILE") or "").strip()
    ucc = (os.getenv("KOTAK_UCC") or "").strip()
    mpin = (os.getenv("KOTAK_MPIN") or "").strip()
    totp_secret = (os.getenv("KOTAK_TOTP_SECRET") or "").strip()
    totp = (os.getenv("KOTAK_TOTP") or "").strip()
    environment = (os.getenv("KOTAK_ENVIRONMENT") or "prod").strip().lower() or "prod"
    neo_fin_key = (os.getenv("KOTAK_NEO_FIN_KEY") or "").strip()
    access_token = (os.getenv("KOTAK_ACCESS_TOKEN") or "").strip()

    missing = []
    if not consumer_key:
        missing.append("KOTAK_CONSUMER_KEY")
    if not access_token:
        if not mobile:
            missing.append("KOTAK_MOBILE")
        if not ucc:
            missing.append("KOTAK_UCC")
        if not mpin:
            missing.append("KOTAK_MPIN")
        if not totp_secret and not totp:
            missing.append("KOTAK_TOTP_SECRET or KOTAK_TOTP")
    if missing:
        raise ValueError(
            "Kotak Neo credentials missing: " + ", ".join(missing)
            + ". Set them in .env for unattended login."
        )
    return KotakCredentials(
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        mobile=mobile,
        ucc=ucc,
        mpin=mpin,
        totp_secret=totp_secret,
        totp=totp,
        environment=environment,
        neo_fin_key=neo_fin_key,
        access_token=access_token,
    )


def _current_totp(secret: str) -> str:
    try:
        import pyotp
    except ImportError as e:
        raise ValueError(
            "pyotp is required for KOTAK_TOTP_SECRET. Install: pip install pyotp"
        ) from e
    return str(pyotp.TOTP(secret).now())


def create_logged_in_neo_api(creds: Optional[KotakCredentials] = None) -> Any:
    """
    Construct NeoAPI and complete TOTP + MPIN login (unless access_token is set).

    Uses the installed ``neo_api_client.NeoAPI`` (kotakneoapi package).
    Returns a live ``NeoAPI`` instance ready for REST / WS.
    """
    from neo_api_client import NeoAPI

    c = creds or get_kotak_credentials()
    env = "prod" if c.environment in ("prod", "production", "live") else "uat"

    if c.access_token:
        api = NeoAPI(
            consumer_key=c.consumer_key or None,
            environment=env,
            access_token=c.access_token,
            neo_fin_key=c.neo_fin_key or None,
        )
        logger.info("Kotak NeoAPI initialized with KOTAK_ACCESS_TOKEN (skip TOTP)")
        return api

    api = NeoAPI(
        consumer_key=c.consumer_key or None,
        environment=env,
        access_token=None,
        neo_fin_key=c.neo_fin_key or None,
    )

    totp_code = c.totp or _current_totp(c.totp_secret)
    login_resp = api.totp_login(mobile_number=c.mobile, ucc=c.ucc, totp=totp_code)
    if isinstance(login_resp, dict) and login_resp.get("error"):
        raise RuntimeError(f"Kotak Neo totp_login failed: {login_resp}")

    validate_resp = api.totp_validate(mpin=c.mpin)
    if isinstance(validate_resp, dict) and (
        validate_resp.get("error") or validate_resp.get("Error Message")
    ):
        raise RuntimeError(f"Kotak Neo totp_validate failed: {validate_resp}")

    cfg = getattr(api, "configuration", None)
    edit_token = getattr(cfg, "edit_token", None) if cfg is not None else None
    # Newer SDK may store the trade token under different attribute names.
    if not edit_token and cfg is not None:
        edit_token = (
            getattr(cfg, "token", None)
            or getattr(cfg, "editToken", None)
            or getattr(cfg, "access_token", None)
        )
    if not edit_token:
        raise RuntimeError(
            "Kotak Neo login did not set edit_token; check credentials / TOTP / MPIN"
            f" login={login_resp!r} validate={validate_resp!r}"
        )
    logger.info("Kotak Neo session ready (TOTP + MPIN) env=%s ucc=%s", env, c.ucc)
    return api
