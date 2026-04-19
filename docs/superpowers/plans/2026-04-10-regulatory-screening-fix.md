# Regulatory Screening Quality Fix

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the regulatory screening agent so it returns properly structured JSON with actual permit/approval requirements instead of NEPA procedural concepts.

**Architecture:** Switch the regulatory screening agent from Gemini Flash to Claude Haiku for reliable JSON output. Rewrite the prompt to distinguish permits from NEPA process steps. Use the `system` parameter to enforce output format. Remove the redundant `permits_required` field from the project parser. Fix a key-name mismatch bug (`type` vs `project_type`) that was causing the project type to always show as "unknown" in the screening prompt.

**Tech Stack:** Python/FastAPI, Anthropic SDK (claude-haiku-4-5-20251001), existing LLM provider abstraction

---

### Task 1: Update AnthropicProvider to use CLAUDE_KEY

**Files:**
- Modify: `backend/llm/anthropic_provider.py`
- Test: `backend/tests/test_regulatory_agent.py` (existing tests still pass)

- [ ] **Step 1: Update env var and default model**

In `backend/llm/anthropic_provider.py`, change the `__init__` method to read `CLAUDE_KEY` instead of `ANTHROPIC_API_KEY`, and default the model to Haiku:

```python
def __init__(self):
    api_key = os.environ.get("CLAUDE_KEY")
    if not api_key:
        raise ValueError("CLAUDE_KEY environment variable is not set.")
    self._model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    self._client = anthropic.Anthropic(api_key=api_key)
```

- [ ] **Step 2: Verify import works**

Run: `cd /Users/sanderschulman/Developer/aiagentsproject/backend && python -c "from llm.anthropic_provider import AnthropicProvider; print('import ok')"`
Expected: `import ok` (it won't instantiate without the key, but the import should work)

- [ ] **Step 3: Commit**

```bash
git add backend/llm/anthropic_provider.py
git commit -m "fix: update AnthropicProvider to use CLAUDE_KEY env var, default to Haiku model"
```

---

### Task 2: Wire up dedicated Anthropic provider for regulatory screening

**Files:**
- Modify: `backend/pipeline.py:151-154` (the `_make_agent_node` function)
- Modify: `backend/pipeline.py:184-194` (the `build_pipeline` function)
- Modify: `backend/pipeline.py:230-236` (the `stream_eia_pipeline` function)

The regulatory screening agent already accepts a separate `llm` and `embedding_provider`. We need to pass it a dedicated Anthropic LLM while keeping Gemini for everything else. The embedding provider stays Gemini since Anthropic doesn't support embeddings.

- [ ] **Step 1: Add a screening_llm parameter to build_pipeline and _make_agent_node**

In `backend/pipeline.py`, update `_make_agent_node` to accept an optional `screening_llm`:

```python
def _make_agent_node(agent_key: str, agent_class, llm: LLMProvider, embedding_provider: LLMProvider, screening_llm: LLMProvider | None = None):
    """Create a LangGraph node function wrapping an agent's .run() call."""
    if agent_key == "regulatory_screening":
        agent = agent_class(screening_llm or llm, embedding_provider)
    else:
        agent = agent_class(llm)
```

Update `build_pipeline`:

```python
def build_pipeline(llm: LLMProvider, embedding_provider: LLMProvider, screening_llm: LLMProvider | None = None):
    """Construct and compile the EIA LangGraph pipeline."""
    graph = StateGraph(EIAPipelineState)
    for agent_key, agent_class in AGENT_REGISTRY:
        graph.add_node(agent_key, _make_agent_node(agent_key, agent_class, llm, embedding_provider, screening_llm))
    prev = START
    for agent_key, _ in AGENT_REGISTRY:
        graph.add_edge(prev, agent_key)
        prev = agent_key
    graph.add_edge(prev, END)
    return graph.compile()
```

- [ ] **Step 2: Update run_eia_pipeline to accept and pass screening_llm**

```python
def run_eia_pipeline(
    project_name: str,
    coordinates: str,
    description: str,
    llm: LLMProvider,
    embedding_provider: LLMProvider,
    screening_llm: LLMProvider | None = None,
) -> dict:
    compiled = build_pipeline(llm, embedding_provider, screening_llm)
```

- [ ] **Step 3: Update stream_eia_pipeline to accept screening_llm and use it for the regulatory_screening node**

In `stream_eia_pipeline`, add the `screening_llm` parameter and use it when constructing the regulatory screening agent:

```python
def stream_eia_pipeline(
    project_name: str,
    coordinates: str,
    description: str,
    llm: LLMProvider,
    embedding_provider: LLMProvider,
    screening_llm: LLMProvider | None = None,
):
```

Then in the per-agent loop (~line 306), update the agent construction:

```python
            if agent_key == "regulatory_screening":
                agent = agent_class(screening_llm or llm, embedding_provider)
            else:
                agent = agent_class(llm)
```

- [ ] **Step 4: Commit**

```bash
git add backend/pipeline.py
git commit -m "feat: add screening_llm parameter to pipeline for dedicated regulatory LLM"
```

---

### Task 3: Instantiate Anthropic provider in main.py when CLAUDE_KEY is set

**Files:**
- Modify: `backend/main.py` (lifespan setup and /api/run endpoint)

- [ ] **Step 1: Create screening LLM in lifespan if CLAUDE_KEY is present**

In `backend/main.py`, after the existing provider initialization (~line 66-67), add:

```python
        llm = get_llm_provider()
        emb = get_embedding_provider()

        # Dedicated Anthropic provider for regulatory screening (optional)
        screening_llm = None
        if os.environ.get("CLAUDE_KEY"):
            from llm.anthropic_provider import AnthropicProvider
            screening_llm = AnthropicProvider()
            logger.info("Regulatory screening LLM: %s (%s)", screening_llm.provider_name, "haiku")
```

Store it on `app.state`:

```python
    app.state.llm_provider = llm
    app.state.embedding_provider = emb
    app.state.screening_llm = screening_llm
```

- [ ] **Step 2: Pass screening_llm to stream_eia_pipeline in the /api/run endpoint**

Update the `stream_eia_pipeline` call (~line 129):

```python
        stream_eia_pipeline(
            project_name=req.project_name,
            coordinates=req.coordinates,
            description=req.description,
            llm=app.state.llm_provider,
            embedding_provider=app.state.embedding_provider,
            screening_llm=app.state.screening_llm,
        ),
```

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: instantiate Anthropic provider for regulatory screening when CLAUDE_KEY is set"
```

---

### Task 4: Fix project_type key mismatch bug

**Files:**
- Modify: `backend/agents/regulatory_screening.py:80,120-121`

The project parser stores `project_type` but the regulatory screening agent reads `parsed.get('type')` — so the project type is always `'unknown'` in the screening prompt. This is a data flow bug.

- [ ] **Step 1: Fix the key name in _build_query_text**

In `backend/agents/regulatory_screening.py`, line 80, change:

```python
# Before
f"Project type: {parsed.get('type', 'unknown')}",

# After
f"Project type: {parsed.get('project_type', 'unknown')}",
```

- [ ] **Step 2: Fix the key name in _build_prompt**

In `backend/agents/regulatory_screening.py`, line 120, change:

```python
# Before
  type: {parsed.get('type', 'unknown')}

# After
  type: {parsed.get('project_type', 'unknown')}
```

- [ ] **Step 3: Update the existing test to use the correct key**

In `backend/tests/test_regulatory_agent.py`, line 73, the test state already uses `"type"`:

```python
# Before
"parsed_project": {"type": "highway widening", "scale": "5 mi"},

# After
"parsed_project": {"project_type": "highway widening", "scale": "5 mi"},
```

- [ ] **Step 4: Run existing tests**

Run: `cd /Users/sanderschulman/Developer/aiagentsproject/backend && python -m pytest tests/test_regulatory_agent.py -v`
Expected: All 3 tests pass

- [ ] **Step 5: Commit**

```bash
git add backend/agents/regulatory_screening.py backend/tests/test_regulatory_agent.py
git commit -m "fix: correct project_type key mismatch in regulatory screening agent"
```

---

### Task 5: Rewrite regulatory screening prompt + use system message

**Files:**
- Modify: `backend/agents/regulatory_screening.py`

This is the core fix. Two changes: (1) move format rules into a `system` message, (2) rewrite the user prompt to distinguish permits from NEPA process steps.

- [ ] **Step 1: Add a system message constant**

At the top of `backend/agents/regulatory_screening.py` (after the imports), add:

```python
_SYSTEM = """\
You are a NEPA regulatory compliance assistant. Your job is to identify \
specific permits, approvals, and consultations that a project must obtain \
based on its characteristics and the regulatory excerpts provided.

You MUST respond with ONLY a valid JSON array. No markdown, no explanation, \
no code fences — just the raw JSON array.

Each item in the array must have exactly these four fields:
{
  "name": "<permit or approval name, e.g. 'Clean Water Act Section 404 Permit', 'ESA Section 7 Consultation'>",
  "jurisdiction": "<'Federal', 'State', or 'Local'>",
  "description": "<1-2 sentences: why this specific project triggers this requirement>",
  "citation": "<formal citation, e.g. '33 CFR §328.3', '50 CFR §402'>"
}

Rules:
- List PERMITS and APPROVALS the project must obtain, not NEPA process steps.
- Do NOT list "Environmental Assessment", "Finding of No Significant Impact", \
"Record of Decision", "Major Federal Action", or "Limitations on Actions During \
NEPA Process" as separate regulations — these are steps within NEPA review, not \
independent permits.
- You MAY list "NEPA Environmental Impact Statement" or "NEPA Environmental \
Assessment" as a single entry if the project triggers NEPA review, but only once.
- Do NOT copy breadcrumb paths, chunk headers, or [DEFINITION] tags into any field.
- Do NOT invent citations. Only cite regulations referenced in the provided excerpts.\
"""
```

- [ ] **Step 2: Rewrite _build_prompt to be a focused user message**

Replace the `_build_prompt` method:

```python
def _build_prompt(self, state: dict, hits: list[dict]) -> str:
    parsed = state.get("parsed_project") or {}
    env = state.get("environmental_data") or {}
    excerpt_lines = []
    for i, h in enumerate(hits, 1):
        meta = h.get("metadata") or {}
        excerpt_lines.append(
            f"[{i}] (cite: {meta.get('citation', '?')}, "
            f"sim: {h.get('similarity', 0):.2f})\n"
            f"    {h.get('content', '').strip()}"
        )
    excerpts = "\n\n".join(excerpt_lines)
    return f"""\
Project:
  type: {parsed.get('project_type', 'unknown')}
  scale: {parsed.get('scale', 'unknown')}
  coordinates: {state.get('coordinates', 'unknown')}
  flags: in_sfha={env.get('fema_flood_zones', {}).get('in_sfha', False)}, \
species_count={env.get('usfws_species', {}).get('count', 0)}, \
wetlands={env.get('nwi_wetlands', {}).get('count', 0)}, \
prime_farmland={env.get('usda_farmland', {}).get('is_prime', False)}

Regulatory excerpts (top {len(hits)} by relevance):
{excerpts}

Identify the permits, approvals, and consultations this project requires. Return JSON only."""
```

- [ ] **Step 3: Update the run() method to pass system message**

In the `run()` method, change line 62 from:

```python
# Before
raw = self.llm.complete(prompt)

# After
raw = self.llm.complete(prompt, system=_SYSTEM)
```

- [ ] **Step 4: Run existing tests**

Run: `cd /Users/sanderschulman/Developer/aiagentsproject/backend && python -m pytest tests/test_regulatory_agent.py -v`
Expected: All 3 tests pass (the mock LLM still returns valid JSON, system param is just passed through)

- [ ] **Step 5: Commit**

```bash
git add backend/agents/regulatory_screening.py
git commit -m "fix: rewrite regulatory screening prompt to distinguish permits from NEPA process steps"
```

---

### Task 6: Remove permits_required from project parser

**Files:**
- Modify: `backend/agents/project_parser.py`
- Modify: `backend/tests/test_project_parser.py`
- Modify: `frontend/src/components/AgentPipeline.jsx:68-86`

The project parser should only extract `project_type`, `scale`, and `location`. Permit determination is the regulatory screening agent's job.

- [ ] **Step 1: Update the prompt template**

In `backend/agents/project_parser.py`, replace the `_PROMPT_TEMPLATE`:

```python
_PROMPT_TEMPLATE = """\
Project name: {project_name}
Coordinates: {coordinates}
Description: {description}

Extract the following fields and return them as a JSON object:
- project_type  (string): the category of project, e.g. "solar farm", "highway expansion", "warehouse", "pipeline", etc.
- scale         (string): size or scope, e.g. "5 MW", "12 miles", "200,000 sq ft", "unknown"
- location      (string): human-readable place name inferred from the description or coordinates

Return exactly this structure:
{{"project_type": "...", "scale": "...", "location": "..."}}
"""
```

- [ ] **Step 2: Remove permits_required from the result normalization**

In the `run()` method, update the result dict (~line 61-66):

```python
            result = {
                "project_type": str(parsed.get("project_type", "unknown")),
                "scale":        str(parsed.get("scale", "unknown")),
                "location":     str(parsed.get("location", coordinates or "unknown")),
            }
```

And the fallback (~line 71-76):

```python
            result = {
                "project_type": "unknown",
                "scale": "unknown",
                "location": coordinates or "unknown",
            }
```

- [ ] **Step 3: Update test fixtures and remove permits-related tests**

In `backend/tests/test_project_parser.py`:

Update `VALID_RESPONSE`:

```python
VALID_RESPONSE = json.dumps({
    "project_type": "solar farm",
    "scale": "50 MW",
    "location": "Pittsburgh, PA",
})
```

Remove these test methods entirely:
- `test_permits_list` (in `TestProjectParserHappyPath`)
- `test_permits_always_list_even_if_llm_returns_string` (in `TestProjectParserOutputTypes`)

Update `test_all_fields_are_strings_except_permits` — rename to `test_all_fields_are_strings` and remove the permits assertion:

```python
    def test_all_fields_are_strings(self):
        agent = ProjectParserAgent(make_llm(VALID_RESPONSE))
        result = agent.run(dict(BASE_STATE))
        pp = result["parsed_project"]
        self.assertIsInstance(pp["project_type"], str)
        self.assertIsInstance(pp["scale"], str)
        self.assertIsInstance(pp["location"], str)
```

In `test_invalid_json_uses_fallback`, remove the permits assertion:

```python
    def test_invalid_json_uses_fallback(self):
        result = self._run_with("Sorry, I cannot help with that.")
        pp = result["parsed_project"]
        self.assertEqual(pp["project_type"], "unknown")
        self.assertEqual(pp["scale"], "unknown")
```

In `test_partial_json_missing_keys`, remove the permits assertion:

```python
    def test_partial_json_missing_keys(self):
        partial = json.dumps({"project_type": "pipeline"})
        agent = ProjectParserAgent(make_llm(partial))
        result = agent.run(dict(BASE_STATE))
        pp = result["parsed_project"]
        self.assertEqual(pp["project_type"], "pipeline")
        self.assertEqual(pp["scale"], "unknown")
```

- [ ] **Step 4: Update frontend to remove permits display from project parser card**

In `frontend/src/components/AgentPipeline.jsx`, replace the `renderProjectParser` function (lines 68-86):

```jsx
function renderProjectParser(data) {
  if (!data) return <Empty />
  return (
    <div style={s.outputBody}>
      <DataRow label="Type" value={data.project_type} />
      <DataRow label="Scale" value={data.scale} />
      <DataRow label="Location" value={data.location} />
    </div>
  )
}
```

- [ ] **Step 5: Run all tests**

Run: `cd /Users/sanderschulman/Developer/aiagentsproject/backend && python -m pytest tests/test_project_parser.py -v`
Expected: All remaining tests pass

- [ ] **Step 6: Commit**

```bash
git add backend/agents/project_parser.py backend/tests/test_project_parser.py frontend/src/components/AgentPipeline.jsx
git commit -m "fix: remove permits_required from project parser, delegate to regulatory screening agent"
```

---

### Task 7: Add CLAUDE_KEY to .env and verify end-to-end

**Files:**
- Modify: `.env` (or whatever local env file is used)

- [ ] **Step 1: Add CLAUDE_KEY to environment**

Add `CLAUDE_KEY=<your-api-key>` to the backend environment variables.

- [ ] **Step 2: Start the backend and verify startup logs**

Run: `cd /Users/sanderschulman/Developer/aiagentsproject/backend && uvicorn main:app --reload --host 0.0.0.0 --port 5050`

Expected in logs:
- `LLM provider: gemini`
- `Embedding provider: gemini`
- `Regulatory screening LLM: anthropic (haiku)`

- [ ] **Step 3: Run a test project through the pipeline**

Submit a project (e.g., 50 MW solar farm in Pittsburgh) and verify:
- Project parser card shows Type, Scale, Location — no permits section
- Regulatory screening returns valid JSON with actual permits (CWA 404, ESA 7, etc.), not NEPA process steps
- Each regulation has `name`, `jurisdiction`, `description`, `citation` fields

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "chore: verify end-to-end regulatory screening with Claude Haiku"
```
