"""Source parsers and figure rendering, no network."""

import pytest

from agent_system.adapters.outbound.research import sources as src
from agent_system.adapters.outbound.research.figures import caption_for, render_png
from agent_system.domain.entities.research import DataPoint, DataSeries, DataTable, Source

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2305.17289v1</id>
    <published>2023-05-26T00:00:00Z</published>
    <title>  Physics-informed   FWI  </title>
    <summary>We study full waveform inversion.   Results improve.</summary>
    <author><name>A. Author</name></author>
    <author><name>B. Author</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/1111.1111v2</id>
    <published>2011-01-01T00:00:00Z</published>
    <title>Second</title>
    <summary>Second summary.</summary>
  </entry>
</feed>"""

S2 = {
    "data": [
        {"title": "Paper One", "abstract": "Abstract one.", "year": 2024, "venue": "NeurIPS",
         "authors": [{"name": "X"}, {"name": "Y"}], "externalIds": {"ArXiv": "2401.00001"}},
        {"title": "", "abstract": "no title, dropped"},
        {"title": "DOI paper", "abstract": None, "year": None, "externalIds": {"DOI": "10.1/abc"}, "url": "https://s2/x"},
    ]
}


@pytest.mark.unit
class TestParsers:
    def test_arxiv_atom(self):
        out = src.parse_arxiv_atom(ATOM)
        assert [s.title for s in out] == ["Physics-informed FWI", "Second"]
        assert out[0].year == 2023 and out[0].authors == ["A. Author", "B. Author"]
        assert out[0].url == "http://arxiv.org/abs/2305.17289v1"
        assert out[0].snippet == "We study full waveform inversion. Results improve."
        assert out[0].lane == "academic" and out[0].venue == "arXiv"

    def test_semantic_scholar(self):
        out = src.parse_semantic_scholar(S2)
        assert [s.title for s in out] == ["Paper One", "DOI paper"]
        assert out[0].url == "https://arxiv.org/abs/2401.00001"
        assert out[1].url == "https://doi.org/10.1/abc"
        assert out[1].snippet == "" and out[1].venue == "Semantic Scholar"

    def test_dedupe_and_ids(self):
        a = Source(id="", lane="academic", title="Same Title", url="https://x/y/")
        b = Source(id="", lane="academic", title="Same Title", url="https://x/y")
        c = Source(id="", lane="academic", title="Other", url=None)
        d = Source(id="", lane="academic", title="OTHER!", url=None)  # same normalised title
        out = src.assign_ids(src.dedupe([a, b, c, d]), "practical")
        assert [s.id for s in out] == ["P1", "P2"]
        assert all(s.lane == "practical" for s in out)

    def test_html_to_text_strips_chrome(self):
        html = "<html><head><style>x{}</style></head><body><nav>menu</nav><main><h1>Hi</h1><p>Body  text</p></main><script>evil()</script></body></html>"
        text = src.html_to_text(html)
        assert "Hi Body text" in text
        assert "menu" not in text and "evil" not in text


def _table(kind="bar", nseries=1, numeric_x=False):
    xs = [1, 2, 3] if numeric_x else ["A", "B", "C"]
    return DataTable(
        title="Accuracy by method", kind=kind, x_label="method", y_label="accuracy", unit="%",
        series=[DataSeries(name=f"s{i}", points=[DataPoint(x=x, y=10.0 * (i + 1) + j) for j, x in enumerate(xs)])
                for i in range(nseries)],
        source_ids=["E1", "A2"],
    )


@pytest.mark.unit
class TestFigures:
    @pytest.mark.parametrize("kind,nseries,numeric", [("bar", 1, False), ("grouped_bar", 2, False), ("line", 2, True), ("line", 1, False)])
    def test_render_png(self, kind, nseries, numeric):
        png = render_png(_table(kind, nseries, numeric), width_px=600, height_px=350, dpi=100)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        assert 5_000 < len(png) < 400_000

    def test_empty_table_raises(self):
        t = DataTable(title="t", series=[DataSeries(name="s", points=[])])
        with pytest.raises(ValueError):
            render_png(t)

    def test_caption_cites_refs(self):
        cap = caption_for(2, _table(), {"E1": 4, "A2": 1, "P9": 7})
        assert cap == "Figure 2: Accuracy by method (%). [1][4]"
