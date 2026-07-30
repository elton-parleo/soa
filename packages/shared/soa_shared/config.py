"""
Runtime configuration for /soa.

Reads from environment variables (set via .env loaded by python-dotenv,
or injected by the deployment platform). Never reads from /supply/config.py.
"""
import os

from dotenv import load_dotenv
load_dotenv()

SUPABASE_DB_HOST_URL: str = os.environ.get("SUPABASE_DB_HOST_URL", "")
SUPABASE_DB_PASSWORD: str = os.environ.get("SUPABASE_DB_PASSWORD", "")
DATABASE_URL: str = os.environ.get("DATABASE_URL", "")
DATABASE_URL_POOLED = os.getenv('DATABASE_URL_POOLED', None)
USE_POOLED_DB: str = os.getenv('USE_POOLED_DB', 'false')
OPEN_AI_API_KEY: str = os.environ.get("OPEN_AI_API_KEY", "")
PERPLEXITY_API_KEY: str = os.environ.get("PERPLEXITY_API_KEY", "")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
ANTHROPIC_CLAUDE_API_KEY: str = os.environ.get("ANTHROPIC_CLAUDE_API_KEY", "")

# Runner behaviour
RUNS_PER_SLOT: int = int(os.environ.get("RUNS_PER_SLOT", "5"))
SOA_DEFAULT_RUNS_PER_QUERY: int = int(os.environ.get("SOA_DEFAULT_RUNS_PER_QUERY", "5"))
SOA_MAX_CONCURRENT: int = int(os.environ.get("SOA_MAX_CONCURRENT", "3"))
SOA_INTER_RUN_DELAY_SECONDS: float = float(os.environ.get("SOA_INTER_RUN_DELAY_SECONDS", "2.0"))

# Per-platform request timeouts
# Claude/OpenAI: 60s — web search adds retrieval latency before generation
# Perplexity/Gemini: 30s — respond consistently within that window
SOA_CLAUDE_TIMEOUT_SECONDS: int = int(os.environ.get("SOA_CLAUDE_TIMEOUT_SECONDS", "120"))
SOA_OPENAI_TIMEOUT_SECONDS: int = int(os.environ.get("SOA_OPENAI_TIMEOUT_SECONDS", "120"))
SOA_PERPLEXITY_TIMEOUT_SECONDS: int = int(os.environ.get("SOA_PERPLEXITY_TIMEOUT_SECONDS", "120"))
SOA_GEMINI_TIMEOUT_SECONDS: int = int(os.environ.get("SOA_GEMINI_TIMEOUT_SECONDS", "120"))

# Gemini 503 UNAVAILABLE retry config
# 503 errors are transient server capacity pressure; handled with exponential
# backoff + jitter in gemini_runner.py, separate from the base retry logic.
SOA_GEMINI_503_MAX_RETRIES: int = int(os.environ.get("SOA_GEMINI_503_MAX_RETRIES", "3"))
SOA_GEMINI_FALLBACK_MODEL: str = os.environ.get("SOA_GEMINI_FALLBACK_MODEL", "gemini-2.5-flash")

# Per-platform concurrency limits (Fix 1: Claude serialized to avoid 429)
SOA_CLAUDE_MAX_CONCURRENT: int = int(os.environ.get("SOA_CLAUDE_MAX_CONCURRENT", "1"))
SOA_OPENAI_MAX_CONCURRENT: int = int(os.environ.get("SOA_OPENAI_MAX_CONCURRENT", "3"))
SOA_PERPLEXITY_MAX_CONCURRENT: int = int(os.environ.get("SOA_PERPLEXITY_MAX_CONCURRENT", "3"))
SOA_GEMINI_MAX_CONCURRENT: int = int(os.environ.get("SOA_GEMINI_MAX_CONCURRENT", "3"))

# Stage 25 (Part 4, Q2): SoA Lite is ChatGPT-only and now runs
# LITE_QUERY_COUNT (24) queries per scan, double the pre-Stage-25 count —
# a lead-gen visitor is waiting live on the result (see worker.py's
# get_next_planned_cycle), so lite cycles get their own, higher
# chatgpt-concurrency override instead of inheriting the shared
# SOA_OPENAI_MAX_CONCURRENT default (3) every other study type uses.
# run_orchestrator.py applies this ONLY when the cycle_code has the
# 'lite-' prefix (the same convention worker.py's queue-priority check
# uses) — never changes concurrency for a regular client cycle.
LITE_QUERY_CONCURRENCY: int = int(os.environ.get("LITE_QUERY_CONCURRENCY", "6"))

# Per-platform inter-run delays (Fix 3: Claude needs wider gap between runs)
SOA_CLAUDE_INTER_RUN_DELAY: float = float(os.environ.get("SOA_CLAUDE_INTER_RUN_DELAY", "3.0"))
SOA_DEFAULT_INTER_RUN_DELAY: float = float(os.environ.get("SOA_DEFAULT_INTER_RUN_DELAY", "2.0"))

# Parser
SOA_CODING_MODEL: str = "gpt-5.4-nano-2026-03-17"
SOA_MAX_CODING_CONCURRENT: int = int(os.environ.get("SOA_MAX_CODING_CONCURRENT", "5"))

# Incentive scoring (Rung-0) — compares stated incentives against Deal Engine ground truth
DEAL_ENGINE_BASE_URL: str = os.environ.get("DEAL_ENGINE_BASE_URL", "")
INCENTIVE_SCORING_ENABLED: bool = os.environ.get("INCENTIVE_SCORING_ENABLED", "false").lower() == "true"
SOA_INCENTIVE_PRICE_TOLERANCE_PCT: float = float(os.environ.get("SOA_INCENTIVE_PRICE_TOLERANCE_PCT", "0.01"))
SOA_DEAL_ENGINE_TIMEOUT_SECONDS: float = float(os.environ.get("SOA_DEAL_ENGINE_TIMEOUT_SECONDS", "10.0"))
SOA_DEAL_ENGINE_MAX_RETRIES: int = int(os.environ.get("SOA_DEAL_ENGINE_MAX_RETRIES", "2"))

# Validity gate (scoring/observation_scorer.py) — a scored row is
# 'measured' only when the Deal Engine actually evaluated >=N candidate
# deals for that merchant/category (applied_deals + available_deals is a
# clean partition of every deal considered — see
# deal_engine/calculator.py::calculate() in /supply). When the engine has
# no deal data for a merchant at all, both lists are empty and it echoes
# the input price back as true_cost — a 0% "gap" that looks like perfect
# accuracy but is actually no measurement. Preferred over the response's
# confidence value, which stays a flat, uninformative default (0.51) in
# the exact same no-data case rather than a purpose-built coverage
# signal — see soa/apps/pipeline scoring/observation_scorer.py's
# measurement_status assignment.
SOA_MEASUREMENT_MIN_DEALS_EVALUATED: int = int(os.environ.get("SOA_MEASUREMENT_MIN_DEALS_EVALUATED", "1"))

# Truecost sweep cycles — bounded concurrency for the Deal Engine sweep executor
SOA_TRUECOST_MAX_CONCURRENT: int = int(os.environ.get("SOA_TRUECOST_MAX_CONCURRENT", "3"))

# Merchant slug fallback map — used when soa_entities/merchants has no slug for a
# merchant_id. Format: "merchant_id:slug,merchant_id:slug".
SOA_MERCHANT_SLUG_FALLBACK_MAP: str = os.environ.get("SOA_MERCHANT_SLUG_FALLBACK_MAP", "")

# Eligibility conditioning — conditions M1/M3 on "live AND eligible" per the
# Deal Engine, using persona membership/tier state. Off by default so
# existing metrics output is unchanged.
ELIGIBILITY_CONDITIONING_ENABLED: bool = (
    os.environ.get("ELIGIBILITY_CONDITIONING_ENABLED", "false").lower() == "true"
)

# Grounded Gemini surface — gemini-2.5 with the google_search grounding tool,
# as a separate "gemini_grounded" platform. Off by default; the existing
# "gemini" platform/runner is never affected by this flag.
ENABLE_GEMINI_GROUNDED: bool = (
    os.environ.get("ENABLE_GEMINI_GROUNDED", "false").lower() == "true"
)

# Lifecycle-triggered sampling — schedules runs around Deal Engine incentive
# windows (launch / mid-window / pre-expiry / post-expiry) instead of plain
# cycle-based sampling. Off by default; does not affect cycle_manager.
INCENTIVE_SCHEDULING_ENABLED: bool = (
    os.environ.get("INCENTIVE_SCHEDULING_ENABLED", "false").lower() == "true"
)

# SKU-level measurement scope — gates the scope-aware coder prompt
# (constrained resolution against soa_scope_skus) and the SKU-level scorer.
# Off by default: the prompt, schema, and scoring path are byte-for-byte
# unchanged even if a cycle happens to have scope SKUs rows.
SKU_SCOPE_ENABLED: bool = (
    os.environ.get("SKU_SCOPE_ENABLED", "false").lower() == "true"
)

# Entity-template / cycle-snapshot scope resolution (soa_shared/scope_resolution.py).
# True (default): a Planned cycle that hasn't been customized tracks its
# measured entities' template edits live until it starts running, then
# freezes. False: the scope snapshot is materialized once at cycle
# creation and never resyncs from templates while Planned.
PLANNED_CYCLE_SCOPE_RESYNC: bool = (
    os.environ.get("PLANNED_CYCLE_SCOPE_RESYNC", "true").lower() == "true"
)

# Pipeline
SOA_PLATFORMS: str = os.environ.get("SOA_PLATFORMS", "chatgpt,perplexity,gemini,claude")
SOA_RUNNER_ERROR_ABORT_THRESHOLD: float = float(os.environ.get("SOA_RUNNER_ERROR_ABORT_THRESHOLD", "0.50"))
SOA_CODER_ERROR_WARN_THRESHOLD: float = float(os.environ.get("SOA_CODER_ERROR_WARN_THRESHOLD", "0.20"))

# Exports — defaults to an exports/ folder beside this config file
SOA_EXPORTS_DIR: str = os.environ.get(
    "SOA_EXPORTS_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "exports"),
)


def validate() -> None:
    """Raise at startup if required env vars are missing."""
    missing = [k for k in ("SUPABASE_DB_HOST_URL", "SUPABASE_DB_PASSWORD") if not os.environ.get(k)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {missing}")
