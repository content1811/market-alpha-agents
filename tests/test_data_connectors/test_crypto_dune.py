"""Live smoke test against Dune's async query lifecycle, reusing the existing
"market-alpha-agents smoke test" query (query_id=8541027, SQL "SELECT 1 as x")
rather than creating a new one -- see docs/research/crypto_data.md section 2
for why the free tier's limited query slots/concurrency make query reuse the
right default for a trivial round-trip check.
"""
from __future__ import annotations

import pytest

from data.connectors.crypto_dune import DuneSource

SMOKE_TEST_QUERY_ID = 8541027


@pytest.mark.network
def test_execute_and_get_results_for_smoke_test_query():
    source = DuneSource()
    execution_id = source.execute_query(SMOKE_TEST_QUERY_ID)
    rows = source.get_execution_results(execution_id)
    assert rows == [{"x": 1}]
