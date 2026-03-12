from __future__ import annotations

from truth_engine.contracts.live import LiveRunRequest


def test_live_request_defaults_to_system_driven_discovery() -> None:
    request = LiveRunRequest.default()

    assert request.candidate_id.startswith("run_")
    assert request.founder_constraints.v1_filter == "software_first"


def test_live_request_accepts_founder_constraints_only() -> None:
    request = LiveRunRequest.model_validate(
        {
            "founder_constraints": {
                "solution_modalities": ["saas", "api"],
                "geo_preference": "US",
            }
        }
    )

    assert request.founder_constraints.solution_modalities == ["saas", "api"]
    assert request.founder_constraints.geo_preference == "US"
