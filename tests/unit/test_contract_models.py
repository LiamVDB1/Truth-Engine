from datetime import UTC, datetime

from truth_engine.contracts.models import CostRecord, ProblemUnit, RawArena, RawSignal
from truth_engine.domain.enums import AgentName, Stage


def test_raw_arena_fingerprint_is_case_and_whitespace_insensitive() -> None:
    first = RawArena(
        domain=" Logistics Operations ",
        icp_user_role="Warehouse Manager",
        icp_buyer_role="VP Operations",
        geo="EU + US",
        channel_surface=["linkedin"],
        solution_modality="saas",
        market_signals=["hiring growth"],
        signal_sources=["https://example.com/jobs"],
        market_size_signal="500+ job postings",
        expected_sales_cycle="2-4 weeks",
        rationale="Strong hiring signal.",
    )
    second = RawArena(
        domain="logistics operations",
        icp_user_role=" warehouse  manager ",
        icp_buyer_role="VP Operations",
        geo="EU + US",
        channel_surface=["linkedin"],
        solution_modality="saas",
        market_signals=["hiring growth"],
        signal_sources=["https://example.com/jobs"],
        market_size_signal="500+ job postings",
        expected_sales_cycle="2-4 weeks",
        rationale="Strong hiring signal.",
    )

    assert first.fingerprint() == second.fingerprint()


def test_raw_signal_hash_is_derived_when_missing() -> None:
    signal = RawSignal(
        source_type="reddit",
        source_url="https://reddit.com/r/test/comments/abc",
        verbatim_quote="This hurts every week.",
        persona="Ops manager",
        inferred_pain="Manual coordination is painful",
        inferred_frequency="weekly",
        proof_of_spend=False,
        switching_signal=True,
        tags=["coordination"],
        reliability_score=0.4,
    )

    assert signal.source_url_hash


def test_raw_signal_hash_normalizes_equivalent_urls() -> None:
    first = RawSignal(
        source_type="reddit",
        source_url="https://reddit.com/r/test/comments/abc/?utm_source=foo#frag",
        verbatim_quote="This hurts every week.",
        persona="Ops manager",
        inferred_pain="Manual coordination is painful",
        inferred_frequency="weekly",
        proof_of_spend=False,
        switching_signal=True,
        tags=["coordination"],
        reliability_score=0.4,
    )
    second = RawSignal(
        source_type="reddit",
        source_url="https://REDDIT.com/r/test/comments/abc",
        verbatim_quote="This hurts every week.",
        persona="Ops manager",
        inferred_pain="Manual coordination is painful",
        inferred_frequency="weekly",
        proof_of_spend=False,
        switching_signal=True,
        tags=["coordination"],
        reliability_score=0.4,
    )

    assert first.source_url_hash == second.source_url_hash


def test_problem_unit_confidence_is_bounded() -> None:
    problem = ProblemUnit(
        id="pu_123",
        job_to_be_done="Coordinate supplier updates",
        trigger_event="Inbound delivery changes",
        frequency="daily",
        severity=8,
        urgency="Operational disruption",
        cost_of_failure="Missed deliveries",
        current_workaround="Email and spreadsheets",
        proof_of_spend="Ops headcount and paid tooling",
        switching_friction=4,
        buyer_authority="VP Operations",
        evidence_ids=["sig_1", "sig_2"],
        signal_count=2,
        source_diversity=2,
        confidence=0.4,
    )

    assert problem.confidence == 0.4


def test_cost_record_captures_stage_and_agent_identity() -> None:
    record = CostRecord(
        candidate_id="cand_1",
        stage=Stage.ARENA_DISCOVERY,
        agent=AgentName.ARENA_SCOUT,
        model="minimax-M2.5",
        input_tokens=100,
        output_tokens=50,
        tool_calls=2,
        cost_eur=0.03,
        timestamp=datetime(2026, 3, 10, 12, 0, tzinfo=UTC),
    )

    assert record.stage is Stage.ARENA_DISCOVERY
    assert record.agent is AgentName.ARENA_SCOUT
