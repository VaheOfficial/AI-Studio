"""One pooled HTTP client for services on this machine (Ollama, LM Studio, llama-server, runtime workers).

A one-off ``httpx.get`` builds a new client — and with it a TLS context that loads the CA bundle from disk — on every
call, even for plain ``http://127.0.0.1`` URLs; on this studio's USB data drive that cost ~0.5 s per request, which
made every WebSocket ``hello`` and system tick slow. The client is thread-safe; pass per-call timeouts.

``tls`` is the same verified TLS context built once: pass it as ``verify=`` to short-lived ``AsyncClient``s (which
can't be shared across event loops) so they skip the per-client CA load too."""

from __future__ import annotations

import httpx

tls = httpx.create_ssl_context()
client = httpx.Client(timeout=10, trust_env=False, verify=tls)
