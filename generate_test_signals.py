#!/usr/bin/env python3
"""
Post Fiat Synthetic Test Signal Generator v1.0.0

Produces known-answer signal batches covering edge cases across all nine
protocols. Each generated batch is annotated with expected conformance
outcomes, enabling automated validation of the conformance testkit itself.

Scenarios:
  1. fully_conformant       — All 9 protocols should PASS
  2. schema_failures        — Signal schema FAIL, downstream cascade to SKIP
  3. cross_protocol_issues  — Schema PASS but cross-protocol consistency violations
  4. stale_proof            — Proof EXPIRED, drift DEGRADED
  5. routing_boundary       — Signals at exact gate thresholds
  6. aggregation_conflict   — Producers in EXTREME disagreement
  7. discovery_invalid      — Invalid producer entry
  8. lifecycle_idempotency  — Lifecycle report with negative growth (violation)
  9. empty_artifacts        — All artifacts empty/missing
  10. malformed_json        — Corrupt structure

Usage:
  python generate_test_signals.py output_dir/
  python generate_test_signals.py output_dir/ --scenario fully_conformant
  python generate_test_signals.py --list
"""

import json
import os
import sys
import hashlib
import datetime
import argparse
from typing import Dict, List, Any

__version__ = "1.0.0"

NOW = "2026-03-30T12:00:00Z"
NOW_DT = datetime.datetime(2026, 3, 30, 12, 0, 0, tzinfo=datetime.timezone.utc)


def compute_attribution_hash(signal):
    """SHA-256 of signal_id|symbol|direction|confidence|horizon_hours|timestamp."""
    parts = [
        str(signal.get("signal_id", "")),
        str(signal.get("symbol", "")),
        str(signal.get("direction", "")),
        str(signal.get("confidence", "")),
        str(signal.get("horizon_hours", "")),
        str(signal.get("timestamp", "")),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_signal(symbol="BTC", direction="bullish", confidence=0.62, horizon_hours=24,
                action="EXECUTE", producer_id="test-producer", index=0, timestamp=None,
                regime_id="NEUTRAL", duration_days=20, add_calibration=True,
                add_hash=True, add_regime=True, weak_symbol=None):
    """Create a well-formed FULL-level signal."""
    ts = timestamp or NOW
    sig = {
        "signal_id": f"test-{symbol}-{index:04d}",
        "producer_id": producer_id,
        "timestamp": ts,
        "symbol": symbol,
        "direction": direction,
        "confidence": confidence,
        "horizon_hours": horizon_hours,
        "action": action,
        "schema_version": "1.0.0",
    }
    if add_regime:
        sig["regime_context"] = {
            "regime_id": regime_id,
            "regime_confidence": 0.85,
            "proximity": 0.3,
            "duration_days": duration_days,
            "decision": "EXECUTE" if regime_id != "SYSTEMIC" else "NO_TRADE",
        }
    if add_calibration:
        sig["calibration"] = {
            "method": "empirical_conditional",
            "sample_size": 200,
            "empirical_hit_rate": 0.52,
            "brier_score": 0.24,
        }
    if add_hash:
        sig["attribution_hash"] = compute_attribution_hash(sig)
    if action == "INVERT" and weak_symbol:
        sig["weak_symbol"] = weak_symbol
    elif action == "INVERT" and not weak_symbol:
        sig["weak_symbol"] = {
            "weakness_score": 0.70,
            "severity": "SEVERE",
            "original_direction": "bearish" if direction == "bullish" else "bullish",
            "inversion_p_value": 0.0001,
        }
    return sig


def make_proof_surface(freshness="LIVE", drift="STABLE", n_resolved=500,
                       accuracy=0.55, reputation_score=0.68, reputation_grade="B",
                       age_hours=0.5, threshold_hours=24):
    """Create a well-formed proof surface."""
    return {
        "meta": {
            "producer_id": "test-producer",
            "wallet": "rTestWallet123",
            "generated_at": NOW,
            "protocol_version": "1.0.0",
            "signal_schema_version": "1.0.0",
            "resolution_protocol_version": "1.0.0",
        },
        "freshness_metadata": {
            "last_resolved_at": NOW,
            "last_update_at": NOW,
            "staleness_threshold_hours": threshold_hours,
            "freshness_grade": freshness,
            "age_hours": age_hours,
            "signals_since_last_update": 0,
        },
        "snapshot_metadata": {
            "snapshot_id": "snap-001",
            "snapshot_version": 1,
            "parent_snapshot_id": None,
            "n_resolved_total": n_resolved,
            "n_new_resolved": 50,
            "n_unresolved_remaining": 20,
        },
        "resolution_delta": {
            "cycle_start": "2026-03-29T12:00:00Z",
            "cycle_end": NOW,
            "n_attempted": 55,
            "n_resolved": 50,
            "n_failed": 3,
            "n_skipped": 2,
            "resolution_rate": 0.909,
            "accuracy_this_cycle": accuracy,
            "price_data_source": "yahoo_finance",
        },
        "rolling_windows": [
            {
                "window_id": "7d",
                "n_signals": 100,
                "n_resolved": 95,
                "resolution_rate": 0.95,
                "accuracy": {"point": accuracy, "lower": accuracy - 0.05, "upper": accuracy + 0.05, "n": 95},
                "brier_score": 0.24,
                "reliability": 0.002,
                "resolution": 0.008,
                "calibration_slope": 0.95,
                "per_symbol": {
                    "BTC": {"accuracy": accuracy + 0.01, "n": 30, "brier_score": 0.23},
                    "ETH": {"accuracy": accuracy, "n": 25, "brier_score": 0.24},
                    "SOL": {"accuracy": accuracy - 0.02, "n": 20, "brier_score": 0.25},
                    "LINK": {"accuracy": accuracy + 0.02, "n": 20, "brier_score": 0.23},
                },
            },
            {
                "window_id": "14d",
                "n_signals": 200,
                "n_resolved": 190,
                "resolution_rate": 0.95,
                "accuracy": {"point": accuracy, "lower": accuracy - 0.04, "upper": accuracy + 0.04, "n": 190},
                "brier_score": 0.24,
                "reliability": 0.002,
                "resolution": 0.007,
                "calibration_slope": 0.96,
            },
            {
                "window_id": "30d",
                "n_signals": 400,
                "n_resolved": 380,
                "resolution_rate": 0.95,
                "accuracy": {"point": accuracy, "lower": accuracy - 0.03, "upper": accuracy + 0.03, "n": 380},
                "brier_score": 0.24,
                "reliability": 0.002,
                "resolution": 0.006,
                "calibration_slope": 0.97,
            },
            {
                "window_id": "all_time",
                "n_signals": n_resolved + 50,
                "n_resolved": n_resolved,
                "resolution_rate": 0.91,
                "accuracy": {"point": accuracy, "lower": accuracy - 0.02, "upper": accuracy + 0.02, "n": n_resolved},
                "brier_score": 0.24,
                "reliability": 0.001,
                "resolution": 0.005,
                "calibration_slope": 0.98,
            },
        ],
        "cusum_state": {
            "cusum_pos": 0.3 if drift == "STABLE" else 1.8,
            "cusum_neg": 0.2 if drift == "STABLE" else 1.9,
            "drift_status": drift,
            "drift_detected_at": None if drift == "STABLE" else "2026-03-28T12:00:00Z",
            "drift_direction": "none" if drift == "STABLE" else "degrading",
            "target_accuracy": accuracy,
            "allowance": 0.02,
            "threshold": 1.5,
            "observations_since_reset": 100,
            "run_length": 0 if drift in ("STABLE", "WATCH") else 60,
        },
        "calibration_trajectory": {
            "checkpoints": [
                {"timestamp": "2026-03-01T12:00:00Z", "n_cumulative": 100, "accuracy": 0.51, "brier_score": 0.25, "reliability": 0.003, "calibration_slope": 0.90},
                {"timestamp": "2026-03-15T12:00:00Z", "n_cumulative": 300, "accuracy": 0.53, "brier_score": 0.24, "reliability": 0.002, "calibration_slope": 0.94},
                {"timestamp": "2026-03-30T12:00:00Z", "n_cumulative": n_resolved, "accuracy": accuracy, "brier_score": 0.24, "reliability": 0.001, "calibration_slope": 0.98},
            ],
            "trend": {"slope_per_day": 0.0005, "p_value": 0.03, "interpretation": "IMPROVING"},
        },
        "reputation": {
            "score": reputation_score,
            "grade": reputation_grade,
            "previous_score": reputation_score - 0.02,
            "score_delta": 0.02,
        },
        "limitations": [
            {
                "id": "OBSERVATION_WINDOW",
                "description": "Forward-test period dominated by SYSTEMIC regime. Directional edge observed primarily in NEUTRAL windows.",
                "bias_direction": "UNDERSTATED",
                "bias_magnitude": "Accuracy during NEUTRAL periods (58%) higher than aggregate (55%). SYSTEMIC accuracy near 50% baseline drags overall number down.",
            },
        ],
        "protocol_version": "1.0.0",
    }


def make_routing_config(regime="NEUTRAL", duration_days=20):
    """Create a well-formed routing policy config."""
    return {
        "policy_version": "1.0.0",
        "producer_id": "test-producer",
        "gates": {
            "regime_gate": {"enabled": True, "allowed_regimes": ["NEUTRAL", "DIVERGENCE"]},
            "duration_gate": {"enabled": True, "default_min_days": 15},
            "confidence_gate": {"enabled": True, "default_min_confidence": 0.30},
            "voi_gate": {"enabled": True, "min_voi": 0.0, "use_hazard_adjustment": False},
            "weak_symbol_gate": {"enabled": True, "severity_threshold": "MODERATE"},
        },
        "symbols": {
            "BTC": {"min_duration_days": 10, "min_confidence": 0.30, "weak_symbol_policy": "NONE", "accuracy": 0.55},
            "ETH": {"min_duration_days": 12, "min_confidence": 0.30, "weak_symbol_policy": "NONE", "accuracy": 0.53},
            "SOL": {
                "min_duration_days": 15, "min_confidence": 0.30,
                "weak_symbol_policy": "INVERT", "accuracy": 0.44,
                "weakness_score": 0.70, "weakness_severity": "SEVERE",
                "inversion_justified": True, "inversion_p_value": 0.0001,
            },
            "LINK": {"min_duration_days": 15, "min_confidence": 0.30, "weak_symbol_policy": "NONE", "accuracy": 0.54},
        },
        "duration_buckets": [
            {"label": "early", "min_days": 0, "max_days": 12},
            {"label": "mid", "min_days": 12, "max_days": 15},
            {"label": "mature", "min_days": 15, "max_days": 18},
            {"label": "late", "min_days": 18, "max_days": 9999},
        ],
    }


def make_resolution_report(n_resolved=500, accuracy=0.55):
    """Create a well-formed resolution report."""
    hits = int(n_resolved * accuracy)
    brier = round((1 - accuracy) * 0.5 + accuracy * 0.1, 4)
    uncertainty = 0.25
    reliability = 0.002
    resolution_val = 0.005
    check_sum = round(reliability - resolution_val + uncertainty, 6)

    return {
        "meta": {
            "producer_id": "test-producer",
            "generated_at": NOW,
            "protocol_version": "1.0.0",
            "signal_schema_version": "1.0.0",
            "date_range": {"start": "2026-03-01T00:00:00Z", "end": NOW},
            "price_source": "yahoo_finance",
        },
        "signal_summary": {
            "total_signals": n_resolved + 50,
            "total_resolved": n_resolved,
            "total_unresolved": 50,
            "resolution_rate": round(n_resolved / (n_resolved + 50), 4),
        },
        "overall": {
            "brier_score": check_sum,
            "reliability": reliability,
            "resolution": resolution_val,
            "uncertainty": uncertainty,
            "check_sum": check_sum,
            "accuracy": {
                "point": accuracy,
                "lower": accuracy - 0.03,
                "upper": accuracy + 0.03,
                "n": n_resolved,
            },
            "calibration_slope": 0.97,
            "sharpness": 0.03,
        },
        "per_symbol": {
            "BTC": {
                "symbol": "BTC",
                "n": 150,
                "brier_decomposition": {"brier_score": 0.24, "reliability": 0.002, "resolution": 0.005},
                "karma": {"cumulative_karma": 5.2, "mean_karma": 0.035},
            },
            "ETH": {
                "symbol": "ETH",
                "n": 130,
                "brier_decomposition": {"brier_score": 0.24, "reliability": 0.002, "resolution": 0.004},
                "karma": {"cumulative_karma": 3.8, "mean_karma": 0.029},
            },
            "SOL": {
                "symbol": "SOL",
                "n": 110,
                "brier_decomposition": {"brier_score": 0.26, "reliability": 0.003, "resolution": 0.003},
                "karma": {"cumulative_karma": -2.1, "mean_karma": -0.019},
            },
            "LINK": {
                "symbol": "LINK",
                "n": 110,
                "brier_decomposition": {"brier_score": 0.23, "reliability": 0.001, "resolution": 0.006},
                "karma": {"cumulative_karma": 4.5, "mean_karma": 0.041},
            },
        },
        "karma": {
            "cumulative_karma": 11.4,
            "mean_karma": round(11.4 / n_resolved, 6),
            "predicted_karma": 12.0,
            "realized_karma": 11.4,
            "prediction_error": round(abs(12.0 - 11.4) / 12.0, 4),
        },
        "confidence_weighted_accuracy": {
            "cw_accuracy": accuracy + 0.01,
            "binary_accuracy": accuracy,
            "delta": 0.01,
        },
        "reputation": {
            "composite_score": 0.68,
            "grade": "B",
            "components": {
                "calibration_quality": {"score": 0.992, "weight": 0.20},
                "binary_accuracy": {"score": 0.25, "weight": 0.15},
                "cw_accuracy": {"score": 0.30, "weight": 0.20},
                "abstention_discipline": {"score": 0.15, "weight": 0.10},
                "confidence_sharpness": {"score": 0.60, "weight": 0.10},
                "karma_validation": {"score": 0.95, "weight": 0.10},
                "monotonicity": {"score": 1.0, "weight": 0.15},
            },
            "formula_version": "1.0.0",
        },
        "limitations": [
            {"id": "SYSTEMIC_DOMINANCE", "description": "Observation window dominated by SYSTEMIC regime.", "bias_direction": "UNDERSTATED", "bias_magnitude": "Accuracy during NEUTRAL periods higher."},
        ],
        "protocol_version": "1.0.0",
    }


def make_discovery_entry(liveness="ALIVE", reputation_score=0.68, grade="B"):
    """Create a well-formed producer discovery entry."""
    return {
        "producer_id": "test-producer",
        "display_name": "Test Signal Producer",
        "description": "Conformance test producer for protocol validation.",
        "endpoint_url": "http://localhost:8080",
        "repository_url": "https://github.com/test/test-signals",
        "capabilities": ["crypto_signals", "regime_detection", "routing_policy", "weak_symbol_policy", "proof_surface", "multi_symbol"],
        "symbol_coverage": {
            "symbols": ["BTC", "ETH", "SOL", "LINK"],
            "symbol_count": 4,
        },
        "reputation_summary": {
            "score": reputation_score,
            "grade": grade,
            "accuracy": 0.55,
            "calibration": 0.97,
            "n_resolved": 500,
            "last_resolved_at": NOW,
        },
        "proof_summary": {
            "proof_surface_url": "https://raw.githubusercontent.com/test/test-signals/proof_surface.json",
            "freshness_grade": "LIVE",
            "drift_status": "STABLE",
            "last_update_at": NOW,
        },
        "supported_protocols": {
            "signal_schema": "1.0.0",
            "resolution_protocol": "1.0.0",
            "routing_protocol": "1.0.0",
            "aggregation_protocol": "1.0.0",
            "proof_protocol": "1.0.0",
            "lifecycle_pipeline": "1.0.0",
            "consumer_audit": "1.0.0",
            "discovery_protocol": "1.0.0",
        },
        "liveness": {
            "heartbeat_interval_seconds": 900,
            "last_heartbeat_at": NOW,
            "liveness_grade": liveness,
            "consecutive_misses": 0,
        },
        "registration": {
            "registered_at": "2026-03-01T00:00:00Z",
            "registrar": "self_attestation",
            "registration_version": "1.0.0",
        },
    }


def make_quickstart_verdict(score=0.76, grade="B", verdict="TRUST"):
    """Create a well-formed consumer verdict."""
    return {
        "meta": {
            "quickstart_version": "1.0.0",
            "protocol_version": "1.0.0",
            "generated_at": NOW,
            "producer_id": "test-producer",
            "content_hash": "abcdef1234567890",
        },
        "verdict": {
            "trust_score": score,
            "trust_grade": grade,
            "trust_verdict": verdict,
        },
        "stages": [
            {"stage": "discovery", "status": "PASS", "duration_ms": 50},
            {"stage": "signal_fetch", "status": "PASS", "duration_ms": 30},
            {"stage": "schema_validation", "status": "PASS", "duration_ms": 120},
            {"stage": "routing_audit", "status": "PASS", "duration_ms": 80},
            {"stage": "resolution_verification", "status": "PASS", "duration_ms": 200},
            {"stage": "proof_verification", "status": "PASS", "duration_ms": 60},
            {"stage": "full_audit", "status": "PASS", "duration_ms": 40},
        ],
        "trust_components": {
            "schema_compliance": {"score": 1.0, "weight": 0.15, "weighted": 0.15},
            "freshness": {"score": 1.0, "weight": 0.15, "weighted": 0.15},
            "reputation": {"score": 0.68, "weight": 0.20, "weighted": 0.136},
            "drift_stability": {"score": 1.0, "weight": 0.15, "weighted": 0.15},
            "routing_discipline": {"score": 0.8, "weight": 0.10, "weighted": 0.08},
            "discovery_health": {"score": 1.0, "weight": 0.10, "weighted": 0.10},
            "signal_volume": {"score": 1.0, "weight": 0.15, "weighted": 0.15},
        },
        "findings": [],
        "limitations": [],
    }


def make_audit_report(score=0.93, grade="A", verdict="TRUST"):
    """Create a well-formed audit report."""
    return {
        "meta": {
            "audit_version": "1.0.0",
            "generated_at": NOW,
            "producer_id": "test-producer",
            "companion_versions": {
                "signal_schema": "1.0.0",
                "resolution_protocol": "1.0.0",
                "routing_protocol": "1.0.0",
                "aggregation_protocol": "1.0.0",
                "proof_protocol": "1.0.0",
                "lifecycle_pipeline": "1.0.0",
            },
        },
        "schema_compliance": {
            "signal_schema": {"status": "PASS", "valid_signals": 500, "invalid_signals": 0},
            "proof_surface": {"status": "PASS", "n_schema_errors": 0},
            "routing_config": {"status": "PASS"},
            "overall_status": "PASS",
        },
        "freshness_verification": {"status": "PASS", "freshness_grade": "LIVE", "age_hours": 0.5},
        "reputation_recomputation": {
            "status": "PASS",
            "claimed_score": 0.68,
            "recomputed_score": 0.68,
            "score_discrepancy": 0.0,
        },
        "drift_verification": {"status": "PASS", "drift_status": "STABLE", "cusum_pos": 0.3, "cusum_neg": 0.2},
        "routing_audit": {"status": "PASS", "filter_rate": 0.15, "total_signals_routed": 500},
        "aggregation_inspection": {"status": "SKIP", "reason": "No registry provided"},
        "trust_grade": {
            "score": score,
            "grade": grade,
            "verdict": verdict,
            "components": {
                "schema_compliance": {"score": 1.0, "weight": 0.15, "weighted": 0.15},
                "freshness": {"score": 1.0, "weight": 0.15, "weighted": 0.15},
                "drift_health": {"score": 1.0, "weight": 0.15, "weighted": 0.15},
                "reputation_consistency": {"score": 1.0, "weight": 0.20, "weighted": 0.20},
                "signal_volume": {"score": 1.0, "weight": 0.10, "weighted": 0.10},
                "calibration_quality": {"score": 0.85, "weight": 0.15, "weighted": 0.1275},
                "routing_discipline": {"score": 0.8, "weight": 0.10, "weighted": 0.08},
            },
            "cold_start": False,
        },
        "findings": [],
        "summary": {"total_checks": 25, "passed": 24, "failed": 0, "warnings": 1, "skipped": 0, "total_findings": 0},
        "limitations": [],
    }


# ===================================================================
# SCENARIO GENERATORS
# ===================================================================

SCENARIOS = {}


def scenario(name, description, expected_outcomes):
    """Decorator to register a scenario generator."""
    def decorator(func):
        SCENARIOS[name] = {
            "generator": func,
            "description": description,
            "expected_outcomes": expected_outcomes,
        }
        return func
    return decorator


@scenario(
    "fully_conformant",
    "All provided artifacts well-formed. Provided protocols PASS. Grade B (aggregation+lifecycle SKIP).",
    {
        "signal_schema": "PASS",
        "routing_protocol": "PASS",
        "resolution_protocol": "PASS",
        "aggregation_protocol": "SKIP",
        "proof_protocol": "PASS",
        "lifecycle_pipeline": "SKIP",
        "consumer_audit": "PASS",
        "discovery_protocol": "PASS",
        "consumer_quickstart": "PASS",
        "expected_grade": "B",
        "cross_protocol_errors": 0,
    },
)
def gen_fully_conformant():
    signals = [
        make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i)
        for i in range(10)
    ] + [
        make_signal("ETH", "bearish", 0.58, 24, "EXECUTE", index=10+i)
        for i in range(10)
    ] + [
        make_signal("SOL", "bullish", 0.55, 24, "INVERT", index=20+i)
        for i in range(5)
    ] + [
        make_signal("LINK", "bullish", 0.60, 24, "EXECUTE", index=25+i)
        for i in range(5)
    ]

    return {
        "signals.json": signals,
        "proof_surface.json": make_proof_surface(),
        "routing_policy.json": make_routing_config(),
        "resolution_report.json": make_resolution_report(),
        "producer_entry.json": make_discovery_entry(),
        "consumer_verdict.json": make_quickstart_verdict(),
        "audit_report.json": make_audit_report(),
    }


@scenario(
    "schema_failures",
    "Signals with missing required fields and invalid values. Schema FAIL, downstream protocols SKIP due to cascade.",
    {
        "signal_schema": "FAIL",
        "routing_protocol": "SKIP",
        "resolution_protocol": "SKIP",
        "aggregation_protocol": "SKIP",
        "proof_protocol": "PASS",
        "lifecycle_pipeline": "SKIP",
        "consumer_audit": "PASS",
        "discovery_protocol": "PASS",
        "consumer_quickstart": "SKIP",
        "expected_grade": "F",
        "cross_protocol_errors": 0,
    },
)
def gen_schema_failures():
    bad_signals = [
        # Missing required fields
        {"producer_id": "test", "timestamp": NOW},  # missing most required
        # Invalid confidence
        {"signal_id": "bad-1", "producer_id": "test", "timestamp": NOW,
         "symbol": "BTC", "direction": "bullish", "confidence": 1.5,
         "horizon_hours": 24, "action": "EXECUTE", "schema_version": "1.0.0"},
        # Invalid direction
        {"signal_id": "bad-2", "producer_id": "test", "timestamp": NOW,
         "symbol": "ETH", "direction": "sideways", "confidence": 0.5,
         "horizon_hours": 24, "action": "EXECUTE", "schema_version": "1.0.0"},
        # Invalid action
        {"signal_id": "bad-3", "producer_id": "test", "timestamp": NOW,
         "symbol": "SOL", "direction": "bullish", "confidence": 0.5,
         "horizon_hours": 24, "action": "HOLD", "schema_version": "1.0.0"},
        # INVERT without weak_symbol
        {"signal_id": "bad-4", "producer_id": "test", "timestamp": NOW,
         "symbol": "SOL", "direction": "bullish", "confidence": 0.5,
         "horizon_hours": 24, "action": "INVERT", "schema_version": "1.0.0"},
        # Invalid symbol (lowercase)
        {"signal_id": "bad-5", "producer_id": "test", "timestamp": NOW,
         "symbol": "btc", "direction": "bullish", "confidence": 0.5,
         "horizon_hours": 24, "action": "EXECUTE", "schema_version": "1.0.0"},
        # horizon_hours out of range
        {"signal_id": "bad-6", "producer_id": "test", "timestamp": NOW,
         "symbol": "BTC", "direction": "bullish", "confidence": 0.5,
         "horizon_hours": 0, "action": "EXECUTE", "schema_version": "1.0.0"},
        # Good signal (1 of 8)
        make_signal("BTC", "bullish", 0.6, 24, "EXECUTE", index=99),
    ]

    return {
        "signals.json": bad_signals,
        "proof_surface.json": make_proof_surface(),
        "producer_entry.json": make_discovery_entry(),
        "consumer_verdict.json": make_quickstart_verdict(),
        "audit_report.json": make_audit_report(),
    }


@scenario(
    "cross_protocol_issues",
    "Signals pass schema but have cross-protocol inconsistencies: orphaned resolved signals, mismatched producer IDs, symbol coverage gaps.",
    {
        "signal_schema": "PASS",
        "routing_protocol": "PASS",
        "resolution_protocol": "PASS",
        "aggregation_protocol": "SKIP",
        "proof_protocol": "PASS",
        "lifecycle_pipeline": "SKIP",
        "consumer_audit": "SKIP",
        "discovery_protocol": "PASS",
        "consumer_quickstart": "SKIP",
        "expected_grade": "B",
        "cross_protocol_errors": 0,
        "cross_protocol_warnings": 2,
    },
)
def gen_cross_protocol_issues():
    signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(10)]

    # Proof with resolved signals not in signal log
    proof = make_proof_surface()
    proof["resolved_signals"] = [
        {"signal_id": "orphan-001", "symbol": "BTC", "resolved": True, "outcome": 1.0},
        {"signal_id": "orphan-002", "symbol": "ETH", "resolved": True, "outcome": 0.0},
    ]

    # Resolution report with different producer_id
    resolution = make_resolution_report()
    resolution["meta"]["producer_id"] = "different-producer"

    # Discovery entry missing DOGE (signals have BTC only, entry has BTC+ETH+SOL+LINK — fine)
    # But signals only have BTC — entry declares more, which is ok
    # Lets make entry NOT declare BTC to trigger the warning
    entry = make_discovery_entry()
    entry["symbol_coverage"]["symbols"] = ["ETH", "SOL", "LINK"]  # missing BTC

    return {
        "signals.json": signals,
        "proof_surface.json": proof,
        "routing_policy.json": make_routing_config(),
        "resolution_report.json": resolution,
        "producer_entry.json": entry,
    }


@scenario(
    "stale_proof",
    "Proof surface is EXPIRED with DEGRADED drift. Proof protocol PASS (semantic warnings only, no schema errors). Cross-protocol catches ALIVE+EXPIRED inconsistency.",
    {
        "signal_schema": "PASS",
        "routing_protocol": "SKIP",
        "resolution_protocol": "SKIP",
        "aggregation_protocol": "SKIP",
        "proof_protocol": "PASS",
        "lifecycle_pipeline": "SKIP",
        "consumer_audit": "SKIP",
        "discovery_protocol": "PASS",
        "consumer_quickstart": "SKIP",
        "expected_grade": "C",
        "cross_protocol_errors": 0,
        "cross_protocol_warnings": 1,
    },
)
def gen_stale_proof():
    signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(10)]
    proof = make_proof_surface(freshness="EXPIRED", drift="DEGRADED", age_hours=120, threshold_hours=24)
    entry = make_discovery_entry(liveness="ALIVE")  # Inconsistent: ALIVE but EXPIRED proof

    return {
        "signals.json": signals,
        "proof_surface.json": proof,
        "producer_entry.json": entry,
    }


@scenario(
    "routing_boundary",
    "Signals at exact gate boundary thresholds. Tests boundary condition handling.",
    {
        "signal_schema": "PASS",
        "routing_protocol": "PASS",
        "resolution_protocol": "SKIP",
        "aggregation_protocol": "SKIP",
        "proof_protocol": "SKIP",
        "lifecycle_pipeline": "SKIP",
        "consumer_audit": "SKIP",
        "discovery_protocol": "SKIP",
        "consumer_quickstart": "SKIP",
        "expected_grade": "C",
        "cross_protocol_errors": 0,
    },
)
def gen_routing_boundary():
    signals = [
        make_signal("BTC", "bullish", 0.30, 24, "EXECUTE", index=0, duration_days=15),  # Exactly at confidence min
        make_signal("ETH", "bearish", 0.29, 24, "WITHHOLD", index=1, duration_days=15),  # Just below confidence min
        make_signal("SOL", "bullish", 0.50, 24, "INVERT", index=2, duration_days=15),  # SOL INVERT
        make_signal("LINK", "bullish", 0.60, 24, "EXECUTE", index=3, duration_days=14),  # Just below duration min
    ]

    config = make_routing_config()
    return {
        "signals.json": signals,
        "routing_policy.json": config,
    }


@scenario(
    "aggregation_conflict",
    "Multi-producer aggregation with EXTREME disagreement triggering CONFLICT action.",
    {
        "signal_schema": "PASS",
        "routing_protocol": "SKIP",
        "resolution_protocol": "SKIP",
        "aggregation_protocol": "PASS",
        "proof_protocol": "SKIP",
        "lifecycle_pipeline": "SKIP",
        "consumer_audit": "SKIP",
        "discovery_protocol": "SKIP",
        "consumer_quickstart": "SKIP",
        "expected_grade": "C",
        "cross_protocol_errors": 0,
    },
)
def gen_aggregation_conflict():
    signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(5)]

    agg_report = {
        "meta": {
            "generated_at": NOW,
            "protocol_version": "1.0.0",
            "signal_schema_version": "1.0.0",
            "resolution_protocol_version": "1.0.0",
            "routing_protocol_version": "1.0.0",
            "aggregation_protocol_version": "1.0.0",
            "n_producers": 3,
            "n_active": 3,
            "aggregation_method": "reputation_weighted_vote",
            "regime_context": {"regime_id": "NEUTRAL", "duration_days": 20, "regime_confidence": 0.85},
            "quorum_threshold": 2,
            "conflict_threshold": 0.70,
        },
        "summary": {
            "total_symbols": 1,
            "total_emit": 0,
            "total_withhold": 0,
            "total_invert": 0,
            "total_conflict": 1,
            "consensus_rate": 0.0,
            "mean_disagreement": 0.85,
            "producer_weight_distribution": {"max_weight": 0.45, "min_weight": 0.20, "hhi": 0.38},
        },
        "decisions": [{
            "symbol": "BTC",
            "consensus_action": "CONFLICT",
            "consensus_direction": "undetermined",
            "consensus_confidence": 0.55,
            "weighted_score": 0.05,
            "n_producers": 3,
            "n_active": 3,
            "quorum_met": True,
            "disagreement": {
                "index": 0.85,
                "level": "EXTREME",
                "n_bullish": 2,
                "n_bearish": 1,
                "n_withhold": 0,
                "direction_split": 0.333,
                "weighted_direction_split": 0.30,
            },
            "contributions": [
                {"producer_id": "alpha", "signal_id": "a-1", "direction": "bullish", "confidence": 0.70, "action": "EXECUTE", "weight": 0.45, "weighted_vote": 0.315},
                {"producer_id": "beta", "signal_id": "b-1", "direction": "bearish", "confidence": 0.80, "action": "EXECUTE", "weight": 0.35, "weighted_vote": -0.28},
                {"producer_id": "gamma", "signal_id": "g-1", "direction": "bullish", "confidence": 0.40, "action": "EXECUTE", "weight": 0.20, "weighted_vote": 0.08},
            ],
        }],
        "protocol_version": "1.0.0",
    }

    return {
        "signals.json": signals,
        "aggregation_report.json": agg_report,
    }


@scenario(
    "discovery_invalid",
    "Producer entry with invalid capabilities, missing required fields, and out-of-range values.",
    {
        "signal_schema": "PASS",
        "routing_protocol": "SKIP",
        "resolution_protocol": "SKIP",
        "aggregation_protocol": "SKIP",
        "proof_protocol": "SKIP",
        "lifecycle_pipeline": "SKIP",
        "consumer_audit": "SKIP",
        "discovery_protocol": "FAIL",
        "consumer_quickstart": "SKIP",
        "expected_grade": "D",
        "cross_protocol_errors": 0,
    },
)
def gen_discovery_invalid():
    signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(5)]

    bad_entry = {
        "producer_id": "",  # Empty (too short)
        "capabilities": ["crypto_signals", "time_travel"],  # Invalid capability
        "symbol_coverage": {
            "symbols": ["btc", "ETH"],  # Lowercase btc
        },
        "reputation_summary": {
            "score": 1.5,  # Out of range
            "grade": "S",  # Invalid grade (not in schema)
            "accuracy": 0.55,
            "n_resolved": 100,
        },
        "supported_protocols": {},  # Missing signal_schema
        "liveness": {
            "heartbeat_interval_seconds": 10,  # Below minimum (60)
            "liveness_grade": "ALIVE",
        },
        "registration": {
            "registered_at": NOW,
            "registrar": "magic",  # Invalid registrar
            "registration_version": "1.0.0",
        },
    }

    return {
        "signals.json": signals,
        "producer_entry.json": bad_entry,
    }


@scenario(
    "lifecycle_idempotency",
    "Lifecycle report with negative n_new_resolved (violation of monotonicity).",
    {
        "signal_schema": "PASS",
        "routing_protocol": "SKIP",
        "resolution_protocol": "SKIP",
        "aggregation_protocol": "SKIP",
        "proof_protocol": "SKIP",
        "lifecycle_pipeline": "FAIL",
        "consumer_audit": "SKIP",
        "discovery_protocol": "SKIP",
        "consumer_quickstart": "SKIP",
        "expected_grade": "D",
        "cross_protocol_errors": 0,
    },
)
def gen_lifecycle_idempotency():
    signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(5)]

    lifecycle_report = {
        "pipeline_meta": {
            "stages": [
                {"stage": "LOAD", "status": "PASS"},
                {"stage": "VALIDATE", "status": "PASS"},
                {"stage": "FETCH_PRICES", "status": "PASS"},
                {"stage": "MAINTAIN_PROOF", "status": "PASS"},
                {"stage": "VALIDATE_REPORT", "status": "INVALID_STATUS"},  # Invalid status
                {"stage": "PUBLISH", "status": "PASS"},
            ],
        },
        "resolution_growth": {
            "n_new_resolved": -5,  # Negative (violation)
            "growth_rate": -0.01,
        },
        "content_hash": "ab",  # Too short
    }

    return {
        "signals.json": signals,
        "lifecycle_report.json": lifecycle_report,
    }


@scenario(
    "empty_artifacts",
    "All artifact files present but empty or minimal. All protocols should SKIP or WARN.",
    {
        "signal_schema": "WARN",
        "routing_protocol": "SKIP",
        "resolution_protocol": "SKIP",
        "aggregation_protocol": "SKIP",
        "proof_protocol": "SKIP",
        "lifecycle_pipeline": "SKIP",
        "consumer_audit": "SKIP",
        "discovery_protocol": "SKIP",
        "consumer_quickstart": "SKIP",
        "expected_grade": "D",
        "cross_protocol_errors": 0,
    },
)
def gen_empty_artifacts():
    return {
        "signals.json": [],
    }


@scenario(
    "partial_conformance",
    "Producer with good signals and proof but no routing or resolution. Mixed PASS/SKIP.",
    {
        "signal_schema": "PASS",
        "routing_protocol": "SKIP",
        "resolution_protocol": "SKIP",
        "aggregation_protocol": "SKIP",
        "proof_protocol": "PASS",
        "lifecycle_pipeline": "SKIP",
        "consumer_audit": "SKIP",
        "discovery_protocol": "PASS",
        "consumer_quickstart": "SKIP",
        "expected_grade": "B",
        "cross_protocol_errors": 0,
    },
)
def gen_partial_conformance():
    signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(20)]
    proof = make_proof_surface()
    entry = make_discovery_entry()

    return {
        "signals.json": signals,
        "proof_surface.json": proof,
        "producer_entry.json": entry,
    }


# ===================================================================
# CLI
# ===================================================================

def write_scenario(output_dir, scenario_name):
    """Generate and write a single scenario."""
    if scenario_name not in SCENARIOS:
        print(f"Unknown scenario: {scenario_name}", file=sys.stderr)
        print(f"Available: {', '.join(sorted(SCENARIOS.keys()))}", file=sys.stderr)
        sys.exit(1)

    info = SCENARIOS[scenario_name]
    scenario_dir = os.path.join(output_dir, scenario_name)
    os.makedirs(scenario_dir, exist_ok=True)

    # Generate artifacts
    artifacts = info["generator"]()

    # Write artifact files
    for filename, data in artifacts.items():
        path = os.path.join(scenario_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    # Write expected outcomes
    expected_path = os.path.join(scenario_dir, "expected_outcomes.json")
    with open(expected_path, "w", encoding="utf-8") as f:
        json.dump({
            "scenario": scenario_name,
            "description": info["description"],
            "expected_outcomes": info["expected_outcomes"],
            "generator_version": __version__,
            "generated_at": NOW,
        }, f, indent=2)

    return scenario_dir


def main():
    parser = argparse.ArgumentParser(
        description="Post Fiat Synthetic Test Signal Generator v" + __version__,
    )
    parser.add_argument("output_dir", nargs="?", help="Output directory for generated scenarios")
    parser.add_argument("--scenario", help="Generate a specific scenario (default: all)")
    parser.add_argument("--list", action="store_true", help="List available scenarios")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    if args.list:
        print("Available scenarios:")
        print()
        for name, info in sorted(SCENARIOS.items()):
            expected = info["expected_outcomes"]
            grade = expected.get("expected_grade", "?")
            print(f"  {name:<30} [Grade {grade}]")
            print(f"    {info['description']}")
            print()
        sys.exit(0)

    if not args.output_dir:
        parser.error("Provide output directory or --list")

    os.makedirs(args.output_dir, exist_ok=True)

    if args.scenario:
        scenario_dir = write_scenario(args.output_dir, args.scenario)
        print(f"Generated scenario '{args.scenario}' in {scenario_dir}")
    else:
        # Generate all scenarios
        for name in sorted(SCENARIOS.keys()):
            scenario_dir = write_scenario(args.output_dir, name)
            print(f"  {name:<30} -> {scenario_dir}")
        print(f"\nGenerated {len(SCENARIOS)} scenarios in {args.output_dir}")


if __name__ == "__main__":
    main()
