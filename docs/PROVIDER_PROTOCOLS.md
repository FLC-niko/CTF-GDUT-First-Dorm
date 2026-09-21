# Provider protocol evidence

This file records time-sensitive routing facts used by the adapters. Model IDs
are examples from the provider directory, not permanent defaults or benchmarked
Fast/Expert/Racing assignments.

## OpenCode Go (checked 2026-09-21)

Source: <https://opencode.ai/docs/go/>

- Subscription price shown by the official page: USD 10/month.
- Published windows: 5-hour usage up to 20% of the monthly allowance, weekly up
  to 50%, monthly up to 100%.
- If the account enables **Use balance**, requests after the subscription limit
  may consume Zen balance. This repository cannot change that account-side
  switch and keeps cross-provider paid fallback disabled by default.
- All conversations require a stable `x-opencode-session`; different solver
  runs must not share a session. Requests use `User-Agent: ctf-agent/0.1`.

| Explicit alias | Client protocol | HTTP endpoint |
|---|---|---|
| `go-responses` | OpenAI Responses | `https://opencode.ai/zen/go/v1/responses` |
| `go-chat` | OpenAI Chat Completions | `https://opencode.ai/zen/go/v1/chat/completions` |
| `go-messages` | Anthropic Messages | `https://opencode.ai/zen/go/v1/messages` |
| discovery | Models | `https://opencode.ai/zen/go/v1/models` |

The Anthropic SDK appends `/v1/messages`, so its configured client base is
`https://opencode.ai/zen/go`; the final wire endpoint remains the one above.

Examples shown by the official page on the check date:

- Responses: `grok-4.6`, `gpt-5.6-luna`,
  `muse-spark-1.3-contributor`, `muse-spark-1.2-contributor`.
- Chat Completions: `glm-5.3-flash`, `glm-5.3`, `kimi-k3`,
  `kimi-k2.7-code`, `deepseek-v4.1-flash`, `deepseek-v4-pro`,
  `deepseek-v4-flash`, `mimo-v2.5`, `hy4-preview`.
- Anthropic Messages: `minimax-m3`, `minimax-m2.7`, `qwen3.8-max`,
  `qwen3.8-flash`, `qwen3.7-plus`.

Do not select a protocol by matching these names. Use the explicit alias and
refresh `/models` before a real benchmark. Contributor models are not enabled
by default because the official page says their data may be used for training.
The page listed 30-day retention for Grok/GPT Luna and zero-day retention for
most other models; recheck this before sending competition material.

## CPA

CPA deployment URLs and enabled model IDs are operator-controlled. The runtime
therefore has separate `cpa-responses` and `cpa-chat` aliases and requires an
explicit base URL and key. A successful `/models` request is not proof that a
model supports tools, streaming, or the selected protocol; those are separate
smoke gates.
