# Third-party notices

Grom AI Studio is licensed under the GNU Affero General Public License v3.0 only (see [`LICENSE`](LICENSE)). Parts of it
are derived from, or include, the projects below. Their notices are reproduced here as their licenses require.
Files derived from another project say so in their header ("ported from …"); those files were modified to fit
this codebase.

Model weights, tokenizers and other assets downloaded at run time keep their own terms; nothing here grants or
summarizes rights under them. Libraries installed as dependencies are covered by their own packages' licenses.

## VoiceStudio — AGPL-3.0-only

<https://github.com/debpalash/VoiceStudio>
Copyright 2024-present Palash Debnath and VoiceStudio contributors.

Dubbing, audiobook, voice text processing (normalization, pronunciation, archetypes, voice description, chunked
speech) and the dub editor and timeline are ported from VoiceStudio: `server/studio/dub/`,
`server/studio/audiobook/`, parts of `server/studio/voice/` and `server/studio/media.py`,
`server/workers/dub_worker.py`, `server/workers/speech_chunks.py`, `apps/studio/src/features/dub/` and
`packages/ui/src/components/Timeline/`. VoiceStudio is licensed under the GNU Affero General Public License v3.0;
the full text is in [`LICENSE`](LICENSE).

## voicebox — MIT

<https://github.com/jamiepine/voicebox>
Copyright (c) voicebox contributors.

`server/workers/speech_chunks.py` descends, through VoiceStudio, from voicebox's chunked text-to-speech. Licensed
under the MIT License (text below).

## OpenMuse — MIT

<https://github.com/CopilotKit/openmuse>
Copyright (c) 2026 OpenMuse contributors.

The agent workspace (per-chat folder, terminals, file tools, browser, background tasks, tool displays, follow-up
queue) is ported from OpenMuse: `server/studio/workspace/`, `apps/studio/src/features/chat/workspace/` and parts
of `apps/studio/src/features/chat/`. Licensed under the MIT License:

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
> documentation files (the "Software"), to deal in the Software without restriction, including without limitation
> the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and
> to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions
> of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
> THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
> AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
> CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
> IN THE SOFTWARE.

## OmniVoice — Apache-2.0

Copyright 2026 Xiaomi Corp. (authors: Han Zhu).

`server/workers/omnivoice/` is the inference part of the OmniVoice package (k2-fsa/OmniVoice), taken from the copy
bundled with VoiceStudio. Only the inference modules are kept and the package `__init__.py` was reduced to match;
the other files are unchanged and keep their original headers. Licensed under the Apache License, Version 2.0;
the full text is in [`server/workers/omnivoice/LICENSE`](server/workers/omnivoice/LICENSE).

## ComfyUI — GPL-3.0

<https://github.com/comfyanonymous/ComfyUI>

The latent-to-RGB preview factors in `server/workers/latent_preview.py` are taken from ComfyUI
(`comfy/latent_formats.py`), which is licensed under the GNU General Public License v3.0.
