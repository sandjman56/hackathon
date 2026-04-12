"""Per-model pricing table for cost tracking in the pipeline.

All prices are USD per 1,000,000 tokens, taken from each provider's
official pricing page on LAST_UPDATED.

Refresh workflow: re-run web searches for each SOURCES URL,
update the numbers + LAST_UPDATED, and commit.
"""

LAST_UPDATED = "2026-04-11"

SOURCES = {
    "openai": "https://openai.com/api/pricing/",
    "anthropic": "https://www.anthropic.com/pricing",
    "gemini": "https://ai.google.dev/pricing",
}

# Each entry: {"provider": str, "label": str, "input": float, "output": float}
# input/output are USD per 1,000,000 tokens.
MODEL_PRICING: dict[str, dict] = {
    "gpt-5.4": {
        "provider": "openai",
        "label": "OpenAI \u00b7 GPT-5.4",
        "input": 2.50,
        "output": 15.00,
    },
    "gpt-5.4-mini": {
        "provider": "openai",
        "label": "OpenAI \u00b7 GPT-5.4 mini",
        "input": 0.75,
        "output": 4.50,
    },
    "claude-opus-4-6": {
        "provider": "anthropic",
        "label": "Claude \u00b7 Opus 4.6",
        "input": 5.00,
        "output": 25.00,
    },
    "claude-sonnet-4-6": {
        "provider": "anthropic",
        "label": "Claude \u00b7 Sonnet 4.6",
        "input": 3.00,
        "output": 15.00,
    },
    "claude-haiku-4-5-20251001": {
        "provider": "anthropic",
        "label": "Claude \u00b7 Haiku 4.5",
        "input": 1.00,
        "output": 5.00,
    },
    "gemini-2.5-pro": {
        "provider": "gemini",
        "label": "Gemini \u00b7 2.5 Pro",
        "input": 1.25,
        "output": 10.00,
    },
    "gemini-2.5-flash": {
        "provider": "gemini",
        "label": "Gemini \u00b7 2.5 Flash",
        "input": 0.30,
        "output": 2.50,
    },
    "gemini-2.0-flash": {
        "provider": "gemini",
        "label": "Gemini \u00b7 2.0 Flash",
        "input": 0.10,
        "output": 0.40,
    },
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Compute USD cost for one completion. Returns 0.0 for unknown models."""
    p = MODEL_PRICING.get(model)
    if not p:
        return 0.0
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
