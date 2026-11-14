"""Tests for the composition root (no network: BigQuery and Vertex are replaced)."""

from pathlib import Path

import pytest

from ga4_sql_analyst import bootstrap
from ga4_sql_analyst.models import AskRequest
from ga4_sql_analyst.offline import build_offline_model
from ga4_sql_analyst.ports import Row
from ga4_sql_analyst.scenarios import SCENARIOS
from ga4_sql_analyst.service import AskService
from ga4_sql_analyst.settings import Settings

PARQUET = Path(__file__).parent / "fixtures" / "ga4_sample.parquet"
ESTIMATE = 1_000
ROW: Row = {"channel": "organic", "revenue": 10}


class _FakeWarehouse:
    def __init__(self) -> None:
        self.dry_runs = 0
        self.executions = 0

    def dry_run(self, sql: str) -> int:
        self.dry_runs += 1
        return ESTIMATE

    def execute(self, sql: str, max_bytes_billed: int) -> list[Row]:
        self.executions += 1
        return [ROW]


@pytest.mark.anyio
async def test_build_service_offline_uses_local_sample() -> None:
    settings = Settings(offline=True, sample_path=PARQUET)
    service = bootstrap.build_service(settings)
    assert isinstance(service, AskService)
    response = await service.ask(AskRequest(question=SCENARIOS[0].question["en"], lang="en"))
    assert response.status == "answered"
    assert response.rows


@pytest.mark.anyio
async def test_build_service_live_wires_cached_warehouse_and_vertex_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warehouse = _FakeWarehouse()
    seen: dict[str, tuple[str, ...]] = {}

    def fake_warehouse(project: str) -> _FakeWarehouse:
        seen["warehouse"] = (project,)
        return warehouse

    def fake_model(model_id: str, project: str, location: str) -> object:
        seen["model"] = (model_id, project, location)
        return build_offline_model()

    monkeypatch.setattr(bootstrap, "create_bigquery_warehouse", fake_warehouse)
    monkeypatch.setattr(bootstrap, "build_vertex_model", fake_model)
    settings = Settings(offline=False, gcp_project="proj", vertex_location="loc", model_id="mod")
    service = bootstrap.build_service(settings)
    request = AskRequest(question=SCENARIOS[0].question["en"], lang="en")
    first = await service.ask(request)
    second = await service.ask(request)
    assert first.status == second.status == "answered"
    assert seen == {"warehouse": ("proj",), "model": ("mod", "proj", "loc")}
    assert (warehouse.dry_runs, warehouse.executions) == (1, 1)
