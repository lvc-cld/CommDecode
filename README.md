# CommDecode - Communication Payload Decoder

A web application for detecting bit group locations within communication data payloads where specific measurements are encoded.

## Overview

CommDecode solves the reverse engineering problem of finding which bit group in a data payload corresponds to a known physical measurement, given multiple sample pairs of (reference_value, captured_payload).

### Algorithm

1. **Sliding Window**: Iterate through every bit position in the payload
2. **Multi-Configuration Extraction**: At each offset, try bit lengths 4 to 24 (step 2), both byte orders, signed and unsigned
3. **Correlation Analysis**: Calculate Pearson correlation between reference values and extracted values
4. **Linear Regression**: Fit linear model to discover encoding formula
5. **Validation**: Filter candidates by error threshold (mean absolute error as % of the reference range)
6. **Ranking**: Sort by confidence score (R² + error). Layouts that decode to identical values are merged, and fields padded with noise bits are dropped (nested F-test)

### Modes

- **Simple (1:1)**: one payload per reference value.
- **Window (1:N)**: one reference value per trial, with many messages (several message IDs) captured in a time window. For each trial, the decoder picks the message that best fits the formula. Because that choice can make random bits fit any reference series, every Window candidate must also pass a **shuffle test**: its fit must be at least 100× better than fits to the same reference values shuffled across trials. In practice Window mode needs R² ≥ about 0.99.

### Bit numbering

- **Big endian** (Motorola, sequential): `bit_offset` counts from the MSB of byte 0, and the field is a contiguous run of bits.
- **Little endian** (Intel, as in CAN DBC files): `bit_offset` is the position of the field's LSB, where bit *k* is bit *k* mod 8 of byte *k* / 8. For byte-aligned fields this is the usual "low byte first".

## Quick Start

### Option 1: Docker (Recommended)

```bash
cd CommDecode
docker-compose up
```

Access the application at: http://localhost:8080

### Option 2: Manual Setup

**Backend:**
```bash
cd backend
pip install -r requirements.txt
python app.py
```

**Frontend:**
```bash
# In a separate terminal
cd frontend
python -m http.server 8000
```

The backend runs with debug mode off. Set `FLASK_DEBUG=1` only on a trusted machine,
because the Werkzeug debugger lets anyone who can reach the port run code.
Other environment variables: `HOST` (default `0.0.0.0`), `PORT` (default `5001`),
`CORS_ORIGINS` (comma-separated, default `http://localhost:8000,http://127.0.0.1:8000`).

### Tests

```bash
cd backend
pip install -r requirements-dev.txt
python -m pytest tests
```

Access:
- Frontend: http://localhost:8000
- API: http://localhost:5001/api

## Usage

1. **Load an Example** (optional): Select from 9 predefined examples covering automotive, industrial, and IoT domains

2. **Enter Data**:
   - Reference Values: Known physical measurement values (one per line)
   - Payloads: Captured data in hex format (one per line)

3. **Configure Settings** (optional):
   - Correlation Threshold: Minimum |r| to consider (default: 0.8)
   - Error Threshold: Maximum mean absolute error, as % of the reference range (default: 5%)

4. **Click Decode**: The algorithm analyzes all possible bit locations and returns ranked candidates

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/examples` | GET | List available examples |
| `/api/examples/<id>` | GET | Get specific example data |
| `/api/window-examples` | GET | List Window mode examples |
| `/api/window-examples/<id>` | GET | Get specific Window mode example |
| `/api/validate` | POST | Validate input data (Simple mode) |
| `/api/decode` | POST | Run decoding algorithm (Simple mode) |
| `/api/decode-window` | POST | Run decoding algorithm (Window mode) |

Request limits: 8 MB body, 1,000 trials, 20,000 messages in total, 512-bit payloads, `top_n` ≤ 100.
Window mode messages may use `id` instead of `message_id`.

### Example API Usage

```bash
curl -X POST http://localhost:5001/api/decode \
  -H "Content-Type: application/json" \
  -d '{
    "reference_values": [25.5, 30.2, 28.8, 35.1, 22.0],
    "payloads": ["A1B2C3D4E5F6", "A1B3C4D5E6F7", "A1B2D4D3E5F6", "A1B4C5D6E7F8", "A1B1C2D3E4F5"],
    "payload_format": "hex",
    "settings": {
      "correlation_threshold": 0.8,
      "error_threshold": 5.0,
      "top_n": 10
    }
  }'
```

## Predefined Examples

Each example exists in a Simple and a Window version. `TestData/` holds further Window captures in a
slightly different format (`id` for the message ID). `BatteryCurrent_Sample1.json` and `_Sample2.json` are
internally inconsistent (no single bit location encodes the reference value in every trial), so the
decoder correctly reports no match for them.

### Automotive
- **Engine RPM**: 16-bit big-endian, CAN bus style
- **Coolant Temperature**: 8-bit with offset (-40°C to 215°C)
- **Vehicle Speed**: 16-bit little-endian

### Industrial
- **Pressure Sensor**: 12-bit, Modbus-like
- **Flow Rate**: 16-bit unsigned
- **Tank Level**: 8-bit percentage

### IoT
- **Temperature**: 12-bit signed big-endian (DS18B20-like)
- **Humidity**: 8-bit (DHT22-like)
- **Battery Voltage**: 16-bit little-endian

## Project Structure

```
CommDecode/
├── backend/
│   ├── app.py              # Flask API
│   ├── bitfield.py         # Shared bit extraction, error metric, ranking
│   ├── decoder.py          # Simple mode algorithm
│   ├── window_decoder.py   # Window mode algorithm + shuffle test
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── tests/
│   ├── Dockerfile
│   └── examples/
│       ├── generate_examples.py
│       ├── generate_window_examples.py
│       ├── examples.json
│       └── window_examples.json
├── TestData/               # Extra Window mode captures
├── frontend/
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── app.js
│       ├── api.js
│       └── visualization.js
├── docker-compose.yml
├── nginx.conf
└── README.md
```

## Output

For each candidate match, the decoder provides:
- **Bit Location**: Offset and length
- **Encoding**: Endianness (big/little) and signedness
- **Correlation**: Pearson r value
- **Error**: Mean absolute error as % of the reference range (`error_pct`)
- **Shuffle test p-value** (Window mode): `shuffle_p_value`
- **Formula**: Linear transformation `physical_value = gain × raw_value + offset`
- **Confidence Score**: Composite ranking score

## License

Proprietary - All rights reserved
