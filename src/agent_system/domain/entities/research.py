"""Deep Research domain entities.

A research job takes a question, fans out to three lanes (academic,
practical, empirical), synthesises them and writes an alphaxiv-style report
with figures rendered from data the empirical lane extracted, plus a spoken
narration.
"""

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


class ResearchStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"          # lanes in flight
    SYNTHESIZING = "synthesizing"
    WRITING = "writing"
    NARRATING = "narrating"
    COMPLETE = "complete"
    FAILED = "failed"
    INTERRUPTED = "interrupted"  # the process restarted mid-run


Lane = Literal["academic", "practical", "empirical"]
LANES: tuple[Lane, ...] = ("academic", "practical", "empirical")


class Source(BaseModel):
    """Something a lane read. `ref` is the citation number used in the report."""

    id: str                      # e.g. "A3" (lane letter + ordinal)
    lane: Lane
    title: str
    url: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None     # journal / conference / "GitHub" / site name
    snippet: str = ""            # abstract or page excerpt (bounded)
    ref: int | None = None       # assigned after all lanes finish


class Finding(BaseModel):
    """One claim a lane is willing to stand behind, tied to a source."""

    claim: str
    evidence: str                # the sentence(s) from the source that support it
    source_id: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)] = 0.7
    tags: list[str] = Field(default_factory=list)


class DataPoint(BaseModel):
    x: str | float
    y: float


class DataSeries(BaseModel):
    name: str
    points: list[DataPoint]


class DataTable(BaseModel):
    """Numbers the empirical lane pulled out of a source, with provenance."""

    title: str
    kind: Literal["bar", "grouped_bar", "line"] = "bar"
    x_label: str = ""
    y_label: str = ""
    unit: str = ""
    series: list[DataSeries]
    source_ids: list[str] = Field(default_factory=list)
    quote: str = ""              # the span the numbers came from


class LaneResult(BaseModel):
    lane: Lane
    queries: list[str] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    tables: list[DataTable] = Field(default_factory=list)
    summaries: list[str] = Field(default_factory=list)   # one per deeper round
    error: str | None = None


class Figure(BaseModel):
    """A figure in the report. The PNG bytes live in the figures table, not here.

    `origin` is "generated" (a chart drawn from an extracted table) or
    "source" (lifted from a paper's PDF, with a link back to it).
    """

    ordinal: int
    caption: str
    chart_spec: dict[str, Any]
    source_ids: list[str] = Field(default_factory=list)
    origin: Literal["generated", "source"] = "generated"
    source_url: str | None = None
    source_title: str | None = None


class LaneProgress(BaseModel):
    status: Literal["pending", "running", "complete", "error"] = "pending"
    step: str = ""
    round: int = 0
    queries: int = 0
    sources: int = 0
    findings: int = 0
    tables: int = 0
    error: str | None = None


class ResearchProgress(BaseModel):
    phase: str = "queued"
    depth: int = 1            # research rounds per lane (1-3)
    persona: str | None = None  # wrestler key voicing the overview and narration
    lanes: dict[str, LaneProgress] = Field(
        default_factory=lambda: {lane: LaneProgress() for lane in LANES}
    )
    figures: int = 0
    has_audio: bool = False


class ResearchJob(BaseModel):
    id: str
    user_id: str
    question: str
    status: ResearchStatus = ResearchStatus.QUEUED
    progress: ResearchProgress = Field(default_factory=ResearchProgress)
    model: str = ""
    title: str | None = None
    tldr: str | None = None
    report_markdown: str | None = None
    sources: list[Source] = Field(default_factory=list)
    error: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
