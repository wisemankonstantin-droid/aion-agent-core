# First SAT buyer CLI

This standalone buyer-side example uses the existing direct Base USDC EIP-3009 purchase endpoint. It needs no AION membership. It does not fund a wallet, change AION payment configuration, or make AION pay gas.

Install buyer-only dependencies in your own Python 3.12 environment:

```sh
python -m pip install -r scripts/requirements-first-sat-buyer.txt
```

Set `AION_BUYER_PRIVATE_KEY` **only in a local environment variable**, ideally from your secret manager. Never put it in a command argument, source file, shell history, CI variable, or shared log. Set `AION_BUYER_BASE_RPC_URL` for your trusted HTTPS Base mainnet RPC, or pass `--rpc-url`; the default is `https://mainnet.base.org`. The buyer wallet must already hold native Base USDC and enough Base ETH for gas. No AION credit or wallet funding occurs.

Dry run (default; no signing or broadcast):

```sh
python scripts/first_sat_buyer.py --need "public bounded routing need" --max-usdc 2
```

Execute one real transaction only with an explicit flag:

```sh
python scripts/first_sat_buyer.py --need "public bounded routing need" --max-usdc 2 --max-gas-eth 0.005 --expected-payee 0xYOUR_INDEPENDENTLY_VERIFIED_AION_RECIPIENT --execute
```

Optional `--candidate-identifier` chooses a public Registry package; optional `--url` overrides the production purchase URL. For **every** real execution, `--expected-payee 0x...` is mandatory: obtain the actual address through an independent trusted channel, not from the same 402 response. Never copy the example placeholder into a real command. Need text is public, at most 128 characters, and must never contain secrets. `--max-usdc` is the hard buyer amount ceiling; `--max-gas-eth` caps the pre-broadcast gas estimate, including Base's L1 data-fee upper-bound estimate and operator fee. Network fees can move before inclusion, so this estimate is not a guaranteed exact charged-fee cap. The command checks Base chain ID, native USDC address, amount and quote agreement, recipient, purchase-bound nonce, EIP-712 domain and authorization window, balances, and nonce-replay state before signing. It waits at most `--timeout` seconds (default 180, maximum 600), then submits the exact same purchase request once with the proof headers. It requires AION's HTTP 200 entitlement and matching purchase, transaction, amount, and result digest before reporting `result_released`.

The default dry run **does POST the purchase endpoint** and may create a prepared, unpaid production purchase row. It makes no money-moving transaction. CI/tests use mocks and must never target production. Both modes print one compact JSON object with safe payment metadata or a fixed error code; no key, seed, signature, raw transaction, or result body is logged. If broadcast or result release becomes ambiguous, the error includes the purchase ID and, if available, transaction hash for manual inspection; **do not rerun `--execute` blindly**. This example does not automatically rebroadcast or create another payment attempt.
