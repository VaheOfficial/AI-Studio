"""Authorization-code PKCE onboarding for user-configured HTTP connectors."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode, urlsplit
import httpx
from .. import config, db
from . import store, vault


from ..schemas_agents import OAuthConfig


def init():
    db.execute('CREATE TABLE IF NOT EXISTS agent_oauth (connector_id TEXT PRIMARY KEY, data TEXT NOT NULL, token_ref TEXT, expires_at REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS agent_oauth_pending (state TEXT PRIMARY KEY, connector_id TEXT NOT NULL, verifier_ref TEXT NOT NULL, expires_at REAL NOT NULL)')


def validate_url(url):
    parts = urlsplit(url)
    if not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError('Enter an authorization endpoint without embedded credentials')
    if parts.scheme != 'https' and not (parts.scheme == 'http' and parts.hostname in ('localhost', '127.0.0.1', '::1')):
        raise ValueError('OAuth endpoints require HTTPS (except loopback development endpoints)')


def start(body: OAuthConfig):
    from ..connectors import _raw
    if body.target == 'service':
        from .services import raw
        raw(body.connector_id)
        connector = {'transport': 'http'}
    else:
        connector = _raw(body.connector_id)
    if connector['transport'] != 'http':
        raise ValueError('OAuth onboarding is for HTTP connectors')
    validate_url(body.authorize_url); validate_url(body.token_url)
    data = body.model_dump()
    if data['client_secret']:
        data['client_secret'] = vault.protect(data['client_secret'])
    db.execute('INSERT INTO agent_oauth(connector_id,data) VALUES(?,?) ON CONFLICT(connector_id) DO UPDATE SET data=excluded.data', (body.connector_id, json.dumps(data)))
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    db.execute('DELETE FROM agent_oauth_pending WHERE expires_at < ?', (time.time(),))
    db.execute('INSERT INTO agent_oauth_pending VALUES(?,?,?,?)', (state, body.connector_id, vault.protect(verifier), time.time() + 600))
    params = {'response_type': 'code', 'client_id': body.client_id, 'redirect_uri': redirect_uri(), 'state': state,
              'code_challenge': challenge, 'code_challenge_method': 'S256', 'scope': ' '.join(body.scopes)}
    return {'authorize_url': body.authorize_url + ('&' if '?' in body.authorize_url else '?') + urlencode(params), 'redirect_uri': redirect_uri()}


def redirect_uri():
    return f'http://127.0.0.1:{config.PORT}/api/agents/oauth/callback'


async def token_request(data, fields):
    fields['client_id'] = data['client_id']
    if data.get('client_secret'):
        fields['client_secret'] = vault.reveal(data['client_secret'])
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.post(data['token_url'], data=fields)
        if not response.is_success:
            raise ValueError(f'OAuth token exchange failed ({response.status_code})')
        result = response.json()
    if not isinstance(result.get('access_token'), str):
        raise ValueError('OAuth response did not include an access token')
    if result.get('token_type', 'Bearer').lower() != 'bearer':
        raise ValueError('Only Bearer token connectors are supported')
    return result


def save_tokens(cid, tokens):
    reference = vault.protect(json.dumps(tokens))
    expires = time.time() + max(0, float(tokens.get('expires_in', 3600)))
    db.execute('UPDATE agent_oauth SET token_ref=?,expires_at=? WHERE connector_id=?', (reference, expires, cid))
    store.notify('connections')


async def finish(state, code):
    from ..agent_plus.store import atomic
    with atomic():
        pending = db.query_one('SELECT * FROM agent_oauth_pending WHERE state=?', (state,))
        if not pending or pending['expires_at'] < time.time():
            raise ValueError('Authorization expired or was already used')
        db.execute('DELETE FROM agent_oauth_pending WHERE state=?', (state,))
    row = db.query_one('SELECT data FROM agent_oauth WHERE connector_id=?', (pending['connector_id'],))
    data = json.loads(row['data'])
    tokens = await token_request(data, {'grant_type': 'authorization_code', 'code': code,
        'redirect_uri': redirect_uri(), 'code_verifier': vault.reveal(pending['verifier_ref'])})
    save_tokens(pending['connector_id'], tokens)
    if data.get('target') == 'service':
        store.notify('services')
        return {'connected': True, 'connector_id': pending['connector_id']}
    from ..connectors import manager, _raw
    await manager._stop(pending['connector_id'])
    value = _raw(pending['connector_id'])
    if value['enabled']:
        manager._start(value)
    return {'connected': True, 'connector_id': pending['connector_id']}


_locks: dict[str, asyncio.Lock] = {}
async def authorized_config(d):
    cid = d['id']
    row = db.query_one('SELECT * FROM agent_oauth WHERE connector_id=?', (cid,))
    if not row or not row['token_ref']:
        return d
    async with _locks.setdefault(cid, asyncio.Lock()):
        row = db.query_one('SELECT * FROM agent_oauth WHERE connector_id=?', (cid,))
        tokens = json.loads(vault.reveal(row['token_ref']))
        if row['expires_at'] is not None and row['expires_at'] <= time.time() + 60:
            if not tokens.get('refresh_token'):
                raise ValueError('Connector authorization expired; connect again')
            newer = await token_request(json.loads(row['data']), {'grant_type': 'refresh_token', 'refresh_token': tokens['refresh_token']})
            newer.setdefault('refresh_token', tokens['refresh_token'])
            tokens = newer
            save_tokens(cid, tokens)
        return {**d, 'headers': {**d.get('headers', {}), 'Authorization': 'Bearer ' + tokens['access_token']}}


def connections():
    return [{'connector_id': r['connector_id'], 'authorized': bool(r['token_ref']), 'expires_at': r['expires_at']}
            for r in db.query('SELECT connector_id,token_ref,expires_at FROM agent_oauth')]
