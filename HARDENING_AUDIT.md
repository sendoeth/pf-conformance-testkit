# Post Fiat Full-Stack Adversarial Hardening Audit

**Generated**: 2026-04-05 22:46 UTC
**Harness Version**: 1.0.0
**Protocol Path**: Signal → Validation → Routing → Resolution → Proof → Audit

## Summary

| Metric | Before Fix | After Fix |
|--------|-----------|-----------|
| Total Cases | 7 | 7 |
| Passed | 0 | 7 |
| Failed | 7 | 0 |
| Errors | 0 | 0 |

## End-to-End Path Tested

```
Signal Generation → Schema Validation (pf-signal-schema)
  → Pre-Flight Routing (pf-routing-protocol)
  → Price Resolution (pf-resolution-protocol / pf-proof-protocol)
  → Proof Maintenance (pf-proof-protocol)
  → Consumer Audit (pf-consumer-audit)
  → Conformance Validation (pf-conformance-testkit)
```

## Fix Commits

| Case(s) | Repo | Commit |
|---------|------|--------|
| ADV-001, ADV-002, ADV-005, ADV-007 | pf-routing-protocol | [`267c918`](https://github.com/sendoeth/pf-routing-protocol/commit/267c918) |
| ADV-003 | pf-consumer-quickstart | [`7dcee56`](https://github.com/sendoeth/pf-consumer-quickstart/commit/7dcee56) |
| ADV-004 | pf-conformance-testkit | [`6b42407`](https://github.com/sendoeth/pf-conformance-testkit/commit/6b42407) |
| ADV-006 | pf-proof-protocol | [`79389c4`](https://github.com/sendoeth/pf-proof-protocol/commit/79389c4) |

## Adversarial Cases

### ADV-001: Zero-confidence signal passes VOI gate

**Target**: `pf-routing-protocol` — `preflight_filter.py:365`
**JSON Path**: `$.decisions[0].action`

**Description**: A signal with confidence=0.0 carries zero information content. VOI formula: confidence * (2*accuracy - 1) = 0.0 * anything = 0.0. With min_voi=0.0 (default), the gate uses >= comparison, so 0.0 >= 0.0 passes. This means a completely uninformative signal is emitted to downstream consumers.

**Adversarial Input**:
```json
{
  "signal_id": "adv-001-zero-conf",
  "producer_id": "adversarial_harness",
  "timestamp": "2026-04-05T20:46:00.991902+00:00",
  "symbol": "BTC",
  "direction": "bullish",
  "confidence": 0.0,
  "horizon_hours": 24,
  "action": "EXECUTE",
  "schema_version": "1.0.0",
  "regime_context": {
    "regime_id": "NEUTRAL",
    "duration_days": 14,
    "regime_confidence": 75,
    "decision": "EXECUTE"
  }
}
```

**Expected Behavior**: WITHHOLD (zero-information signal should not be emitted)

| Phase | Status | Observed |
|-------|--------|----------|
| Before Fix | **FAIL** | VOI gate uses `>= 0.0` comparison. `compute_voi(accuracy, 0.0)` = 0.0, and `0.0 >= 0.0` is True → signal EMITs. Zero-information signal passes to downstream consumers. |
| After Fix | **PASS** | VOI gate now uses strict `>` comparison ([`267c918`](https://github.com/sendoeth/pf-routing-protocol/commit/267c918)). `0.0 > 0.0` is False → WITHHOLD. `compute_voi` also sets `zero_confidence: true` flag. |

---

### ADV-002: Missing Weibull params for regime cause silent hazard skip

**Target**: `pf-routing-protocol` — `preflight_filter.py:354`
**JSON Path**: `$.decisions[0].voi.hazard_adjustment`

**Description**: When use_hazard_adjustment=True and regime_id is not in weibull_params, the hazard adjustment is silently skipped. No warning, no audit trail. Consumer expects hazard-adjusted VOI but gets raw VOI. If Weibull params contain incomplete keys (missing shape or scale), a KeyError crashes.

**Adversarial Input**:
```json
{
  "signal": {
    "signal_id": "adv-002-missing-weibull",
    "producer_id": "adversarial_harness",
    "timestamp": "2026-04-05T20:46:00.991902+00:00",
    "symbol": "BTC",
    "direction": "bullish",
    "confidence": 0.65,
    "horizon_hours": 24,
    "action": "EXECUTE",
    "schema_version": "1.0.0",
    "regime_context": {
      "regime_id": "DIVERGENCE",
      "duration_days": 14,
      "regime_confidence": 70,
      "decision": "EXECUTE"
    }
  },
  "config_override": {
    "weibull_params": {
      "DIVERGENCE": {
        "scale": 18.0
      }
    },
    "gates": {
      "voi_gate": {
        "enabled": true,
        "min_voi": 0.0,
        "use_hazard_adjustment": true
      }
    }
  }
}
```

**Expected Behavior**: Graceful fallback with warning, not KeyError or silent skip

| Phase | Status | Observed |
|-------|--------|----------|
| Before Fix | **FAIL** | Hazard adjustment silently skipped for DIVERGENCE regime (not in weibull_params or incomplete params). No warning in output. |
| After Fix | **PASS** | Hazard adjustment skipped (incomplete params), `hazard_skipped: true` + `hazard_skip_reason` emitted ([`267c918`](https://github.com/sendoeth/pf-routing-protocol/commit/267c918)). `INCOMPLETE_HAZARD_PARAMS` limitation added to report. Graceful fallback to non-hazard VOI. |

---

### ADV-003: Price resolution tolerance mismatch across protocols

**Target**: `pf-consumer-quickstart + pf-proof-protocol` — `quickstart.py:707 vs maintain_proof.py:363`
**JSON Path**: `$.resolution.tolerance_hours`

**Description**: quickstart.py uses 1.5h (5400s) tolerance for price matching, while maintain_proof.py uses 2.0h (7200s). A signal with a price point available at 1.75h from the target timestamp will resolve successfully in maintain_proof but fail in quickstart. This means the same signal has different outcomes depending on which protocol resolves it — a cross-protocol inconsistency.

**Adversarial Input**:
```json
{
  "signal_timestamp": "2026-03-30T12:00:00Z",
  "price_available_at": "2026-03-30T13:45:00Z",
  "gap_seconds": 6300,
  "quickstart_tolerance": 5400,
  "maintain_proof_tolerance": 7200
}
```

**Expected Behavior**: Both protocols use same tolerance (7200s / 2.0h)

| Phase | Status | Observed |
|-------|--------|----------|
| Before Fix | **FAIL** | quickstart.py:707 uses tolerance_hours=1.5 (5400s). maintain_proof.py:363 uses gap <= 7200 (2.0h). Same signal at 1.75h gap resolves in maintain_proof (within 7200s) but fails in quickstart (exceeds 5400s). Cross-protocol inconsistency confirmed. |
| After Fix | **PASS** | Tolerances unified ([`7dcee56`](https://github.com/sendoeth/pf-consumer-quickstart/commit/7dcee56)): quickstart now uses tolerance_hours=2.0 (7200s), matching maintain_proof's 7200s. Both consistent. |

---

### ADV-004: Brier identity tolerance allows fabrication within 0.01 budget

**Target**: `pf-conformance-testkit` — `conformance_testkit.py:753`
**JSON Path**: `$.overall.brier_score`

**Description**: conformance_testkit.py line 753 uses tolerance=0.01 for the Brier identity check (brier = reliability - resolution + uncertainty). A producer can claim: reliability=0.001, resolution=0.005, uncertainty=0.247 → expected brier=0.243, declared brier=0.234. The gap is 0.009, which passes the 0.01 tolerance. This allows a ~4% fabrication of the Brier score without detection.

**Adversarial Input**:
```json
{
  "brier_score": 0.234,
  "reliability": 0.001,
  "resolution": 0.005,
  "uncertainty": 0.247,
  "expected_brier": 0.243,
  "declared_gap": 0.009,
  "tolerance": 0.01
}
```

**Expected Behavior**: Violation detected (tolerance tightened to 0.005)

| Phase | Status | Observed |
|-------|--------|----------|
| Before Fix | **FAIL** | Declared brier=0.234, expected=0.2430, gap=0.0090. Tolerance=0.01. PASSES identity check. Fabricated Brier score (3.7% error) slips through. |
| After Fix | **PASS** | Gap=0.0090. Tolerance tightened to 0.005 ([`6b42407`](https://github.com/sendoeth/pf-conformance-testkit/commit/6b42407)). FAILS identity check. Fabricated Brier score now correctly detected. |

---

### ADV-005: Null regime_context cascades silently through routing

**Target**: `pf-routing-protocol` — `preflight_filter.py:725-730`
**JSON Path**: `$.decisions[0].rationale`

**Description**: Signal schema makes regime_context optional. A signal with regime_context=null passes schema validation. When routed, the CLI infers regime from the first signal's regime_context, calling .get() on None → falls back to UNKNOWN. But the regime_gate's allowed_regimes may not include UNKNOWN, causing silent WITHHOLD with no clear error explaining the null-context cascade.

**Adversarial Input**:
```json
{
  "signal_id": "adv-005-null-regime",
  "producer_id": "adversarial_harness",
  "timestamp": "2026-04-05T20:46:00.991902+00:00",
  "symbol": "BTC",
  "direction": "bullish",
  "confidence": 0.65,
  "horizon_hours": 24,
  "action": "EXECUTE",
  "schema_version": "1.0.0",
  "regime_context": null
}
```

**Expected Behavior**: Explicit warning about null regime_context in decision rationale

| Phase | Status | Observed |
|-------|--------|----------|
| Before Fix | **FAIL** | action=WITHHOLD, rationale='WITHHOLD: regime UNKNOWN not in allowed list ['NEUTRAL', 'DIVERGENCE']'. Null regime_context → UNKNOWN regime → no warning about null context. Signal withheld because UNKNOWN not in allowed_regimes, but rationale doesn't explain the null-context root cause. |
| After Fix | **PASS** | `UNKNOWN_REGIME` limitation emitted with `"Regime is UNKNOWN — may indicate null or missing regime_context"` ([`267c918`](https://github.com/sendoeth/pf-routing-protocol/commit/267c918)). Root cause now visible in report. |

---

### ADV-006: maintain_proof accepts non-schema-valid signals without validation

**Target**: `pf-proof-protocol` — `maintain_proof.py:389`
**JSON Path**: `$.resolved_signals[*].confidence`

**Description**: pf-proof-protocol's maintain_proof.py has no schema validation step. Signals with out-of-range confidence (5.0) or invalid symbols pass directly into proof surface computation. quickstart.py and conformance_testkit both validate schema, but maintain_proof assumes all input signals are valid. A malformed signal persisted in proof surface corrupts accuracy/Brier metrics downstream.

**Adversarial Input**:
```json
{
  "signal_id": "adv-006-bad-schema",
  "producer_id": "adversarial_harness",
  "timestamp": "2026-04-05T20:46:00.991902+00:00",
  "symbol": "INVALID_TICKER_XYZ",
  "direction": "bullish",
  "confidence": 5.0,
  "horizon_hours": 24,
  "action": "EXECUTE",
  "schema_version": "1.0.0",
  "regime_context": {
    "regime_id": "NEUTRAL",
    "duration_days": 14,
    "regime_confidence": 75,
    "decision": "EXECUTE"
  }
}
```

**Expected Behavior**: Schema validation at intake rejects out-of-range confidence

| Phase | Status | Observed |
|-------|--------|----------|
| Before Fix | **FAIL** | maintain_proof.py has no schema validation. Signal with confidence=5.0 and symbol=INVALID_TICKER_XYZ enters resolution pipeline unchecked. Rejection occurs downstream (missing price data), not at intake. Invalid confidence corrupts Brier/accuracy if prices happen to exist. |
| After Fix | **PASS** | Lightweight intake validation added ([`79389c4`](https://github.com/sendoeth/pf-proof-protocol/commit/79389c4)): checks `0 <= confidence <= 1` and `symbol in {BTC, ETH, SOL, LINK}`. Returns `resolution_reason: "schema_validation_failed"` before processing. |

---

### ADV-007: Duration bucket gap causes silent fallback to last bucket

**Target**: `pf-routing-protocol` — `preflight_filter.py:145-153`
**JSON Path**: `$.decisions[0].voi.accuracy_estimate`

**Description**: If duration_buckets have a gap (e.g., early=[0,10), late=[15,9999)), a signal at duration_days=12 falls through all buckets. assign_duration_bucket() returns buckets[-1]['label'] (the last bucket) silently, with no warning that the duration is in an uncovered gap. This means VOI accuracy estimates come from the wrong bucket.

**Adversarial Input**:
```json
{
  "duration_days": 12,
  "duration_buckets": [
    {
      "label": "early",
      "min_days": 0,
      "max_days": 10
    },
    {
      "label": "late",
      "min_days": 15,
      "max_days": 9999
    }
  ],
  "expected_bucket": "NONE (gap)",
  "actual_bucket": "late (last bucket fallback)"
}
```

**Expected Behavior**: Warning about duration falling in uncovered bucket gap

| Phase | Status | Observed |
|-------|--------|----------|
| Before Fix | **FAIL** | `assign_duration_bucket(12.0, buckets)` falls through all buckets (12 not in [0,10) or [15,9999)). Returns `buckets[-1]["label"]` = "late" silently. VOI accuracy estimate drawn from wrong bucket with no warning. |
| After Fix | **PASS** | Gap detection added ([`267c918`](https://github.com/sendoeth/pf-routing-protocol/commit/267c918)). Returns `"unknown"` for uncovered durations. Overflow beyond all `max_days` still returns last bucket (correct). |

---

## Remaining Blockers

All adversarial cases passing after fixes.

## Reusability

This harness is reusable by any operator:
```bash
# Run all adversarial cases
python adversarial_harness.py

# Run single case
python adversarial_harness.py --case ADV-001

# JSON output for automation
python adversarial_harness.py --json

# Generate full audit report
python adversarial_harness.py --audit
```
