import json

from tests.support.synthetic_hr_knowledge import FIXTURE_ROOT


def test_version_one_is_aggregate_only_and_permanently_invalidated() -> None:
    record = json.loads((FIXTURE_ROOT / "invalidations" / "v1.json").read_text(encoding="utf-8"))
    assert record["dataset_version"] == "1.0.0"
    assert record["status"] == "invalidated_before_checkpoint"
    assert len(record["integrity_defects"]) == 4
    assert record["aborted_attempt_observed_calibration_or_holdout"] is False
    assert record["completed_results_support_threshold_approval"] is False
    serialized = json.dumps(record, sort_keys=True)
    assert "query_text" not in serialized and "source_content" not in serialized
