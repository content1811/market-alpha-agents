"""Dune Analytics adapter -- custom-SQL on-chain query execution, per
docs/research/crypto_data.md section 2 ("Dune Analytics" row): free tier is
~15 req/min on write-heavy endpoints (create/execute) and ~40 req/min on
read-heavy endpoints (status/results), 1 concurrent query, 30-min execution
timeout, queries expire after 3 months.

Does NOT subclass DataSource: query results are caller-defined SQL rows, not
OHLCV bars, so the base class's get_ohlcv contract doesn't apply.
"""
from __future__ import annotations

import time

import requests
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_URL = "https://api.dune.com/api/v1"


class DuneSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    dune_api_key: str | None = None


class DuneSource:
    name = "dune"

    def __init__(self, settings: DuneSettings | None = None):
        s = settings or DuneSettings()
        if not s.dune_api_key:
            raise ValueError("DUNE_API_KEY not set -- see .env.example")
        self._session = requests.Session()
        self._session.headers.update({"X-Dune-API-Key": s.dune_api_key})

    def create_query(self, name: str, sql: str) -> int:
        resp = self._session.post(
            f"{BASE_URL}/query",
            json={"name": name, "query_sql": sql, "is_private": True},
        )
        resp.raise_for_status()
        return resp.json()["query_id"]

    def execute_query(self, query_id: int) -> str:
        resp = self._session.post(f"{BASE_URL}/query/{query_id}/execute")
        resp.raise_for_status()
        return resp.json()["execution_id"]

    def get_execution_results(
        self,
        execution_id: str,
        poll_timeout_seconds: float = 120,
        initial_backoff: float = 1.0,
        max_backoff: float = 10.0,
    ) -> list[dict]:
        deadline = time.monotonic() + poll_timeout_seconds
        backoff = initial_backoff
        while True:
            resp = self._session.get(f"{BASE_URL}/execution/{execution_id}/status")
            resp.raise_for_status()
            if resp.json()["is_execution_finished"]:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"execution {execution_id} did not finish within {poll_timeout_seconds}s"
                )
            time.sleep(min(backoff, max_backoff, deadline - time.monotonic()))
            backoff = min(backoff * 2, max_backoff)

        resp = self._session.get(f"{BASE_URL}/execution/{execution_id}/results")
        resp.raise_for_status()
        return resp.json()["result"]["rows"]


if __name__ == "__main__":
    source = DuneSource()
    execution_id = source.execute_query(8541027)
    rows = source.get_execution_results(execution_id)
    print(f"Fetched {len(rows)} row(s) from query 8541027: {rows}")
