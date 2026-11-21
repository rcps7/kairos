"""Draw & write artifacts: diagrams (SVG) and documents, stored in the data root.

Everything is saved under ``<storage_root>/Kairos/Artifacts/``. SVG produced by
an LLM is sanitized first (scripts, event handlers, ``javascript:`` URIs and
external ``href`` references are removed) so an opened file cannot execute code
or load remote resources.

Config (``artifacts``): ``{ "enabled": true, "allow_svg": true, "max_bytes": 2000000 }``
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from kairos import config, safety

logger = logging.getLogger(__name__)

_FORBIDDEN_TAGS = {"script", "foreignobject", "iframe", "image", "use", "a"}
_NAME_RE = re.compile(r"[^A-Za-z0-9._-]")
_TEXT_EXTS = {"md", "markdown", "txt", "py", "json", "csv", "html", "xml", "yaml",
              "yml", "js", "ts", "c", "cpp", "h", "ino"}


def _cfg() -> dict:
    try:
        return config.load_config().get("artifacts", {}) or {}
    except Exception:
        return {}


def enabled() -> bool:
    return bool(_cfg().get("enabled", True))


def _dir() -> Path:
    root = config.load_config().get("storage_root", str(Path.home()))
    d = Path(root) / "Kairos" / "Artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(name: str, default_ext: str) -> str:
    name = (name or "").strip().replace("\\", "_").replace("/", "_")
    name = _NAME_RE.sub("_", name).strip("._") or "artifact"
    if "." not in name:
        name = f"{name}.{default_ext}"
    return name[:120]


def _local(tag) -> str:
    return str(tag).split("}")[-1].lower()


def sanitize_svg(svg: str) -> str:
    """Return a safe SVG string, or raise ValueError if it is not valid SVG."""
    svg = (svg or "").strip()
    if "```" in svg:
        svg = re.sub(r"^```[a-zA-Z]*\n?", "", svg)
        svg = re.sub(r"\n?```$", "", svg).strip()
    try:
        root = ET.fromstring(svg)
    except Exception as e:
        raise ValueError(f"Invalid SVG: {e}")
    if _local(root.tag) != "svg":
        raise ValueError("SVG root element must be <svg>.")

    def clean(elem):
        for child in list(elem):
            if _local(child.tag) in _FORBIDDEN_TAGS:
                elem.remove(child)
            else:
                clean(child)
        for k in list(elem.attrib):
            lk = k.lower()
            val = str(elem.attrib.get(k) or "")
            if lk.startswith("on") or "javascript:" in val.lower():
                del elem.attrib[k]
            elif lk.endswith("href") and not val.strip().startswith("#"):
                del elem.attrib[k]

    clean(root)
    return ET.tostring(root, encoding="unicode")


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------
def write_document(name: str, content: str, fmt: str = None) -> str:
    if not enabled():
        raise PermissionError("Artifacts are disabled (artifacts.enabled).")
    ext = (fmt or "").lstrip(".").lower() or "md"
    if ext not in _TEXT_EXTS and ext not in ("svg",):
        ext = "md"
    data = content or ""
    max_bytes = int(_cfg().get("max_bytes", 2_000_000))
    if len(data.encode("utf-8", "ignore")) > max_bytes:
        raise ValueError("Document exceeds the configured artifact size limit.")
    path = _dir() / _safe_name(name, ext)
    safety.atomic_write_text(path, data)
    return str(path)


def draw_svg(name: str, svg: str) -> str:
    if not enabled():
        raise PermissionError("Artifacts are disabled (artifacts.enabled).")
    if not _cfg().get("allow_svg", True):
        raise PermissionError("SVG output is disabled (artifacts.allow_svg).")
    clean = sanitize_svg(svg)
    path = _dir() / _safe_name(name, "svg")
    safety.atomic_write_text(path, clean)
    return str(path)


def list_artifacts(limit: int = 200) -> list:
    out = []
    try:
        d = _dir()
    except Exception:
        return out
    files = sorted(d.glob("*"), key=lambda p: p.stat().st_mtime if p.exists() else 0,
                   reverse=True)
    for p in files[:limit]:
        try:
            st = p.stat()
            out.append({"name": p.name, "path": str(p), "size": st.st_size,
                        "mtime": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()})
        except Exception:
            continue
    return out


def delete_artifact(path: str) -> bool:
    """Delete a single artifact, confined to the Artifacts folder."""
    d = _dir().resolve()
    p = Path(path).resolve()
    if p != d and d not in p.parents:
        raise PermissionError("Refusing to delete a file outside the artifacts folder.")
    if not p.exists() or not p.is_file():
        return False
    p.unlink()
    return True


# ---------------------------------------------------------------------------
# Dependency-light SVG builders
# ---------------------------------------------------------------------------
def _svg(width, height, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
            f'<rect width="100%" height="100%" fill="#0d1117"/>'
            f'<g font-family="Segoe UI, sans-serif" fill="#e6edf3">{body}</g></svg>')


def bar_chart(title: str, labels, values, width: int = 640, height: int = 400) -> str:
    labels = [str(x) for x in (labels or [])]
    values = [float(v) for v in (values or [])]
    n = max(1, len(values))
    vmax = max(values) if values else 1.0
    vmax = vmax if vmax > 0 else 1.0
    pad, top = 40, 50
    bw = (width - 2 * pad) / n * 0.7
    gap = (width - 2 * pad) / n
    bars = [f'<text x="{width/2}" y="28" text-anchor="middle" font-size="18" '
            f'fill="#00ff66">{title}</text>']
    for i, v in enumerate(values):
        h = (height - top - pad) * (v / vmax)
        x = pad + i * gap + (gap - bw) / 2
        y = height - pad - h
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" '
                    f'fill="#00b84d"/>')
        bars.append(f'<text x="{x + bw/2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
                    f'font-size="12" fill="#e6edf3">{v:g}</text>')
        lab = labels[i] if i < len(labels) else str(i + 1)
        bars.append(f'<text x="{x + bw/2:.1f}" y="{height - pad + 18}" '
                    f'text-anchor="middle" font-size="11" fill="#9aa5b1">{lab}</text>')
    bars.append(f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" '
                f'y2="{height - pad}" stroke="#30363d"/>')
    return _svg(width, height, "".join(bars))


def line_chart(title: str, labels, values, width: int = 640, height: int = 400) -> str:
    labels = [str(x) for x in (labels or [])]
    values = [float(v) for v in (values or [])]
    n = max(1, len(values))
    vmax = max(values) if values else 1.0
    vmax = vmax if vmax > 0 else 1.0
    vmin = min(values) if values else 0.0
    span = (vmax - vmin) or 1.0
    pad, top = 40, 50
    step = (width - 2 * pad) / max(1, n - 1)
    pts = []
    for i, v in enumerate(values):
        x = pad + i * step
        y = top + (height - top - pad) * (1 - (v - vmin) / span)
        pts.append(f"{x:.1f},{y:.1f}")
    body = [f'<text x="{width/2}" y="28" text-anchor="middle" font-size="18" '
            f'fill="#00ff66">{title}</text>',
            f'<polyline points="{" ".join(pts)}" fill="none" stroke="#00ff66" '
            f'stroke-width="2"/>']
    for i, pt in enumerate(pts):
        x, y = pt.split(",")
        body.append(f'<circle cx="{x}" cy="{y}" r="3" fill="#00b84d"/>')
        if i < len(labels):
            body.append(f'<text x="{x}" y="{height - pad + 18}" text-anchor="middle" '
                        f'font-size="11" fill="#9aa5b1">{labels[i]}</text>')
    return _svg(width, height, "".join(body))


def flowchart(title: str, nodes, edges, width: int = 760, height: int = 460) -> str:
    nodes = [str(n) for n in (nodes or [])]
    bw, bh, pad = 160, 46, 30
    per_row = max(1, (width - pad) // (bw + pad))
    pos = {}
    body = [f'<text x="{width/2}" y="28" text-anchor="middle" font-size="18" '
            f'fill="#00ff66">{title}</text>']
    for i, name in enumerate(nodes):
        r, c = divmod(i, per_row)
        x = pad + c * (bw + pad)
        y = 60 + r * (bh + pad)
        pos[i] = (x, y)
        body.append(f'<rect x="{x}" y="{y}" width="{bw}" height="{bh}" rx="8" '
                    f'fill="#161b22" stroke="#00b84d"/>')
        body.append(f'<text x="{x + bw/2}" y="{y + bh/2 + 5}" text-anchor="middle" '
                    f'font-size="12" fill="#e6edf3">{name[:22]}</text>')
    for e in (edges or []):
        try:
            a, b = int(e[0]), int(e[1])
        except Exception:
            continue
        if a in pos and b in pos:
            ax, ay = pos[a]
            bx, by = pos[b]
            body.append(f'<line x1="{ax + bw/2}" y1="{ay + bh}" x2="{bx + bw/2}" '
                        f'y2="{by}" stroke="#9aa5b1" marker-end="url(#arrow)"/>')
    body.insert(0, '<defs><marker id="arrow" markerWidth="10" markerHeight="10" '
                   'refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" '
                   'fill="#9aa5b1"/></marker></defs>')
    return _svg(width, height, "".join(body))
