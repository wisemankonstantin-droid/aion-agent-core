# Ruflo execution guard (AION FIRST SAT)

Scope: every Ruflo agent invocation and orchestration task. This is an **invocation-time contract**, not evidence that Ruflo server globally enforces a policy. Agent configs were tagged with matching policy on 2026-10-08. The caller MUST enforce these rules even if config is ignored.

- At most **2 concurrent heavy LLM requests** (3 only where independent measured provider headroom permits). Keep a queue for excess work.
- Specialist FINAL OUTPUT: **at most 150 Russian words**. Exactly these concise fields: `ACTION`, `ERROR`, `CHANGE`, `TEST`, `BLOCKER`. Omit empty fields. Orchestrator owner report **at most 300 words**.
- Reserve enough generation tokens (recommended `maxTokens: 1800`, within available provider quota) for reasoning and valid short output; enforce output length **after** generation, not by starving the model. Do not request hidden reasoning or print it. Save technical evidence and detailed logs to task results, scoped repository files, PR comments or verified CI artifacts.
- Inspect `success`, `stopReason`, `messageId`, `usage.inputTokens`, `usage.outputTokens` and text length. `stopReason=length` means **INCOMPLETE**, never completed. Continue from the exact unfinished boundary with previous output, request only missing final content, dedupe text. If the output is empty, ask for a complete bounded report of the already completed work rather than claiming success.
- On 429: respect `Retry-After` where supplied; otherwise bounded exponential backoff with jitter and a queue. Only route to a compatible configured fallback model that preserves safety/quality, never silently increase spend or provider quotas. Avoid bulk retry storms.
- Before a tool call, check the scoped token/request budget; log provider/model/usage and known USD rate. If prices are unavailable, record tokens and mark cost unknown, not zero.
- Orchestrator receives **compact structured result summaries and evidence IDs**, not full agent dialogues. No repeated architecture audits without changed evidence.
- The only commercial objective before first SAT is external need -> qualified preflight/route -> legitimate external payer -> verified settlement/entitlement. Nominal AION-operated workers and AION self-pay are not buyers or proof.

Critical checks run in the repository/CI, but tools, connector permissions and actual provider limits remain authoritative. An agent config update is not a substitute for controlling the invocation scheduler.
