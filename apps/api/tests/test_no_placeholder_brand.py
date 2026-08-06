"""
Stage 9 (P1): repo-wide guard that the retired demo placeholder brand
"Drunk Elephant" never creeps back into lite/demo/fixture code.

A handful of files legitimately keep it and were explicitly flagged and
left untouched during the Stage 9 swap (P2): three vendored copies of
soa_models.py use it only as a generic column-comment example, and the
pipeline seed/test files use it as unrelated, non-lite sample content.
Everything else in the repo must be clean.
"""
import re
from pathlib import Path

PLACEHOLDER_PATTERN = re.compile(r"drunk[\s\-]?elephant", re.IGNORECASE)

REPO_ROOT = Path(__file__).resolve().parents[3]

EXCLUDED_DIRS = {
    ".git", "node_modules", "dist", "build", "__pycache__", ".pytest_cache",
    ".venv", "venv", ".vite",
    # Local, gitignored design-export reference material (mocks + design
    # tokens) — never committed, never imported at build time, and its
    # own third-party doc copy is outside this repo's control.
    "design-refs",
}

# Explicitly flagged during Stage 9 P2 review and intentionally left
# untouched (not lite/demo/fixture content) — see stage 9 diagnostic.
ALLOWED_FILES = {
    REPO_ROOT / "packages/shared/soa_shared/models/soa_models.py",
    REPO_ROOT / "apps/pipeline/soa_shared/models/soa_models.py",
    REPO_ROOT / "apps/api/soa_shared/models/soa_models.py",
    REPO_ROOT / "apps/pipeline/seeds/soa_queries_seed.py",
    REPO_ROOT / "apps/pipeline/tests/test_entity_helpers.py",
}

TEXT_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".yaml", ".yml"}


THIS_FILE = Path(__file__).resolve()


def _iter_repo_files():
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path == THIS_FILE:
            continue
        if path.suffix not in TEXT_SUFFIXES:
            continue
        if any(part in EXCLUDED_DIRS for part in path.parts):
            continue
        yield path


def test_no_placeholder_brand_outside_allowed_files():
    offenders = []
    for path in _iter_repo_files():
        if path in ALLOWED_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if PLACEHOLDER_PATTERN.search(text):
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert not offenders, (
        "Found the retired placeholder brand outside the allowed files: "
        + ", ".join(sorted(offenders))
    )


def test_allowed_files_still_exist_and_still_contain_it():
    """
    Guards the exclusion list itself: if one of these files is edited so it
    no longer contains the placeholder, drop it from ALLOWED_FILES so this
    test suite keeps enforcing the tightest possible scope.
    """
    stale = []
    for path in ALLOWED_FILES:
        if not path.is_file():
            stale.append(f"{path} (missing)")
            continue
        text = path.read_text(encoding="utf-8")
        if not PLACEHOLDER_PATTERN.search(text):
            stale.append(f"{path} (no longer contains the placeholder)")

    assert not stale, (
        "ALLOWED_FILES is stale, update test_no_placeholder_brand.py: "
        + ", ".join(stale)
    )
