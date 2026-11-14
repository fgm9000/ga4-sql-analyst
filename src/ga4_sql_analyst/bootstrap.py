"""Composition root: builds the AskService for live or offline mode from Settings."""

from ga4_sql_analyst.cache import CachingWarehouse
from ga4_sql_analyst.llm import PydanticAiSqlGenerator, PydanticAiSummarizer, build_vertex_model
from ga4_sql_analyst.offline import build_offline_service
from ga4_sql_analyst.service import AskService
from ga4_sql_analyst.settings import Settings
from ga4_sql_analyst.snapshot import Snapshot
from ga4_sql_analyst.warehouse import create_bigquery_warehouse


def build_service(settings: Settings) -> AskService:
    """Offline: DuckDB + deterministic model. Live: cached BigQuery + Vertex AI + snapshot."""
    if settings.offline:
        return build_offline_service(settings.sample_path, settings.max_bytes_billed)
    model = build_vertex_model(settings.model_id, settings.gcp_project, settings.vertex_location)
    warehouse = CachingWarehouse(
        create_bigquery_warehouse(settings.gcp_project), settings.cache_max_entries
    )
    return AskService(
        PydanticAiSqlGenerator(model),
        PydanticAiSummarizer(model),
        warehouse,
        Snapshot.load(),
        settings.max_bytes_billed,
    )
