"""Seed-material ingestion: Excel/CSV, links, and free text -> one seed document."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def ingest_excel(path: str, llm=None, max_chars: int = 12000) -> str:
    """Read all sheets of an .xlsx/.xls file and summarize into text."""
    import pandas as pd

    sheets = pd.read_excel(path, sheet_name=None)
    parts = []
    for sheet_name, df in sheets.items():
        if df is None or df.empty:
            continue
        parts.append(f"## Sheet: {sheet_name}")
        # Include headers + first N rows as text
        sample = df.head(50).to_string(index=False)
        parts.append(sample)
    text = "\n\n".join(parts)
    return _maybe_summarize(text, llm, max_chars)


def ingest_csv(path: str, llm=None, max_chars: int = 12000) -> str:
    """Read a CSV file into text."""
    import pandas as pd

    df = pd.read_csv(path)
    if df is None or df.empty:
        return ""
    text = df.head(100).to_string(index=False)
    return _maybe_summarize(text, llm, max_chars)


def _maybe_summarize(text: str, llm, max_chars: int) -> str:
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    if llm is not None:
        try:
            from kairos.web import summarize_with_llm
            return summarize_with_llm(llm, text, max_chars)
        except Exception:
            logger.exception("Summarize failed; truncating instead.")
    return text[:max_chars]


def ingest_links(urls, engine, max_chars: int = 6000) -> str:
    """Fetch + summarize each URL into text."""
    parts = []
    for url in urls:
        url = url.strip()
        if not url:
            continue
        try:
            data = engine.scrape_page(url)
            title = data.get("title") or url
            text = data.get("text") or ""
            parts.append(f"## Source: {url} ({title})\n{text[:max_chars]}")
        except Exception as e:
            parts.append(f"## Source: {url}\n(Error fetching: {e})")
    return "\n\n".join(parts)


def build_seed(question: str, files=None, links=None, text=None, engine=None) -> str:
    """Combine all inputs into a single seed document for prediction."""
    sections = [f"PREDICTION QUESTION:\n{question}"]

    if text and text.strip():
        sections.append(f"ADDITIONAL CONTEXT:\n{text.strip()}")

    files = files or []
    for f in files:
        p = Path(f)
        if not p.exists():
            sections.append(f"## File (missing): {p.name}")
            continue
        ext = p.suffix.lower()
        try:
            if ext in (".xlsx", ".xls"):
                sections.append(f"## File: {p.name}\n" + ingest_excel(f, engine.llm if engine else None))
            elif ext == ".csv":
                sections.append(f"## File: {p.name}\n" + ingest_csv(f, engine.llm if engine else None))
            else:
                sections.append(f"## File: {p.name}\n" + p.read_text(encoding="utf-8", errors="ignore")[:12000])
        except Exception as e:
            sections.append(f"## File: {p.name}\n(Error reading: {e})")

    if links:
        sections.append(ingest_links(links, engine))

    return "\n\n".join(sections)
