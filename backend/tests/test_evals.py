"""The bill checker accuracy test set, replayed from recorded AI answers (no AI calls). A drop
here means a code change made Ritam read bills worse. If the text sent to the AI changes, the
recordings must be redone once with: python -m evals.bills --live --record"""

from evals.bills import CASSETTES, Cassette, run


async def test_bill_checker_accuracy_set_is_perfect():
    results, total = await run(Cassette(CASSETTES))
    assert total["bills"] == 7
    assert total["privacy_ok"], "a name or address reached the AI"
    assert total["false_alarms"] == 0, [r["rules"] for r in results if r["rules"]["false_alarms"]]
    assert total["rules_missed"] == 0, [r["rules"] for r in results if r["rules"]["missing"]]
    assert total["charge_precision"] == 1.0 and total["charge_recall"] == 1.0, [
        r["charges"] for r in results
    ]
    assert total["fields_correct"] == 1.0, [r["fields"] for r in results]
