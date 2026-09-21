# CTF Benchmark Performance Report

> Generated at: 2026-09-21 16:41:09

## 1. Summary by Model & Mode

| Model & Mode | Total | Solved | Solve Rate | Avg Time-to-Flag (s) | Tool Accuracy | Total Tokens |
|--------------|-------|--------|------------|----------------------|---------------|--------------|
| `codex/gpt-5.4-mini [fast]` | 5 | 2 | 40.0% | 18.75s | 73.0% | 12550 |
| `codex/gpt-5.4 [expert]` | 3 | 2 | 66.7% | 46.4s | 88.9% | 18100 |
| `go-messages/deepseek-r1 [racing]` | 1 | 1 | 100.0% | 74.5s | 100.0% | 6400 |

**Marginal Racing Coverage Benefit**: 33.3%

## 2. Recommended Solver Role Matrix

- **Fast Solver (Warmup/初筛)**: Lightweight small models (`codex/gpt-5.4-mini` / `go-chat/qwen-2.5-coder-7b`), prioritizing low token usage and high tool invocation speed.
- **Expert Solver (Deep Reasoning/攻坚)**: Strong reasoning models (`codex/gpt-5.4` / `go-messages/deepseek-r1`), handling complex multi-step exploits.
- **Racing Solver (Cross-Family/瓶颈突破)**: Combining different model families (`Codex GPT` + `CPA Gemini` + `Go DeepSeek`), exploring orthogonal attack vectors when Expert stalls.

## 3. Individual Challenge Results

| Challenge | Category | Model | Mode | Solved | Time (s) | Tool Acc |
|-----------|----------|-------|------|--------|----------|----------|
| web_jwt_bypass | web | `codex/gpt-5.4-mini` | fast | ✅ | 22.4s | 100.0% |
| misc_stego_flag | misc | `codex/gpt-5.4-mini` | fast | ✅ | 15.1s | 100.0% |
| crypto_affine | crypto | `codex/gpt-5.4-mini` | fast | ❌ | 60.0s | 50.0% |
| pwn_ret2text | pwn | `codex/gpt-5.4-mini` | fast | ❌ | 90.0s | 40.0% |
| rev_xor_check | reverse | `codex/gpt-5.4-mini` | fast | ❌ | 75.0s | 75.0% |
| crypto_affine | crypto | `codex/gpt-5.4` | expert | ✅ | 38.6s | 100.0% |
| rev_xor_check | reverse | `codex/gpt-5.4` | expert | ✅ | 54.2s | 100.0% |
| pwn_ret2text | pwn | `codex/gpt-5.4` | expert | ❌ | 180.0s | 66.7% |
| pwn_ret2text | pwn | `go-messages/deepseek-r1` | racing | ✅ | 74.5s | 100.0% |