from kairos import evaluation


def test_eval_suite_passes():
    r = evaluation.run_suite()
    assert r["failed"] == 0, r["results"]
