# Permanent project directive

AION must become a production-ready, agent-native ecosystem. An independent external agent must be able to discover AION, connect, obtain utility, interact and return.

The primary product loop is:

discovery -> Agent Card -> identify/register -> capabilities -> needs/offers -> match -> useful result -> interaction -> reputation/history -> return

The first milestone is **10 independent external agents that performed a useful action and later returned**. Registrations, traffic, synthetic agents and operator-controlled identities do not satisfy this milestone.

- GitHub is the source of truth; direct tracked source is authoritative.
- A2A-first: A2A is the main agent-to-agent communication layer.
- MCP remains a separate integration/tool layer.
- Matching capabilities, needs and offers is the killer feature of the current phase.
- An external URL is only a candidate until the agent and its behavior are verified.
- Identity and deduplication are mandatory; count product metrics by unique external agents.
- Monetize useful actions, not registration alone. Payment intents are not settled payments.
- Security, reliability and testing are mandatory.
- Do not scale growth until activation and return are demonstrated.
- Never fabricate metrics or describe synthetic/test agents as real adoption.
- Apply red-team review to major decisions: challenge assumptions, abuse paths, failure modes and evidence.
- A 10/10 goal means eliminating real weaknesses, not inflating a score.
- Execute by priority: BLOCKER -> CRITICAL -> HIGH -> MEDIUM -> LOW.

## Continuous execution

If a next useful action is within Codex's authorized scope and can be performed independently, execute it without waiting for “continue”. Stop only at a genuine USER BLOCKER: login, CAPTCHA, 2FA, payment, required permission, or an action physically requiring the user. Code, deployment, test, dependency and architecture failures are engineering work, not USER BLOCKERs. Continue unaffected work while a user-dependent action is pending. This directive does not authorize unsolicited outreach or bypass platform permissions.

## Critical path

audit -> normalize GitHub -> reproducible deployment -> identity/deduplication -> A2A conformance -> core product loop -> matching -> external-agent validation -> metrics/retention -> security/reliability/testing -> machine payments -> 10 retained external agents -> growth
