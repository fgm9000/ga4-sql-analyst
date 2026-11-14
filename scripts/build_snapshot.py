"""Build src/ga4_sql_analyst/data/snapshot.json by running the 4 scenarios in PT and EN.

Offline (default): DuckDB over the local Parquet sample plus a deterministic FunctionModel.
Live: real BigQuery plus Vertex AI (billed; run only with Application Default Credentials):
    uv run python scripts/build_snapshot.py --live --project P --model-id M --location L
"""

import argparse
import asyncio
import json
import re
from pathlib import Path

from pydantic_ai import models
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from ga4_sql_analyst.llm import PydanticAiSqlGenerator, PydanticAiSummarizer, build_vertex_model
from ga4_sql_analyst.models import AskRequest, Lang
from ga4_sql_analyst.ports import Warehouse
from ga4_sql_analyst.scenarios import SCENARIOS, Scenario
from ga4_sql_analyst.service import AskService
from ga4_sql_analyst.snapshot import DEFAULT_SNAPSHOT_PATH, Snapshot, SnapshotEntry, dump_entries
from ga4_sql_analyst.warehouse import DuckDbWarehouse, create_bigquery_warehouse

DEFAULT_PARQUET = Path("tests/fixtures/ga4_sample.parquet")
DEFAULT_LOCATION = "global"
MAX_BYTES = 400_000_000  # ADR 002: per-query billing ceiling
RESULT_PATTERN = re.compile(r"<query_result>(.*)</query_result>", re.DOTALL)
SUMMARY_TEXT: dict[Lang, str] = {
    "pt": "Resultado principal: {key} = {value}.",
    "en": "Top result: {key} = {value}.",
}
EMPTY_TEXT: dict[Lang, str] = {"pt": "Nenhum resultado encontrado.", "en": "No results found."}


def _prompt_text(messages: list[ModelMessage]) -> str:
    return "\n".join(
        str(part.content)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, UserPromptPart)
    )


def _scenario_sql(prompt: str) -> str:
    for scenario in SCENARIOS:
        if any(question in prompt for question in scenario.question.values()):
            return scenario.offline_sql
    raise ValueError("no scenario matches the prompt")


def _summary_text(prompt: str, lang: Lang) -> str:
    match = RESULT_PATTERN.search(prompt)
    rows = json.loads(match.group(1)) if match is not None else []
    if not rows:
        return EMPTY_TEXT[lang]
    key, value = next(iter(rows[0].items()))
    return SUMMARY_TEXT[lang].format(key=key, value=value)


def _offline_handler(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    prompt = _prompt_text(messages)
    lang: Lang = "pt" if "português" in (info.instructions or "") else "en"
    args: dict[str, str | list[str]]
    if "<query_result>" in prompt:
        args = {"summary": _summary_text(prompt, lang)}
    else:
        args = {"sql": _scenario_sql(prompt), "tables": ["events_*"], "intent": "offline demo"}
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(args))])


def _build_service(warehouse: Warehouse, model: Model) -> AskService:
    return AskService(
        PydanticAiSqlGenerator(model),
        PydanticAiSummarizer(model),
        warehouse,
        Snapshot([]),
        MAX_BYTES,
    )


async def _run_scenario(service: AskService, scenario: Scenario, lang: Lang) -> SnapshotEntry:
    question = scenario.question[lang]
    response = await service.ask(AskRequest(question=question, lang=lang))
    entry = SnapshotEntry(
        scenario=scenario.scenario, lang=lang, question=question, response=response
    )
    print(f"scenario {scenario.scenario} [{lang}]: {response.status} {response.reason or ''}")
    return entry


async def _run_all(service: AskService) -> list[SnapshotEntry]:
    entries: list[SnapshotEntry] = []
    for scenario in SCENARIOS:
        for lang in scenario.question:
            entries.append(await _run_scenario(service, scenario, lang))
    return entries


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="DuckDB + FunctionModel (default)")
    mode.add_argument("--live", action="store_true", help="BigQuery + Vertex AI (billed)")
    parser.add_argument("--project")
    parser.add_argument("--model-id")
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET)
    parser.add_argument("--output", type=Path, default=DEFAULT_SNAPSHOT_PATH)
    return parser.parse_args()


def _live_service(args: argparse.Namespace) -> AskService:
    if not args.project or not args.model_id:
        raise SystemExit("--live requires --project and --model-id")
    model = build_vertex_model(args.model_id, args.project, args.location)
    return _build_service(create_bigquery_warehouse(args.project), model)


def _offline_service(parquet: Path) -> AskService:
    models.ALLOW_MODEL_REQUESTS = False
    return _build_service(DuckDbWarehouse(parquet), FunctionModel(_offline_handler))


def main() -> None:
    args = _parse_args()
    service = _live_service(args) if args.live else _offline_service(args.parquet)
    entries = asyncio.run(_run_all(service))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    dump_entries(entries, args.output)
    print(f"wrote {len(entries)} entries to {args.output}")


if __name__ == "__main__":
    main()
