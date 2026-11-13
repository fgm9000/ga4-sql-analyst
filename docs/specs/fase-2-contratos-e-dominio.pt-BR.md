# Especificação da Fase 2 — Contratos (`models.py`) e domínio puro (`domain.py`)

> Base: PRD v1.0 (P4, RF-02, RF-04, RF-06), ADR 002 (C01–C06), `docs/spikes.pt-BR.md` (spikes 2 e 4). Escrita pelo orquestrador em 2026-11-13. Executores seguem à risca; dúvida = parar e perguntar.

## Regras gerais
- Pacote: `src/ga4_sql_analyst/`. Python 3.12, `mypy --strict`, Ruff do `pyproject.toml`.
- **Proibido:** `# type: ignore`, `# noqa`, `# pragma: no cover`, `pyright: ignore`, `typing.Any` explícito, `cast` para contornar erro, desligar checagem por config.
- `domain.py`: **zero I/O**, zero rede, zero estado global mutável, zero `datetime.now()`.
- Funções ≤ 40 linhas (máx. 60), aninhamento ≤ 3 níveis, constantes em `UPPER_SNAKE_CASE` no topo, booleanos com prefixo `is_/has_/can_/should_`.
- Testes em `tests/` (ali `assert` é permitido). Meta: **100% de cobertura de linhas** em `models.py` e `domain.py`.

## 1. `models.py`
Todos os modelos: `model_config = ConfigDict(frozen=True, extra="forbid")`.

```text
Lang = Literal["pt", "en"]
Status = Literal["answered", "blocked", "unavailable"]
Authority = Literal["code", "llm"]
CheckId = Literal["C01_select_only", "C02_allowed_tables", "C03_limit",
                  "C04_date_anchor", "C05_cost_ceiling", "C06_summary_numbers"]
CellValue = str | int | float | bool | None

QUESTION_MIN_CHARS = 3
QUESTION_MAX_CHARS = 500
SQL_MAX_CHARS = 4000
INTENT_MAX_CHARS = 200

AskRequest:   question: str; lang: Lang = "pt"
              validator (mode="before" em question): unicodedata.normalize("NFC"), strip,
              colapsar qualquer sequência de whitespace em 1 espaço; depois validar
              QUESTION_MIN_CHARS <= len <= QUESTION_MAX_CHARS (erro de validação Pydantic).
SqlDraft:     sql: str (1..SQL_MAX_CHARS); tables: list[str]; intent: str (1..INTENT_MAX_CHARS)
Period:       start: date; end: date; anchored: bool
              validator de modelo: start <= end.
CheckResult:  id: CheckId; passed: bool; authority: Authority = "code";
              detail: str | None = None; bytes_estimated: int | None = None
AskResponse:  status: Status; period: Period | None = None; sql: str | None = None;
              checks: list[CheckResult] = []; rows: list[dict[str, CellValue]] = [];
              summary: str | None = None; degraded: bool = False; reason: str | None = None
```
Testes (`tests/test_models.py`): normalização NFC (ex.: "e" + U+0301 vira "é"), colapso de espaços, limites min/max, `lang` inválido, `extra` proibido, `frozen`, `Period` com start > end.

## 2. `domain.py`

### Constantes
```text
DATASET_START = date(2020, 11, 1)
DATASET_END = date(2021, 1, 31)          # "hoje" da demo
ALLOWED_PROJECT = "bigquery-public-data"
ALLOWED_DATASET = "ga4_obfuscated_sample_ecommerce"
WILDCARD_TABLE = "events_*"
DAILY_TABLE_PATTERN = re.compile(r"events_\d{8}")   # fullmatch
LOCAL_TABLE = "events"
MAX_ROWS = 100
MIN_BILLED_BYTES = 10 * 1024**2          # medido no spike 2: mínimo por query
```

### 2.1 `validate_sql(sql: str) -> SqlValidation` — C01, C02, C03
`SqlValidation`: dataclass frozen (ou BaseModel frozen) com `is_valid: bool`, `sql: str` (SQL final em dialeto BigQuery, já com LIMIT aplicado; igual à entrada se inválido), `checks: tuple[CheckResult, ...]` (sempre C01, C02, C03 nessa ordem; os não avaliados por falha anterior saem com `passed=False, detail="not_evaluated"`), `reason: str | None`.

Ordem e regras:
1. **C01 — somente leitura** (`detail` = código do motivo):
   - `sqlglot.parse(sql, read="bigquery")` levanta erro → `parse_error`.
   - Número de statements não-`None` ≠ 1 → `multiple_statements`.
   - Raiz não é `exp.Select` nem operação de conjunto (`exp.Union`/`exp.Intersect`/`exp.Except`) — inclusive com `WITH` → `not_select`.
   - Qualquer nó na árvore inteira de tipo DML/DDL/comando (`exp.Insert`, `exp.Update`, `exp.Delete`, `exp.Merge`, `exp.Drop`, `exp.Create`, `exp.Alter`, `exp.Command`, `exp.TruncateTable` — confirmar os nomes existentes no sqlglot 30.31.0 e listar só os que existem) → `forbidden_statement`.
2. **C02 — tabelas permitidas:** todo `exp.Table` da árvore, exceto referências a nomes de CTE do próprio `WITH`, precisa ter `catalog == ALLOWED_PROJECT`, `db == ALLOWED_DATASET` e nome `== WILDCARD_TABLE` ou `fullmatch(DAILY_TABLE_PATTERN)`. Comparação case-insensitive. Falha → `detail="table_not_allowed:<nome completo>"`. Falta de catalog/db também falha.
3. **C03 — LIMIT** (nunca bloqueia; `passed=True` sempre que avaliado):
   - Query externa sem LIMIT → injeta `LIMIT MAX_ROWS`, `detail="limit_injected"`.
   - LIMIT literal > MAX_ROWS → substitui por MAX_ROWS, `detail="limit_capped"`.
   - LIMIT não literal → substitui por MAX_ROWS, `detail="limit_capped"`.
   - Caso contrário `detail=None`.
   - SQL final: `.sql(dialect="bigquery")`.

### 2.2 `resolve_period(question: str) -> Period | None` — C04
Determinístico, PT e EN, case-insensitive, aceita com ou sem acento. Âncora: `DATASET_END`. Primeira expressão encontrada vence. `anchored=True` sempre que retornar.

| Expressão (PT / EN) | start | end |
|---|---|---|
| `hoje` / `today` | DATASET_END | DATASET_END |
| `ontem` / `yesterday` | END − 1 | END − 1 |
| `últimos N dias` / `last N days` (N dígitos) | END − (N − 1) | END |
| `última semana` / `last week` | END − 6 | END |
| `este mês` / `this month` | 1º dia do mês de END | END |
| `último mês` / `mês passado` / `last month` | 1º dia do mês anterior | último dia do mês anterior |
| `último trimestre` / `last quarter` | 1º dia do trimestre civil anterior | último dia dele |
| nada disso | → `None` | |

Depois: `start = max(start, DATASET_START)`; se `start > end` após o clamp (ex.: "últimos 500 dias" não gera isso, mas trimestre totalmente antes do dataset sim) → retornar período `DATASET_START..DATASET_START`? **Não**: retornar `None` (fora do dataset; o LLM/usuário decide). N = 0 → `None`.

Também: `period_bounds(period: Period) -> tuple[str, str]` → (`"YYYYMMDD"`, `"YYYYMMDD"`) para `_TABLE_SUFFIX`.

Casos obrigatórios nos testes: "últimos 30 dias" → 2021-01-02..2021-01-31; "ultimos 7 dias"; "last 7 days"; "ontem" → 2021-01-30; "último mês" → 2020-12-01..2020-12-31; "último trimestre" → 2020-10-01 clampado → 2020-11-01..2020-12-31; "últimos 200 dias" → clamp em 2020-11-01; "este mês" → 2021-01-01..2021-01-31; "Qual canal trouxe mais receita?" → None; "últimos 0 dias" → None.

### 2.3 `rewrite_for_duckdb(bigquery_sql: str) -> str`
Portar a lógica de `spikes/transpile.py` (reescritas na AST, sem regex/replace de string):
1. tabela curinga **ou diária permitida** → `LOCAL_TABLE`; para tabela diária `events_YYYYMMDD`, adicionar o filtro equivalente é **fora do escopo** — basta trocar pelo `LOCAL_TABLE` e documentar em docstring que a query diária na amostra lê o período todo (só testes usam isso);
2. coluna `_TABLE_SUFFIX` → `event_date`;
3. `UNNEST` sem alias dentro de `FROM` → `(SELECT UNNEST(x, max_depth := 2))`;
4. `.sql(dialect="duckdb")`.
Testes: as 4 queries do spike 4 executadas no DuckDB sobre `tests/fixtures/ga4_sample.parquet` (via `duckdb.connect()` + `read_parquet(...).create_view("events")`) com ≥ 1 linha cada. Execução em teste é permitida (I/O fica no teste, não em `domain.py`).

### 2.4 `check_cost(bytes_estimated: int, max_bytes: int) -> CheckResult` — C05
`billed = max(bytes_estimated, MIN_BILLED_BYTES)`; `passed = billed <= max_bytes`; `bytes_estimated=bytes_estimated`; `detail = f"billed={billed} max={max_bytes}"`. `bytes_estimated < 0` ou `max_bytes <= 0` → `ValueError`. Testes: 0 bytes (cobrado 10 MiB), exatamente no teto, 1 byte acima, 3_583_657_854 com teto 400_000_000 → falha.

### 2.5 `ground_summary_numbers(summary: str, rows: Sequence[Mapping[str, CellValue]], lang: Lang, context_numbers: frozenset[float]) -> tuple[str, CheckResult]` — C06
- Extrair números do resumo conforme `lang`: `pt` → milhar `.` e decimal `,` (ex.: `1.234,56`, `12,5%`); `en` → milhar `,` e decimal `.` (ex.: `1,234.56`, `12.5%`). Inteiros simples também. Sinal negativo opcional.
- Valores de referência: todo `int`/`float` (não `bool`) das linhas, mais `context_numbers` (números da pergunta e do período, ex.: 30, 2021).
- Número do resumo é **ancorado** se: (a) existe valor de referência `v` com `abs(n − v) <= REL_TOLERANCE * max(abs(v), 1)` onde `REL_TOLERANCE = 0.005`; ou (b) o número tem `%` e existe `v` com `abs(n − v*100) <= REL_TOLERANCE * max(abs(v*100), 1)` (razões vindas como 0–1); ou (c) arredondar `v` para as casas decimais escritas no resumo dá exatamente `n`.
- Números não ancorados: substituir no texto o token original por `[?]`. `CheckResult(id="C06_summary_numbers", passed=<nenhum não ancorado>, detail=None ou "ungrounded:<tokens separados por vírgula>")`.
- Testes: resumo PT e EN totalmente ancorado; número inventado vira `[?]`; percentual derivado de razão 0,1234 → "12,3%" ancorado; ano da pergunta em `context_numbers` não é marcado; bool nas linhas é ignorado; resumo sem números.

## 3. Casos adversariais obrigatórios (C01/C02) em `tests/test_domain_sql.py`
Cada um com o `detail` esperado:
1. `DELETE FROM ...events_* WHERE true` → `forbidden_statement` ou `not_select`
2. `DROP TABLE x` → idem
3. `SELECT 1; DROP TABLE x` → `multiple_statements`
4. `INSERT INTO x SELECT * FROM ...events_*` → `not_select`/`forbidden_statement`
5. `CREATE TABLE x AS SELECT ...` → idem
6. `MERGE ...` → idem
7. `SELECT * FROM \`other-project.ds.t\`` → `table_not_allowed:...`
8. `SELECT * FROM \`bigquery-public-data.ga4_obfuscated_sample_ecommerce.INFORMATION_SCHEMA.TABLES\`` → C02 falha
9. `SELECT * FROM events_*` (sem projeto/dataset) → C02 falha
10. Subquery ou `UNION ALL` com tabela não permitida → C02 falha
11. CTE `WITH t AS (SELECT ... FROM ...events_*) SELECT * FROM t` → passa
12. Comentário contendo `DROP TABLE` em query SELECT válida → passa
13. Palavras em minúsculas / caixa mista → mesmo resultado
14. `SELECT ... LIMIT 5000` → passa com `limit_capped` e SQL final com `LIMIT 100`
15. String vazia e lixo (`"not sql at all ;;"`) → `parse_error` ou `not_select`
16. Script BigQuery (`DECLARE x INT64; SELECT 1`) → `multiple_statements` ou `parse_error`
Usar a tabela completa com crases: `` `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*` ``.

## 4. Verificação (todas obrigatórias)
```
uv run ruff format --check . && uv run ruff check .
uv run mypy
uv run pytest --cov=ga4_sql_analyst --cov-report=term-missing -q
grep -rnE "type: ignore|noqa|pragma: no cover|pyright: ignore" src tests || echo zero
```
Cobertura de `models.py` e `domain.py`: 100%.
