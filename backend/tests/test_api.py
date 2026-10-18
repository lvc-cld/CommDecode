import pytest

import app as app_module


@pytest.fixture
def client():
    app_module.app.config['TESTING'] = True
    return app_module.app.test_client()


SIMPLE_TRIALS = [
    {'reference_value': raw * 0.5, 'payload': f'AA{raw:02X}55'}
    for raw in [10, 40, 25, 90, 60, 120, 5]
]


def test_health(client):
    assert client.get('/api/health').get_json()['status'] == 'ok'


def test_decode_returns_ranked_candidates(client):
    response = client.post('/api/decode', json={'trials': SIMPLE_TRIALS})
    body = response.get_json()
    assert response.status_code == 200
    assert (body['candidates'][0]['bit_offset'], body['candidates'][0]['bit_length']) == (8, 8)
    assert 'error_pct' in body['candidates'][0]


def test_legacy_mape_threshold_setting_is_accepted(client):
    response = client.post('/api/decode', json={'trials': SIMPLE_TRIALS, 'settings': {'mape_threshold': 2}})
    assert response.status_code == 200
    assert response.get_json()['thresholds']['error_pct'] == 2


@pytest.mark.parametrize('settings', [
    {'top_n': 0}, {'top_n': 1000}, {'top_n': 'x'}, {'correlation_threshold': 2},
    {'p_value_threshold': 0}, {'error_threshold': True}, 'not-an-object',
])
def test_invalid_settings_are_rejected(client, settings):
    response = client.post('/api/decode', json={'trials': SIMPLE_TRIALS, 'settings': settings})
    assert response.status_code == 400


@pytest.mark.parametrize('trial', [
    {'reference_value': True, 'payload': 'AA00'},
    {'reference_value': None, 'payload': 'AA00'},
    {'reference_value': 'x', 'payload': 'AA00'},
    {'reference_value': 1.0, 'payload': 'ZZ'},
    {'reference_value': 1.0, 'payload': 'A' * 200},  # 800 bits
])
def test_invalid_trials_are_rejected(client, trial):
    response = client.post('/api/decode', json={'trials': SIMPLE_TRIALS[:3] + [trial]})
    assert response.status_code == 400


def test_too_many_trials_are_rejected(client):
    trials = SIMPLE_TRIALS * (app_module.MAX_TRIALS // len(SIMPLE_TRIALS) + 1)
    assert client.post('/api/decode', json={'trials': trials}).status_code == 400


def test_too_many_window_messages_are_rejected(client):
    messages = [{'timestamp': 0, 'message_id': '0x1', 'payload': 'AABB'}] * (app_module.MAX_TOTAL_MESSAGES // 3 + 1)
    trials = [{'reference_value': float(i), 'messages': messages} for i in range(3)]
    assert client.post('/api/decode-window', json={'trials': trials}).status_code == 400


def test_window_accepts_id_alias(client):
    trials = [
        {'reference_value': raw * 0.5,
         'messages': [{'timestamp': 0, 'id': '0x9', 'payload': f'{raw:04X}0000'}]}
        for raw in [100, 900, 400, 2500, 1600, 3100]
    ]
    body = client.post('/api/decode-window', json={'trials': trials}).get_json()
    assert body['candidates'][0]['message_id'] == '0x9'


def test_oversized_request_is_rejected(client):
    body = b'{"trials": "' + b'x' * app_module.MAX_CONTENT_LENGTH + b'"}'
    response = client.post('/api/decode', data=body, content_type='application/json')
    assert response.status_code == 413


def test_cors_allows_only_configured_origins(client):
    allowed = client.get('/api/health', headers={'Origin': 'http://localhost:8000'})
    other = client.get('/api/health', headers={'Origin': 'http://evil.example'})
    assert allowed.headers.get('Access-Control-Allow-Origin') == 'http://localhost:8000'
    assert 'Access-Control-Allow-Origin' not in other.headers


def test_debug_mode_is_off_by_default():
    assert not app_module.app.debug
