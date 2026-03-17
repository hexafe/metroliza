from modules.stats_number_formatting import (
    format_capability_index,
    format_measurement_value,
    format_percent_from_ratio,
    format_ppm,
    format_probability,
    format_probability_percent,
)


def test_format_capability_index_uses_two_decimals_with_trailing_zeros():
    assert format_capability_index(1.2) == '1.20'


def test_format_measurement_value_uses_three_decimals_with_trailing_zeros():
    assert format_measurement_value(10) == '10.000'


def test_format_probability_uses_small_value_notation():
    assert format_probability(0.0004) == '<0.001'
    assert format_probability(0.0042) == '0.004'


def test_format_probability_percent_uses_small_value_notation():
    assert format_probability_percent(0.0000009) == '<0.001%'
    assert format_probability_percent(0.0001234) == '0.012%'


def test_format_percent_from_ratio_uses_fixed_decimals():
    assert format_percent_from_ratio(0.1234, decimals=3) == '12.340%'


def test_format_ppm_uses_grouping_without_decimals():
    assert format_ppm(1234.56) == '1,235'
