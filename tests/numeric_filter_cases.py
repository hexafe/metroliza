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


PRECISION_VALUES = (
    2**53, 2**53 + 1, "9007199254740993", "9007199254740993.0", float(2**53),
    2**63 - 1, "9223372036854775807", "9223372036854775808", "9223372036854775809",
    "18446744073709551615", float(2**63), None,
)
PRECISION_CASES = (
    (NumberFilterSpec("reference", "eq", 2**53), [1, 4, 5]),
    (NumberFilterSpec("reference", "eq", 2**53 + 1), [2, 3]),
    (NumberFilterSpec("reference", "gt", 2**53), [2, 3, 6, 7, 8, 9, 10, 11]),
    (NumberFilterSpec("reference", "lte", 2**53), [1, 4, 5]),
    (NumberFilterSpec("reference", "between", 2**63 - 1, 2**53 + 1), [2, 3, 6, 7]),
    (NumberFilterSpec("reference", "eq", 2**63 - 1), [6, 7]),
    (NumberFilterSpec("reference", "lt", 2**63), [1, 2, 3, 4, 5, 6, 7]),
    (NumberFilterSpec("reference", "gt", 2**63), [9, 10]),
    (MembershipFilterSpec("reference", (2**63,)), [8, 11]),
    (MembershipFilterSpec("reference", (2**63,), negate=True), [1, 2, 3, 4, 5, 6, 7, 9, 10, 12]),
    (NumberFilterSpec("reference", "is_blank"), [12]),
)

# Scalar boundary oracle: exact known numbers, including neighbouring binary64
# values. Invalid syntax stays invalid even when Python float() accepts it.
SOURCE_CASES = (
    ("254.8182562205433470848", float.fromhex("0x1.fda2f27ab5f6fp+7")),
    ("2548182562205433470848e-19", float.fromhex("0x1.fda2f27ab5f6fp+7")),
    ("-254.8182562205433470848", -float.fromhex("0x1.fda2f27ab5f6fp+7")),
    (0.2754124212333596, 0.2754124212333596),
    ("+1.2", 1.2), (".5", .5), ("1.", 1), ("+1e2", 100), ("01.50e+01", 15),
    ("1.e2", 100), ("-.1e-1", -.01), ("-000", 0), ("+00001", 1),
    ("\t\r\n\v\f 2 \t\r\n\v\f", 2), ("1e-999", 0), ("-1e-999", 0),
    ("1.0000000000000002", 1.0000000000000002),
    ("1.2345678901234567", 1.2345678901234567),
    ("1.7976931348623157e308", float.fromhex("0x1.fffffffffffffp+1023")),
    ("1.7976931348623158e308", float.fromhex("0x1.fffffffffffffp+1023")),
    ("-1.7976931348623157e308", -float.fromhex("0x1.fffffffffffffp+1023")),
    ("5e-324", float.fromhex("0x0.0000000000001p-1022")),
    ("2e-324", 0), ("3e-324", float.fromhex("0x0.0000000000001p-1022")),
    (-(2**63), -(2**63)), (str(-(2**63)), -(2**63)),
    (str(-(2**63) + 1), -(2**63) + 1),
    (True, 1), (False, 0), (0, 0), (-.5, -.5),
    (None, None), ("", None), (" \t", None), ("abc", None), ("1x", None), ("1.2x", None),
    ("+", None), (".", None), ("1.2.3", None), ("1e", None), ("1e+", None),
    ("1ee2", None), ("1e1e1", None), ("--1", None), ("+-1", None), ("1 2", None),
    ("0x10", None), ("1_0", None), ("１２", None), ("\u00a01\u00a0", None),
    ("1\x00x", None), ("1\x00", None), (b"1", None),
    ("NaN", None), ("+Inf", None), ("-Infinity", None), ("Infinity", None),
    (float("nan"), None), (float("inf"), None), (-float("inf"), None),
    ("1e999", None), ("-1e999", None), ("1.7976931348623159e308", None),
)


# Independently stated binary64 row scope, including exact ties to even.
_ROUNDED_UP = float.fromhex("0x1.fda2f27ab5f6fp+7")
_ROUNDED_DOWN = float.fromhex("0x1.fda2f27ab5f6ep+7")
ROUNDING_VALUES = (
    "254.8182562205433470848", "2548182562205433470848e-19", _ROUNDED_UP,
    "254.81825622054336", _ROUNDED_DOWN, "254.81825622054333",
    "-254.8182562205433470848", -_ROUNDED_UP, -_ROUNDED_DOWN, None, "bad",
    "254.8182562205433470126081374473869800567626953125",  # lower tie -> even lower float
    "254.8182562205433754343175678513944149017333984375",  # upper tie -> even upper float
    "1.00000000000000011102230246251565404236316680908203125",  # exact tie -> 1
    "1.000000000000000111022302462515654042363166809082031251",  # above tie -> next float
    "-1.00000000000000011102230246251565404236316680908203125",
)
ROUNDING_CASES = (
    (NumberFilterSpec("reference", "eq", _ROUNDED_UP), [1, 2, 3, 4]),
    (NumberFilterSpec("reference", "ne", _ROUNDED_UP), [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]),
    (NumberFilterSpec("reference", "gt", _ROUNDED_UP), [13]),
    (NumberFilterSpec("reference", "gte", _ROUNDED_UP), [1, 2, 3, 4, 13]),
    (NumberFilterSpec("reference", "lt", _ROUNDED_UP), [5, 6, 7, 8, 9, 12, 14, 15, 16]),
    (NumberFilterSpec("reference", "lte", _ROUNDED_UP), [1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 14, 15, 16]),
    (NumberFilterSpec("reference", "between", _ROUNDED_DOWN, _ROUNDED_UP), [1, 2, 3, 4, 5, 6, 12]),
    (NumberFilterSpec("reference", "eq", -_ROUNDED_UP), [7, 8]),
    (MembershipFilterSpec("reference", (_ROUNDED_UP, 1, -1)), [1, 2, 3, 4, 14, 16]),
    (MembershipFilterSpec("reference", (_ROUNDED_UP, 1, -1), negate=True), [5, 6, 7, 8, 9, 10, 11, 12, 13, 15]),
)
