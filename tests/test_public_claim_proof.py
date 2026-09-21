from app import main as main_module


def test_app_title_has_no_claim_proof_by_default(monkeypatch):
    monkeypatch.delenv("AION_PUBLIC_CLAIM_PROOF", raising=False)
    assert main_module._app_title() == "AION Agent Core"


def test_app_title_exposes_bounded_claim_proof(monkeypatch):
    monkeypatch.setenv(
        "AION_PUBLIC_CLAIM_PROOF",
        "claim-7d1b00364da85f3b",
    )
    assert (
        main_module._app_title()
        == "AION Agent Core [claim-7d1b00364da85f3b]"
    )


def test_app_title_ignores_invalid_claim_proof(monkeypatch):
    monkeypatch.setenv("AION_PUBLIC_CLAIM_PROOF", "claim with spaces")
    assert main_module._app_title() == "AION Agent Core"

    monkeypatch.setenv("AION_PUBLIC_CLAIM_PROOF", "x" * 129)
    assert main_module._app_title() == "AION Agent Core"
