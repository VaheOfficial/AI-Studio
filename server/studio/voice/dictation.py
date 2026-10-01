"""Live dictation over WebSocket ``/api/voice/dictate`` with an installed faster-whisper model.

Client -> server: binary frames of 16 kHz mono int16 PCM; the text frame ``"EOF"`` ends input (the socket
stays open until the summary). Server -> client: ``status`` (loading/ready), ``partial`` (the current
utterance so far, re-decoded about once a second), ``final`` with ``final_kind="utterance"`` when ~0.7 s
of silence (or 25 s of speech) closes an utterance, and a ``final`` ``"summary"`` with the joined text at EOF.
Endpointing is an RMS gate like VoiceStudio's offline-model path; decoding is greedy on a rolling window.
"""

from __future__ import annotations

import asyncio
import base64
import math
import time
from array import array
from collections import deque

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..models import ModelError, models
from ..runtimes import WorkerError, runtimes
from ..schemas import InstalledModel
from ..schemas_voice import DictationError, DictationFinal, DictationPartial, DictationStatus
from . import profiles

SAMPLE_RATE = 16000
_BYTES_PER_S = SAMPLE_RATE * 2
_PARTIAL_EVERY_S = 1.0
_SILENCE_RMS = 0.012
_END_SILENCE_S = 0.7
_MIN_UTTERANCE_S = 0.4
_MAX_UTTERANCE_S = 25.0
_LEAD_KEEP_S = 0.5  # audio kept before speech starts, so onsets aren't clipped


def _rms(frame: bytes) -> float:
    samples = array("h", frame[: len(frame) - len(frame) % 2])
    if not samples:
        return 0.0
    return math.sqrt(sum(s * s for s in samples) / len(samples)) / 32768.0


class _Session:
    def __init__(self, ws: WebSocket, model: InstalledModel, language: str | None) -> None:
        self.ws = ws
        self.model = model
        self.language = language
        self.buf = bytearray()
        self.silence_s = 0.0
        self.speech = False
        self.last_partial = 0.0
        self.partial_len = 0
        self.finals: list[str] = []
        self.total_s = 0.0
        # Filled by the receiver while decoding runs, so the socket keeps being read (and pinged)
        self.frames: deque[bytes] = deque()
        self.eof = False
        self.closed = False
        self.wake = asyncio.Event()

    async def send(self, msg: BaseModel) -> None:
        await self.ws.send_json(msg.model_dump())

    async def _decode(self, pcm: bytes) -> str:
        result = await asyncio.to_thread(
            runtimes.request, self.model.runtime, "POST", "/transcribe",
            {"pcm16": base64.b64encode(pcm).decode(), "language": self.language}, 120)
        return str(result.get("text") or "").strip()

    async def receive(self) -> None:
        try:
            while True:
                msg = await self.ws.receive()
                if msg["type"] == "websocket.disconnect":
                    self.closed = True
                    return
                data = msg.get("bytes")
                if data:
                    self.frames.append(data)
                    self.wake.set()
                elif data is not None or msg.get("text") == "EOF":
                    self.eof = True
                    return
        finally:
            self.wake.set()

    async def process(self) -> None:
        """Feed queued frames in order; returns after the summary (EOF) or when the client left."""
        while not self.closed:
            await self.wake.wait()
            self.wake.clear()
            while self.frames and not self.closed:
                await self.feed(self.frames.popleft())
            if self.eof and not self.frames:
                await self.finish()
                return

    async def feed(self, frame: bytes) -> None:
        self.buf.extend(frame)
        seconds = len(frame) / _BYTES_PER_S
        self.total_s += seconds
        if _rms(frame) >= _SILENCE_RMS:
            self.speech, self.silence_s = True, 0.0
        else:
            self.silence_s += seconds
        if not self.speech:
            keep = int(_LEAD_KEEP_S * _BYTES_PER_S)
            del self.buf[: max(0, len(self.buf) - keep)]
            return
        length = len(self.buf) / _BYTES_PER_S
        if (self.silence_s >= _END_SILENCE_S and length >= _MIN_UTTERANCE_S) or length >= _MAX_UTTERANCE_S:
            await self.commit()
        elif (not self.frames and time.monotonic() - self.last_partial >= _PARTIAL_EVERY_S
              and len(self.buf) > self.partial_len):
            self.last_partial = time.monotonic()
            self.partial_len = len(self.buf)
            text = await self._decode(bytes(self.buf))
            if text:
                await self.send(DictationPartial(text=text))

    async def commit(self) -> None:
        pcm = bytes(self.buf)
        self.buf.clear()
        self.speech, self.silence_s, self.partial_len = False, 0.0, 0
        if len(pcm) / _BYTES_PER_S < _MIN_UTTERANCE_S:
            return
        text = await self._decode(pcm)
        if text:
            self.finals.append(text)
            seconds = round(len(pcm) / _BYTES_PER_S, 2)
            await self.send(DictationFinal(text=text, final_kind="utterance", duration_s=seconds))

    async def finish(self) -> None:
        if self.speech:
            await self.commit()
        summary = " ".join(self.finals)
        await self.send(DictationFinal(text=summary, final_kind="summary", duration_s=round(self.total_s, 2)))


async def run(ws: WebSocket, model_id: str | None, language: str | None) -> None:
    await ws.accept()
    try:
        model = models.get(model_id) if model_id else profiles.stt_model()
        if model is None or model.kind != "stt" or model.runtime != "faster-whisper":
            await ws.send_json(DictationError(message="Live dictation needs a faster-whisper model — install "
                                                      "Whisper small from Models → Catalog.").model_dump())
            await ws.close()
            return
        await ws.send_json(DictationStatus(stage="loading", model_id=model.id).model_dump())
        await asyncio.to_thread(models.ensure_loaded, model.id)
        session = _Session(ws, model, language)
        await session.send(DictationStatus(stage="ready", model_id=model.id))
        receiver = asyncio.create_task(session.receive())
        try:
            await session.process()
        finally:
            receiver.cancel()
        if session.eof:
            await ws.close()
    except WebSocketDisconnect:
        return
    except (ModelError, WorkerError) as exc:
        await ws.send_json(DictationError(message=str(exc)).model_dump())
        await ws.close()
