"""Buyer-kit tests use only fake HTTP and chain clients; no live payment."""

import hashlib
from types import SimpleNamespace

import pytest

from scripts import first_sat_buyer as buyer


BUYER = "0x1111111111111111111111111111111111111111"
PAYEE = "0x2222222222222222222222222222222222222222"
PURCHASE = "123e4567-e89b-42d3-a456-426614174000"
DIGEST = "sha256:" + "a" * 64
NONCE = "0x" + hashlib.sha256(
    f"aion-direct-base-usdc-eip3009-v1|{PURCHASE}|{DIGEST}".encode("ascii")
).hexdigest()
TX = "0x" + "b" * 64


def offer():
    return {
        "code": "payment_required",
        "payment_method": "direct_base_usdc_eip3009_buyer_broadcast",
        "purchase_id": PURCHASE,
        "prepared_result_digest": DIGEST,
        "expires_at": "2030-01-01T00:20:00+00:00",
        "quote": {"amount": "1.25", "currency": "USDC", "atomic_amount": "1250000", "network": "eip155:8453", "asset": buyer.BASE_USDC, "asset_code": "USDC"},
        "payment_instructions": {
            "payment_method": "direct_base_usdc_eip3009_buyer_broadcast",
            "payment_flow": "upfront", "transfer_method": "eip3009_transferWithAuthorization",
            "network": "eip155:8453", "chain_id": 8453, "asset": buyer.BASE_USDC,
            "asset_code": "USDC", "asset_decimals": 6, "amount": "1250000",
            "quote_amount": "1.25", "quote_currency": "USDC", "pay_to": PAYEE,
            "buyer_pays_gas": True, "aion_broadcasts_transaction": False,
            "facilitator_required": False, "purchase_id": PURCHASE,
            "prepared_result_digest": DIGEST, "expires_at": "2030-01-01T00:20:00+00:00",
            "authorization": {
                "type": "TransferWithAuthorization",
                "domain": {"name": "USD Coin", "version": "2", "chainId": 8453, "verifyingContract": buyer.BASE_USDC},
                "message": {"from": "BUYER_EVM_ADDRESS", "to": PAYEE, "value": "1250000", "validAfter": "1893456000", "validBefore": "1893457200", "nonce": NONCE},
                "contract_call": {"to": buyer.BASE_USDC, "function": "transferWithAuthorization(address,address,uint256,uint256,uint256,bytes32,uint8,bytes32,bytes32)", "selector": "0xe3ee160e", "caller_pays_gas": True},
            },
            "submit_proof_with": {"purchase_id_header": "X-AION-PURCHASE-ID", "transaction_hash_header": "X-AION-PAYMENT-TX"},
        },
    }


def test_valid_offer_binds_purchase_nonce_and_amount():
    checked = buyer.validate_offer(offer(), BUYER, max_usdc="2", now=1893456060)
    assert checked.purchase_id == PURCHASE
    assert checked.amount == 1250000
    assert checked.nonce == NONCE


@pytest.mark.parametrize("path,value", [
    (("payment_instructions", "network"), "eip155:1"),
    (("payment_instructions", "asset"), "0x3333333333333333333333333333333333333333"),
    (("payment_instructions", "amount"), "1250001"),
    (("payment_instructions", "authorization", "message", "to"), "0x3333333333333333333333333333333333333333"),
    (("payment_instructions", "authorization", "message", "nonce"), "0x" + "0" * 64),
    (("payment_instructions", "authorization", "message", "validBefore"), "1893456000"),
    (("payment_instructions", "authorization", "domain", "chainId"), 1),
    (("payment_instructions", "transfer_method"), "other"),
])
def test_rejects_wrong_or_expired_payment_instruction(path, value):
    data = offer()
    cursor = data
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    with pytest.raises(buyer.BuyerError):
        buyer.validate_offer(data, BUYER, max_usdc="2", now=1893456060)


def test_rejects_amount_over_buyer_cap():
    with pytest.raises(buyer.BuyerError):
        buyer.validate_offer(offer(), BUYER, max_usdc="1", now=1893456060)


def test_rejects_expired_or_inconsistent_preparation_timestamp():
    data = offer()
    data["expires_at"] = "2030-01-01T00:00:00+00:00"
    with pytest.raises(buyer.BuyerError):
        buyer.validate_offer(data, BUYER, max_usdc="2", now=1893456060)


class FakeResponse:
    def __init__(self, status, data):
        self.status_code = status
        self._data = data

    def json(self):
        return self._data


class FakeHttp:
    def __init__(self, first, second=None):
        self.first = first
        self.second = second
        self.calls = []

    def post(self, url, json, headers=None):
        self.calls.append((url, json, headers))
        return self.first if len(self.calls) == 1 else self.second


class FakeChain:
    address = BUYER
    chain_id = 8453
    usdc_balance = 2_000_000
    eth_balance = 10**17
    gas_budget = 10**15
    authorization_used = False
    sent = False
    signed = False

    def is_authorization_used(self, checked):
        return self.authorization_used

    def broadcast(self, checked):
        self.signed = True
        self.sent = True
        return TX

    def wait_safe(self, tx, deadline):
        return True


def args(execute=False):
    return SimpleNamespace(url="https://aion.example/commercial/route-intelligence/purchase", need="research", candidate_identifier=None, max_usdc="2", expected_payee=PAYEE, execute=execute, timeout=30)


def test_dry_run_never_signs_broadcasts_or_retries():
    http = FakeHttp(FakeResponse(402, offer()))
    chain = FakeChain()
    result = buyer.run(args(), http, chain, now=1893456060)
    assert result["status"] == "dry_run_validated"
    assert len(http.calls) == 1
    assert not chain.signed and not chain.sent


def test_execute_sends_once_and_retries_identical_purchase_for_result():
    http = FakeHttp(FakeResponse(402, offer()), FakeResponse(200, {"purchase_id": PURCHASE, "state": "entitled", "result": {"route": "value"}, "prepared_result_digest": DIGEST, "payment": {"method": "direct_base_usdc_eip3009_buyer_broadcast", "transaction": TX, "atomic_amount": "1250000", "network": "eip155:8453"}}))
    chain = FakeChain()
    result = buyer.run(args(execute=True), http, chain, now=1893456060)
    assert result == {"purchase_id": PURCHASE, "tx_hash": TX, "amount": "1250000", "recipient": PAYEE, "network": "eip155:8453", "status": "result_released"}
    assert chain.sent
    assert http.calls[1][1] == http.calls[0][1]
    assert http.calls[1][2] == {"X-AION-PURCHASE-ID": PURCHASE, "X-AION-PAYMENT-TX": TX}


def test_insufficient_balance_or_used_nonce_never_broadcasts():
    for attribute, value in (("usdc_balance", 1), ("eth_balance", 1), ("authorization_used", True), ("chain_id", 1)):
        http = FakeHttp(FakeResponse(402, offer()))
        chain = FakeChain()
        setattr(chain, attribute, value)
        with pytest.raises(buyer.BuyerError):
            buyer.run(args(execute=True), http, chain, now=1893456060)
        assert not chain.sent
        assert len(http.calls) == 1


def test_non_402_never_broadcasts():
    chain = FakeChain()
    with pytest.raises(buyer.BuyerError):
        buyer.run(args(execute=True), FakeHttp(FakeResponse(503, {"code": "disabled"})), chain, now=1893456060)
    assert not chain.sent


def test_safe_timeout_does_not_submit_proof_or_broadcast_twice():
    http = FakeHttp(FakeResponse(402, offer()))
    chain = FakeChain()
    chain.wait_safe = lambda tx, deadline: False
    with pytest.raises(buyer.BuyerError) as error:
        buyer.run(args(execute=True), http, chain, now=1893456060)
    assert error.value.tx_hash == TX
    assert len(http.calls) == 1


def test_reverted_receipt_is_definite_failure_not_unknown():
    http = FakeHttp(FakeResponse(402, offer()))
    chain = FakeChain()
    chain.wait_safe = lambda tx, deadline: (_ for _ in ()).throw(buyer.BuyerError("payment_transaction_failed"))
    with pytest.raises(buyer.BuyerError) as error:
        buyer.run(args(execute=True), http, chain, now=1893456060)
    assert error.value.code == "payment_transaction_failed"
    assert error.value.tx_hash == TX
    assert len(http.calls) == 1


def test_gas_budget_read_once_before_balance_and_cap_checks():
    class ChangingGasChain(FakeChain):
        reads = 0

        @property
        def gas_budget(self):
            self.reads += 1
            if self.reads > 1:
                raise AssertionError("gas price was read again")
            return 10**15

    chain = ChangingGasChain()
    buyer.run(args(), FakeHttp(FakeResponse(402, offer())), chain, now=1893456060)
    assert chain.reads == 1


def test_default_purchase_host_also_requires_independent_payee_pin_to_execute():
    options = args(execute=True)
    options.url = buyer.DEFAULT_URL
    options.expected_payee = None
    with pytest.raises(buyer.BuyerError) as error:
        buyer.run(options, FakeHttp(FakeResponse(402, offer())), FakeChain(), now=1893456060)
    assert error.value.code == "expected_payee_required_for_execution"


def test_result_mismatch_is_not_reported_as_success():
    http = FakeHttp(FakeResponse(402, offer()), FakeResponse(200, {"purchase_id": PURCHASE, "state": "entitled", "result": {"route": "value"}, "prepared_result_digest": DIGEST, "payment": {"method": buyer.METHOD, "transaction": "0x" + "c" * 64, "atomic_amount": "1250000", "network": "eip155:8453"}}))
    with pytest.raises(buyer.BuyerError) as error:
        buyer.run(args(execute=True), http, FakeChain(), now=1893456060)
    assert error.value.code == "result_release_unverified"


def test_gas_budget_over_cap_never_broadcasts():
    chain = FakeChain()
    chain.gas_budget = 10**18
    with pytest.raises(buyer.BuyerError):
        buyer.run(args(execute=True), FakeHttp(FakeResponse(402, offer())), chain, now=1893456060)
    assert not chain.sent


@pytest.mark.parametrize("cap", ["NaN", "-1", "0", "0.0000000000000000001", "garbage"])
def test_invalid_gas_cap_never_broadcasts(cap):
    options = args(execute=True)
    options.max_gas_eth = cap
    chain = FakeChain()
    with pytest.raises(buyer.BuyerError) as error:
        buyer.run(options, FakeHttp(FakeResponse(402, offer())), chain, now=1893456060)
    assert error.value.code == "gas_cap_invalid"
    assert not chain.sent


def test_base_gas_budget_includes_op_stack_l1_fee_bound_without_rpc_network():
    class FakeOracleCall:
        def call(self):
            return 123_456

    class FakeOracleFunctions:
        def getL1FeeUpperBound(self, unsigned_tx_bytes):
            assert unsigned_tx_bytes == buyer.L1_FEE_ESTIMATE_TX_BYTES
            return FakeOracleCall()

        def getOperatorFee(self, gas_used):
            assert gas_used == buyer.GAS_LIMIT
            return SimpleNamespace(call=lambda: 654_321)

    chain = object.__new__(buyer.BaseChain)
    chain.w3 = SimpleNamespace(eth=SimpleNamespace(gas_price=1_000_000_000))
    chain.gas_oracle = SimpleNamespace(functions=FakeOracleFunctions())
    assert chain.gas_budget == buyer.GAS_LIMIT * 1_000_000_000 + 123_456 + 654_321


def test_custom_purchase_host_requires_independent_payee_pin_for_execution():
    options = args(execute=True)
    options.expected_payee = None
    chain = FakeChain()
    with pytest.raises(buyer.BuyerError):
        buyer.run(options, FakeHttp(FakeResponse(402, offer())), chain, now=1893456060)
    assert not chain.sent


def test_wrong_independently_pinned_payee_never_broadcasts():
    options = args(execute=True)
    options.expected_payee = "0x3333333333333333333333333333333333333333"
    chain = FakeChain()
    with pytest.raises(buyer.BuyerError):
        buyer.run(options, FakeHttp(FakeResponse(402, offer())), chain, now=1893456060)
    assert not chain.sent


def test_eip712_signature_is_recoverable_only_for_purchase_bound_message():
    from eth_account import Account
    from eth_account.messages import encode_typed_data

    key = "0x" + "1" * 64  # deterministic test key, never funded
    address = Account.from_key(key).address
    checked = buyer.validate_offer(offer(), address, max_usdc="2", now=1893456060)
    v, r, s = buyer.sign_authorization(checked, key)
    types = {"TransferWithAuthorization": [
        {"name": "from", "type": "address"}, {"name": "to", "type": "address"},
        {"name": "value", "type": "uint256"}, {"name": "validAfter", "type": "uint256"},
        {"name": "validBefore", "type": "uint256"}, {"name": "nonce", "type": "bytes32"},
    ]}
    signed_message = encode_typed_data(
        domain_data={"name": "USD Coin", "version": "2", "chainId": 8453, "verifyingContract": buyer.BASE_USDC},
        message_types=types,
        message_data={"from": address, "to": PAYEE, "value": 1250000, "validAfter": 1893456000, "validBefore": 1893457200, "nonce": bytes.fromhex(NONCE[2:])},
    )
    assert Account.recover_message(signed_message, vrs=(v, r, s)) == address


def test_offline_usdc_calldata_uses_server_expected_selector_and_nonce():
    from eth_account import Account

    key = "0x" + "1" * 64
    address = Account.from_key(key).address
    checked = buyer.validate_offer(offer(), address, max_usdc="2", now=1893456060)
    chain = buyer.BaseChain("https://invalid.example", key)
    v, r, s = buyer.sign_authorization(checked, key)
    calldata = chain.contract.encode_abi("transferWithAuthorization", args=[
        address, PAYEE, 1250000, 1893456000, 1893457200,
        bytes.fromhex(NONCE[2:]), v, r.to_bytes(32, "big"), s.to_bytes(32, "big"),
    ])
    assert calldata[:10] == "0xe3ee160e"
    assert calldata[10 + 5 * 64:10 + 6 * 64] == NONCE[2:]
