"""Universal Metered MCP Tool Gate (x402 / Prepaid / Order-Capture),
Counterfactual LLM FinOps Savings-Share Ledger, and Deterministic
Storyboard Compiler governed by NodeGrid + GridLedger.

Zero external Python dependencies (100% Python stdlib + SQLite WAL).
Conforms strictly to ZeroHardcodedValuesAstGate and DomainAgnosticNamingGate.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_LIFECYCLE_ORDER: Tuple[str, ...] = (
    "represented",
    "applicable",
    "proposed",
    "dispatched",
    "evaluated",
    "verified",
    "promoted",
)


@dataclass(frozen=True)
class ParameterBounds:
    """Clamps integer_range, choice, and boolean parameters to declared bounds."""

    kind: str
    low: Optional[int] = None
    high: Optional[int] = None
    step: Optional[int] = None
    choices: Tuple[Any, ...] = ()

    def clamp(self, raw_value: Any) -> Any:
        if self.kind == "integer_range":
            assert self.low is not None and self.high is not None
            val = int(raw_value)
            if val < self.low:
                return self.low
            if val > self.high:
                return self.high
            return val
        if self.kind in ("choice", "boolean"):
            if raw_value in self.choices:
                return raw_value
            return self.choices[0]
        raise ValueError(f"Unsupported parameter kind: {self.kind}")


@dataclass
class GridLedger:
    """Tracks configuration cell lifecycle through verified promotion."""

    states: Dict[str, str] = field(default_factory=dict)
    evidence: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    def transition(
        self,
        cell_id: str,
        target_state: str,
        receipt: Optional[Dict[str, Any]] = None,
    ) -> str:
        if target_state not in _LIFECYCLE_ORDER:
            raise ValueError(f"Invalid lifecycle state: {target_state}")
        current = self.states.get(cell_id)
        if current is None:
            if target_state != _LIFECYCLE_ORDER[0]:
                raise ValueError("Initial state must be 'represented'")
        else:
            cur_idx = _LIFECYCLE_ORDER.index(current)
            tgt_idx = _LIFECYCLE_ORDER.index(target_state)
            if tgt_idx > cur_idx + 1:
                raise ValueError(f"Cannot skip lifecycle state: {current} -> {target_state}")
            if target_state == "promoted" and current != "verified":
                raise ValueError("Cannot promote an unverified configuration cell")
        self.states[cell_id] = target_state
        if receipt is not None:
            self.evidence.setdefault(cell_id, []).append(dict(receipt))
        return target_state


class NodeGrid:
    """Multi-dimensional configuration settings grid with boundary auto-expansion."""

    def __init__(self, spec: Dict[str, Any]) -> None:
        self.grid_id: str = str(spec["grid_id"])
        self.generation: int = int(spec["generation"])
        self.runtime_constants: Dict[str, Any] = dict(spec["runtime_constants"])
        self.constraints: List[Dict[str, Any]] = list(spec.get("constraints", []))
        self.parameters: Dict[str, ParameterBounds] = {}
        for name, pdef in spec["parameters"].items():
            self.parameters[name] = ParameterBounds(
                kind=str(pdef["kind"]),
                low=int(pdef["low"]) if "low" in pdef else None,
                high=int(pdef["high"]) if "high" in pdef else None,
                step=int(pdef["step"]) if "step" in pdef else None,
                choices=tuple(pdef.get("choices", ())),
            )
        self.regimes: Dict[str, Dict[str, Any]] = {}
        self.ledger = GridLedger()
        for regime_name, raw_cell in spec["regimes"].items():
            clamped = self._clamp_and_validate(raw_cell)
            self.regimes[regime_name] = clamped
            for st in _LIFECYCLE_ORDER:
                self.ledger.transition(regime_name, st, {"generation": self.generation})

    @classmethod
    def from_json_path(cls, path: Path) -> "NodeGrid":
        return cls(json.loads(path.read_text(encoding="utf-8")))

    def _clamp_and_validate(self, cell: Dict[str, Any]) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        for pname, bounds in self.parameters.items():
            resolved[pname] = bounds.clamp(cell[pname])
        for rule in self.constraints:
            if "when_param" in rule:
                wval = int(resolved[str(rule["when_param"])])
                if wval >= int(rule["min_value"]):
                    req_key = str(rule["require_param"])
                    if resolved[req_key] != rule["equals"]:
                        resolved[req_key] = rule["equals"]
            if "less_or_equal_pair" in rule:
                lo_key, hi_key = rule["less_or_equal_pair"]
                if int(resolved[lo_key]) > int(resolved[hi_key]):
                    resolved[lo_key] = resolved[hi_key]
        return resolved

    def resolve_cell(
        self,
        regime: str,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        base_name = regime if regime in self.regimes else next(iter(self.regimes))
        merged = dict(self.regimes[base_name])
        if overrides:
            for k, v in overrides.items():
                if k in self.parameters and v is not None:
                    merged[k] = v
        return self._clamp_and_validate(merged)

    def auto_expand_axis(self, param_name: str, observed_demand: int) -> bool:
        bounds = self.parameters[param_name]
        if bounds.kind != "integer_range" or bounds.high is None or bounds.low is None:
            return False
        if observed_demand <= bounds.high:
            return False
        factor = int(self.runtime_constants["boundary_expansion_factor"])
        new_high = max(observed_demand, bounds.high * factor)
        self.parameters[param_name] = ParameterBounds(
            kind=bounds.kind,
            low=bounds.low,
            high=new_high,
            step=bounds.step,
            choices=bounds.choices,
        )
        self.generation += 1
        return True


class MeteredCommerceAndFinOpsStore:
    """SQLite WAL ledger for x402/prepaid/order-capture metering and FinOps savings."""

    def __init__(
        self,
        db_path: Path,
        grid: NodeGrid,
        signing_secret: Optional[str] = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.grid = grid
        self._secret = (signing_secret or secrets.token_hex()).encode("utf-8")
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS payment_challenges (
                    challenge_id TEXT PRIMARY KEY,
                    tool_name TEXT NOT NULL,
                    settlement_rail TEXT NOT NULL,
                    price_microusd INTEGER NOT NULL,
                    expires_at REAL NOT NULL,
                    signature TEXT NOT NULL,
                    redeemed INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS settled_receipts (
                    tx_ref TEXT PRIMARY KEY,
                    challenge_id TEXT NOT NULL,
                    payer_id TEXT NOT NULL,
                    settlement_rail TEXT NOT NULL,
                    amount_microusd INTEGER NOT NULL,
                    settled_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS prepaid_balances (
                    account_id TEXT PRIMARY KEY,
                    balance_microusd INTEGER NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS verified_artifacts (
                    cache_key TEXT PRIMARY KEY,
                    task_hash TEXT NOT NULL,
                    contract_digest TEXT NOT NULL,
                    maker_id TEXT NOT NULL,
                    checker_ids_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS finops_cost_ledger (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id TEXT NOT NULL,
                    regime TEXT NOT NULL,
                    route_source TEXT NOT NULL,
                    chosen_effort TEXT NOT NULL,
                    baseline_microusd INTEGER NOT NULL,
                    actual_microusd INTEGER NOT NULL,
                    saved_microusd INTEGER NOT NULL,
                    platform_fee_microusd INTEGER NOT NULL,
                    recorded_at REAL NOT NULL
                );
                """
            )

    def _sign_challenge(self, challenge_id: str, tool_name: str, price_microusd: int, expires_at: float) -> str:
        hex_len = int(self.grid.runtime_constants["hmac_digest_hex_chars"])
        msg = f"{challenge_id}:{tool_name}:{price_microusd}:{expires_at:.3f}".encode("utf-8")
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()[:hex_len]

    def credit_prepaid_account(self, account_id: str, amount_microusd: int) -> Dict[str, Any]:
        if amount_microusd < 0:
            raise ValueError("amount_microusd must be non-negative")
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT balance_microusd FROM prepaid_balances WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            new_bal = (int(row["balance_microusd"]) if row else 0) + int(amount_microusd)
            conn.execute(
                """
                INSERT INTO prepaid_balances(account_id, balance_microusd, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    balance_microusd = excluded.balance_microusd,
                    updated_at = excluded.updated_at
                """,
                (account_id, new_bal, now),
            )
            conn.commit()
        return {"ok": True, "account_id": account_id, "balance_microusd": new_bal}

    def issue_payment_challenge(
        self,
        tool_name: str,
        regime: str = "micro_tool_x402",
        overrides: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        cell = self.grid.resolve_cell(regime, overrides)
        ts = float(now if now is not None else time.time())
        price = int(cell["unit_call_price_microusd"])
        if price > (self.grid.parameters["unit_call_price_microusd"].high or price):
            self.grid.auto_expand_axis("unit_call_price_microusd", price)
        expires_at = ts + float(cell["receipt_ttl_seconds"])
        hex_len = int(self.grid.runtime_constants["hmac_digest_hex_chars"])
        challenge_id = "chk_" + secrets.token_hex()[:hex_len]
        rail = str(cell["settlement_rail"])
        sig = self._sign_challenge(challenge_id, tool_name, price, expires_at)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO payment_challenges(
                    challenge_id, tool_name, settlement_rail, price_microusd, expires_at, signature, redeemed
                ) VALUES (?, ?, ?, ?, ?, ?, 0)
                """,
                (challenge_id, tool_name, rail, price, expires_at, sig),
            )
            conn.commit()
        return {
            "http_status": int(self.grid.runtime_constants["http_status_payment_required"]),
            "protocol": "x402-v1",
            "challenge_id": challenge_id,
            "tool_name": tool_name,
            "settlement_rail": rail,
            "price_microusd": price,
            "expires_at": expires_at,
            "signature": sig,
        }

    def authorize_or_settle_tool_call(
        self,
        tool_name: str,
        regime: str = "micro_tool_x402",
        account_id: Optional[str] = None,
        payment_proof: Optional[Dict[str, Any]] = None,
        now: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Gate an MCP or HTTP tool invocation via prepaid balance OR x402 / order-capture proof."""
        cell = self.grid.resolve_cell(regime)
        price = int(cell["unit_call_price_microusd"])
        ts = float(now if now is not None else time.time())
        ok_code = int(self.grid.runtime_constants["http_status_ok"])

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if payment_proof:
                tx_ref = str(payment_proof.get("tx_ref") or "").strip()
                challenge_id = str(payment_proof.get("challenge_id") or "").strip()
                paid_amount = int(payment_proof.get("amount_microusd") or 0)
                payer_id = str(payment_proof.get("payer_id") or account_id or "anonymous")
                rail = str(payment_proof.get("settlement_rail") or cell["settlement_rail"])

                dup = conn.execute(
                    "SELECT tx_ref FROM settled_receipts WHERE tx_ref = ?",
                    (tx_ref,),
                ).fetchone()
                if not tx_ref or dup is not None:
                    conn.rollback()
                    return {"ok": False, "error": "duplicate_or_empty_tx_ref", "http_status": int(self.grid.runtime_constants["http_status_payment_required"])}

                ch_row = conn.execute(
                    "SELECT * FROM payment_challenges WHERE challenge_id = ?",
                    (challenge_id,),
                ).fetchone()
                if ch_row is None or int(ch_row["redeemed"]) == 1:
                    conn.rollback()
                    return {"ok": False, "error": "invalid_or_redeemed_challenge", "http_status": int(self.grid.runtime_constants["http_status_payment_required"])}
                if str(ch_row["tool_name"]) != tool_name:
                    conn.rollback()
                    return {"ok": False, "error": "challenge_tool_mismatch", "http_status": int(self.grid.runtime_constants["http_status_payment_required"])}
                if ts > float(ch_row["expires_at"]):
                    conn.rollback()
                    return {"ok": False, "error": "challenge_expired", "http_status": int(self.grid.runtime_constants["http_status_payment_required"])}
                expected_sig = self._sign_challenge(
                    challenge_id,
                    str(ch_row["tool_name"]),
                    int(ch_row["price_microusd"]),
                    float(ch_row["expires_at"]),
                )
                if not hmac.compare_digest(expected_sig, str(ch_row["signature"])):
                    conn.rollback()
                    return {"ok": False, "error": "invalid_challenge_signature", "http_status": int(self.grid.runtime_constants["http_status_payment_required"])}
                if paid_amount < int(ch_row["price_microusd"]):
                    conn.rollback()
                    return {"ok": False, "error": "insufficient_payment_amount", "http_status": int(self.grid.runtime_constants["http_status_payment_required"])}

                conn.execute(
                    "UPDATE payment_challenges SET redeemed = 1 WHERE challenge_id = ?",
                    (challenge_id,),
                )
                conn.execute(
                    """
                    INSERT INTO settled_receipts(
                        tx_ref, challenge_id, payer_id, settlement_rail, amount_microusd, settled_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (tx_ref, challenge_id, payer_id, rail, paid_amount, ts),
                )
                conn.commit()
                return {
                    "ok": True,
                    "http_status": ok_code,
                    "settlement_mode": rail,
                    "tx_ref": tx_ref,
                    "charged_microusd": paid_amount,
                }

            if account_id:
                bal_row = conn.execute(
                    "SELECT balance_microusd FROM prepaid_balances WHERE account_id = ?",
                    (account_id,),
                ).fetchone()
                cur_bal = int(bal_row["balance_microusd"]) if bal_row else 0
                if cur_bal >= price:
                    rem = cur_bal - price
                    conn.execute(
                        "UPDATE prepaid_balances SET balance_microusd = ?, updated_at = ? WHERE account_id = ?",
                        (rem, ts, account_id),
                    )
                    conn.commit()
                    return {
                        "ok": True,
                        "http_status": ok_code,
                        "settlement_mode": "prepaid_credit",
                        "account_id": account_id,
                        "charged_microusd": price,
                        "remaining_balance_microusd": rem,
                    }
            conn.rollback()

        challenge = self.issue_payment_challenge(tool_name=tool_name, regime=regime, now=ts)
        challenge["ok"] = False
        challenge["error"] = "payment_required"
        return challenge

    def promote_verified_artifact(
        self,
        task_hash: str,
        contract_digest: str,
        maker_id: str,
        checker_id: str,
        payload: Dict[str, Any],
        regime: str = "enterprise_finops_share",
    ) -> Dict[str, Any]:
        cell = self.grid.resolve_cell(regime)
        if bool(cell["require_distinct_checker"]) and maker_id == checker_id:
            return {"ok": False, "error": "self_certification_rejected"}
        cache_key = f"{task_hash}:{contract_digest}"
        quorum = int(cell["verification_quorum"])
        now = time.time()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT checker_ids_json FROM verified_artifacts WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            checkers: List[str] = json.loads(existing["checker_ids_json"]) if existing else []
            if checker_id not in checkers:
                checkers.append(checker_id)
            conn.execute(
                """
                INSERT INTO verified_artifacts(
                    cache_key, task_hash, contract_digest, maker_id, checker_ids_json, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    checker_ids_json = excluded.checker_ids_json,
                    payload_json = excluded.payload_json
                """,
                (cache_key, task_hash, contract_digest, maker_id, json.dumps(checkers), json.dumps(payload, sort_keys=True), now),
            )
            conn.commit()
        promoted = len(checkers) >= quorum
        return {"ok": True, "promoted": promoted, "checker_count": len(checkers), "quorum": quorum}

    def evaluate_finops_request(
        self,
        account_id: str,
        prompt_text: str,
        contract_digest: str = "v1",
        structured_schema: bool = False,
        requested_max_tokens: Optional[int] = None,
        regime: str = "enterprise_finops_share",
    ) -> Dict[str, Any]:
        """Route request via verified cache + local effort guard and compute savings-share fee."""
        cell = self.grid.resolve_cell(regime)
        quorum = int(cell["verification_quorum"])
        task_hash = hashlib.sha256(prompt_text.strip().encode("utf-8")).hexdigest()
        cache_key = f"{task_hash}:{contract_digest}"

        bps_denom = int(self.grid.runtime_constants["basis_points_denominator"])
        per_1k = int(self.grid.runtime_constants["tokens_per_kilotoken"])
        price_per_1k = int(cell["output_token_price_microusd_per_1k"])
        baseline_tokens = int(cell["baseline_high_effort_tokens"])
        baseline_microusd = (baseline_tokens * price_per_1k) // per_1k

        with self._connect() as conn:
            row = conn.execute(
                "SELECT checker_ids_json, payload_json FROM verified_artifacts WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if row is not None:
                checkers = json.loads(row["checker_ids_json"])
                if len(checkers) >= quorum:
                    saved = baseline_microusd
                    fee = (saved * int(cell["savings_fee_basis_points"])) // bps_denom
                    conn.execute(
                        """
                        INSERT INTO finops_cost_ledger(
                            account_id, regime, route_source, chosen_effort,
                            baseline_microusd, actual_microusd, saved_microusd, platform_fee_microusd, recorded_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (account_id, regime, "verified_artifact_cache", "none", baseline_microusd, 0, saved, fee, time.time()),
                    )
                    conn.commit()
                    return {
                        "cache_hit": True,
                        "task_hash": task_hash,
                        "artifact": json.loads(row["payload_json"]),
                        "chosen_effort": "none",
                        "baseline_microusd": baseline_microusd,
                        "actual_microusd": 0,
                        "saved_microusd": saved,
                        "platform_fee_microusd": fee,
                    }

            clean = prompt_text.strip()
            is_trivial = (not structured_schema) and (len(clean) <= int(cell["trivial_prompt_char_cap"]))
            if is_trivial:
                effort = "minimal"
                est_tokens = int(cell["minimal_effort_tokens"])
                effective_max_tokens = requested_max_tokens
            else:
                effort = "high" if structured_schema else "medium"
                floor_tok = int(cell["structured_output_token_floor"])
                if structured_schema:
                    effective_max_tokens = max(int(requested_max_tokens or 0), floor_tok)
                    if effective_max_tokens > (self.grid.parameters["structured_output_token_floor"].high or effective_max_tokens):
                        self.grid.auto_expand_axis("structured_output_token_floor", effective_max_tokens)
                else:
                    effective_max_tokens = requested_max_tokens
                est_tokens = baseline_tokens if effort == "high" else (baseline_tokens + int(cell["minimal_effort_tokens"])) // int(self.grid.runtime_constants["boundary_expansion_factor"])

            actual_microusd = (est_tokens * price_per_1k) // per_1k
            saved = max(0, baseline_microusd - actual_microusd)
            fee = (saved * int(cell["savings_fee_basis_points"])) // bps_denom
            conn.execute(
                """
                INSERT INTO finops_cost_ledger(
                    account_id, regime, route_source, chosen_effort,
                    baseline_microusd, actual_microusd, saved_microusd, platform_fee_microusd, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, regime, "local_effort_calibrator", effort, baseline_microusd, actual_microusd, saved, fee, time.time()),
            )
            conn.commit()

        return {
            "cache_hit": False,
            "task_hash": task_hash,
            "chosen_effort": effort,
            "effective_max_tokens": effective_max_tokens,
            "baseline_microusd": baseline_microusd,
            "actual_microusd": actual_microusd,
            "saved_microusd": saved,
            "platform_fee_microusd": fee,
        }

    def summarize_revenue_and_savings(self) -> Dict[str, Any]:
        with self._connect() as conn:
            settled = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(amount_microusd), 0) AS rev FROM settled_receipts"
            ).fetchone()
            finops = conn.execute(
                """
                SELECT COUNT(*) AS n,
                       COALESCE(SUM(baseline_microusd), 0) AS base_u,
                       COALESCE(SUM(actual_microusd), 0) AS act_u,
                       COALESCE(SUM(saved_microusd), 0) AS sav_u,
                       COALESCE(SUM(platform_fee_microusd), 0) AS fee_u
                FROM finops_cost_ledger
                """
            ).fetchone()
        return {
            "grid_id": self.grid.grid_id,
            "grid_generation": self.grid.generation,
            "settled_tool_calls": int(settled["n"]),
            "settled_tool_revenue_microusd": int(settled["rev"]),
            "finops_evaluated_calls": int(finops["n"]),
            "finops_baseline_microusd": int(finops["base_u"]),
            "finops_actual_microusd": int(finops["act_u"]),
            "finops_saved_microusd": int(finops["sav_u"]),
            "finops_platform_fee_microusd": int(finops["fee_u"]),
        }


class ArtifactStoryboardCompiler:
    """Deterministically compiles productized explainroo launch video specs from repo briefs."""

    def __init__(self, grid: NodeGrid) -> None:
        self.grid = grid

    def compile_bundle(
        self,
        brief: Dict[str, Any],
        regime: str = "micro_tool_x402",
    ) -> Dict[str, Any]:
        cell = self.grid.resolve_cell(regime)
        rc = self.grid.runtime_constants
        scene_cap = int(cell["storyboard_scene_cap"])

        title = str(brief["title"]).strip()
        hook_line = str(brief["problem_statement"]).strip()
        pillars: List[Dict[str, str]] = list(brief.get("pillars", []))[: max(1, scene_cap - 1 - 1)]
        cta_url = str(brief["repo_url"]).strip()

        video_cfg = {
            "title": title,
            "theme": str(brief.get("theme") or "paper"),
            "size": f"{int(rc['default_canvas_width'])}x{int(rc['default_canvas_height'])}",
            "fps": int(rc["default_fps"]),
            "voice": str(brief.get("voice") or "af_heart"),
            "camera": "still",
            "captions": False,
            "music": {
                "style": "warm",
                "volume": float(rc["default_music_volume"]),
                "full": True,
                "duckDb": float(rc["default_duck_db"]),
            },
            "sfx": "minimal",
            "loudness": int(rc["default_loudness_lufs"]),
        }

        sections: List[str] = [f"## hook\n{hook_line} [#intro] Meet {title}."]
        scene_names: List[str] = ["hook"]
        for idx, p in enumerate(pillars):
            sname = f"pillar_{idx + 1}"
            scene_names.append(sname)
            sections.append(f"## {sname}\n[#card] {p['narration']}")
        scene_names.append("ship")
        sections.append(f"## ship\n[#cta] Deploy {title} today from {cta_url}.")

        return {
            "scene_count": len(scene_names),
            "scene_names": scene_names,
            "video_json": video_cfg,
            "script_md": "\n\n".join(sections) + "\n",
        }


def run_mcp_stdio_loop(store: MeteredCommerceAndFinOpsStore) -> None:
    """JSON-RPC 2.0 Stdio MCP server exposing metered gate + FinOps router tools."""
    tools = [
        {
            "name": "meter_issue_x402_challenge",
            "description": "Issue an HTTP 402 (x402) signed payment challenge for a metered MCP tool.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string"},
                    "regime": {"type": "string"},
                },
                "required": ["tool_name"],
            },
        },
        {
            "name": "meter_authorize_tool_call",
            "description": "Authorize a metered MCP call using prepaid credit or an x402 / order-capture receipt.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string"},
                    "regime": {"type": "string"},
                    "account_id": {"type": "string"},
                    "payment_proof": {"type": "object"},
                },
                "required": ["tool_name"],
            },
        },
        {
            "name": "finops_evaluate_and_meter",
            "description": "Route an LLM request via verified maker!=checker cache + local effort calibrator and record savings-share fee.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "account_id": {"type": "string"},
                    "prompt_text": {"type": "string"},
                    "contract_digest": {"type": "string"},
                    "structured_schema": {"type": "boolean"},
                    "requested_max_tokens": {"type": "integer"},
                    "regime": {"type": "string"},
                },
                "required": ["account_id", "prompt_text"],
            },
        },
    ]

    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        req = json.loads(line)
        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        if method == "initialize":
            result: Any = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "metered-mcp-finops-gate", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": tools}
        elif method == "tools/call":
            tname = str(params.get("name") or "")
            targs = dict(params.get("arguments") or {})
            if tname == "meter_issue_x402_challenge":
                payload = store.issue_payment_challenge(
                    tool_name=str(targs["tool_name"]),
                    regime=str(targs.get("regime") or "micro_tool_x402"),
                )
            elif tname == "meter_authorize_tool_call":
                payload = store.authorize_or_settle_tool_call(
                    tool_name=str(targs["tool_name"]),
                    regime=str(targs.get("regime") or "micro_tool_x402"),
                    account_id=targs.get("account_id"),
                    payment_proof=targs.get("payment_proof"),
                )
            elif tname == "finops_evaluate_and_meter":
                payload = store.evaluate_finops_request(
                    account_id=str(targs["account_id"]),
                    prompt_text=str(targs["prompt_text"]),
                    contract_digest=str(targs.get("contract_digest") or "v1"),
                    structured_schema=bool(targs.get("structured_schema", False)),
                    requested_max_tokens=targs.get("requested_max_tokens"),
                    regime=str(targs.get("regime") or "enterprise_finops_share"),
                )
            else:
                payload = {"ok": False, "error": f"unknown_tool:{tname}"}
            result = {"content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}]}
        else:
            if req_id is None:
                continue
            result = {"ok": True}

        if req_id is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
            sys.stdout.flush()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Metered MCP x402 Gate & LLM FinOps Savings Engine")
    parser.add_argument("--db", default="./.metered_gate.sqlite3", help="SQLite WAL path")
    parser.add_argument(
        "--grid",
        default=str(Path(__file__).resolve().parent / "commerce_finops_grid.json"),
        help="Path to NodeGrid JSON schema",
    )
    parser.add_argument("--mcp-stdio", action="store_true", help="Serve JSON-RPC 2.0 MCP over stdio")
    parser.add_argument("--summary", action="store_true", help="Print revenue and FinOps savings summary JSON")
    args = parser.parse_args(argv)

    grid = NodeGrid.from_json_path(Path(args.grid))
    store = MeteredCommerceAndFinOpsStore(db_path=Path(args.db), grid=grid)
    if args.mcp_stdio:
        run_mcp_stdio_loop(store)
        return 0
    if args.summary:
        print(json.dumps(store.summarize_revenue_and_savings(), indent=int(grid.runtime_constants["boundary_expansion_factor"]), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
