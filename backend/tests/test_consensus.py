from __future__ import annotations

from snowwatch.analysis.consensus import period_consensus

HOURS = [0, 3600]


def s(v: float) -> dict[int, float | None]:
    return dict.fromkeys(HOURS, v)


def test_median_of_models_while_three_run() -> None:
    c = period_consensus(HOURS, {"a": s(1), "b": s(2), "c": s(10)})
    assert (c.value, c.basis, c.nmodels) == (4.0, "models", 3)


def test_short_range_and_blend_join_early_only() -> None:
    models = {"a": s(1), "b": s(1)}
    early = period_consensus(HOURS, models, short_range={"hrrr": s(5)}, blend=s(5), early=True)
    late = period_consensus(HOURS, models, short_range={"hrrr": s(5)}, blend=s(5), ens_mean=3.0)
    # Period totals 2, 2, 10 (HRRR) and 10 (blend): median 6.
    assert (early.value, early.basis, early.nmodels) == (6.0, "models", 4)
    assert (late.value, late.basis) == (3.0, "ensemble")


def test_model_that_ended_is_ignored() -> None:
    ended = {0: 1.0, 3600: None}
    c = period_consensus(HOURS, {"a": s(1), "b": s(1), "c": ended}, ens_mean=7.0)
    assert c.models["c"] is None and c.basis == "ensemble" and c.value == 7.0


def test_fallback_without_ensemble() -> None:
    c = period_consensus(HOURS, {"a": s(1)}, blend=s(2))
    assert (c.value, c.basis) == (3.0, "models")
    assert period_consensus(HOURS, {}).value is None
