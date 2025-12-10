"""
Extended Communication Decoder - Capture Window Support

This module extends the decoder to handle realistic scenarios where
multiple messages are captured in a time window for each reference value.

Algorithm:
1. Group messages by message_id across all trials
2. For each message group, try all bit location combinations
3. Use iterative best-match to find which message instance per trial
   corresponds to the reference value
4. Calculate correlation and rank candidates
"""

import numpy as np
from scipy import stats
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import defaultdict


@dataclass
class CapturedMessage:
    """A single captured message."""
    timestamp: float
    message_id: str
    payload: str  # hex string


@dataclass
class CaptureWindow:
    """A capture window containing multiple messages for one reference value."""
    reference_value: float
    messages: List[CapturedMessage]


@dataclass
class WindowDecodingCandidate:
    """Represents a potential match from window-based decoding."""
    message_id: str
    bit_offset: int
    bit_length: int
    endianness: str
    signed: bool
    correlation: float
    p_value: float
    mape: float
    gain: float
    offset: float
    r_squared: float
    confidence_score: float
    # Which message index was selected per trial
    selected_indices: List[int] = field(default_factory=list)
    selected_timestamps: List[float] = field(default_factory=list)
    extracted_values: List[float] = field(default_factory=list)
    predicted_values: List[float] = field(default_factory=list)

    def to_dict(self, include_values: bool = True) -> dict:
        result = {
            'message_id': self.message_id,
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
        if include_values:
            result['selected_indices'] = [int(i) for i in self.selected_indices]
            result['selected_timestamps'] = [float(round(t, 4)) for t in self.selected_timestamps]
            result['extracted_values'] = [float(round(v, 4)) for v in self.extracted_values]
            result['predicted_values'] = [float(round(v, 4)) for v in self.predicted_values]
        return result


class WindowPayloadDecoder:
    """
    Decoder for finding bit group locations when multiple messages
    are captured per reference value.
    """

    BIT_LENGTHS = [4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24]
    ENDIANNESS_OPTIONS = ['big', 'little']
    SIGNEDNESS_OPTIONS = [False, True]

    def __init__(self,
                 correlation_threshold: float = 0.8,
                 p_value_threshold: float = 0.05,
                 mape_threshold: float = 5.0,
                 min_variance: float = 1e-10,
                 min_trial_coverage: float = 0.8,
                 max_iterations: int = 10):
        """
        Initialize the window decoder.

        Args:
            correlation_threshold: Minimum |r| to consider a candidate
            p_value_threshold: Maximum p-value for statistical significance
            mape_threshold: Maximum Mean Absolute Percentage Error (%)
            min_variance: Minimum variance to avoid constant value issues
            min_trial_coverage: Minimum fraction of trials that must have the message_id
            max_iterations: Maximum iterations for best-match refinement
        """
        self.correlation_threshold = correlation_threshold
        self.p_value_threshold = p_value_threshold
        self.mape_threshold = mape_threshold
        self.min_variance = min_variance
        self.min_trial_coverage = min_trial_coverage
        self.max_iterations = max_iterations

    def hex_to_bits(self, hex_string: str) -> str:
        """Convert hex string to binary string."""
        hex_clean = hex_string.replace(' ', '').replace('0x', '').replace('0X', '')
        return ''.join(format(int(c, 16), '04b') for c in hex_clean)

    def extract_bits(self, bits: str, offset: int, length: int) -> Optional[str]:
        """Extract a substring of bits from the given offset."""
        if offset + length > len(bits):
            return None
        return bits[offset:offset + length]

    def bits_to_int(self, bits: str, endianness: str, signed: bool) -> Optional[int]:
        """Convert a bit string to an integer."""
        if not bits:
            return None

        bit_length = len(bits)

        if bit_length % 8 != 0:
            if endianness == 'big':
                padded = bits.zfill((bit_length + 7) // 8 * 8)
            else:
                padded = bits + '0' * ((8 - bit_length % 8) % 8)
            value = int(padded, 2)
        else:
            num_bytes = bit_length // 8
            bytes_list = [int(bits[i*8:(i+1)*8], 2) for i in range(num_bytes)]

            if endianness == 'little':
                bytes_list = bytes_list[::-1]

            value = 0
            for b in bytes_list:
                value = (value << 8) | b

        if signed:
            max_val = 1 << bit_length
            if value >= (max_val >> 1):
                value -= max_val

        return value

    def extract_value(self, payload_hex: str, bit_offset: int, bit_length: int,
                      endianness: str, signed: bool) -> Optional[float]:
        """Extract a value from a hex payload."""
        bits = self.hex_to_bits(payload_hex)
        bit_str = self.extract_bits(bits, bit_offset, bit_length)
        if bit_str is None:
            return None
        value = self.bits_to_int(bit_str, endianness, signed)
        return float(value) if value is not None else None

    def group_messages_by_id(self, windows: List[CaptureWindow]) -> Dict[str, List[List[CapturedMessage]]]:
        """
        Group messages by message_id across all capture windows.

        Returns:
            Dict mapping message_id to list of message lists (one per trial)
        """
        grouped = defaultdict(lambda: [[] for _ in range(len(windows))])

        for trial_idx, window in enumerate(windows):
            for msg in window.messages:
                grouped[msg.message_id][trial_idx].append(msg)

        return dict(grouped)

    def calculate_mape(self, actual: np.ndarray, predicted: np.ndarray) -> float:
        """Calculate Mean Absolute Percentage Error."""
        mask = np.abs(actual) > 1e-10
        if not np.any(mask):
            return np.mean(np.abs(actual - predicted)) * 100
        mape = np.mean(np.abs((actual[mask] - predicted[mask]) / actual[mask])) * 100
        return mape

    def calculate_confidence_score(self, correlation: float, p_value: float,
                                   mape: float, r_squared: float) -> float:
        """Calculate composite confidence score."""
        corr_score = abs(correlation)
        pval_score = 1.0 - min(p_value, 1.0)
        mape_score = max(0, 1.0 - mape / 10.0)

        score = (
            0.4 * corr_score +
            0.2 * pval_score +
            0.2 * mape_score +
            0.2 * r_squared
        )
        return score

    def find_best_match_iterative(self,
                                  reference_values: np.ndarray,
                                  all_extracted: List[List[float]]) -> Tuple[List[int], np.ndarray]:
        """
        Find the best matching message index per trial using iterative refinement.

        Args:
            reference_values: Array of reference values (one per trial)
            all_extracted: List of lists - for each trial, all extracted values from messages

        Returns:
            Tuple of (selected_indices, selected_values)
        """
        n_trials = len(reference_values)

        # Initial selection: for each trial, pick the median extracted value
        selected_indices = []
        selected_values = []

        for trial_idx in range(n_trials):
            values = all_extracted[trial_idx]
            if not values:
                return None, None
            # Start with median
            median_val = np.median(values)
            best_idx = np.argmin([abs(v - median_val) for v in values])
            selected_indices.append(best_idx)
            selected_values.append(values[best_idx])

        selected_values = np.array(selected_values)

        # Iterative refinement
        for iteration in range(self.max_iterations):
            # Fit linear model with current selection
            if np.var(selected_values) < self.min_variance:
                break

            try:
                slope, intercept, _, _, _ = stats.linregress(selected_values, reference_values)
            except Exception:
                break

            # For each trial, find the value that best fits the model
            new_indices = []
            new_values = []
            changed = False

            for trial_idx in range(n_trials):
                values = all_extracted[trial_idx]
                ref = reference_values[trial_idx]

                # Find value that minimizes |ref - (slope * value + intercept)|
                # Equivalently, find value closest to (ref - intercept) / slope
                if abs(slope) > 1e-10:
                    target = (ref - intercept) / slope
                else:
                    target = ref

                best_idx = np.argmin([abs(v - target) for v in values])

                if best_idx != selected_indices[trial_idx]:
                    changed = True

                new_indices.append(best_idx)
                new_values.append(values[best_idx])

            selected_indices = new_indices
            selected_values = np.array(new_values)

            if not changed:
                break

        return selected_indices, selected_values

    def analyze_message_group(self,
                              message_id: str,
                              messages_per_trial: List[List[CapturedMessage]],
                              reference_values: np.ndarray,
                              bit_offset: int,
                              bit_length: int,
                              endianness: str,
                              signed: bool) -> Optional[WindowDecodingCandidate]:
        """
        Analyze a specific message group and bit location combination.

        Returns a candidate if it meets the thresholds, None otherwise.
        """
        n_trials = len(reference_values)

        # Extract all values for each trial
        all_extracted = []
        for trial_idx in range(n_trials):
            trial_messages = messages_per_trial[trial_idx]
            if not trial_messages:
                return None  # Message type missing in this trial

            values = []
            for msg in trial_messages:
                val = self.extract_value(msg.payload, bit_offset, bit_length, endianness, signed)
                if val is not None:
                    values.append(val)

            if not values:
                return None  # Could not extract from any message in this trial

            all_extracted.append(values)

        # Find best matching selection
        selected_indices, selected_values = self.find_best_match_iterative(
            reference_values, all_extracted
        )

        if selected_indices is None or selected_values is None:
            return None

        # Check variance
        if np.var(selected_values) < self.min_variance:
            return None

        # Calculate correlation
        try:
            correlation, p_value = stats.pearsonr(reference_values, selected_values)
        except Exception:
            return None

        if abs(correlation) < self.correlation_threshold:
            return None

        if p_value > self.p_value_threshold:
            return None

        # Fit linear regression
        try:
            slope, intercept, r_value, _, _ = stats.linregress(selected_values, reference_values)
        except Exception:
            return None

        r_squared = r_value ** 2

        # Calculate predicted values and MAPE
        predicted = slope * selected_values + intercept
        mape = self.calculate_mape(reference_values, predicted)

        if mape > self.mape_threshold:
            return None

        # Calculate confidence score
        confidence = self.calculate_confidence_score(correlation, p_value, mape, r_squared)

        # Get selected timestamps
        selected_timestamps = []
        for trial_idx, msg_idx in enumerate(selected_indices):
            selected_timestamps.append(messages_per_trial[trial_idx][msg_idx].timestamp)

        return WindowDecodingCandidate(
            message_id=message_id,
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
            selected_indices=selected_indices,
            selected_timestamps=selected_timestamps,
            extracted_values=selected_values.tolist(),
            predicted_values=predicted.tolist()
        )

    def find_candidates(self, windows: List[CaptureWindow]) -> List[WindowDecodingCandidate]:
        """
        Find all candidate bit group locations across all message types.

        Args:
            windows: List of CaptureWindow objects (one per trial)

        Returns:
            List of WindowDecodingCandidate objects, sorted by confidence
        """
        n_trials = len(windows)
        if n_trials < 3:
            raise ValueError("At least 3 trials required for statistical analysis")

        reference_values = np.array([w.reference_value for w in windows], dtype=np.float64)

        if np.var(reference_values) < self.min_variance:
            raise ValueError("Reference values have insufficient variance")

        # Group messages by ID
        grouped = self.group_messages_by_id(windows)

        candidates = []

        # Analyze each message group
        for message_id, messages_per_trial in grouped.items():
            # Check trial coverage
            trials_with_messages = sum(1 for msgs in messages_per_trial if msgs)
            if trials_with_messages / n_trials < self.min_trial_coverage:
                continue

            # Determine payload length from first available message
            payload_length_bits = None
            for msgs in messages_per_trial:
                if msgs:
                    payload_length_bits = len(self.hex_to_bits(msgs[0].payload))
                    break

            if payload_length_bits is None:
                continue

            # Try all bit location combinations
            for bit_length in self.BIT_LENGTHS:
                if bit_length > payload_length_bits:
                    continue

                max_offset = payload_length_bits - bit_length

                for bit_offset in range(max_offset + 1):
                    for endianness in self.ENDIANNESS_OPTIONS:
                        for signed in self.SIGNEDNESS_OPTIONS:
                            candidate = self.analyze_message_group(
                                message_id,
                                messages_per_trial,
                                reference_values,
                                bit_offset,
                                bit_length,
                                endianness,
                                signed
                            )

                            if candidate is not None:
                                candidates.append(candidate)

        # Sort by confidence score
        candidates.sort(key=lambda c: c.confidence_score, reverse=True)

        return candidates

    def decode(self, windows: List[CaptureWindow], top_n: int = 10) -> dict:
        """
        Main decoding interface for window-based data.

        Args:
            windows: List of CaptureWindow objects
            top_n: Maximum number of candidates to return

        Returns:
            Dictionary with analysis results
        """
        try:
            candidates = self.find_candidates(windows)

            # Count unique message IDs
            all_message_ids = set()
            for window in windows:
                for msg in window.messages:
                    all_message_ids.add(msg.message_id)

            # Get reference values for the response
            reference_values = [w.reference_value for w in windows]

            return {
                'success': True,
                'n_trials': len(windows),
                'n_message_types': len(all_message_ids),
                'total_messages': sum(len(w.messages) for w in windows),
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


def parse_capture_data(data: dict) -> List[CaptureWindow]:
    """
    Parse input data into CaptureWindow objects.

    Expected format:
    {
        "trials": [
            {
                "reference_value": 25.5,
                "messages": [
                    {"timestamp": 0.001, "message_id": "0x123", "payload": "A1B2C3D4"},
                    ...
                ]
            },
            ...
        ]
    }
    """
    windows = []

    for trial in data.get('trials', []):
        messages = []
        for msg in trial.get('messages', []):
            messages.append(CapturedMessage(
                timestamp=msg.get('timestamp', 0.0),
                message_id=msg.get('message_id', ''),
                payload=msg.get('payload', '')
            ))

        windows.append(CaptureWindow(
            reference_value=trial.get('reference_value', 0.0),
            messages=messages
        ))

    return windows


if __name__ == '__main__':
    # Test with synthetic data
    import random

    random.seed(42)

    # Simulate: Temperature sensor at message ID 0x1A3, bit offset 8, 12 bits
    # Formula: temp = raw * 0.0625 (like DS18B20)

    n_trials = 10
    message_rate = 10  # Hz
    window_duration = 2  # seconds
    target_message_id = "0x1A3"
    target_bit_offset = 8
    target_bit_length = 12

    windows = []

    for trial in range(n_trials):
        # Generate reference temperature
        ref_temp = random.uniform(20, 40)

        messages = []
        current_time = 0.0

        # Generate messages at ~10Hz for 2 seconds
        while current_time < window_duration:
            # Random message ID (simulate mixed traffic)
            msg_ids = ["0x100", "0x1A3", "0x200", "0x1A3", "0x150"]
            msg_id = random.choice(msg_ids)

            # Generate payload
            if msg_id == target_message_id:
                # This is our target - encode the temperature
                raw_value = int(ref_temp / 0.0625)
                # Create 64-bit payload with value at correct position
                payload_bits = ['0'] * 64
                value_bits = format(raw_value, '012b')
                for i, bit in enumerate(value_bits):
                    payload_bits[target_bit_offset + i] = bit
                # Add some noise to other bits
                for i in range(64):
                    if i < target_bit_offset or i >= target_bit_offset + target_bit_length:
                        payload_bits[i] = random.choice('01')
                payload_hex = ''.join(format(int(''.join(payload_bits[i:i+4]), 2), 'X')
                                     for i in range(0, 64, 4))
            else:
                # Random payload for other message types
                payload_hex = ''.join(random.choice('0123456789ABCDEF') for _ in range(16))

            messages.append(CapturedMessage(
                timestamp=current_time,
                message_id=msg_id,
                payload=payload_hex
            ))

            current_time += random.uniform(0.05, 0.15)  # ~10Hz with jitter

        windows.append(CaptureWindow(
            reference_value=ref_temp,
            messages=messages
        ))

    # Test decoder
    decoder = WindowPayloadDecoder()
    result = decoder.decode(windows)

    if result['success']:
        print(f"Analyzed {result['n_trials']} trials")
        print(f"Found {result['n_message_types']} message types")
        print(f"Total messages: {result['total_messages']}")
        print(f"Found {result['n_candidates']} candidates")
        print()

        for i, candidate in enumerate(result['candidates'][:3]):
            print(f"{i+1}. Message {candidate['message_id']}")
            print(f"   Offset={candidate['bit_offset']}, Length={candidate['bit_length']}")
            print(f"   Endian={candidate['endianness']}, Signed={candidate['signed']}")
            print(f"   Correlation={candidate['correlation']:.4f}, MAPE={candidate['mape']:.2f}%")
            print(f"   Formula: {candidate['formula']}")
            print()
    else:
        print(f"Error: {result['error']}")
