#!/usr/bin/env python3
"""
CI Contract Manifest Checker

Compares a conformance report against a pinned contract manifest and exits
nonzero on any drift. Detects: grade mismatch, composite score regression,
per-protocol status changes, and error/fail count violations.

Usage:
    python3 ci_check_manifest.py conformance_report.json contract_manifest.json

Exit codes:
    0 — conformance report matches manifest (no contract drift)
    1 — contract drift detected (details printed to stderr)
    2 — input error (missing files, malformed JSON)
"""

import json
import sys
import os


def load_json(path):
    """Load and parse a JSON file."""
    if not os.path.isfile(path):
        print(f"ERROR: File not found: {path}", file=sys.stderr)
        sys.exit(2)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Malformed JSON in {path}: {e}", file=sys.stderr)
        sys.exit(2)


def check_manifest(report, manifest):
    """
    Compare conformance report against contract manifest.
    Returns list of drift descriptions. Empty list = pass.
    """
    drifts = []
    expected = manifest.get("expected_outcomes", {})

    # 1. Grade check
    actual_grade = report.get("readiness_grade", {}).get("grade")
    expected_grade = expected.get("readiness_grade")
    if expected_grade and actual_grade != expected_grade:
        drifts.append(
            f"Grade drift: expected {expected_grade}, got {actual_grade}"
        )

    # 2. Composite score floor
    actual_score = report.get("readiness_grade", {}).get("composite_score", 0.0)
    min_score = expected.get("minimum_composite_score", 0.0)
    if actual_score < min_score:
        drifts.append(
            f"Composite score regression: {actual_score:.4f} < minimum {min_score:.4f}"
        )

    # 3. Per-protocol status checks
    expected_statuses = expected.get("protocol_statuses", {})
    actual_results = report.get("protocol_results", {})
    for protocol, expected_status in expected_statuses.items():
        actual_status = actual_results.get(protocol, {}).get("status", "MISSING")
        if actual_status != expected_status:
            drifts.append(
                f"Protocol drift [{protocol}]: expected {expected_status}, got {actual_status}"
            )

    # 4. Error count ceiling
    max_errors = expected.get("max_errors")
    if max_errors is not None:
        actual_errors = report.get("summary", {}).get("total_errors", 0)
        if actual_errors > max_errors:
            drifts.append(
                f"Error count exceeded: {actual_errors} > max {max_errors}"
            )

    # 5. Fail count ceiling
    max_fails = expected.get("max_fails")
    if max_fails is not None:
        actual_fails = report.get("summary", {}).get("failed", 0)
        if actual_fails > max_fails:
            drifts.append(
                f"Fail count exceeded: {actual_fails} > max {max_fails}"
            )

    return drifts


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: python3 ci_check_manifest.py <conformance_report.json> <contract_manifest.json>",
            file=sys.stderr,
        )
        sys.exit(2)

    report_path = sys.argv[1]
    manifest_path = sys.argv[2]

    report = load_json(report_path)
    manifest = load_json(manifest_path)

    print(f"Checking conformance report against contract manifest...", file=sys.stderr)
    print(f"  Report:   {report_path}", file=sys.stderr)
    print(f"  Manifest: {manifest_path}", file=sys.stderr)

    drifts = check_manifest(report, manifest)

    if drifts:
        print(f"\nCONTRACT DRIFT DETECTED ({len(drifts)} issue(s)):", file=sys.stderr)
        for d in drifts:
            print(f"  !! {d}", file=sys.stderr)
        print(
            "\nThe conformance validator no longer produces the expected outcomes "
            "against the pinned reference bundle. This means the canonical contract "
            "has changed. Review the drift, update the reference bundle or validator, "
            "and re-pin the manifest.",
            file=sys.stderr,
        )
        # Machine-readable drift summary to stdout
        drift_report = {
            "status": "DRIFT",
            "n_drifts": len(drifts),
            "drifts": drifts,
            "report_grade": report.get("readiness_grade", {}).get("grade"),
            "expected_grade": manifest.get("expected_outcomes", {}).get("readiness_grade"),
            "report_score": report.get("readiness_grade", {}).get("composite_score"),
            "manifest_version": manifest.get("manifest_version"),
        }
        print(json.dumps(drift_report, indent=2))
        sys.exit(1)
    else:
        actual_grade = report.get("readiness_grade", {}).get("grade")
        actual_score = report.get("readiness_grade", {}).get("composite_score", 0.0)
        print(f"\n  PASS — No contract drift detected.", file=sys.stderr)
        print(f"  Grade: {actual_grade}  Score: {actual_score:.4f}", file=sys.stderr)
        print(f"  Manifest version: {manifest.get('manifest_version')}", file=sys.stderr)
        # Machine-readable pass summary to stdout
        pass_report = {
            "status": "PASS",
            "n_drifts": 0,
            "drifts": [],
            "report_grade": actual_grade,
            "expected_grade": manifest.get("expected_outcomes", {}).get("readiness_grade"),
            "report_score": actual_score,
            "manifest_version": manifest.get("manifest_version"),
        }
        print(json.dumps(pass_report, indent=2))
        sys.exit(0)


if __name__ == "__main__":
    main()
