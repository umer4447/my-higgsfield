"""Credit cost for a submission, itemised so the UI can explain it.

One function serves both the quote endpoint and the debit, so the number on the
button is always the number that gets charged.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Price:
    base: int
    move_surcharge: int
    total: int
    per_output: int


def price_job(credit_cost: int, batch: int, has_move: bool) -> Price:
    base = credit_cost * batch
    # Presets that drive a camera move cost one extra credit per output.
    surcharge = batch if has_move else 0
    per_output = credit_cost + (1 if has_move else 0)
    return Price(
        base=base,
        move_surcharge=surcharge,
        total=base + surcharge,
        per_output=per_output,
    )
