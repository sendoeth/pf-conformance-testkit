#!/usr/bin/env python3
"""
Post Fiat Protocol Conformance Test Kit v1.0.0

Single-entry-point conformance validator that accepts a producer endpoint URL
or local signal/proof/routing/aggregation/discovery artifacts, validates against
all nine published protocols in dependency order, performs cross-protocol
consistency checks, and outputs conformance_report.json with per-protocol
PASS/FAIL/WARN/SKIP status, specific violations, remediation hints, and an
overall readiness grade.

Dependency order:
  1. pf-signal-schema        (foundation — all other protocols depend on valid signals)
  2. pf-routing-protocol     (depends on signal schema)
  3. pf-resolution-protocol  (depends on signal schema)
  4. pf-aggregation-protocol (depends on resolution + routing)
  5. pf-proof-protocol       (depends on resolution)
  6. pf-lifecycle-pipeline   (depends on proof protocol)
  7. pf-consumer-audit       (depends on proof + routing + aggregation)
  8. pf-discovery-protocol   (depends on resolution + proof summaries)
  9. pf-consumer-quickstart  (depends on all above)

Zero external dependencies. Pure Python 3.8+ stdlib.

Usage:
  python conformance_testkit.py /path/to/artifacts/
  python conformance_testkit.py /path/to/artifacts/ --json
  python conformance_testkit.py /path/to/artifacts/ -o report.json
  python conformance_testkit.py /path/to/artifacts/ --validate
  python conformance_testkit.py --endpoint http://producer.example.com/
"""

import json
import os
import sys
import re
import hashlib
import math
import copy
import urllib.request
import urllib.error
import datetime
import argparse
import traceback
from typing import Dict, List, Optional, Tuple, Any

__version__ = "1.0.0"
PROTOCOL_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Protocol dependency graph (index = execution order)
# ---------------------------------------------------------------------------

PROTOCOL_ORDER = [
    "signal_schema",
    "routing_protocol",
    "resolution_protocol",
    "aggregation_protocol",
    "proof_protocol",
    "lifecycle_pipeline",
    "consumer_audit",
    "discovery_protocol",
    "consumer_quickstart",
]

PROTOCOL_DISPLAY = {
    "signal_schema": "pf-signal-schema",
    "routing_protocol": "pf-routing-protocol",
    "resolution_protocol": "pf-resolution-protocol",
    "aggregation_protocol": "pf-aggregation-protocol",
    "proof_protocol": "pf-proof-protocol",
    "lifecycle_pipeline": "pf-lifecycle-pipeline",
    "consumer_audit": "pf-consumer-audit",
    "discovery_protocol": "pf-discovery-protocol",
    "consumer_quickstart": "pf-consumer-quickstart",
}

PROTOCOL_DEPENDENCIES = {
    "signal_schema": [],
    "routing_protocol": ["signal_schema"],
    "resolution_protocol": ["signal_schema"],
    "aggregation_protocol": ["resolution_protocol", "routing_protocol"],
    "proof_protocol": ["resolution_protocol"],
    "lifecycle_pipeline": ["proof_protocol"],
    "consumer_audit": ["proof_protocol", "routing_protocol", "aggregation_protocol"],
    "discovery_protocol": ["resolution_protocol", "proof_protocol"],
    "consumer_quickstart": [
        "signal_schema", "routing_protocol", "resolution_protocol",
        "aggregation_protocol", "proof_protocol", "lifecycle_pipeline",
        "consumer_audit", "discovery_protocol",
    ],
}

# ---------------------------------------------------------------------------
# Readiness grade thresholds
# ---------------------------------------------------------------------------

GRADE_THRESHOLDS = {
    "A": 0.90,  # >=90% protocols PASS, zero FAIL
    "B": 0.75,  # >=75% protocols PASS, at most 1 FAIL
    "C": 0.55,  # >=55% protocols PASS
    "D": 0.35,  # >=35% protocols PASS
    "F": 0.00,  # below 35%
}

# Weights per protocol for composite scoring
PROTOCOL_WEIGHTS = {
    "signal_schema": 0.20,       # foundation
    "routing_protocol": 0.10,
    "resolution_protocol": 0.15,
    "aggregation_protocol": 0.08,
    "proof_protocol": 0.15,
    "lifecycle_pipeline": 0.07,
    "consumer_audit": 0.10,
    "discovery_protocol": 0.07,
    "consumer_quickstart": 0.08,
}

STATUS_SCORES = {
    "PASS": 1.0,
    "WARN": 0.6,
    "SKIP": 0.3,
    "FAIL": 0.0,
}


# ---------------------------------------------------------------------------
# Artifact file mapping
# ---------------------------------------------------------------------------

ARTIFACT_FILES = {
    "signals": ["signals.json", "signal_batch.json", "signal_log.json"],
    "proof_surface": ["proof_surface.json", "proof_maintenance.json", "proof_report.json"],
    "routing_config": ["routing_policy.json", "routing_config.json"],
    "routing_report": ["routing_report.json"],
    "resolution_report": ["resolution_report.json"],
    "aggregation_report": ["aggregation_report.json"],
    "aggregation_registry": ["reputation_registry.json", "registry.json", "producer_registry.json"],
    "lifecycle_report": ["lifecycle_report.json", "evolution_report.json"],
    "audit_report": ["audit_report.json"],
    "discovery_registry": ["discovery_registry.json", "registry.json"],
    "discovery_entry": ["producer_entry.json", "producer_config.json"],
    "quickstart_verdict": ["consumer_verdict.json"],
    "prices": ["prices.csv"],
}


# ===================================================================
# UTILITY FUNCTIONS
# ===================================================================

def iso_timestamp(dt=None):
    """Return ISO 8601 timestamp string."""
    if dt is None:
        dt = datetime.datetime.now(datetime.timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


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


def wilson_ci(successes, trials, z=1.645):
    """Wilson score confidence interval for binomial proportion."""
    if trials == 0:
        return {"point": 0.0, "lower": 0.0, "upper": 0.0, "n": 0}
    p = successes / trials
    denom = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denom
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * trials)) / trials) / denom
    return {
        "point": round(p, 6),
        "lower": round(max(0.0, center - spread), 6),
        "upper": round(min(1.0, center + spread), 6),
        "n": trials,
    }


def load_json_file(path):
    """Load JSON from file path. Returns (data, error)."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"File not found: {path}"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON in {path}: {e}"
    except Exception as e:
        return None, f"Error reading {path}: {e}"


def fetch_json_url(url, timeout=15):
    """Fetch JSON from URL. Returns (data, error)."""
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw), None
    except urllib.error.URLError as e:
        return None, f"URL error fetching {url}: {e}"
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} fetching {url}: {e.reason}"
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON from {url}: {e}"
    except Exception as e:
        return None, f"Error fetching {url}: {e}"


def find_artifact(directory, artifact_key):
    """Find artifact file in directory by checking known filenames."""
    candidates = ARTIFACT_FILES.get(artifact_key, [])
    for fname in candidates:
        path = os.path.join(directory, fname)
        if os.path.isfile(path):
            return path
    return None


def load_artifact(directory, artifact_key):
    """Load artifact from directory. Returns (data, path, error)."""
    path = find_artifact(directory, artifact_key)
    if path is None:
        return None, None, f"No {artifact_key} artifact found"
    data, err = load_json_file(path)
    return data, path, err


# ===================================================================
# VIOLATION RECORD
# ===================================================================

class Violation:
    """Single conformance violation with JSON path, description, and remediation."""

    def __init__(self, protocol, path, message, remediation=None, severity="ERROR"):
        self.protocol = protocol
        self.path = path            # JSON path e.g. "$.signals[0].confidence"
        self.message = message
        self.remediation = remediation or ""
        self.severity = severity    # ERROR, WARNING, INFO

    def to_dict(self):
        return {
            "protocol": self.protocol,
            "json_path": self.path,
            "message": self.message,
            "remediation": self.remediation,
            "severity": self.severity,
        }


# ===================================================================
# PER-PROTOCOL VALIDATORS
# ===================================================================

class SignalSchemaValidator:
    """Validates signals against pf-signal-schema v1.0.0."""

    REQUIRED_FIELDS = [
        "signal_id", "producer_id", "timestamp", "symbol",
        "direction", "confidence", "horizon_hours", "action", "schema_version",
    ]
    VALID_DIRECTIONS = {"bullish", "bearish"}
    VALID_ACTIONS = {"EXECUTE", "WITHHOLD", "INVERT"}
    VALID_REGIMES = {"SYSTEMIC", "NEUTRAL", "DIVERGENCE", "EARNINGS", "UNKNOWN"}
    VALID_DECISIONS = {"NO_TRADE", "EXECUTE", "MONITOR"}
    VALID_SEVERITIES = {"NONE", "MILD", "MODERATE", "SEVERE"}

    def validate_signal(self, signal, index=0):
        """Validate a single signal. Returns list of Violations."""
        violations = []
        prefix = f"$.signals[{index}]"

        # Required fields
        for field in self.REQUIRED_FIELDS:
            if field not in signal or signal[field] is None:
                violations.append(Violation(
                    "signal_schema", f"{prefix}.{field}",
                    f"Required field '{field}' is missing",
                    f"Add '{field}' to the signal object. See pf-signal-schema README for field specifications.",
                ))

        # Type and range checks (only if field present)
        if "direction" in signal and signal["direction"] not in self.VALID_DIRECTIONS:
            violations.append(Violation(
                "signal_schema", f"{prefix}.direction",
                f"Invalid direction '{signal['direction']}'. Must be 'bullish' or 'bearish'",
                "Set direction to 'bullish' or 'bearish'.",
            ))

        if "action" in signal and signal["action"] not in self.VALID_ACTIONS:
            violations.append(Violation(
                "signal_schema", f"{prefix}.action",
                f"Invalid action '{signal['action']}'. Must be EXECUTE, WITHHOLD, or INVERT",
                "Set action to one of: EXECUTE, WITHHOLD, INVERT.",
            ))

        if "confidence" in signal:
            conf = signal["confidence"]
            if not isinstance(conf, (int, float)):
                violations.append(Violation(
                    "signal_schema", f"{prefix}.confidence",
                    f"Confidence must be a number, got {type(conf).__name__}",
                    "Set confidence to a float between 0.0 and 1.0.",
                ))
            elif conf < 0.0 or conf > 1.0:
                violations.append(Violation(
                    "signal_schema", f"{prefix}.confidence",
                    f"Confidence {conf} out of range [0.0, 1.0]",
                    "Set confidence to a value between 0.0 and 1.0. This is a probability, not a percentage.",
                ))

        if "horizon_hours" in signal:
            hh = signal["horizon_hours"]
            if not isinstance(hh, int):
                violations.append(Violation(
                    "signal_schema", f"{prefix}.horizon_hours",
                    f"horizon_hours must be an integer, got {type(hh).__name__}",
                    "Set horizon_hours to an integer between 1 and 8760.",
                ))
            elif hh < 1 or hh > 8760:
                violations.append(Violation(
                    "signal_schema", f"{prefix}.horizon_hours",
                    f"horizon_hours {hh} out of range [1, 8760]",
                    "Set horizon_hours between 1 (1 hour) and 8760 (1 year).",
                ))

        if "symbol" in signal:
            sym = signal["symbol"]
            if not isinstance(sym, str) or not re.match(r"^[A-Z0-9]+$", sym):
                violations.append(Violation(
                    "signal_schema", f"{prefix}.symbol",
                    f"Symbol '{sym}' must be uppercase alphanumeric (e.g., BTC, ETH)",
                    "Use uppercase alphanumeric symbols only (regex: ^[A-Z0-9]+$).",
                ))

        if "timestamp" in signal:
            ts = signal["timestamp"]
            if not isinstance(ts, str):
                violations.append(Violation(
                    "signal_schema", f"{prefix}.timestamp",
                    f"Timestamp must be an ISO 8601 string, got {type(ts).__name__}",
                    "Use ISO 8601 format: 2026-03-30T12:00:00Z",
                ))
            else:
                try:
                    if ts.endswith("Z"):
                        datetime.datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    else:
                        datetime.datetime.fromisoformat(ts)
                except ValueError:
                    violations.append(Violation(
                        "signal_schema", f"{prefix}.timestamp",
                        f"Invalid ISO 8601 timestamp: '{ts}'",
                        "Use ISO 8601 format with timezone: 2026-03-30T12:00:00Z or 2026-03-30T12:00:00+00:00",
                    ))

        # Conditional: INVERT requires weak_symbol
        if signal.get("action") == "INVERT":
            if "weak_symbol" not in signal or not isinstance(signal.get("weak_symbol"), dict):
                violations.append(Violation(
                    "signal_schema", f"{prefix}.weak_symbol",
                    "action=INVERT requires weak_symbol metadata",
                    "Add weak_symbol object with weakness_score, severity, original_direction, and inversion_p_value.",
                ))
            else:
                ws = signal["weak_symbol"]
                if "weakness_score" in ws:
                    wscore = ws["weakness_score"]
                    if isinstance(wscore, (int, float)) and (wscore < 0.0 or wscore > 1.0):
                        violations.append(Violation(
                            "signal_schema", f"{prefix}.weak_symbol.weakness_score",
                            f"weakness_score {wscore} out of range [0.0, 1.0]",
                            "Set weakness_score between 0.0 and 1.0.",
                        ))
                if "severity" in ws and ws["severity"] not in self.VALID_SEVERITIES:
                    violations.append(Violation(
                        "signal_schema", f"{prefix}.weak_symbol.severity",
                        f"Invalid severity '{ws['severity']}'",
                        "Set severity to one of: NONE, MILD, MODERATE, SEVERE.",
                    ))

        # Regime context checks (if present)
        if "regime_context" in signal and isinstance(signal.get("regime_context"), dict):
            rc = signal["regime_context"]
            if "regime_id" in rc and rc["regime_id"] not in self.VALID_REGIMES:
                violations.append(Violation(
                    "signal_schema", f"{prefix}.regime_context.regime_id",
                    f"Invalid regime_id '{rc['regime_id']}'",
                    f"Use one of: {', '.join(sorted(self.VALID_REGIMES))}.",
                ))
            if "regime_confidence" in rc:
                rconf = rc["regime_confidence"]
                if isinstance(rconf, (int, float)) and (rconf < 0.0 or rconf > 1.0):
                    violations.append(Violation(
                        "signal_schema", f"{prefix}.regime_context.regime_confidence",
                        f"regime_confidence {rconf} should be 0-1 scale, not 0-100",
                        "Use 0.0-1.0 scale for regime_confidence (e.g., 0.85 not 85).",
                        severity="WARNING",
                    ))
            if "decision" in rc and rc["decision"] not in self.VALID_DECISIONS:
                violations.append(Violation(
                    "signal_schema", f"{prefix}.regime_context.decision",
                    f"Invalid regime decision '{rc['decision']}'",
                    f"Use one of: {', '.join(sorted(self.VALID_DECISIONS))}.",
                ))

        # Attribution hash verification (if present)
        if "attribution_hash" in signal:
            expected = compute_attribution_hash(signal)
            actual = signal["attribution_hash"]
            if actual != expected:
                violations.append(Violation(
                    "signal_schema", f"{prefix}.attribution_hash",
                    f"Attribution hash mismatch: declared={actual[:16]}..., computed={expected[:16]}...",
                    "Recompute hash as SHA-256 of 'signal_id|symbol|direction|confidence|horizon_hours|timestamp'.",
                    severity="WARNING",
                ))

        # Calibration checks (if present)
        if "calibration" in signal and isinstance(signal.get("calibration"), dict):
            cal = signal["calibration"]
            if "empirical_hit_rate" in cal:
                ehr = cal["empirical_hit_rate"]
                if isinstance(ehr, (int, float)) and (ehr < 0.0 or ehr > 1.0):
                    violations.append(Violation(
                        "signal_schema", f"{prefix}.calibration.empirical_hit_rate",
                        f"empirical_hit_rate {ehr} out of range [0.0, 1.0]",
                        "Use 0.0-1.0 scale.",
                    ))
            if "brier_score" in cal:
                bs = cal["brier_score"]
                if isinstance(bs, (int, float)) and (bs < 0.0 or bs > 1.0):
                    violations.append(Violation(
                        "signal_schema", f"{prefix}.calibration.brier_score",
                        f"brier_score {bs} out of range [0.0, 1.0]",
                        "Brier score is bounded [0, 1]. 0.25 = random baseline.",
                    ))

        return violations

    def detect_conformance_level(self, signal):
        """Detect signal conformance level: MINIMAL, STANDARD, FULL, or INCOMPLETE."""
        # Check required fields
        for field in self.REQUIRED_FIELDS:
            if field not in signal or signal[field] is None:
                return "INCOMPLETE"
        # Check for STANDARD (has regime_context)
        has_regime = "regime_context" in signal and isinstance(signal.get("regime_context"), dict)
        # Check for FULL (has attribution_hash and calibration)
        has_hash = "attribution_hash" in signal
        has_cal = "calibration" in signal and isinstance(signal.get("calibration"), dict)
        if has_regime and has_hash and has_cal:
            return "FULL"
        elif has_regime:
            return "STANDARD"
        return "MINIMAL"

    def validate(self, artifacts):
        """Validate all signals. Returns (status, violations, details)."""
        signals = artifacts.get("signals")
        if signals is None:
            return "SKIP", [], {"reason": "No signals artifact provided"}

        if not isinstance(signals, list):
            # Could be a batch
            if isinstance(signals, dict) and "signals" in signals:
                batch = signals
                signals = batch.get("signals", [])
                # Validate batch-level fields
                if "signal_count" in batch and batch["signal_count"] != len(signals):
                    return "FAIL", [Violation(
                        "signal_schema", "$.signal_count",
                        f"Batch signal_count ({batch['signal_count']}) != actual count ({len(signals)})",
                        "Set signal_count to match the number of signals in the batch array.",
                    )], {"n_signals": len(signals)}
            else:
                return "FAIL", [Violation(
                    "signal_schema", "$",
                    "Signals must be a JSON array or a batch object with 'signals' array",
                    "Provide signals as a JSON array of signal objects.",
                )], {}

        if len(signals) == 0:
            return "WARN", [Violation(
                "signal_schema", "$.signals",
                "Empty signal list",
                "Provide at least one signal for conformance testing.",
                severity="WARNING",
            )], {"n_signals": 0}

        all_violations = []
        levels = {"MINIMAL": 0, "STANDARD": 0, "FULL": 0, "INCOMPLETE": 0}
        n_passed = 0
        signal_ids = set()
        duplicate_ids = []

        for i, sig in enumerate(signals):
            # Check duplicate IDs
            sid = sig.get("signal_id")
            if sid is not None:
                if sid in signal_ids:
                    duplicate_ids.append(sid)
                signal_ids.add(sid)

            vs = self.validate_signal(sig, i)
            errors = [v for v in vs if v.severity == "ERROR"]
            all_violations.extend(vs)
            level = self.detect_conformance_level(sig)
            levels[level] += 1
            if len(errors) == 0:
                n_passed += 1

        if duplicate_ids:
            for did in duplicate_ids[:5]:
                all_violations.append(Violation(
                    "signal_schema", "$.signals[*].signal_id",
                    f"Duplicate signal_id: '{did}'",
                    "Each signal must have a unique signal_id.",
                    severity="WARNING",
                ))

        pass_rate = n_passed / len(signals) if signals else 0.0
        details = {
            "n_signals": len(signals),
            "n_passed": n_passed,
            "n_failed": len(signals) - n_passed,
            "pass_rate": round(pass_rate, 4),
            "level_distribution": levels,
            "duplicate_signal_ids": len(duplicate_ids),
        }

        errors_only = [v for v in all_violations if v.severity == "ERROR"]
        if len(errors_only) == 0:
            return "PASS", all_violations, details
        elif pass_rate >= 0.90:
            return "WARN", all_violations, details
        else:
            return "FAIL", all_violations, details


class RoutingProtocolValidator:
    """Validates routing config and reports against pf-routing-protocol."""

    VALID_GATES = {"regime_gate", "duration_gate", "confidence_gate", "voi_gate", "weak_symbol_gate"}
    VALID_ACTIONS = {"EMIT", "WITHHOLD", "INVERT"}
    VALID_POLICIES = {"NONE", "INVERT", "EXCLUDE", "REDUCE_WEIGHT"}

    def validate_config(self, config):
        """Validate routing policy config. Returns list of Violations."""
        violations = []
        if not isinstance(config, dict):
            violations.append(Violation(
                "routing_protocol", "$.routing_config",
                "Routing config must be a JSON object",
                "Provide routing_policy.json as a JSON object with gates and symbols.",
            ))
            return violations

        # Check gates section
        gates = config.get("gates", {})
        if not isinstance(gates, dict):
            violations.append(Violation(
                "routing_protocol", "$.gates",
                "Gates must be a JSON object",
                "Add gates object with regime_gate, duration_gate, etc.",
            ))

        # Check regime gate
        if "regime_gate" in gates:
            rg = gates["regime_gate"]
            if "allowed_regimes" in rg:
                for r in rg["allowed_regimes"]:
                    if r not in SignalSchemaValidator.VALID_REGIMES:
                        violations.append(Violation(
                            "routing_protocol", "$.gates.regime_gate.allowed_regimes",
                            f"Invalid regime '{r}' in allowed_regimes",
                            f"Use: {', '.join(sorted(SignalSchemaValidator.VALID_REGIMES))}.",
                        ))

        # Check confidence gate
        if "confidence_gate" in gates:
            cg = gates["confidence_gate"]
            mc = cg.get("default_min_confidence")
            if mc is not None and isinstance(mc, (int, float)) and (mc < 0.0 or mc > 1.0):
                violations.append(Violation(
                    "routing_protocol", "$.gates.confidence_gate.default_min_confidence",
                    f"default_min_confidence {mc} out of range [0.0, 1.0]",
                    "Set min_confidence between 0.0 and 1.0.",
                ))

        # Check duration gate
        if "duration_gate" in gates:
            dg = gates["duration_gate"]
            dmd = dg.get("default_min_days")
            if dmd is not None and isinstance(dmd, (int, float)) and dmd < 0:
                violations.append(Violation(
                    "routing_protocol", "$.gates.duration_gate.default_min_days",
                    f"default_min_days {dmd} cannot be negative",
                    "Set default_min_days to a non-negative integer.",
                ))

        # Check symbols section
        symbols = config.get("symbols", {})
        if isinstance(symbols, dict):
            for sym, sconf in symbols.items():
                if not re.match(r"^[A-Z0-9]+$", sym):
                    violations.append(Violation(
                        "routing_protocol", f"$.symbols.{sym}",
                        f"Symbol key '{sym}' must be uppercase alphanumeric",
                        "Use uppercase symbols like BTC, ETH, SOL.",
                    ))
                if isinstance(sconf, dict):
                    wsp = sconf.get("weak_symbol_policy")
                    if wsp is not None and wsp not in self.VALID_POLICIES:
                        violations.append(Violation(
                            "routing_protocol", f"$.symbols.{sym}.weak_symbol_policy",
                            f"Invalid weak_symbol_policy '{wsp}'",
                            f"Use one of: {', '.join(sorted(self.VALID_POLICIES))}.",
                        ))
                    acc = sconf.get("accuracy")
                    if acc is not None and isinstance(acc, (int, float)) and (acc < 0.0 or acc > 1.0):
                        violations.append(Violation(
                            "routing_protocol", f"$.symbols.{sym}.accuracy",
                            f"Accuracy {acc} out of range [0.0, 1.0]",
                            "Set accuracy between 0.0 and 1.0.",
                        ))

        return violations

    def validate_report(self, report):
        """Validate routing report output. Returns list of Violations."""
        violations = []
        if not isinstance(report, dict):
            violations.append(Violation(
                "routing_protocol", "$.routing_report",
                "Routing report must be a JSON object",
                "Generate routing report using preflight_filter.py.",
            ))
            return violations

        # Check summary math
        summary = report.get("summary", {})
        if isinstance(summary, dict):
            te = summary.get("total_emit", 0)
            tw = summary.get("total_withhold", 0)
            ti = summary.get("total_invert", 0)
            total = summary.get("total_input", 0)
            if total > 0 and (te + tw + ti) != total:
                violations.append(Violation(
                    "routing_protocol", "$.summary",
                    f"Routing counts inconsistent: emit({te}) + withhold({tw}) + invert({ti}) = {te+tw+ti} != total_input({total})",
                    "Ensure total_emit + total_withhold + total_invert == total_input.",
                ))
            if total > 0:
                expected_fr = tw / total
                actual_fr = summary.get("filter_rate", -1)
                if isinstance(actual_fr, (int, float)) and abs(actual_fr - expected_fr) > 0.001:
                    violations.append(Violation(
                        "routing_protocol", "$.summary.filter_rate",
                        f"filter_rate {actual_fr} != total_withhold/total_input ({round(expected_fr, 4)})",
                        "Recompute filter_rate as total_withhold / total_input.",
                    ))

        # Check decisions
        decisions = report.get("decisions", [])
        if isinstance(decisions, list):
            for i, dec in enumerate(decisions):
                action = dec.get("action")
                if action not in self.VALID_ACTIONS:
                    violations.append(Violation(
                        "routing_protocol", f"$.decisions[{i}].action",
                        f"Invalid action '{action}'",
                        "Set action to EMIT, WITHHOLD, or INVERT.",
                    ))

        return violations

    def validate(self, artifacts):
        """Validate routing artifacts. Returns (status, violations, details)."""
        config = artifacts.get("routing_config")
        report = artifacts.get("routing_report")

        if config is None and report is None:
            return "SKIP", [], {"reason": "No routing artifacts provided"}

        all_violations = []
        details = {}

        if config is not None:
            config_vs = self.validate_config(config)
            all_violations.extend(config_vs)
            details["config_violations"] = len(config_vs)

        if report is not None:
            report_vs = self.validate_report(report)
            all_violations.extend(report_vs)
            details["report_violations"] = len(report_vs)

        errors = [v for v in all_violations if v.severity == "ERROR"]
        if len(errors) == 0:
            if len(all_violations) > 0:
                return "WARN", all_violations, details
            return "PASS", all_violations, details
        return "FAIL", all_violations, details


class ResolutionProtocolValidator:
    """Validates resolution reports against pf-resolution-protocol."""

    REQUIRED_REPORT_FIELDS = ["meta", "signal_summary", "overall", "per_symbol", "karma", "protocol_version"]
    VALID_GRADES = {"A", "B", "C", "D", "F"}

    def validate_report(self, report):
        """Validate resolution report. Returns list of Violations."""
        violations = []
        if not isinstance(report, dict):
            violations.append(Violation(
                "resolution_protocol", "$.resolution_report",
                "Resolution report must be a JSON object",
                "Generate report using resolve_signals.py.",
            ))
            return violations

        for field in self.REQUIRED_REPORT_FIELDS:
            if field not in report:
                violations.append(Violation(
                    "resolution_protocol", f"$.{field}",
                    f"Required field '{field}' missing from resolution report",
                    f"Add '{field}' to resolution report. See pf-resolution-protocol README.",
                ))

        # Brier decomposition identity check
        overall = report.get("overall", {})
        if isinstance(overall, dict):
            bs = overall.get("brier_score")
            rel = overall.get("reliability")
            res = overall.get("resolution")
            unc = overall.get("uncertainty")
            if all(isinstance(v, (int, float)) for v in [bs, rel, res, unc] if v is not None):
                if bs is not None and rel is not None and res is not None and unc is not None:
                    expected = rel - res + unc
                    if abs(bs - expected) > 0.005:
                        violations.append(Violation(
                            "resolution_protocol", "$.overall",
                            f"Brier identity violated: brier_score({bs:.4f}) != reliability({rel:.4f}) - resolution({res:.4f}) + uncertainty({unc:.4f}) = {expected:.4f}",
                            "Recompute Brier decomposition. Identity: brier = reliability - resolution + uncertainty.",
                        ))

            # Accuracy CI
            accuracy = overall.get("accuracy", {})
            if isinstance(accuracy, dict):
                pt = accuracy.get("point")
                lo = accuracy.get("lower")
                hi = accuracy.get("upper")
                if all(isinstance(v, (int, float)) for v in [pt, lo, hi] if v is not None):
                    if pt is not None and lo is not None and hi is not None:
                        if lo > pt or pt > hi:
                            violations.append(Violation(
                                "resolution_protocol", "$.overall.accuracy",
                                f"Wilson CI ordering violation: lower({lo}) <= point({pt}) <= upper({hi}) failed",
                                "Recompute Wilson confidence interval. Bounds must satisfy lower <= point <= upper.",
                            ))

        # Reputation check
        reputation = report.get("reputation", {})
        if isinstance(reputation, dict):
            score = reputation.get("composite_score")
            if isinstance(score, (int, float)) and (score < 0.0 or score > 1.0):
                violations.append(Violation(
                    "resolution_protocol", "$.reputation.composite_score",
                    f"Reputation score {score} out of range [0.0, 1.0]",
                    "Composite score must be between 0.0 and 1.0.",
                ))
            grade = reputation.get("grade")
            if grade is not None and grade not in self.VALID_GRADES:
                violations.append(Violation(
                    "resolution_protocol", "$.reputation.grade",
                    f"Invalid grade '{grade}'",
                    f"Use one of: {', '.join(sorted(self.VALID_GRADES))}.",
                ))
            # Grade-score consistency
            if isinstance(score, (int, float)) and grade is not None and grade in self.VALID_GRADES:
                expected_grade = self._score_to_grade(score)
                if grade != expected_grade:
                    violations.append(Violation(
                        "resolution_protocol", "$.reputation",
                        f"Grade '{grade}' inconsistent with score {score:.4f} (expected '{expected_grade}')",
                        "Grade thresholds: A >= 0.80, B >= 0.65, C >= 0.50, D >= 0.35, F < 0.35.",
                        severity="WARNING",
                    ))

        # Signal summary consistency
        ss = report.get("signal_summary", {})
        if isinstance(ss, dict):
            total = ss.get("total_signals", 0)
            resolved = ss.get("total_resolved", 0)
            unresolved = ss.get("total_unresolved", 0)
            if total > 0 and (resolved + unresolved) != total:
                violations.append(Violation(
                    "resolution_protocol", "$.signal_summary",
                    f"Signal counts inconsistent: resolved({resolved}) + unresolved({unresolved}) != total({total})",
                    "Ensure total_resolved + total_unresolved == total_signals.",
                ))

        # Karma check
        karma = report.get("karma", {})
        if isinstance(karma, dict):
            ck = karma.get("cumulative_karma")
            mk = karma.get("mean_karma")
            if isinstance(ck, (int, float)) and isinstance(mk, (int, float)):
                total_resolved = ss.get("total_resolved", 0) if isinstance(ss, dict) else 0
                if total_resolved > 0:
                    expected_mean = ck / total_resolved
                    if abs(mk - expected_mean) > 0.01:
                        violations.append(Violation(
                            "resolution_protocol", "$.karma",
                            f"mean_karma({mk:.4f}) != cumulative_karma({ck:.4f}) / n_resolved({total_resolved}) = {expected_mean:.4f}",
                            "Recompute mean_karma as cumulative_karma / total_resolved.",
                            severity="WARNING",
                        ))

        return violations

    def _score_to_grade(self, score):
        if score >= 0.80:
            return "A"
        elif score >= 0.65:
            return "B"
        elif score >= 0.50:
            return "C"
        elif score >= 0.35:
            return "D"
        return "F"

    def validate(self, artifacts):
        """Validate resolution artifacts. Returns (status, violations, details)."""
        report = artifacts.get("resolution_report")
        if report is None:
            return "SKIP", [], {"reason": "No resolution report provided"}

        violations = self.validate_report(report)
        details = {"n_violations": len(violations)}

        errors = [v for v in violations if v.severity == "ERROR"]
        if len(errors) == 0:
            if len(violations) > 0:
                return "WARN", violations, details
            return "PASS", violations, details
        return "FAIL", violations, details


class AggregationProtocolValidator:
    """Validates aggregation reports against pf-aggregation-protocol."""

    VALID_ACTIONS = {"EMIT", "WITHHOLD", "INVERT", "CONFLICT"}
    VALID_DIRECTIONS = {"bullish", "bearish", "undetermined"}
    VALID_LEVELS = {"LOW", "MODERATE", "HIGH", "EXTREME"}

    def validate_report(self, report):
        """Validate aggregation report. Returns list of Violations."""
        violations = []
        if not isinstance(report, dict):
            violations.append(Violation(
                "aggregation_protocol", "$.aggregation_report",
                "Aggregation report must be a JSON object",
                "Generate report using aggregate_signals.py.",
            ))
            return violations

        # Summary math
        summary = report.get("summary", {})
        if isinstance(summary, dict):
            total = summary.get("total_symbols", 0)
            te = summary.get("total_emit", 0)
            tw = summary.get("total_withhold", 0)
            ti = summary.get("total_invert", 0)
            tc = summary.get("total_conflict", 0)
            if total > 0 and (te + tw + ti + tc) != total:
                violations.append(Violation(
                    "aggregation_protocol", "$.summary",
                    f"Summary counts inconsistent: emit({te})+withhold({tw})+invert({ti})+conflict({tc}) = {te+tw+ti+tc} != total({total})",
                    "Ensure action counts sum to total_symbols.",
                ))

            # HHI range
            pwd = summary.get("producer_weight_distribution", {})
            if isinstance(pwd, dict):
                hhi = pwd.get("hhi")
                if isinstance(hhi, (int, float)) and (hhi < 0.0 or hhi > 1.0):
                    violations.append(Violation(
                        "aggregation_protocol", "$.summary.producer_weight_distribution.hhi",
                        f"HHI {hhi} out of range [0.0, 1.0]",
                        "HHI ranges from 1/N (equal weights) to 1.0 (monopoly).",
                    ))

        # Decisions
        decisions = report.get("decisions", [])
        if isinstance(decisions, list):
            for i, dec in enumerate(decisions):
                action = dec.get("consensus_action")
                if action not in self.VALID_ACTIONS:
                    violations.append(Violation(
                        "aggregation_protocol", f"$.decisions[{i}].consensus_action",
                        f"Invalid consensus_action '{action}'",
                        f"Use one of: {', '.join(sorted(self.VALID_ACTIONS))}.",
                    ))

                direction = dec.get("consensus_direction")
                if direction is not None and direction not in self.VALID_DIRECTIONS:
                    violations.append(Violation(
                        "aggregation_protocol", f"$.decisions[{i}].consensus_direction",
                        f"Invalid consensus_direction '{direction}'",
                        f"Use one of: {', '.join(sorted(self.VALID_DIRECTIONS))}.",
                    ))

                # Disagreement index
                disagree = dec.get("disagreement", {})
                if isinstance(disagree, dict):
                    idx = disagree.get("index")
                    level = disagree.get("level")
                    if isinstance(idx, (int, float)) and level is not None:
                        expected_level = self._index_to_level(idx)
                        if level != expected_level:
                            violations.append(Violation(
                                "aggregation_protocol",
                                f"$.decisions[{i}].disagreement",
                                f"Disagreement level '{level}' inconsistent with index {idx:.4f} (expected '{expected_level}')",
                                "Thresholds: <0.15=LOW, <0.40=MODERATE, <0.70=HIGH, >=0.70=EXTREME.",
                                severity="WARNING",
                            ))

        return violations

    def _index_to_level(self, idx):
        if idx < 0.15:
            return "LOW"
        elif idx < 0.40:
            return "MODERATE"
        elif idx < 0.70:
            return "HIGH"
        return "EXTREME"

    def validate(self, artifacts):
        """Validate aggregation artifacts. Returns (status, violations, details)."""
        report = artifacts.get("aggregation_report")
        registry = artifacts.get("aggregation_registry")

        if report is None and registry is None:
            return "SKIP", [], {"reason": "No aggregation artifacts provided"}

        violations = []
        details = {}

        if report is not None:
            vs = self.validate_report(report)
            violations.extend(vs)
            details["report_violations"] = len(vs)

        if registry is not None:
            # Basic registry validation
            if isinstance(registry, dict):
                producers = registry.get("producers", registry)
                if isinstance(producers, dict):
                    details["n_producers"] = len(producers)
                    for pid, entry in producers.items():
                        if isinstance(entry, dict):
                            score = entry.get("reputation_score")
                            if isinstance(score, (int, float)) and (score < 0.0 or score > 1.0):
                                violations.append(Violation(
                                    "aggregation_protocol",
                                    f"$.registry.{pid}.reputation_score",
                                    f"reputation_score {score} out of range [0.0, 1.0]",
                                    "Set reputation_score between 0.0 and 1.0.",
                                ))

        errors = [v for v in violations if v.severity == "ERROR"]
        if len(errors) == 0:
            if len(violations) > 0:
                return "WARN", violations, details
            return "PASS", violations, details
        return "FAIL", violations, details


class ProofProtocolValidator:
    """Validates proof surfaces against pf-proof-protocol."""

    VALID_FRESHNESS = {"LIVE", "RECENT", "STALE", "EXPIRED"}
    VALID_DRIFT = {"STABLE", "WATCH", "DRIFTING", "DEGRADED"}
    VALID_GRADES = {"A", "B", "C", "D", "F"}
    VALID_WINDOWS = {"7d", "14d", "30d", "all_time"}

    def validate_report(self, proof):
        """Validate proof surface. Returns list of Violations."""
        violations = []
        if not isinstance(proof, dict):
            violations.append(Violation(
                "proof_protocol", "$.proof_surface",
                "Proof surface must be a JSON object",
                "Generate proof using maintain_proof.py.",
            ))
            return violations

        # Freshness
        fm = proof.get("freshness_metadata", {})
        if isinstance(fm, dict):
            grade = fm.get("freshness_grade")
            if grade is not None and grade not in self.VALID_FRESHNESS:
                violations.append(Violation(
                    "proof_protocol", "$.freshness_metadata.freshness_grade",
                    f"Invalid freshness_grade '{grade}'",
                    f"Use one of: {', '.join(sorted(self.VALID_FRESHNESS))}.",
                ))
            age = fm.get("age_hours")
            threshold = fm.get("staleness_threshold_hours", 24)
            if isinstance(age, (int, float)) and isinstance(threshold, (int, float)):
                expected_grade = self._age_to_freshness(age, threshold)
                if grade is not None and grade != expected_grade:
                    violations.append(Violation(
                        "proof_protocol", "$.freshness_metadata",
                        f"freshness_grade '{grade}' inconsistent with age_hours={age}, threshold={threshold} (expected '{expected_grade}')",
                        "LIVE: age <= threshold, RECENT: <= 2x, STALE: <= 4x, EXPIRED: > 4x.",
                        severity="WARNING",
                    ))

        # Drift
        cusum = proof.get("cusum_state", proof.get("drift", {}))
        if isinstance(cusum, dict):
            ds = cusum.get("drift_status")
            if ds is not None and ds not in self.VALID_DRIFT:
                violations.append(Violation(
                    "proof_protocol", "$.cusum_state.drift_status",
                    f"Invalid drift_status '{ds}'",
                    f"Use one of: {', '.join(sorted(self.VALID_DRIFT))}.",
                ))
            cp = cusum.get("cusum_pos")
            cn = cusum.get("cusum_neg")
            if isinstance(cp, (int, float)) and cp < 0:
                violations.append(Violation(
                    "proof_protocol", "$.cusum_state.cusum_pos",
                    f"cusum_pos ({cp}) cannot be negative",
                    "CUSUM statistics are non-negative. Check CUSUM update logic.",
                ))
            if isinstance(cn, (int, float)) and cn < 0:
                violations.append(Violation(
                    "proof_protocol", "$.cusum_state.cusum_neg",
                    f"cusum_neg ({cn}) cannot be negative",
                    "CUSUM statistics are non-negative. Check CUSUM update logic.",
                ))

        # Rolling windows
        windows = proof.get("rolling_windows", [])
        if isinstance(windows, list):
            prev_n = 0
            for i, w in enumerate(windows):
                if not isinstance(w, dict):
                    continue
                wid = w.get("window_id", "")
                n_res = w.get("n_resolved", 0)

                # Wilson CI ordering
                accuracy = w.get("accuracy", {})
                if isinstance(accuracy, dict):
                    pt = accuracy.get("point")
                    lo = accuracy.get("lower")
                    hi = accuracy.get("upper")
                    if all(isinstance(v, (int, float)) for v in [pt, lo, hi] if v is not None):
                        if pt is not None and lo is not None and hi is not None:
                            if lo > pt + 0.001 or pt > hi + 0.001:
                                violations.append(Violation(
                                    "proof_protocol",
                                    f"$.rolling_windows[{i}].accuracy",
                                    f"Wilson CI ordering violation in {wid}: lower({lo}) <= point({pt}) <= upper({hi})",
                                    "Recompute Wilson score CI. Bounds must satisfy lower <= point <= upper.",
                                ))

        # Reputation
        rep = proof.get("reputation", {})
        if isinstance(rep, dict):
            score = rep.get("score")
            if isinstance(score, (int, float)) and (score < 0.0 or score > 1.0):
                violations.append(Violation(
                    "proof_protocol", "$.reputation.score",
                    f"Reputation score {score} out of range [0.0, 1.0]",
                    "Composite reputation must be between 0.0 and 1.0.",
                ))
            grade = rep.get("grade")
            if grade is not None and grade not in self.VALID_GRADES:
                violations.append(Violation(
                    "proof_protocol", "$.reputation.grade",
                    f"Invalid reputation grade '{grade}'",
                    f"Use one of: {', '.join(sorted(self.VALID_GRADES))}.",
                ))

        # Snapshot monotonicity
        snap = proof.get("snapshot_metadata", {})
        if isinstance(snap, dict):
            sv = snap.get("snapshot_version")
            if isinstance(sv, (int, float)) and sv < 1:
                violations.append(Violation(
                    "proof_protocol", "$.snapshot_metadata.snapshot_version",
                    f"snapshot_version ({sv}) must be >= 1",
                    "Snapshot version is a monotonically increasing counter starting at 1.",
                ))

        return violations

    def _age_to_freshness(self, age, threshold):
        if age <= threshold:
            return "LIVE"
        elif age <= threshold * 2:
            return "RECENT"
        elif age <= threshold * 4:
            return "STALE"
        return "EXPIRED"

    def validate(self, artifacts):
        """Validate proof artifacts. Returns (status, violations, details)."""
        proof = artifacts.get("proof_surface")
        if proof is None:
            return "SKIP", [], {"reason": "No proof surface provided"}

        violations = self.validate_report(proof)
        details = {"n_violations": len(violations)}

        # Extract key metrics for details
        fm = proof.get("freshness_metadata", {})
        if isinstance(fm, dict):
            details["freshness_grade"] = fm.get("freshness_grade")
        cusum = proof.get("cusum_state", proof.get("drift", {}))
        if isinstance(cusum, dict):
            details["drift_status"] = cusum.get("drift_status")

        errors = [v for v in violations if v.severity == "ERROR"]
        if len(errors) == 0:
            if len(violations) > 0:
                return "WARN", violations, details
            return "PASS", violations, details
        return "FAIL", violations, details


class LifecyclePipelineValidator:
    """Validates lifecycle pipeline outputs against pf-lifecycle-pipeline."""

    VALID_STAGES = {"LOAD", "VALIDATE", "FETCH_PRICES", "MAINTAIN_PROOF", "VALIDATE_REPORT", "PUBLISH"}

    def validate_report(self, report):
        """Validate lifecycle/evolution report. Returns list of Violations."""
        violations = []
        if not isinstance(report, dict):
            violations.append(Violation(
                "lifecycle_pipeline", "$.lifecycle_report",
                "Lifecycle report must be a JSON object",
                "Generate report using proof_pipeline.py or evolution_report.py.",
            ))
            return violations

        # Pipeline stages
        meta = report.get("pipeline_meta", report.get("meta", {}))
        if isinstance(meta, dict):
            stages = meta.get("stages", [])
            if isinstance(stages, list):
                stage_names = set()
                for i, s in enumerate(stages):
                    if isinstance(s, dict):
                        name = s.get("stage", s.get("name"))
                        if name:
                            stage_names.add(name)
                        status = s.get("status")
                        if status is not None and status not in {"PASS", "FAIL", "SKIP", "WARN"}:
                            violations.append(Violation(
                                "lifecycle_pipeline", f"$.pipeline_meta.stages[{i}].status",
                                f"Invalid stage status '{status}'",
                                "Stage status must be PASS, FAIL, SKIP, or WARN.",
                            ))

        # Content hash
        ch = report.get("content_hash")
        if ch is not None:
            if not isinstance(ch, str) or len(ch) < 8:
                violations.append(Violation(
                    "lifecycle_pipeline", "$.content_hash",
                    f"content_hash must be a hex string (got length {len(ch) if isinstance(ch, str) else 'non-string'})",
                    "content_hash should be a truncated SHA-256 hex string.",
                    severity="WARNING",
                ))

        # Evolution-specific checks
        if "resolution_growth" in report:
            rg = report["resolution_growth"]
            if isinstance(rg, dict):
                nn = rg.get("n_new_resolved")
                if isinstance(nn, (int, float)) and nn < 0:
                    violations.append(Violation(
                        "lifecycle_pipeline", "$.resolution_growth.n_new_resolved",
                        f"n_new_resolved ({nn}) cannot be negative",
                        "Check resolution delta computation.",
                    ))

        return violations

    def validate(self, artifacts):
        """Validate lifecycle artifacts. Returns (status, violations, details)."""
        report = artifacts.get("lifecycle_report")
        if report is None:
            return "SKIP", [], {"reason": "No lifecycle report provided"}

        violations = self.validate_report(report)
        details = {"n_violations": len(violations)}

        errors = [v for v in violations if v.severity == "ERROR"]
        if len(errors) == 0:
            if len(violations) > 0:
                return "WARN", violations, details
            return "PASS", violations, details
        return "FAIL", violations, details


class ConsumerAuditValidator:
    """Validates audit reports against pf-consumer-audit."""

    VALID_STATUSES = {"PASS", "FAIL", "WARN", "SKIP"}
    VALID_VERDICTS = {"TRUST", "TRUST_WITH_CAUTION", "INSUFFICIENT_EVIDENCE", "DO_NOT_TRUST"}
    VALID_SEVERITIES_FINDING = {"CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"}
    VALID_BIAS = {"OVERSTATED_TRUST", "UNDERSTATED_TRUST", "INDETERMINATE", "OVERSTATED", "UNDERSTATED", "NONE", "UNKNOWN"}

    def validate_report(self, report):
        """Validate audit report. Returns list of Violations."""
        violations = []
        if not isinstance(report, dict):
            violations.append(Violation(
                "consumer_audit", "$.audit_report",
                "Audit report must be a JSON object",
                "Generate report using audit_producer.py.",
            ))
            return violations

        # Trust grade
        tg = report.get("trust_grade", {})
        if isinstance(tg, dict):
            score = tg.get("score")
            if isinstance(score, (int, float)) and (score < 0.0 or score > 1.0):
                violations.append(Violation(
                    "consumer_audit", "$.trust_grade.score",
                    f"Trust score {score} out of range [0.0, 1.0]",
                    "Trust score must be between 0.0 and 1.0.",
                ))
            verdict = tg.get("verdict")
            if verdict is not None and verdict not in self.VALID_VERDICTS:
                violations.append(Violation(
                    "consumer_audit", "$.trust_grade.verdict",
                    f"Invalid verdict '{verdict}'",
                    f"Use one of: {', '.join(sorted(self.VALID_VERDICTS))}.",
                ))

            # Component weight sum
            components = tg.get("components", {})
            if isinstance(components, dict) and len(components) > 0:
                total_weight = 0.0
                for cname, cdata in components.items():
                    if isinstance(cdata, dict):
                        w = cdata.get("weight", 0)
                        if isinstance(w, (int, float)):
                            total_weight += w
                if abs(total_weight - 1.0) > 0.01:
                    violations.append(Violation(
                        "consumer_audit", "$.trust_grade.components",
                        f"Component weights sum to {total_weight:.4f}, expected 1.0",
                        "Ensure all 7 trust component weights sum to 1.0.",
                    ))

        # Hard gate logic
        schema_section = report.get("schema_compliance", {})
        if isinstance(schema_section, dict):
            overall_status = schema_section.get("overall_status")
            if overall_status == "FAIL":
                if isinstance(tg, dict) and tg.get("verdict") not in {"DO_NOT_TRUST", None}:
                    violations.append(Violation(
                        "consumer_audit", "$.trust_grade.verdict",
                        f"Schema compliance FAIL should trigger DO_NOT_TRUST hard gate, but verdict is '{tg.get('verdict')}'",
                        "Schema failure is a hard gate — verdict must be DO_NOT_TRUST.",
                        severity="WARNING",
                    ))

        drift_section = report.get("drift_verification", {})
        if isinstance(drift_section, dict):
            ds = drift_section.get("drift_status")
            if ds == "DEGRADED":
                if isinstance(tg, dict) and tg.get("verdict") not in {"DO_NOT_TRUST", None}:
                    violations.append(Violation(
                        "consumer_audit", "$.trust_grade.verdict",
                        f"DEGRADED drift should trigger DO_NOT_TRUST hard gate, but verdict is '{tg.get('verdict')}'",
                        "DEGRADED drift is a hard gate — verdict must be DO_NOT_TRUST.",
                        severity="WARNING",
                    ))

        # Findings severity ordering
        findings = report.get("findings", [])
        if isinstance(findings, list) and len(findings) > 1:
            severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "INFO": 4}
            for i in range(len(findings) - 1):
                s1 = findings[i].get("severity", "INFO")
                s2 = findings[i + 1].get("severity", "INFO")
                if severity_order.get(s1, 5) > severity_order.get(s2, 5):
                    violations.append(Violation(
                        "consumer_audit", f"$.findings[{i}]",
                        f"Findings not sorted by severity: '{s1}' before '{s2}'",
                        "Sort findings by severity: CRITICAL > HIGH > MEDIUM > LOW > INFO.",
                        severity="WARNING",
                    ))
                    break

        # Summary check counts
        summary = report.get("summary", {})
        if isinstance(summary, dict):
            total = summary.get("total_checks", 0)
            passed = summary.get("passed", 0)
            failed = summary.get("failed", 0)
            warnings = summary.get("warnings", 0)
            skipped = summary.get("skipped", 0)
            if total > 0 and (passed + failed + warnings + skipped) != total:
                violations.append(Violation(
                    "consumer_audit", "$.summary",
                    f"Check counts inconsistent: passed({passed})+failed({failed})+warnings({warnings})+skipped({skipped}) != total({total})",
                    "Ensure check count totals are consistent.",
                ))

        return violations

    def validate(self, artifacts):
        """Validate audit artifacts. Returns (status, violations, details)."""
        report = artifacts.get("audit_report")
        if report is None:
            return "SKIP", [], {"reason": "No audit report provided"}

        violations = self.validate_report(report)
        details = {"n_violations": len(violations)}

        errors = [v for v in violations if v.severity == "ERROR"]
        if len(errors) == 0:
            if len(violations) > 0:
                return "WARN", violations, details
            return "PASS", violations, details
        return "FAIL", violations, details


class DiscoveryProtocolValidator:
    """Validates discovery artifacts against pf-discovery-protocol."""

    VALID_CAPABILITIES = {
        "crypto_signals", "equity_signals", "forex_signals",
        "regime_detection", "routing_policy", "weak_symbol_policy",
        "proof_surface", "forward_testing", "multi_symbol", "single_symbol",
    }
    VALID_LIVENESS = {"ALIVE", "DEGRADED", "UNRESPONSIVE", "UNKNOWN"}
    VALID_REGISTRARS = {"self_attestation", "registry_verified", "consumer_nominated"}
    VALID_FRESHNESS = {"LIVE", "RECENT", "STALE", "EXPIRED", "UNKNOWN"}
    VALID_DRIFT = {"STABLE", "WATCH", "DRIFTING", "DEGRADED", "UNKNOWN"}

    def validate_entry(self, entry, prefix="$.producer_entry"):
        """Validate a producer entry. Returns list of Violations."""
        violations = []
        if not isinstance(entry, dict):
            violations.append(Violation(
                "discovery_protocol", prefix,
                "Producer entry must be a JSON object",
                "See pf-discovery-protocol README for producer_entry schema.",
            ))
            return violations

        # Required fields
        required = ["producer_id", "capabilities", "symbol_coverage", "reputation_summary",
                     "supported_protocols", "liveness", "registration"]
        for field in required:
            if field not in entry:
                violations.append(Violation(
                    "discovery_protocol", f"{prefix}.{field}",
                    f"Required field '{field}' missing from producer entry",
                    f"Add '{field}' to producer entry. See pf-discovery-protocol schema.",
                ))

        # producer_id
        pid = entry.get("producer_id")
        if isinstance(pid, str) and (len(pid) < 1 or len(pid) > 128):
            violations.append(Violation(
                "discovery_protocol", f"{prefix}.producer_id",
                f"producer_id length ({len(pid)}) must be 1-128 characters",
                "Keep producer_id between 1 and 128 characters.",
            ))

        # Capabilities
        caps = entry.get("capabilities", [])
        if isinstance(caps, list):
            for cap in caps:
                if cap not in self.VALID_CAPABILITIES:
                    violations.append(Violation(
                        "discovery_protocol", f"{prefix}.capabilities",
                        f"Invalid capability '{cap}'",
                        f"Valid capabilities: {', '.join(sorted(self.VALID_CAPABILITIES))}.",
                    ))

        # Symbol coverage
        sc = entry.get("symbol_coverage", {})
        if isinstance(sc, dict):
            symbols = sc.get("symbols", [])
            if isinstance(symbols, list):
                for sym in symbols:
                    if not isinstance(sym, str) or not re.match(r"^[A-Z0-9]+$", sym):
                        violations.append(Violation(
                            "discovery_protocol", f"{prefix}.symbol_coverage.symbols",
                            f"Invalid symbol '{sym}' — must be uppercase alphanumeric",
                            "Use uppercase symbols: BTC, ETH, SOL, LINK.",
                        ))

        # Reputation summary
        rs = entry.get("reputation_summary", {})
        if isinstance(rs, dict):
            score = rs.get("score")
            if isinstance(score, (int, float)) and (score < 0.0 or score > 1.0):
                violations.append(Violation(
                    "discovery_protocol", f"{prefix}.reputation_summary.score",
                    f"reputation score {score} out of range [0.0, 1.0]",
                    "Set reputation score between 0.0 and 1.0.",
                ))

        # Liveness
        lv = entry.get("liveness", {})
        if isinstance(lv, dict):
            lg = lv.get("liveness_grade")
            if lg is not None and lg not in self.VALID_LIVENESS:
                violations.append(Violation(
                    "discovery_protocol", f"{prefix}.liveness.liveness_grade",
                    f"Invalid liveness_grade '{lg}'",
                    f"Use one of: {', '.join(sorted(self.VALID_LIVENESS))}.",
                ))
            hbi = lv.get("heartbeat_interval_seconds")
            if isinstance(hbi, (int, float)) and (hbi < 60 or hbi > 86400):
                violations.append(Violation(
                    "discovery_protocol", f"{prefix}.liveness.heartbeat_interval_seconds",
                    f"heartbeat_interval_seconds {hbi} out of range [60, 86400]",
                    "Set heartbeat interval between 60 seconds (1 min) and 86400 seconds (24 hours).",
                ))

        # Registration
        reg = entry.get("registration", {})
        if isinstance(reg, dict):
            registrar = reg.get("registrar")
            if registrar is not None and registrar not in self.VALID_REGISTRARS:
                violations.append(Violation(
                    "discovery_protocol", f"{prefix}.registration.registrar",
                    f"Invalid registrar '{registrar}'",
                    f"Use one of: {', '.join(sorted(self.VALID_REGISTRARS))}.",
                ))

        # Supported protocols — signal_schema required
        sp = entry.get("supported_protocols", {})
        if isinstance(sp, dict):
            if "signal_schema" not in sp:
                violations.append(Violation(
                    "discovery_protocol", f"{prefix}.supported_protocols.signal_schema",
                    "supported_protocols must include signal_schema version",
                    "Add signal_schema version (e.g., '1.0.0') to supported_protocols.",
                ))

        return violations

    def validate_registry(self, registry):
        """Validate discovery registry. Returns list of Violations."""
        violations = []
        if not isinstance(registry, dict):
            violations.append(Violation(
                "discovery_protocol", "$.registry",
                "Discovery registry must be a JSON object",
                "Registry should contain producers dict.",
            ))
            return violations

        producers = registry.get("producers", {})
        if isinstance(producers, dict):
            for pid, entry in producers.items():
                vs = self.validate_entry(entry, f"$.registry.producers.{pid}")
                violations.extend(vs)

        return violations

    def validate(self, artifacts):
        """Validate discovery artifacts. Returns (status, violations, details)."""
        entry = artifacts.get("discovery_entry")
        registry = artifacts.get("discovery_registry")

        if entry is None and registry is None:
            return "SKIP", [], {"reason": "No discovery artifacts provided"}

        violations = []
        details = {}

        if entry is not None:
            vs = self.validate_entry(entry)
            violations.extend(vs)
            details["entry_violations"] = len(vs)

        if registry is not None:
            vs = self.validate_registry(registry)
            violations.extend(vs)
            details["registry_violations"] = len(vs)

        errors = [v for v in violations if v.severity == "ERROR"]
        if len(errors) == 0:
            if len(violations) > 0:
                return "WARN", violations, details
            return "PASS", violations, details
        return "FAIL", violations, details


class ConsumerQuickstartValidator:
    """Validates consumer verdict against pf-consumer-quickstart."""

    VALID_VERDICTS = {"TRUST", "TRUST_WITH_CAUTION", "INSUFFICIENT_EVIDENCE", "DO_NOT_TRUST"}
    VALID_GRADES = {"A", "B", "C", "D", "F"}
    VALID_STAGE_STATUSES = {"PASS", "FAIL", "WARN", "SKIP", "PENDING"}

    def validate_verdict(self, verdict):
        """Validate consumer verdict. Returns list of Violations."""
        violations = []
        if not isinstance(verdict, dict):
            violations.append(Violation(
                "consumer_quickstart", "$.consumer_verdict",
                "Consumer verdict must be a JSON object",
                "Generate verdict using quickstart.py.",
            ))
            return violations

        # Verdict section
        v = verdict.get("verdict", {})
        if isinstance(v, dict):
            tv = v.get("trust_verdict")
            if tv is not None and tv not in self.VALID_VERDICTS:
                violations.append(Violation(
                    "consumer_quickstart", "$.verdict.trust_verdict",
                    f"Invalid trust_verdict '{tv}'",
                    f"Use one of: {', '.join(sorted(self.VALID_VERDICTS))}.",
                ))

            score = v.get("trust_score")
            if isinstance(score, (int, float)) and (score < 0.0 or score > 1.0):
                violations.append(Violation(
                    "consumer_quickstart", "$.verdict.trust_score",
                    f"Trust score {score} out of range [0.0, 1.0]",
                    "Trust score must be between 0.0 and 1.0.",
                ))

            grade = v.get("trust_grade")
            if grade is not None and grade not in self.VALID_GRADES:
                violations.append(Violation(
                    "consumer_quickstart", "$.verdict.trust_grade",
                    f"Invalid trust_grade '{grade}'",
                    f"Use one of: {', '.join(sorted(self.VALID_GRADES))}.",
                ))

            # Grade-score consistency
            if isinstance(score, (int, float)) and grade in self.VALID_GRADES:
                expected = self._score_to_grade(score)
                if grade != expected:
                    violations.append(Violation(
                        "consumer_quickstart", "$.verdict",
                        f"Grade '{grade}' inconsistent with score {score:.4f} (expected '{expected}')",
                        "Grade thresholds: A >= 0.80, B >= 0.65, C >= 0.50, D >= 0.35, F < 0.35.",
                        severity="WARNING",
                    ))

        # Stages
        stages = verdict.get("stages", [])
        if isinstance(stages, list):
            for i, s in enumerate(stages):
                if isinstance(s, dict):
                    status = s.get("status")
                    if status is not None and status not in self.VALID_STAGE_STATUSES:
                        violations.append(Violation(
                            "consumer_quickstart", f"$.stages[{i}].status",
                            f"Invalid stage status '{status}'",
                            f"Use one of: {', '.join(sorted(self.VALID_STAGE_STATUSES))}.",
                        ))

        # Trust components weight sum
        tc = verdict.get("trust_components", {})
        if isinstance(tc, dict) and len(tc) > 0:
            total_weight = 0.0
            for cname, cdata in tc.items():
                if isinstance(cdata, dict):
                    w = cdata.get("weight", 0)
                    if isinstance(w, (int, float)):
                        total_weight += w
            if total_weight > 0 and abs(total_weight - 1.0) > 0.02:
                violations.append(Violation(
                    "consumer_quickstart", "$.trust_components",
                    f"Component weights sum to {total_weight:.4f}, expected ~1.0",
                    "Trust component weights should sum to 1.0.",
                    severity="WARNING",
                ))

        return violations

    def _score_to_grade(self, score):
        if score >= 0.80:
            return "A"
        elif score >= 0.65:
            return "B"
        elif score >= 0.50:
            return "C"
        elif score >= 0.35:
            return "D"
        return "F"

    def validate(self, artifacts):
        """Validate quickstart artifacts. Returns (status, violations, details)."""
        verdict = artifacts.get("quickstart_verdict")
        if verdict is None:
            return "SKIP", [], {"reason": "No consumer verdict provided"}

        violations = self.validate_verdict(verdict)
        details = {"n_violations": len(violations)}

        errors = [v for v in violations if v.severity == "ERROR"]
        if len(errors) == 0:
            if len(violations) > 0:
                return "WARN", violations, details
            return "PASS", violations, details
        return "FAIL", violations, details


# ===================================================================
# CROSS-PROTOCOL CONSISTENCY CHECKER
# ===================================================================

class CrossProtocolChecker:
    """Checks consistency across protocol boundaries."""

    def check(self, artifacts, protocol_results):
        """Run cross-protocol consistency checks. Returns list of Violations."""
        violations = []

        signals = artifacts.get("signals")
        proof = artifacts.get("proof_surface")
        routing_report = artifacts.get("routing_report")
        resolution_report = artifacts.get("resolution_report")
        audit_report = artifacts.get("audit_report")
        quickstart_verdict = artifacts.get("quickstart_verdict")
        discovery_entry = artifacts.get("discovery_entry")

        # 1. Signals referenced in proof must exist in signal log
        if isinstance(signals, (list, dict)) and isinstance(proof, dict):
            signal_ids = set()
            sig_list = signals if isinstance(signals, list) else signals.get("signals", [])
            for s in sig_list:
                if isinstance(s, dict):
                    signal_ids.add(s.get("signal_id"))

            resolved = proof.get("resolved_signals", [])
            if isinstance(resolved, list):
                orphaned = []
                for rs in resolved:
                    if isinstance(rs, dict):
                        rsid = rs.get("signal_id")
                        if rsid and rsid not in signal_ids:
                            orphaned.append(rsid)
                if orphaned:
                    violations.append(Violation(
                        "cross_protocol", "$.proof_surface.resolved_signals",
                        f"{len(orphaned)} resolved signal(s) in proof not found in signal log (first: {orphaned[0]})",
                        "Ensure all resolved signals in proof surface have corresponding entries in the signal log. This is a lifecycle gap.",
                    ))

        # 2. Routing decisions must reference valid signal IDs
        if isinstance(signals, (list, dict)) and isinstance(routing_report, dict):
            signal_ids = set()
            sig_list = signals if isinstance(signals, list) else signals.get("signals", [])
            for s in sig_list:
                if isinstance(s, dict):
                    signal_ids.add(s.get("signal_id"))

            decisions = routing_report.get("decisions", [])
            if isinstance(decisions, list):
                unmatched = []
                for d in decisions:
                    if isinstance(d, dict):
                        dsid = d.get("signal_id")
                        if dsid and dsid not in signal_ids:
                            unmatched.append(dsid)
                if unmatched:
                    violations.append(Violation(
                        "cross_protocol", "$.routing_report.decisions",
                        f"{len(unmatched)} routing decision(s) reference signal IDs not in signal log (first: {unmatched[0]})",
                        "Routing decisions must reference signals from the signal log.",
                    ))

        # 3. Schema-valid signal failing routing = routing issue, not schema issue
        if protocol_results.get("signal_schema", {}).get("status") == "PASS":
            if protocol_results.get("routing_protocol", {}).get("status") == "FAIL":
                violations.append(Violation(
                    "cross_protocol", "$.routing_protocol",
                    "Signals pass schema validation but fail routing — this is a routing configuration issue, not a schema issue",
                    "Review routing_policy.json configuration. Signal format is valid; routing rules need adjustment.",
                    severity="INFO",
                ))

        # 4. Resolution report producer_id should match signal producer_id
        if isinstance(signals, (list, dict)) and isinstance(resolution_report, dict):
            sig_list = signals if isinstance(signals, list) else signals.get("signals", [])
            signal_pids = set()
            for s in sig_list:
                if isinstance(s, dict) and "producer_id" in s:
                    signal_pids.add(s["producer_id"])
            res_meta = resolution_report.get("meta", {})
            if isinstance(res_meta, dict):
                res_pid = res_meta.get("producer_id")
                if res_pid and signal_pids and res_pid not in signal_pids:
                    violations.append(Violation(
                        "cross_protocol", "$.resolution_report.meta.producer_id",
                        f"Resolution report producer_id '{res_pid}' not found in signal producer IDs {signal_pids}",
                        "Ensure resolution report is generated from the same signals being tested.",
                        severity="WARNING",
                    ))

        # 5. Proof freshness vs discovery liveness consistency
        if isinstance(proof, dict) and isinstance(discovery_entry, dict):
            fm = proof.get("freshness_metadata", {})
            fg = fm.get("freshness_grade") if isinstance(fm, dict) else None
            lv = discovery_entry.get("liveness", {})
            lg = lv.get("liveness_grade") if isinstance(lv, dict) else None
            if fg == "EXPIRED" and lg == "ALIVE":
                violations.append(Violation(
                    "cross_protocol", "$.discovery_entry.liveness",
                    "Discovery entry claims ALIVE but proof surface is EXPIRED — inconsistent",
                    "Update heartbeat to reflect actual proof freshness, or refresh proof surface.",
                    severity="WARNING",
                ))
            elif fg == "LIVE" and lg == "UNRESPONSIVE":
                violations.append(Violation(
                    "cross_protocol", "$.discovery_entry.liveness",
                    "Proof surface is LIVE but discovery entry shows UNRESPONSIVE — heartbeat may be stale",
                    "Resume heartbeat updates to the discovery registry.",
                    severity="WARNING",
                ))

        # 6. Proof reputation vs resolution reputation consistency
        if isinstance(proof, dict) and isinstance(resolution_report, dict):
            proof_rep = proof.get("reputation", {})
            res_rep = resolution_report.get("reputation", {})
            if isinstance(proof_rep, dict) and isinstance(res_rep, dict):
                ps = proof_rep.get("score")
                rs = res_rep.get("composite_score")
                if isinstance(ps, (int, float)) and isinstance(rs, (int, float)):
                    if abs(ps - rs) > 0.15:
                        violations.append(Violation(
                            "cross_protocol", "$.proof_surface.reputation vs $.resolution_report.reputation",
                            f"Reputation score discrepancy: proof({ps:.4f}) vs resolution({rs:.4f}), delta={abs(ps-rs):.4f}",
                            "Large reputation discrepancy suggests proof surface is stale or uses different resolution data.",
                            severity="WARNING",
                        ))

        # 7. Audit verdict vs quickstart verdict consistency
        if isinstance(audit_report, dict) and isinstance(quickstart_verdict, dict):
            audit_tg = audit_report.get("trust_grade", {})
            qs_v = quickstart_verdict.get("verdict", {})
            if isinstance(audit_tg, dict) and isinstance(qs_v, dict):
                a_verdict = audit_tg.get("verdict")
                q_verdict = qs_v.get("trust_verdict")
                if a_verdict and q_verdict and a_verdict != q_verdict:
                    violations.append(Violation(
                        "cross_protocol", "$.audit vs $.quickstart",
                        f"Audit verdict '{a_verdict}' differs from quickstart verdict '{q_verdict}'",
                        "Different input data or policy thresholds may explain divergence. Check both reports.",
                        severity="INFO",
                    ))

        # 8. Signal symbols must match discovery symbol_coverage
        if isinstance(signals, (list, dict)) and isinstance(discovery_entry, dict):
            sig_list = signals if isinstance(signals, list) else signals.get("signals", [])
            signal_symbols = set()
            for s in sig_list:
                if isinstance(s, dict) and "symbol" in s:
                    signal_symbols.add(s["symbol"])
            sc = discovery_entry.get("symbol_coverage", {})
            if isinstance(sc, dict):
                declared = set(sc.get("symbols", []))
                missing = signal_symbols - declared
                if missing:
                    violations.append(Violation(
                        "cross_protocol", "$.discovery_entry.symbol_coverage",
                        f"Signals contain symbols not in discovery coverage: {sorted(missing)}",
                        "Update symbol_coverage in discovery entry to include all emitted symbols.",
                        severity="WARNING",
                    ))

        return violations


# ===================================================================
# CONFORMANCE ENGINE
# ===================================================================

VALIDATORS = {
    "signal_schema": SignalSchemaValidator,
    "routing_protocol": RoutingProtocolValidator,
    "resolution_protocol": ResolutionProtocolValidator,
    "aggregation_protocol": AggregationProtocolValidator,
    "proof_protocol": ProofProtocolValidator,
    "lifecycle_pipeline": LifecyclePipelineValidator,
    "consumer_audit": ConsumerAuditValidator,
    "discovery_protocol": DiscoveryProtocolValidator,
    "consumer_quickstart": ConsumerQuickstartValidator,
}


class ConformanceEngine:
    """Orchestrates dependency-ordered validation across all 9 protocols."""

    def __init__(self):
        self.validators = {k: v() for k, v in VALIDATORS.items()}
        self.cross_checker = CrossProtocolChecker()

    def load_artifacts_from_directory(self, directory):
        """Load all artifacts from a local directory."""
        artifacts = {}

        # Signals
        data, path, err = load_artifact(directory, "signals")
        if data is not None:
            artifacts["signals"] = data
            artifacts["_paths"] = artifacts.get("_paths", {})
            artifacts["_paths"]["signals"] = path

        # Proof surface
        data, path, err = load_artifact(directory, "proof_surface")
        if data is not None:
            artifacts["proof_surface"] = data
            artifacts["_paths"] = artifacts.get("_paths", {})
            artifacts["_paths"]["proof_surface"] = path

        # Routing config
        data, path, err = load_artifact(directory, "routing_config")
        if data is not None:
            artifacts["routing_config"] = data

        # Routing report
        data, path, err = load_artifact(directory, "routing_report")
        if data is not None:
            artifacts["routing_report"] = data

        # Resolution report
        data, path, err = load_artifact(directory, "resolution_report")
        if data is not None:
            artifacts["resolution_report"] = data

        # Aggregation report
        data, path, err = load_artifact(directory, "aggregation_report")
        if data is not None:
            artifacts["aggregation_report"] = data

        # Aggregation registry
        data, path, err = load_artifact(directory, "aggregation_registry")
        if data is not None:
            artifacts["aggregation_registry"] = data

        # Lifecycle report
        data, path, err = load_artifact(directory, "lifecycle_report")
        if data is not None:
            artifacts["lifecycle_report"] = data

        # Audit report
        data, path, err = load_artifact(directory, "audit_report")
        if data is not None:
            artifacts["audit_report"] = data

        # Discovery registry
        data, path, err = load_artifact(directory, "discovery_registry")
        if data is not None:
            artifacts["discovery_registry"] = data

        # Discovery entry
        data, path, err = load_artifact(directory, "discovery_entry")
        if data is not None:
            artifacts["discovery_entry"] = data

        # Quickstart verdict
        data, path, err = load_artifact(directory, "quickstart_verdict")
        if data is not None:
            artifacts["quickstart_verdict"] = data

        return artifacts

    def load_artifacts_from_endpoint(self, endpoint_url, timeout=15):
        """Load artifacts from a producer endpoint URL."""
        artifacts = {}
        errors = []

        # Common endpoint patterns
        endpoints = {
            "signals": ["/signals", "/api/signals", "/signal_log.json"],
            "proof_surface": ["/proof", "/api/proof", "/proof_surface.json"],
            "routing_report": ["/routing", "/api/routing"],
            "resolution_report": ["/resolution", "/api/resolution"],
            "discovery_entry": ["/producer", "/api/producer"],
        }

        base = endpoint_url.rstrip("/")
        for artifact_key, paths in endpoints.items():
            for path in paths:
                url = base + path
                data, err = fetch_json_url(url, timeout=timeout)
                if data is not None:
                    artifacts[artifact_key] = data
                    break

        return artifacts

    def run(self, artifacts):
        """Run full conformance validation. Returns conformance report dict."""
        started_at = iso_timestamp()
        protocol_results = {}
        all_violations = []

        # Phase 1: Dependency-ordered per-protocol validation
        for protocol in PROTOCOL_ORDER:
            deps = PROTOCOL_DEPENDENCIES[protocol]
            upstream_failed = False
            failed_deps = []

            for dep in deps:
                dep_result = protocol_results.get(dep, {})
                if dep_result.get("status") == "FAIL":
                    upstream_failed = True
                    failed_deps.append(dep)

            if upstream_failed:
                # Cascade: skip downstream if upstream failed
                protocol_results[protocol] = {
                    "status": "SKIP",
                    "violations": [],
                    "details": {
                        "reason": f"Upstream dependency failed: {', '.join(PROTOCOL_DISPLAY[d] for d in failed_deps)}",
                        "skipped_due_to": failed_deps,
                    },
                    "n_errors": 0,
                    "n_warnings": 0,
                }
                continue

            validator = self.validators[protocol]
            try:
                status, violations, details = validator.validate(artifacts)
            except Exception as e:
                status = "FAIL"
                violations = [Violation(
                    protocol, "$",
                    f"Validator raised exception: {str(e)}",
                    "Check artifact format. This may indicate a corrupted or unexpected file structure.",
                )]
                details = {"exception": str(e)}

            errors = [v for v in violations if v.severity == "ERROR"]
            warnings = [v for v in violations if v.severity == "WARNING"]

            protocol_results[protocol] = {
                "status": status,
                "violations": [v.to_dict() for v in violations],
                "details": details,
                "n_errors": len(errors),
                "n_warnings": len(warnings),
            }
            all_violations.extend(violations)

        # Phase 2: Cross-protocol consistency
        cross_violations = self.cross_checker.check(artifacts, protocol_results)
        cross_errors = [v for v in cross_violations if v.severity == "ERROR"]
        cross_warnings = [v for v in cross_violations if v.severity == "WARNING"]

        # Phase 3: Compute overall readiness grade
        grade_info = self._compute_grade(protocol_results)

        # Phase 4: Generate limitations
        limitations = self._detect_limitations(artifacts, protocol_results)

        # Build report
        finished_at = iso_timestamp()
        report = {
            "meta": {
                "testkit_version": __version__,
                "protocol_version": PROTOCOL_VERSION,
                "generated_at": finished_at,
                "started_at": started_at,
                "artifact_source": artifacts.get("_source", "local_directory"),
                "artifact_path": artifacts.get("_path", ""),
            },
            "readiness_grade": grade_info,
            "protocol_results": {},
            "cross_protocol_checks": {
                "violations": [v.to_dict() for v in cross_violations],
                "n_errors": len(cross_errors),
                "n_warnings": len(cross_warnings),
                "n_info": len([v for v in cross_violations if v.severity == "INFO"]),
            },
            "summary": {
                "total_protocols": len(PROTOCOL_ORDER),
                "passed": sum(1 for r in protocol_results.values() if r["status"] == "PASS"),
                "warned": sum(1 for r in protocol_results.values() if r["status"] == "WARN"),
                "failed": sum(1 for r in protocol_results.values() if r["status"] == "FAIL"),
                "skipped": sum(1 for r in protocol_results.values() if r["status"] == "SKIP"),
                "total_violations": len(all_violations) + len(cross_violations),
                "total_errors": sum(r["n_errors"] for r in protocol_results.values()) + len(cross_errors),
                "total_warnings": sum(r["n_warnings"] for r in protocol_results.values()) + len(cross_warnings),
            },
            "limitations": [lim for lim in limitations],
            "protocol_version": PROTOCOL_VERSION,
        }

        # Add per-protocol results in dependency order
        for protocol in PROTOCOL_ORDER:
            result = protocol_results[protocol]
            report["protocol_results"][protocol] = {
                "display_name": PROTOCOL_DISPLAY[protocol],
                "status": result["status"],
                "violations": result["violations"],
                "details": result["details"],
                "n_errors": result["n_errors"],
                "n_warnings": result["n_warnings"],
                "dependencies": PROTOCOL_DEPENDENCIES[protocol],
            }

        return report

    def _compute_grade(self, protocol_results):
        """Compute overall readiness grade from protocol results."""
        # Weighted composite score
        composite = 0.0
        total_weight = 0.0
        n_fail = 0

        for protocol in PROTOCOL_ORDER:
            result = protocol_results.get(protocol, {})
            status = result.get("status", "SKIP")
            weight = PROTOCOL_WEIGHTS.get(protocol, 0.1)
            score = STATUS_SCORES.get(status, 0.0)
            composite += weight * score
            total_weight += weight
            if status == "FAIL":
                n_fail += 1

        if total_weight > 0:
            composite = composite / total_weight
        composite = round(composite, 4)

        # Determine letter grade
        grade = "F"
        for g, threshold in sorted(GRADE_THRESHOLDS.items(), key=lambda x: -x[1]):
            if composite >= threshold:
                grade = g
                break

        # Grade penalties
        if n_fail >= 3:
            grade = max(grade, "D")  # Cap at D with 3+ failures
        if protocol_results.get("signal_schema", {}).get("status") == "FAIL":
            grade = "F"  # Foundation failure = automatic F

        return {
            "grade": grade,
            "composite_score": composite,
            "n_pass": sum(1 for r in protocol_results.values() if r["status"] == "PASS"),
            "n_fail": n_fail,
            "n_warn": sum(1 for r in protocol_results.values() if r["status"] == "WARN"),
            "n_skip": sum(1 for r in protocol_results.values() if r["status"] == "SKIP"),
            "grade_thresholds": GRADE_THRESHOLDS,
            "protocol_weights": PROTOCOL_WEIGHTS,
            "per_protocol_scores": {
                p: {"status": protocol_results[p]["status"],
                    "score": STATUS_SCORES.get(protocol_results[p]["status"], 0.0),
                    "weight": PROTOCOL_WEIGHTS.get(p, 0.1)}
                for p in PROTOCOL_ORDER
            },
        }

    def _detect_limitations(self, artifacts, protocol_results):
        """Detect conformance limitations with bias direction."""
        limitations = []

        # Count available artifacts
        artifact_keys = [k for k in artifacts if not k.startswith("_")]
        n_available = len(artifact_keys)

        if n_available < 3:
            limitations.append({
                "id": "SPARSE_ARTIFACTS",
                "description": f"Only {n_available} artifact(s) provided. Conformance testing requires signal, proof, and routing artifacts at minimum for meaningful results.",
                "bias_direction": "OVERSTATED_READINESS",
                "bias_magnitude": f"{9 - n_available} of 9 protocol checks are SKIP due to missing artifacts. True readiness may be lower than grade suggests.",
            })

        # Signal volume
        signals = artifacts.get("signals")
        if isinstance(signals, (list, dict)):
            sig_list = signals if isinstance(signals, list) else signals.get("signals", [])
            if len(sig_list) < 30:
                limitations.append({
                    "id": "SMALL_SIGNAL_SAMPLE",
                    "description": f"Only {len(sig_list)} signals provided. Statistical validation (Wilson CIs, Brier decomposition) requires >= 30 signals for stability.",
                    "bias_direction": "INDETERMINATE",
                    "bias_magnitude": f"Sample size {len(sig_list)} produces wide confidence intervals. Pass/fail determination has high uncertainty.",
                })

        # Foundation failure
        if protocol_results.get("signal_schema", {}).get("status") == "FAIL":
            limitations.append({
                "id": "FOUNDATION_FAILURE",
                "description": "Signal schema validation failed. All downstream protocol checks that depend on valid signals may produce unreliable results.",
                "bias_direction": "UNDERSTATED_FAILURES",
                "bias_magnitude": "Downstream SKIP results mask additional failures that would surface with valid signals.",
            })

        # Cascade skips
        n_skip = sum(1 for r in protocol_results.values() if r["status"] == "SKIP")
        skip_due_to_cascade = sum(
            1 for r in protocol_results.values()
            if r["status"] == "SKIP" and "skipped_due_to" in r.get("details", {})
        )
        if skip_due_to_cascade > 0:
            limitations.append({
                "id": "CASCADE_SKIPS",
                "description": f"{skip_due_to_cascade} protocol(s) skipped due to upstream dependency failure. These protocols were not tested.",
                "bias_direction": "UNDERSTATED_FAILURES",
                "bias_magnitude": f"Fix upstream failures first to unlock testing of {skip_due_to_cascade} additional protocol(s).",
            })

        # No cross-protocol data
        if n_available <= 1:
            limitations.append({
                "id": "NO_CROSS_PROTOCOL_DATA",
                "description": "Cross-protocol consistency checks require at least 2 artifact types. Only single-protocol validation was performed.",
                "bias_direction": "OVERSTATED_READINESS",
                "bias_magnitude": "Inter-protocol inconsistencies (orphaned signals, mismatched producer IDs, stale references) cannot be detected.",
            })

        return limitations


# ===================================================================
# CLI INTERFACE
# ===================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Post Fiat Protocol Conformance Test Kit v" + __version__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s /path/to/artifacts/
  %(prog)s /path/to/artifacts/ --json
  %(prog)s /path/to/artifacts/ -o conformance_report.json
  %(prog)s --endpoint http://producer.example.com/
  %(prog)s /path/to/artifacts/ --validate
        """,
    )
    parser.add_argument("directory", nargs="?", help="Path to artifact directory")
    parser.add_argument("--endpoint", help="Producer endpoint URL to fetch artifacts from")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("-o", "--output", help="Write conformance report to file")
    parser.add_argument("--validate", action="store_true", help="Validate output report against own schema")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout in seconds (default: 15)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    if not args.directory and not args.endpoint:
        parser.error("Provide either a directory path or --endpoint URL")

    engine = ConformanceEngine()

    # Load artifacts
    if args.endpoint:
        print(f"Fetching artifacts from {args.endpoint}...", file=sys.stderr)
        artifacts = engine.load_artifacts_from_endpoint(args.endpoint, timeout=args.timeout)
        artifacts["_source"] = "endpoint"
        artifacts["_path"] = args.endpoint
    else:
        if not os.path.isdir(args.directory):
            print(f"Error: '{args.directory}' is not a directory", file=sys.stderr)
            sys.exit(1)
        artifacts = engine.load_artifacts_from_directory(args.directory)
        artifacts["_source"] = "local_directory"
        artifacts["_path"] = os.path.abspath(args.directory)

    # Run conformance
    report = engine.run(artifacts)

    # Self-validation
    if args.validate:
        self_violations = validate_conformance_report(report)
        if self_violations:
            print(f"WARN: Conformance report has {len(self_violations)} self-validation issue(s):", file=sys.stderr)
            for sv in self_violations[:5]:
                print(f"  - {sv}", file=sys.stderr)
        else:
            print("Conformance report passes self-validation.", file=sys.stderr)

    # Output
    if args.json:
        print(json.dumps(report, indent=2))
    elif args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"Conformance report written to {args.output}", file=sys.stderr)
    else:
        _print_text_report(report)

    # Exit code
    grade = report["readiness_grade"]["grade"]
    n_fail = report["summary"]["failed"]
    if grade == "F" or n_fail > 0:
        sys.exit(1)
    sys.exit(0)


def validate_conformance_report(report):
    """Self-validate conformance report structure. Returns list of issue strings."""
    issues = []

    if not isinstance(report, dict):
        return ["Report is not a dict"]

    required = ["meta", "readiness_grade", "protocol_results", "cross_protocol_checks", "summary", "limitations"]
    for field in required:
        if field not in report:
            issues.append(f"Missing required field: {field}")

    # Check grade
    rg = report.get("readiness_grade", {})
    if isinstance(rg, dict):
        grade = rg.get("grade")
        if grade not in {"A", "B", "C", "D", "F"}:
            issues.append(f"Invalid grade: {grade}")
        score = rg.get("composite_score")
        if isinstance(score, (int, float)) and (score < 0.0 or score > 1.0):
            issues.append(f"composite_score {score} out of range [0.0, 1.0]")

    # Check protocol results
    pr = report.get("protocol_results", {})
    if isinstance(pr, dict):
        for protocol in PROTOCOL_ORDER:
            if protocol not in pr:
                issues.append(f"Missing protocol result: {protocol}")
            else:
                result = pr[protocol]
                if isinstance(result, dict):
                    status = result.get("status")
                    if status not in {"PASS", "FAIL", "WARN", "SKIP"}:
                        issues.append(f"{protocol}: invalid status '{status}'")

    # Check summary consistency
    summary = report.get("summary", {})
    if isinstance(summary, dict):
        total = summary.get("total_protocols", 0)
        p = summary.get("passed", 0)
        w = summary.get("warned", 0)
        f_ = summary.get("failed", 0)
        s = summary.get("skipped", 0)
        if total > 0 and (p + w + f_ + s) != total:
            issues.append(f"Summary counts inconsistent: {p}+{w}+{f_}+{s} != {total}")

    return issues


def _print_text_report(report):
    """Print human-readable conformance report."""
    grade_info = report.get("readiness_grade", {})
    grade = grade_info.get("grade", "?")
    score = grade_info.get("composite_score", 0)

    print("=" * 60)
    print(f"  Post Fiat Protocol Conformance Report")
    print(f"  Testkit v{__version__}")
    print("=" * 60)
    print()
    print(f"  Overall Readiness Grade:  {grade}  ({score:.1%})")
    print()

    summary = report.get("summary", {})
    print(f"  Protocols:  {summary.get('passed', 0)} PASS  |  "
          f"{summary.get('warned', 0)} WARN  |  "
          f"{summary.get('failed', 0)} FAIL  |  "
          f"{summary.get('skipped', 0)} SKIP")
    print(f"  Violations: {summary.get('total_errors', 0)} errors  |  "
          f"{summary.get('total_warnings', 0)} warnings")
    print()
    print("-" * 60)
    print("  Per-Protocol Results (dependency order)")
    print("-" * 60)

    pr = report.get("protocol_results", {})
    for protocol in PROTOCOL_ORDER:
        result = pr.get(protocol, {})
        status = result.get("status", "?")
        display = result.get("display_name", protocol)
        n_err = result.get("n_errors", 0)
        n_warn = result.get("n_warnings", 0)

        status_icon = {"PASS": "[OK]", "WARN": "[!!]", "FAIL": "[XX]", "SKIP": "[--]"}.get(status, "[??]")

        detail_parts = []
        if n_err > 0:
            detail_parts.append(f"{n_err} error(s)")
        if n_warn > 0:
            detail_parts.append(f"{n_warn} warning(s)")
        details = result.get("details", {})
        if isinstance(details, dict):
            if "reason" in details:
                detail_parts.append(details["reason"])
            if "pass_rate" in details:
                detail_parts.append(f"pass_rate={details['pass_rate']}")

        detail_str = " — " + ", ".join(detail_parts) if detail_parts else ""
        print(f"  {status_icon} {display:<32} {status}{detail_str}")

        # Show top violations
        violations = result.get("violations", [])
        error_violations = [v for v in violations if v.get("severity") == "ERROR"]
        for v in error_violations[:3]:
            print(f"       {v.get('json_path', '?')}: {v.get('message', '')}")
            if v.get("remediation"):
                print(f"       -> {v['remediation']}")

    # Cross-protocol
    cross = report.get("cross_protocol_checks", {})
    cross_vs = cross.get("violations", [])
    if cross_vs:
        print()
        print("-" * 60)
        print("  Cross-Protocol Consistency")
        print("-" * 60)
        for v in cross_vs[:5]:
            severity = v.get("severity", "INFO")
            print(f"  [{severity}] {v.get('message', '')}")
            if v.get("remediation"):
                print(f"       -> {v['remediation']}")

    # Limitations
    limitations = report.get("limitations", [])
    if limitations:
        print()
        print("-" * 60)
        print("  Limitations")
        print("-" * 60)
        for lim in limitations:
            print(f"  [{lim.get('id', '?')}] {lim.get('description', '')}")
            print(f"       Bias: {lim.get('bias_direction', '?')} — {lim.get('bias_magnitude', '')}")

    print()
    print("=" * 60)
    print(f"  Grade: {grade}  |  Score: {score:.1%}  |  "
          f"Errors: {summary.get('total_errors', 0)}  |  "
          f"Warnings: {summary.get('total_warnings', 0)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
