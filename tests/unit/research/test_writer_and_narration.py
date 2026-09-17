"""Markdown finalisation, narration script and TTS chunking."""

import pytest

from agent_system.adapters.outbound.research.narration import chunk_text
from agent_system.adapters.outbound.research.writer import (
    finalize_markdown,
    narration_script,
    number_sources,
)
from agent_system.domain.entities.research import (
    DataPoint, DataSeries, DataTable, Figure, Finding, LaneResult, Source,
)


def _fig(n):
    return Figure(ordinal=n, caption=f"Figure {n}: Something ({n}).", chart_spec={}, source_ids=[])


def _sources():
    return [
        Source(id="A1", lane="academic", title="Paper A", authors=["Ann", "Bob", "Cy", "Di"], year=2024, venue="arXiv", url="https://arxiv.org/abs/1", ref=1),
        Source(id="P1", lane="practical", title="Lib P", venue="GitHub", ref=2),
    ]


@pytest.mark.unit
class TestFinalize:
    def test_every_figure_exactly_once_and_references_appended(self):
        body = (
            "# T\n\n**TL;DR** x\n\n## What the Numbers Show\n\n![Figure 1](figure:1)\n\ntext\n\n"
            "![Figure 1](figure:1)\n\n## Synthesis: Where the Lanes Agree and Disagree\n\nmore [1]\n"
        )
        md = finalize_markdown(body, [_fig(1), _fig(2)], _sources())
        assert md.count("(figure:1)") == 1
        assert md.count("(figure:2)") == 1
        # the missing figure lands before the Synthesis section
        assert md.index("(figure:2)") < md.index("## Synthesis")
        assert "## References" in md
        assert "1. **Paper A** (Ann, Bob, Cy et al. · 2024 · arXiv) — https://arxiv.org/abs/1" in md
        assert "2. **Lib P** (GitHub)" in md

    def test_missing_figure_without_synthesis_section_goes_to_end(self):
        md = finalize_markdown("# T\n\nbody", [_fig(1)], [])
        assert md.index("(figure:1)") < md.index("## References")

    def test_number_sources_only_cited(self):
        a = Source(id="A1", lane="academic", title="cited")
        b = Source(id="A2", lane="academic", title="uncited")
        p = Source(id="P1", lane="practical", title="table-cited")
        results = {
            "academic": LaneResult(lane="academic", sources=[a, b], findings=[Finding(claim="c", evidence="e", source_id="A1")]),
            "practical": LaneResult(lane="practical", sources=[p], tables=[DataTable(title="t", series=[DataSeries(name="s", points=[DataPoint(x="a", y=1)])], source_ids=["P1"])]),
            "empirical": LaneResult(lane="empirical"),
        }
        numbered, refs = number_sources(results)
        assert [s.id for s in numbered] == ["A1", "P1"]
        assert refs == {"A1": 1, "P1": 2}
        assert numbered[1].ref == 2


@pytest.mark.unit
class TestNarration:
    def test_script_is_plain_and_reads_captions(self):
        md = (
            "# Title\n\n**TL;DR** Short.\n\n## Section\n\nA claim [3] with *emphasis* and `code` and $x^2$ "
            "and a [link](https://x).\n\n![Figure 1](figure:1)\n\n## References\n\n1. **Paper**\n"
        )
        script = narration_script(md, [_fig(1)])
        assert script.startswith("Title")
        assert "Too long, didn't read." in script
        assert "Figure 1: Something (1)." in script
        assert "[3]" not in script and "*" not in script and "`" not in script and "$" not in script
        assert "link" in script and "https://x" not in script
        assert "References" not in script and "Paper" not in script

    def test_chunking_respects_limit_and_boundaries(self):
        para = "This is a sentence. " * 30  # ~600 chars
        text = "\n\n".join([para] * 10)
        chunks = chunk_text(text, limit=1500)
        assert all(len(c) <= 1500 for c in chunks)
        assert "".join(chunks).count("sentence") == text.count("sentence")
        assert all(c.rstrip().endswith(".") for c in chunks)

    def test_oversized_paragraph_splits_on_sentences(self):
        text = "Word word word. " * 400  # single 6400-char paragraph
        chunks = chunk_text(text, limit=1000)
        assert len(chunks) >= 7 and all(len(c) <= 1000 for c in chunks)
