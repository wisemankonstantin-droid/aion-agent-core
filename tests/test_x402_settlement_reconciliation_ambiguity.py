"""Red-team proof: duplicate qualifying transfer evidence is not a definite failure."""
from types import SimpleNamespace

from app.services import settlement_reconciliation


TX = "0x" + "4" * 64
ASSET = "0x" + "1" * 40
PAY_TO = "0x" + "2" * 40
PAYER = "0x" + "3" * 40
AMOUNT = "1250000"


def _topic_address(address: str) -> str:
    return "0x" + "0" * 24 + address[2:].lower()


def test_multiple_exact_finalized_transfers_remain_ambiguous(monkeypatch):
    row = SimpleNamespace(
        network="eip155:8453",
        transaction_id=TX,
        asset=ASSET,
        pay_to=PAY_TO,
        payer=PAYER,
        atomic_amount=AMOUNT,
    )
    exact_log = {
        "address": ASSET,
        "topics": [
            settlement_reconciliation._TRANSFER_TOPIC,
            _topic_address(PAYER),
            _topic_address(PAY_TO),
        ],
        "data": "0x" + format(int(AMOUNT), "064x"),
        "logIndex": "0x0",
    }
    receipt = {
        "transactionHash": TX,
        "blockNumber": "0x64",
        "blockHash": "0x" + "5" * 64,
        "status": "0x1",
        "logs": [exact_log, {**exact_log, "logIndex": "0x1"}],
    }

    def rpc(url, method, params):
        if method == "eth_chainId":
            return "0x2105", None
        if method == "eth_getTransactionReceipt":
            return receipt, None
        if method == "eth_getBlockByNumber":
            return {"number": "0x70"}, None
        raise AssertionError(method)

    monkeypatch.setattr(settlement_reconciliation, "_rpc", rpc)
    result = settlement_reconciliation._resolve_finalized_chain_evidence(row)
    assert result == {
        "outcome": "unresolved",
        "code": "multiple_exact_transfers_ambiguous",
    }
