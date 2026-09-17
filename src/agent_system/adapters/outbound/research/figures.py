"""Render DataTables to PNG with matplotlib (Agg backend, no display)."""

from __future__ import annotations

import io
import logging

from agent_system.domain.entities.research import DataTable

logger = logging.getLogger(__name__)

PALETTE = ["#2563EB", "#F59E0B", "#10B981", "#EF4444", "#8B5CF6", "#0EA5E9", "#F97316", "#64748B"]


def _all_numeric(xs: list) -> bool:
    try:
        [float(x) for x in xs]
        return True
    except (TypeError, ValueError):
        return False


def render_png(table: DataTable, width_px: int = 1200, height_px: int = 700, dpi: int = 150) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    series = [s for s in table.series if s.points]
    if not series:
        raise ValueError("table has no points")

    fig, ax = plt.subplots(figsize=(width_px / dpi, height_px / dpi), dpi=dpi)
    fig.patch.set_facecolor("white")

    labels = list(dict.fromkeys(str(p.x) for s in series for p in s.points))
    kind = table.kind
    if kind == "line" and not _all_numeric(labels):
        kind = "grouped_bar" if len(series) > 1 else "bar"
    if kind == "bar" and len(series) > 1:
        kind = "grouped_bar"

    if kind == "line":
        for i, s in enumerate(series):
            pts = sorted(((float(p.x), p.y) for p in s.points), key=lambda t: t[0])
            ax.plot([x for x, _ in pts], [y for _, y in pts], marker="o", linewidth=2,
                    color=PALETTE[i % len(PALETTE)], label=s.name)
    else:
        idx = np.arange(len(labels))
        n = len(series)
        width = 0.8 / max(n, 1)
        for i, s in enumerate(series):
            ys = {str(p.x): p.y for p in s.points}
            vals = [ys.get(lbl, np.nan) for lbl in labels]
            offset = (i - (n - 1) / 2) * width
            bars = ax.bar(idx + offset, vals, width=width * 0.95, color=PALETTE[i % len(PALETTE)], label=s.name)
            if len(labels) <= 8:
                for b, v in zip(bars, vals):
                    if v == v:  # not NaN
                        ax.annotate(f"{v:g}", (b.get_x() + b.get_width() / 2, b.get_height()),
                                    ha="center", va="bottom", fontsize=8, xytext=(0, 2),
                                    textcoords="offset points")
        ax.set_xticks(idx)
        ax.set_xticklabels(labels, rotation=20 if max(len(l) for l in labels) > 8 else 0, ha="right" if max(len(l) for l in labels) > 8 else "center")

    ylabel = table.y_label + (f" ({table.unit})" if table.unit and table.unit not in table.y_label else "")
    ax.set_xlabel(table.x_label)
    ax.set_ylabel(ylabel)
    ax.set_title(table.title, fontsize=12, fontweight="bold", loc="left")
    ax.grid(axis="y", alpha=0.25)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if len(series) > 1 or kind == "line":
        ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    return buf.getvalue()


def caption_for(ordinal: int, table: DataTable, ref_by_source: dict[str, int]) -> str:
    refs = sorted({ref_by_source[s] for s in table.source_ids if s in ref_by_source})
    cite = " " + "".join(f"[{r}]" for r in refs) if refs else ""
    unit = f" ({table.unit})" if table.unit else ""
    return f"Figure {ordinal}: {table.title}{unit}.{cite}"
