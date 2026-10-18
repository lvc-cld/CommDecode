import random

import numpy as np
import pytest

from bitfield import Payload, PayloadArray, extract_raw, field_bit_positions


def test_big_endian_contiguous_field():
    # 12 bits starting at bit 4 of 0x0ABC -> 0xABC
    assert extract_raw(Payload.from_hex('0ABC'), 4, 12, 'big', False) == 0xABC


def test_little_endian_byte_aligned_field():
    # Low byte first: 34 12 -> 0x1234
    assert extract_raw(Payload.from_hex('3412'), 0, 16, 'little', False) == 0x1234


def test_little_endian_non_aligned_field_uses_intel_layout():
    # TestData/WheelSpeed: raw 0xD45 stored as bytes 51 D4 (LSB at Intel bit 4)
    assert extract_raw(Payload.from_hex('51D4'), 4, 12, 'little', False) == 0xD45


@pytest.mark.parametrize('endianness,payload', [('big', '7FF0'), ('little', 'FF07')])
def test_signed_values_stay_in_field_range(endianness, payload):
    assert extract_raw(Payload.from_hex(payload), 0, 12, endianness, True) == 2047
    assert extract_raw(Payload.from_hex('8000' if endianness == 'big' else '0008'), 0, 12, endianness, True) == -2048


def test_field_past_end_returns_none():
    assert extract_raw(Payload.from_hex('FF'), 4, 8, 'big', False) is None


def test_little_endian_needs_whole_bytes():
    assert extract_raw(Payload.from_hex('ABC'), 0, 8, 'little', False) is None


@pytest.mark.parametrize('bad', ['', 'XYZ', '12-4', '1_2'])
def test_invalid_hex_is_rejected(bad):
    with pytest.raises(ValueError):
        Payload.from_hex(bad)


def test_binary_and_hex_parse_the_same():
    a = Payload.from_hex('A1B2')
    b = Payload.from_bits('1010000110110010')
    assert (a.n_bits, a.big, a.little) == (b.n_bits, b.big, b.little)


@pytest.mark.parametrize('n_bytes', [8, 16])  # uint64 path and Python-int path
def test_vectorized_extraction_matches_scalar(n_bytes):
    rng = random.Random(0)
    payloads = [Payload.from_hex(''.join(rng.choice('0123456789ABCDEF') for _ in range(2 * n_bytes)))
                for _ in range(20)]
    array = PayloadArray(payloads)
    for _ in range(200):
        length = rng.choice([4, 6, 8, 12, 16, 24])
        offset = rng.randrange(0, n_bytes * 8 - length + 1)
        endianness = rng.choice(['big', 'little'])
        signed = rng.choice([False, True])
        expected = [extract_raw(p, offset, length, endianness, signed) for p in payloads]
        np.testing.assert_array_equal(array.extract(offset, length, endianness, signed), expected)


def test_little_endian_bit_positions_for_display():
    # Intel bits 4..15 = high nibble of byte 0 and all of byte 1
    assert sorted(field_bit_positions(4, 12, 'little')) == [0, 1, 2, 3] + list(range(8, 16))
