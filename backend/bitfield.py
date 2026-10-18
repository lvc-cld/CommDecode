"""
Shared bit-field helpers used by both decoders.

Bit numbering:
- 'big' (Motorola, sequential): bit_offset counts from the MSB of byte 0,
  and the field is a contiguous run of bits read MSB first.
- 'little' (Intel, as in CAN DBC files): bit_offset is the position of the
  field's LSB, where bit k is bit (k % 8) of byte (k // 8) and bit 0 is the
  LSB of byte 0. For byte-aligned fields this is the usual "low byte first".
"""

import re
from typing import List, Optional

import numpy as np
from scipy import special, stats

BIT_LENGTHS = [4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24]
ENDIANNESS_OPTIONS = ['big', 'little']
SIGNEDNESS_OPTIONS = [False, True]

_HEX_RE = re.compile(r'^[0-9a-fA-F]*$')
_BIN_RE = re.compile(r'^[01]*$')


def clean_hex(hex_string: str) -> str:
    """Remove spaces and 0x prefixes from a hex payload string."""
    return hex_string.replace(' ', '').replace('0x', '').replace('0X', '')


class Payload:
    """A payload parsed once into integers for fast bit-field extraction."""

    __slots__ = ('n_bits', 'big', 'little')

    def __init__(self, n_bits: int, big: int, little: Optional[int]):
        self.n_bits = n_bits
        self.big = big
        # Intel extraction needs whole bytes
        self.little = little

    @classmethod
    def from_hex(cls, hex_string: str) -> 'Payload':
        clean = clean_hex(hex_string)
        if not clean or not _HEX_RE.match(clean):
            raise ValueError(f"Invalid hex payload: {hex_string!r}")
        little = int.from_bytes(bytes.fromhex(clean), 'little') if len(clean) % 2 == 0 else None
        return cls(len(clean) * 4, int(clean, 16), little)

    @classmethod
    def from_bits(cls, bit_string: str) -> 'Payload':
        if not bit_string or not _BIN_RE.match(bit_string):
            raise ValueError(f"Invalid binary payload: {bit_string!r}")
        n_bits = len(bit_string)
        big = int(bit_string, 2)
        little = int.from_bytes(big.to_bytes(n_bits // 8, 'big'), 'little') if n_bits % 8 == 0 else None
        return cls(n_bits, big, little)


def extract_raw(payload: Payload, bit_offset: int, bit_length: int,
                endianness: str, signed: bool) -> Optional[int]:
    """Extract one integer field from a payload, or None if it does not fit."""
    if bit_offset + bit_length > payload.n_bits:
        return None

    mask = (1 << bit_length) - 1
    if endianness == 'big':
        value = (payload.big >> (payload.n_bits - bit_offset - bit_length)) & mask
    else:
        if payload.little is None:
            return None
        value = (payload.little >> bit_offset) & mask

    # Two's complement on the field's own width
    if signed and value >> (bit_length - 1):
        value -= 1 << bit_length

    return value


class PayloadArray:
    """
    Many payloads stored as numpy arrays, so one field can be extracted from
    all of them in a single vectorized step. Uses uint64 when every payload
    fits in 64 bits, else Python ints in object arrays.
    """

    def __init__(self, payloads: List[Payload]):
        dtype = np.uint64 if all(p.n_bits <= 64 for p in payloads) else object
        self.n_bits = np.array([p.n_bits for p in payloads], dtype=np.int64)
        self.big = np.array([p.big for p in payloads], dtype=dtype)
        self.has_little = np.array([p.little is not None for p in payloads])
        self.little = np.array([p.little or 0 for p in payloads], dtype=dtype)
        self.dtype = dtype

    def extract(self, bit_offset: int, bit_length: int, endianness: str, signed: bool) -> np.ndarray:
        """Extract a field from every payload. Payloads it does not fit in give NaN."""
        fits = self.n_bits >= bit_offset + bit_length
        if endianness == 'big':
            shift = np.where(fits, self.n_bits - bit_offset - bit_length, 0).astype(self.dtype)
            source = self.big
        else:
            fits &= self.has_little
            shift = self.dtype(bit_offset) if self.dtype is np.uint64 else bit_offset
            source = self.little
        mask = (1 << bit_length) - 1
        if self.dtype is np.uint64:
            mask = np.uint64(mask)
        values = ((source >> shift) & mask).astype(np.float64)
        if signed:
            half = float(1 << (bit_length - 1))
            values = np.where(values >= half, values - 2 * half, values)
        return np.where(fits, values, np.nan)


def field_bit_positions(bit_offset: int, bit_length: int, endianness: str):
    """
    Return the payload bit positions of a field in MSB-first numbering
    (position 0 = MSB of byte 0), for display purposes.
    """
    if endianness == 'big':
        return list(range(bit_offset, bit_offset + bit_length))
    return [(k // 8) * 8 + (7 - k % 8) for k in range(bit_offset, bit_offset + bit_length)]


def linear_fit(x: np.ndarray, y: np.ndarray):
    """Least-squares fit y = slope * x + intercept. Returns (slope, intercept, r)."""
    x_mean = x.mean()
    y_mean = y.mean()
    dx = x - x_mean
    dy = y - y_mean
    sxx = np.dot(dx, dx)
    syy = np.dot(dy, dy)
    if sxx <= 0 or syy <= 0:
        return 0.0, y_mean, 0.0
    sxy = np.dot(dx, dy)
    slope = sxy / sxx
    return slope, y_mean - slope * x_mean, sxy / np.sqrt(sxx * syy)


def correlation_p_value(r: float, n: int) -> float:
    """Two-sided p-value of a Pearson correlation r over n samples (same as scipy.stats.pearsonr)."""
    if n <= 2:
        return 1.0
    if abs(r) >= 1.0:
        return 0.0
    t = abs(r) * np.sqrt((n - 2) / (1.0 - r * r))
    return float(2.0 * special.stdtr(n - 2, -t))


def calculate_error_pct(actual: np.ndarray, predicted: np.ndarray) -> float:
    """
    Mean absolute error as a percentage of the reference value range.

    Normalizing by the range (not by each value, as MAPE does) keeps the
    metric stable for signals that cross or sit near zero.
    """
    value_range = np.max(actual) - np.min(actual)
    if value_range <= 0:
        return float('inf')
    return float(np.mean(np.abs(actual - predicted)) / value_range * 100)


def calculate_confidence_score(r_squared: float, error_pct: float) -> float:
    """Composite score in [0, 1]: half fit quality (R²), half error (10% error -> 0)."""
    error_score = max(0.0, 1.0 - error_pct / 10.0)
    return 0.5 * r_squared + 0.5 * error_score


def layout_preference(candidate) -> tuple:
    """
    Sort key among candidates that produce identical decoded values
    (for example a field and the same field with constant zero top bits).
    Lower is preferred: byte-aligned, unsigned, big-endian, then shorter.
    """
    aligned = candidate.bit_offset % 8 == 0 and candidate.bit_length % 8 == 0
    return (not aligned, candidate.signed, candidate.endianness != 'big', candidate.bit_length)


def varying_bits_mask(candidate) -> int:
    """
    Bit mask (over MSB-first payload positions) of the field bits whose value
    changes across the decoded samples. Constant bits carry no information.
    """
    mask = (1 << candidate.bit_length) - 1
    raw = [int(v) & mask for v in candidate.extracted_values]
    varying = 0
    for v in raw:
        varying |= v ^ raw[0]
    positions = field_bit_positions(candidate.bit_offset, candidate.bit_length, candidate.endianness)
    result = 0
    for i in range(candidate.bit_length):
        if varying >> i & 1:
            # positions are listed MSB first for 'big' and LSB first for 'little'
            pos = positions[candidate.bit_length - 1 - i] if candidate.endianness == 'big' else positions[i]
            result |= 1 << pos
    return result


def adds_information(reference: np.ndarray, x_small: np.ndarray, x_large: np.ndarray,
                     alpha: float) -> bool:
    """
    Nested F-test: does adding x_large to the fit reference ~ x_small
    reduce the residual error significantly (p < alpha)?
    """
    n = len(reference)
    if n <= 3:
        return False
    ones = np.ones(n)
    rss_small = _rss(np.column_stack([x_small, ones]), reference)
    if rss_small <= _exact_fit_rss(reference):
        return False  # x_small already fits exactly
    rss_both = _rss(np.column_stack([x_small, x_large, ones]), reference)
    if rss_both <= _exact_fit_rss(reference):
        return True
    f_stat = (rss_small - rss_both) / (rss_both / (n - 3))
    return stats.f.sf(f_stat, 1, n - 3) < alpha


def _exact_fit_rss(reference: np.ndarray) -> float:
    """Residual sum of squares below which a fit counts as exact (float noise)."""
    centered = reference - reference.mean()
    return 1e-18 * max(float(np.dot(centered, centered)), 1e-300)


def _rss(design: np.ndarray, y: np.ndarray) -> float:
    """Residual sum of squares of a least-squares fit."""
    coef, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    residual = y - design @ coef
    return float(np.dot(residual, residual))


# Bit counts at or below this may differ between two candidates that the
# data cannot tell apart, and the layout preference then decides. A real
# field that lost 3 or more low bits would fit at least 8x worse, which
# the F-test detects, so more extra bits that add nothing are noise.
MAX_AMBIGUOUS_EXTRA_BITS = 2

# Significance level for extra bits. Stricter than the usual 0.05 because
# each real field is compared with many noise-padded variants of itself.
EXTRA_BITS_ALPHA = 0.01

# Only the best candidates are compared pairwise (the comparison is O(n²))
MAX_PAIRWISE_CANDIDATES = 300


def rank_candidates(candidates: list, reference_values, group_key=lambda c: ()) -> list:
    """
    Sort candidates by confidence after two clean-up steps:
    1. Layouts that decode to the same values collapse into one entry,
       keeping the preferred layout.
    2. When one candidate's varying bits strictly contain another's, and the
       extra bits do not improve the fit significantly (nested F-test), one
       of the two is dropped: the smaller one if the extra bits are few
       (at most MAX_AMBIGUOUS_EXTRA_BITS) and the larger layout is
       preferred, else the larger one. This removes fields padded with
       unrelated noise bits and fields that lost low-order bits.
    """
    groups = {}
    for c in candidates:
        key = group_key(c) + tuple(np.round(c.predicted_values, 6))
        best = groups.get(key)
        if best is None or layout_preference(c) < layout_preference(best):
            groups[key] = c
    unique = sorted(groups.values(), key=lambda c: (-c.confidence_score, layout_preference(c)))
    head = unique[:MAX_PAIRWISE_CANDIDATES]

    reference = np.asarray(reference_values, dtype=np.float64)
    masks = [varying_bits_mask(c) for c in head]
    dropped = set()
    for i, large in enumerate(head):
        for j, small in enumerate(head):
            if (i == j or masks[i] == masks[j] or masks[i] & masks[j] != masks[j]
                    or group_key(large) != group_key(small)):
                continue
            # small's varying bits are a strict subset of large's
            x_small = np.asarray(small.extracted_values, dtype=np.float64)
            x_large = np.asarray(large.extracted_values, dtype=np.float64)
            if adds_information(reference, x_small, x_large, EXTRA_BITS_ALPHA):
                continue
            extra_bits = bin(masks[i] & ~masks[j]).count('1')
            if (extra_bits <= MAX_AMBIGUOUS_EXTRA_BITS
                    and layout_preference(large) < layout_preference(small)
                    and not adds_information(reference, x_large, x_small, EXTRA_BITS_ALPHA)):
                dropped.add(j)
            else:
                dropped.add(i)

    return [c for i, c in enumerate(head) if i not in dropped] + unique[MAX_PAIRWISE_CANDIDATES:]
