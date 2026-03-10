from __future__ import annotations

import json
from pathlib import Path

from truth_engine.contracts.stages import CandidateDossier


def render_dossier_markdown(dossier: CandidateDossier) -> str:
    sections = [
        f"# Candidate Dossier: {dossier.candidate_id}",
        f"*Generated: {dossier.generated_at.strftime('%Y-%m-%d %H:%M UTC')}*",
    ]

    # ── Arena ─────────────────────────────────────────
    sections.extend(
        [
            "",
            "## Arena",
            f"**Domain:** {dossier.arena.arena.domain}",
            f"**ICP User:** {dossier.arena.arena.icp_user_role}",
            f"**ICP Buyer:** {dossier.arena.arena.icp_buyer_role}",
            f"**Geo:** {dossier.arena.arena.geo}",
            f"**Arena Score:** {dossier.arena.score}/100 — {dossier.arena.viability_verdict}",
            "",
            dossier.arena.arena.rationale,
        ]
    )

    # ── Problem Unit ──────────────────────────────────
    sections.extend(
        [
            "",
            "## Problem Unit",
            dossier.problem_unit.job_to_be_done,
        ]
    )

    # ── Top Evidence ──────────────────────────────────
    evidence_lines = "\n".join(
        f'- *"{signal.verbatim_quote}"* — [{signal.source_type}]({signal.source_url})'
        for signal in dossier.top_evidence
    )
    sections.extend(
        [
            "",
            "## Top Evidence",
            evidence_lines or "- No evidence collected.",
        ]
    )

    # ── Scoring Breakdown ─────────────────────────────
    sections.extend(
        [
            "",
            "## Scoring",
            f"**Total Score:** {dossier.scoring.total_score}/100 "
            f"(confidence: {dossier.scoring.confidence:.0%})",
            "",
            dossier.scoring.confidence_rationale,
            "",
            "| Dimension | Score | Evidence | Rationale |",
            "|-----------|-------|----------|-----------|",
        ]
    )
    for dim_name, dim_score in dossier.scoring.dimension_scores.items():
        evidence = dossier.scoring.dimension_evidence.get(dim_name, "—")
        rationale = dossier.scoring.dimension_rationale.get(dim_name, "—")
        # Truncate for readability
        evidence_short = evidence[:80] + "…" if len(evidence) > 80 else evidence
        rationale_short = rationale[:80] + "…" if len(rationale) > 80 else rationale
        sections.append(f"| {dim_name} | {dim_score}/10 | {evidence_short} | {rationale_short} |")

    if dossier.scoring.weakest_dimensions:
        sections.extend(
            [
                "",
                f"**Weakest dimensions:** {', '.join(dossier.scoring.weakest_dimensions)}",
            ]
        )

    # ── Skeptic Assessment ────────────────────────────
    sections.extend(
        [
            "",
            "## Skeptic Assessment",
            f"**Evidence Integrity:** {dossier.skeptic.evidence_integrity}",
            f"**Recommendation:** {dossier.skeptic.recommendation}",
            f"**Primary Weakness:** {dossier.skeptic.primary_weakness}",
            "",
            "**Risk Flags:**",
        ]
    )
    if dossier.skeptic.risk_flags:
        for flag in dossier.skeptic.risk_flags:
            sections.append(f"- {flag}")
    else:
        sections.append("- None identified")

    # ── Selected Wedge ────────────────────────────────
    sections.extend(
        [
            "",
            "## Selected Wedge",
            f"**Promise:** {dossier.selected_wedge.wedge_promise}",
            f"**Key Capability:** {dossier.selected_wedge.key_capability}",
        ]
    )

    # ── Buyer and Channel Map ─────────────────────────
    sections.extend(
        [
            "",
            "## Buyer and Channel Map",
            f"**User Role:** {dossier.channel_validation.user_role}",
            f"**Buyer Role:** {dossier.channel_validation.buyer_role}",
            f"**Buyer is User:** {'Yes' if dossier.channel_validation.buyer_is_user else 'No'}",
            f"**Blockers:** {', '.join(dossier.channel_validation.blocker_roles) or 'None'}",
            f"**Procurement Notes:** {dossier.channel_validation.procurement_notes}",
            f"**Total Reachable Leads:** {dossier.channel_validation.total_reachable_leads}",
            f"**Est. Cost/Conversation:** "
            f"€{dossier.channel_validation.estimated_cost_per_conversation:.2f}",
            f"**Verdict:** {dossier.channel_validation.verdict.value}"
            f" — {dossier.channel_validation.verdict_rationale}",
        ]
    )

    # ── First 20 Conversations ────────────────────────
    sections.extend(["", "## First 20 Conversations"])
    for plan in dossier.channel_validation.channels:
        sections.extend(
            [
                "",
                f"### {plan.channel}",
                f"- **Message Angle:** {plan.message_angle}",
                f"- **Volume:** {plan.volume_estimate} leads",
                f"- **How to Reach:** {plan.how_to_reach}",
                f"- **Lead Source:** {plan.lead_source}",
                f"- **First 20 Plan:** {plan.first_20_plan}",
            ]
        )

    # ── Caution Flags ─────────────────────────────────
    if dossier.caution_flags:
        sections.extend(["", "## ⚠️ Caution Flags"])
        for flag in dossier.caution_flags:
            sections.append(f"- {flag}")

    # ── Gate History ──────────────────────────────────
    sections.extend(["", "## Gate History"])
    for event in dossier.gate_history:
        action_val = event.action.value
        if action_val == "advance":
            icon = "✓"
        elif action_val == "kill":
            icon = "✗"
        else:
            icon = "↻"
        sections.append(f"- {icon} **{event.stage.value}** → {event.action.value}: {event.reason}")

    # ── Cost Summary ──────────────────────────────────
    cost_breakdown = getattr(dossier, "cost_breakdown", {})
    total_cost = getattr(dossier, "total_cost_eur", 0.0)
    if cost_breakdown or total_cost > 0:
        sections.extend(
            [
                "",
                "## Cost Summary",
                "",
                "| Stage | Cost (EUR) |",
                "|-------|-----------|",
            ]
        )
        for stage_name, stage_cost in cost_breakdown.items():
            sections.append(f"| {stage_name} | €{stage_cost:.4f} |")
        sections.append(f"| **Total** | **€{total_cost:.4f}** |")

    sections.append("")
    return "\n".join(sections)


def write_dossier_artifacts(dossier: CandidateDossier, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{dossier.candidate_id}.json"
    markdown_path = output_dir / f"{dossier.candidate_id}.md"
    json_path.write_text(json.dumps(dossier.model_dump(mode="json"), indent=2), encoding="utf-8")
    markdown_path.write_text(render_dossier_markdown(dossier), encoding="utf-8")
    return json_path, markdown_path
