"""Independent row-ID oracle from #995's accepted finite-source decision."""

from metroliza.shared.grouping_filter_core import MembershipFilterSpec, NumberFilterSpec


# Exactly the 23 source rows in the #925 assessment; IDs are one-based positions.
PROBE_VALUES = (
    None, "", " ", "abc", "1x", "1.2x", "0", "0.0", "-0", "+0", "1", "-1",
    "1.2", "+1.2", ".5", "1.", "1e2", " 2 ", "Inf", "-Inf", "NaN", "+1e2", "1e999",
)

# Expectations are stated independently, never calculated by either implementation.
PROBE_CASES = (
    (NumberFilterSpec("reference", "eq", 0), [7, 8, 9, 10]),
    (NumberFilterSpec("reference", "ne", 0),
     [1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23]),
    (NumberFilterSpec("reference", "gt", -1),
     [7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 22]),
    (NumberFilterSpec("reference", "gte", 0),
     [7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 22]),
    (NumberFilterSpec("reference", "lt", 1), [7, 8, 9, 10, 12, 15]),
    (NumberFilterSpec("reference", "lte", 0), [7, 8, 9, 10, 12]),
    (NumberFilterSpec("reference", "between", -1, 1), [7, 8, 9, 10, 11, 12, 15, 16]),
    (NumberFilterSpec("reference", "is_blank"), [1, 2, 3, 4, 5, 6, 19, 20, 21, 23]),
    (NumberFilterSpec("reference", "is_not_blank"),
     [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 22]),
    (MembershipFilterSpec("reference", (0, .5, 1, 1.2, 100)),
     [7, 8, 9, 10, 11, 13, 14, 15, 16, 17, 22]),
    (MembershipFilterSpec("reference", (0, .5, 1, 1.2, 100), negate=True),
     [1, 2, 3, 4, 5, 6, 12, 18, 19, 20, 21, 23]),
)
