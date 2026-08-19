"""R601 — extract_numbers(explanation_text) (pure, FR-7 support).

Acceptance (tasks.md R601): a narrative with N numbers yields exactly those N values; formatted
numbers (commas, units, %, "mm") are captured; prose without numbers -> empty set.

Each extracted number carries its parsed float VALUE (for tolerance comparison in R603) and the
raw token as it appeared (for naming the offending number in a tripwire message). This is the
first half of the numeric-provenance guardrail (mandate #2): you cannot verify a number you did
not extract.
"""
from __future__ import annotations

from agents.risk_reasoning.guardrail import extract_numbers


def _values(text):
    return [n.value for n in extract_numbers(text)]


def test_plain_integers_and_decimals():
    nums = _values("The score is 72 and the ratio was 0.84.")
    assert nums == [72.0, 0.84]


def test_percentage_is_captured_as_its_numeric_value():
    nums = extract_numbers("Vibration reached 84% of the limit.")
    assert len(nums) == 1
    assert nums[0].value == 84.0
    assert "%" in nums[0].raw or "84" in nums[0].raw


def test_units_are_stripped_to_the_number():
    nums = _values("Deflection was 48 mm against a 50 mm limit.")
    assert nums == [48.0, 50.0]


def test_thousands_separators_are_handled():
    nums = _values("The cycle processed 1,250 samples.")
    assert nums == [1250.0]


def test_negative_numbers_captured():
    nums = _values("Temperature compensation was -3.5 degrees.")
    assert nums == [-3.5]


def test_prose_without_numbers_is_empty():
    assert extract_numbers("The bridge appears stable with no notable change.") == ()
    assert extract_numbers("") == ()


def test_multiple_numbers_all_captured_in_order():
    nums = _values("Factors 90, 30 and 55 combined to 59, mapped to WARNING.")
    assert nums == [90.0, 30.0, 55.0, 59.0]


def test_raw_token_preserved_for_tripwire_message():
    # The raw token lets a tripwire say exactly which number failed (e.g. "48 mm").
    nums = extract_numbers("Deflection was 48 mm.")
    assert nums[0].raw.strip().startswith("48")


def test_decimal_without_leading_zero():
    nums = _values("A ratio of .84 was observed.")
    assert nums == [0.84]
