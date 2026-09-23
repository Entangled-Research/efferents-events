"""The Writer is only triggered when a campaign shows novelty + significant gain."""
from __future__ import annotations


from efferents.agents.writer import should_publish, GateInputs


def test_below_threshold_blocks():
    inputs = GateInputs(
        primary_metric_name="e_w1",
        baseline_value=0.020,
        candidate_value=0.0199,   # only 0.5% better
        novelty_claim="some claim",
        existing_lab_claims=[],
    )
    ok, reason = should_publish(inputs, gain_threshold=0.05)
    assert not ok
    assert "gain" in reason.lower()


def test_at_threshold_passes():
    inputs = GateInputs(
        primary_metric_name="e_w1",
        baseline_value=0.020,
        candidate_value=0.018,   # 10% better
        novelty_claim="first lap-pyr UNet on QFM",
        existing_lab_claims=["amp-ratio gate", "annular radial head"],
    )
    ok, reason = should_publish(inputs, gain_threshold=0.05)
    assert ok, reason


def test_empty_novelty_blocks():
    inputs = GateInputs(
        primary_metric_name="e_w1",
        baseline_value=0.020,
        candidate_value=0.010,
        novelty_claim="   ",
        existing_lab_claims=[],
    )
    ok, reason = should_publish(inputs, gain_threshold=0.05)
    assert not ok
    assert "novel" in reason.lower()


def test_duplicates_existing_claim_blocks():
    inputs = GateInputs(
        primary_metric_name="e_w1",
        baseline_value=0.020,
        candidate_value=0.010,
        novelty_claim="amp-ratio gate",
        existing_lab_claims=["amp-ratio gate", "annular radial head"],
    )
    ok, reason = should_publish(inputs, gain_threshold=0.05)
    assert not ok
    assert "duplicate" in reason.lower() or "existing" in reason.lower()


def test_refutation_path_passes_without_gain():
    inputs = GateInputs(
        primary_metric_name="e_w1",
        baseline_value=0.020,
        candidate_value=0.020,   # no gain
        novelty_claim="refutes prior corroborated claim X",
        existing_lab_claims=[],
        refutation_of_corroborated="claim-x",
    )
    ok, reason = should_publish(inputs, gain_threshold=0.05)
    assert ok


def test_explicit_negative_and_verification_findings_reach_review_without_gain():
    for kind in ("negative_result", "verification"):
        inputs = GateInputs(
            primary_metric_name="loss",
            baseline_value=0.02,
            candidate_value=0.02,
            novelty_claim=f"bounded {kind} claim",
            finding_kind=kind,
        )
        ok, reason = should_publish(inputs, gain_threshold=0.05)
        assert ok, reason
        assert kind in reason


def test_finding_route_requires_finite_measured_values_and_known_kind():
    base = GateInputs(
        primary_metric_name="loss", baseline_value=float("nan"),
        candidate_value=0.02, novelty_claim="bounded result",
        finding_kind="negative_result",
    )
    assert not should_publish(base)[0]
    assert not should_publish(
        GateInputs(**{**base.__dict__, "baseline_value": 0.02,
                      "finding_kind": "skip_gate"})
    )[0]
