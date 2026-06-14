from __future__ import annotations

import math
import struct
from datetime import date
from typing import Any

from pipeline.lpe_pipeline.postcodes import canonical_postcode

BINARY_MAGIC = b"LPE1"
BINARY_HEADER_BYTES = 8
BINARY_BYTES_PER_POINT = 23
POSTCODE_BYTES = 8
TYPE_TO_CODE = {"D": 0, "S": 1, "T": 2, "F": 3, "O": 4}
EPOCH = date(1970, 1, 1)


class BinaryEncodingError(ValueError):
    pass


def _date_days(value: date | str) -> int:
    parsed = date.fromisoformat(value) if isinstance(value, str) else value
    days = (parsed - EPOCH).days
    if not 0 <= days <= 0xFFFF:
        raise BinaryEncodingError(f"date outside Uint16 epoch-day range: {parsed}")
    return days


def encode_points(rows: list[dict[str, Any]]) -> bytes:
    count = len(rows)
    payload = bytearray(BINARY_HEADER_BYTES + BINARY_BYTES_PER_POINT * count)
    payload[0:4] = BINARY_MAGIC
    struct.pack_into("<I", payload, 4, count)
    lng_offset = BINARY_HEADER_BYTES
    lat_offset = lng_offset + 4 * count
    price_offset = lat_offset + 4 * count
    date_offset = price_offset + 4 * count
    type_offset = date_offset + 2 * count
    postcode_offset = type_offset + count
    for index, row in enumerate(rows):
        longitude = float(row["lng"])
        latitude = float(row["lat"])
        if not math.isfinite(longitude) or not -180 <= longitude <= 180:
            raise BinaryEncodingError(f"invalid longitude: {longitude}")
        if not math.isfinite(latitude) or not -90 <= latitude <= 90:
            raise BinaryEncodingError(f"invalid latitude: {latitude}")
        property_type = str(row["type"])
        if property_type not in TYPE_TO_CODE:
            raise BinaryEncodingError(f"invalid property type: {property_type}")
        postcode = str(row["postcode"])
        try:
            if canonical_postcode(postcode) != postcode:
                raise BinaryEncodingError(f"postcode is not canonical: {postcode}")
        except ValueError as exc:
            raise BinaryEncodingError(str(exc)) from exc
        try:
            postcode_raw = postcode.encode("ascii")
        except UnicodeEncodeError as exc:
            raise BinaryEncodingError("postcode must be ASCII") from exc
        if len(postcode_raw) > POSTCODE_BYTES:
            raise BinaryEncodingError(f"postcode exceeds {POSTCODE_BYTES} bytes: {postcode}")
        price = int(row["price"])
        if not 10_000 <= price <= 50_000_000:
            raise BinaryEncodingError(f"price outside application range: {price}")
        struct.pack_into("<f", payload, lng_offset + 4 * index, longitude)
        struct.pack_into("<f", payload, lat_offset + 4 * index, latitude)
        struct.pack_into("<I", payload, price_offset + 4 * index, price)
        struct.pack_into("<H", payload, date_offset + 2 * index, _date_days(row["date"]))
        payload[type_offset + index] = TYPE_TO_CODE[property_type]
        start = postcode_offset + POSTCODE_BYTES * index
        payload[start : start + len(postcode_raw)] = postcode_raw
    return bytes(payload)
