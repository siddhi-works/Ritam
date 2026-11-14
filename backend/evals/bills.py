"""Bill checker accuracy test set.

Each scenario is a synthetic bill (built here as a PDF) with hand-written expected answers. The
same code the API uses reads it (app.bills), so the score covers parsing, masking, the AI read,
value verification and every rule.

    python -m evals.bills                    # replay recorded AI answers (no AI calls)
    python -m evals.bills --live --record    # ask the AI again and save its answers
    python -m evals.bills --private DIR      # also run real bills kept outside the repo

Scores:
  charges   precision/recall on (kind, amount): did Ritam find every bank charge, and nothing else?
  fields    total due, minimum due, due date, statement date exactly right
  rules     expected findings raised; any other "ask the bank" finding is a false alarm
  privacy   the bill's name and address never reach the AI
"""

import argparse
import asyncio
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.bills import Bill, check_bill, check_pair, read_bill
from app.config import get_settings
from app.llm.factory import make_router

HERE = Path(__file__).parent
CASSETTES = HERE / "cassettes" / "bills"
MAX_BYTES = 20 * 1024 * 1024
NAME, ADDRESS = "PRIYA TESTCASE", "42 SAMPLE NAGAR, PUNE 411001"
EMI_INFO = {"info.emi_cost"}


@dataclass
class Expect:
    charges: list[tuple[str, str]] = field(default_factory=list)  # (kind, amount)
    total_due: str | None = None
    minimum_due: str | None = None
    due: str | None = None
    statement_date: str | None = None
    rules: set[str] = field(default_factory=set)


@dataclass
class Scenario:
    name: str
    lines: list[str]
    expect: Expect
    previous: "Scenario | None" = None  # for two-bill scenarios


def _hdr(stmt: str, due: str, total: str, minimum: str, limit: str = "1,50,000") -> list[str]:
    return [
        "HDFC Bank Millennia Credit Card Statement",
        f"Name: {NAME}",
        f"Address: {ADDRESS}",
        "Card No: 4893 77XX XXXX 7890",
        f"Statement Date: {stmt}     Payment Due Date: {due}",
        f"Total Amount Due: {total}     Minimum Amount Due: {minimum}     Credit Limit: {limit}",
        "",
        "Date        Transaction Description                         Amount (Rs.)",
    ]


def _row(d: str, desc: str, amt: str) -> str:
    return f"{d}  {desc:<52}{amt:>14}"


FULL = Scenario(
    "full",
    _hdr("05/10/2026", "25/10/2026", "27,013.65", "1,350.00")
    + [
        _row("12/09/2026", "AMAZON PAY INDIA BANGALORE", "2,499.00"),
        _row("15/09/2026", "STEAM GAMES SEATTLE USD 36.00", "3,000.00"),
        _row("15/09/2026", "MARKUP FEE ON FOREIGN CURRENCY TXN", "105.00"),
        _row("15/09/2026", "IGST @18% ON MARKUP FEE", "18.90"),
        _row("18/09/2026", "RENTPAY - RENT PAYMENT FEE", "150.00"),
        _row("18/09/2026", "IGST @18% ON RENT FEE", "27.00"),
        _row("26/09/2026", "LATE PAYMENT FEE", "600.00"),
        _row("26/09/2026", "IGST @18% ON LATE FEE", "108.00"),
        _row("27/09/2026", "PAYMENT RECEIVED - THANK YOU", "15,000.00 Cr"),
        _row("01/10/2026", "SWIGGY BANGALORE", "450.00"),
        _row("01/10/2026", "SWIGGY BANGALORE", "450.00"),
        _row("02/10/2026", "INDIAN OIL PETROL PUMP PUNE", "2,000.00"),
        _row("02/10/2026", "FUEL SURCHARGE", "20.00"),
        _row("02/10/2026", "IGST @18% ON FUEL SURCHARGE", "3.60"),
        _row("02/10/2026", "FUEL SURCHARGE WAIVER", "20.00 Cr"),
        _row("03/10/2026", "ANNUAL MEMBERSHIP FEE", "1,000.00"),
        _row("03/10/2026", "IGST @18% ON ANNUAL FEE", "180.00"),
        _row("04/10/2026", "NO COST EMI - SAMSUNG PHONE 1/6", "4,999.00"),
        _row("04/10/2026", "EMI INTEREST - SAMSUNG 1/6", "312.40"),
        _row("04/10/2026", "EMI PROCESSING FEE", "199.00"),
        _row("04/10/2026", "OVERLIMIT FEE", "600.00"),
        _row("05/10/2026", "FINANCE CHARGES", "412.50"),
        _row("05/10/2026", "IGST @18% ON FINANCE CHARGES", "74.25"),
    ],
    Expect(
        charges=[
            ("forex_markup", "105"),
            ("gst", "18.90"),
            ("rent_payment_fee", "150"),
            ("gst", "27"),
            ("late_payment_fee", "600"),
            ("gst", "108"),
            ("fuel_surcharge", "20"),
            ("gst", "3.60"),
            ("annual_fee", "1000"),
            ("gst", "180"),
            ("emi_interest", "312.40"),
            ("emi_processing_fee", "199"),
            ("overlimit_fee", "600"),
            ("finance_charge", "412.50"),
            ("gst", "74.25"),
        ],
        total_due="27013.65",
        minimum_due="1350",
        due="2026-10-25",
        statement_date="2026-10-05",
        rules={
            "rbi.overlimit_consent",
            "rbi.emi_no_cost",
            "info.annual_fee",
            "txn.duplicate",
            "rbi.late_fee_check",
            "info.fuel_gst",
            *EMI_INFO,
        },
    ),
)

CLEAN = Scenario(
    "clean",
    _hdr("05/10/2026", "25/10/2026", "6,349.00", "320.00")
    + [
        _row("27/09/2026", "PAYMENT RECEIVED - THANK YOU", "8,120.00 Cr"),
        _row("28/09/2026", "BIGBASKET BANGALORE", "1,850.00"),
        _row("30/09/2026", "IRCTC TICKET BOOKING", "2,450.00"),
        _row("02/10/2026", "APOLLO PHARMACY PUNE", "649.00"),
        _row("03/10/2026", "AMAZON REFUND", "300.00 Cr"),
        _row("04/10/2026", "UBER INDIA", "1,700.00"),
        "Previous Balance 8,120.00 | Payments 8,120.00 | Purchases 6,649.00 | Credits 300.00",
    ],
    Expect(total_due="6349", minimum_due="320", due="2026-10-25", statement_date="2026-10-05"),
)

SCHEDULE_TRAP = Scenario(
    "schedule_trap",
    _hdr("05/10/2026", "25/10/2026", "3,200.00", "160.00")
    + [
        _row("21/09/2026", "DMART PUNE", "2,100.00"),
        _row("29/09/2026", "PVR CINEMAS", "1,100.00"),
        "**** End of Statement ****",
        "Schedule of charges",
        "Finance Charges (Retail & Cash) 3.6% p.m (52.86% per annum)",
        "Late payment fee: Rs 500 if total due is between Rs 501 - Rs 5,000; Rs 750 above Rs 5,000",
        "Cash Withdrawal Fees 2.5% of cash withdrawn (Min. Rs 500)",
        "Example: You purchased goods for Rs.25000.00 on 12th June and paid Rs.5000.00 on 10th July.",
        "Interest on Rs.25000 @ 3.6% p.m. from 12th June to 20th July (39 Days) 1153.97",
        "Total Interest charged on 20th July 1478.43",
        "Over limit penalty 3% of over limit amount (Min. Rs 500)",
    ],
    Expect(total_due="3200", minimum_due="160", due="2026-10-25", statement_date="2026-10-05"),
)

OLD_FORMAT = Scenario(
    "old_format",
    [
        "Your Credit Card Statement",
        f"{NAME}",
        f"{ADDRESS}",
        "Indian Bank Credit Card No. Statement Date Statement Period Payment Due Date",
        "4328 09XX XXXX 7471 20-10-16 21-09-16 - 20-10-16 04-11-16",
        "Txn. Date Transaction Particulars Cr/Dr Amt. in Rs.",
        "20-SEP-16 PREVIOUS STATEMENT OUTSTANDING Dr 14,760.28",
        "25-SEP-16 ROSHAN CHENNAI IN,4328XXXXXXXX7471-17243521 Dr 5,249.00",
        "03-OCT-16 PAYMENT RECEIVED-THANK YOU Cr 14,760.00",
        "08-OCT-16 THE CHENNAI SILKS SALEM IN,4328XXXXXXXX7471-17386306 Dr 750.00",
        "10-OCT-16 RAMRAJ COTTON SALEM IN,4328XXXXXXXX7471-17404432 Dr 885.00",
        "PURCHASE INTEREST Dr 0.01",
        "Previous Balance Purchases & Other Charges Payments Total amount due Minimum Amt. Due",
        "14760.28 6884.01 14760.00 6884.29 345.00",
        "4328 09XX XXXX 7471 2510216 6884.29 345.00",
    ],
    Expect(
        charges=[("finance_charge", "0.01")],
        total_due="6884.29",
        minimum_due="345",
        due="2016-11-04",
        statement_date="2016-10-20",
    ),
)

LATE_PREV = Scenario(
    "late_pair_prev",
    _hdr("05/09/2026", "25/09/2026", "12,000.00", "600.00")
    + [
        _row("20/08/2026", "RELIANCE DIGITAL", "12,000.00"),
        "Previous Balance 0.00 Purchases 12,000.00",
    ],
    Expect(total_due="12000", minimum_due="600", due="2026-09-25", statement_date="2026-09-05"),
)
LATE_PAIR = Scenario(
    "late_pair",
    _hdr("05/10/2026", "25/10/2026", "1,708.00", "100.00")
    + [
        _row("27/09/2026", "PAYMENT RECEIVED - THANK YOU", "12,000.00 Cr"),
        _row("26/09/2026", "LATE PAYMENT FEE", "600.00"),
        _row("26/09/2026", "IGST @18% ON LATE FEE", "108.00"),
        _row("01/10/2026", "ZOMATO", "1,000.00"),
        "Payments received this period: 12,000.00",
    ],
    Expect(
        charges=[("late_payment_fee", "600"), ("gst", "108")],
        total_due="1708",
        minimum_due="100",
        due="2026-10-25",
        statement_date="2026-10-05",
        rules={"rbi.late_fee_grace"},
    ),
    previous=LATE_PREV,
)

INT_PREV = Scenario(
    "interest_pair_prev",
    _hdr("05/09/2026", "25/09/2026", "12,000.00", "600.00", limit="2,00,000")
    + [
        _row("20/08/2026", "CROMA ELECTRONICS", "12,000.00"),
        "Previous Balance 0.00 Purchases 12,000.00",
    ],
    Expect(total_due="12000", minimum_due="600", due="2026-09-25", statement_date="2026-09-05"),
)
INT_PAIR = Scenario(
    "interest_pair",
    _hdr("05/10/2026", "25/10/2026", "3,486.75", "175.00", limit="50,000")
    + [
        _row("20/09/2026", "PAYMENT RECEIVED - THANK YOU", "12,000.00 Cr"),
        _row("28/09/2026", "MYNTRA", "3,000.00"),
        _row("05/10/2026", "FINANCE CHARGES", "412.50"),
        _row("05/10/2026", "IGST @18% ON FINANCE CHARGES", "74.25"),
        "Payments received this period: 12,000.00",
    ],
    Expect(
        charges=[("finance_charge", "412.50"), ("gst", "74.25")],
        total_due="3486.75",
        minimum_due="175",
        due="2026-10-25",
        statement_date="2026-10-05",
        rules={"rbi.interest_after_full_payment", "rbi.limit_cut_notice"},
    ),
    previous=INT_PREV,
)

# Only legitimate charges: a normal annual fee, a late fee paid well after the due date, and
# interest on a balance carried over. A person should see nothing to raise with the bank.
NORMAL_FEES = Scenario(
    "normal_fees",
    _hdr("05/10/2026", "25/10/2026", "21,977.95", "1,100.00")
    + [
        _row("12/09/2026", "RELIANCE FRESH PUNE", "3,200.00"),
        _row("20/09/2026", "LATE PAYMENT FEE", "600.00"),
        _row("20/09/2026", "IGST @18% ON LATE FEE", "108.00"),
        _row("30/09/2026", "PAYMENT RECEIVED - THANK YOU", "2,000.00 Cr"),
        _row("03/10/2026", "ANNUAL MEMBERSHIP FEE", "1,000.00"),
        _row("03/10/2026", "IGST @18% ON ANNUAL FEE", "180.00"),
        _row("05/10/2026", "FINANCE CHARGES", "412.50"),
        _row("05/10/2026", "IGST @18% ON FINANCE CHARGES", "74.25"),
    ],
    Expect(
        charges=[
            ("late_payment_fee", "600"),
            ("gst", "108"),
            ("annual_fee", "1000"),
            ("gst", "180"),
            ("finance_charge", "412.50"),
            ("gst", "74.25"),
        ],
        total_due="21977.95",
        minimum_due="1100",
        due="2026-10-25",
        statement_date="2026-10-05",
        rules={"info.annual_fee", "rbi.late_fee_check"},
    ),
)

SCENARIOS = [FULL, CLEAN, SCHEDULE_TRAP, OLD_FORMAT, LATE_PAIR, INT_PAIR, NORMAL_FEES]


def pdf_bytes(lines: list[str]) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=9)
    for line in lines:
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


class Cassette:
    """Replays recorded AI answers keyed by the exact prompt. In live mode it asks the AI only for
    bills without a recording (or for every bill with refresh=True), and can save the answers."""

    def __init__(self, folder: Path, live: Any = None, record: bool = False, refresh: bool = False):
        self.folder, self.live, self.record, self.refresh = folder, live, record, refresh
        self.calls = 0

    async def generate_structured(self, *, task: Any, system: str, prompt: str, schema: Any) -> Any:
        key = hashlib.sha256((system + prompt).encode()).hexdigest()[:16]
        path = self.folder / f"{key}.json"
        if path.exists() and not (self.live and self.refresh):
            return _Out(schema.model_validate_json(path.read_text(encoding="utf-8")))
        if self.live is None:
            raise FileNotFoundError(
                f"No recorded AI answer for this bill ({path.name}): the text sent to the AI changed "
                "or the bill is new. Record it with `python -m evals.bills --live --record` (one AI "
                "call per bill without a recording)."
            )
        self.calls += 1
        out = await self.live.generate_structured(
            task=task, system=system, prompt=prompt, schema=schema
        )
        if self.record:
            self.folder.mkdir(parents=True, exist_ok=True)
            path.write_text(out.data.model_dump_json(indent=1), encoding="utf-8")
        return out


@dataclass
class _Out:
    data: Any


async def _bill(source: list[str] | bytes, llm: Any) -> Bill:
    """Read a bill exactly as the API does. `bill.text` is what was sent to the AI."""
    body = source if isinstance(source, bytes) else pdf_bytes(source)
    return await read_bill(
        body, llm, filename="bill.pdf", content_type="application/pdf", max_bytes=MAX_BYTES
    )


def _num(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v).replace(",", ""))


def _iso(d: Any) -> str | None:
    return d.isoformat() if d else None


def score(
    name: str,
    bill: Bill,
    findings: list[dict[str, Any]],
    e: Expect,
    never_sent: tuple[str, ...] = (NAME, "SAMPLE NAGAR"),
) -> dict[str, Any]:
    got = Counter((c.kind, _num(c.amount)) for c in bill.facts.charges)
    want = Counter((k, _num(a)) for k, a in e.charges)
    f = bill.facts
    fields = {
        "total_due": (_num(f.total_due), _num(e.total_due)),
        "minimum_due": (_num(f.minimum_due), _num(e.minimum_due)),
        "due": (_iso(f.due), e.due),
        "statement_date": (_iso(f.statement_date), e.statement_date),
    }
    raised = {x["rule"] for x in findings}
    asks = {x["rule"] for x in findings if x.get("ask", True)}
    return {
        "name": name,
        "charges": {
            "found": sum(got.values()),
            "expected": sum(want.values()),
            "correct": sum((got & want).values()),
            "missed": sorted(map(str, (want - got).elements())),
            "extra": sorted(map(str, (got - want).elements())),
        },
        "fields": {
            k: {"got": str(g), "want": str(w), "ok": g == w} for k, (g, w) in fields.items() if w
        },
        "rules": {"missing": sorted(e.rules - raised), "false_alarms": sorted(asks - e.rules)},
        "privacy_ok": not any(s in bill.text for s in never_sent),
    }


async def run_scenario(s: Scenario, llm: Any) -> dict[str, Any]:
    bill = await _bill(s.lines, llm)
    if s.previous is None:
        out = check_bill(bill, card=None, terms=None)
    else:
        out = check_pair(await _bill(s.previous.lines, llm), bill, card=None, terms=None)
    return score(s.name, bill, out["findings"], s.expect)


async def run_private(folder: Path, llm: Any) -> list[dict[str, Any]]:
    """Real bills kept outside the repo: folder/golden.json lists {file, charges, total_due, ...}."""
    golden = json.loads((folder / "golden.json").read_text(encoding="utf-8"))
    out = []
    for g in golden:
        bill = await _bill((folder / g["file"]).read_bytes(), llm)
        expect = Expect(
            charges=[(k, a) for k, a in g.get("charges", [])],
            total_due=g.get("total_due"),
            minimum_due=g.get("minimum_due"),
            due=g.get("due"),
            statement_date=g.get("statement_date"),
            rules=set(g.get("rules", [])),
        )
        findings = check_bill(bill, card=None, terms=None)["findings"]
        out.append(score(g["file"], bill, findings, expect, tuple(g.get("never_sent", []))))
    return out


def summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    found = sum(r["charges"]["found"] for r in results)
    expected = sum(r["charges"]["expected"] for r in results)
    correct = sum(r["charges"]["correct"] for r in results)
    fields = [f["ok"] for r in results for f in r["fields"].values()]
    return {
        "bills": len(results),
        "charge_precision": round(correct / found, 3) if found else 1.0,
        "charge_recall": round(correct / expected, 3) if expected else 1.0,
        "fields_correct": round(sum(fields) / len(fields), 3) if fields else 1.0,
        "rules_missed": sum(len(r["rules"]["missing"]) for r in results),
        "false_alarms": sum(len(r["rules"]["false_alarms"]) for r in results),
        "privacy_ok": all(r["privacy_ok"] for r in results),
    }


async def run(
    llm: Any, private: Path | None = None, private_llm: Any = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results = [await run_scenario(s, llm) for s in SCENARIOS]
    if private is not None:
        results += await run_private(private, private_llm or llm)
    return results, summary(results)


def _line(r: dict[str, Any]) -> str:
    c, rules = r["charges"], r["rules"]
    wrong = [k for k, v in r["fields"].items() if not v["ok"]]
    return (
        f"{r['name']:<52} charges {c['correct']}/{c['expected']} (+{len(c['extra'])} extra)"
        f"  fields wrong: {wrong or '-'}  missed rules: {rules['missing'] or '-'}"
        f"  false alarms: {rules['false_alarms'] or '-'}"
        f"  privacy: {'ok' if r['privacy_ok'] else 'LEAK'}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--live", action="store_true", help="ask the AI again (uses quota)")
    ap.add_argument("--record", action="store_true", help="with --live: save answers for replay")
    ap.add_argument(
        "--refresh", action="store_true", help="with --live: re-ask bills already recorded"
    )
    ap.add_argument("--private", type=Path, help="folder with real bills and golden.json")
    args = ap.parse_args()

    live = make_router(get_settings()) if args.live else None
    llm = Cassette(CASSETTES, live, args.record, args.refresh)
    private_llm = (
        Cassette(args.private / "cassettes", live, args.record, args.refresh)
        if args.private
        else None
    )
    results, total = asyncio.run(run(llm, args.private, private_llm))

    for r in results:
        print(_line(r))
    print(json.dumps(total, indent=1))
    print(f"AI calls this run: {llm.calls + (private_llm.calls if private_llm else 0)}")
    ok = total["false_alarms"] == 0 and total["privacy_ok"] and total["rules_missed"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
