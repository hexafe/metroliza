from modules.csv_summary_worker_helpers import compute_boxplot_summary, compute_histogram_payload


def test_compute_histogram_payload_returns_interval_counts():
    payload = compute_histogram_payload([1, 1, 2, 3], 2)

    assert len(payload) == 2
    assert sum(count for _, count in payload) == 4


def test_compute_boxplot_summary_returns_five_number_summary():
    summary = compute_boxplot_summary([1, 2, 3, 4])

    labels = [name for name, _ in summary]
    assert labels == ['Min', 'Q1', 'Median', 'Q3', 'Max']
