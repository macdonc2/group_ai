"""Structured outputs the lanes, synthesis and writer ask the model for."""

from typing import Annotated

from pydantic import BaseModel, Field

from agent_system.domain.entities.research import DataTable, Finding


class QueryPlan(BaseModel):
    queries: Annotated[list[str], Field(min_length=1, max_length=6)]
    rationale: str = ""


class GapPlan(BaseModel):
    summary: Annotated[str, Field(description="What this lane has established so far, 5-8 sentences")]
    gaps: list[str] = Field(default_factory=list, description="Unanswered sub-questions, conflicts, single-source claims")
    queries: Annotated[list[str], Field(max_length=6)] = Field(default_factory=list)


class FindingsOut(BaseModel):
    findings: list[Finding]
    dropped_source_ids: list[str] = Field(
        default_factory=list, description="Sources judged irrelevant or too thin to cite"
    )


class TablesOut(BaseModel):
    tables: list[DataTable]
    notes: str = ""


class SectionPlan(BaseModel):
    heading: str
    key_points: list[str]
    source_ids: list[str] = Field(default_factory=list)
    figure_ordinals: list[int] = Field(default_factory=list)


class Synthesis(BaseModel):
    title: str
    tldr: Annotated[str, Field(description="3-5 sentences a busy reader can stop after")]
    agreements: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    sections: list[SectionPlan]
    figures_to_use: list[int] = Field(
        default_factory=list, description="Ordinals of the extracted tables worth charting, best first"
    )
