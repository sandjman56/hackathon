# Per-Agent Model Selection & Cost Tracking — Design Spec

**Date:** 2026-04-11
**Status:** Approved (pending user review of this file)
**Branch context:** `fix/regulatory-prompt-quality` (last commit `7ac4d12`)

## Overview

Add two user-facing capabilities to the EIA Agent pipeline:

1. **Per-agent LLM selection.** Each of the five agent rows in the pipeline column shows a dropdown letting the user pick which provider+model to use for that specific step. Selections persist across page reloads via `localStorage`.
2. **Per-agent cost display.** After each agent completes, its inline cost (USD) appears on its row and a `TOTAL` chip in the `PIPELINE STATUS` header sums all per-agent costs. Costs are computed from token usage reported by each provider's SDK and per‑1M‑token prices stored in a versioned `pricing.py` table.

Design constraint baked into both features: the **embedding provider stays fixed** (Gemini) because changing it would invalidate the `regulatory_chunks` pgvector corpus. The dropdowns control chat LLMs only.

## Context — what's actually wired up today

| Agent | Calls an LLM today? | Dropdown in this feature? |
|---|---|---|
| `project_parser` | ✅ yes | ✅ active |
| `environmental_data` | ❌ no (REST APIs only) | disabled `no LLM` pill (permanent) |
| `regulatory_screening` | ✅ yes + embedding | ✅ active |
| `impact_analysis` | ❌ **stub** — receives `llm`, never calls it | disabled `no LLM` pill (until stub is implemented) |
| `report_synthesis` | ❌ **stub** — receives `llm`, never calls it | disabled `no LLM` pill (until stub is implemented) |

Only two agents will actually consume the new dropdown on day one. The other three rows still render a dropdown slot so that (a) the UI matches the user's "every agent step" ask, and (b) when the two stubs are later implemented, their dropdowns auto-activate via a single-line change to a frontend constant — no UI rework needed.

Cost for the three non-LLM agents is always `$0.00`, displayed as `—` per the "Cost chip formatting rules" subsection below.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  FRONTEND (App.jsx / AgentPipeline.jsx / ProjectForm.jsx)        │
│  ┌──────────────────────────┐                                    │
│  │ 5 per-agent <select>     │──┐                                 │
│  │ reading from localStorage│  │                                 │
│  └──────────────────────────┘  │                                 │
│  ┌──────────────────────────┐  │                                 │
│  │ cost chip per agent row  │<─┼──── SSE "agent_cost" event ───┐ │
│  │ total in PIPELINE header │  │                               │ │
│  └──────────────────────────┘  │                               │ │
│  ┌──────────────────────────┐  │                               │ │
│  │ greyed-out if provider   │<─┤──── GET /api/providers ──┐    │ │
│  │ key missing              │  │                          │    │ │
│  └──────────────────────────┘  │                          │    │ │
│              POST /api/run { models: {agent: model_id}}   │    │ │
│                                │                          │    │ │
└────────────────────────────────┼──────────────────────────┼────┼─┘
                                 │                          │    │
┌────────────────────────────────┼──────────────────────────┼────┼─┐
│  BACKEND                       ▼                          │    │ │
│  ┌─────────────────────────────────────┐                  │    │ │
│  │ pipeline.stream_eia_pipeline()      │                  │    │ │
│  │  resolves model_id -> provider      │                  │    │ │
│  │  each agent run() yields LLMResult  │                  │    │ │
│  │  pricing.py lookup -> $ per call    │                  │    │ │
│  │  emits "agent_cost" SSE event ──────┼──────────────────┼────┘ │
│  └─────────────────────────────────────┘                  │      │
│  ┌─────────────────────────────────────┐                  │      │
│  │ GET /api/providers ─ env-var check ─┼──────────────────┘      │
│  └─────────────────────────────────────┘                         │
│  ┌─────────────────────────────────────┐                         │
│  │ llm/pricing.py (static $/1M table)  │                         │
│  │ llm/base.py     (LLMResult dataclass)│                        │
│  └─────────────────────────────────────┘                         │
└──────────────────────────────────────────────────────────────────┘
```

**Data flow for one run:**

1. Frontend mounts → reads `localStorage.getItem("eia.model_selections")` merged over hardcoded `DEFAULT_MODELS` → calls `GET /api/providers` → greys out unavailable options.
2. User clicks RUN → `POST /api/run` with `{project_name, coordinates, description, models: {project_parser: "gemini-2.0-flash", regulatory_screening: "claude-haiku-4-5-20251001", ...}}`.
3. Pipeline builds a model→provider map **per request** (not per startup), instantiates providers lazily, passes each agent its own configured LLM.
4. Each real agent calls `llm.complete()` which returns an `LLMResult(text, input_tokens, output_tokens, model)`. Agent stores usage under `state["_usage"][agent_key]`.
5. After each agent finishes, the pipeline looks up `pricing.cost_usd(model, in, out)` → emits `agent_cost` SSE event after the existing `agent_complete` event.
6. Frontend `ProjectForm.handleSSEEvent` receives `agent_cost`, calls `onCostUpdate`, App merges it into `agentCosts` state, `AgentPipeline` renders the chip and updates the header TOTAL.

**Key invariant:** No chat LLM is pre-instantiated at server startup anymore. Each run builds its own provider set. The `embedding_provider` singleton stays (RAG corpus dependency).

## Backend changes

### New file: `backend/llm/pricing.py`

Static pricing table. Web-searched during implementation, committed with `LAST_UPDATED` + source URLs so staleness is obvious.

```python
"""Per-model pricing table for cost tracking in the pipeline.

All prices are USD per 1,000,000 tokens, taken from each provider's
official pricing page on LAST_UPDATED. Refresh by re-running the web
searches documented in
docs/superpowers/specs/2026-04-11-per-agent-model-cost-design.md
and committing a new table with an updated LAST_UPDATED stamp.
"""
LAST_UPDATED = "2026-04-11"

SOURCES = {
    "openai":    "https://openai.com/api/pricing/",
    "anthropic": "https://www.anthropic.com/pricing",
    "gemini":    "https://ai.google.dev/pricing",
}

MODEL_PRICING: dict[str, dict] = {
    # Filled in by the implementation step via web search.
    # Each entry: {"provider": str, "label": str, "input": float, "output": float}
    # input/output are USD per 1,000,000 tokens.
}

def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost for one completion. Returns 0.0 for unknown models."""
    p = MODEL_PRICING.get(model)
    if not p:
        return 0.0
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
```

Design choices:

- `cost_usd()` returns `0.0` on unknown model rather than raising. A misconfigured model id must not crash a pipeline run mid-stream.
- `LAST_UPDATED` and `SOURCES` are surfaced via `GET /api/providers` so the frontend could later show "prices as of 2026-04-11" in a tooltip. Not built now (YAGNI) but free future optionality.

### Web search plan (executed during implementation)

Three searches, one per provider, targeting each provider's own pricing page — not third-party aggregators which go stale and sometimes carry wrong numbers:

1. `OpenAI API pricing gpt-4o gpt-4o-mini per 1M tokens 2026` → target `openai.com/api/pricing`
2. `Anthropic Claude API pricing Opus Sonnet Haiku per 1M tokens 2026` → target `anthropic.com/pricing` or `docs.anthropic.com/en/docs/about-claude/models`
3. `Google Gemini API pricing 2.5 Pro Flash per 1M tokens 2026` → target `ai.google.dev/pricing`

For each provider, capture both **input** and **output** token prices (they differ, sometimes dramatically — Opus output is ~5× input). Capture the exact model ID string the API accepts because that string is the key into `MODEL_PRICING` and must match what each provider SDK sends on the wire.

### Models priced (the full dropdown set)

Verified against each provider's pricing page on 2026-04-11:

| Model ID (pricing.py key) | Label | Provider | Input $/MTok | Output $/MTok |
|---|---|---|---|---|
| `gpt-5.4` | `OpenAI · GPT-5.4` | openai | 2.50 | 15.00 |
| `gpt-5.4-mini` | `OpenAI · GPT-5.4 mini` | openai | 0.75 | 4.50 |
| `claude-opus-4-6` | `Claude · Opus 4.6` | anthropic | 5.00 | 25.00 |
| `claude-sonnet-4-6` | `Claude · Sonnet 4.6` | anthropic | 3.00 | 15.00 |
| `claude-haiku-4-5-20251001` | `Claude · Haiku 4.5` | anthropic | 1.00 | 5.00 |
| `gemini-2.5-pro` | `Gemini · 2.5 Pro` | gemini | 1.25 | 10.00 |
| `gemini-2.5-flash` | `Gemini · 2.5 Flash` | gemini | 0.30 | 2.50 |
| `gemini-2.0-flash` | `Gemini · 2.0 Flash` | gemini | 0.10 | 0.40 |

**Deprecation notice:** `gemini-2.0-flash` is officially scheduled for shutdown on 2026-06-01. Because the current branch uses it as the default for every Gemini-consuming agent, `DEFAULT_MODELS` in this feature migrates to `gemini-2.5-flash` instead (same provider, Flash tier, ~3× cost but still sub-cent per call for this pipeline's prompt sizes). Users can still select `gemini-2.0-flash` from the dropdown until shutdown if they want the old default.

**OpenAI note:** As of 2026-04-11, OpenAI's pricing page lists `gpt-5.4` as the current flagship and `gpt-5.4-mini` as the efficient variant; `gpt-4o` / `gpt-4o-mini` are no longer shown. The existing `OPENAI_MODEL` env var fallback in `openai_provider.py` stays untouched by this feature — only the new dropdown list is affected.

If a future web search reveals a model has been renamed or deprecated, swap it for the current equivalent, update the prices, bump `LAST_UPDATED`, and note the substitution in the commit message.

**Refresh workflow** (documented for future use): ask an agent "refresh `backend/llm/pricing.py`". The agent re-runs the three searches above, updates the numbers + `LAST_UPDATED`, and commits. No DB migration, no restart needed beyond a normal redeploy.

### Modified: `backend/llm/base.py`

```python
from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str  # exact model id; matches a pricing.py key


class LLMProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    def complete(self, prompt: str, system: str = None) -> LLMResult: ...

    @abstractmethod
    def embed(self, text: str) -> list[float]: ...

    @abstractmethod
    def chat(self, messages: list[dict]) -> str: ...
```

`embed()` and `chat()` signatures are unchanged — embeddings aren't priced in this feature and `chat()` isn't called by any pipeline agent today.

### Modified: `backend/llm/{openai,anthropic,gemini,ollama}_provider.py`

Each `complete()` pulls token counts off the SDK response and returns `LLMResult`. Constructors accept an optional `model` kwarg so the factory can override the env default per request.

- **OpenAI** (langchain): `response.response_metadata["token_usage"]["prompt_tokens"/"completion_tokens"]`, model id from `self._model`.
- **Anthropic** (direct SDK): `response.usage.input_tokens`, `response.usage.output_tokens`, model id from `self._model`.
- **Gemini** (langchain): `response.usage_metadata["input_tokens"/"output_tokens"]`, model id from `self._model`.
- **Ollama** gets the same interface change to satisfy the ABC. It's not reachable from the dropdown (cloud-only per user decision). Returns `LLMResult` with `model="ollama-local"` so `cost_usd()` returns `0.0`.

Defensive fallback pattern in each provider to avoid hard crashes on SDK upgrades:

```python
usage = getattr(response, "usage", None) or {}
return LLMResult(
    text=text,
    input_tokens=int(usage.get("input_tokens", 0)),
    output_tokens=int(usage.get("output_tokens", 0)),
    model=self._model,
)
```

If usage metadata is missing, cost comes out as `$0` and a `warning` level log line ("usage metadata missing from <provider> response — cost will be $0") goes to the Brain Scanner.

### Modified: `backend/llm/provider_factory.py`

New helpers, existing env-var-based helpers retained for the embedding provider path:

```python
class MissingAPIKeyError(RuntimeError): ...
class UnknownModelError(ValueError): ...

def get_llm_for_model(model_id: str) -> LLMProvider:
    """Instantiate the correct provider class for a pricing.py model id."""
    from .pricing import MODEL_PRICING
    if model_id not in MODEL_PRICING:
        raise UnknownModelError(f"unknown model: {model_id!r}")
    provider_name = MODEL_PRICING[model_id]["provider"]
    if provider_name == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise MissingAPIKeyError("OPENAI_API_KEY not set")
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(model=model_id)
    if provider_name == "anthropic":
        if not os.environ.get("CLAUDE_KEY"):
            raise MissingAPIKeyError("CLAUDE_KEY not set")
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model_id)
    if provider_name == "gemini":
        if not os.environ.get("GOOGLE_API_KEY"):
            raise MissingAPIKeyError("GOOGLE_API_KEY not set")
        from .gemini_provider import GeminiProvider
        return GeminiProvider(model=model_id)
    raise UnknownModelError(f"unknown provider for model {model_id!r}")


def available_providers() -> dict[str, bool]:
    """Used by GET /api/providers. Checks env vars, doesn't instantiate."""
    return {
        "openai":    bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic": bool(os.environ.get("CLAUDE_KEY")),
        "gemini":    bool(os.environ.get("GOOGLE_API_KEY")),
    }
```

### Modified: `backend/main.py`

**New endpoint:**

```python
@app.get("/api/providers")
def get_providers():
    from llm.pricing import MODEL_PRICING, LAST_UPDATED, SOURCES
    from llm.provider_factory import available_providers
    return {
        "available": available_providers(),
        "models": [
            {"id": mid, **{k: v for k, v in info.items() if k != "provider"},
             "provider": info["provider"]}
            for mid, info in MODEL_PRICING.items()
        ],
        "pricing_last_updated": LAST_UPDATED,
        "pricing_sources": SOURCES,
    }
```

**Modified `POST /api/run` request model:**

```python
class RunRequest(BaseModel):
    project_name: str
    coordinates: str
    description: str
    models: dict[str, str] = Field(default_factory=dict)  # NEW: agent_key -> model_id
```

**Modified startup:** remove the `llm_provider` / `screening_llm` singletons from `app.state`. Pipeline no longer depends on them. `embedding_provider` stays because the RAG retriever is tied to its output dimensionality.

**Modified handler:** `stream_eia_pipeline` is called with the `models` dict instead of pre-built providers.

### Modified: `backend/pipeline.py`

New signature:

```python
def stream_eia_pipeline(
    project_name: str,
    coordinates: str,
    description: str,
    models: dict[str, str],
    embedding_provider: LLMProvider,
):
    ...
```

New constants:

```python
DEFAULT_MODELS: dict[str, str] = {
    "project_parser":       "gemini-2.0-flash",
    "environmental_data":   "gemini-2.0-flash",  # not actually used
    "regulatory_screening": "claude-haiku-4-5-20251001",
    "impact_analysis":      "gemini-2.0-flash",  # not actually used
    "report_synthesis":     "gemini-2.0-flash",  # not actually used
}
```

This preserves the current `fix/regulatory-prompt-quality` branch behavior (project_parser on Gemini, regulatory_screening on Claude Haiku) as the baseline any fresh-cache user sees.

New helper:

```python
def _resolve_agent_llm(agent_key: str, models: dict[str, str]) -> tuple[LLMProvider | None, str]:
    """Returns (llm_instance, model_id). Non-LLM agents get (None, model_id)."""
    model_id = models.get(agent_key) or DEFAULT_MODELS[agent_key]
    if agent_key in NON_LLM_AGENTS:  # see below
        return None, model_id
    llm = get_llm_for_model(model_id)
    return llm, model_id


NON_LLM_AGENTS = frozenset({
    "environmental_data",
    "impact_analysis",
    "report_synthesis",
})
```

**Pre-flight validation:** before the first agent runs, `stream_eia_pipeline` calls `_resolve_agent_llm` for every LLM-using agent. If any raise `MissingAPIKeyError` or `UnknownModelError`, the pipeline emits one `pipeline_error` SSE event and returns. No partial runs, no mid-pipeline crashes.

**Per-agent cost emission:** After each agent's `agent_complete` event, the pipeline reads `state["_usage"].get(agent_key)` and emits:

```
event: agent_cost
data: {"agent": "regulatory_screening",
       "model": "claude-haiku-4-5-20251001",
       "input_tokens": 4123,
       "output_tokens": 287,
       "cost_usd": 0.0041}
```

For agents that didn't populate `_usage` (non-LLM agents, or LLM agents whose `complete()` raised), the event is still emitted with zeros:

```
event: agent_cost
data: {"agent": "environmental_data",
       "model": "gemini-2.0-flash",
       "input_tokens": 0,
       "output_tokens": 0,
       "cost_usd": 0.0}
```

Always emitting exactly one `agent_cost` event per agent keeps the frontend state machine trivially simple.

### Modified: `backend/agents/project_parser.py`

- Unchanged call shape, now receives an `LLMResult` back: `result = self.llm.complete(prompt, system=_SYSTEM); raw = result.text`.
- Before returning, populates usage:
  ```python
  state.setdefault("_usage", {})["project_parser"] = {
      "input_tokens": result.input_tokens,
      "output_tokens": result.output_tokens,
      "model": result.model,
  }
  ```

### Modified: `backend/agents/regulatory_screening.py`

Same pattern as project_parser. The existing extensive logging added in the previous commit stays intact; only the LLM call site changes.

### Modified: `backend/agents/impact_analysis.py` and `backend/agents/report_synthesis.py`

Targeted improvement while in the file: **remove the unused `llm` constructor parameter** from both stubs. Cleaner signal that they're stubs and the pipeline no longer passes them an LLM. When the stubs are later implemented, the implementer consciously re-adds the parameter and routes it through `_resolve_agent_llm`.

### Modified: `backend/agents/environmental_data.py`

Same treatment — the `llm` parameter was never used. Remove it.

## Frontend changes

### New hook: `frontend/src/hooks/useModelSelections.js`

Single hook that owns per-agent model state + localStorage + provider availability.

```js
// API surface:
// {
//   selections: {project_parser: "gemini-2.0-flash", ...},
//   setSelection: (agentKey, modelId) => void,
//   availableProviders: {openai: true, anthropic: true, gemini: false},
//   modelCatalog: [{id, label, provider, input, output}, ...],
//   loading: boolean,
// }
```

Behavior:

- Mounts once in `App.jsx`, passed down to `ProjectForm` and `AgentPipeline`.
- On mount: `fetch('/api/providers')` populates `availableProviders` + `modelCatalog`.
- Initial `selections` = `localStorage.getItem('eia.model_selections')` merged over hardcoded `DEFAULT_MODELS` (matching backend defaults so a cold cache still shows the right picks).
- `setSelection` writes through to localStorage on every change.
- After `/api/providers` returns, any selection whose `model_id` isn't in `modelCatalog` is silently replaced with the `DEFAULT_MODELS` value for that agent and rewritten to localStorage (handles stale model ids after a backend rename).

### New component: `frontend/src/components/ModelDropdown.jsx`

Per-row `<select>`:

- Options grouped by provider via `<optgroup label="OpenAI">` / `<optgroup label="Claude">` / `<optgroup label="Gemini">`.
- If the agent is in `NON_LLM_AGENTS`, renders a disabled `no LLM` pill instead of a `<select>`.
- If a provider's key is missing in `availableProviders`, that group's options get `disabled` + a `title="OPENAI_API_KEY not set on backend"` tooltip (or equivalent per provider).
- Styled to match the existing card aesthetic: mono font, green border on focus, ~140px wide, fits inline on the agent row.

### Modified: `frontend/src/components/AgentPipeline.jsx`

Focused changes; no refactor of the existing row rendering.

- New props: `selections`, `setSelection`, `availableProviders`, `modelCatalog`, `agentCosts`.
- The `PIPELINE STATUS` header gets a right-aligned chip: `TOTAL $0.0042` (sum of all `agentCosts[*].cost_usd`, formatted per the "Cost chip formatting rules" subsection, or `—` before the first cost event arrives).
- Each agent row gets two new inline elements between `agentName` and `statusText`: a `<ModelDropdown>` and a cost chip.
- The existing `VIEW SOURCES` button on the regulatory row stays exactly where it is; it gets positioned next to the dropdown on that row.
- Rows in `NON_LLM_AGENTS` show the `no LLM` pill + cost chip `—` permanently.

Column-width handling: the middle column is ~28% of viewport. On narrow windows the dropdown drops below the name line on a second row via pure CSS `flex-wrap`.

### New constant: `NON_LLM_AGENTS` in `AgentPipeline.jsx`

```js
const NON_LLM_AGENTS = new Set([
  'environmental_data',
  'impact_analysis',
  'report_synthesis',
])
```

Single source of truth. When `impact_analysis` or `report_synthesis` gets a real LLM call, you delete its entry here and its dropdown activates.

### Modified: `frontend/src/components/ProjectForm.jsx`

- Accepts new prop `modelSelections`.
- `handleSubmit` includes `models: modelSelections` in the `POST /api/run` body.
- `handleSSEEvent` gains one new case:
  ```js
  case 'agent_cost':
    onCostUpdate?.(data)
    break
  ```

### Modified: `frontend/src/App.jsx`

- Mounts `useModelSelections()`.
- New state: `const [agentCosts, setAgentCosts] = useState({})`.
- `handleCostUpdate = (data) => setAgentCosts(prev => ({...prev, [data.agent]: data}))`.
- Passes `selections` / `setSelection` / `availableProviders` / `modelCatalog` / `agentCosts` down to `AgentPipeline`.
- Passes `selections` and `onCostUpdate` down to `ProjectForm`.
- The hardcoded `<span style={styles.providerBadge}>Gemini</span>` in the top-right header is **removed** — with per-agent dropdowns, a global provider badge is misleading.
- On pipeline start (`handleSubmit`), resets `agentCosts` to `{}` so stale chips from a previous run don't linger.

### Cost chip formatting rules

- Zero or missing → `—` in `text-muted`
- `$ < 0.0001` → `<$0.0001` in `text-secondary`
- `$ >= 0.0001` → `$0.0042` (4 decimals) in `text-secondary`
- `$ >= 1.00` → `$1.23` (2 decimals) in `yellow-warn` (draws the eye on expensive runs)
- `TOTAL` chip in header follows the same rules.

## Edge cases & error handling

### Selected provider has no API key at runtime

Defense in depth:

1. **Frontend pre-flight:** `GET /api/providers` greys out unavailable `<optgroup>`s. User cannot submit a run that picks an unavailable provider from a fresh UI state.
2. **Backend safety net:** If a stale frontend sends a request for an unavailable provider, `get_llm_for_model()` raises `MissingAPIKeyError` during pre-flight validation in `stream_eia_pipeline`. The pipeline emits one `pipeline_error` SSE event before any agents start:
   ```
   event: pipeline_error
   data: {"msg": "Claude selected for regulatory_screening but CLAUDE_KEY is not set on the server",
          "type": "MissingAPIKeyError"}
   ```

### Mid-pipeline LLM failure

Existing per-node `try/except` in `stream_eia_pipeline` handles this. New behavior layered on top: if `llm.complete()` raises, the agent's `_usage` dict is not populated. The pipeline still emits an `agent_cost` event with zeros. Frontend chip shows `—`. Row status goes to `error` via the existing path.

Always emitting exactly one `agent_cost` event per agent (success OR failure OR non-LLM) keeps the frontend state machine uniform.

### Pipeline cancelled mid-run (`/q`)

Existing cancel flag path is honored. Agents that haven't started get no `agent_cost` event. Frontend chips stay at `—` for those rows. Header TOTAL sums only the agents that actually executed.

### Token counts missing from SDK response

Defensive fallback in each provider returns zeros → `cost_usd` returns `0.0`. Brain Scanner log emits a `warning` level message so the regression is visible at debug time.

### Unknown model id in pricing table

- `get_llm_for_model()` raises `UnknownModelError` pre-flight. Pipeline emits `pipeline_error` and stops.
- Frontend-side: after `/api/providers` returns, the hook cross-checks localStorage selections against `modelCatalog`. Any stale selection is silently replaced with the default and rewritten to localStorage.

### Non-LLM agents

`environmental_data`, `impact_analysis`, `report_synthesis` always emit an `agent_cost` event with zeros. They receive a `models` entry in the request but the pipeline ignores it (they're in `NON_LLM_AGENTS`, they don't instantiate an LLM).

### First run after localStorage is empty

Hook initializes with `DEFAULT_MODELS` (frontend constant matching backend defaults). First `/api/providers` fetch happens in parallel with render. If the user clicks RUN in the ~200ms before fetch completes, the request goes out with `DEFAULT_MODELS` and the backend uses them. No race condition; backend is the source of truth.

### Embedding provider is unavailable

The embedding provider is instantiated at server startup by the existing lifespan handler. If `GOOGLE_API_KEY` is missing at startup, the server fails to boot (pre-existing behavior — no change). This feature doesn't touch embedding costs.

## Out of scope for this feature

- **Embedding cost tracking.** Gemini embeddings are called once per pipeline run (the RAG query) and cost pennies. Pricing them would mean adding a pricing entry for `gemini-embedding-001`, counting query characters, and attributing the cost to `regulatory_screening`. Documented as future work.
- **Cost-budget enforcement** ("stop the run if total > $1"). Not requested.
- **Historical cost logging to a DB table.** Not requested.
- **Ollama pricing.** Cloud-only per user decision.
- **Streaming token cost updates during a single LLM call.** All costs are computed once after `complete()` returns.
- **Multi-call cost aggregation within one agent.** No agent makes multiple LLM calls per run today. If that changes later, the `_usage` dict shape is already summable across calls; the pipeline would need to aggregate before emitting `agent_cost`. Flag-and-defer.
- **Playwright / end-to-end browser tests.** The project doesn't have E2E setup and this feature isn't justification to add one.

## Testing plan

### Backend

| File | What it covers |
|---|---|
| `backend/tests/test_pricing.py` *(new)* | `cost_usd()` happy path, zero tokens, unknown model → `0.0` (not raise), float precision at sub-cent sizes. Asserts every entry in `MODEL_PRICING` has required keys. |
| `backend/tests/test_provider_factory.py` *(new)* | `available_providers()` reads env vars correctly (monkeypatch). `get_llm_for_model()` raises `UnknownModelError` for bogus ids and `MissingAPIKeyError` when env var absent. No real provider instantiation (mocked). |
| `backend/tests/test_project_parser.py` *(extend)* | Existing tests become `LLMResult`-aware. New test: parser populates `state["_usage"]["project_parser"]` with tokens + model. |
| `backend/tests/test_regulatory_agent.py` *(extend)* | Same treatment for regulatory_screening. Fake LLM returns `LLMResult(text=..., input_tokens=123, output_tokens=45, model="claude-haiku-4-5-20251001")`. |
| `backend/tests/test_pipeline_cost.py` *(new)* | End-to-end in-process test of `stream_eia_pipeline` with all LLMs mocked. Asserts: (a) exactly one `agent_cost` event per agent, (b) LLM agents have non-zero cost, (c) non-LLM agents emit zero-cost events, (d) cost events come after their corresponding `agent_complete`, (e) `MissingAPIKeyError` pre-flight emits one `pipeline_error` and zero `agent_cost` events. |

### Frontend (Vitest + @testing-library/react)

| File | What it covers |
|---|---|
| `frontend/src/components/AgentPipeline.test.jsx` *(extend)* | (a) `ModelDropdown` rendered on `project_parser` and `regulatory_screening`, (b) `no LLM` pill for the three non-LLM rows, (c) cost chip when `agentCosts[agent]` present, (d) `TOTAL` in header sums all `agentCosts`, (e) `—` chip when cost is 0 or missing, (f) yellow chip when cost ≥ $1. |
| `frontend/src/components/ModelDropdown.test.jsx` *(new)* | (a) renders one `<option>` per `modelCatalog` entry, grouped by provider via `<optgroup>`, (b) options for unavailable providers are disabled with the right `title`, (c) `onChange` fires `setSelection(agentKey, modelId)`. |
| `frontend/src/hooks/useModelSelections.test.js` *(new)* | (a) initial state falls back to `DEFAULT_MODELS` when localStorage empty, (b) `setSelection` writes through to localStorage, (c) `fetch('/api/providers')` called once on mount, (d) stale localStorage selections replaced with defaults. Uses `vi.stubGlobal('fetch', ...)` + `vi.stubGlobal('localStorage', ...)`. |

### Manual verification checklist (post-merge)

1. Fresh load → all three providers green in every dropdown; defaults match the table in the "Context" section.
2. Change `regulatory_screening` to `OpenAI · GPT-4o`, reload page → selection persists.
3. Remove `CLAUDE_KEY` from backend env, restart server, reload frontend → all Claude options greyed out with tooltip.
4. Run the pipeline → exactly two rows show a non-zero cost chip (`project_parser`, `regulatory_screening`); header `TOTAL` equals their sum; three rows show `—`.
5. Pick `Claude · Opus 4.6` for `project_parser`, re-run same input → cost chip visibly larger than a Haiku run (sanity check on pricing).
6. Click `/q` mid-run during regulatory_screening → `project_parser` cost chip populated, regulatory chip stays `—`, TOTAL equals project_parser cost only.

## Files touched (summary)

**New:**
- `backend/llm/pricing.py`
- `backend/tests/test_pricing.py`
- `backend/tests/test_provider_factory.py`
- `backend/tests/test_pipeline_cost.py`
- `frontend/src/hooks/useModelSelections.js`
- `frontend/src/hooks/useModelSelections.test.js`
- `frontend/src/components/ModelDropdown.jsx`
- `frontend/src/components/ModelDropdown.test.jsx`

**Modified:**
- `backend/llm/base.py` (add `LLMResult`, change `complete()` signature)
- `backend/llm/openai_provider.py`
- `backend/llm/anthropic_provider.py`
- `backend/llm/gemini_provider.py`
- `backend/llm/ollama_provider.py`
- `backend/llm/provider_factory.py` (add `get_llm_for_model`, `available_providers`, error classes)
- `backend/main.py` (`GET /api/providers`, `RunRequest.models`, remove startup LLM singletons)
- `backend/pipeline.py` (new signature, `DEFAULT_MODELS`, `_resolve_agent_llm`, `NON_LLM_AGENTS`, pre-flight validation, `agent_cost` events)
- `backend/agents/project_parser.py` (consume `LLMResult`, populate `_usage`)
- `backend/agents/regulatory_screening.py` (consume `LLMResult`, populate `_usage`)
- `backend/agents/environmental_data.py` (remove unused `llm` param)
- `backend/agents/impact_analysis.py` (remove unused `llm` param)
- `backend/agents/report_synthesis.py` (remove unused `llm` param)
- `backend/tests/test_project_parser.py` (LLMResult-aware)
- `backend/tests/test_regulatory_agent.py` (LLMResult-aware)
- `frontend/src/App.jsx` (mount hook, `agentCosts` state, remove hardcoded Gemini badge)
- `frontend/src/components/ProjectForm.jsx` (send `models`, handle `agent_cost` event)
- `frontend/src/components/AgentPipeline.jsx` (dropdowns, cost chips, header TOTAL, `NON_LLM_AGENTS`)
- `frontend/src/components/AgentPipeline.test.jsx` (extend)
