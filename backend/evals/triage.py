"""Problem router accuracy: messages written the way people describe card problems (from the forum
research: Reddit, TechnoFino, DesiDime, complaint sites), in English and Hinglish, each labelled
with the problem it should go to. Keyword rules only, no AI calls.

    python -m evals.triage

Fraud must never be missed: a missed fraud costs money within days."""

import asyncio
import sys
from typing import Any

from app.triage import route

# (message, expected problem key, expected card name or None)
CASES: list[tuple[str, str, str | None]] = [
    ("Someone used my card for 25,000 on some website, I didn't make this payment", "fraud", None),
    ("Got a call from 'bank' asking OTP and now money is gone from my HDFC card", "fraud", None),
    (
        "unauthorised transaction on my SBI Cashback card last night",
        "fraud",
        "SBI Card Cashback credit card",
    ),
    ("mere card se chori ho gayi payment, maine nahi kiya", "fraud", None),
    ("lost my card in a cab, what do I do", "fraud", None),
    ("Swiggy charged me twice for the same order on my card", "duplicate", None),
    ("there is a double debit of 1,600 on my statement", "duplicate", None),
    ("ek hi payment do baar kat gaya", "duplicate", None),
    (
        "I asked ICICI to close my card in July and it's still active, they keep charging",
        "closure",
        None,
    ),
    ("bank is not closing my credit card even after 3 emails", "closure", None),
    ("card band karna hai par bank band nahi kar raha", "closure", None),
    ("Charged member fees despite being LTF, help!", "ltf_fee", None),
    (
        "Agent told me Swiggy HDFC is lifetime free but now 500 annual fee came",
        "ltf_fee",
        "Swiggy HDFC Bank credit card",
    ),
    ("they promised it was free for life and charged joining fee", "ltf_fee", None),
    (
        "why did I get a renewal fee of 1180 on my Axis ACE",
        "annual_fee",
        "Axis Bank ACE credit card",
    ),
    ("annual fee charged even though I spent more than 1 lakh", "annual_fee", None),
    ("I paid on 27th, due date was 25th, still they put late fee", "late_fee", None),
    ("late payment charge even after paying before due date", "late_fee", None),
    ("I paid the full amount on time but they charged interest", "interest", None),
    ("finance charges on my bill even though I always pay full", "interest", None),
    ("byaj kyun laga jab maine poora bill bhara", "interest", None),
    ("No cost EMI on my phone but bank is charging interest and processing fee", "emi", None),
    ("they want 3% foreclosure on my EMI", "emi", None),
    ("over limit fee 600 charged, I never opted in", "overlimit", None),
    ("My card limit revised from 20L to 20K without any notice", "limit_cut", None),
    ("bank reduced my credit limit suddenly", "limit_cut", None),
    ("Reward points nullified on my IDFC First card", "points", None),
    ("1.5 lakh points disappeared from my account", "points", None),
    ("cashback not credited for last two months", "points", None),
    ("my cashback card gives cashback as amazon vouchers, not money", "cashback_form", None),
    ("got points instead of cashback on my SBI card", "cashback_form", None),
    ("cashback ki jagah gift card mil raha hai", "cashback_form", None),
    ("Axis Magnus devaluation is brutal", "benefits_cut", "Axis Bank Magnus credit card"),
    ("lounge access removed from my card without telling", "benefits_cut", None),
    ("they changed the terms of my card after I got it", "benefits_cut", None),
    ("I never applied for this card but it was delivered", "unsolicited", None),
    ("bank upgraded my card without my consent and charged fee", "unsolicited", None),
    ("DCC charge on Klook booking paid in INR", "forex", None),
    ("forex markup on my international transaction is more than they said", "forex", None),
    ("fuel surcharge refund doesn't include GST", "fuel", None),
    ("bank not responding to my complaint for 40 days", "complaint", None),
    ("how do I go to RBI ombudsman", "complaint", None),
    ("my CIBIL shows late payment that never happened", "cibil", None),
    ("credit score dropped because bank reported wrong", "cibil", None),
    ("recovery agents are calling my office and family", "recovery", None),
    ("collection agents harassing me at 10 pm", "recovery", None),
    ("which card is best for online shopping", "card_info", None),
    ("what are the fees of HDFC Millennia", "card_info", "HDFC Bank Millennia credit card"),
]


# Written after the rules were tuned on CASES and never used for tuning: an honest score.
HELD_OUT: list[tuple[str, str, str | None]] = [
    ("there's a transaction of 9,999 from Mumbai that I don't recognise", "fraud", None),
    ("someone took money from my card using a fake KYC link", "fraud", None),
    ("my statement shows the same Amazon order charged two times", "duplicate", None),
    ("closed my Kotak card 3 weeks ago but annual fee still came", "closure", None),
    ("salesman said zero fee forever, now 499 + GST charged", "ltf_fee", None),
    ("got hit with 750 late fee though I paid a day after due date", "late_fee", None),
    ("why am I paying interest when I cleared the full bill", "interest", None),
    ("they charged me 199 processing fee on a no cost EMI", "emi", None),
    ("my credit limit got slashed to half overnight", "limit_cut", None),
    ("all my reward points expired and nobody told me", "points", None),
    ("they removed free movie tickets from my card", "benefits_cut", None),
    ("got a credit card I never requested in the post", "unsolicited", None),
    ("paid in rupees on a foreign website and got extra charges", "forex", None),
    ("bank closed my complaint without solving it, what next", "complaint", None),
    ("loan app recovery guys threatening to call my contacts", "recovery", None),
    ("is SBI SimplyCLICK worth it", "card_info", "SBI Card SimplyCLICK credit card"),
]

Case = tuple[str, str, str | None]


async def score(cases: list[Case]) -> tuple[float, list[tuple[str, str, Any]]]:
    """Share routed to the right problem, and the misses as (message, wanted, got)."""
    wrong = []
    for text, want, _ in cases:
        got = (await route(text)).as_dict()["problem"]
        if got != want:
            wrong.append((text, want, got))
    return round(1 - len(wrong) / len(cases), 3), wrong


async def run() -> dict[str, Any]:
    correct, wrong = await score(CASES)
    card_wrong = []
    for text, _, card in CASES:
        got = (await route(text)).as_dict()["prefill"]["card"]
        if card and got != card:
            card_wrong.append((text, card, got))
    fraud = [c for c in CASES if c[1] == "fraud"]
    fraud_missed = [w for w in wrong if w[1] == "fraud"]
    return {
        "messages": len(CASES),
        "correct": correct,
        "fraud_caught": f"{len(fraud) - len(fraud_missed)}/{len(fraud)}",
        "wrong": wrong,
        "card_wrong": card_wrong,
    }


def main() -> int:
    out = asyncio.run(run())
    for t, want, got in out["wrong"]:
        print(f"WRONG  want {want:<13} got {got!s:<13} {t}")
    for t, want, got in out["card_wrong"]:
        print(f"CARD   want {want} got {got}: {t}")
    print({k: v for k, v in out.items() if k not in ("wrong", "card_wrong")})
    return 0 if not any(w[1] == "fraud" for w in out["wrong"]) else 1


if __name__ == "__main__":
    sys.exit(main())
