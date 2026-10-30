"""Reviewed HTTP services expose OpenAPI operations through the normal tool dispatcher."""
from __future__ import annotations
import json
import re
import uuid
from urllib.parse import quote, unquote, urlsplit
import httpx
from .. import db
from ..agent.types import ToolSpec, ToolOutcome, ToolFailure
from ..localhttp import tls
from ..schemas_agents import AgentService, ServiceCreate, ServiceImport, ServiceOperation
from . import store, vault

MASK = '•••'
MAX_BYTES = 2 * 1024 * 1024


def init():
    db.execute('CREATE TABLE IF NOT EXISTS agent_services (id TEXT PRIMARY KEY, data TEXT NOT NULL)')


def raw(sid):
    row = db.query_one('SELECT data FROM agent_services WHERE id=?', (sid,))
    if not row:
        raise ValueError('Service not found')
    return AgentService.model_validate_json(row['data'])


def list_all():
    values = [AgentService.model_validate_json(row['data']) for row in db.query('SELECT data FROM agent_services ORDER BY rowid DESC')]
    return [value.model_copy(update={'headers':{key:MASK for key in value.headers}}) for value in values]


def endpoint(value):
    parts = urlsplit(value)
    if not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Service base URL must have a host and no credentials, query or fragment')
    if parts.scheme != 'https' and not (parts.scheme == 'http' and parts.hostname in ('localhost', '127.0.0.1', '::1')):
        raise ValueError('HTTP services require HTTPS, except loopback development endpoints')
    return value.rstrip('/')


def create(body: ServiceCreate):
    base = endpoint(body.base_url)
    names = set()
    for operation in body.operations:
        if operation.id in names or not operation.path.startswith('/') or operation.path.startswith('//') or '\\' in operation.path or '?' in operation.path or '#' in operation.path:
            raise ValueError('Duplicate operation identifier or unsafe operation path')
        decoded = operation.path
        for _ in range(3): decoded = unquote(decoded)
        if any(segment in ('.', '..') for segment in decoded.replace('\\','/').split('/')):
            raise ValueError('Operation path cannot traverse directories')
        if operation.parameters.get('type') != 'object' or not isinstance(operation.parameters.get('properties'), dict):
            raise ValueError('Operation parameters must be an object schema')
        if operation.read_only and operation.method not in ('GET', 'HEAD'):
            raise ValueError('Mutation methods cannot be marked read-only')
        from jsonschema import Draft202012Validator
        try:
            Draft202012Validator.check_schema(operation.parameters)
        except Exception as exc:
            raise ValueError('Invalid operation JSON schema: ' + str(exc)[:500]) from exc
        def refs(schema):
            if isinstance(schema, dict):
                if '$ref' in schema or '$dynamicRef' in schema:
                    raise ValueError('Operation schemas must resolve references before installation')
                for item in schema.values(): refs(item)
            elif isinstance(schema,list):
                for item in schema: refs(item)
        refs(operation.parameters)
        if any(key not in operation.parameters['properties'] for key in operation.bindings) or (operation.body_field and operation.body_field not in operation.parameters['properties']):
            raise ValueError('Operation bindings must refer to declared input properties')
        names.add(operation.id)
    from ..agent_plus.store import atomic
    with atomic():
        value = AgentService(id=uuid.uuid4().hex[:16], name=body.name, base_url=base, enabled=body.enabled,
            headers={key: vault.protect(secret) for key, secret in body.headers.items()}, operations=body.operations, created_at=db.now_iso())
        db.execute('INSERT INTO agent_services VALUES(?,?)', (value.id, value.model_dump_json()))
    store.notify('services')
    return next(item for item in list_all() if item.id == value.id)


def enable(sid, enabled):
    value = raw(sid); value.enabled = enabled
    db.execute('UPDATE agent_services SET data=? WHERE id=?', (value.model_dump_json(), sid))
    store.notify('services')
    return next(item for item in list_all() if item.id == sid)


def remove(sid):
    raw(sid)
    db.execute('DELETE FROM agent_services WHERE id=?', (sid,))
    store.notify('services')


def operation_name(sid, operation):
    from ..connectors import tool_name
    return tool_name('api_' + sid, operation.id)


def specs():
    return [ToolSpec(operation_name(item.id, operation), '[' + item.name + '] ' + operation.description,
                    operation.parameters, needs_approval=not operation.read_only)
            for row in db.query('SELECT data FROM agent_services') if (item := AgentService.model_validate_json(row['data'])).enabled
            for operation in item.operations]


def identify(name):
    for row in db.query('SELECT data FROM agent_services'):
        value = AgentService.model_validate_json(row['data'])
        if value.enabled:
            for operation in value.operations:
                if operation_name(value.id, operation) == name:
                    return value, operation
    raise ToolFailure('Service operation is unavailable')


def redact(value):
    if isinstance(value, dict):
        return {key: MASK if re.search(r'^(authorization|cookie|set-cookie|access_token|refresh_token|client_secret|password|api_key)$', key, re.I) else redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def request(value, operation, args):
    path, query = operation.path, {}
    for key, binding in operation.bindings.items():
        if key not in args:
            continue
        if binding.location == 'path':
            text = str(args[key])
            if any(segment in ('.','..') for segment in text.replace('\\','/').split('/')):
                raise ToolFailure('Path parameters cannot traverse directories')
            path = path.replace('{' + binding.name + '}', quote(text, safe=''))
        else:
            query[binding.name] = args[key]
    if re.search(r'\{[^}]+\}', path):
        raise ToolFailure('Required path parameter is missing')
    return value.base_url + path, query, args.get(operation.body_field) if operation.body_field else None


async def call(name, args, ctx):
    value, operation = identify(name)
    from jsonschema import Draft202012Validator, ValidationError
    try:
        Draft202012Validator(operation.parameters).validate(args)
    except ValidationError as exc:
        raise ToolFailure('Service input does not match its schema: ' + exc.message[:500]) from exc
    url, query, body = request(value, operation, args)
    from . import oauth
    authorized = await oauth.authorized_config({'id': value.id, 'headers': value.headers})
    headers = vault.resolve_map(authorized['headers'])
    async with httpx.AsyncClient(timeout=60, verify=tls, trust_env=False, follow_redirects=False) as client:
        async with client.stream(operation.method, url, params=query, json=body, headers=headers) as response:
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ToolFailure('Service result exceeds the 2 MiB limit; inspect before repeating a mutation')
                chunks.append(chunk)
            data = b''.join(chunks)
            try:
                payload = redact(json.loads(data))
            except (ValueError, UnicodeError):
                payload = data.decode('utf-8', errors='replace')[:64000]
            successful = response.is_success and not (isinstance(payload,dict) and (payload.get('ok') is False or bool(payload.get('errors'))))
            return ToolOutcome(successful, json.dumps({'service': value.name, 'operation': operation.id,
                'status': response.status_code, 'observed_at':db.now_iso(), 'source':url, 'data': payload}, ensure_ascii=False))


def import_openapi(body: ServiceImport):
    document = body.document
    if len(json.dumps(document)) > MAX_BYTES or not str(document.get('openapi', '')).startswith('3.'):
        raise ValueError('Provide an OpenAPI 3 document under 2 MiB')
    warnings, operations = [], []
    def resolve(value, trail=()):
        if len(trail) > 24:
            raise ValueError('Schema nesting exceeds the import limit')
        if isinstance(value, dict):
            if '$ref' in value:
                reference = value['$ref']
                if not isinstance(reference, str) or not reference.startswith('#/') or reference in trail:
                    raise ValueError('Remote or recursive references require a manual operation schema')
                target = document
                for part in reference[2:].split('/'):
                    target = target[part.replace('~1', '/').replace('~0', '~')]
                return resolve(target, (*trail, reference))
            result = {key:resolve(item,(*trail,key)) for key,item in value.items()}
            if result.pop('nullable',False) and isinstance(result.get('type'),str): result['type'] = [result['type'],'null']
            return result
        if isinstance(value, list):
            return [resolve(item, (*trail, 'item')) for item in value]
        return value
    paths = document.get('paths',{})
    if not isinstance(paths,dict): raise ValueError('OpenAPI paths must be an object')
    for path, item in paths.items():
        if not isinstance(item,dict):
            warnings.append(str(path) + ': Path item must be an object'); continue
        for method, definition in item.items():
            if len(operations) >= 500:
                raise ValueError('Import at most 500 operations per service')
            if method.upper() not in ('GET','POST','PUT','PATCH','DELETE','HEAD'):
                continue
            try:
                if not isinstance(definition,dict): raise ValueError('Operation must be an object')
                definition = {**definition, 'parameters': resolve(definition.get('parameters', [])),
                              **({'requestBody':resolve(definition['requestBody'])} if definition.get('requestBody') else {})}
                properties, bindings, required = {}, {}, []
                merged = {}
                for parameter in [*resolve(item.get('parameters', [])), *definition.get('parameters', [])]:
                    merged[(parameter.get('in'),parameter.get('name'))] = parameter
                for parameter in merged.values():
                    location, name = parameter.get('in'), parameter.get('name')
                    if location not in ('path', 'query'):
                        if parameter.get('required'):
                            raise ValueError('Required headers/cookies belong in connection configuration')
                        continue
                    if not isinstance(name,str) or not name: raise ValueError('Parameter name is required')
                    schema = parameter.get('schema',{'type':'string'})
                    if schema.get('type') == 'object' or (location == 'path' and schema.get('type') == 'array') or parameter.get('style', 'form' if location == 'query' else 'simple') not in ('form','simple') or (schema.get('type') == 'array' and parameter.get('explode') is False):
                        raise ValueError('Complex parameter serialization requires a manual adapter')
                    key = name if name not in properties else location + '_' + name
                    if key in properties: raise ValueError('Conflicting parameter names')
                    properties[key] = schema
                    bindings[key] = {'location': location, 'name': name}
                    if parameter.get('required') or location == 'path':
                        required.append(key)
                request_body = definition.get('requestBody')
                body_field = None
                if request_body:
                    schema = request_body.get('content', {}).get('application/json', {}).get('schema')
                    if not schema:
                        raise ValueError('Only JSON request bodies are imported')
                    body_field = 'request_body'
                    if body_field in properties:
                        raise ValueError('Conflicting request_body parameter')
                    properties[body_field] = schema
                    if request_body.get('required'):
                        required.append(body_field)
                operations.append(ServiceOperation(id=definition.get('operationId') or method + '_' + re.sub(r'[^a-z0-9]+', '_', path.lower()),
                    description=definition.get('summary') or definition.get('description') or method.upper() + ' ' + path,
                    method=method.upper(), path=path, parameters={'type':'object','properties':properties,'required':required,'additionalProperties':False},
                    bindings=bindings, body_field=body_field))
            except (ValueError, KeyError, TypeError) as exc:
                warnings.append(method.upper() + ' ' + path + ': ' + str(exc))
    if not operations:
        raise ValueError('No supported operations found')
    return {'service': ServiceCreate(name=body.name, base_url=endpoint(body.base_url), headers=body.headers, operations=operations).model_dump(), 'warnings': warnings}
