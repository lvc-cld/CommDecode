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
5. Keep only candidates that pass a shuffle test, because the per-trial
   selection in step 3 can make random bits fit any reference series
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

from bitfield import (
    BIT_LENGTHS, ENDIANNESS_OPTIONS, SIGNEDNESS_OPTIONS,
    Payload, PayloadArray, linear_fit, correlation_p_value, calculate_error_pct,
    calculate_confidence_score, rank_candidates,
)


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
    error_pct: float
    gain: float
    offset: float
    r_squared: float
    confidence_score: float
    # Which message index was selected per trial
    selected_indices: List[int] = field(default_factory=list)
    selected_timestamps: List[float] = field(default_factory=list)
    extracted_values: List[float] = field(default_factory=list)
    predicted_values: List[float] = field(default_factory=list)
    # Fraction of shuffled-reference runs that fit at least as well (set by the shuffle test)
    shuffle_p_value: Optional[float] = None

    def to_dict(self, include_values: bool = True) -> dict:
        result = {
            'message_id': self.message_id,
            'bit_offset': self.bit_offset,
            'bit_length': self.bit_length,
            'endianness': self.endianness,
            'signed': self.signed,
            'correlation': round(self.correlation, 6),
            'p_value': round(self.p_value, 8),
            'shuffle_p_value': None if self.shuffle_p_value is None else round(self.shuffle_p_value, 4),
            'error_pct': round(self.error_pct, 4),
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


def row_medians(values: np.ndarray) -> np.ndarray:
    """Median of each row, ignoring NaN (faster than np.nanmedian for small rows)."""
    ordered = np.sort(values, axis=1)  # NaN sorts last
    counts = np.count_nonzero(~np.isnan(values), axis=1)
    rows = np.arange(len(values))
    return (ordered[rows, (counts - 1) // 2] + ordered[rows, counts // 2]) / 2


class MessageGroup:
    """
    All messages with one message_id, laid out as a (trials x messages)
    matrix so a field can be extracted from every message in one step.
    """

    def __init__(self, messages_per_trial: List[List[CapturedMessage]]):
        self.messages = messages_per_trial
        n_trials = len(messages_per_trial)
        self.width = max(1, max(len(msgs) for msgs in messages_per_trial))

        flat = [Payload.from_hex(m.payload) for msgs in messages_per_trial for m in msgs]
        self.max_bits = max((p.n_bits for p in flat), default=0)
        self.payloads = PayloadArray(flat) if flat else None

        # Position of each flat payload in the matrix
        self.rows = np.array([t for t, msgs in enumerate(messages_per_trial) for _ in msgs], dtype=np.int64)
        self.cols = np.array([i for msgs in messages_per_trial for i in range(len(msgs))], dtype=np.int64)
        self.shape = (n_trials, self.width)

    def extract(self, bit_offset: int, bit_length: int, endianness: str, signed: bool) -> np.ndarray:
        """Matrix of extracted values, NaN where there is no message or no fit."""
        matrix = np.full(self.shape, np.nan)
        if self.payloads is not None:
            matrix[self.rows, self.cols] = self.payloads.extract(bit_offset, bit_length, endianness, signed)
        return matrix


class WindowPayloadDecoder:
    """
    Decoder for finding bit group locations when multiple messages
    are captured per reference value.

    Because the decoder chooses one message per trial, it can make random
    bits fit almost any reference series. Every reported candidate must
    therefore pass a shuffle test: the same fit, run with the reference
    values shuffled across trials, must be far worse.
    """

    def __init__(self,
                 correlation_threshold: float = 0.8,
                 p_value_threshold: float = 0.05,
                 error_threshold: float = 5.0,
                 min_variance: float = 1e-10,
                 min_trial_coverage: float = 0.8,
                 max_iterations: int = 10,
                 max_shuffle_checks: int = 200,
                 shuffle_margin: float = 100.0,
                 random_seed: int = 0):
        """
        Initialize the window decoder.

        Args:
            correlation_threshold: Minimum |r| to consider a candidate
            p_value_threshold: Maximum p-value, used for Pearson and for the shuffle test
            error_threshold: Maximum mean absolute error, as % of the reference range
            min_variance: Minimum variance to avoid constant value issues
            min_trial_coverage: Minimum fraction of trials that must have the message_id
            max_iterations: Maximum iterations for best-match refinement
            max_shuffle_checks: Maximum number of candidates sent to the shuffle test
            shuffle_margin: A shuffle fits "as well" when its unexplained variance is
                less than this many times that of the real order
            random_seed: Seed for the shuffles, so results are repeatable
        """
        self.correlation_threshold = correlation_threshold
        self.p_value_threshold = p_value_threshold
        self.error_threshold = error_threshold
        self.min_variance = min_variance
        self.min_trial_coverage = min_trial_coverage
        self.max_iterations = max_iterations
        self.max_shuffle_checks = max_shuffle_checks
        self.shuffle_margin = shuffle_margin
        self.random_seed = random_seed

    def group_messages_by_id(self, windows: List[CaptureWindow]) -> Dict[str, 'MessageGroup']:
        """
        Group messages by message_id across all capture windows, parsing
        each payload once.

        Returns:
            Dict mapping message_id to a MessageGroup
        """
        grouped = defaultdict(lambda: [[] for _ in range(len(windows))])

        for trial_idx, window in enumerate(windows):
            for msg in window.messages:
                grouped[msg.message_id][trial_idx].append(msg)

        return {message_id: MessageGroup(per_trial) for message_id, per_trial in grouped.items()}

    def find_best_match_iterative(self,
                                  reference_values: np.ndarray,
                                  values: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Find the best matching message index per trial using iterative refinement.

        Args:
            reference_values: Array of reference values (one per trial)
            values: Matrix (trials x messages) of extracted values, NaN where
                there is no message or the field does not fit

        Returns:
            Tuple of (selected_indices, selected_values)
        """
        rows = np.arange(len(values))

        # Initial selection: for each trial, pick the value closest to its median
        medians = row_medians(values)
        selected_indices = np.nanargmin(np.abs(values - medians[:, None]), axis=1)
        selected_values = values[rows, selected_indices]

        # Iterative refinement
        for _ in range(self.max_iterations):
            if np.var(selected_values) < self.min_variance:
                break

            slope, intercept, _ = linear_fit(selected_values, reference_values)

            # For each trial, pick the value closest to (ref - intercept) / slope
            if abs(slope) > 1e-10:
                targets = (reference_values - intercept) / slope
            else:
                targets = reference_values

            new_indices = np.nanargmin(np.abs(values - targets[:, None]), axis=1)
            changed = not np.array_equal(new_indices, selected_indices)

            selected_indices = new_indices
            selected_values = values[rows, selected_indices]

            if not changed:
                break

        return selected_indices, selected_values

    def fit_r_squared(self, reference_values: np.ndarray, values: np.ndarray) -> float:
        """R² of the best-match fit for the given reference values."""
        _, selected = self.find_best_match_iterative(reference_values, values)
        if np.var(selected) < self.min_variance:
            return 0.0
        _, _, r = linear_fit(selected, reference_values)
        return r ** 2

    def shuffle_test(self, reference_values: np.ndarray, values: np.ndarray,
                     observed_r_squared: float, rng: np.random.Generator) -> float:
        """
        Test whether the fit depends on which reference value goes with which trial.

        A shuffle "fits as well" when its unexplained variance (1 - R²) is
        less than shuffle_margin times that of the real order. Random bits fit
        shuffled values almost as well as the real ones (often within 10x);
        a real signal fits them far worse.

        Returns the p-value (1 + n_as_good) / (1 + n_shuffles). It stops early
        once the candidate cannot reach p <= p_value_threshold.
        """
        n_shuffles = self.n_shuffles()
        limit = self.shuffle_margin * (1.0 - observed_r_squared)
        max_as_good = self.p_value_threshold * (n_shuffles + 1) - 1
        n_as_good = 0
        for _ in range(n_shuffles):
            shuffled = rng.permutation(reference_values)
            if 1.0 - self.fit_r_squared(shuffled, values) <= limit:
                n_as_good += 1
                if n_as_good > max_as_good:
                    break
        return (1 + n_as_good) / (1 + n_shuffles)

    def n_shuffles(self) -> int:
        """Smallest number of shuffles that can reach p <= p_value_threshold (at least 19)."""
        return max(19, int(np.ceil(1.0 / self.p_value_threshold)) - 1)

    def analyze_message_group(self,
                              message_id: str,
                              group: 'MessageGroup',
                              reference_values: np.ndarray,
                              bit_offset: int,
                              bit_length: int,
                              endianness: str,
                              signed: bool) -> Optional[Tuple[WindowDecodingCandidate, np.ndarray]]:
        """
        Analyze a specific message group and bit location combination.

        Returns (candidate, values matrix) if it meets the thresholds, None otherwise.
        """
        values = group.extract(bit_offset, bit_length, endianness, signed)

        # Every trial needs at least one message the field fits in
        if np.isnan(values).all(axis=1).any():
            return None

        selected, selected_values = self.find_best_match_iterative(reference_values, values)

        if np.var(selected_values) < self.min_variance:
            return None

        slope, intercept, correlation = linear_fit(selected_values, reference_values)
        if abs(correlation) < self.correlation_threshold:
            return None

        p_value = correlation_p_value(correlation, len(reference_values))
        if p_value > self.p_value_threshold:
            return None

        r_squared = correlation ** 2

        predicted = slope * selected_values + intercept
        error_pct = calculate_error_pct(reference_values, predicted)

        if error_pct > self.error_threshold:
            return None

        message_indices = [int(i) for i in selected]
        selected_timestamps = [group.messages[t][m].timestamp for t, m in enumerate(message_indices)]

        candidate = WindowDecodingCandidate(
            message_id=message_id,
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
            selected_indices=message_indices,
            selected_timestamps=selected_timestamps,
            extracted_values=selected_values.tolist(),
            predicted_values=predicted.tolist()
        )
        return candidate, values

    def find_candidates(self, windows: List[CaptureWindow], top_n: int = 10) -> dict:
        """
        Find candidate bit group locations across all message types.

        Args:
            windows: List of CaptureWindow objects (one per trial)
            top_n: Stop once this many candidates have passed the shuffle test

        Returns:
            Dict with 'accepted' (candidates that passed, best first),
            'n_screened' (candidates that passed the thresholds) and
            'n_rejected' (candidates that failed the shuffle test)
        """
        n_trials = len(windows)
        if n_trials < 3:
            raise ValueError("At least 3 trials required for statistical analysis")

        reference_values = np.array([w.reference_value for w in windows], dtype=np.float64)

        if np.var(reference_values) < self.min_variance:
            raise ValueError("Reference values have insufficient variance")

        grouped = self.group_messages_by_id(windows)

        screened = []
        values_by_candidate = {}

        for message_id, group in grouped.items():
            # Check trial coverage. Trials without the message cannot be
            # matched, so analyze_message_group rejects the group anyway.
            trials_with_messages = sum(1 for msgs in group.messages if msgs)
            if trials_with_messages / n_trials < self.min_trial_coverage:
                continue

            payload_length_bits = group.max_bits

            for bit_length in BIT_LENGTHS:
                if bit_length > payload_length_bits:
                    continue

                for bit_offset in range(payload_length_bits - bit_length + 1):
                    for endianness in ENDIANNESS_OPTIONS:
                        for signed in SIGNEDNESS_OPTIONS:
                            result = self.analyze_message_group(
                                message_id, group, reference_values,
                                bit_offset, bit_length, endianness, signed
                            )
                            if result is not None:
                                candidate, values = result
                                screened.append(candidate)
                                values_by_candidate[id(candidate)] = values

        ranked = rank_candidates(screened, reference_values, group_key=lambda c: (c.message_id,))

        # Shuffle test, best candidates first
        rng = np.random.default_rng(self.random_seed)
        accepted = []
        n_rejected = 0
        for candidate in ranked[:self.max_shuffle_checks]:
            candidate.shuffle_p_value = self.shuffle_test(
                reference_values, values_by_candidate[id(candidate)],
                candidate.r_squared, rng
            )
            if candidate.shuffle_p_value <= self.p_value_threshold:
                accepted.append(candidate)
                if len(accepted) >= top_n:
                    break
            else:
                n_rejected += 1

        return {'accepted': accepted, 'n_screened': len(ranked), 'n_rejected': n_rejected}

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
            found = self.find_candidates(windows, top_n=top_n)
            candidates = found['accepted']

            all_message_ids = set(msg.message_id for w in windows for msg in w.messages)
            reference_values = [w.reference_value for w in windows]

            return {
                'success': True,
                'n_trials': len(windows),
                'n_message_types': len(all_message_ids),
                'total_messages': sum(len(w.messages) for w in windows),
                # Candidates that passed the shuffle test (at most top_n)
                'n_candidates': len(candidates),
                'n_screened': found['n_screened'],
                'n_rejected_by_shuffle_test': found['n_rejected'],
                'reference_values': [round(v, 4) for v in reference_values],
                'candidates': [c.to_dict() for c in candidates],
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
                # 'id' is accepted as an alias (used by the TestData files)
                message_id=str(msg.get('message_id', msg.get('id', ''))),
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
            print(f"   Correlation={candidate['correlation']:.4f}, Error={candidate['error_pct']:.2f}%")
            print(f"   Formula: {candidate['formula']}")
            print()
    else:
        print(f"Error: {result['error']}")
