"""Pure computation helpers used by CSV summary worker thread."""

import pandas as pd


def compute_histogram_payload(series_values, bin_count):
    """Return histogram bucket labels and counts for a numeric series."""
    series = pd.Series(series_values)
    bins = pd.cut(series, bins=bin_count)
    counts = bins.value_counts().sort_index()
    return [(str(interval), int(count)) for interval, count in counts.items()]


def compute_boxplot_summary(series_values):
    """Return five-number summary values used for boxplot worksheet output."""
    series = pd.Series(series_values)
    return [
        ('Min', float(series.min())),
        ('Q1', float(series.quantile(0.25))),
        ('Median', float(series.median())),
        ('Q3', float(series.quantile(0.75))),
        ('Max', float(series.max())),
    ]
