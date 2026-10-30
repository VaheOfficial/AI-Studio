"""Structured repository operations and conversation-owned Git worktrees."""
from __future__ import annotations
import asyncio
import json
import uuid
from pathlib import Path
from .. import config, db
from ..agent.types import ToolFailure, ToolOutcome, ToolSpec
from ..osenv import NO_WINDOW
from ..proc import kill_tree
from ..workspace import files, state
from .tools import obj, S

READ={'status','diff','history','list_worktrees'}
SPECS=[ToolSpec('git_workspace','Inspect repository state, diffs and history; stage exact paths, commit, or manage conversation-owned worktrees outside the project folder. Worktree removal refuses uncommitted changes. No push or merge is performed.',
    obj({'action':{'type':'string','enum':sorted(READ|{'stage','commit','create_worktree','remove_worktree'})},
         'paths':{'type':'array','items':S,'maxItems':100},'message':S,'branch':S,'ref':S,'worktree_id':S,
         'staged':{'type':'boolean'},'limit':{'type':'integer','minimum':1,'maximum':100}},['action']),
    asks_like=lambda a:None if a['action'] in READ else 'run_command')]


def init():
    db.execute('CREATE TABLE IF NOT EXISTS agent_git_worktrees (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, repository TEXT NOT NULL, path TEXT NOT NULL, branch TEXT NOT NULL, created_at TEXT NOT NULL)')


async def git(root,*args):
    proc=await asyncio.create_subprocess_exec('git','-c','core.fsmonitor=false','-C',str(root),*args,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,creationflags=NO_WINDOW)
    async def read(stream):
        chunks=[];size=0
        while chunk:=await stream.read(16384):
            size+=len(chunk)
            if size>2*1024*1024: raise ToolFailure('Git output exceeds 2 MiB; narrow the requested paths')
            chunks.append(chunk)
        return b''.join(chunks)
    try:
        async with asyncio.timeout(60):
            stdout,stderr=await asyncio.gather(read(proc.stdout),read(proc.stderr));await proc.wait()
        if proc.returncode: raise ToolFailure(stderr.decode(errors='replace')[:4000] or f'Git exited {proc.returncode}')
        return stdout.decode('utf-8',errors='replace')
    finally:
        if proc.returncode is None: await asyncio.to_thread(kill_tree,proc.pid);await proc.wait()


async def invoke(a,ctx):
    root=state.require_root(ctx.session_id).resolve()
    top=Path((await git(root,'rev-parse','--show-toplevel')).strip()).resolve()
    if top!=root: raise ToolFailure('Choose the repository root as the conversation workspace')
    action=a['action'];paths=[]
    for path in a.get('paths',[]):
        resolved=files.resolve(root,path)
        paths.append(resolved.relative_to(root).as_posix())
    if action=='status': result=await git(root,'status','--porcelain=v1','--branch')
    elif action=='diff': result=await git(root,'diff','--no-ext-diff','--no-textconv',*(['--cached'] if a.get('staged') else []),'--',*paths)
    elif action=='history': result=await git(root,'log','--oneline','-n',str(a.get('limit',20)),'--',*paths)
    elif action=='stage':
        if not paths: raise ToolFailure('Supply explicit paths to stage')
        result=await git(root,'add','--',*paths)
    elif action=='commit':
        if not a.get('message') or len(a['message'])>8000: raise ToolFailure('Supply a bounded commit message')
        result=await git(root,'commit','-m',a['message'])
    elif action=='list_worktrees':
        result=json.dumps([dict(row) for row in db.query('SELECT * FROM agent_git_worktrees WHERE session_id=? AND repository=?',(ctx.session_id,str(root)))])
    elif action=='create_worktree':
        branch=a.get('branch','');ref=a.get('ref','HEAD')
        if not branch or branch.startswith('-') or ref.startswith('-'): raise ToolFailure('Supply an explicit valid branch name and revision')
        await git(root,'check-ref-format','--branch',branch)
        key=uuid.uuid4().hex[:16];directory=config.WORKTREES_DIR/ctx.session_id
        if root==directory.resolve() or root in directory.resolve().parents:
            raise ToolFailure('Managed worktree storage must be outside the source repository')
        directory.mkdir(parents=True,exist_ok=True)
        path=(directory/key).resolve()
        if directory.resolve() not in path.parents: raise ToolFailure('Worktree target must remain inside managed storage')
        await git(root,'worktree','add','-b',branch,str(path),ref)
        db.execute('INSERT INTO agent_git_worktrees VALUES(?,?,?,?,?,?)',(key,ctx.session_id,str(root),str(path),branch,db.now_iso()))
        result=json.dumps({'id':key,'path':str(path),'branch':branch,'repository':str(root)})
    else:
        row=db.query_one('SELECT * FROM agent_git_worktrees WHERE id=? AND session_id=? AND repository=?',(a.get('worktree_id'),ctx.session_id,str(root)))
        if not row: raise ToolFailure('Worktree is not owned by this conversation')
        path=Path(row['path']).resolve();managed=(config.WORKTREES_DIR/ctx.session_id).resolve()
        if managed not in path.parents: raise ToolFailure('Worktree path is outside managed storage')
        result=await git(root,'worktree','remove',str(path))
        db.execute('DELETE FROM agent_git_worktrees WHERE id=?',(row['id'],))
    return ToolOutcome(True,result or 'Git operation completed; inspect status before continuing.')


IMPL={'git_workspace':invoke}
