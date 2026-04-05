# Post Fiat Protocol Conformance Test Kit

**Single-entry-point conformance validator for the Post Fiat signal protocol stack.**

Validates producer artifacts against all nine published protocols in dependency order, performs cross-protocol consistency checks, and outputs a structured conformance report with per-protocol PASS/FAIL/WARN/SKIP status, specific violations with JSON path references, remediation hints, and an overall readiness grade.

## Why This Exists

The Post Fiat protocol stack comprises nine companion repositories. A producer achieving conformance must satisfy constraints across all nine — and many constraints span protocol boundaries. This testkit provides the self-serve conformance gate: any producer can verify full-stack readiness before registration, and any consumer can audit compliance without private translation.

## Companion Repositories

This is the **tenth** companion to the Post Fiat signal protocol stack:

| Order | Repository | Purpose |
|-------|-----------|---------|
| 1 | [pf-signal-schema](https://github.com/sendoeth/pf-signal-schema) | Signal format specification |
| 2 | [pf-routing-protocol](https://github.com/sendoeth/pf-routing-protocol) | Pre-flight routing gates |
| 3 | [pf-resolution-protocol](https://github.com/sendoeth/pf-resolution-protocol) | Signal resolution + reputation |
| 4 | [pf-aggregation-protocol](https://github.com/sendoeth/pf-aggregation-protocol) | Multi-producer consensus |
| 5 | [pf-proof-protocol](https://github.com/sendoeth/pf-proof-protocol) | Continuous proof maintenance |
| 6 | [pf-lifecycle-pipeline](https://github.com/sendoeth/pf-lifecycle-pipeline) | Proof lifecycle orchestration |
| 7 | [pf-consumer-audit](https://github.com/sendoeth/pf-consumer-audit) | Consumer trust verification |
| 8 | [pf-discovery-protocol](https://github.com/sendoeth/pf-discovery-protocol) | Producer registration + discovery |
| 9 | [pf-consumer-quickstart](https://github.com/sendoeth/pf-consumer-quickstart) | End-to-end consumer pipeline |
| **10** | **pf-conformance-testkit** | **Protocol conformance validation** |

## Validation Dependency Order

The testkit validates in strict dependency order. If an upstream protocol fails, downstream protocols that depend on it are marked SKIP (not tested) to avoid cascading false failures:

```
signal_schema (foundation)
├── routing_protocol
├── resolution_protocol
│   ├── aggregation_protocol (+ routing)
│   ├── proof_protocol
│   │   ├── lifecycle_pipeline
│   │   └── consumer_audit (+ routing + aggregation)
│   └── discovery_protocol
└── consumer_quickstart (depends on all 8)
```

## Quick Start

### Producer Conformance Walkthrough

Verify your artifacts pass full-stack conformance:

```bash
# 1. Organize artifacts in a directory
mkdir my_producer/
cp signals.json proof_surface.json routing_policy.json my_producer/

# 2. Run conformance check
python3 conformance_testkit.py my_producer/

# 3. Get machine-readable report
python3 conformance_testkit.py my_producer/ -o conformance_report.json

# 4. Self-validate the report
python3 conformance_testkit.py my_producer/ --validate
```

### Consumer Audit Walkthrough

Audit any producer's conformance:

```bash
# Audit from local artifacts
python3 conformance_testkit.py /path/to/producer/artifacts/ --json

# Audit from remote endpoint
python3 conformance_testkit.py --endpoint http://producer.example.com/ --json
```

### Generate Test Signals

Create synthetic test scenarios for development:

```bash
# List available scenarios
python3 generate_test_signals.py --list

# Generate all scenarios
python3 generate_test_signals.py test_data/

# Generate a specific scenario
python3 generate_test_signals.py test_data/ --scenario schema_failures
```

## Artifact Discovery

Place artifacts in a directory. The testkit auto-discovers files by name:

| Artifact | Recognized Filenames |
|----------|---------------------|
| Signals | `signals.json`, `signal_batch.json`, `signal_log.json` |
| Proof Surface | `proof_surface.json`, `proof_maintenance.json`, `proof_report.json` |
| Routing Config | `routing_policy.json`, `routing_config.json` |
| Routing Report | `routing_report.json` |
| Resolution Report | `resolution_report.json` |
| Aggregation Report | `aggregation_report.json` |
| Lifecycle Report | `lifecycle_report.json`, `evolution_report.json` |
| Audit Report | `audit_report.json` |
| Discovery Entry | `producer_entry.json`, `producer_config.json` |
| Consumer Verdict | `consumer_verdict.json` |

Missing artifacts are marked SKIP — provide as many as available.

## Conformance Report Structure

```json
{
  "meta": {
    "testkit_version": "1.0.0",
    "generated_at": "2026-03-30T12:00:00.000Z",
    "artifact_source": "local_directory"
  },
  "readiness_grade": {
    "grade": "B",
    "composite_score": 0.8950,
    "n_pass": 7, "n_fail": 0, "n_warn": 0, "n_skip": 2
  },
  "protocol_results": {
    "signal_schema": {
      "status": "PASS",
      "violations": [],
      "details": { "n_signals": 30, "pass_rate": 1.0, "level_distribution": {...} }
    },
    ...
  },
  "cross_protocol_checks": {
    "violations": [...],
    "n_errors": 0, "n_warnings": 1
  },
  "summary": {
    "total_protocols": 9,
    "passed": 7, "warned": 0, "failed": 0, "skipped": 2,
    "total_violations": 1, "total_errors": 0, "total_warnings": 1
  },
  "limitations": [...]
}
```

## Readiness Grades

| Grade | Composite Score | Meaning |
|-------|----------------|---------|
| A | >= 0.90 | Full conformance. Ready for registration. |
| B | >= 0.75 | Strong conformance. Minor gaps (typically SKIP protocols). |
| C | >= 0.55 | Partial conformance. Some protocols need attention. |
| D | >= 0.35 | Weak conformance. Significant gaps. |
| F | < 0.35 | Non-conformant. Foundation failures or missing artifacts. |

**Hard gates:**
- Signal schema FAIL = automatic Grade F (foundation failure)
- 3+ protocol FAILs = grade capped at D

## Violation Format

Every violation includes:
- **protocol** — which protocol detected the issue
- **json_path** — exact location in the artifact (e.g., `$.signals[3].confidence`)
- **message** — what went wrong
- **remediation** — how to fix it
- **severity** — ERROR (blocks PASS), WARNING (flags concern), INFO (informational)

## Cross-Protocol Consistency Checks

Beyond per-protocol validation, the testkit detects inter-protocol inconsistencies:

1. **Orphaned resolved signals** — proof references signals not in the signal log (lifecycle gap)
2. **Routing decision mismatches** — routing decisions reference unknown signal IDs
3. **Schema-valid but routing-invalid** — classified as routing issue, not schema issue
4. **Producer ID mismatches** — resolution report references different producer than signals
5. **Freshness/liveness inconsistency** — EXPIRED proof but ALIVE discovery entry
6. **Reputation discrepancy** — proof vs resolution reputation score divergence > 0.15
7. **Audit/quickstart verdict divergence** — different trust conclusions from same producer
8. **Symbol coverage gaps** — signals emit symbols not declared in discovery entry

## Synthetic Test Scenarios

The generator produces 10 scenarios with annotated expected outcomes:

| Scenario | Expected Grade | Key Behavior |
|----------|---------------|--------------|
| `fully_conformant` | B | All provided protocols PASS |
| `schema_failures` | F | Signal schema FAIL, cascade SKIP |
| `cross_protocol_issues` | B | Schema PASS but cross-protocol warnings |
| `stale_proof` | C | EXPIRED proof, DEGRADED drift |
| `routing_boundary` | C | Signals at exact gate thresholds |
| `aggregation_conflict` | C | EXTREME disagreement, CONFLICT action |
| `discovery_invalid` | D | Invalid capabilities, missing fields |
| `lifecycle_idempotency` | D | Negative n_new_resolved violation |
| `empty_artifacts` | D | Empty signal list |
| `partial_conformance` | B | Good signals + proof, no routing |

Each scenario includes `expected_outcomes.json` for automated verification.

## Step-by-Step: From First Run to Full Readiness

### Step 1: Validate Signal Schema (Foundation)

```bash
python3 conformance_testkit.py my_signals/ --json | python3 -c "
import json,sys; r=json.load(sys.stdin)
print(r['protocol_results']['signal_schema']['status'])
print(r['protocol_results']['signal_schema']['details'])
"
```

Fix all ERROR violations. Common issues:
- Missing required fields (signal_id, producer_id, timestamp, symbol, direction, confidence, horizon_hours, action, schema_version)
- `confidence` on 0-100 scale instead of 0-1
- `action=INVERT` without `weak_symbol` metadata
- Lowercase symbol names

### Step 2: Add Routing Config

Add `routing_policy.json` with gate configurations. Re-run testkit.

### Step 3: Add Proof Surface

Add `proof_surface.json` from your proof maintenance pipeline. The testkit validates freshness, drift status, rolling windows, Wilson CIs, and reputation.

### Step 4: Add Resolution + Discovery

Add `resolution_report.json` and `producer_entry.json`. Cross-protocol checks will now verify producer ID consistency, symbol coverage, and reputation alignment.

### Step 5: Full Conformance

Provide all available artifacts. Target Grade B or above. Fix violations in dependency order (schema first, then routing, then downstream).

## CI Conformance Gate

This repo enforces the canonical producer contract via a GitHub Actions workflow that runs on every push and pull request. The workflow validates a pinned reference artifact bundle against the conformance testkit and fails the build on any contract drift.

### How It Works

1. **Reference bundle** (`reference_bundle/`) — deterministic set of producer artifacts representing the canonical contract at v1.0.0
2. **Contract manifest** (`reference_bundle/contract_manifest.json`) — declares expected grade, per-protocol statuses, composite score floor, and error/fail ceilings
3. **Conformance validator** runs against the reference bundle and emits a machine-readable JSON report
4. **Manifest checker** (`ci_check_manifest.py`) compares the report against the manifest — any deviation (grade change, status flip, score regression) = contract drift = build failure
5. **Report artifact** — the JSON conformance report is uploaded as a build artifact for reviewer inspection

### Pass/Fail Rule

The build **passes** when ALL of the following hold:
- Readiness grade matches the manifest (currently: **B**)
- Composite score >= manifest floor (currently: **0.85**)
- Every protocol status matches the manifest exactly (7 PASS, 2 SKIP)
- Total errors <= manifest ceiling (currently: **0**)
- Total fails <= manifest ceiling (currently: **0**)

The build **fails** on any single deviation. Even "improvements" (e.g., SKIP→PASS) are flagged as drift because the manifest is the explicit contract.

### Run Locally

```bash
# Full CI gate in two commands:
python3 conformance_testkit.py reference_bundle/ -o conformance_report.json --validate
python3 ci_check_manifest.py conformance_report.json reference_bundle/contract_manifest.json
```

Exit code 0 = pass, 1 = contract drift detected.

### Reuse in Another Repo

To add the same conformance gate to any other protocol repo:

1. Copy `conformance_testkit.py`, `ci_check_manifest.py`, and `reference_bundle/` into your repo
2. Copy `.github/workflows/conformance-gate.yml`
3. Adjust `reference_bundle/contract_manifest.json` to match your expected outcomes
4. Push — the workflow runs automatically on push and pull request

No external dependencies required. Pure Python 3.8+ stdlib.

## Tests

```bash
python3 -m pytest tests/ -v
```

164 tests across 24 test classes covering:
- Per-protocol validation (9 validators)
- Cross-protocol consistency detection
- Dependency-ordered cascade behavior
- Grade threshold boundaries
- Synthetic generator correctness
- Conformance report self-validation
- Limitation detection with bias direction
- Remote endpoint timeout handling
- Directory artifact loading
- CI manifest drift detection (grade, score, status, error/fail ceilings)
- Reference bundle integrity and end-to-end conformance

## Zero External Dependencies

Pure Python 3.8+ stdlib. No pip install required. Follows the same zero-dependency pattern as all companion repos.

## Usage

```
python3 conformance_testkit.py <directory> [options]

Options:
  --json          Output JSON to stdout
  -o FILE         Write report to file
  --validate      Self-validate the output report
  --endpoint URL  Fetch artifacts from producer HTTP endpoint
  --timeout SEC   HTTP timeout (default: 15)
  --version       Show version
```

## Protocol Version

v1.0.0 — validates against v1.0.0 of all nine companion protocols.
