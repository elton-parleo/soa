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

# Per-platform inter-run delays (Fix 3: Claude needs wider gap between runs)
SOA_CLAUDE_INTER_RUN_DELAY: float = float(os.environ.get("SOA_CLAUDE_INTER_RUN_DELAY", "3.0"))
SOA_DEFAULT_INTER_RUN_DELAY: float = float(os.environ.get("SOA_DEFAULT_INTER_RUN_DELAY", "2.0"))

# Parser
SOA_CODING_MODEL: str = "gpt-5.4-nano-2026-03-17"
SOA_MAX_CODING_CONCURRENT: int = int(os.environ.get("SOA_MAX_CODING_CONCURRENT", "5"))

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
