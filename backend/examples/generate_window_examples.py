"""
Generate realistic window-based example datasets for the Communication Decoder.

Creates examples with multiple messages per capture window, simulating
real-world protocol reverse engineering scenarios.
"""

import json
import random
import os

random.seed(42)


def generate_random_hex(length: int) -> str:
    """Generate random hex string of given length (in hex chars)."""
    return ''.join(random.choice('0123456789ABCDEF') for _ in range(length))


def int_to_bits(value: int, bit_length: int) -> str:
    """Convert integer to binary string."""
    if value < 0:
        value = (1 << bit_length) + value
    return format(value, f'0{bit_length}b')


def insert_value_in_payload(payload_hex: str, bit_offset: int, bit_length: int,
                            value: int, endianness: str = 'big') -> str:
    """Insert a value at specific bit position in a hex payload."""
    # Convert hex to bits
    bits = list(''.join(format(int(c, 16), '04b') for c in payload_hex))

    # Convert value to bits
    value_bits = int_to_bits(value, bit_length)

    # Handle endianness for byte-aligned values
    if bit_length % 8 == 0 and endianness == 'little':
        num_bytes = bit_length // 8
        byte_list = [value_bits[i*8:(i+1)*8] for i in range(num_bytes)]
        value_bits = ''.join(reversed(byte_list))

    # Insert value bits
    for i, bit in enumerate(value_bits):
        if bit_offset + i < len(bits):
            bits[bit_offset + i] = bit

    # Convert back to hex
    bit_string = ''.join(bits)
    hex_string = ''
    for i in range(0, len(bit_string), 4):
        nibble = bit_string[i:i+4]
        hex_string += format(int(nibble, 2), 'X')

    return hex_string


def generate_window_example(
    name: str,
    domain: str,
    description: str,
    unit: str,
    value_range: tuple,
    target_message_id: str,
    other_message_ids: list,
    bit_offset: int,
    bit_length: int,
    payload_length_hex: int,
    gain: float,
    offset: float,
    endianness: str = 'big',
    signed: bool = False,
    n_trials: int = 10,
    window_duration: float = 2.0,
    message_rate: float = 10.0
) -> dict:
    """Generate a complete window-based example dataset."""

    trials = []
    min_val, max_val = value_range

    for trial_idx in range(n_trials):
        # Generate reference value
        ref_value = random.uniform(min_val, max_val)

        # Calculate raw encoded value
        raw_value = int(round((ref_value - offset) / gain))

        # Clamp to valid range
        if signed:
            min_raw = -(1 << (bit_length - 1))
            max_raw = (1 << (bit_length - 1)) - 1
        else:
            min_raw = 0
            max_raw = (1 << bit_length) - 1
        raw_value = max(min_raw, min(max_raw, raw_value))

        # Generate messages for this window
        messages = []
        current_time = 0.0
        all_message_ids = [target_message_id] + other_message_ids

        while current_time < window_duration:
            # Pick a message ID (weighted to include target)
            if random.random() < 0.3:  # 30% chance of target message
                msg_id = target_message_id
            else:
                msg_id = random.choice(all_message_ids)

            # Generate payload
            if msg_id == target_message_id:
                # Insert the actual encoded value
                base_payload = generate_random_hex(payload_length_hex)
                payload = insert_value_in_payload(
                    base_payload, bit_offset, bit_length, raw_value, endianness
                )
            else:
                # Random payload for other message types
                payload = generate_random_hex(payload_length_hex)

            messages.append({
                'timestamp': round(current_time, 4),
                'message_id': msg_id,
                'payload': payload
            })

            # Advance time with jitter
            current_time += random.uniform(0.5 / message_rate, 1.5 / message_rate)

        # Recalculate actual reference value from raw (to account for rounding)
        actual_ref = gain * raw_value + offset

        trials.append({
            'reference_value': round(actual_ref, 4),
            'messages': messages
        })

    return {
        'name': name,
        'domain': domain,
        'description': description,
        'unit': unit,
        'trials': trials,
        'ground_truth': {
            'message_id': target_message_id,
            'bit_offset': bit_offset,
            'bit_length': bit_length,
            'endianness': endianness,
            'signed': signed,
            'gain': gain,
            'offset': offset,
            'formula': f"physical_value = {gain} * raw_value + {offset}"
        }
    }


def main():
    examples = {}

    # ==================== AUTOMOTIVE EXAMPLES ====================

    # 1. Engine RPM on CAN bus
    examples['window_automotive_rpm'] = generate_window_example(
        name='Engine RPM (CAN)',
        domain='automotive',
        description='Engine speed on CAN bus with mixed traffic. '
                    'Message ID 0x0C0 contains RPM at bits 8-23.',
        unit='RPM',
        value_range=(800, 7500),
        target_message_id='0x0C0',
        other_message_ids=['0x100', '0x1A0', '0x200', '0x2C0', '0x300'],
        bit_offset=8,
        bit_length=16,
        payload_length_hex=16,  # 8 bytes = 16 hex chars
        gain=0.25,
        offset=0,
        endianness='big',
        signed=False,
        n_trials=12,
        window_duration=3.0,
        message_rate=10.0
    )

    # 2. Coolant Temperature
    examples['window_automotive_coolant'] = generate_window_example(
        name='Coolant Temperature (CAN)',
        domain='automotive',
        description='Engine coolant temp on CAN bus. '
                    'Message ID 0x105 with temp at bits 16-23, offset -40.',
        unit='°C',
        value_range=(50, 110),
        target_message_id='0x105',
        other_message_ids=['0x0C0', '0x100', '0x1A0', '0x200', '0x300'],
        bit_offset=16,
        bit_length=8,
        payload_length_hex=16,
        gain=1.0,
        offset=-40,
        endianness='big',
        signed=False,
        n_trials=10,
        window_duration=2.5,
        message_rate=8.0
    )

    # 3. Vehicle Speed (little-endian)
    examples['window_automotive_speed'] = generate_window_example(
        name='Vehicle Speed (CAN)',
        domain='automotive',
        description='Vehicle speed on CAN bus. '
                    'Message ID 0x1B0, little-endian 16-bit at bits 0-15.',
        unit='km/h',
        value_range=(0, 200),
        target_message_id='0x1B0',
        other_message_ids=['0x0C0', '0x100', '0x105', '0x200', '0x2C0'],
        bit_offset=0,
        bit_length=16,
        payload_length_hex=16,
        gain=0.01,
        offset=0,
        endianness='little',
        signed=False,
        n_trials=14,
        window_duration=2.0,
        message_rate=10.0
    )

    # ==================== INDUSTRIAL EXAMPLES ====================

    # 4. Pressure Sensor (Modbus-like)
    examples['window_industrial_pressure'] = generate_window_example(
        name='Pressure Sensor (Modbus)',
        domain='industrial',
        description='Industrial pressure transmitter on Modbus-like protocol. '
                    'Slave address 0x10 with pressure at bits 0-11.',
        unit='bar',
        value_range=(0, 400),
        target_message_id='0x10',
        other_message_ids=['0x01', '0x02', '0x11', '0x12', '0x20'],
        bit_offset=0,
        bit_length=12,
        payload_length_hex=12,  # 6 bytes
        gain=0.1,
        offset=0,
        endianness='big',
        signed=False,
        n_trials=15,
        window_duration=5.0,
        message_rate=5.0
    )

    # 5. Flow Rate (signed, bidirectional)
    examples['window_industrial_flow'] = generate_window_example(
        name='Flow Rate (Industrial)',
        domain='industrial',
        description='Bidirectional flow meter. '
                    'Device ID 0x25 with signed 16-bit flow at bits 8-23.',
        unit='L/min',
        value_range=(50, 500),
        target_message_id='0x25',
        other_message_ids=['0x10', '0x11', '0x20', '0x30', '0x40'],
        bit_offset=8,
        bit_length=16,
        payload_length_hex=12,
        gain=0.1,
        offset=0,
        endianness='big',
        signed=False,
        n_trials=12,
        window_duration=4.0,
        message_rate=4.0
    )

    # 6. Tank Level
    examples['window_industrial_tank'] = generate_window_example(
        name='Tank Level (Industrial)',
        domain='industrial',
        description='Ultrasonic tank level sensor. '
                    'Device ID 0x30 with level percentage at bits 24-31.',
        unit='%',
        value_range=(5, 95),
        target_message_id='0x30',
        other_message_ids=['0x10', '0x20', '0x25', '0x35', '0x40'],
        bit_offset=24,
        bit_length=8,
        payload_length_hex=10,  # 5 bytes
        gain=0.5,
        offset=0,
        endianness='big',
        signed=False,
        n_trials=10,
        window_duration=3.0,
        message_rate=3.0
    )

    # ==================== IOT EXAMPLES ====================

    # 7. Temperature Sensor (signed, like DS18B20)
    examples['window_iot_temperature'] = generate_window_example(
        name='IoT Temperature Sensor',
        domain='iot',
        description='Wireless temperature sensor network. '
                    'Sensor ID 0xA1 with 12-bit signed temp at bits 4-15.',
        unit='°C',
        value_range=(-5, 45),
        target_message_id='0xA1',
        other_message_ids=['0xA0', '0xA2', '0xB1', '0xB2', '0xC1'],
        bit_offset=4,
        bit_length=12,
        payload_length_hex=8,  # 4 bytes
        gain=0.0625,
        offset=0,
        endianness='big',
        signed=True,
        n_trials=12,
        window_duration=5.0,
        message_rate=2.0
    )

    # 8. Humidity Sensor
    examples['window_iot_humidity'] = generate_window_example(
        name='IoT Humidity Sensor',
        domain='iot',
        description='Wireless humidity sensor. '
                    'Sensor ID 0xA2 with 8-bit humidity at bits 8-15.',
        unit='%RH',
        value_range=(20, 90),
        target_message_id='0xA2',
        other_message_ids=['0xA0', '0xA1', '0xB1', '0xB2', '0xC1'],
        bit_offset=8,
        bit_length=8,
        payload_length_hex=8,
        gain=0.5,
        offset=0,
        endianness='big',
        signed=False,
        n_trials=10,
        window_duration=5.0,
        message_rate=2.0
    )

    # 9. Battery Voltage (little-endian)
    examples['window_iot_battery'] = generate_window_example(
        name='IoT Battery Monitor',
        domain='iot',
        description='Battery voltage monitor for IoT devices. '
                    'Sensor ID 0xB1 with 16-bit voltage at bits 0-15, little-endian.',
        unit='V',
        value_range=(2.8, 4.2),
        target_message_id='0xB1',
        other_message_ids=['0xA0', '0xA1', '0xA2', '0xB2', '0xC1'],
        bit_offset=0,
        bit_length=16,
        payload_length_hex=8,
        gain=0.001,
        offset=0,
        endianness='little',
        signed=False,
        n_trials=14,
        window_duration=10.0,
        message_rate=1.0
    )

    # Save to JSON
    output_path = os.path.join(os.path.dirname(__file__), 'window_examples.json')
    with open(output_path, 'w') as f:
        json.dump(examples, f, indent=2)

    print(f"Generated {len(examples)} window-based examples:")
    for example_id, example in examples.items():
        n_trials = len(example['trials'])
        total_msgs = sum(len(t['messages']) for t in example['trials'])
        gt = example['ground_truth']
        print(f"  - {example_id}: {example['name']} ({example['domain']})")
        print(f"    {n_trials} trials, {total_msgs} total messages")
        print(f"    Target: {gt['message_id']}, offset={gt['bit_offset']}, len={gt['bit_length']}")

    print(f"\nSaved to: {output_path}")


if __name__ == '__main__':
    main()
