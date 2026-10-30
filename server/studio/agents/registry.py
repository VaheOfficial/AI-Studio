"""Search and deferred schema loading over the permission-aware tool catalog."""
from __future__ import annotations
import re
import math
from collections import Counter
from .. import db
from ..agent.types import ToolSpec
from ..schemas_agents import CapabilityEntry

BASE = {'start_mission', 'search_tools', 'load_tools', 'ask_user', 'list_dir', 'read_file',
        'search_files', 'system_info', 'list_models', 'world_time', 'skill_read'}


def visible(sid: str, specs: list[ToolSpec]) -> list[ToolSpec]:
    from . import documents
    specs = [s for s in specs if not s.name.startswith("document__") or documents.owned(sid, s.name)]
    loaded = {r['name'] for r in db.query('SELECT name FROM agent_tool_loads WHERE session_id = ?', (sid,))}
    # A small catalog is already cheaper than a discovery round trip.
    if len(specs) <= 24:
        return specs
    return [s for s in specs if s.name in BASE or s.name in loaded]


def search(specs: list[ToolSpec], query: str, limit: int = 12, schemas: bool = False, mode: str = 'bm25') -> list[CapabilityEntry]:
    if len(query) > 500: raise ValueError('Tool search query exceeds 500 characters')
    if mode not in ('bm25','regex'): raise ValueError('Unknown tool search mode')
    words = set(re.findall(r'[\w-]+', query.lower().replace('_',' ')))
    documents = [Counter(re.findall(r'[\w-]+',(spec.name.replace('_',' ') + ' ' + spec.description).lower())) for spec in specs]
    average = sum(sum(doc.values()) for doc in documents) / max(1,len(documents)) or 1
    frequency = Counter(term for doc in documents for term in doc)
    pattern = None
    if mode == 'regex':
        import regex
        try: pattern = regex.compile(query,regex.IGNORECASE)
        except regex.error as exc: raise ValueError('Invalid tool search expression') from exc
    scored = []
    for spec,terms in zip(specs,documents):
        if pattern is not None:
            try: score = 1 if pattern.search(spec.name + ' ' + spec.description[:4000],timeout=0.01) else 0
            except TimeoutError as exc: raise ValueError('Tool search expression exceeded its execution limit') from exc
        else:
            score = 0.0
            for word in words:
                if word in terms:
                    count = terms[word]
                    score += math.log(1+(len(documents)-frequency[word]+0.5)/(frequency[word]+0.5)) * count * 2.2 / (count + 1.2*(0.25+0.75*sum(terms.values())/average))
            if query.strip() and query.lower() in spec.name.lower(): score += 10
        if not query.strip() or score: scored.append((score,spec))
    scored.sort(key=lambda item:(-item[0],item[1].name))
    from ..agent_plus.tools import SPECS as mission_specs
    mission_names = {s.name for s in mission_specs}
    return [CapabilityEntry(name=s.name, description=s.description,
            origin='connector' if '__' in s.name else ('mission' if s.name in mission_names else 'builtin'), needs_approval=s.needs_approval,
            parameters=s.parameters if schemas else None) for _, s in scored[:max(1, min(limit, 2000))]]


def load(sid: str, names: list[str], specs: list[ToolSpec]) -> list[CapabilityEntry]:
    catalog = {s.name: s for s in specs}
    missing = [n for n in names if n not in catalog]
    if missing:
        raise ValueError('Tools outside this agent\'s catalog: ' + ', '.join(missing))
    for name in names[:30]:
        db.execute('INSERT INTO agent_tool_loads(session_id,name,loaded_at) VALUES(?,?,?) ON CONFLICT(session_id,name) DO UPDATE SET loaded_at=excluded.loaded_at', (sid, name, db.now_iso()))
    retained = {row['name'] for row in db.query('SELECT name FROM agent_tool_loads WHERE session_id=? ORDER BY loaded_at DESC,rowid DESC LIMIT 30', (sid,))}
    for row in db.query('SELECT name FROM agent_tool_loads WHERE session_id=?', (sid,)):
        if row['name'] not in retained:
            db.execute('DELETE FROM agent_tool_loads WHERE session_id=? AND name=?', (sid, row['name']))
    return [CapabilityEntry(name=n, description=catalog[n].description, origin='connector' if '__' in n else 'builtin',
            needs_approval=catalog[n].needs_approval, parameters=catalog[n].parameters) for n in names[:30]]


def catalog(sid: str) -> list[ToolSpec]:
    from ..agent import profiles, tools
    from . import documents
    specs = [s for s in tools.all_specs() if not s.name.startswith("document__") or documents.owned(sid, s.name)]
    profile = profiles.resolve(sid)
    return profile.tools(specs) if profile else specs


def discovery_guide(specs: list[ToolSpec]) -> str:
    """Describe only the current session's permitted catalog, including deferred tools."""
    names = sorted({spec.name for spec in specs})
    return (
        "\n## Tool discovery\n"
        "The function schemas shown to you are a starter set, not the full catalog. "
        "Available tool names for this session: " + ", ".join(names) + ".\n"
        "If a listed tool has no visible schema, call load_tools with its exact name, then call it using the "
        "returned schema. For an unfamiliar task, call search_tools with a short task description, then "
        "load_tools with the matching names. Never use skill_read to list tools or invent a skill named tools. "
        "If search has no results, rephrase or use an empty query to browse before concluding a tool is absent. "
        "Use actual function tool calls; never print a simulated [Tool call ...] transcript. "
        "A tool's presence does not mean its model, credentials, workspace or external service is configured. "
        "For current time use world_time; a date in this prompt is not a live clock reading. "
        "For installed models use list_models; do not infer installation from generation tools or examples. "
        "Never claim a tool was called or a clock, file, or system was inspected without its actual result.\n"
    )
