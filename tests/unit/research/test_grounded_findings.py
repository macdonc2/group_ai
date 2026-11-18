"""Research findings are checked against the source they cite before any later model sees them."""

from types import SimpleNamespace

import pytest

from agent_system.adapters.outbound.llm.context import (
    ContextBundle,
    check_reply,
    find_quote,
    normalise_for_match,
    quoted_spans,
)
from agent_system.adapters.outbound.research import lanes
from agent_system.adapters.outbound.research.schemas import FindingsOut
from agent_system.domain.entities.research import Finding, Source

pytestmark = pytest.mark.unit

PAGE = ("ReliabilityBench evaluated two models across four domains and 1,280 episodes. Task success fell from "
        "96.9% at perturbation intensity 0 to 88.1% at 0.2. The authors note that “nominal performance "
        "does not predict performance under stress” — a point they repeat.")
SOURCES = [
    Source(id="A1", lane="academic", title="ReliabilityBench: Evaluating LLM Agent Reliability", snippet=PAGE),
    Source(id="A2", lane="academic", title="TREK: A Travel Reasoning Kit", snippet="TREK includes 267 provably infeasible tasks among 800."),
]


def finding(evidence, source_id="A1", claim="Success drops under perturbation."):
    return Finding(claim=claim, evidence=evidence, source_id=source_id)


# --- the quote check -------------------------------------------------------


def test_a_quote_must_be_in_the_source_word_for_word():
    assert find_quote("Task success fell from 96.9% at perturbation intensity 0 to 88.1% at 0.2", PAGE).found
    # a changed number, a paraphrase and an invention all fail
    assert find_quote("Task success fell from 96.9% at perturbation intensity 0 to 81.8% at 0.2", PAGE).reason == "not_in_source"
    assert find_quote("Success dropped by roughly nine points when tasks were perturbed", PAGE).reason == "not_in_source"
    assert find_quote("The benchmark was validated in production at three companies", PAGE).reason == "not_in_source"


def test_only_typography_spacing_and_case_are_forgiven():
    assert find_quote('"nominal performance does not predict performance under stress" - a point', PAGE).found   # straight quotes, hyphen
    assert find_quote("TASK SUCCESS   fell from\n96.9% at perturbation", PAGE).found
    assert normalise_for_match("“Five‑nines” —  it’s") == '"five-nines" - it\'s'


def test_an_ellipsis_may_skip_words_but_the_parts_must_be_there_in_order():
    ok = find_quote("ReliabilityBench evaluated two models ... and 1,280 episodes", PAGE)
    assert ok.found
    assert ok.segments == 2
    assert find_quote("1,280 episodes ... ReliabilityBench evaluated two models", PAGE).reason == "out_of_order"
    assert find_quote("ReliabilityBench evaluated two models … across nine domains", PAGE).reason == "not_in_source"


def test_a_quote_too_short_to_mean_anything_is_not_accepted():
    assert find_quote("96.9%", PAGE).reason == "too_short"
    assert find_quote("the", PAGE).reason == "too_short"
    assert find_quote("", PAGE).reason == "too_short"


# --- findings --------------------------------------------------------------


def test_findings_are_split_into_supported_and_not():
    kept, rejected = lanes.verify_findings([
        finding("Task success fell from 96.9% at perturbation intensity 0 to 88.1% at 0.2"),
        finding("ReliabilityBench: Evaluating LLM Agent Reliability"),               # the title counts: the model was shown it
        finding("Agents lost about nine points of success under perturbation"),      # a paraphrase
        finding("TREK includes 267 provably infeasible tasks among 800."),           # real quote, wrong source
        finding("TREK includes 267 provably infeasible tasks among 800.", source_id="A2"),
        finding("A quote from a source that was never retrieved", source_id="Z9"),
    ], SOURCES)
    assert [f.evidence[:12] for f in kept] == ["Task success", "ReliabilityB", "TREK include"]
    assert [(r["source_id"], r["reason"]) for r in rejected] == [("A1", "not_in_source"), ("A1", "not_in_source"), ("Z9", "unknown_source")]


class ScriptedAgent:
    """Stands in for the findings model: returns each scripted output in turn and records its prompts."""

    def __init__(self, *outputs):
        self.outputs, self.prompts = list(outputs), []

    async def run(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(output=self.outputs.pop(0))


DEPS = lanes.LaneDeps(api_key="sk-test", strong_model="strong", fast_model="fast")


async def test_unsupported_findings_get_one_correction_and_are_dropped_if_still_wrong(monkeypatch):
    good = finding("Task success fell from 96.9% at perturbation intensity 0 to 88.1% at 0.2")
    paraphrase = finding("Success fell by nine points", claim="Nine-point drop.")
    invented = finding("The benchmark was validated in production", claim="Validated in production.")
    fixed = finding("ReliabilityBench evaluated two models across four domains and 1,280 episodes", claim="Nine-point drop.")
    still_invented = finding("It was validated at three companies in production", claim="Validated in production.")
    agent = ScriptedAgent(FindingsOut(findings=[good, paraphrase, invented], dropped_source_ids=["A2"]),
                          FindingsOut(findings=[fixed, still_invented]))
    monkeypatch.setattr(lanes, "make_agent", lambda *a, **k: agent)
    reports = []

    out = await lanes._findings("How reliable are agents?", "academic", SOURCES, DEPS, report=reports.append)

    assert [f.evidence for f in out.findings] == [good.evidence, fixed.evidence]     # the invention never gets through
    assert out.dropped_source_ids == ["A2"]
    assert reports == [{"proposed": 3, "verified": 1, "rejected": 2, "repaired": 1, "final": 2, "dropped": 1,
                        "dropped_reasons": ["not_in_source"]}]
    assert len(agent.prompts) == 2
    assert "discarded because their evidence is not an exact quote" in agent.prompts[1]
    assert "Success fell by nine points" in agent.prompts[1]
    assert "copied character for character" in agent.prompts[1]


async def test_no_correction_call_is_made_when_everything_checks_out(monkeypatch):
    agent = ScriptedAgent(FindingsOut(findings=[finding("TREK includes 267 provably infeasible tasks among 800.", source_id="A2")]))
    monkeypatch.setattr(lanes, "make_agent", lambda *a, **k: agent)
    out = await lanes._findings("q", "academic", SOURCES, DEPS)
    assert len(out.findings) == 1
    assert len(agent.prompts) == 1


async def test_a_finding_citing_an_unknown_source_is_dropped_without_a_retry(monkeypatch):
    agent = ScriptedAgent(FindingsOut(findings=[finding("Anything at all that looks like a quote", source_id="Z9")]))
    monkeypatch.setattr(lanes, "make_agent", lambda *a, **k: agent)
    reports = []
    out = await lanes._findings("q", "academic", SOURCES, DEPS, report=reports.append)
    assert out.findings == []
    assert len(agent.prompts) == 1
    assert reports[0]["dropped_reasons"] == ["unknown_source"]


# --- quotations in a chat reply --------------------------------------------


def test_quotations_in_a_reply_are_found():
    reply = ('The page says "nominal performance does not predict performance under stress" and calls it "robust".\n\n'
             "> Task success fell from 96.9% at perturbation intensity 0\n> to 88.1% at 0.2.\n\nThat is all.")
    assert quoted_spans(reply) == ["nominal performance does not predict performance under stress",
                                   "Task success fell from 96.9% at perturbation intensity 0 to 88.1% at 0.2."]


def test_a_quotation_the_model_was_never_shown_is_reported():
    bundle = ContextBundle("u")
    bundle.add_web_page("https://bench.example/paper", PAGE)
    reply = ('It reports that "nominal performance does not predict performance under stress", and that '
             '"agents failed in every production deployment the authors studied".')
    check = check_reply(reply, bundle)
    assert check["quotes"] == 2
    assert check["unsupported_quotes"] == ["agents failed in every production deployment the authors studied"]
    # quoting the user back to themselves is fine
    assert check_reply('You asked: "who is playing at the Lantern Room this Saturday?"', bundle,
                       also_allowed="who is playing at the Lantern Room this Saturday?")["unsupported_quotes"] == []
