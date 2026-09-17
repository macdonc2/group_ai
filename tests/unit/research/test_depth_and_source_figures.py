"""Recursive research rounds and figures lifted from source PDFs, no network."""

import pytest

from agent_system.adapters.outbound.research import lanes as lanes_mod
from agent_system.adapters.outbound.research import source_figures as sf
from agent_system.adapters.outbound.research.lanes import LaneDeps, run_lane
from agent_system.adapters.outbound.research.schemas import FindingsOut, GapPlan, QueryPlan
from agent_system.adapters.outbound.research.writer import source_figure_caption
from agent_system.domain.entities.research import Finding, Source


# ---------------------------------------------------------------------------
# rounds
# ---------------------------------------------------------------------------

def _fake_lane_pipeline(monkeypatch):
    calls = {"plan": 0, "search": [], "findings": 0, "gap": 0}

    async def plan(question, lane, deps, n):
        calls["plan"] += 1
        return [f"q{i}" for i in range(n)]

    async def search(lane, queries, deps):
        calls["search"].append(list(queries))
        # round 1 returns two sources; gap round returns one new + one duplicate
        if queries and queries[0].startswith("gap"):
            return [Source(id="", lane=lane, title="New Paper", url="https://x/new", snippet="new"),
                    Source(id="", lane=lane, title="Paper One", url="https://x/one", snippet="dup")]
        return [Source(id="", lane=lane, title="Paper One", url="https://x/one", snippet="s1"),
                Source(id="", lane=lane, title="Paper Two", url="https://x/two", snippet="s2")]

    async def findings(question, lane, sources, deps):
        calls["findings"] += 1
        return FindingsOut(findings=[Finding(claim=f"claim from {s.id}", evidence="e", source_id=s.id) for s in sources])

    async def gap(question, lane, found, deps, n):
        calls["gap"] += 1
        return GapPlan(summary=f"summary after {len(found)} findings", gaps=["what about X?"], queries=["gap query"])

    async def enrich(sources, limit):
        return sources

    async def tables(question, sources, deps):
        return []

    monkeypatch.setattr(lanes_mod, "_plan_queries", plan)
    monkeypatch.setattr(lanes_mod, "_search", search)
    monkeypatch.setattr(lanes_mod, "_findings", findings)
    monkeypatch.setattr(lanes_mod, "_gap_plan", gap)
    monkeypatch.setattr(lanes_mod, "_enrich_with_pages", enrich)
    monkeypatch.setattr(lanes_mod, "_tables", tables)
    return calls


@pytest.mark.unit
async def test_depth_one_is_a_single_pass(monkeypatch):
    calls = _fake_lane_pipeline(monkeypatch)
    events = []

    async def emit(t, lane, msg, data):
        events.append(t)

    result = await run_lane("academic", "Q?", LaneDeps(api_key="k", strong_model="m", fast_model="f", depth=1), emit)
    assert [s.id for s in result.sources] == ["A1", "A2"]
    assert len(result.findings) == 2 and result.summaries == []
    assert calls["gap"] == 0 and "lane_round" not in events


@pytest.mark.unit
async def test_depth_two_adds_a_gap_round_with_unique_ids(monkeypatch):
    calls = _fake_lane_pipeline(monkeypatch)
    events = []

    async def emit(t, lane, msg, data):
        events.append((t, data))

    result = await run_lane("practical", "Q?", LaneDeps(api_key="k", strong_model="m", fast_model="f", depth=2), emit)
    # the duplicate from the gap round was dropped, the new one got the next id
    assert [s.id for s in result.sources] == ["P1", "P2", "P3"]
    assert result.sources[2].title == "New Paper"
    assert len(result.findings) == 3
    assert result.summaries == ["summary after 2 findings"]
    assert result.queries == ["q0", "q1", "q2", "q3", "gap query"]
    assert calls["gap"] == 1 and calls["findings"] == 2 and calls["search"][1] == ["gap query"]
    types = [t for t, _ in events]
    assert types.index("lane_round") < types.index("lane_gaps") < types.index("lane_complete")
    round_ev = next(d for t, d in events if t == "lane_round")
    assert round_ev["round"] == 2
    assert events[-1][1]["rounds"] == 2


@pytest.mark.unit
async def test_depth_three_stops_early_when_no_gap_queries(monkeypatch):
    calls = _fake_lane_pipeline(monkeypatch)

    async def no_more(question, lane, found, deps, n):
        calls["gap"] += 1
        return GapPlan(summary="nothing missing", gaps=[], queries=[])

    monkeypatch.setattr(lanes_mod, "_gap_plan", no_more)

    async def emit(t, lane, msg, data):
        pass

    result = await run_lane("empirical", "Q?", LaneDeps(api_key="k", strong_model="m", fast_model="f", depth=3), emit)
    assert calls["gap"] == 1 and len(result.sources) == 2  # broke out after the first empty plan


# ---------------------------------------------------------------------------
# source figures
# ---------------------------------------------------------------------------

def _pdf_with_figure(caption: str = "Figure 2: Accuracy versus depth for both models.") -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 60), "Some Paper Title", fontsize=14)
    # a big raster image (well above the min size), then its caption right below
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 640, 480), 0)
    pix.clear_with(200)
    rect = fitz.Rect(72, 100, 540, 450)
    page.insert_image(rect, pixmap=pix)
    page.insert_text((72, 470), caption, fontsize=10)
    page.insert_text((72, 700), "Body text that is not a caption.", fontsize=10)
    # a tiny logo that must be ignored
    tiny = fitz.Pixmap(fontsize=None) if False else fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 40), 0)
    page.insert_image(fitz.Rect(560, 20, 600, 60), pixmap=tiny)
    out = doc.tobytes()
    doc.close()
    return out


@pytest.mark.unit
def test_extract_figures_finds_image_and_caption():
    src = Source(id="A1", lane="academic", title="Some Paper", url="https://arxiv.org/abs/2401.00001")
    figs = sf.extract_figures(_pdf_with_figure(), src, max_figures=2)
    assert len(figs) == 1
    f = figs[0]
    assert f.number == 2 and f.caption.startswith("Accuracy versus depth")
    assert f.page == 1 and f.width == 640 and f.height == 480
    assert sf.png_bytes_ok(f.png)


@pytest.mark.unit
def test_extract_figures_survives_garbage():
    src = Source(id="A1", lane="academic", title="Broken")
    assert sf.extract_figures(b"not a pdf", src) == []


@pytest.mark.unit
def test_arxiv_url_and_ranking():
    assert sf.arxiv_pdf_url("https://arxiv.org/abs/2305.17289v1") == "https://arxiv.org/pdf/2305.17289v1"
    assert sf.arxiv_pdf_url("http://arxiv.org/pdf/2305.17289") == "https://arxiv.org/pdf/2305.17289"
    assert sf.arxiv_pdf_url("https://doi.org/10.1/x") is None
    a = Source(id="A1", lane="academic", title="one", url="https://arxiv.org/abs/2401.00001")
    b = Source(id="A2", lane="academic", title="two", url="https://arxiv.org/abs/2402.00002v2")
    c = Source(id="A3", lane="academic", title="no pdf", url="https://doi.org/10.1/x")
    p = Source(id="P1", lane="practical", title="blog", url="https://arxiv.org/abs/2403.00003")
    findings = [Finding(claim="c", evidence="e", source_id=i) for i in ("A2", "A2", "A1", "A3", "P1")]
    ranked = sf.rank_sources_for_figures([a, b, c, p], findings)
    assert [s.id for s in ranked] == ["A2", "A1"]


@pytest.mark.unit
def test_source_caption_links_the_paper():
    src = Source(id="A1", lane="academic", title="Some Paper", url="https://arxiv.org/abs/2401.00001")
    cap = source_figure_caption(3, "Accuracy versus depth.", src, 7, 2)
    assert cap == "Figure 3: Accuracy versus depth. (their Figure 2) [7] — [Some Paper](https://arxiv.org/abs/2401.00001)"
    cap2 = source_figure_caption(1, "", src, None, None)
    assert cap2.startswith("Figure 1: Figure from Some Paper — [Some Paper](")
