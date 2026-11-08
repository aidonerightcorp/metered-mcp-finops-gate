# `metered-mcp-finops-gate` — Universal x402 / Prepaid / Order-Capture MCP Gate & LLM FinOps Savings Engine

`metered-mcp-finops-gate` provides three zero-dependency (**100% Python stdlib + SQLite WAL**) monetization and agentic-commerce primitives governed by a declarative `NodeGrid` + `GridLedger` (`commerce_finops_grid.json`):

1. **Multi-Rail Metered MCP & HTTP `402 Payment Required` Gate (`MeteredCommerceAndFinOpsStore`)**
   - Issues HMAC-SHA256 signed `x402-v1` payment challenges (`http_status: 402`) and settles tool calls atomically (`BEGIN IMMEDIATE`) across **x402 USDC receipts**, **prepaid Polar/Stripe/Apify usage balances**, and **order-capture commerce flows** (such as PayPal Sandbox / escrow agentic checkout).
   - Enforces one-time `challenge_id` redemption and unique `tx_ref` anti-replay protection (`duplicate_or_empty_tx_ref`).
2. **Counterfactual LLM FinOps Proxy & Savings-Share Ledger**
   - Combines **distinct-checker (`maker_id != checker_id`) verified artifact caching** (`0` actual tokens on contract-matched cache hits) with **sub-millisecond local reasoning-effort calibration** (`"How are you?" -> minimal`, JSON schema proofs -> `high` + `structured_output_token_floor`).
   - Computes exact counterfactual `saved_microusd = baseline_microusd - actual_microusd` and `platform_fee_microusd` (`savings_fee_basis_points`), supporting zero-risk performance-based B2B billing.
3. **Deterministic Productized Video Storyboard Compiler (`ArtifactStoryboardCompiler`)**
   - Compiles structured repository/capability briefs directly into `explainroo`-ready `video.json` and `script.md` bundles for `$0`-API-cost 1080p launch videos.

## Quickstart

```bash
# Serve as a JSON-RPC 2.0 Stdio MCP server:
python3 metered_gate_engine.py --db ./.metered_gate.sqlite3 --mcp-stdio

# Inspect live settled tool revenue and FinOps savings ledger:
python3 metered_gate_engine.py --db ./.metered_gate.sqlite3 --summary
```

## License

MIT (`aidonerightcorp`)
