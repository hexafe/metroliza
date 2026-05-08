from modules.filter_state import FilterState, summarize_filter_state
from datetime import date


def test_summarize_filter_state_not_applied_when_empty():
    label, tooltip = summarize_filter_state(FilterState())
    assert label == "Not applied"
    assert tooltip == "Not applied"


def test_summarize_filter_state_hides_default_broad_date_range():
    state = FilterState(date_from="1970-01-01", date_to=date.today().isoformat())
    label, tooltip = summarize_filter_state(state)
    assert label == "Not applied"
    assert tooltip == "Not applied"


def test_summarize_filter_state_shows_nondefault_date_range():
    state = FilterState(date_from="2024-01-01", date_to="2024-12-31")
    label, tooltip = summarize_filter_state(state)
    assert label == "Date: 2024-01-01 to 2024-12-31"
    assert tooltip == "Date: 2024-01-01 to 2024-12-31"


def test_summarize_filter_state_shows_one_value_and_counts_many_values():
    state = FilterState(reference_values=("REF1",), header_values=("H1", "H2"))
    label, tooltip = summarize_filter_state(state)
    assert label == "Reference: REF1; Header: 2 selected"
    assert "Reference: REF1" in tooltip
    assert "Header: H1, H2" in tooltip
