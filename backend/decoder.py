"""
Communication Decoder - Core Algorithm

This module implements the bit-group detection algorithm for identifying
where specific measurements are encoded within binary data payloads.

Algorithm:
1. Sliding window across all bit positions
2. Extract values using bit lengths from 4 to 24 (step 2)
3. Try all combinations of endianness and signedness
4. Calculate Pearson correlation with reference values
5. Validate candidates with linear regression and an error check
6. Rank candidates by confidence and merge layouts that decode identically
"""

import numpy as np
from dataclasses import dataclass
from typing import List, Optional

from bitfield import (
    BIT_LENGTHS, ENDIANNESS_OPTIONS, SIGNEDNESS_OPTIONS,
    Payload, PayloadArray, linear_fit, correlation_p_value, calculate_error_pct,
    calculate_confidence_score, rank_candidates,
)


@dataclass
class DecodingCandidate:
    """Represents a potential bit group location match."""
    bit_offset: int
    bit_length: int
    endianness: str  # 'big' or 'little'
    signed: bool
    correlation: float
    p_value: float
    error_pct: float  # Mean absolute error as % of the reference range
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
            'error_pct': round(self.error_pct, 4),
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

    def __init__(self,
                 correlation_threshold: float = 0.8,
                 p_value_threshold: float = 0.05,
                 error_threshold: float = 5.0,
                 min_variance: float = 1e-10):
        """
        Initialize the decoder with configurable thresholds.

        Args:
            correlation_threshold: Minimum |r| to consider a candidate
            p_value_threshold: Maximum p-value for statistical significance
            error_threshold: Maximum mean absolute error, as % of the reference range
            min_variance: Minimum variance to avoid constant value issues
        """
        self.correlation_threshold = correlation_threshold
        self.p_value_threshold = p_value_threshold
        self.error_threshold = error_threshold
        self.min_variance = min_variance

    def parse_payloads(self, payloads: List[str], payload_format: str) -> List[Payload]:
        """Parse payload strings ('hex' or 'binary') into Payload objects."""
        if payload_format == 'hex':
            return [Payload.from_hex(p) for p in payloads]
        return [Payload.from_bits(p) for p in payloads]

    def extract_series(self,
                       payloads: PayloadArray,
                       bit_offset: int,
                       bit_length: int,
                       endianness: str,
                       signed: bool) -> Optional[np.ndarray]:
        """
        Extract a series of integer values from multiple payloads.

        Returns:
            Numpy array of extracted values, or None if extraction fails
        """
        values = payloads.extract(bit_offset, bit_length, endianness, signed)
        if np.isnan(values).any():
            return None
        return values

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

        parsed = self.parse_payloads(payloads, payload_format)

        # Verify all payloads have same length
        payload_lengths = set(p.n_bits for p in parsed)
        if len(payload_lengths) > 1:
            raise ValueError(f"Payloads have inconsistent lengths: {payload_lengths}")

        payload_length = parsed[0].n_bits
        payload_array = PayloadArray(parsed)

        candidates = []

        # Sliding window through all bit positions
        for bit_length in BIT_LENGTHS:
            max_offset = payload_length - bit_length
            if max_offset < 0:
                continue

            for bit_offset in range(max_offset + 1):
                for endianness in ENDIANNESS_OPTIONS:
                    for signed in SIGNEDNESS_OPTIONS:
                        extracted = self.extract_series(
                            payload_array, bit_offset, bit_length, endianness, signed
                        )

                        if extracted is None:
                            continue

                        # Check for variance in extracted values
                        if np.var(extracted) < self.min_variance:
                            continue

                        # Fit linear regression: reference = gain * extracted + offset
                        slope, intercept, correlation = linear_fit(extracted, ref_array)
                        if abs(correlation) < self.correlation_threshold:
                            continue

                        # Check statistical significance
                        p_value = correlation_p_value(correlation, n_trials)
                        if p_value > self.p_value_threshold:
                            continue

                        r_squared = correlation ** 2

                        predicted = slope * extracted + intercept
                        error_pct = calculate_error_pct(ref_array, predicted)

                        if error_pct > self.error_threshold:
                            continue

                        candidates.append(DecodingCandidate(
                            bit_offset=bit_offset,
                            bit_length=bit_length,
                            endianness=endianness,
                            signed=signed,
                            correlation=float(correlation),
                            p_value=float(p_value),
                            error_pct=error_pct,
                            gain=float(slope),
                            offset=float(intercept),
                            r_squared=float(r_squared),
                            confidence_score=calculate_confidence_score(r_squared, error_pct),
                            extracted_values=extracted.tolist(),
                            predicted_values=predicted.tolist()
                        ))

        return rank_candidates(candidates, ref_array)

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

            return {
                'success': True,
                'n_trials': len(reference_values),
                'payload_length_bits': self.parse_payloads(payloads[:1], payload_format)[0].n_bits,
                'n_candidates': len(candidates),
                'reference_values': [round(v, 4) for v in reference_values],
                'candidates': [c.to_dict() for c in candidates[:top_n]],
                'thresholds': {
                    'correlation': self.correlation_threshold,
                    'p_value': self.p_value_threshold,
                    'error_pct': self.error_threshold
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
            print(f"   Correlation={candidate['correlation']:.4f}, Error={candidate['error_pct']:.2f}%")
            print(f"   Formula: {candidate['formula']}")
    else:
        print(f"Error: {result['error']}")
