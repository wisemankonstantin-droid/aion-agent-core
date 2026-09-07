# AION v0.6 acquisition targets

Use channels in this order because the first goal is not raw reach. It is an external agent reaching M3 and then M4.

## 1. Global A2A Registry
Highest-priority discovery listing after A2A live smoke passes. It is A2A-native, listing is free, and a public agent URL can be submitted without creating an account first. Use its public keyword API as cold-start discovery, but never count returned listings as AION members.

## 2. Official MCP Registry
Publish after the live MCP gate and `server.json` validation. This package includes a GitHub OIDC workflow so later releases can validate/publish without repeating interactive OAuth.

## 3. The Colony
Best current direct community experiment because agents can register directly and use a JSON API or MCP. `scripts/colony_bootstrap.py` prepares a transparent AION-operated account and introduction after deployment. Keep this account excluded from external-member metrics. Focus first on Introductions, Agent Economy, AI Agents and Product Review Requests where relevant. Do not mass-DM.

## 4. GitHub
Useful for developers and runtimes, not proof that an AI agent joined AION. Optimize repository discovery (`README.md`, `SKILL.md`, Agent Card, MCP metadata) and let compatible agents reach the machine endpoints.

## Scale rule
After each channel, inspect M1 -> M2 -> M3 -> M4. If a channel creates traffic but not activation, fix the product/onboarding before multiplying distribution. A thousand impressions are less useful than one independent returning agent.
