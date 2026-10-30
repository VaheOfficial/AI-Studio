"""Programmatic tool bridge: framed JSON requests over a private process pipe."""
from __future__ import annotations
import contextlib
import io
import json
import sys


class Log(io.StringIO):
    def write(self, text):
        super().write(text[:max(0, 16000 - self.tell())])
        return len(text)


def main():
    source, sink = sys.stdin, sys.stdout
    request = json.loads(source.readline())
    log = Log()
    class Tools:
        def call(self, name, args=None, **kwargs):
            payload = {'type': 'call', 'name': name, 'args': args if args is not None else kwargs}
            sink.write(json.dumps(payload, allow_nan=False) + '\n'); sink.flush()
            answer = json.loads(source.readline())
            if not answer['ok']:
                raise RuntimeError(answer['output'])
            try:
                return json.loads(answer['output'])
            except ValueError:
                return answer['output']
        def __getattr__(self, name):
            return lambda **kwargs: self.call(name, kwargs)
    try:
        namespace = {'__name__': 'tool_script', 'tools': Tools(), 'inputs': request.get('inputs', {})}
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            exec(compile(request['code'], '<tool-script>', 'exec'), namespace)
        result = {'type': 'result', 'ok': True, 'value': namespace.get('result'), 'log': log.getvalue()}
        encoded = json.dumps(result, allow_nan=False)
    except Exception as exc:
        encoded = json.dumps({'type': 'result', 'ok': False, 'error': f'{type(exc).__name__}: {exc}', 'log': log.getvalue()})
    sink.write(encoded + '\n'); sink.flush()


if __name__ == '__main__':
    main()
