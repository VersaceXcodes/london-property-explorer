import pytest

from pipeline.lpe_pipeline.postcodes import canonical_postcode, postcode_district, postcode_join_key


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sw114nb", "SW11 4NB"),
        (" SW11 4nb ", "SW11 4NB"),
        ("ec1a1bb", "EC1A 1BB"),
        ("e8 1aa", "E8 1AA"),
    ],
)
def test_canonical_postcode(raw: str, expected: str) -> None:
    assert canonical_postcode(raw) == expected
    assert postcode_join_key(raw) == expected.replace(" ", "")
    assert postcode_district(raw) == expected.split()[0]


@pytest.mark.parametrize("raw", ["", "ABC 1AA", "SW1 14NB", "SW11-4NB", "11 1AA"])
def test_invalid_postcodes(raw: str) -> None:
    with pytest.raises(ValueError):
        canonical_postcode(raw)
