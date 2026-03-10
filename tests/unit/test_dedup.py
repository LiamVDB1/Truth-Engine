from truth_engine.services.dedup import arena_fingerprint


def test_arena_fingerprint_normalizes_case_spacing_and_punctuation() -> None:
    first = arena_fingerprint("Logistics  Operations", "Warehouse Manager")
    second = arena_fingerprint(" logistics operations ", "warehouse-manager")

    assert first == second
