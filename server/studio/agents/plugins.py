"""Reviewed local plugin bundles: instructions and disabled-by-default MCP connectors."""
from __future__ import annotations
import io
import json
import zipfile
import re
import yaml
from .. import db
from ..schemas_agents import SkillCreate
from ..schemas_connectors import ConnectorCreate
from . import store


def init():
    db.execute('CREATE TABLE IF NOT EXISTS agent_plugins (id TEXT PRIMARY KEY, version TEXT NOT NULL, data TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS agent_plugin_files (plugin_id TEXT NOT NULL, path TEXT NOT NULL, content BLOB NOT NULL, PRIMARY KEY(plugin_id,path))')


def skill_document(text: str, fallback: str) -> dict:
    metadata = {}
    if text.startswith('---\n') or text.startswith('---\r\n'):
        parts = re.split(r'^---\s*$', text, maxsplit=2, flags=re.M)
        if len(parts) != 3:
            raise ValueError('Skill frontmatter is not closed')
        try:
            metadata = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError as exc:
            raise ValueError('Invalid skill frontmatter') from exc
        if not isinstance(metadata, dict):
            raise ValueError('Skill metadata must be an object')
        text = parts[2].strip()
    return SkillCreate(name=str(metadata.get('name') or fallback), description=str(metadata.get('description') or ''),
                       instructions=text).model_dump()


def import_manifest(archive, names):
    if 'plugin.json' in names:
        manifest = json.loads(archive.read('plugin.json'))
        return manifest, {name: name for name in names if not name.endswith('/')}, []
    markers = [name for name in names if name.endswith('.claude-plugin/plugin.json')]
    if len(markers) != 1:
        raise ValueError('Expected plugin.json or one .claude-plugin/plugin.json')
    marker = markers[0]
    root = marker.removesuffix('.claude-plugin/plugin.json')
    original = json.loads(archive.read(marker))
    if not isinstance(original, dict) or not isinstance(original.get('name'), str):
        raise ValueError('Plugin manifest requires a name')
    files = {name.removeprefix(root): name for name in names if name.startswith(root) and not name.endswith('/')}
    skills = []
    for path, source in sorted(files.items()):
        if path.startswith('skills/') and path.endswith('/SKILL.md'):
            skill = skill_document(archive.read(source).decode('utf-8'), path.split('/')[-2])
            skill['name'] = original['name'] + ':' + skill['name']
            skill['instructions'] += '\n\nPlugin source: ' + original['name'] + '/' + path + '. Use plugin_read_file for referenced supporting files.'
            skills.append(SkillCreate.model_validate(skill).model_dump())
    if len(skills) > 50:
        raise ValueError('Plugin exceeds the 50-skill limit')
    servers = {}
    if '.mcp.json' in files:
        config = json.loads(archive.read(files['.mcp.json']))
        if not isinstance(config, dict) or not isinstance(config.get('mcpServers', config), dict):
            raise ValueError('MCP configuration must contain a server map')
        servers.update(config.get('mcpServers', config))
    declared = original.get('mcpServers', {})
    warnings = []
    if isinstance(declared, dict):
        servers.update(declared)
    elif declared:
        warnings.append('Custom MCP configuration paths require manual setup')
    connections = []
    for name, config in servers.items():
        if not isinstance(config, dict):
            raise ValueError('Invalid MCP server configuration')
        serialized = json.dumps(config)
        if len(connections) >= 20:
            raise ValueError('Plugin exceeds the 20-connection limit')
        if '${' in serialized or config.get('type') not in (None, 'stdio', 'http') or config.get('env') or config.get('headers'):
            warnings.append(f'Configure MCP connection {name} manually: variables, credentials or transport require review')
            continue
        connections.append({'name': original['name'] + '-' + name, 'transport': 'http' if config.get('url') else 'stdio',
                            **{k: config[k] for k in ('command','args','url') if k in config}})
    ignored = [name for name in ('hooks','agents','commands','skills','settings','userConfig','channels','lspServers','outputStyles','workflows','dependencies') if original.get(name)]
    if ignored:
        warnings.append('Provider-specific declarations are retained as source files, without executing: ' + ', '.join(ignored))
    manifest = {'format': 'grom-plugin-v1', 'id': original['name'], 'version': original.get('version','1'),
                'skills': skills, 'connectors': connections, 'imported': True}
    return manifest, files, warnings


def inspect(data: bytes) -> dict:
    if len(data) > 10 * 1024 * 1024:
        raise ValueError('Plugin exceeds the 10 MiB limit')
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError('Plugin must be a valid ZIP bundle') from exc
    with archive:
        names = archive.namelist()
        if len(names) > 200 or len({name.replace('\\', '/') for name in names}) != len(names):
            raise ValueError('Plugin contains too many or duplicate entries')
        if sum(entry.file_size for entry in archive.infolist()) > 20 * 1024 * 1024:
            raise ValueError('Expanded plugin exceeds the 20 MiB limit')
        for entry in archive.infolist():
            name = entry.filename.replace('\\', '/')
            if name.startswith('/') or ':' in name or '..' in name.split('/') or entry.file_size > 1024 * 1024:
                raise ValueError('Unsafe plugin entry')
        manifest, source_files, warnings = import_manifest(archive, names)
        if not isinstance(manifest, dict) or manifest.get('format') != 'grom-plugin-v1':
            raise ValueError('Expected a grom-plugin-v1 manifest')
        identity = manifest.get('id', '')
        if not identity or len(identity) > 120 or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_.' for c in identity):
            raise ValueError('Invalid plugin identifier')
        if not isinstance(manifest.get('skills', []), list) or len(manifest.get('skills', [])) > 50:
            raise ValueError('Provide at most 50 skill entries')
        if not isinstance(manifest.get('connectors', []), list) or len(manifest.get('connectors', [])) > 20:
            raise ValueError('Provide at most 20 connection entries')
        skills = []
        for entry in manifest.get('skills', []):
            body = dict(entry)
            if body.get('file'):
                body['instructions'] = archive.read(body.pop('file')).decode('utf-8')
            skills.append(SkillCreate.model_validate(body).model_dump())
        connectors = []
        for entry in manifest.get('connectors', []):
            body = ConnectorCreate.model_validate({**entry, 'enabled': False, 'approval': 'ask'})
            if body.env or body.headers:
                raise ValueError('Supply credentials through connection settings, not plugin bundles')
            connectors.append(body.model_dump())
        files = {}
        for path, name in source_files.items():
            try:
                files[path] = archive.read(name).decode('utf-8')
            except UnicodeDecodeError:
                warnings.append('Binary source omitted: ' + path)
        return {'id': identity, 'version': str(manifest.get('version', '1'))[:60], 'skills': skills, 'connectors': connectors,
                'source_files': files, 'warnings': warnings, 'imported': bool(manifest.get('imported'))}


def install(bundle):
    from ..agent_plus.store import atomic
    from ..connectors import manager
    old = db.query_one('SELECT data FROM agent_plugins WHERE id=?', (bundle['id'],))
    if old:
        raise ValueError('Plugin already installed; remove it before installing a new version')
    pending = {s['name']: s for s in bundle['skills']}
    if len(pending) != len(bundle['skills']):
        raise ValueError('Duplicate skill name in plugin')
    ordered = []
    while pending:
        ready = [s for s in pending.values() if not set(s.get('dependencies', [])) & pending.keys()]
        if not ready:
            raise ValueError('Plugin skill dependencies contain a cycle')
        for skill in ready:
            ordered.append(skill)
            pending.pop(skill['name'])
    with atomic():
        skills = [store.add_skill(SkillCreate.model_validate(s)).id for s in ordered]
        if bundle.get('imported'):
            for sid in skills:
                skill = store.skill(sid)
                skill.enabled = False
                db.execute('UPDATE agent_skills SET data=? WHERE id=?', (skill.model_dump_json(), sid))
        connectors = [manager.create(ConnectorCreate.model_validate(c)).id for c in bundle['connectors']]
        for path, content in bundle.get('source_files', {}).items():
            db.execute('INSERT INTO agent_plugin_files VALUES(?,?,?)', (bundle['id'], path, content.encode()))
        record = {**{k: v for k,v in bundle.items() if k != 'source_files'}, 'file_paths': sorted(bundle.get('source_files', {})), 'skill_ids': skills, 'connector_ids': connectors}
        db.execute('INSERT INTO agent_plugins VALUES(?,?,?)', (bundle['id'], bundle['version'], json.dumps(record)))
    store.notify('plugins')
    return {'id': bundle['id'], 'version': bundle['version'], 'skill_ids': skills, 'connector_ids': connectors}


def list_all():
    return [{'id': r['id'], 'version': r['version'], **{k: v for k,v in json.loads(r['data']).items() if k in ('skill_ids','connector_ids')}}
            for r in db.query('SELECT * FROM agent_plugins ORDER BY id')]


async def remove(pid):
    from ..connectors import manager
    row = db.query_one('SELECT data FROM agent_plugins WHERE id=?', (pid,))
    if not row:
        raise ValueError('Plugin not found')
    data = json.loads(row['data'])
    for cid in data['connector_ids']:
        try:
            await manager.delete(cid)
        except ValueError:
            pass
    for sid in data['skill_ids']:
        db.execute('DELETE FROM agent_skills WHERE id=?', (sid,))
    db.execute('DELETE FROM agent_plugins WHERE id=?', (pid,))
    db.execute('DELETE FROM agent_plugin_files WHERE plugin_id=?', (pid,))
    store.notify('plugins')


def read_file(pid, path):
    row = db.query_one('SELECT content FROM agent_plugin_files WHERE plugin_id=? AND path=?', (pid, path))
    if not row:
        raise ValueError('Plugin source file not found')
    content = bytes(row['content'])
    if len(content) > 256000:
        raise ValueError('Plugin source exceeds the 256 KiB read limit')
    return {'plugin_id': pid, 'path': path, 'text': content.decode('utf-8')}
