# CommDecode - Communication Payload Decoder

A web application for detecting bit group locations within communication data payloads where specific measurements are encoded.

## Overview

CommDecode solves the reverse engineering problem of finding which bit group in a data payload corresponds to a known physical measurement, given multiple sample pairs of (reference_value, captured_payload).

### Algorithm

1. **Sliding Window**: Iterate through every bit position in the payload
2. **Multi-Configuration Extraction**: At each offset, try 4/8/12/16 bit lengths with both endianness and signed/unsigned
3. **Correlation Analysis**: Calculate Pearson correlation between reference values and extracted values
4. **Linear Regression**: Fit linear model to discover encoding formula
5. **Validation**: Filter candidates by MAPE (Mean Absolute Percentage Error) threshold
6. **Ranking**: Sort by confidence score (correlation + p-value + MAPE + R²)

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
   - MAPE Threshold: Maximum error percentage (default: 5%)

4. **Click Decode**: The algorithm analyzes all possible bit locations and returns ranked candidates

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/examples` | GET | List available examples |
| `/api/examples/<id>` | GET | Get specific example data |
| `/api/validate` | POST | Validate input data |
| `/api/decode` | POST | Run decoding algorithm |

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
      "mape_threshold": 5.0,
      "top_n": 10
    }
  }'
```

## Predefined Examples

### Automotive
- **Engine RPM**: 16-bit big-endian, CAN bus style
- **Coolant Temperature**: 8-bit with offset (-40°C to 215°C)
- **Vehicle Speed**: 16-bit little-endian

### Industrial
- **Pressure Sensor**: 12-bit, Modbus-like
- **Flow Rate**: 16-bit signed (bidirectional)
- **Tank Level**: 8-bit percentage

### IoT
- **Temperature**: 12-bit signed (DS18B20-like)
- **Humidity**: 8-bit (DHT22-like)
- **Battery Voltage**: 16-bit little-endian

## Project Structure

```
CommDecode/
├── backend/
│   ├── app.py              # Flask API
│   ├── decoder.py          # Core algorithm
│   ├── requirements.txt
│   ├── Dockerfile
│   └── examples/
│       ├── generate_examples.py
│       └── examples.json
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
- **MAPE**: Mean Absolute Percentage Error
- **Formula**: Linear transformation `physical_value = gain × raw_value + offset`
- **Confidence Score**: Composite ranking score

## License

Proprietary - All rights reserved
