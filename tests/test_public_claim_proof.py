import pytest

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


def test_allagents_claim_proof_file_returns_exact_nonce(monkeypatch):
    monkeypatch.setenv(
        "AION_PUBLIC_CLAIM_PROOF",
        "claim-reissue-0123456789abcdef",
    )
    response = main_module.allagents_claim_proof()
    assert response.status_code == 200
    assert response.body == b"claim-reissue-0123456789abcdef"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.headers["cache-control"] == "no-store"


def test_allagents_claim_proof_file_is_absent_when_unconfigured(monkeypatch):
    monkeypatch.delenv("AION_PUBLIC_CLAIM_PROOF", raising=False)
    with pytest.raises(main_module.HTTPException) as exc:
        main_module.allagents_claim_proof()
    assert exc.value.status_code == 404


def test_allagents_claim_proof_file_rejects_invalid_value(monkeypatch):
    monkeypatch.setenv("AION_PUBLIC_CLAIM_PROOF", "claim proof with spaces")
    with pytest.raises(main_module.HTTPException) as exc:
        main_module.allagents_claim_proof()
    assert exc.value.status_code == 404
