"""Return estimates for Mississippi tax liens.

Rules used (verify against the current Mississippi Code before relying on them):
- The buyer earns 1.5% per month on the face amount; the overbid earns nothing
  and is not refunded.
- The owner has 2 years from the sale to redeem.
Interest is counted in whole months elapsed, so figures are estimates.
"""
from datetime import date

MONTHLY_RATE = 0.015
REDEMPTION_YEARS = 2


def _add_years(d: date, years: int) -> date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29
        return d.replace(year=d.year + years, day=28)


def _months_between(start: date, end: date) -> int:
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def lien_metrics(face_amount, overbid, sale_date: str | None, as_of: date | None = None) -> dict:
    if not face_amount or not sale_date:
        return {}
    as_of = as_of or date.today()
    sale = date.fromisoformat(sale_date)
    deadline = _add_years(sale, REDEMPTION_YEARS)
    outlay = face_amount + (overbid or 0)
    months = _months_between(sale, min(as_of, deadline)) if as_of >= sale else 0
    interest = round(face_amount * MONTHLY_RATE * months, 2)
    max_interest = round(face_amount * MONTHLY_RATE * 12 * REDEMPTION_YEARS, 2)
    return {
        "redemption_deadline": deadline.isoformat(),
        "in_redemption_period": sale <= as_of < deadline,
        "days_until_deadline": (deadline - as_of).days if as_of < deadline else 0,
        "months_elapsed": months,
        "total_outlay": round(outlay, 2),
        "accrued_interest": interest,
        "redemption_amount": round(face_amount + interest, 2),
        "return_to_date": round(interest / outlay, 4),
        # If redeemed on the last day: the best case for the buyer.
        "max_interest": max_interest,
        "max_return": round(max_interest / outlay, 4),
        "max_annualized_return": round(max_interest / outlay / REDEMPTION_YEARS, 4),
    }
