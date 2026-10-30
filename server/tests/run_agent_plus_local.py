"""A live, zero-paid-inference acceptance run using the installed Qwen 27B.

Uses temporary mission storage; native runtime binaries and weights are reused, never copied.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import agent_plus, config, connectors, db, llamacpp, memories, openrouter_usage
from studio.agent.loop import AgentService
from studio.agent.providers.local_chat import LlamaCppProvider
from studio.agent import tools as agent_tools, web_tools
from studio.agent.python_tools import SPECS as PYTHON_SPECS
from studio.agent_plus import store
from studio.agent_plus.controller import controller
from studio.routes import agent_plus as routes
from studio.schemas_agent_plus import AgentPlusCreate
from studio.workspace import state

MODEL = 'qwen3.8-27b-uncensored-hauhaucs-aggressive-mtp-gguf-q4-k'
EXPECTED = [
    {'rows': [{'id': 'A', 'currency': 'USD', 'amount': '1234.50', 'date': '2026-10-01'},
              {'id': 'B', 'currency': 'USD', 'amount': '-75.20', 'date': '2026-10-02'},
              {'id': 'C', 'currency': 'EUR', 'amount': '1234.56', 'date': '2026-10-03'}],
     'totals': {'USD': '1159.30', 'EUR': '1234.56'}},
    {'rows': [{'id': 'D', 'currency': 'EUR', 'amount': '-12.34', 'date': '2026-10-04'},
              {'id': 'E', 'currency': 'EUR', 'amount': '45.67', 'date': '2026-10-05'}], 'totals': {'EUR': '33.33'}}
]
TASK = '''Build and use a missing reusable invoice normalization tool via research_tool. Do not solve the task by run_python or a command.
The tool accepts {"rows":[{"id":"...","currency":"USD or EUR","amount":"...","date":"..."}]} and returns
{"rows":[{"id":"...","currency":"USD or EUR","amount":"two-decimal string","date":"YYYY-MM-DD"}],"totals":{"currency":"two-decimal string"}}.
USD amounts use comma thousands and dot decimals. EUR amounts use dot thousands and comma decimals, optionally a euro symbol. Parentheses mean negative. ISO dates stay ISO; slash dates are DD/MM/YYYY. Preserve input row order, sum with Decimal, reject unsupported currencies or impossible dates with ValueError.
Research official Python csv, decimal and datetime documentation. Before delegation define fixed acceptance cases including normal USD/EUR, negative amounts and date conversion; add distinct edge cases in the researcher. Invoke the validated tool on BOTH batches below in this same chat, inspect outputs, and record evidence. Save a final report.json in your invocation output folder as part of execute(args). Inspect that file with observe_artifact. The final report must be the second batch result. Plan and complete delivery/validation work and the mission using real receipts.
Batch 1: [{"id":"A","currency":"USD","amount":"1,234.50","date":"2026-10-01"},{"id":"B","currency":"USD","amount":"(75.20)","date":"02/10/2026"},{"id":"C","currency":"EUR","amount":"€1.234,56","date":"03/10/2026"}]. Expected totals USD=1159.30, EUR=1234.56.
Batch 2: [{"id":"D","currency":"EUR","amount":"(12,34)","date":"04/10/2026"},{"id":"E","currency":"EUR","amount":"45,67","date":"2026-10-05"}]. Expected total EUR=33.33.
Only fetch_url/read_skill and Agent+ tools are available for this acceptance run. Keep all generated files in the invocation folder; use relative report.json. Source URLs: https://docs.python.org/3/library/decimal.html and https://docs.python.org/3/library/datetime.html .'''


async def main() -> None:
    real_db = config.DB_PATH
    with sqlite3.connect(f'file:{real_db.as_posix()}?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT * FROM installed_models WHERE id=?', (MODEL,)).fetchone()
        if row is None:
            raise RuntimeError('Installed Qwen 27B entry not found')
        record = dict(row)
    if not llamacpp.installed():
        raise RuntimeError('Native llama.cpp runtime is not installed')
    with tempfile.TemporaryDirectory(prefix='agentplus-local-') as tmp:
        root = Path(tmp)
        original_body = LlamaCppProvider._body
        def acceptance_body(self, *args, **kwargs):
            body = original_body(self, *args, **kwargs)
            # Exercise real inference with concise output; no response content is scripted.
            body.update(chat_template_kwargs={'enable_thinking': False}, reasoning_effort='none', max_tokens=5000)
            return body
        patches = [patch.object(config, 'DATA_DIR', root), patch.object(config, 'DB_PATH', root / 'studio.db'),
                   patch.object(config, 'CACHE_DIR', root / 'cache'), patch.object(config, 'OUTPUTS_DIR', root / 'outputs'),
                   patch.object(LlamaCppProvider, '_body', acceptance_body),
                   patch('studio.agent.tools.all_specs', return_value=[*web_tools.SPECS, *[s for s in PYTHON_SPECS if s.name == 'read_skill']])]
        for p in patches:
            p.start()
        db.init()
        state.init()
        memories.init()
        connectors.init()
        openrouter_usage.init()
        agent_plus.init()
        fields = list(record)
        record['status'] = 'ready'
        db.execute('INSERT INTO installed_models(' + ','.join(fields) + ') VALUES(' + ','.join('?' for _ in fields) + ')',
                   [record[f] for f in fields])
        for key, value in {'agent_auto_approve': ['run_python'], 'llamacpp_ctx_size': 16384,
                           'llamacpp_kv_cache': 'q8_0', 'agent_completion_check': 'never'}.items():
            db.set_setting_value(key, value)
        service = AgentService()
        controller.start(service)
        sid = None
        destination = real_db.parent / 'agentplus-verification'
        destination.mkdir(exist_ok=True)
        try:
            d = await routes.create(AgentPlusCreate(model='llamacpp:' + MODEL, objective=TASK,
                criteria=['Both batch results match the specified Decimal totals and normalized dates',
                          'The same validated chat tool is reused for both batches',
                          'The final report.json contains batch 2 and has been inspected'], max_requests=60))
            sid = d.mission.session_id
            m = store.get(sid)
            m.status = 'running'
            store.save(m)
            print('Local acceptance run started:', sid, flush=True)
            turn = service.start(db.get_session(sid), TASK)
            last = 0
            async with asyncio.timeout(25 * 60):
                while True:
                    for e in store.detail(sid).events:
                        if e.seq > last:
                            print(e.kind + ': ' + e.text[:320], flush=True)
                            last = e.seq
                    status = store.get(sid).status
                    if status != 'running' and not service.busy(sid):
                        break
                    await asyncio.sleep(3)
            d = store.detail(sid)
            reports = list((root / 'outputs' / 'agentplus' / sid).glob('report.json'))
            report = json.loads(reports[0].read_text()) if reports else None
            uses = [a for a in d.actions if a.name == 'invoke_chat_tool' and a.status == 'succeeded']
            values = [json.loads(a.output)['value'] for a in uses]
            passed = (d.mission.status == 'completed' and all(expected in values for expected in EXPECTED)
                      and len({a.args['tool_id'] for a in uses}) == 1 and report == EXPECTED[1])
            print(json.dumps({'status': d.mission.status, 'reason': d.mission.reason, 'requests': d.mission.requests,
                'tools': [{'name': t.name, 'status': t.status, 'passed_checks': sum(r['passed'] for r in t.results),
                           'total_checks': len(t.results)} for t in d.tools],
                'successful_uses': len(uses), 'report': report, 'passed': bool(passed)}, ensure_ascii=False, indent=2), flush=True)
            # Retain only the reviewable run record and final output in the existing ignored verification area.
            record_json = d.model_dump_json(indent=2)
            (destination / 'local-run.json').write_text(record_json, encoding='utf-8')
            (destination / f'run-{sid}.json').write_text(record_json, encoding='utf-8')
            if report:
                (destination / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            if not passed:
                raise RuntimeError('Local Agent+ acceptance run did not meet all checks')
        finally:
            await controller.shutdown()
            await service.shutdown()
            if sid:
                (destination / f'run-{sid}.json').write_text(store.detail(sid).model_dump_json(indent=2), encoding='utf-8')
            await asyncio.to_thread(llamacpp.server.stop)
            if db._conn:
                db._conn.close()
                db._conn = None
            for p in reversed(patches):
                p.stop()


if __name__ == '__main__':
    asyncio.run(main())
