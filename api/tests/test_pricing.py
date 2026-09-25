from app.services.pricing import price_job


def test_base_cost_scales_with_batch() -> None:
    p = price_job(2, 4, has_move=False)
    assert (p.base, p.move_surcharge, p.total, p.per_output) == (8, 0, 8, 2)


def test_move_preset_adds_one_credit_per_output() -> None:
    p = price_job(2, 4, has_move=True)
    assert (p.base, p.move_surcharge, p.total, p.per_output) == (8, 4, 12, 3)


def test_motion_costs_nine_times_a_still() -> None:
    """The number the pricing page leads with, asserted."""
    still = price_job(2, 1, has_move=False).total
    motion = price_job(18, 1, has_move=False).total
    assert motion == still * 9


def test_single_output() -> None:
    assert price_job(3, 1, has_move=False).total == 3
