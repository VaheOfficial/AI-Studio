"""Local document retrieval with source hashes, page/line references and FTS ranking."""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
import math
from urllib.parse import urlsplit
from pathlib import Path
import uuid
import zipfile
from xml.etree import ElementTree
from .. import config, db
from ..agent.types import ToolFailure, ToolOutcome, ToolSpec
from ..workspace import files, state
from . import store
from .tools import obj, S

SPECS = [
    ToolSpec('index_documents', 'Index workspace documents with source citations. Optional embedding_model uses an already installed local Ollama embedding model for semantic retrieval.', obj({'collection': S, 'paths': {'type': 'array', 'items': S, 'maxItems': 100}, 'embedding_model': S}, ['collection', 'paths']), asks_like=lambda a: 'run_python' if a.get('embedding_model') else None),
    ToolSpec('search_documents', 'Retrieve cited passages by lexical or local semantic similarity. Semantic mode requires a collection indexed with embeddings. Changed source files are marked stale.', obj({'query': S, 'collection': S, 'limit': {'type': 'integer'}, 'mode': {'type':'string','enum':['lexical','semantic']}}, ['query'])),
]


def init():
    db.execute('CREATE TABLE IF NOT EXISTS agent_documents (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, collection TEXT NOT NULL, path TEXT NOT NULL, source_hash TEXT NOT NULL, locator TEXT NOT NULL, content TEXT NOT NULL)')
    db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS agent_documents_fts USING fts5(id UNINDEXED,content)")
    db.execute('CREATE TABLE IF NOT EXISTS agent_document_vectors (id TEXT PRIMARY KEY, model TEXT NOT NULL, data TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS agent_collection_models (workspace TEXT NOT NULL, collection TEXT NOT NULL, model TEXT NOT NULL, PRIMARY KEY(workspace,collection))')


def embed(model, texts):
    from ..localhttp import client
    if urlsplit(config.OLLAMA_URL).hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('Semantic retrieval requires a local Ollama endpoint')
    response = client.post(config.OLLAMA_URL.rstrip('/') + '/api/embed', json={'model':model.removeprefix('ollama:'),'input':texts,'truncate':False}, timeout=120)
    response.raise_for_status()
    vectors = response.json().get('embeddings')
    if not isinstance(vectors,list) or len(vectors) != len(texts):
        raise ValueError('Embedding runtime returned the wrong number of vectors')
    for vector in vectors:
        if not isinstance(vector,list) or not 1 <= len(vector) <= 8192 or any(isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value) for value in vector):
            raise ValueError('Invalid embedding vector')
    if len({len(vector) for vector in vectors}) > 1:
        raise ValueError('Embedding dimensions are inconsistent')
    return vectors


def passages(path):
    if path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('Document exceeds the 32 MiB limit: ' + path.name)
    if path.suffix.lower() == '.pdf':
        from pypdf import PdfReader
        for i, page in enumerate(PdfReader(path).pages):
            text = page.extract_text() or ''
            for start in range(0, len(text), 4000):
                yield f'page {i+1}, character {start+1}', text[start:start+4500]
    else:
        if path.suffix.lower() == '.docx':
            with zipfile.ZipFile(path) as archive:
                entry = archive.getinfo('word/document.xml')
                if entry.file_size > 16 * 1024 * 1024:
                    raise ValueError('DOCX text exceeds the extraction limit')
                tree = ElementTree.fromstring(archive.read(entry))
            text = '\n'.join(''.join(p.itertext()) for p in tree.iter() if p.tag.endswith('}p'))
        elif path.suffix.lower() in {'.txt', '.md', '.csv', '.json', '.jsonl', '.log', '.py', '.ts', '.tsx', '.html'}:
            text = path.read_text(encoding='utf-8', errors='replace')
        else:
            raise ValueError('Unsupported document format: ' + path.suffix)
        lines = text.splitlines()
        for start in range(0, len(lines), 50):
            yield f'lines {start+1}-{min(len(lines),start+60)}', '\n'.join(lines[start:start+60])[:8000]


def index(sid, collection, paths, embedding_model=None):
    from ..agent_plus.store import atomic
    root = state.require_root(sid)
    staged = []
    for name in paths[:100]:
        path = files.resolve(root, name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.stat().st_size <= 32 * 1024 * 1024 else None
        if digest is None:
            raise ValueError('Document exceeds size limit')
        chunks = []
        for passage in passages(path):
            if len(chunks) >= 5000:
                raise ValueError('Document exceeds the passage limit')
            chunks.append(passage)
        staged.append((str(path), digest, chunks))
        if sum(len(item[2]) for item in staged) > 5000: raise ValueError('Index at most 5,000 passages per request')
    model_row = db.query_one('SELECT model FROM agent_collection_models WHERE workspace=? AND collection=?', (str(root),collection))
    if model_row and embedding_model != model_row['model']:
        raise ValueError('Use the existing collection embedding model, or index a new collection')
    if embedding_model and not model_row:
        existing = {row['path'] for row in db.query('SELECT DISTINCT path FROM agent_documents WHERE workspace=? AND collection=?',(str(root),collection))}
        if existing - {path for path,_,_ in staged}: raise ValueError('Adding embeddings requires reindexing every existing document in the collection')
    vectors = []
    if embedding_model:
        texts = [content for _,_,chunks in staged for _,content in chunks]
        for start in range(0,len(texts),32):
            vectors.extend(embed(embedding_model,texts[start:start+32]))
    if len({len(vector) for vector in vectors}) > 1: raise ValueError('Embedding dimensions changed between batches')
    if sum(len(json.dumps(vector)) for vector in vectors) > 16*1024*1024: raise ValueError('Embedding request exceeds the 16 MiB vector limit; index fewer passages')
    vector_index = 0
    with atomic():
        for path, digest, chunks in staged:
            old = db.query('SELECT id FROM agent_documents WHERE workspace=? AND collection=? AND path=?', (str(root), collection, path))
            for row in old:
                db.execute('DELETE FROM agent_documents_fts WHERE id=?', (row['id'],))
                db.execute('DELETE FROM agent_document_vectors WHERE id=?', (row['id'],))
            db.execute('DELETE FROM agent_documents WHERE workspace=? AND collection=? AND path=?', (str(root), collection, path))
            for locator, content in chunks:
                key = uuid.uuid4().hex
                db.execute('INSERT INTO agent_documents VALUES(?,?,?,?,?,?,?)', (key, str(root), collection, path, digest, locator, content))
                db.execute('INSERT INTO agent_documents_fts VALUES(?,?)', (key, content))
                if embedding_model:
                    db.execute('INSERT INTO agent_document_vectors VALUES(?,?,?)', (key,embedding_model,json.dumps(vectors[vector_index])))
                    vector_index += 1
        if embedding_model:
            db.execute('INSERT INTO agent_collection_models VALUES(?,?,?) ON CONFLICT(workspace,collection) DO UPDATE SET model=excluded.model', (str(root),collection,embedding_model))
    store.notify('collections', sid)
    return {'collection': collection, 'documents': len(staged), 'passages': sum(len(v[2]) for v in staged)}


def search(sid, query, collection=None, limit=8, mode='lexical'):
    root = str(state.require_root(sid))
    if mode == 'semantic':
        model = db.query_one('SELECT model FROM agent_collection_models WHERE workspace=? AND collection=?', (root,collection))
        if not model:
            raise ValueError('Semantic search needs a collection indexed with an installed embedding model')
        query_vector = embed(model['model'], [query])[0]
        norm = math.sqrt(sum(value*value for value in query_vector))
        if norm == 0:
            raise ValueError('Query embedding has zero magnitude')
        candidates = db.query('SELECT d.*,v.data AS vector FROM agent_documents d JOIN agent_document_vectors v ON v.id=d.id WHERE d.workspace=? AND d.collection=? AND v.model=?', (root,collection,model['model']))
        ranked = []
        for candidate in candidates:
            vector = json.loads(candidate['vector'])
            if len(vector) != len(query_vector):
                raise ValueError('Embedding dimensions changed; rebuild this collection')
            magnitude = math.sqrt(sum(value*value for value in vector))
            similarity = sum(x*y for x,y in zip(vector,query_vector)) / (norm*magnitude) if magnitude else 0
            ranked.append((similarity,candidate))
        results = [dict(row, similarity=score) for score,row in sorted(ranked,key=lambda pair:pair[0],reverse=True)[:max(1,min(limit,30))]]
        return cited(results)
    words = re.findall(r'[\w-]{2,}', query)[:30]
    if not words:
        return []
    expression = ' OR '.join('"' + word.replace('"', '""') + '"' for word in words)
    rows = db.query('''SELECT d.*,bm25(agent_documents_fts) AS rank FROM agent_documents_fts
        JOIN agent_documents d ON d.id=agent_documents_fts.id WHERE agent_documents_fts MATCH ?
        AND d.workspace=? AND (? IS NULL OR d.collection=?) ORDER BY rank LIMIT ?''', (expression, root, collection, collection, max(1,min(limit,30))))
    return cited(rows)


def cited(rows):
    hashes = {}
    results = []
    for row in rows:
        if row['path'] not in hashes:
            try:
                path = Path(row['path']).resolve()
                if Path(row['workspace']).resolve() not in path.parents: raise OSError('Source moved outside its workspace')
                hashes[row['path']] = hashlib.sha256(path.read_bytes()).hexdigest() if path.stat().st_size <= 32*1024*1024 else None
            except OSError:
                hashes[row['path']] = None
        results.append({'text':row['content'],'collection':row['collection'],'stale':hashes[row['path']] != row['source_hash'],
                        'citation':{'path':row['path'],'location':row['locator'],'source_hash':row['source_hash']},
                        **({'similarity':row['similarity']} if 'similarity' in row.keys() else {})})
    return results


async def index_tool(a, ctx):
    return ToolOutcome(True, json.dumps(await asyncio.to_thread(index, ctx.session_id, a['collection'], a['paths'], a.get('embedding_model'))))


async def search_tool(a, ctx):
    return ToolOutcome(True, json.dumps(await asyncio.to_thread(search, ctx.session_id, a['query'], a.get('collection'), a.get('limit',8), a.get('mode','lexical')), ensure_ascii=False))


IMPL = {'index_documents': index_tool, 'search_documents': search_tool}
