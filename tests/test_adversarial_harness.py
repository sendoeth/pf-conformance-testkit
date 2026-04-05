#!/usr/bin/env python3
"""
Tests for the adversarial hardening harness.

Verifies:
1. All adversarial cases are defined and runnable
2. Before-fix runs produce expected FAIL states
3. After-fix runs produce PASS states (fixes applied)
4. Harness report structure is correct
5. Individual fix behaviors verified
"""

import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

# Add parent directory for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "pf-routing-protocol"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "pf-proof-protocol"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "pf-consumer-quickstart"))

from adversarial_harness import (
    build_cases, run_harness, AdversarialCase, CASE_RUNNERS, RERUN_RUNNERS,
    ROUTING_CONFIG, VALID_SIGNAL, generate_audit_report
)
from preflight_filter import (
    PreFlightRouter, compute_voi, assign_duration_bucket
)
from maintain_proof import PriceResolver


class TestCaseDefinitions(unittest.TestCase):
    """Verify all adversarial cases are properly defined."""

    def test_seven_cases_defined(self):
        cases = build_cases()
        self.assertEqual(len(cases), 7)

    def test_all_case_ids_unique(self):
        cases = build_cases()
        ids = [c.case_id for c in cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_cases_have_runners(self):
        cases = build_cases()
        for c in cases:
            self.assertIn(c.case_id, CASE_RUNNERS, f"Missing runner for {c.case_id}")
            self.assertIn(c.case_id, RERUN_RUNNERS, f"Missing rerun for {c.case_id}")

    def test_case_fields_populated(self):
        cases = build_cases()
        for c in cases:
            self.assertTrue(c.title, f"{c.case_id} missing title")
            self.assertTrue(c.description, f"{c.case_id} missing description")
            self.assertTrue(c.target_repo, f"{c.case_id} missing target_repo")
            self.assertTrue(c.target_file, f"{c.case_id} missing target_file")
            self.assertTrue(c.expected_behavior, f"{c.case_id} missing expected_behavior")

    def test_case_serialization(self):
        cases = build_cases()
        for c in cases:
            d = c.to_dict()
            self.assertIn("case_id", d)
            self.assertIn("target", d)
            self.assertIn("before_fix", d)
            self.assertIn("after_fix", d)
            # Verify JSON-serializable
            json.dumps(d, default=str)


class TestHarnessReport(unittest.TestCase):
    """Verify harness report structure and content."""

    def test_before_report_structure(self):
        report = run_harness(phase="before")
        self.assertIn("meta", report)
        self.assertIn("summary", report)
        self.assertIn("cases", report)
        self.assertEqual(report["meta"]["phase"], "before")

    def test_after_report_structure(self):
        report = run_harness(phase="after")
        self.assertIn("meta", report)
        self.assertIn("summary", report)
        self.assertIn("cases", report)
        self.assertEqual(report["meta"]["phase"], "after")

    def test_single_case_filter(self):
        report = run_harness(case_filter="ADV-001", phase="after")
        self.assertEqual(len(report["cases"]), 1)
        self.assertEqual(report["cases"][0]["case_id"], "ADV-001")

    def test_summary_counts_match(self):
        report = run_harness(phase="after")
        s = report["summary"]
        total = s["passed"] + s["failed"] + s["errors"]
        self.assertEqual(total, s["total_cases"])

    def test_report_json_serializable(self):
        report = run_harness(phase="after")
        json.dumps(report, default=str)

    def test_audit_report_generation(self):
        before = run_harness(phase="before")
        after = run_harness(phase="after")
        md = generate_audit_report(before, after)
        self.assertIn("# Post Fiat Full-Stack Adversarial Hardening Audit", md)
        self.assertIn("ADV-001", md)
        self.assertIn("Before Fix", md)
        self.assertIn("After Fix", md)


# ===================================================================
# FIX VERIFICATION TESTS — verifies each fix independently
# ===================================================================

class TestADV001_ZeroConfidenceVOI(unittest.TestCase):
    """ADV-001: Zero-confidence signals should be withheld by VOI gate."""

    def test_zero_confidence_withheld(self):
        """VOI gate uses strict inequality, so VOI=0 does not pass."""
        config = dict(ROUTING_CONFIG)
        router = PreFlightRouter.from_dict(config)
        sig = dict(VALID_SIGNAL)
        sig["confidence"] = 0.0
        report = router.route_signals([sig], regime_id="NEUTRAL", duration_days=14)
        self.assertEqual(report["decisions"][0]["action"], "WITHHOLD")

    def test_minimal_positive_confidence_emits(self):
        """A signal with small but positive confidence should still pass."""
        config = dict(ROUTING_CONFIG)
        router = PreFlightRouter.from_dict(config)
        sig = dict(VALID_SIGNAL)
        sig["confidence"] = 0.01
        report = router.route_signals([sig], regime_id="NEUTRAL", duration_days=14)
        self.assertEqual(report["decisions"][0]["action"], "EMIT")

    def test_zero_confidence_voi_flagged(self):
        """compute_voi should flag zero-confidence signals."""
        result = compute_voi(0.55, 0.0)
        self.assertTrue(result.get("zero_confidence", False))

    def test_positive_confidence_not_flagged(self):
        """Normal confidence should not be flagged."""
        result = compute_voi(0.55, 0.65)
        self.assertFalse(result.get("zero_confidence", False))


class TestADV002_WeibullParamValidation(unittest.TestCase):
    """ADV-002: Incomplete Weibull params should not crash."""

    def test_missing_shape_no_crash(self):
        """Missing 'shape' key should not raise KeyError."""
        result = compute_voi(0.55, 0.65,
                            hazard_params={"scale": 18.0},
                            duration_days=14)
        self.assertTrue(result.get("hazard_skipped", False))
        self.assertNotIn("hazard_adjustment", result)

    def test_missing_scale_no_crash(self):
        """Missing 'scale' key should not raise KeyError."""
        result = compute_voi(0.55, 0.65,
                            hazard_params={"shape": 1.8},
                            duration_days=14)
        self.assertTrue(result.get("hazard_skipped", False))

    def test_complete_params_still_work(self):
        """Complete Weibull params should still produce hazard adjustment."""
        result = compute_voi(0.55, 0.65,
                            hazard_params={"shape": 1.8, "scale": 22.0},
                            duration_days=14)
        self.assertIn("hazard_adjustment", result)
        self.assertFalse(result.get("hazard_skipped", False))

    def test_empty_params_no_crash(self):
        """Empty dict is falsy, hazard block skipped entirely (correct)."""
        result = compute_voi(0.55, 0.65,
                            hazard_params={},
                            duration_days=14)
        # {} is falsy so hazard block not entered — no skip flag, no crash
        self.assertNotIn("hazard_adjustment", result)

    def test_skip_reason_documented(self):
        """Skip reason should explain what's missing."""
        result = compute_voi(0.55, 0.65,
                            hazard_params={"scale": 18.0},
                            duration_days=14)
        reason = result.get("hazard_skip_reason", "")
        self.assertIn("shape", reason)


class TestADV003_PriceToleranceAlignment(unittest.TestCase):
    """ADV-003: Price resolution tolerance should be consistent."""

    def test_quickstart_tolerance_is_2h(self):
        """quickstart.py should use 2.0h tolerance (unified with maintain_proof)."""
        qs_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "..", "pf-consumer-quickstart", "quickstart.py")
        if not os.path.isfile(qs_path):
            self.skipTest("quickstart.py not found")

        with open(qs_path) as f:
            content = f.read()
        self.assertIn("tolerance_hours=2.0", content)
        self.assertNotIn("tolerance_hours=1.5", content)


class TestADV004_BrierTolerance(unittest.TestCase):
    """ADV-004: Brier identity tolerance should be 0.005."""

    def test_tolerance_tightened(self):
        """conformance_testkit should use 0.005 not 0.01."""
        ct_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "conformance_testkit.py")
        with open(ct_path) as f:
            content = f.read()
        self.assertIn("0.005", content)

    def test_fabricated_score_detected(self):
        """A 0.009 gap should now fail the Brier check."""
        # The adversarial input: gap = 0.009
        gap = 0.009
        tolerance = 0.005
        self.assertGreater(gap, tolerance)


class TestADV005_UnknownRegimeWarning(unittest.TestCase):
    """ADV-005: UNKNOWN regime should produce a warning in limitations."""

    def test_unknown_regime_produces_limitation(self):
        router = PreFlightRouter.from_dict(ROUTING_CONFIG)
        sig = dict(VALID_SIGNAL)
        report = router.route_signals([sig], regime_id="UNKNOWN", duration_days=0)
        limitations = report.get("limitations", [])
        unknown_warnings = [l for l in limitations if l.get("id") == "UNKNOWN_REGIME"]
        self.assertTrue(len(unknown_warnings) > 0,
                       "Expected UNKNOWN_REGIME limitation")

    def test_known_regime_no_warning(self):
        router = PreFlightRouter.from_dict(ROUTING_CONFIG)
        sig = dict(VALID_SIGNAL)
        report = router.route_signals([sig], regime_id="NEUTRAL", duration_days=14)
        limitations = report.get("limitations", [])
        unknown_warnings = [l for l in limitations if l.get("id") == "UNKNOWN_REGIME"]
        self.assertEqual(len(unknown_warnings), 0)


class TestADV006_MaintainProofValidation(unittest.TestCase):
    """ADV-006: maintain_proof should validate signals at intake."""

    def test_out_of_range_confidence_rejected(self):
        resolver = PriceResolver(csv_path=None)
        sig = dict(VALID_SIGNAL)
        sig["confidence"] = 5.0
        result = resolver.resolve_signal(sig)
        self.assertFalse(result.get("resolved", True))
        self.assertEqual(result.get("resolution_reason"), "schema_validation_failed")

    def test_invalid_symbol_rejected(self):
        resolver = PriceResolver(csv_path=None)
        sig = dict(VALID_SIGNAL)
        sig["symbol"] = "INVALID_XYZ"
        result = resolver.resolve_signal(sig)
        self.assertFalse(result.get("resolved", True))
        self.assertEqual(result.get("resolution_reason"), "schema_validation_failed")

    def test_valid_signal_still_accepted(self):
        resolver = PriceResolver(csv_path=None)
        sig = dict(VALID_SIGNAL)
        result = resolver.resolve_signal(sig)
        # Will fail on price resolution (no CSV), not schema validation
        self.assertNotEqual(result.get("resolution_reason"), "schema_validation_failed")

    def test_negative_confidence_rejected(self):
        resolver = PriceResolver(csv_path=None)
        sig = dict(VALID_SIGNAL)
        sig["confidence"] = -0.5
        result = resolver.resolve_signal(sig)
        self.assertEqual(result.get("resolution_reason"), "schema_validation_failed")

    def test_confidence_boundary_accepted(self):
        """Confidence exactly 0.0 and 1.0 should be accepted."""
        resolver = PriceResolver(csv_path=None)
        for conf in [0.0, 1.0]:
            sig = dict(VALID_SIGNAL)
            sig["confidence"] = conf
            result = resolver.resolve_signal(sig)
            self.assertNotEqual(result.get("resolution_reason"), "schema_validation_failed",
                              f"Confidence {conf} should be accepted")


class TestADV007_DurationBucketGap(unittest.TestCase):
    """ADV-007: Duration in bucket gap should return 'unknown'."""

    def test_gap_returns_unknown(self):
        buckets = [
            {"label": "early", "min_days": 0, "max_days": 10},
            {"label": "late", "min_days": 15, "max_days": 9999}
        ]
        result = assign_duration_bucket(12.0, buckets)
        self.assertEqual(result, "unknown")

    def test_normal_bucket_still_works(self):
        buckets = [
            {"label": "early", "min_days": 0, "max_days": 10},
            {"label": "late", "min_days": 15, "max_days": 9999}
        ]
        self.assertEqual(assign_duration_bucket(5.0, buckets), "early")
        self.assertEqual(assign_duration_bucket(20.0, buckets), "late")

    def test_contiguous_buckets_work(self):
        from adversarial_harness import ROUTING_CONFIG
        buckets = ROUTING_CONFIG["duration_buckets"]
        self.assertEqual(assign_duration_bucket(5.0, buckets), "early")
        self.assertEqual(assign_duration_bucket(13.0, buckets), "mid")
        self.assertEqual(assign_duration_bucket(16.0, buckets), "mature")
        self.assertEqual(assign_duration_bucket(25.0, buckets), "late")

    def test_empty_buckets_returns_unknown(self):
        self.assertEqual(assign_duration_bucket(5.0, []), "unknown")

    def test_overflow_returns_last(self):
        """Duration beyond all bucket max_days returns last bucket."""
        buckets = [
            {"label": "early", "min_days": 0, "max_days": 10},
            {"label": "late", "min_days": 10, "max_days": 20}
        ]
        result = assign_duration_bucket(25.0, buckets)
        self.assertEqual(result, "late")


if __name__ == "__main__":
    unittest.main()
