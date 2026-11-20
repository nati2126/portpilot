"""Failure signatures seen in fmt's tests on QNX 8.0 (QEMU x86_64, Nov 4, 2026)."""

from __future__ import annotations

from portpilot.testfail import classify

# shape of fmt printf-test output on QNX without muslflt (values from the real log)
HEX = """[ RUN      ] printf_test.float_precision
test/printf-test.cc:326: Failure
Expected equality of these values:
  buffer
    Which is: "0x9.a52p+7"
  test_sprintf("%.3a", 1234.5678)
    Which is: "0x1.34ap+10"
[  FAILED  ] printf_test.float_precision (0 ms)
"""

LONG = """test/format-test.cc:1352: Failure
Expected equality of these values:
  buffer
    Which is: "123023192216111717693155{z}.0"
  fmt::format("{{:#.1000g}}", large)
    Which is: "123023192216111717693155881327675251464071389573683{d}.0"
""".format(z="0" * 80, d="1" * 50)

OTHER = """Expected equality of these values:
  s
    Which is: "hello"
  t
    Which is: "world"
"""


def test_hex_float_difference_is_float_format() -> None:
    (c,) = classify(HEX)
    assert c.rule_id == "float-format" and "0x9.a52p+7" in c.evidence


def test_long_decimal_expansion_is_float_format() -> None:
    assert [c.rule_id for c in classify(LONG)] == ["float-format"]


def test_unrelated_failures_are_not_classified() -> None:
    assert classify(OTHER) == []
    assert classify("Segmentation fault\n") == []


def test_round_trip_float_from_unquoted_gtest_values() -> None:
    """yaml-cpp NodeTest.FloatingPrecisionDouble on QNX 8.0."""
    log = ("node_test.cpp:672: Failure\nExpected equality of these values:\n  x\n"
           "    Which is: 0.123456789\n  node.as<double>()\n"
           "    Which is: 0.12345678900000001\n")
    assert [c.rule_id for c in classify(log)] == ["float-format"]
    # a real numeric difference, or a short rendering, is not a formatting problem
    assert classify("    Which is: 1.25\n    Which is: 1.5\n") == []
    assert classify("    Which is: 0.1\n    Which is: 0.10000000000000002\n") != []
    assert classify("    Which is: 0.1\n    Which is: 0.1000001\n") == []


def test_double_bits_after_parse_is_float_format() -> None:
    """open62541 check_types_builtin_json on QNX 8.0 (strtod, F-015)."""
    log = ("check_types_builtin_json.c:1896:F:json_encode:UA_Variant_Double2_json_encode:0: "
           "Assertion 'memcmp(&srcData, &outData, sizeof(UA_Double)) == 0' failed\n")
    [c] = classify(log)
    assert c.rule_id == "float-format" and "double bits differ" in c.evidence
    # a memcmp of anything else is not a float problem
    assert classify("Assertion 'memcmp(a, b, sizeof(UA_Guid)) == 0' failed\n") == []
