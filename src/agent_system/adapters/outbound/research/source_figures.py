"""Figures lifted straight out of source papers (arXiv PDFs).

For a handful of the most-cited academic sources we download the PDF, find
the embedded raster figures with PyMuPDF, pair each with the nearest
"Figure N:" caption on the page, and keep the best one or two. Fail-soft:
any problem with a paper just yields nothing for that paper.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

import httpx

from agent_system.domain.entities.research import Finding, Source

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
MAX_PDF_BYTES = 20 * 1024 * 1024
MIN_SIDE_PX = 320          # skip icons, logos, equation snippets
MIN_AREA_FRACTION = 0.06   # of the page area
MAX_PAGES = 14
_CAPTION_RE = re.compile(r"^\s*(Fig\.?|Figure)\s*(\d+)[.:]?\s*(.*)", re.I | re.S)
_ARXIV_ID_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}(?:v\d+)?|[a-z\-]+/[0-9]{7})")


@dataclass
class ExtractedFigure:
    png: bytes
    caption: str          # the paper's own caption (may be empty)
    number: int | None    # the paper's figure number
    page: int
    width: int
    height: int
    source: Source


def arxiv_pdf_url(url: str | None) -> str | None:
    if not url:
        return None
    m = _ARXIV_ID_RE.search(url)
    return f"https://arxiv.org/pdf/{m.group(1)}" if m else None


def rank_sources_for_figures(sources: list[Source], findings: list[Finding], limit: int = 3) -> list[Source]:
    """Most-cited academic sources that have an arXiv PDF."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.source_id] = counts.get(f.source_id, 0) + 1
    candidates = [s for s in sources if s.lane == "academic" and arxiv_pdf_url(s.url)]
    candidates.sort(key=lambda s: (-counts.get(s.id, 0), s.id))
    return [s for s in candidates if counts.get(s.id, 0) > 0][:limit]


async def download_pdf(url: str) -> bytes | None:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True,
                                     headers={"User-Agent": "agent-system-deep-research/1.0"}) as client:
            r = await client.get(url)
            r.raise_for_status()
            if "pdf" not in r.headers.get("content-type", "") and not r.content.startswith(b"%PDF"):
                return None
            if len(r.content) > MAX_PDF_BYTES:
                return None
            return r.content
    except Exception as exc:  # noqa: BLE001
        logger.info("pdf download failed %s: %s", url, exc)
        return None


def _captions_on_page(page) -> list[tuple[float, float, int | None, str]]:
    """(y_top, y_bottom, figure number, text) for blocks that look like captions."""
    out = []
    for x0, y0, x1, y1, text, *_ in page.get_text("blocks"):
        m = _CAPTION_RE.match(text or "")
        if m:
            num = int(m.group(2)) if m.group(2).isdigit() else None
            body = re.sub(r"\s+", " ", m.group(3)).strip()
            out.append((y0, y1, num, body))
    return out


def extract_figures(pdf_bytes: bytes, source: Source, max_figures: int = 2) -> list[ExtractedFigure]:
    """Best raster figures with their captions. Pure function, no network."""
    import fitz  # PyMuPDF

    found: list[ExtractedFigure] = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        logger.info("pdf open failed for %s: %s", source.id, exc)
        return []
    try:
        for pno in range(min(len(doc), MAX_PAGES)):
            page = doc[pno]
            page_area = float(page.rect.width * page.rect.height) or 1.0
            captions = _captions_on_page(page)
            seen_xrefs: set[int] = set()
            for img in page.get_images(full=True):
                xref = img[0]
                if xref in seen_xrefs:
                    continue
                seen_xrefs.add(xref)
                rects = page.get_image_rects(xref)
                if not rects:
                    continue
                rect = max(rects, key=lambda r: r.width * r.height)
                if rect.width * rect.height / page_area < MIN_AREA_FRACTION:
                    continue
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n - pix.alpha >= 4:  # CMYK -> RGB
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    if pix.width < MIN_SIDE_PX or pix.height < MIN_SIDE_PX:
                        continue
                    png = pix.tobytes("png")
                except Exception as exc:  # noqa: BLE001
                    logger.info("pixmap failed xref %s: %s", xref, exc)
                    continue
                # nearest caption below the image (within ~a quarter page), else nearest anywhere
                below = [c for c in captions if c[0] >= rect.y1 - 4 and c[0] - rect.y1 < page.rect.height * 0.25]
                pick = min(below, key=lambda c: c[0] - rect.y1) if below else (
                    min(captions, key=lambda c: abs(c[0] - rect.y1)) if captions else None
                )
                found.append(ExtractedFigure(
                    png=png, caption=pick[3] if pick else "", number=pick[2] if pick else None,
                    page=pno + 1, width=pix.width, height=pix.height, source=source,
                ))
    finally:
        doc.close()

    # Prefer figures that have a caption, then earlier pages, then larger.
    found.sort(key=lambda f: (0 if f.caption else 1, f.page, -(f.width * f.height)))
    # One figure per paper figure number
    seen_nums: set[int | None] = set()
    out = []
    for f in found:
        if f.number in seen_nums and f.number is not None:
            continue
        seen_nums.add(f.number)
        out.append(f)
        if len(out) >= max_figures:
            break
    return out


async def figures_from_sources(sources: list[Source], findings: list[Finding], max_total: int = 2) -> list[ExtractedFigure]:
    """Download the top-cited arXiv papers and pull their best figures."""
    out: list[ExtractedFigure] = []
    for s in rank_sources_for_figures(sources, findings):
        pdf_url = arxiv_pdf_url(s.url)
        if not pdf_url:
            continue
        pdf = await download_pdf(pdf_url)
        if not pdf:
            continue
        figs = extract_figures(pdf, s, max_figures=1 if len(out) else 2)
        out.extend(figs)
        if len(out) >= max_total:
            break
    return out[:max_total]


def normalise_png(png: bytes, max_width: int = 1400) -> bytes:
    """Downscale very large extracted images so the report stays light."""
    try:
        import fitz

        pix = fitz.Pixmap(png)
        if pix.width <= max_width:
            return png
        scale = max_width / pix.width
        mat = fitz.Matrix(scale, scale)
        doc = fitz.open()
        page = doc.new_page(width=pix.width * scale, height=pix.height * scale)
        page.insert_image(page.rect, pixmap=pix)
        shrunk = page.get_pixmap(matrix=fitz.Matrix(1, 1))
        del mat
        return shrunk.tobytes("png")
    except Exception:  # noqa: BLE001
        return png


def png_bytes_ok(png: bytes) -> bool:
    return png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000


def _unused(_: io.BytesIO) -> None:  # keep io import meaningful for type checkers
    return None
