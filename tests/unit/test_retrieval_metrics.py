import math

import pytest

from erp_ai.knowledge.evaluation.metrics import retrieval_metrics
from tests.support.retrieval_evaluation import relevant


def test_precision_recall_mrr_and_graded_ndcg_formulas() -> None:
    expected = (relevant("a", grade=3), relevant("b", grade=1))
    precision, recall, mrr, ndcg = retrieval_metrics(("x", "b", "a"), expected, 3)
    assert precision == pytest.approx(2 / 3)
    assert recall == 1.0
    assert mrr == 0.5
    dcg = 1 / math.log2(3) + 7 / math.log2(4)
    ideal = 7 / math.log2(2) + 1 / math.log2(3)
    assert ndcg == pytest.approx(dcg / ideal)


def test_metric_zero_denominators_and_cutoff_are_explicit() -> None:
    assert retrieval_metrics(("x",), (), 1) == (0.0, 0.0, 0.0, 0.0)
    precision, recall, mrr, ndcg = retrieval_metrics(("x", "relevant"), (relevant("relevant"),), 1)
    assert (precision, recall, mrr, ndcg) == (0.0, 0.0, 0.0, 0.0)
