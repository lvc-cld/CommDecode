"""
Communication Decoder - Core Algorithm

This module implements the bit-group detection algorithm for identifying
where specific measurements are encoded within binary data payloads.

Algorithm:
1. Sliding window across all bit positions
2. Extract values using different bit lengths (4, 8, 12, 16)
3. Try all combinations of endianness and signedness
4. Calculate Pearson correlation with reference values
5. Validate candidates with linear regression and MAPE check
6. Rank candidates by correlation strength
"""

import numpy as np
from scipy import stats
from dataclasses import dataclass
from typing import List, Tuple, Optional
import struct


@dataclass
class DecodingCandidate:
    """Represents a potential bit group location match."""
    bit_offset: int
    bit_length: int
    endianness: str  # 'big' or 'little'
    signed: bool
    correlation: float
    p_value: float
    mape: float  # Mean Absolute Percentage Error
    gain: float  # Linear formula: reference = gain * extracted + offset
    offset: float
    r_squared: float
    confidence_score: float  # Composite score for ranking
    extracted_values: List[float] = None  # Raw extracted values from payloads
    predicted_values: List[float] = None  # Predicted values using the formula

    def to_dict(self, include_values: bool = True) -> dict:
        result = {
            'bit_offset': self.bit_offset,
            'bit_length': self.bit_length,
            'endianness': self.endianness,
            'signed': self.signed,
            'correlation': round(self.correlation, 6),
            'p_value': round(self.p_value, 8),
            'mape': round(self.mape, 4),
            'gain': round(self.gain, 6),
            'offset': round(self.offset, 6),
            'r_squared': round(self.r_squared, 6),
            'confidence_score': round(self.confidence_score, 4),
            'formula': f"value = {self.gain:.4f} * raw + {self.offset:.4f}"
        }
        if include_values and self.extracted_values is not None:
            result['extracted_values'] = [round(v, 4) for v in self.extracted_values]
        if include_values and self.predicted_values is not None:
            result['predicted_values'] = [round(v, 4) for v in self.predicted_values]
        return result


class PayloadDecoder:
    """
    Decoder for finding bit group locations in binary payloads.
    """

    BIT_LENGTHS = [4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24]
    ENDIANNESS_OPTIONS = ['big', 'little']
    SIGNEDNESS_OPTIONS = [False, True]  # unsigned, signed

    def __init__(self,
                 correlation_threshold: float = 0.8,
                 p_value_threshold: float = 0.05,
                 mape_threshold: float = 5.0,
                 min_variance: float = 1e-10):
        """
        Initialize the decoder with configurable thresholds.

        Args:
            correlation_threshold: Minimum |r| to consider a candidate
            p_value_threshold: Maximum p-value for statistical significance
            mape_threshold: Maximum Mean Absolute Percentage Error (%)
            min_variance: Minimum variance to avoid constant value issues
        """
        self.correlation_threshold = correlation_threshold
        self.p_value_threshold = p_value_threshold
        self.mape_threshold = mape_threshold
        self.min_variance = min_variance

    def hex_to_bits(self, hex_string: str) -> str:
        """Convert hex string to binary string."""
        # Remove any spaces or common prefixes
        hex_clean = hex_string.replace(' ', '').replace('0x', '').replace('0X', '')
        # Convert to binary, padding each hex digit to 4 bits
        return ''.join(format(int(c, 16), '04b') for c in hex_clean)

    def bytes_to_bits(self, data: bytes) -> str:
        """Convert bytes to binary string."""
        return ''.join(format(byte, '08b') for byte in data)

    def extract_bits(self, bits: str, offset: int, length: int) -> str:
        """Extract a substring of bits from the given offset."""
        if offset + length > len(bits):
            return None
        return bits[offset:offset + length]

    def bits_to_int(self, bits: str, endianness: str, signed: bool) -> int:
        """
        Convert a bit string to an integer.

        For endianness:
        - 'big': MSB first (leftmost bit is most significant)
        - 'little': LSB first (rightmost bit is most significant when read as bytes)

        For bit groups that span multiple bytes, we handle byte-level endianness.
        """
        if not bits:
            return None

        bit_length = len(bits)

        # For non-byte-aligned lengths, we interpret at bit level
        if bit_length % 8 != 0:
            # Pad to byte boundary
            if endianness == 'big':
                padded = bits.zfill((bit_length + 7) // 8 * 8)
            else:
                padded = bits + '0' * ((8 - bit_length % 8) % 8)
            value = int(padded, 2)
        else:
            # Byte-aligned: handle byte-level endianness
            num_bytes = bit_length // 8
            bytes_list = [int(bits[i*8:(i+1)*8], 2) for i in range(num_bytes)]

            if endianness == 'little':
                bytes_list = bytes_list[::-1]

            value = 0
            for b in bytes_list:
                value = (value << 8) | b

        # Handle signed interpretation
        if signed:
            max_val = 1 << bit_length
            if value >= (max_val >> 1):
                value -= max_val

        return value

    def extract_series(self,
                       payloads: List[str],
                       bit_offset: int,
                       bit_length: int,
                       endianness: str,
                       signed: bool) -> Optional[np.ndarray]:
        """
        Extract a series of integer values from multiple payloads.

        Args:
            payloads: List of binary strings (one per trial)
            bit_offset: Starting bit position
            bit_length: Number of bits to extract
            endianness: 'big' or 'little'
            signed: Whether to interpret as signed integer

        Returns:
            Numpy array of extracted values, or None if extraction fails
        """
        values = []
        for payload in payloads:
            bits = self.extract_bits(payload, bit_offset, bit_length)
            if bits is None:
                return None
            value = self.bits_to_int(bits, endianness, signed)
            if value is None:
                return None
            values.append(value)

        return np.array(values, dtype=np.float64)

    def calculate_mape(self, actual: np.ndarray, predicted: np.ndarray) -> float:
        """
        Calculate Mean Absolute Percentage Error.

        Handles zero values by using a small epsilon or relative measure.
        """
        # Avoid division by zero
        mask = np.abs(actual) > 1e-10
        if not np.any(mask):
            # All values near zero, use absolute error instead
            return np.mean(np.abs(actual - predicted)) * 100

        # Calculate MAPE only for non-zero actuals
        mape = np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100
        return mape

    def calculate_confidence_score(self,
                                   correlation: float,
                                   p_value: float,
                                   mape: float,
                                   r_squared: float) -> float:
        """
        Calculate a composite confidence score for ranking candidates.

        Score combines:
        - Absolute correlation (higher is better)
        - P-value (lower is better)
        - MAPE (lower is better)
        - R-squared (higher is better)
        """
        # Normalize components to [0, 1]
        corr_score = abs(correlation)
        pval_score = 1.0 - min(p_value, 1.0)
        mape_score = max(0, 1.0 - mape / 10.0)  # 10% MAPE -> score 0

        # Weighted combination
        score = (
            0.4 * corr_score +
            0.2 * pval_score +
            0.2 * mape_score +
            0.2 * r_squared
        )

        return score

    def find_candidates(self,
                        reference_values: List[float],
                        payloads: List[str],
                        payload_format: str = 'hex') -> List[DecodingCandidate]:
        """
        Find all candidate bit group locations that match the reference values.

        Args:
            reference_values: List of known physical values (one per trial)
            payloads: List of data payloads (one per trial)
            payload_format: 'hex' or 'binary'

        Returns:
            List of DecodingCandidate objects, sorted by confidence score
        """
        if len(reference_values) != len(payloads):
            raise ValueError("Number of reference values must match number of payloads")

        n_trials = len(reference_values)
        if n_trials < 3:
            raise ValueError("At least 3 trials required for statistical analysis")

        # Convert reference values to numpy array
        ref_array = np.array(reference_values, dtype=np.float64)

        # Check for variance in reference values
        if np.var(ref_array) < self.min_variance:
            raise ValueError("Reference values have insufficient variance for correlation analysis")

        # Convert payloads to binary strings
        if payload_format == 'hex':
            binary_payloads = [self.hex_to_bits(p) for p in payloads]
        else:
            binary_payloads = payloads

        # Verify all payloads have same length
        payload_lengths = set(len(p) for p in binary_payloads)
        if len(payload_lengths) > 1:
            raise ValueError(f"Payloads have inconsistent lengths: {payload_lengths}")

        payload_length = len(binary_payloads[0])

        candidates = []

        # Sliding window through all bit positions
        for bit_length in self.BIT_LENGTHS:
            max_offset = payload_length - bit_length
            if max_offset < 0:
                continue

            for bit_offset in range(max_offset + 1):
                for endianness in self.ENDIANNESS_OPTIONS:
                    for signed in self.SIGNEDNESS_OPTIONS:
                        # Extract series for this configuration
                        extracted = self.extract_series(
                            binary_payloads,
                            bit_offset,
                            bit_length,
                            endianness,
                            signed
                        )

                        if extracted is None:
                            continue

                        # Check for variance in extracted values
                        if np.var(extracted) < self.min_variance:
                            continue

                        # Calculate Pearson correlation
                        try:
                            correlation, p_value = stats.pearsonr(ref_array, extracted)
                        except Exception:
                            continue

                        # Check if correlation meets threshold
                        if abs(correlation) < self.correlation_threshold:
                            continue

                        # Check statistical significance
                        if p_value > self.p_value_threshold:
                            continue

                        # Fit linear regression: reference = gain * extracted + offset
                        try:
                            slope, intercept, r_value, _, _ = stats.linregress(extracted, ref_array)
                        except Exception:
                            continue

                        r_squared = r_value ** 2

                        # Calculate predicted values and MAPE
                        predicted = slope * extracted + intercept
                        mape = self.calculate_mape(ref_array, predicted)

                        # Check MAPE threshold
                        if mape > self.mape_threshold:
                            continue

                        # Calculate confidence score
                        confidence = self.calculate_confidence_score(
                            correlation, p_value, mape, r_squared
                        )

                        # Create candidate
                        candidate = DecodingCandidate(
                            bit_offset=bit_offset,
                            bit_length=bit_length,
                            endianness=endianness,
                            signed=signed,
                            correlation=correlation,
                            p_value=p_value,
                            mape=mape,
                            gain=slope,
                            offset=intercept,
                            r_squared=r_squared,
                            confidence_score=confidence,
                            extracted_values=extracted.tolist(),
                            predicted_values=predicted.tolist()
                        )

                        candidates.append(candidate)

        # Sort by confidence score (descending)
        candidates.sort(key=lambda c: c.confidence_score, reverse=True)

        return candidates

    def decode(self,
               reference_values: List[float],
               payloads: List[str],
               payload_format: str = 'hex',
               top_n: int = 10) -> dict:
        """
        Main decoding interface.

        Args:
            reference_values: List of known physical values
            payloads: List of data payloads
            payload_format: 'hex' or 'binary'
            top_n: Maximum number of candidates to return

        Returns:
            Dictionary with analysis results
        """
        try:
            candidates = self.find_candidates(reference_values, payloads, payload_format)

            # Convert payloads to binary for visualization
            if payload_format == 'hex':
                binary_payloads = [self.hex_to_bits(p) for p in payloads]
            else:
                binary_payloads = payloads

            return {
                'success': True,
                'n_trials': len(reference_values),
                'payload_length_bits': len(binary_payloads[0]),
                'n_candidates': len(candidates),
                'reference_values': [round(v, 4) for v in reference_values],
                'candidates': [c.to_dict() for c in candidates[:top_n]],
                'thresholds': {
                    'correlation': self.correlation_threshold,
                    'p_value': self.p_value_threshold,
                    'mape': self.mape_threshold
                }
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }


def generate_test_payload(bit_offset: int,
                          bit_length: int,
                          value: int,
                          payload_length_bits: int = 64,
                          endianness: str = 'big') -> str:
    """
    Generate a test payload with a known value at a specific bit position.
    Useful for testing and demonstration.

    Returns hex string.
    """
    # Create random bits for the payload
    import random
    bits = [random.choice('01') for _ in range(payload_length_bits)]

    # Convert value to binary string of specified length
    if value < 0:
        # Two's complement for negative values
        value = (1 << bit_length) + value

    value_bits = format(value, f'0{bit_length}b')

    # Handle endianness for byte-aligned values
    if bit_length % 8 == 0 and endianness == 'little':
        # Reverse bytes
        num_bytes = bit_length // 8
        byte_list = [value_bits[i*8:(i+1)*8] for i in range(num_bytes)]
        value_bits = ''.join(reversed(byte_list))

    # Insert value at specified offset
    for i, bit in enumerate(value_bits):
        bits[bit_offset + i] = bit

    # Convert to hex
    bit_string = ''.join(bits)
    hex_string = ''
    for i in range(0, len(bit_string), 4):
        nibble = bit_string[i:i+4]
        hex_string += format(int(nibble, 2), 'X')

    return hex_string


if __name__ == '__main__':
    # Simple test
    import random

    # Generate test data: temperature sensor at bit offset 16, 12 bits
    # Formula: raw = (temp - 20) * 10  => temp = raw * 0.1 + 20

    reference_temps = [random.uniform(20, 80) for _ in range(10)]
    payloads = []

    for temp in reference_temps:
        raw_value = int((temp - 20) * 10)
        payload = generate_test_payload(
            bit_offset=16,
            bit_length=12,
            value=raw_value,
            payload_length_bits=64,
            endianness='big'
        )
        payloads.append(payload)

    # Test decoder
    decoder = PayloadDecoder()
    result = decoder.decode(reference_temps, payloads, payload_format='hex')

    if result['success']:
        print(f"Found {result['n_candidates']} candidates")
        for i, candidate in enumerate(result['candidates'][:3]):
            print(f"\n{i+1}. Offset={candidate['bit_offset']}, Length={candidate['bit_length']}")
            print(f"   Endian={candidate['endianness']}, Signed={candidate['signed']}")
            print(f"   Correlation={candidate['correlation']:.4f}, MAPE={candidate['mape']:.2f}%")
            print(f"   Formula: {candidate['formula']}")
    else:
        print(f"Error: {result['error']}")
