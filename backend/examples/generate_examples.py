"""
Generate predefined example datasets for the Communication Decoder.

Creates 9 examples:
- Automotive (3): Engine RPM, Coolant Temperature, Vehicle Speed
- Industrial (3): Pressure Sensor, Flow Rate, Tank Level
- IoT (3): Temperature, Humidity, Battery Voltage
"""

import json
import random
import os

# Set seed for reproducibility
random.seed(42)


def generate_random_bits(length: int) -> str:
    """Generate random binary string of given length."""
    return ''.join(random.choice('01') for _ in range(length))


def int_to_bits(value: int, bit_length: int, endianness: str = 'big') -> str:
    """Convert integer to binary string with specified endianness."""
    if value < 0:
        # Two's complement
        value = (1 << bit_length) + value

    bits = format(value, f'0{bit_length}b')

    # Handle byte-level endianness for byte-aligned values
    if bit_length % 8 == 0 and endianness == 'little':
        num_bytes = bit_length // 8
        byte_list = [bits[i*8:(i+1)*8] for i in range(num_bytes)]
        bits = ''.join(reversed(byte_list))

    return bits


def bits_to_hex(bits: str) -> str:
    """Convert binary string to hex string."""
    hex_str = ''
    for i in range(0, len(bits), 4):
        nibble = bits[i:i+4]
        hex_str += format(int(nibble, 2), 'X')
    return hex_str


def generate_payload(reference_value: float,
                    gain: float,
                    offset: float,
                    bit_offset: int,
                    bit_length: int,
                    payload_length_bits: int,
                    endianness: str = 'big',
                    signed: bool = False,
                    noise_percent: float = 0.5) -> tuple:
    """
    Generate a payload with the encoded value at the specified location.

    The encoding formula is: raw_value = (reference_value - offset) / gain
    Adding small noise to simulate real-world measurements.

    Returns: (actual_reference, hex_payload)
    """
    # Add small measurement noise
    noise = reference_value * (random.uniform(-noise_percent, noise_percent) / 100)
    noisy_reference = reference_value + noise

    # Calculate raw encoded value
    raw_value = int(round((noisy_reference - offset) / gain))

    # Clamp to valid range
    if signed:
        min_val = -(1 << (bit_length - 1))
        max_val = (1 << (bit_length - 1)) - 1
    else:
        min_val = 0
        max_val = (1 << bit_length) - 1

    raw_value = max(min_val, min(max_val, raw_value))

    # Generate random payload
    bits = list(generate_random_bits(payload_length_bits))

    # Insert encoded value at specified offset
    value_bits = int_to_bits(raw_value, bit_length, endianness)
    for i, bit in enumerate(value_bits):
        bits[bit_offset + i] = bit

    # Convert to hex
    hex_payload = bits_to_hex(''.join(bits))

    return noisy_reference, hex_payload


def generate_example(name: str,
                    domain: str,
                    description: str,
                    unit: str,
                    value_range: tuple,
                    n_samples: int,
                    bit_offset: int,
                    bit_length: int,
                    payload_length_bits: int,
                    gain: float,
                    offset: float,
                    endianness: str = 'big',
                    signed: bool = False) -> dict:
    """Generate a complete example dataset."""

    # Generate reference values within the range
    min_val, max_val = value_range
    reference_values = []
    payloads = []

    for _ in range(n_samples):
        ref_value = random.uniform(min_val, max_val)
        actual_ref, payload = generate_payload(
            ref_value, gain, offset, bit_offset, bit_length,
            payload_length_bits, endianness, signed
        )
        reference_values.append(round(actual_ref, 4))
        payloads.append(payload)

    return {
        'name': name,
        'domain': domain,
        'description': description,
        'unit': unit,
        'reference_values': reference_values,
        'payloads': payloads,
        'payload_format': 'hex',
        'ground_truth': {
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

    # 1. Engine RPM (CAN-like, 16-bit, big-endian)
    # Typical CAN encoding: RPM = raw * 0.25
    examples['automotive_rpm'] = generate_example(
        name='Engine RPM',
        domain='automotive',
        description='Engine speed measurement from OBD-II / CAN bus. '
                    'Typical range 0-8000 RPM, encoded in 16 bits.',
        unit='RPM',
        value_range=(800, 7500),
        n_samples=15,
        bit_offset=8,  # After 1-byte header
        bit_length=16,
        payload_length_bits=64,  # 8-byte CAN frame
        gain=0.25,
        offset=0,
        endianness='big',
        signed=False
    )

    # 2. Coolant Temperature (8-bit with offset)
    # Typical encoding: Temp(C) = raw - 40
    examples['automotive_coolant'] = generate_example(
        name='Coolant Temperature',
        domain='automotive',
        description='Engine coolant temperature from ECU. '
                    'Range -40 to 215°C, 8-bit encoding with offset.',
        unit='°C',
        value_range=(60, 105),
        n_samples=12,
        bit_offset=24,
        bit_length=8,
        payload_length_bits=64,
        gain=1.0,
        offset=-40,
        endianness='big',
        signed=False
    )

    # 3. Vehicle Speed (little-endian, 16-bit)
    # Speed = raw * 0.01 (in km/h)
    examples['automotive_speed'] = generate_example(
        name='Vehicle Speed',
        domain='automotive',
        description='Vehicle speed from wheel sensors. '
                    '16-bit little-endian encoding, range 0-250 km/h.',
        unit='km/h',
        value_range=(0, 180),
        n_samples=14,
        bit_offset=32,
        bit_length=16,
        payload_length_bits=64,
        gain=0.01,
        offset=0,
        endianness='little',
        signed=False
    )

    # ==================== INDUSTRIAL EXAMPLES ====================

    # 4. Pressure Sensor (12-bit, Modbus-like)
    # Pressure = raw * 0.1 (in bar)
    examples['industrial_pressure'] = generate_example(
        name='Pressure Sensor',
        domain='industrial',
        description='Industrial pressure transmitter (4-20mA converted). '
                    '12-bit resolution, range 0-400 bar.',
        unit='bar',
        value_range=(10, 350),
        n_samples=16,
        bit_offset=4,  # Nibble-aligned
        bit_length=12,
        payload_length_bits=48,
        gain=0.1,
        offset=0,
        endianness='big',
        signed=False
    )

    # 5. Flow Rate (16-bit, signed for bidirectional flow)
    # Flow = raw * 0.1 (in L/min) - using larger gain for better resolution
    examples['industrial_flow'] = generate_example(
        name='Flow Rate',
        domain='industrial',
        description='Bidirectional flow meter for liquids. '
                    '16-bit unsigned, range 50 to 450 L/min.',
        unit='L/min',
        value_range=(50, 450),  # Use positive range for cleaner MAPE
        n_samples=20,
        bit_offset=16,
        bit_length=16,
        payload_length_bits=64,
        gain=0.1,
        offset=0,
        endianness='big',
        signed=False  # Use unsigned for cleaner example
    )

    # 6. Tank Level (8-bit percentage)
    # Level = raw * 0.5 (0-100%)
    examples['industrial_tank'] = generate_example(
        name='Tank Level',
        domain='industrial',
        description='Ultrasonic tank level sensor. '
                    '8-bit encoding representing 0-100% fill level.',
        unit='%',
        value_range=(5, 95),
        n_samples=13,
        bit_offset=40,
        bit_length=8,
        payload_length_bits=56,
        gain=0.5,
        offset=0,
        endianness='big',
        signed=False
    )

    # ==================== IOT EXAMPLES ====================

    # 7. Temperature (12-bit, signed for negative temps)
    # Temp = raw * 0.0625 (common for DS18B20-like sensors)
    examples['iot_temperature'] = generate_example(
        name='IoT Temperature',
        domain='iot',
        description='Digital temperature sensor (DS18B20-like). '
                    '12-bit signed, resolution 0.0625°C.',
        unit='°C',
        value_range=(-10, 45),
        n_samples=15,
        bit_offset=8,
        bit_length=12,
        payload_length_bits=40,
        gain=0.0625,
        offset=0,
        endianness='big',  # 'little' only applies to byte-aligned fields here
        signed=True
    )

    # 8. Humidity (8-bit, 0-100%)
    # Humidity = raw * 0.5
    examples['iot_humidity'] = generate_example(
        name='Relative Humidity',
        domain='iot',
        description='Capacitive humidity sensor (DHT22-like). '
                    '8-bit encoding, 0-100% RH.',
        unit='%RH',
        value_range=(20, 85),
        n_samples=12,
        bit_offset=20,
        bit_length=8,
        payload_length_bits=40,
        gain=0.5,
        offset=0,
        endianness='big',
        signed=False
    )

    # 9. Battery Voltage (16-bit, millivolts)
    # Voltage = raw * 0.001 (in V)
    examples['iot_battery'] = generate_example(
        name='Battery Voltage',
        domain='iot',
        description='LiPo battery voltage monitor. '
                    '16-bit little-endian, range 2.5-4.2V.',
        unit='V',
        value_range=(2.8, 4.15),
        n_samples=14,
        bit_offset=0,
        bit_length=16,
        payload_length_bits=48,
        gain=0.001,
        offset=0,
        endianness='little',
        signed=False
    )

    # Save to JSON
    output_path = os.path.join(os.path.dirname(__file__), 'examples.json')
    with open(output_path, 'w') as f:
        json.dump(examples, f, indent=2)

    print(f"Generated {len(examples)} examples:")
    for example_id, example in examples.items():
        print(f"  - {example_id}: {example['name']} ({example['domain']})")
        print(f"    {len(example['reference_values'])} samples, "
              f"offset={example['ground_truth']['bit_offset']}, "
              f"length={example['ground_truth']['bit_length']}")

    print(f"\nSaved to: {output_path}")


if __name__ == '__main__':
    main()
