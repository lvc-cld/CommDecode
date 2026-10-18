"""
Regression tests on the bundled examples, TestData captures and random noise.
"""

import json
import os
import random

import pytest

from decoder import PayloadDecoder
from window_decoder import WindowPayloadDecoder, CaptureWindow, CapturedMessage, parse_capture_data

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLES = json.load(open(os.path.join(BACKEND_DIR, 'examples', 'examples.json')))
WINDOW_EXAMPLES = json.load(open(os.path.join(BACKEND_DIR, 'examples', 'window_examples.json')))
TEST_DATA_DIR = os.path.join(os.path.dirname(BACKEND_DIR), 'TestData')


def load_test_data(name):
    with open(os.path.join(TEST_DATA_DIR, name)) as f:
        return json.load(f)


def random_hex(rng, n_digits):
    return ''.join(rng.choice('0123456789ABCDEF') for _ in range(n_digits))


@pytest.mark.parametrize('example_id', sorted(EXAMPLES))
def test_simple_example_ranks_ground_truth_first(example_id):
    example = EXAMPLES[example_id]
    truth = example['ground_truth']
    result = PayloadDecoder().decode(example['reference_values'], example['payloads'])

    assert result['success'], result.get('error')
    best = result['candidates'][0]
    assert (best['bit_offset'], best['bit_length'], best['endianness'], best['signed']) == \
        (truth['bit_offset'], truth['bit_length'], truth['endianness'], truth['signed'])
    assert best['gain'] == pytest.approx(truth['gain'], rel=0.01)


@pytest.mark.parametrize('example_id', sorted(WINDOW_EXAMPLES))
def test_window_example_ranks_ground_truth_first(example_id):
    example = WINDOW_EXAMPLES[example_id]
    truth = example['ground_truth']
    result = WindowPayloadDecoder().decode(parse_capture_data(example), top_n=3)

    assert result['success'], result.get('error')
    best = result['candidates'][0]
    assert (best['message_id'], best['bit_offset'], best['bit_length'], best['endianness']) == \
        (truth['message_id'], truth['bit_offset'], truth['bit_length'], truth['endianness'])
    assert best['gain'] == pytest.approx(truth['gain'], rel=0.01)
    assert best['shuffle_p_value'] <= 0.05


@pytest.mark.parametrize('name,message_id,bit_offset,bit_length,endianness,gain,offset', [
    # WheelSpeed's own docs say start bit 24, but its data puts the field's
    # LSB at Intel bit 28 (raw 0xD45 stored as bytes 51 D4)
    ('WheelSpeed_Sample_Complex.json', '0x244', 28, 12, 'little', 0.05, -10.0),
    ('WheelSpeed_Converted.json', '0x244', 28, 12, 'little', 0.05, -10.0),
    ('RPM_Sample1.json', '0x210', 16, 16, 'big', 0.25, 0.0),
    ('VehicleSpeed_Sample1.json', '0x1B0', 0, 16, 'little', 0.01, 0.0),
])
def test_test_data_capture_decodes(name, message_id, bit_offset, bit_length, endianness, gain, offset):
    result = WindowPayloadDecoder().decode(parse_capture_data(load_test_data(name)), top_n=1)

    assert result['success'], result.get('error')
    best = result['candidates'][0]
    assert (best['message_id'], best['bit_offset'], best['bit_length'], best['endianness']) == \
        (message_id, bit_offset, bit_length, endianness)
    assert best['gain'] == pytest.approx(gain, rel=1e-3)
    assert best['offset'] == pytest.approx(offset, abs=1e-2)


@pytest.mark.parametrize('name', ['BatteryCurrent_Sample1.json', 'BatteryCurrent_Sample2.json'])
def test_inconsistent_capture_reports_no_match(name):
    # No single bit location encodes the reference value in every trial of
    # these files, so the decoder must not report a match.
    result = WindowPayloadDecoder().decode(parse_capture_data(load_test_data(name)))

    assert result['success'], result.get('error')
    assert result['n_candidates'] == 0


@pytest.mark.parametrize('seed', [1, 2, 3])
def test_simple_mode_finds_nothing_in_noise(seed):
    rng = random.Random(seed)
    references = [rng.uniform(20, 80) for _ in range(10)]
    payloads = [random_hex(rng, 16) for _ in references]

    assert PayloadDecoder().decode(references, payloads)['n_candidates'] == 0


@pytest.mark.parametrize('seed', [1, 2, 3])
def test_window_mode_finds_nothing_in_noise(seed):
    # Before the shuffle test, every such run returned ~2000 candidates with |r| ~ 1
    rng = random.Random(seed)
    windows = [
        CaptureWindow(rng.uniform(20, 80),
                      [CapturedMessage(i * 0.01, '0x1', random_hex(rng, 16)) for i in range(20)])
        for _ in range(10)
    ]
    result = WindowPayloadDecoder().decode(windows)

    assert result['success'], result.get('error')
    assert result['n_candidates'] == 0
    assert result['n_rejected_by_shuffle_test'] > 0


def test_signal_crossing_zero_is_found():
    # A percentage error per sample (MAPE) explodes near zero; the range-based error does not
    rng = random.Random(7)
    references, payloads = [], []
    for _ in range(15):
        raw = rng.randint(-500, 500)
        references.append(raw * 0.1)
        payloads.append(random_hex(rng, 2) + format(raw & 0xFFFF, '04X') + random_hex(rng, 2))

    best = PayloadDecoder().decode(references, payloads)['candidates'][0]
    assert (best['bit_offset'], best['bit_length'], best['signed']) == (8, 16, True)


def test_selected_indices_point_at_matching_messages():
    rng = random.Random(3)
    windows = []
    for _ in range(8):
        raw = rng.randint(100, 4000)
        messages = [CapturedMessage(0.0, '0x7', 'F')]  # too short for any field wider than 4 bits
        messages += [CapturedMessage(0.01 * i, '0x7', random_hex(rng, 8)) for i in range(1, 4)]
        target = rng.randrange(1, 4)
        messages[target] = CapturedMessage(0.5, '0x7', format(raw, '04X') + random_hex(rng, 4))
        windows.append(CaptureWindow(raw * 0.5, messages))

    best = WindowPayloadDecoder().decode(windows, top_n=1)['candidates'][0]
    assert all(t == 0.5 for t in best['selected_timestamps'])
