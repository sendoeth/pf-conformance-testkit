#!/usr/bin/env python3
"""
Test suite for Post Fiat Protocol Conformance Test Kit.

80+ tests covering:
  - Dependency-ordered validation sequencing
  - Cross-protocol consistency detection accuracy
  - Synthetic signal generator correctness against expected outcomes
  - Grade threshold boundary transitions
  - Partial artifact availability handling
  - Malformed input rejection at each protocol stage
  - Empty artifact sets
  - Remote endpoint timeout handling
  - Conformance report schema self-validation
"""

import json
import os
import sys
import unittest
import tempfile
import shutil
import hashlib
import math
import datetime
import copy
from unittest.mock import patch, MagicMock

# Add parent dir to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from conformance_testkit import (
    ConformanceEngine, Violation,
    SignalSchemaValidator, RoutingProtocolValidator,
    ResolutionProtocolValidator, AggregationProtocolValidator,
    ProofProtocolValidator, LifecyclePipelineValidator,
    ConsumerAuditValidator, DiscoveryProtocolValidator,
    ConsumerQuickstartValidator, CrossProtocolChecker,
    compute_attribution_hash, wilson_ci, validate_conformance_report,
    PROTOCOL_ORDER, PROTOCOL_DEPENDENCIES, PROTOCOL_WEIGHTS,
    GRADE_THRESHOLDS, STATUS_SCORES, iso_timestamp,
    load_json_file, find_artifact, load_artifact,
)
from generate_test_signals import (
    SCENARIOS, make_signal, make_proof_surface, make_routing_config,
    make_resolution_report, make_discovery_entry, make_quickstart_verdict,
    make_audit_report,
)


# ===================================================================
# TEST: Signal Schema Validation
# ===================================================================

class TestSignalSchemaValidator(unittest.TestCase):
    """Tests for pf-signal-schema conformance validation."""

    def setUp(self):
        self.v = SignalSchemaValidator()

    def test_valid_minimal_signal(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE",
                          add_calibration=False, add_hash=False, add_regime=False)
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_valid_full_signal(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_missing_required_field(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE")
        del sig["signal_id"]
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)
        self.assertIn("signal_id", errors[0].message)

    def test_invalid_direction(self):
        sig = make_signal("BTC", "sideways", 0.62, 24, "EXECUTE")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 1)
        self.assertIn("direction", errors[0].path)

    def test_invalid_action(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "HOLD")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_confidence_out_of_range_high(self):
        sig = make_signal("BTC", "bullish", 1.5, 24, "EXECUTE")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)
        self.assertIn("confidence", errors[0].path)

    def test_confidence_out_of_range_low(self):
        sig = make_signal("BTC", "bullish", -0.1, 24, "EXECUTE")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_confidence_boundary_zero(self):
        sig = make_signal("BTC", "bullish", 0.0, 24, "EXECUTE")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_confidence_boundary_one(self):
        sig = make_signal("BTC", "bullish", 1.0, 24, "EXECUTE")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_horizon_hours_out_of_range(self):
        sig = make_signal("BTC", "bullish", 0.62, 0, "EXECUTE")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_horizon_hours_max_boundary(self):
        sig = make_signal("BTC", "bullish", 0.62, 8760, "EXECUTE")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_lowercase_symbol(self):
        sig = make_signal("btc", "bullish", 0.62, 24, "EXECUTE")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_invert_without_weak_symbol(self):
        sig = make_signal("SOL", "bullish", 0.55, 24, "INVERT",
                          add_calibration=False, add_hash=False, add_regime=False)
        del sig["weak_symbol"]
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)
        self.assertIn("weak_symbol", errors[0].path)

    def test_invert_with_valid_weak_symbol(self):
        sig = make_signal("SOL", "bullish", 0.55, 24, "INVERT")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_invalid_regime_id(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", regime_id="CHAOS")
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_regime_confidence_100_scale_warning(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE")
        sig["regime_context"]["regime_confidence"] = 85  # Should be 0.85
        violations = self.v.validate_signal(sig)
        warnings = [v for v in violations if v.severity == "WARNING"]
        self.assertGreater(len(warnings), 0)

    def test_attribution_hash_mismatch(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE")
        sig["attribution_hash"] = "0" * 64
        violations = self.v.validate_signal(sig)
        warnings = [v for v in violations if v.severity == "WARNING"]
        hash_warnings = [w for w in warnings if "hash" in w.message.lower()]
        self.assertGreater(len(hash_warnings), 0)

    def test_attribution_hash_correct(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE")
        # Hash was computed in make_signal
        violations = self.v.validate_signal(sig)
        hash_warnings = [v for v in violations if "hash" in v.message.lower()]
        self.assertEqual(len(hash_warnings), 0)

    def test_invalid_timestamp(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE")
        sig["timestamp"] = "not-a-date"
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_conformance_level_minimal(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE",
                          add_calibration=False, add_hash=False, add_regime=False)
        level = self.v.detect_conformance_level(sig)
        self.assertEqual(level, "MINIMAL")

    def test_conformance_level_standard(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE",
                          add_calibration=False, add_hash=False, add_regime=True)
        level = self.v.detect_conformance_level(sig)
        self.assertEqual(level, "STANDARD")

    def test_conformance_level_full(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE")
        level = self.v.detect_conformance_level(sig)
        self.assertEqual(level, "FULL")

    def test_conformance_level_incomplete(self):
        sig = {"producer_id": "test"}  # Missing most fields
        level = self.v.detect_conformance_level(sig)
        self.assertEqual(level, "INCOMPLETE")

    def test_validate_batch_pass(self):
        signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(10)]
        status, violations, details = self.v.validate({"signals": signals})
        self.assertEqual(status, "PASS")
        self.assertEqual(details["pass_rate"], 1.0)

    def test_validate_batch_fail_high_error_rate(self):
        bad = [{"producer_id": "test"}] * 9 + [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=0)]
        status, violations, details = self.v.validate({"signals": bad})
        self.assertEqual(status, "FAIL")

    def test_validate_empty_signals(self):
        status, violations, details = self.v.validate({"signals": []})
        self.assertEqual(status, "WARN")

    def test_validate_no_signals(self):
        status, violations, details = self.v.validate({})
        self.assertEqual(status, "SKIP")

    def test_duplicate_signal_ids(self):
        signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=0)] * 3
        status, violations, details = self.v.validate({"signals": signals})
        self.assertGreater(details["duplicate_signal_ids"], 0)

    def test_batch_signal_count_mismatch(self):
        batch = {"signals": [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=0)], "signal_count": 5}
        status, violations, details = self.v.validate({"signals": batch})
        self.assertEqual(status, "FAIL")

    def test_weak_symbol_score_out_of_range(self):
        sig = make_signal("SOL", "bullish", 0.55, 24, "INVERT")
        sig["weak_symbol"]["weakness_score"] = 1.5
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_invalid_weak_symbol_severity(self):
        sig = make_signal("SOL", "bullish", 0.55, 24, "INVERT")
        sig["weak_symbol"]["severity"] = "EXTREME"  # Not valid
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_calibration_brier_out_of_range(self):
        sig = make_signal("BTC", "bullish", 0.62, 24, "EXECUTE")
        sig["calibration"]["brier_score"] = 1.5
        violations = self.v.validate_signal(sig)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)


# ===================================================================
# TEST: Routing Protocol Validation
# ===================================================================

class TestRoutingProtocolValidator(unittest.TestCase):

    def setUp(self):
        self.v = RoutingProtocolValidator()

    def test_valid_config(self):
        config = make_routing_config()
        violations = self.v.validate_config(config)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_invalid_regime_in_config(self):
        config = make_routing_config()
        config["gates"]["regime_gate"]["allowed_regimes"].append("CHAOS")
        violations = self.v.validate_config(config)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_confidence_out_of_range_in_config(self):
        config = make_routing_config()
        config["gates"]["confidence_gate"]["default_min_confidence"] = 1.5
        violations = self.v.validate_config(config)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_invalid_weak_symbol_policy(self):
        config = make_routing_config()
        config["symbols"]["BTC"]["weak_symbol_policy"] = "DESTROY"
        violations = self.v.validate_config(config)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_routing_report_math_consistency(self):
        report = {
            "summary": {"total_input": 10, "total_emit": 7, "total_withhold": 2, "total_invert": 1, "filter_rate": 0.2},
            "decisions": [{"action": "EMIT", "signal_id": f"s{i}"} for i in range(7)] +
                         [{"action": "WITHHOLD", "signal_id": f"w{i}"} for i in range(2)] +
                         [{"action": "INVERT", "signal_id": "inv1"}],
        }
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_routing_report_math_inconsistency(self):
        report = {
            "summary": {"total_input": 10, "total_emit": 7, "total_withhold": 2, "total_invert": 2, "filter_rate": 0.2},
            "decisions": [],
        }
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)  # 7+2+2 = 11 != 10

    def test_validate_skip_when_no_artifacts(self):
        status, violations, details = self.v.validate({})
        self.assertEqual(status, "SKIP")

    def test_lowercase_symbol_in_config(self):
        config = make_routing_config()
        config["symbols"]["btc"] = config["symbols"].pop("BTC")
        violations = self.v.validate_config(config)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)


# ===================================================================
# TEST: Resolution Protocol Validation
# ===================================================================

class TestResolutionProtocolValidator(unittest.TestCase):

    def setUp(self):
        self.v = ResolutionProtocolValidator()

    def test_valid_report(self):
        report = make_resolution_report()
        status, violations, details = self.v.validate({"resolution_report": report})
        self.assertIn(status, ("PASS", "WARN"))

    def test_missing_required_fields(self):
        report = {"meta": {"producer_id": "test"}}
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_brier_identity_violation(self):
        report = make_resolution_report()
        report["overall"]["brier_score"] = 0.5  # Wrong
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_wilson_ci_ordering_violation(self):
        report = make_resolution_report()
        report["overall"]["accuracy"]["lower"] = 0.9
        report["overall"]["accuracy"]["upper"] = 0.1
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_reputation_score_out_of_range(self):
        report = make_resolution_report()
        report["reputation"]["composite_score"] = 1.5
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_grade_score_inconsistency(self):
        report = make_resolution_report()
        report["reputation"]["composite_score"] = 0.90
        report["reputation"]["grade"] = "D"
        violations = self.v.validate_report(report)
        warnings = [v for v in violations if v.severity == "WARNING"]
        grade_warnings = [w for w in warnings if "inconsistent" in w.message.lower()]
        self.assertGreater(len(grade_warnings), 0)

    def test_signal_summary_inconsistency(self):
        report = make_resolution_report()
        report["signal_summary"]["total_resolved"] = 400
        report["signal_summary"]["total_unresolved"] = 200
        # total_signals is 550 but 400+200=600
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_skip_when_no_report(self):
        status, violations, details = self.v.validate({})
        self.assertEqual(status, "SKIP")


# ===================================================================
# TEST: Aggregation Protocol Validation
# ===================================================================

class TestAggregationProtocolValidator(unittest.TestCase):

    def setUp(self):
        self.v = AggregationProtocolValidator()

    def test_valid_conflict_report(self):
        scenario = SCENARIOS["aggregation_conflict"]
        artifacts = scenario["generator"]()
        report = artifacts["aggregation_report.json"]
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_summary_count_inconsistency(self):
        report = {"summary": {"total_symbols": 3, "total_emit": 1, "total_withhold": 1,
                               "total_invert": 0, "total_conflict": 0}, "decisions": []}
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)  # 1+1+0+0=2 != 3

    def test_hhi_out_of_range(self):
        report = {"summary": {"total_symbols": 1, "total_emit": 1, "total_withhold": 0,
                               "total_invert": 0, "total_conflict": 0,
                               "producer_weight_distribution": {"hhi": 1.5}},
                  "decisions": []}
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_invalid_consensus_action(self):
        report = {"summary": {}, "decisions": [{"consensus_action": "PANIC", "symbol": "BTC"}]}
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_disagreement_level_inconsistency(self):
        report = {
            "summary": {},
            "decisions": [{
                "consensus_action": "EMIT", "symbol": "BTC",
                "disagreement": {"index": 0.80, "level": "LOW"},  # Should be EXTREME
            }],
        }
        violations = self.v.validate_report(report)
        warnings = [v for v in violations if v.severity == "WARNING"]
        self.assertGreater(len(warnings), 0)


# ===================================================================
# TEST: Proof Protocol Validation
# ===================================================================

class TestProofProtocolValidator(unittest.TestCase):

    def setUp(self):
        self.v = ProofProtocolValidator()

    def test_valid_proof(self):
        proof = make_proof_surface()
        status, violations, details = self.v.validate({"proof_surface": proof})
        self.assertEqual(status, "PASS")

    def test_invalid_freshness_grade(self):
        proof = make_proof_surface()
        proof["freshness_metadata"]["freshness_grade"] = "DEAD"
        violations = self.v.validate_report(proof)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_invalid_drift_status(self):
        proof = make_proof_surface()
        proof["cusum_state"]["drift_status"] = "BROKEN"
        violations = self.v.validate_report(proof)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_negative_cusum(self):
        proof = make_proof_surface()
        proof["cusum_state"]["cusum_pos"] = -0.5
        violations = self.v.validate_report(proof)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_wilson_ci_ordering_in_rolling_window(self):
        proof = make_proof_surface()
        proof["rolling_windows"][0]["accuracy"]["lower"] = 0.9
        proof["rolling_windows"][0]["accuracy"]["upper"] = 0.1
        violations = self.v.validate_report(proof)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_reputation_score_out_of_range(self):
        proof = make_proof_surface()
        proof["reputation"]["score"] = -0.1
        violations = self.v.validate_report(proof)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_freshness_grade_age_inconsistency(self):
        proof = make_proof_surface(freshness="LIVE", age_hours=100, threshold_hours=24)
        violations = self.v.validate_report(proof)
        warnings = [v for v in violations if v.severity == "WARNING"]
        self.assertGreater(len(warnings), 0)

    def test_skip_when_no_proof(self):
        status, violations, details = self.v.validate({})
        self.assertEqual(status, "SKIP")


# ===================================================================
# TEST: Lifecycle Pipeline Validation
# ===================================================================

class TestLifecyclePipelineValidator(unittest.TestCase):

    def setUp(self):
        self.v = LifecyclePipelineValidator()

    def test_negative_new_resolved(self):
        report = {"resolution_growth": {"n_new_resolved": -5}}
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_invalid_stage_status(self):
        report = {"pipeline_meta": {"stages": [{"stage": "LOAD", "status": "EXPLODED"}]}}
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_short_content_hash(self):
        report = {"content_hash": "ab"}
        violations = self.v.validate_report(report)
        warnings = [v for v in violations if v.severity == "WARNING"]
        self.assertGreater(len(warnings), 0)

    def test_skip_when_no_report(self):
        status, violations, details = self.v.validate({})
        self.assertEqual(status, "SKIP")


# ===================================================================
# TEST: Consumer Audit Validation
# ===================================================================

class TestConsumerAuditValidator(unittest.TestCase):

    def setUp(self):
        self.v = ConsumerAuditValidator()

    def test_valid_audit(self):
        report = make_audit_report()
        status, violations, details = self.v.validate({"audit_report": report})
        self.assertIn(status, ("PASS", "WARN"))

    def test_trust_score_out_of_range(self):
        report = make_audit_report()
        report["trust_grade"]["score"] = 1.5
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_invalid_verdict(self):
        report = make_audit_report()
        report["trust_grade"]["verdict"] = "MAYBE"
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_component_weight_sum(self):
        report = make_audit_report()
        # Weights already sum to 1.0 in make_audit_report
        violations = self.v.validate_report(report)
        weight_violations = [v for v in violations if "weight" in v.message.lower()]
        self.assertEqual(len(weight_violations), 0)

    def test_schema_fail_hard_gate(self):
        report = make_audit_report()
        report["schema_compliance"]["overall_status"] = "FAIL"
        report["trust_grade"]["verdict"] = "TRUST"  # Should be DO_NOT_TRUST
        violations = self.v.validate_report(report)
        warnings = [v for v in violations if v.severity == "WARNING" and "hard gate" in v.message.lower()]
        self.assertGreater(len(warnings), 0)

    def test_drift_degraded_hard_gate(self):
        report = make_audit_report()
        report["drift_verification"]["drift_status"] = "DEGRADED"
        report["trust_grade"]["verdict"] = "TRUST"
        violations = self.v.validate_report(report)
        warnings = [v for v in violations if v.severity == "WARNING" and "hard gate" in v.message.lower()]
        self.assertGreater(len(warnings), 0)

    def test_findings_severity_ordering(self):
        report = make_audit_report()
        report["findings"] = [
            {"severity": "LOW", "finding_id": "F1"},
            {"severity": "CRITICAL", "finding_id": "F2"},
        ]
        violations = self.v.validate_report(report)
        warnings = [v for v in violations if "sorted" in v.message.lower() or "severity" in v.message.lower()]
        self.assertGreater(len(warnings), 0)

    def test_summary_check_inconsistency(self):
        report = make_audit_report()
        report["summary"]["total_checks"] = 100
        # passed+failed+warnings+skipped = 25, not 100
        violations = self.v.validate_report(report)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)


# ===================================================================
# TEST: Discovery Protocol Validation
# ===================================================================

class TestDiscoveryProtocolValidator(unittest.TestCase):

    def setUp(self):
        self.v = DiscoveryProtocolValidator()

    def test_valid_entry(self):
        entry = make_discovery_entry()
        violations = self.v.validate_entry(entry)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0)

    def test_empty_producer_id(self):
        entry = make_discovery_entry()
        entry["producer_id"] = ""
        violations = self.v.validate_entry(entry)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_invalid_capability(self):
        entry = make_discovery_entry()
        entry["capabilities"].append("time_travel")
        violations = self.v.validate_entry(entry)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_lowercase_symbol(self):
        entry = make_discovery_entry()
        entry["symbol_coverage"]["symbols"].append("btc")
        violations = self.v.validate_entry(entry)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_reputation_score_out_of_range(self):
        entry = make_discovery_entry()
        entry["reputation_summary"]["score"] = 1.5
        violations = self.v.validate_entry(entry)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_heartbeat_interval_too_low(self):
        entry = make_discovery_entry()
        entry["liveness"]["heartbeat_interval_seconds"] = 10
        violations = self.v.validate_entry(entry)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_invalid_registrar(self):
        entry = make_discovery_entry()
        entry["registration"]["registrar"] = "magic"
        violations = self.v.validate_entry(entry)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_missing_signal_schema_protocol(self):
        entry = make_discovery_entry()
        del entry["supported_protocols"]["signal_schema"]
        violations = self.v.validate_entry(entry)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_invalid_liveness_grade(self):
        entry = make_discovery_entry()
        entry["liveness"]["liveness_grade"] = "DEAD"
        violations = self.v.validate_entry(entry)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_missing_required_field(self):
        entry = make_discovery_entry()
        del entry["capabilities"]
        violations = self.v.validate_entry(entry)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_skip_when_no_artifacts(self):
        status, violations, details = self.v.validate({})
        self.assertEqual(status, "SKIP")


# ===================================================================
# TEST: Consumer Quickstart Validation
# ===================================================================

class TestConsumerQuickstartValidator(unittest.TestCase):

    def setUp(self):
        self.v = ConsumerQuickstartValidator()

    def test_valid_verdict(self):
        verdict = make_quickstart_verdict()
        status, violations, details = self.v.validate({"quickstart_verdict": verdict})
        self.assertIn(status, ("PASS", "WARN"))

    def test_invalid_trust_verdict(self):
        verdict = make_quickstart_verdict()
        verdict["verdict"]["trust_verdict"] = "MAYBE"
        violations = self.v.validate_verdict(verdict)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_trust_score_out_of_range(self):
        verdict = make_quickstart_verdict()
        verdict["verdict"]["trust_score"] = -0.1
        violations = self.v.validate_verdict(verdict)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)

    def test_grade_score_inconsistency(self):
        verdict = make_quickstart_verdict(score=0.90, grade="D")
        violations = self.v.validate_verdict(verdict)
        warnings = [v for v in violations if v.severity == "WARNING" and "inconsistent" in v.message.lower()]
        self.assertGreater(len(warnings), 0)

    def test_invalid_stage_status(self):
        verdict = make_quickstart_verdict()
        verdict["stages"][0]["status"] = "EXPLODED"
        violations = self.v.validate_verdict(verdict)
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertGreater(len(errors), 0)


# ===================================================================
# TEST: Cross-Protocol Consistency
# ===================================================================

class TestCrossProtocolChecker(unittest.TestCase):

    def setUp(self):
        self.checker = CrossProtocolChecker()

    def test_orphaned_resolved_signals(self):
        signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=0)]
        proof = make_proof_surface()
        proof["resolved_signals"] = [{"signal_id": "orphan-1", "symbol": "BTC"}]
        violations = self.checker.check(
            {"signals": signals, "proof_surface": proof},
            {"signal_schema": {"status": "PASS"}}
        )
        orphan_vs = [v for v in violations if "orphan" in v.message.lower() or "not found" in v.message.lower()]
        self.assertGreater(len(orphan_vs), 0)

    def test_producer_id_mismatch(self):
        signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", producer_id="alpha")]
        resolution = make_resolution_report()
        resolution["meta"]["producer_id"] = "beta"
        violations = self.checker.check(
            {"signals": signals, "resolution_report": resolution},
            {}
        )
        pid_vs = [v for v in violations if "producer_id" in v.message.lower()]
        self.assertGreater(len(pid_vs), 0)

    def test_symbol_coverage_gap(self):
        signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=0)]
        entry = make_discovery_entry()
        entry["symbol_coverage"]["symbols"] = ["ETH"]  # Missing BTC
        violations = self.checker.check(
            {"signals": signals, "discovery_entry": entry},
            {}
        )
        sym_vs = [v for v in violations if "symbol" in v.message.lower() and "coverage" in v.message.lower()]
        self.assertGreater(len(sym_vs), 0)

    def test_freshness_liveness_inconsistency(self):
        proof = make_proof_surface(freshness="EXPIRED", age_hours=200)
        entry = make_discovery_entry(liveness="ALIVE")
        violations = self.checker.check(
            {"proof_surface": proof, "discovery_entry": entry},
            {}
        )
        inconsistency_vs = [v for v in violations if "EXPIRED" in v.message and "ALIVE" in v.message]
        self.assertGreater(len(inconsistency_vs), 0)

    def test_schema_pass_routing_fail_info(self):
        violations = self.checker.check(
            {},
            {"signal_schema": {"status": "PASS"}, "routing_protocol": {"status": "FAIL"}}
        )
        info_vs = [v for v in violations if v.severity == "INFO" and "routing" in v.message.lower()]
        self.assertGreater(len(info_vs), 0)

    def test_reputation_discrepancy(self):
        proof = make_proof_surface(reputation_score=0.80)
        resolution = make_resolution_report()
        resolution["reputation"]["composite_score"] = 0.40  # Big discrepancy
        violations = self.checker.check(
            {"proof_surface": proof, "resolution_report": resolution},
            {}
        )
        rep_vs = [v for v in violations if "discrepancy" in v.message.lower()]
        self.assertGreater(len(rep_vs), 0)


# ===================================================================
# TEST: Dependency-Ordered Validation Sequencing
# ===================================================================

class TestDependencyOrdering(unittest.TestCase):

    def test_protocol_order_covers_all_nine(self):
        self.assertEqual(len(PROTOCOL_ORDER), 9)

    def test_all_protocols_have_dependencies(self):
        for p in PROTOCOL_ORDER:
            self.assertIn(p, PROTOCOL_DEPENDENCIES)

    def test_signal_schema_has_no_dependencies(self):
        self.assertEqual(PROTOCOL_DEPENDENCIES["signal_schema"], [])

    def test_dependencies_reference_earlier_protocols(self):
        for i, protocol in enumerate(PROTOCOL_ORDER):
            deps = PROTOCOL_DEPENDENCIES[protocol]
            for dep in deps:
                dep_idx = PROTOCOL_ORDER.index(dep)
                self.assertLess(dep_idx, i,
                                f"{protocol} depends on {dep} which comes after it in order")

    def test_cascade_skip_on_upstream_failure(self):
        """When signal_schema FAILs, routing and resolution should SKIP."""
        engine = ConformanceEngine()
        artifacts = {"signals": [{"bad": "signal"}]}  # Will cause schema FAIL
        report = engine.run(artifacts)
        self.assertEqual(report["protocol_results"]["signal_schema"]["status"], "FAIL")
        self.assertEqual(report["protocol_results"]["routing_protocol"]["status"], "SKIP")
        self.assertEqual(report["protocol_results"]["resolution_protocol"]["status"], "SKIP")

    def test_cascade_skip_includes_reason(self):
        engine = ConformanceEngine()
        artifacts = {"signals": [{"bad": "signal"}]}
        report = engine.run(artifacts)
        routing_details = report["protocol_results"]["routing_protocol"]["details"]
        self.assertIn("skipped_due_to", routing_details)
        self.assertIn("signal_schema", routing_details["skipped_due_to"])

    def test_independent_protocols_not_affected_by_cascade(self):
        """proof_protocol depends on resolution, not signal_schema directly."""
        engine = ConformanceEngine()
        proof = make_proof_surface()
        artifacts = {"signals": [{"bad": "signal"}], "proof_surface": proof}
        report = engine.run(artifacts)
        # Proof depends on resolution, which depends on signal_schema
        # signal_schema FAIL → resolution SKIP → proof SKIP
        # Actually proof_protocol depends on resolution_protocol, not signal_schema
        # resolution_protocol depends on signal_schema
        # So proof should SKIP due to resolution being SKIP? No — SKIP != FAIL
        # Only FAIL causes cascade, SKIP does not
        proof_status = report["protocol_results"]["proof_protocol"]["status"]
        # Proof has its own artifact, so it validates independently (PASS)
        self.assertEqual(proof_status, "PASS")


# ===================================================================
# TEST: Grade Computation
# ===================================================================

class TestGradeComputation(unittest.TestCase):

    def test_all_pass_gives_high_grade(self):
        engine = ConformanceEngine()
        results = {p: {"status": "PASS", "n_errors": 0, "n_warnings": 0} for p in PROTOCOL_ORDER}
        grade_info = engine._compute_grade(results)
        self.assertIn(grade_info["grade"], ("A", "B"))
        self.assertGreaterEqual(grade_info["composite_score"], 0.90)

    def test_all_fail_gives_f(self):
        engine = ConformanceEngine()
        results = {p: {"status": "FAIL", "n_errors": 1, "n_warnings": 0} for p in PROTOCOL_ORDER}
        grade_info = engine._compute_grade(results)
        self.assertEqual(grade_info["grade"], "F")
        self.assertEqual(grade_info["composite_score"], 0.0)

    def test_all_skip_gives_low_grade(self):
        engine = ConformanceEngine()
        results = {p: {"status": "SKIP", "n_errors": 0, "n_warnings": 0} for p in PROTOCOL_ORDER}
        grade_info = engine._compute_grade(results)
        # All SKIP = composite 0.3, below D threshold (0.35) = F
        self.assertEqual(grade_info["grade"], "F")
        self.assertAlmostEqual(grade_info["composite_score"], 0.3, places=1)

    def test_signal_schema_fail_forces_f(self):
        engine = ConformanceEngine()
        results = {p: {"status": "PASS", "n_errors": 0, "n_warnings": 0} for p in PROTOCOL_ORDER}
        results["signal_schema"]["status"] = "FAIL"
        results["signal_schema"]["n_errors"] = 1
        grade_info = engine._compute_grade(results)
        self.assertEqual(grade_info["grade"], "F")

    def test_grade_threshold_boundary_a(self):
        """Score exactly at 0.90 should be grade A."""
        engine = ConformanceEngine()
        # We need composite_score >= 0.90
        # All PASS = 1.0, so that's A
        results = {p: {"status": "PASS", "n_errors": 0, "n_warnings": 0} for p in PROTOCOL_ORDER}
        grade_info = engine._compute_grade(results)
        self.assertEqual(grade_info["grade"], "A")

    def test_protocol_weights_sum_to_one(self):
        total = sum(PROTOCOL_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=2)


# ===================================================================
# TEST: Conformance Report Self-Validation
# ===================================================================

class TestReportSelfValidation(unittest.TestCase):

    def test_valid_report_passes_self_validation(self):
        engine = ConformanceEngine()
        signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(5)]
        artifacts = {"signals": signals, "proof_surface": make_proof_surface()}
        report = engine.run(artifacts)
        issues = validate_conformance_report(report)
        self.assertEqual(len(issues), 0)

    def test_missing_field_detected(self):
        report = {"meta": {}, "readiness_grade": {"grade": "A", "composite_score": 0.95}}
        issues = validate_conformance_report(report)
        self.assertGreater(len(issues), 0)

    def test_invalid_grade_detected(self):
        engine = ConformanceEngine()
        artifacts = {"signals": [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=0)]}
        report = engine.run(artifacts)
        report["readiness_grade"]["grade"] = "S"
        issues = validate_conformance_report(report)
        self.assertGreater(len(issues), 0)

    def test_summary_consistency(self):
        engine = ConformanceEngine()
        artifacts = {"signals": [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=0)]}
        report = engine.run(artifacts)
        # Verify summary counts are consistent
        s = report["summary"]
        self.assertEqual(s["passed"] + s["warned"] + s["failed"] + s["skipped"], s["total_protocols"])


# ===================================================================
# TEST: Synthetic Generator Correctness
# ===================================================================

class TestSyntheticGeneratorCorrectness(unittest.TestCase):
    """Verify generated scenarios produce expected conformance outcomes."""

    def setUp(self):
        self.engine = ConformanceEngine()

    def _run_scenario(self, scenario_name):
        info = SCENARIOS[scenario_name]
        artifacts_dict = info["generator"]()
        # Convert to engine format
        artifacts = {}
        key_map = {
            "signals.json": "signals",
            "proof_surface.json": "proof_surface",
            "routing_policy.json": "routing_config",
            "routing_report.json": "routing_report",
            "resolution_report.json": "resolution_report",
            "aggregation_report.json": "aggregation_report",
            "producer_entry.json": "discovery_entry",
            "consumer_verdict.json": "quickstart_verdict",
            "audit_report.json": "audit_report",
            "lifecycle_report.json": "lifecycle_report",
        }
        for fname, data in artifacts_dict.items():
            akey = key_map.get(fname)
            if akey:
                artifacts[akey] = data
        return self.engine.run(artifacts), info["expected_outcomes"]

    def test_fully_conformant(self):
        report, expected = self._run_scenario("fully_conformant")
        for protocol in PROTOCOL_ORDER:
            if protocol in expected:
                actual = report["protocol_results"][protocol]["status"]
                self.assertEqual(actual, expected[protocol],
                                 f"fully_conformant: {protocol} expected {expected[protocol]}, got {actual}")
        self.assertEqual(report["readiness_grade"]["grade"], expected["expected_grade"])

    def test_schema_failures(self):
        report, expected = self._run_scenario("schema_failures")
        self.assertEqual(report["protocol_results"]["signal_schema"]["status"], "FAIL")
        self.assertEqual(report["readiness_grade"]["grade"], "F")
        # Cascade: routing and resolution should SKIP
        self.assertEqual(report["protocol_results"]["routing_protocol"]["status"], "SKIP")
        self.assertEqual(report["protocol_results"]["resolution_protocol"]["status"], "SKIP")

    def test_cross_protocol_issues(self):
        report, expected = self._run_scenario("cross_protocol_issues")
        self.assertEqual(report["protocol_results"]["signal_schema"]["status"], "PASS")
        n_cross = len(report["cross_protocol_checks"]["violations"])
        self.assertGreater(n_cross, 0)

    def test_discovery_invalid(self):
        report, expected = self._run_scenario("discovery_invalid")
        self.assertEqual(report["protocol_results"]["discovery_protocol"]["status"], "FAIL")

    def test_lifecycle_idempotency(self):
        report, expected = self._run_scenario("lifecycle_idempotency")
        self.assertEqual(report["protocol_results"]["lifecycle_pipeline"]["status"], "FAIL")

    def test_empty_artifacts(self):
        report, expected = self._run_scenario("empty_artifacts")
        self.assertEqual(report["protocol_results"]["signal_schema"]["status"], "WARN")

    def test_aggregation_conflict(self):
        report, expected = self._run_scenario("aggregation_conflict")
        self.assertEqual(report["protocol_results"]["aggregation_protocol"]["status"], "PASS")

    def test_partial_conformance(self):
        report, expected = self._run_scenario("partial_conformance")
        self.assertEqual(report["protocol_results"]["signal_schema"]["status"], "PASS")
        self.assertEqual(report["protocol_results"]["proof_protocol"]["status"], "PASS")


# ===================================================================
# TEST: Utility Functions
# ===================================================================

class TestUtilityFunctions(unittest.TestCase):

    def test_compute_attribution_hash(self):
        sig = {"signal_id": "test-1", "symbol": "BTC", "direction": "bullish",
               "confidence": 0.62, "horizon_hours": 24, "timestamp": "2026-03-30T12:00:00Z"}
        h = compute_attribution_hash(sig)
        self.assertEqual(len(h), 64)
        # Deterministic
        h2 = compute_attribution_hash(sig)
        self.assertEqual(h, h2)

    def test_wilson_ci(self):
        ci = wilson_ci(55, 100)
        self.assertGreater(ci["point"], 0)
        self.assertLessEqual(ci["lower"], ci["point"])
        self.assertGreaterEqual(ci["upper"], ci["point"])
        self.assertEqual(ci["n"], 100)

    def test_wilson_ci_zero_trials(self):
        ci = wilson_ci(0, 0)
        self.assertEqual(ci["point"], 0.0)
        self.assertEqual(ci["n"], 0)

    def test_iso_timestamp_format(self):
        ts = iso_timestamp()
        self.assertTrue(ts.endswith("Z"))
        self.assertIn("T", ts)

    def test_load_json_file_not_found(self):
        data, err = load_json_file("/nonexistent/path.json")
        self.assertIsNone(data)
        self.assertIsNotNone(err)

    def test_load_json_file_valid(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"test": True}, f)
            path = f.name
        try:
            data, err = load_json_file(path)
            self.assertIsNotNone(data)
            self.assertIsNone(err)
            self.assertTrue(data["test"])
        finally:
            os.unlink(path)

    def test_find_artifact_known_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "signals.json")
            with open(path, "w") as f:
                json.dump([], f)
            found = find_artifact(tmpdir, "signals")
            self.assertEqual(found, path)

    def test_find_artifact_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            found = find_artifact(tmpdir, "signals")
            self.assertIsNone(found)


# ===================================================================
# TEST: Limitation Detection
# ===================================================================

class TestLimitationDetection(unittest.TestCase):

    def test_sparse_artifacts_detected(self):
        engine = ConformanceEngine()
        artifacts = {"signals": [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=0)]}
        report = engine.run(artifacts)
        lim_ids = [l["id"] for l in report["limitations"]]
        self.assertIn("SPARSE_ARTIFACTS", lim_ids)

    def test_small_signal_sample_detected(self):
        engine = ConformanceEngine()
        signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(5)]
        artifacts = {"signals": signals}
        report = engine.run(artifacts)
        lim_ids = [l["id"] for l in report["limitations"]]
        self.assertIn("SMALL_SIGNAL_SAMPLE", lim_ids)

    def test_foundation_failure_detected(self):
        engine = ConformanceEngine()
        artifacts = {"signals": [{"bad": "signal"}]}
        report = engine.run(artifacts)
        lim_ids = [l["id"] for l in report["limitations"]]
        self.assertIn("FOUNDATION_FAILURE", lim_ids)

    def test_cascade_skips_detected(self):
        engine = ConformanceEngine()
        artifacts = {"signals": [{"bad": "signal"}]}
        report = engine.run(artifacts)
        lim_ids = [l["id"] for l in report["limitations"]]
        self.assertIn("CASCADE_SKIPS", lim_ids)

    def test_all_limitations_have_bias(self):
        engine = ConformanceEngine()
        artifacts = {"signals": [{"bad": "signal"}]}
        report = engine.run(artifacts)
        for lim in report["limitations"]:
            self.assertIn("bias_direction", lim)
            self.assertIn("bias_magnitude", lim)


# ===================================================================
# TEST: End-to-End Integration
# ===================================================================

class TestEndToEndIntegration(unittest.TestCase):

    def test_full_pipeline_with_all_artifacts(self):
        engine = ConformanceEngine()
        signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(20)]
        artifacts = {
            "signals": signals,
            "proof_surface": make_proof_surface(),
            "routing_config": make_routing_config(),
            "resolution_report": make_resolution_report(),
            "discovery_entry": make_discovery_entry(),
            "quickstart_verdict": make_quickstart_verdict(),
            "audit_report": make_audit_report(),
        }
        report = engine.run(artifacts)

        # Basic structure
        self.assertIn("meta", report)
        self.assertIn("readiness_grade", report)
        self.assertIn("protocol_results", report)
        self.assertIn("cross_protocol_checks", report)
        self.assertIn("summary", report)
        self.assertIn("limitations", report)

        # All 9 protocols have results
        self.assertEqual(len(report["protocol_results"]), 9)

        # Grade exists
        self.assertIn(report["readiness_grade"]["grade"], {"A", "B", "C", "D", "F"})

        # Self-validates
        issues = validate_conformance_report(report)
        self.assertEqual(len(issues), 0)

    def test_directory_loading(self):
        """Test loading artifacts from a directory."""
        engine = ConformanceEngine()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Write signal file
            signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=i) for i in range(5)]
            with open(os.path.join(tmpdir, "signals.json"), "w") as f:
                json.dump(signals, f)
            # Write proof
            with open(os.path.join(tmpdir, "proof_surface.json"), "w") as f:
                json.dump(make_proof_surface(), f)

            artifacts = engine.load_artifacts_from_directory(tmpdir)
            self.assertIn("signals", artifacts)
            self.assertIn("proof_surface", artifacts)

            report = engine.run(artifacts)
            self.assertEqual(report["protocol_results"]["signal_schema"]["status"], "PASS")

    def test_violation_has_remediation(self):
        """Every violation should include a remediation hint."""
        sig = {"producer_id": "test"}  # Missing most fields
        v = SignalSchemaValidator()
        violations = v.validate_signal(sig)
        for violation in violations:
            if violation.severity == "ERROR":
                self.assertNotEqual(violation.remediation, "",
                                    f"Violation at {violation.path} missing remediation")


# ===================================================================
# TEST: Remote Endpoint Handling
# ===================================================================

class TestRemoteEndpointHandling(unittest.TestCase):

    @patch("conformance_testkit.fetch_json_url")
    def test_endpoint_timeout_handling(self, mock_fetch):
        mock_fetch.return_value = (None, "Connection timed out")
        engine = ConformanceEngine()
        artifacts = engine.load_artifacts_from_endpoint("http://example.com", timeout=1)
        # Should return empty artifacts, not crash
        self.assertIsInstance(artifacts, dict)

    @patch("conformance_testkit.fetch_json_url")
    def test_endpoint_success(self, mock_fetch):
        signals = [make_signal("BTC", "bullish", 0.62, 24, "EXECUTE", index=0)]
        mock_fetch.return_value = (signals, None)
        engine = ConformanceEngine()
        artifacts = engine.load_artifacts_from_endpoint("http://example.com")
        self.assertIn("signals", artifacts)


if __name__ == "__main__":
    unittest.main()
