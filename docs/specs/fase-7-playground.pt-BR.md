# Especificação da Fase 7 — Static Web Playground

> Base: PRD §5 (4 cenários), RF-07, RF-08, RNF-05, ADR 005, Padrão Mestre §5. Escrita pelo orquestrador em 2026-11-14.
> **Decisão de hospedagem (Fabio, 2026-11-14):** o GitHub Pages não funciona com o repo privado no plano atual (HTTP 422). Até a Fase 10, o playground é servido **pelo próprio Cloud Run em `/app/`** (mesma origem, sem CORS). O `pages.yml` fica pronto para quando o repo abrir.

## Regras gerais
- `web/` na raiz é a fonte da verdade: `index.html`, `app.js`, `input.css`, `styles.css` (Tailwind **pré-compilado** e commitado), `examples.json`.
- HTML semântico + Vanilla JS moderno (ES2022, módulo único, sem bundler, sem framework, **sem nenhuma CDN**). Nenhum `<script>` inline, nenhum `style=""` inline, nenhum `onclick=` inline (CSP estrita). Nada de `innerHTML` com dado vindo da API: construir DOM com `document.createElement`/`textContent` (a pergunta, o SQL e o resumo são dados não confiáveis).
- Bilíngue: PT padrão, EN alternável no cabeçalho **sem recarregar**, 100% dos textos via dicionário `I18N` em `app.js` (atributos `data-i18n`). Lembrar a escolha em `localStorage` (com `try/catch`).
- Visual: usar o padrão visual da demo 1 (`/c/Users/fabio/development/ad-copy-grader/web/`, só leitura) como referência de estilo e organização, **sem copiar textos ou cenários** (o domínio é outro).
- Acessível: botões são `<button>`, contraste AA, `aria-live="polite"` na área de resultado, foco visível.

## Estrutura da página
1. **Cabeçalho:** nome "GA4 SQL Analyst", subtítulo "Text-to-SQL com autoridade do código" (EN: "Text-to-SQL with code authority"), link "API (/docs) ↗", toggle 🇧🇷 PT / 🇺🇸 EN.
2. **Banner de 3 passos** (regra dos 30 segundos): (1) Escolha um cenário; (2) Veja o SQL e cada verificação — quem decidiu, o código ou o LLM; (3) Tente quebrar: pergunta livre ou o botão de injeção.
3. **Cenários** (`examples.json`): 4 cards com as perguntas PT/EN de `src/ga4_sql_analyst/scenarios.py` (leia as strings exatas de lá), um rótulo curto e uma frase do que observar:
   - 1 Caminho feliz — "a âncora transforma 'últimos 30 dias' em 02/01–31/01/2021";
   - 2 Caso complexo — "funil com várias etapas por dispositivo";
   - 3 **Diferencial** — "o custo é estimado antes de gastar; acima do teto, nada roda";
   - 4 Injeção — botão "Tentar injeção" (ver abaixo).
4. **Pergunta livre:** `<textarea>` (3–500 caracteres, contador), seletor de idioma da pergunta = idioma da UI, botão "Perguntar".
5. **Resultado** (`aria-live`):
   - selo de status: `answered` (verde), `blocked` (âmbar, com o motivo traduzido), `unavailable` (cinza);
   - aviso "Resposta em cache" quando `degraded: true`;
   - **período** resolvido (quando houver), com a etiqueta "âncora do código";
   - **SQL** em `<pre><code>` com destaque de sintaxe por função local pequena (palavras-chave, strings, números, comentários) feita com spans via `createElement` (sem regex que gere HTML);
   - **lista de verificações** C01–C06: nome legível PT/EN, passou/falhou, `detail` legível, e o selo de autoridade "Verificado pelo Código" / "Verified by Code" (todas aqui são `code`);
   - **medidor de custo** (C05): barra com bytes estimados vs. teto — o teto sai do `detail` (`billed=X max=Y`), sem número fixo no frontend; formatar em MB/GB; vermelho quando acima;
   - **tabela** das linhas (`rows`), até 100;
   - **resumo**, com `[?]` destacado e uma nota "número sem lastro removido pelo código" quando C06 falhar.
6. **Cenário 4 — "Tentar injeção" (RF-08):** um clique faz duas chamadas e mostra **duas colunas**:
   - Camada 1 — `POST /v1/ask` com a pergunta de injeção: mostra o SQL inofensivo gerado ("o LLM ignorou o pedido").
   - Camada 2 — `POST /v1/validate` com `DELETE FROM \`bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*\` WHERE true`: mostra `is_valid: false`, `not_select`, selo "Verificado pelo Código".
   - Texto curto: "Mesmo que o LLM obedecesse, o código recusaria."
7. **"Como o código funciona por baixo"** (Under the Hood): 4 cards ligando o que se vê aos módulos reais: `sql_rules.py`/`domain.py` (C01–C06), `llm.py` (PydanticAI + Vertex AI, nova tentativa com o erro devolvido), `service.py` (8 passos, degradação), `evals/` + CI (recall de bloqueio 1,0 e falso bloqueio 0,0, catraca 100%).
8. **Rodapé:** "Dados: Google Merchandise Store, nov/2020–jan/2021 (amostra pública ofuscada do GA4)". Link do repositório **não** (está privado).

## Comportamento de rede
- `API_BASE`: string vazia (mesma origem) por padrão; se `location.hostname` termina em `github.io`, usar `https://ga4-sql-analyst-7l7x7llydq-uc.a.run.app`. Constante no topo do `app.js`.
- Timeout de 60 s (`AbortController`). Se a resposta demorar > 3 s, mostrar "Acordando o servidor (primeira visita pode levar alguns segundos)…" (RNF-05).
- `429`: mostrar o motivo traduzido (`rate_limited`, `daily_quota`, `daily_llm_quota`) e o `Retry-After` em segundos.
- Erro de rede ou 5xx: mensagem clara, sem stack.

## Servir pelo Cloud Run
- `settings.py`: novo campo `web_dir: Path = Path("web")`.
- `api.py` (em `create_app`): se `settings.web_dir` existir, montar `StaticFiles(directory=..., html=True)` em `/app` e um `GET /app` → redirect para `/app/`. Middleware que, **só para respostas de `/app`**, adiciona `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`, `X-Content-Type-Options: nosniff` e `Referrer-Policy: no-referrer`.
- `GET /` continua redirecionando para `/docs` (Padrão Mestre).
- `Dockerfile`: copiar `web/` para `/app/web` no estágio runtime (`COPY --chown=appuser:appgroup web ./web`) e tirar `web` do `.dockerignore` (manter `web/input.css` fora se quiser; não é obrigatório).
- Testes (`tests/test_api_web.py`): `/app/` devolve o `index.html` com o CSP; `/app` redireciona; `/app/app.js` servido; `/v1/ask` **não** recebe o header CSP; app sem `web_dir` não monta a rota (404). 100% de cobertura mantida.

## `pages.yml` (pronto para a Fase 10)
Porte o `.github/workflows/pages.yml` da demo 1 publicando `web/`. Como o repo é privado, proteger o job com `if: github.event.repository.private == false` (igual ao CodeQL).

## Tailwind
- Compilar `web/styles.css` a partir de `web/input.css` com o Tailwind CLI v4 com **versão exata** (`npx --yes @tailwindcss/cli@<versão> -i web/input.css -o web/styles.css --minify`), escolhendo uma versão publicada há ≥ 2 semanas. Documentar o comando num comentário no topo do `input.css`.
- `web/styles.css` é commitado (gerado). O CI não precisa de Node.

## Verificação
```
uv run ruff format --check . && uv run ruff check . && uv run mypy
uv run pytest --cov=ga4_sql_analyst -q
uv run python scripts/quality_baseline.py && uv run python scripts/quality_check.py
grep -nE "<script>|onclick=|style=\"|innerHTML|cdn\.|https://unpkg|jsdelivr" web/index.html web/app.js || echo clean
GA4_OFFLINE=1 uv run uvicorn ga4_sql_analyst.api:app_factory --factory --port 8077   # abrir http://localhost:8077/app/
```
