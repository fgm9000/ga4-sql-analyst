/**
 * GA4 SQL Analyst playground.
 *
 * Plain ES module, no bundler and no CDN. Everything that comes from the API (question, SQL,
 * rows, summary) is untrusted: the DOM is built with createElement/textContent only.
 */

const API_BASE = location.hostname.endsWith("github.io")
  ? "https://ga4-sql-analyst-7l7x7llydq-uc.a.run.app"
  : "";
const REQUEST_TIMEOUT_MS = 60_000;
const WAKE_NOTICE_MS = 3_000;
const QUESTION_MIN = 3;
const QUESTION_MAX = 500;
const MAX_ROWS = 100;
const LANG_KEY = "ga4-playground-lang";
const DEFAULT_LANG = "pt";
const UNGROUNDED_MARKER = "[?]";
const CHECK_ORDER = [
  "C01_select_only",
  "C02_allowed_tables",
  "C03_limit",
  "C04_date_anchor",
  "C05_cost_ceiling",
  "C06_summary_numbers",
];
const INJECTION_SCENARIO = 4;
const SQL_KEYWORDS = new Set(
  (
    "SELECT FROM WHERE GROUP BY ORDER LIMIT OFFSET HAVING JOIN LEFT RIGHT INNER OUTER FULL CROSS ON " +
    "USING AS AND OR NOT IN IS NULL BETWEEN LIKE CASE WHEN THEN ELSE END DISTINCT UNION ALL WITH " +
    "OVER PARTITION ASC DESC TRUE FALSE UNNEST INTERVAL EXISTS DELETE INSERT UPDATE DROP CREATE " +
    "ALTER TRUNCATE MERGE INTO VALUES SET"
  ).split(" "),
);

const I18N = {
  pt: {
    subtitle: "Text-to-SQL com autoridade do código",
    apiLink: "API (/docs) ↗",
    backToGithub: "← Mais projetos no GitHub",
    introTitle: "O que é isto",
    introP1: "Faça uma pergunta, em português ou inglês, sobre o tráfego e as vendas de uma loja online e receba a resposta junto com o SQL que a gerou. Os dados são a amostra pública e anonimizada do Google Analytics 4 que o Google disponibiliza no BigQuery: a Google Merchandise Store de 1º/11/2020 a 31/01/2021, com 92 tabelas diárias, cerca de 4,3 milhões de eventos e 3,6 GB.",
    introP2: "Sua pergunta vai para uma API que eu construí (FastAPI no Google Cloud Run). Um LLM (Gemini no Vertex AI) escreve o SQL, e o código decide se ele pode rodar: só leitura, só esta tabela, período válido e no máximo 400 MB lidos por consulta. Só então a consulta roda no BigQuery, e o código ainda confere os números do resumo antes de mostrar a resposta.",
    stepsTitle: "Explore em 30 segundos",
    step1: "Escolha um cenário.",
    step2: "Veja o SQL e cada verificação: quem decidiu, o código ou o LLM.",
    step3: "Tente quebrar: pergunta livre ou o botão de injeção.",
    scenariosTitle: "Cenários",
    observeLabel: "Observe:",
    runBtn: "Executar",
    injectBtn: "Tentar injeção",
    askTitle: "Pergunta livre",
    questionLabel: "Sua pergunta sobre os dados do GA4",
    questionPlaceholder: "Ex.: Qual dispositivo converte mais?",
    askBtn: "Perguntar",
    resultTitle: "Resultado",
    hoodTitle: "Como o código funciona por baixo",
    hood1:
      "As verificações C01–C06 são funções puras do código: só SELECT, só a tabela permitida, LIMIT, âncora de datas, teto de custo e números do resumo com lastro.",
    hood2:
      "PydanticAI sobre o Vertex AI gera o SQL e o resumo; se o código rejeitar a saída, o erro volta ao modelo para uma nova tentativa.",
    hood3:
      "Orquestra 8 passos (período, geração, validação, estimativa de custo, execução, resumo, números) e degrada para a última resposta gravada quando um serviço cai.",
    hood4:
      "Um conjunto de avaliação mede o recall de bloqueio (1,0) e o falso bloqueio (0,0); o CI aplica uma catraca de cobertura de 100%.",
    footer:
      "Dados: Google Merchandise Store, nov/2020–jan/2021 (amostra pública ofuscada do GA4).",
    wake: "Acordando o servidor (primeira visita pode levar alguns segundos)…",
    loading: "Consultando…",
    statusAnswered: "Respondida",
    statusBlocked: "Bloqueada",
    statusUnavailable: "Indisponível",
    blockedBecause: "Motivo",
    cached: "Resposta em cache (o serviço de IA está indisponível ou no limite diário).",
    periodTitle: "Período resolvido",
    anchorTag: "âncora do código",
    sqlTitle: "SQL",
    noSql: "Nenhum SQL foi produzido: o código barrou antes.",
    checksTitle: "Verificações",
    checkPassed: "passou",
    checkFailed: "falhou",
    byCode: "Verificado pelo Código",
    byLlm: "Verificado pelo LLM",
    costTitle: "Custo estimado vs. teto",
    costDetail: "estimado {billed} de um teto de {max}",
    costAbove: "acima do teto: nada foi executado",
    rowsTitle: "Linhas",
    rowsCount: "{n} linha(s)",
    summaryTitle: "Resumo",
    ungroundedNote: "número sem lastro removido pelo código",
    layer1Title: "Camada 1: o LLM",
    layer1Note: "POST /v1/ask com a pergunta de injeção. O LLM ignorou o pedido?",
    layer2Title: "Camada 2: o código",
    layer2Note: "POST /v1/validate com um DELETE direto, como se o LLM tivesse obedecido.",
    injectionClosing: "Mesmo que o LLM obedecesse, o código recusaria.",
    validateInvalid: "SQL recusado",
    validateValid: "SQL aceito",
    errNetwork: "Não foi possível falar com o servidor. Verifique a conexão e tente de novo.",
    errTimeout: "O servidor demorou mais de 60 s. Tente de novo em instantes.",
    errServer: "O servidor teve um problema (código {status}). Tente de novo em instantes.",
    errRate: "Limite de uso atingido: {reason}. Tente de novo em {seconds} s.",
    errRateNoWait: "Limite de uso atingido: {reason}.",
    errExamples: "Não foi possível carregar os cenários.",
    checkNames: {
      C01_select_only: "C01 Somente SELECT",
      C02_allowed_tables: "C02 Tabelas permitidas",
      C03_limit: "C03 Limite de linhas",
      C04_date_anchor: "C04 Âncora de datas",
      C05_cost_ceiling: "C05 Teto de custo",
      C06_summary_numbers: "C06 Números do resumo",
    },
    codes: {
      no_relative_period: "nenhum período relativo na pergunta",
      limit_injected: "LIMIT adicionado pelo código",
      limit_capped: "LIMIT reduzido ao máximo permitido",
      not_evaluated: "não avaliada (uma verificação anterior falhou)",
      not_select: "só consultas SELECT são aceitas",
      forbidden_statement: "comando proibido",
      multiple_statements: "mais de um comando",
      parse_error: "SQL que não pôde ser lido",
      forbidden_function: "função proibida",
      table_not_allowed: "tabela não permitida",
      no_allowed_table: "nenhuma tabela permitida na consulta",
      cost_ceiling: "custo estimado acima do teto",
      llm_unavailable: "serviço de IA indisponível",
      warehouse_unavailable: "banco de dados indisponível",
      summary_unavailable: "resumo indisponível",
      rate_limited: "muitas requisições por minuto",
      daily_quota: "cota diária de requisições esgotada",
      daily_llm_quota: "cota diária do LLM esgotada",
      ungrounded: "número sem lastro",
    },
  },
  en: {
    subtitle: "Text-to-SQL with code authority",
    apiLink: "API (/docs) ↗",
    backToGithub: "← More projects on GitHub",
    introTitle: "What this is",
    introP1: "Ask a question, in English or Portuguese, about an online store's traffic and sales and get the answer together with the SQL that produced it. The data is the public, anonymized Google Analytics 4 sample that Google publishes on BigQuery: the Google Merchandise Store from Nov 1, 2020 to Jan 31, 2021, with 92 daily tables, about 4.3 million events and 3.6 GB.",
    introP2: "Your question goes to an API I built (FastAPI on Google Cloud Run). An LLM (Gemini on Vertex AI) writes the SQL, and code decides whether it may run: read-only, this table only, a valid date range and at most 400 MB read per query. Only then does the query run on BigQuery, and code still checks the numbers in the summary before showing the answer.",
    stepsTitle: "Explore in 30 seconds",
    step1: "Pick a scenario.",
    step2: "See the SQL and every check: who decided, the code or the LLM.",
    step3: "Try to break it: free question or the injection button.",
    scenariosTitle: "Scenarios",
    observeLabel: "Watch for:",
    runBtn: "Run",
    injectBtn: "Try injection",
    askTitle: "Free question",
    questionLabel: "Your question about the GA4 data",
    questionPlaceholder: "E.g.: Which device converts best?",
    askBtn: "Ask",
    resultTitle: "Result",
    hoodTitle: "How the code works under the hood",
    hood1:
      "Checks C01–C06 are pure code functions: SELECT only, only the allowed table, LIMIT, date anchor, cost ceiling and summary numbers traced to the data.",
    hood2:
      "PydanticAI on Vertex AI generates the SQL and the summary; if the code rejects the output, the error goes back to the model for another attempt.",
    hood3:
      "Orchestrates 8 steps (period, generation, validation, cost estimate, execution, summary, numbers) and degrades to the last recorded answer when a service is down.",
    hood4:
      "An evaluation suite measures block recall (1.0) and false blocks (0.0); CI enforces a 100% coverage ratchet.",
    footer:
      "Data: Google Merchandise Store, Nov 2020 – Jan 2021 (public obfuscated GA4 sample).",
    wake: "Waking up the server (the first visit can take a few seconds)…",
    loading: "Querying…",
    statusAnswered: "Answered",
    statusBlocked: "Blocked",
    statusUnavailable: "Unavailable",
    blockedBecause: "Reason",
    cached: "Cached answer (the AI service is unavailable or at its daily limit).",
    periodTitle: "Resolved period",
    anchorTag: "code anchor",
    sqlTitle: "SQL",
    noSql: "No SQL was produced: the code stopped it first.",
    checksTitle: "Checks",
    checkPassed: "passed",
    checkFailed: "failed",
    byCode: "Verified by Code",
    byLlm: "Verified by LLM",
    costTitle: "Estimated cost vs. ceiling",
    costDetail: "estimated {billed} against a ceiling of {max}",
    costAbove: "above the ceiling: nothing was executed",
    rowsTitle: "Rows",
    rowsCount: "{n} row(s)",
    summaryTitle: "Summary",
    ungroundedNote: "ungrounded number removed by the code",
    layer1Title: "Layer 1: the LLM",
    layer1Note: "POST /v1/ask with the injection question. Did the LLM ignore the request?",
    layer2Title: "Layer 2: the code",
    layer2Note: "POST /v1/validate with a direct DELETE, as if the LLM had obeyed.",
    injectionClosing: "Even if the LLM obeyed, the code would refuse.",
    validateInvalid: "SQL rejected",
    validateValid: "SQL accepted",
    errNetwork: "Could not reach the server. Check your connection and try again.",
    errTimeout: "The server took more than 60 s. Try again shortly.",
    errServer: "The server had a problem (code {status}). Try again shortly.",
    errRate: "Usage limit reached: {reason}. Try again in {seconds} s.",
    errRateNoWait: "Usage limit reached: {reason}.",
    errExamples: "Could not load the scenarios.",
    checkNames: {
      C01_select_only: "C01 SELECT only",
      C02_allowed_tables: "C02 Allowed tables",
      C03_limit: "C03 Row limit",
      C04_date_anchor: "C04 Date anchor",
      C05_cost_ceiling: "C05 Cost ceiling",
      C06_summary_numbers: "C06 Summary numbers",
    },
    codes: {
      no_relative_period: "no relative period in the question",
      limit_injected: "LIMIT added by the code",
      limit_capped: "LIMIT reduced to the allowed maximum",
      not_evaluated: "not evaluated (an earlier check failed)",
      not_select: "only SELECT queries are accepted",
      forbidden_statement: "forbidden statement",
      multiple_statements: "more than one statement",
      parse_error: "SQL could not be parsed",
      forbidden_function: "forbidden function",
      table_not_allowed: "table not allowed",
      no_allowed_table: "no allowed table in the query",
      cost_ceiling: "estimated cost above the ceiling",
      llm_unavailable: "AI service unavailable",
      warehouse_unavailable: "database unavailable",
      summary_unavailable: "summary unavailable",
      rate_limited: "too many requests per minute",
      daily_quota: "daily request quota exhausted",
      daily_llm_quota: "daily LLM quota exhausted",
      ungrounded: "ungrounded number",
    },
  },
};

const BADGE_BASE = "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ";
const BADGE_CODE = BADGE_BASE + "bg-indigo-100 text-indigo-900 border-indigo-300";
const BADGE_LLM = BADGE_BASE + "bg-slate-100 text-slate-800 border-slate-300";
const STATUS_BADGE = {
  answered: BADGE_BASE + "bg-emerald-100 text-emerald-900 border-emerald-300",
  blocked: BADGE_BASE + "bg-amber-100 text-amber-900 border-amber-300",
  unavailable: BADGE_BASE + "bg-slate-200 text-slate-800 border-slate-300",
};
const STATUS_KEY = {
  answered: "statusAnswered",
  blocked: "statusBlocked",
  unavailable: "statusUnavailable",
};
const CARD = "rounded-xl border border-slate-200 bg-white p-4";
const SECTION_TITLE = "text-xs font-bold uppercase tracking-wide text-slate-600 mb-2";
const TOKEN_CLASS = {
  keyword: "text-indigo-700 font-semibold",
  string: "text-emerald-700",
  number: "text-amber-700",
  comment: "text-slate-500 italic",
  identifier: "text-sky-800",
};
const LANG_ACTIVE = "px-2.5 py-1 text-xs font-semibold rounded-md bg-white shadow-2xs text-indigo-700";
const LANG_IDLE = "px-2.5 py-1 text-xs font-semibold rounded-md text-slate-600 hover:text-slate-900";

const state = { lang: DEFAULT_LANG, examples: [], busy: false, view: null };

const byId = (id) => document.getElementById(id);

function t(key) {
  return I18N[state.lang][key];
}

function locale() {
  return state.lang === "pt" ? "pt-BR" : "en-US";
}

function format(template, values) {
  return template.replace(/\{(\w+)\}/g, (_, name) => String(values[name]));
}

function h(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

/* ---------- formatting helpers ---------- */

function formatBytes(bytes) {
  if (bytes >= 1e9) {
    return `${(bytes / 1e9).toLocaleString(locale(), { maximumFractionDigits: 2 })} GB`;
  }
  return `${(bytes / 1e6).toLocaleString(locale(), { maximumFractionDigits: 1 })} MB`;
}

function formatDate(iso) {
  const [year, month, day] = iso.split("-");
  return state.lang === "pt" ? `${day}/${month}/${year}` : iso;
}

function formatCell(value) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "number") {
    return value.toLocaleString(locale(), { maximumFractionDigits: 4 });
  }
  return String(value);
}

function translateCode(code) {
  const separator = code.indexOf(":");
  const base = separator === -1 ? code : code.slice(0, separator);
  const argument = separator === -1 ? "" : code.slice(separator + 1);
  const text = I18N[state.lang].codes[base];
  if (text === undefined) return code;
  return argument ? `${text}: ${argument}` : text;
}

function parseCost(check) {
  const match = /^billed=(\d+) max=(\d+)$/.exec(check.detail ?? "");
  return match ? { billed: Number(match[1]), max: Number(match[2]) } : null;
}

function costText(cost) {
  return format(t("costDetail"), { billed: formatBytes(cost.billed), max: formatBytes(cost.max) });
}

function describeDetail(check) {
  if (!check.detail) return "";
  const cost = parseCost(check);
  if (cost) return costText(cost);
  const range = /^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$/.exec(check.detail);
  if (range) return `${formatDate(range[1])} – ${formatDate(range[2])}`;
  return translateCode(check.detail);
}

/* ---------- SQL highlighting (spans via createElement, no HTML strings) ---------- */

const isWordStart = (c) => /[A-Za-z_@]/.test(c);
const isWordChar = (c) => /[A-Za-z0-9_]/.test(c);
const isDigit = (c) => c >= "0" && c <= "9";

function scanQuoted(sql, start, quote) {
  let i = start + 1;
  while (i < sql.length && sql[i] !== quote) {
    i += sql[i] === "\\" ? 2 : 1;
  }
  return Math.min(i + 1, sql.length);
}

function scanToken(sql, i) {
  const c = sql[i];
  const next = sql[i + 1];
  if (c === "-" && next === "-") {
    const end = sql.indexOf("\n", i);
    return { kind: "comment", end: end === -1 ? sql.length : end };
  }
  if (c === "/" && next === "*") {
    const end = sql.indexOf("*/", i + 2);
    return { kind: "comment", end: end === -1 ? sql.length : end + 2 };
  }
  if (c === "'" || c === '"') return { kind: "string", end: scanQuoted(sql, i, c) };
  if (c === "`") return { kind: "identifier", end: scanQuoted(sql, i, c) };
  if (isDigit(c)) {
    let end = i + 1;
    while (end < sql.length && (isDigit(sql[end]) || sql[end] === ".")) end += 1;
    return { kind: "number", end };
  }
  if (isWordStart(c)) {
    let end = i + 1;
    while (end < sql.length && isWordChar(sql[end])) end += 1;
    const isKeyword = SQL_KEYWORDS.has(sql.slice(i, end).toUpperCase());
    return { kind: isKeyword ? "keyword" : "plain", end };
  }
  return { kind: "plain", end: i + 1 };
}

function highlightSql(sql, target) {
  let i = 0;
  while (i < sql.length) {
    const token = scanToken(sql, i);
    const text = sql.slice(i, token.end);
    if (token.kind === "plain") {
      target.append(document.createTextNode(text));
    } else {
      target.append(h("span", TOKEN_CLASS[token.kind], text));
    }
    i = token.end;
  }
}

/* ---------- result rendering ---------- */

function statusBlock(response) {
  const box = h("div", "flex flex-wrap items-center gap-2");
  box.append(h("span", STATUS_BADGE[response.status], t(STATUS_KEY[response.status])));
  if (response.reason) {
    const reason = h("span", "text-sm text-slate-800");
    reason.append(h("strong", "", `${t("blockedBecause")}: `), translateCode(response.reason));
    box.append(reason);
  }
  return box;
}

function periodBlock(period) {
  const box = h("div", "flex flex-wrap items-center gap-2 text-sm");
  box.append(h("span", "font-semibold text-slate-800", `${t("periodTitle")}:`));
  box.append(
    h("span", "font-mono text-slate-900", `${formatDate(period.start)} – ${formatDate(period.end)}`),
  );
  if (period.anchored) box.append(h("span", BADGE_CODE, t("anchorTag")));
  return box;
}

function sqlBlock(sql) {
  const box = h("div");
  box.append(h("h3", SECTION_TITLE, t("sqlTitle")));
  if (!sql) {
    box.append(h("p", "text-sm text-slate-700", t("noSql")));
    return box;
  }
  const pre = h(
    "pre",
    "sql-wrap rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-900",
  );
  const code = h("code", "font-mono");
  highlightSql(sql, code);
  pre.append(code);
  box.append(pre);
  return box;
}

function checkItem(check) {
  const item = h(
    "li",
    "flex flex-wrap items-start justify-between gap-2 rounded-lg border border-slate-200 p-2 text-sm",
  );
  const left = h("div", "min-w-0");
  const markClass = check.passed ? "font-bold text-emerald-700" : "font-bold text-red-700";
  left.append(
    h("span", markClass, check.passed ? "✓ " : "✗ "),
    h("span", "font-medium text-slate-900", I18N[state.lang].checkNames[check.id]),
    h("span", "sr-only", ` (${check.passed ? t("checkPassed") : t("checkFailed")})`),
  );
  const detail = describeDetail(check);
  if (detail) left.append(h("div", "text-xs text-slate-700 mt-0.5 break-words", detail));
  const isCode = check.authority === "code";
  item.append(left, h("span", isCode ? BADGE_CODE : BADGE_LLM, isCode ? t("byCode") : t("byLlm")));
  return item;
}

function checksBlock(checks) {
  const box = h("div");
  box.append(h("h3", SECTION_TITLE, t("checksTitle")));
  const list = h("ul", "space-y-2");
  const ordered = [...checks].sort(
    (a, b) => CHECK_ORDER.indexOf(a.id) - CHECK_ORDER.indexOf(b.id),
  );
  for (const check of ordered) list.append(checkItem(check));
  box.append(list);
  return box;
}

function costBlock(checks) {
  const check = checks.find((entry) => entry.id === "C05_cost_ceiling");
  const cost = check ? parseCost(check) : null;
  if (!cost) return null;
  const above = cost.billed > cost.max;
  const box = h("div");
  box.append(h("h3", SECTION_TITLE, t("costTitle")));
  const meter = h("progress", above ? "cost-meter cost-meter-over" : "cost-meter");
  meter.max = cost.max;
  meter.value = Math.min(cost.billed, cost.max);
  meter.setAttribute("aria-label", t("costTitle"));
  box.append(meter);
  const caption = above ? `${costText(cost)}: ${t("costAbove")}` : costText(cost);
  box.append(
    h("p", above ? "mt-1 text-sm font-semibold text-red-700" : "mt-1 text-sm text-slate-800", caption),
  );
  return box;
}

function rowsBlock(rows) {
  if (rows.length === 0) return null;
  const shown = rows.slice(0, MAX_ROWS);
  const box = h("div");
  const count = format(t("rowsCount"), { n: shown.length });
  box.append(h("h3", SECTION_TITLE, `${t("rowsTitle")} (${count})`));
  const wrapper = h("div", "overflow-x-auto rounded-lg border border-slate-200");
  const table = h("table", "min-w-full text-sm");
  const columns = Object.keys(shown[0]);
  const head = h("thead", "bg-slate-100");
  const headRow = h("tr");
  for (const column of columns) {
    headRow.append(h("th", "px-3 py-2 text-left font-semibold text-slate-800", column));
  }
  head.append(headRow);
  const body = h("tbody");
  for (const row of shown) {
    const tr = h("tr", "border-t border-slate-200");
    for (const column of columns) {
      tr.append(h("td", "px-3 py-1.5 text-slate-900 whitespace-nowrap", formatCell(row[column])));
    }
    body.append(tr);
  }
  table.append(head, body);
  wrapper.append(table);
  box.append(wrapper);
  return box;
}

function summaryBlock(summary, checks) {
  if (!summary) return null;
  const box = h("div");
  box.append(h("h3", SECTION_TITLE, t("summaryTitle")));
  const paragraph = h("p", "text-sm text-slate-900");
  summary.split(UNGROUNDED_MARKER).forEach((part, index) => {
    if (index > 0) {
      paragraph.append(
        h("mark", "rounded bg-amber-200 px-1 font-semibold text-amber-950", UNGROUNDED_MARKER),
      );
    }
    paragraph.append(document.createTextNode(part));
  });
  box.append(paragraph);
  const c06 = checks.find((entry) => entry.id === "C06_summary_numbers");
  if (c06 && !c06.passed) {
    box.append(h("p", "mt-1 text-xs font-medium text-amber-900", t("ungroundedNote")));
  }
  return box;
}

function renderAnswer(response) {
  const card = h("div", `${CARD} space-y-4`);
  card.append(statusBlock(response));
  if (response.degraded) {
    card.append(
      h("p", "rounded-lg border border-slate-300 bg-slate-100 p-2 text-sm text-slate-800", t("cached")),
    );
  }
  if (response.period) card.append(periodBlock(response.period));
  card.append(sqlBlock(response.sql));
  if (response.checks.length > 0) card.append(checksBlock(response.checks));
  const optional = [
    costBlock(response.checks),
    rowsBlock(response.rows),
    summaryBlock(response.summary, response.checks),
  ];
  for (const block of optional) {
    if (block) card.append(block);
  }
  return card;
}

function renderInjection(ask, validation) {
  const wrapper = h("div", "space-y-3");
  const grid = h("div", "grid gap-4 lg:grid-cols-2");
  const layer1 = h("div", "space-y-2");
  layer1.append(
    h("h3", "text-sm font-bold text-slate-900", t("layer1Title")),
    h("p", "text-sm text-slate-700", t("layer1Note")),
    renderAnswer(ask),
  );
  const asResponse = {
    status: validation.is_valid ? "answered" : "blocked",
    period: null,
    sql: validation.sql,
    checks: validation.checks,
    rows: [],
    summary: null,
    degraded: false,
    reason: validation.reason,
  };
  const verdict = validation.is_valid ? t("validateValid") : t("validateInvalid");
  const layer2 = h("div", "space-y-2");
  layer2.append(
    h("h3", "text-sm font-bold text-slate-900", t("layer2Title")),
    h("p", "text-sm text-slate-700", t("layer2Note")),
    h("p", "text-sm font-semibold text-slate-900", `is_valid: ${validation.is_valid} (${verdict})`),
    renderAnswer(asResponse),
  );
  grid.append(layer1, layer2);
  wrapper.append(
    grid,
    h(
      "p",
      "rounded-lg bg-indigo-700 p-3 text-center text-sm font-semibold text-white",
      t("injectionClosing"),
    ),
  );
  return wrapper;
}

function errorMessage(error) {
  if (error.kind === "rate") {
    const reason = translateCode(error.detail || "rate_limited");
    return error.retryAfter
      ? format(t("errRate"), { reason, seconds: error.retryAfter })
      : format(t("errRateNoWait"), { reason });
  }
  if (error.kind === "timeout") return t("errTimeout");
  if (error.kind === "server") return format(t("errServer"), { status: error.detail });
  return t("errNetwork");
}

function renderView() {
  const result = byId("result");
  result.replaceChildren();
  const view = state.view;
  if (!view) return;
  if (view.kind === "error") {
    result.append(
      h(
        "p",
        "rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900",
        errorMessage(view.error),
      ),
    );
  } else if (view.kind === "injection") {
    result.append(renderInjection(view.ask, view.validation));
  } else {
    result.append(renderAnswer(view.response));
  }
}

/* ---------- network ---------- */

class ApiError extends Error {
  constructor(kind, detail = "", retryAfter = "") {
    super(kind);
    this.kind = kind;
    this.detail = detail;
    this.retryAfter = retryAfter;
  }
}

function setNotice(text) {
  byId("notice").textContent = text;
}

async function postJson(path, body) {
  const controller = new AbortController();
  const abortTimer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const wakeTimer = setTimeout(() => setNotice(t("wake")), WAKE_NOTICE_MS);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (response.status === 429) {
      const payload = await response.json().catch(() => ({}));
      throw new ApiError("rate", payload.detail ?? "", response.headers.get("Retry-After") ?? "");
    }
    if (!response.ok) throw new ApiError("server", String(response.status));
    return await response.json();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(error.name === "AbortError" ? "timeout" : "network");
  } finally {
    clearTimeout(abortTimer);
    clearTimeout(wakeTimer);
  }
}

function updateAskButton() {
  const length = byId("question").value.trim().length;
  byId("askBtn").disabled = state.busy || length < QUESTION_MIN || length > QUESTION_MAX;
}

function setBusy(busy) {
  state.busy = busy;
  updateAskButton();
  for (const button of document.querySelectorAll("[data-run]")) button.disabled = busy;
}

async function runTask(task) {
  if (state.busy) return;
  setBusy(true);
  setNotice(t("loading"));
  byId("result").replaceChildren();
  try {
    state.view = await task();
  } catch (error) {
    state.view = {
      kind: "error",
      error: error instanceof ApiError ? error : new ApiError("network"),
    };
  }
  setNotice("");
  setBusy(false);
  renderView();
}

function askTask(question) {
  return async () => ({
    kind: "ask",
    response: await postJson("/v1/ask", { question, lang: state.lang }),
  });
}

function injectionTask(example) {
  return async () => {
    const question = example.question[state.lang];
    const [ask, validation] = await Promise.all([
      postJson("/v1/ask", { question, lang: state.lang }),
      postJson("/v1/validate", { sql: example.validateSql }),
    ]);
    return { kind: "injection", ask, validation };
  };
}

/* ---------- page wiring ---------- */

function updateCounter() {
  byId("counter").textContent = `${byId("question").value.length}/${QUESTION_MAX}`;
  updateAskButton();
}

function scenarioCard(example) {
  const isInjection = example.id === INJECTION_SCENARIO;
  const card = h("article", `${CARD} flex flex-col gap-2`);
  card.append(
    h("span", "text-xs font-bold text-indigo-700", `#${example.id}`),
    h("h3", "text-sm font-bold text-slate-900", example.label[state.lang]),
    h("p", "text-sm text-slate-800", example.question[state.lang]),
  );
  const observe = h("p", "text-xs text-slate-700");
  observe.append(h("strong", "", `${t("observeLabel")} `), example.observe[state.lang]);
  card.append(observe);
  const button = h(
    "button",
    "mt-auto px-3 py-1.5 rounded-lg bg-indigo-700 text-white text-sm font-semibold hover:bg-indigo-800 disabled:bg-slate-400 disabled:cursor-not-allowed focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-700",
    isInjection ? t("injectBtn") : t("runBtn"),
  );
  button.type = "button";
  button.dataset.run = String(example.id);
  button.disabled = state.busy;
  button.addEventListener("click", () => {
    byId("question").value = example.question[state.lang];
    updateCounter();
    runTask(isInjection ? injectionTask(example) : askTask(example.question[state.lang]));
  });
  card.append(button);
  return card;
}

function renderScenarios() {
  byId("scenarios").replaceChildren(...state.examples.map(scenarioCard));
}

function applyLanguage() {
  document.documentElement.lang = state.lang;
  for (const node of document.querySelectorAll("[data-i18n]")) {
    node.textContent = t(node.dataset.i18n);
  }
  byId("question").placeholder = t("questionPlaceholder");
  const isPt = state.lang === "pt";
  byId("langPt").className = isPt ? LANG_ACTIVE : LANG_IDLE;
  byId("langEn").className = isPt ? LANG_IDLE : LANG_ACTIVE;
  byId("langPt").setAttribute("aria-pressed", String(isPt));
  byId("langEn").setAttribute("aria-pressed", String(!isPt));
  renderScenarios();
  renderView();
}

function setLanguage(lang) {
  state.lang = lang;
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    /* storage unavailable: the choice just is not remembered */
  }
  applyLanguage();
}

function initialLanguage() {
  try {
    const stored = localStorage.getItem(LANG_KEY);
    if (stored === "pt" || stored === "en") return stored;
  } catch {
    /* storage unavailable: use the default */
  }
  return DEFAULT_LANG;
}

async function loadExamples() {
  try {
    const response = await fetch("./examples.json");
    state.examples = await response.json();
  } catch {
    setNotice(t("errExamples"));
  }
}

async function init() {
  state.lang = initialLanguage();
  byId("langPt").addEventListener("click", () => setLanguage("pt"));
  byId("langEn").addEventListener("click", () => setLanguage("en"));
  byId("question").addEventListener("input", updateCounter);
  byId("askForm").addEventListener("submit", (event) => {
    event.preventDefault();
    runTask(askTask(byId("question").value.trim()));
  });
  await loadExamples();
  applyLanguage();
  updateCounter();
}

init();
