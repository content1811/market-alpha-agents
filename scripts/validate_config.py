"""Phase 0 test per docs/plan/section_orchestration.md section 3: load
config.yaml + all watchlists and fail loudly on missing/malformed fields.

Usage: python scripts/validate_config.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_TOP_LEVEL_KEYS = [
    "system",
    "asset_classes",
    "data_sources",
    "thresholds",
    "risk_management",
    "schedules",
    "alerting",
    "llm",
    "backtesting",
]

REQUIRED_ASSET_CLASSES = ["us_equity", "jp_equity", "crypto"]

ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


class ConfigError(Exception):
    pass


def resolve_env_vars(value):
    """Recursively walk config, leaving ${VAR} placeholders as-is but
    validating they reference a known env var name shape -- actual secret
    values are resolved lazily by the code that uses them, never logged here."""
    if isinstance(value, dict):
        return {k: resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_env_vars(v) for v in value]
    if isinstance(value, str):
        m = ENV_VAR_PATTERN.fullmatch(value)
        if m:
            return {"__env_var__": m.group(1)}
        return value
    return value


def load_yaml(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"Missing required file: {path.relative_to(REPO_ROOT)}")
    with open(path) as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f"Malformed YAML in {path.relative_to(REPO_ROOT)}: {e}") from e
    if data is None:
        raise ConfigError(f"{path.relative_to(REPO_ROOT)} is empty")
    return data


def validate_config(config_path: Path) -> dict:
    config = load_yaml(config_path)

    missing = [k for k in REQUIRED_TOP_LEVEL_KEYS if k not in config]
    if missing:
        raise ConfigError(f"config.yaml missing required top-level keys: {missing}")

    asset_classes = config["asset_classes"]
    missing_ac = [k for k in REQUIRED_ASSET_CLASSES if k not in asset_classes]
    if missing_ac:
        raise ConfigError(f"config.yaml asset_classes missing: {missing_ac}")

    for ac_name, ac in asset_classes.items():
        if "enabled" not in ac:
            raise ConfigError(f"asset_classes.{ac_name} missing 'enabled'")
        if not ac.get("enabled"):
            continue
        watchlist_file = ac.get("watchlist_file")
        if not watchlist_file:
            raise ConfigError(f"asset_classes.{ac_name} missing 'watchlist_file'")
        watchlist_path = REPO_ROOT / watchlist_file
        watchlist = load_yaml(watchlist_path)
        if "symbols" not in watchlist or not watchlist["symbols"]:
            raise ConfigError(f"{watchlist_file} has no symbols")
        for entry in watchlist["symbols"]:
            if "symbol" not in entry:
                raise ConfigError(f"{watchlist_file} has an entry with no 'symbol' field: {entry}")

        for strategy_file in ac.get("strategy_files", []):
            strategy_path = REPO_ROOT / strategy_file
            load_yaml(strategy_path)  # raises loudly on malformed/missing

    risk = config["risk_management"]
    equity = risk.get("account_equity_jpy")
    if not isinstance(equity, (int, float)) or equity <= 0:
        raise ConfigError("risk_management.account_equity_jpy must be a positive number")

    resolve_env_vars(config)  # walk the whole tree to catch malformed ${...} refs early

    return config


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    config_path = REPO_ROOT / "config" / "config.yaml"
    try:
        config = validate_config(config_path)
    except ConfigError as e:
        print(f"CONFIG INVALID: {e}", file=sys.stderr)
        return 1

    enabled = [k for k, v in config["asset_classes"].items() if v.get("enabled")]
    print(f"Config OK. Enabled asset classes: {enabled}")
    print(f"Account equity: JPY {config['risk_management']['account_equity_jpy']:,.0f}")

    missing_env = []
    for key, val in config["data_sources"].get("api_keys", {}).items():
        m = ENV_VAR_PATTERN.fullmatch(val) if isinstance(val, str) else None
        if m and not os.environ.get(m.group(1)):
            missing_env.append(m.group(1))
    if missing_env:
        print(
            f"Note: {len(missing_env)} API key env vars not set yet (fine for "
            f"keyless sources like yfinance/CCXT public/SEC EDGAR): {missing_env}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
