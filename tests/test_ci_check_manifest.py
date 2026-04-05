#!/usr/bin/env python3
"""
Test suite for CI Contract Manifest Checker.

Validates drift detection logic for: grade mismatch, composite score
regression, per-protocol status changes, and error/fail count violations.
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ci_check_manifest import check_manifest, load_json


def _make_report(grade="B", score=0.895, statuses=None, total_errors=0, failed=0):
    """Factory for conformance report dicts."""
    default_statuses = {
        "signal_schema": {"status": "PASS"},
        "routing_protocol": {"status": "PASS"},
        "resolution_protocol": {"status": "PASS"},
        "aggregation_protocol": {"status": "SKIP"},
        "proof_protocol": {"status": "PASS"},
        "lifecycle_pipeline": {"status": "SKIP"},
        "consumer_audit": {"status": "PASS"},
        "discovery_protocol": {"status": "PASS"},
        "consumer_quickstart": {"status": "PASS"},
    }
    if statuses:
        for k, v in statuses.items():
            default_statuses[k] = {"status": v}
    return {
        "readiness_grade": {"grade": grade, "composite_score": score},
        "protocol_results": default_statuses,
        "summary": {"total_errors": total_errors, "failed": failed},
    }


def _make_manifest(grade="B", min_score=0.85, statuses=None, max_errors=0, max_fails=0):
    """Factory for contract manifest dicts."""
    default_statuses = {
        "signal_schema": "PASS",
        "routing_protocol": "PASS",
        "resolution_protocol": "PASS",
        "aggregation_protocol": "SKIP",
        "proof_protocol": "PASS",
        "lifecycle_pipeline": "SKIP",
        "consumer_audit": "PASS",
        "discovery_protocol": "PASS",
        "consumer_quickstart": "PASS",
    }
    if statuses:
        default_statuses.update(statuses)
    return {
        "manifest_version": "1.0.0",
        "expected_outcomes": {
            "readiness_grade": grade,
            "minimum_composite_score": min_score,
            "protocol_statuses": default_statuses,
            "max_errors": max_errors,
            "max_fails": max_fails,
        },
    }


class TestCheckManifestPass(unittest.TestCase):
    """Verify that matching report+manifest produces no drifts."""

    def test_exact_match_no_drift(self):
        report = _make_report()
        manifest = _make_manifest()
        drifts = check_manifest(report, manifest)
        self.assertEqual(drifts, [])

    def test_score_above_minimum(self):
        report = _make_report(score=0.92)
        manifest = _make_manifest(min_score=0.85)
        drifts = check_manifest(report, manifest)
        self.assertEqual(drifts, [])

    def test_score_at_exact_minimum(self):
        report = _make_report(score=0.85)
        manifest = _make_manifest(min_score=0.85)
        drifts = check_manifest(report, manifest)
        self.assertEqual(drifts, [])


class TestCheckManifestGradeDrift(unittest.TestCase):
    """Verify grade mismatch detection."""

    def test_grade_downgrade_detected(self):
        report = _make_report(grade="C")
        manifest = _make_manifest(grade="B")
        drifts = check_manifest(report, manifest)
        self.assertEqual(len(drifts), 1)
        self.assertIn("Grade drift", drifts[0])
        self.assertIn("expected B", drifts[0])
        self.assertIn("got C", drifts[0])

    def test_grade_upgrade_detected(self):
        """Even upgrades are drift — contract should be explicit."""
        report = _make_report(grade="A", score=0.95)
        manifest = _make_manifest(grade="B")
        drifts = check_manifest(report, manifest)
        grade_drifts = [d for d in drifts if "Grade drift" in d]
        self.assertEqual(len(grade_drifts), 1)

    def test_grade_f_detected(self):
        report = _make_report(grade="F", score=0.20)
        manifest = _make_manifest(grade="B")
        drifts = check_manifest(report, manifest)
        self.assertTrue(any("Grade drift" in d for d in drifts))


class TestCheckManifestScoreRegression(unittest.TestCase):
    """Verify composite score floor enforcement."""

    def test_score_below_minimum(self):
        report = _make_report(score=0.70)
        manifest = _make_manifest(min_score=0.85)
        drifts = check_manifest(report, manifest)
        score_drifts = [d for d in drifts if "Composite score regression" in d]
        self.assertEqual(len(score_drifts), 1)
        self.assertIn("0.7000", score_drifts[0])
        self.assertIn("0.8500", score_drifts[0])

    def test_score_slightly_below(self):
        report = _make_report(score=0.8499)
        manifest = _make_manifest(min_score=0.85)
        drifts = check_manifest(report, manifest)
        self.assertTrue(any("Composite score regression" in d for d in drifts))


class TestCheckManifestProtocolDrift(unittest.TestCase):
    """Verify per-protocol status change detection."""

    def test_pass_to_fail_detected(self):
        report = _make_report(statuses={"signal_schema": "FAIL"})
        manifest = _make_manifest()
        drifts = check_manifest(report, manifest)
        proto_drifts = [d for d in drifts if "Protocol drift" in d]
        self.assertTrue(any("signal_schema" in d for d in proto_drifts))

    def test_pass_to_warn_detected(self):
        report = _make_report(statuses={"proof_protocol": "WARN"})
        manifest = _make_manifest()
        drifts = check_manifest(report, manifest)
        self.assertTrue(any("proof_protocol" in d for d in drifts))

    def test_skip_to_pass_detected(self):
        """SKIP→PASS is also drift — the manifest is the contract."""
        report = _make_report(statuses={"aggregation_protocol": "PASS"})
        manifest = _make_manifest()
        drifts = check_manifest(report, manifest)
        self.assertTrue(any("aggregation_protocol" in d for d in drifts))

    def test_multiple_protocol_drifts(self):
        report = _make_report(
            statuses={"signal_schema": "FAIL", "routing_protocol": "SKIP"}
        )
        manifest = _make_manifest()
        drifts = check_manifest(report, manifest)
        proto_drifts = [d for d in drifts if "Protocol drift" in d]
        self.assertGreaterEqual(len(proto_drifts), 2)

    def test_missing_protocol_in_report(self):
        report = _make_report()
        del report["protocol_results"]["signal_schema"]
        manifest = _make_manifest()
        drifts = check_manifest(report, manifest)
        self.assertTrue(any("signal_schema" in d and "MISSING" in d for d in drifts))


class TestCheckManifestErrorCeiling(unittest.TestCase):
    """Verify error count and fail count ceiling enforcement."""

    def test_errors_over_max(self):
        report = _make_report(total_errors=5)
        manifest = _make_manifest(max_errors=0)
        drifts = check_manifest(report, manifest)
        self.assertTrue(any("Error count exceeded" in d for d in drifts))

    def test_errors_at_max(self):
        report = _make_report(total_errors=0)
        manifest = _make_manifest(max_errors=0)
        drifts = check_manifest(report, manifest)
        error_drifts = [d for d in drifts if "Error count" in d]
        self.assertEqual(len(error_drifts), 0)

    def test_fails_over_max(self):
        report = _make_report(failed=2)
        manifest = _make_manifest(max_fails=0)
        drifts = check_manifest(report, manifest)
        self.assertTrue(any("Fail count exceeded" in d for d in drifts))


class TestCheckManifestCombinedDrifts(unittest.TestCase):
    """Verify multiple drift types reported simultaneously."""

    def test_grade_plus_score_plus_protocol(self):
        report = _make_report(
            grade="F",
            score=0.30,
            statuses={"signal_schema": "FAIL"},
            total_errors=5,
            failed=1,
        )
        manifest = _make_manifest()
        drifts = check_manifest(report, manifest)
        # Should detect: grade, score, protocol, errors, fails
        self.assertGreaterEqual(len(drifts), 4)


class TestLoadJsonEdgeCases(unittest.TestCase):
    """Verify JSON loading edge cases."""

    def test_load_missing_file_exits(self):
        with self.assertRaises(SystemExit) as ctx:
            load_json("/nonexistent/path.json")
        self.assertEqual(ctx.exception.code, 2)

    def test_load_valid_json(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"test": True}, f)
            path = f.name
        try:
            data = load_json(path)
            self.assertEqual(data, {"test": True})
        finally:
            os.unlink(path)

    def test_load_malformed_json_exits(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            path = f.name
        try:
            with self.assertRaises(SystemExit) as ctx:
                load_json(path)
            self.assertEqual(ctx.exception.code, 2)
        finally:
            os.unlink(path)


class TestReferenceBundle(unittest.TestCase):
    """Verify reference bundle + manifest are consistent and valid."""

    def setUp(self):
        self.bundle_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "reference_bundle",
        )
        self.manifest_path = os.path.join(self.bundle_dir, "contract_manifest.json")

    def test_manifest_exists(self):
        self.assertTrue(os.path.isfile(self.manifest_path))

    def test_manifest_valid_json(self):
        with open(self.manifest_path, "r") as f:
            manifest = json.load(f)
        self.assertIn("manifest_version", manifest)
        self.assertIn("expected_outcomes", manifest)

    def test_all_declared_artifacts_exist(self):
        with open(self.manifest_path, "r") as f:
            manifest = json.load(f)
        for artifact_name in manifest.get("artifacts", []):
            path = os.path.join(self.bundle_dir, artifact_name)
            self.assertTrue(
                os.path.isfile(path),
                f"Declared artifact missing: {artifact_name}",
            )

    def test_nine_protocols_in_manifest(self):
        with open(self.manifest_path, "r") as f:
            manifest = json.load(f)
        statuses = manifest["expected_outcomes"]["protocol_statuses"]
        self.assertEqual(len(statuses), 9)

    def test_reference_bundle_passes_conformance(self):
        """End-to-end: reference bundle passes the validator."""
        sys.path.insert(0, os.path.dirname(self.bundle_dir))
        from conformance_testkit import ConformanceEngine
        engine = ConformanceEngine()
        artifacts = engine.load_artifacts_from_directory(self.bundle_dir)
        artifacts["_source"] = "local_directory"
        artifacts["_path"] = self.bundle_dir
        report = engine.run(artifacts)
        self.assertEqual(report["readiness_grade"]["grade"], "B")
        self.assertEqual(report["summary"]["failed"], 0)

    def test_reference_bundle_matches_manifest(self):
        """End-to-end: reference bundle report matches contract manifest."""
        sys.path.insert(0, os.path.dirname(self.bundle_dir))
        from conformance_testkit import ConformanceEngine
        engine = ConformanceEngine()
        artifacts = engine.load_artifacts_from_directory(self.bundle_dir)
        artifacts["_source"] = "local_directory"
        artifacts["_path"] = self.bundle_dir
        report = engine.run(artifacts)
        with open(self.manifest_path, "r") as f:
            manifest = json.load(f)
        drifts = check_manifest(report, manifest)
        self.assertEqual(
            drifts, [],
            f"Reference bundle drifts from manifest: {drifts}",
        )


if __name__ == "__main__":
    unittest.main()
