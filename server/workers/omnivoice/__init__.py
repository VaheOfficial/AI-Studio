# Copyright    2026  Xiaomi Corp.        (authors:  Han Zhu)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""OmniVoice inference package (k2-fsa/OmniVoice), vendored from VoiceStudio's ``omnivoice/``.

Only the inference modules are kept: ``models/omnivoice.py`` and the ``utils`` it imports.
``utils/lang_map.py`` and ``utils/voice_design.py`` are stdlib-only; the Studio server loads them
by file path for the language list and the voice-design vocabulary, so they stay the single source
of truth for both processes.
"""

import warnings

warnings.filterwarnings("ignore", module="torchaudio")
warnings.filterwarnings("ignore", category=SyntaxWarning, message="invalid escape sequence", module="pydub.utils")
