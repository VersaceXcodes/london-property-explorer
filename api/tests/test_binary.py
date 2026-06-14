from datetime import date
from struct import unpack_from

import pytest

from api.app.services.binary import BINARY_MAGIC, BinaryEncodingError, encode_points


def test_binary_layout() -> None:
    payload = encode_points(
        [
            {
                "lng": -0.16,
                "lat": 51.47,
                "price": 485_000,
                "date": date(2024, 3, 1),
                "type": "F",
                "postcode": "SW11 4NB",
            }
        ]
    )
    assert payload[:4] == BINARY_MAGIC
    assert unpack_from("<I", payload, 4)[0] == 1
    assert len(payload) == 31
    assert payload[-8:] == b"SW11 4NB"


def test_binary_rejects_bad_postcode() -> None:
    with pytest.raises(BinaryEncodingError):
        encode_points(
            [
                {
                    "lng": 0,
                    "lat": 0,
                    "price": 1,
                    "date": date.today(),
                    "type": "F",
                    "postcode": "TOO LONG 1AA",
                }
            ]
        )


def test_binary_rejects_invalid_coordinates() -> None:
    with pytest.raises(BinaryEncodingError, match="longitude"):
        encode_points(
            [
                {
                    "lng": float("nan"),
                    "lat": 51.5,
                    "price": 485_000,
                    "date": date(2024, 3, 1),
                    "type": "F",
                    "postcode": "SW11 4NB",
                }
            ]
        )
