"""Capability coverage derived from tools, installed runtimes and configured connections."""
from __future__ import annotations
import os
import shutil
import sys
from pathlib import Path
from .. import db, media, osenv, settings
from ..runtimes import envs
from ..schemas_agents import CapabilityFamily
from . import documents, services, store, model_checks, monitors, channels


def browser_installed():
    if shutil.which('msedge') or shutil.which('google-chrome') or shutil.which('chromium') or shutil.which('chromium-browser'):
        return True
    if sys.platform == 'win32':
        if any((Path(os.environ.get(key, '')) / suffix).is_file()
                   for key in ('PROGRAMFILES', 'PROGRAMFILES(X86)', 'LOCALAPPDATA')
                   for suffix in ('Microsoft/Edge/Application/msedge.exe', 'Google/Chrome/Application/chrome.exe')): return True
    if sys.platform == 'darwin' and Path('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome').is_file():
        return True
    roots = [Path(os.environ['PLAYWRIGHT_BROWSERS_PATH'])] if os.environ.get('PLAYWRIGHT_BROWSERS_PATH') else [
        Path.home() / 'AppData/Local/ms-playwright', Path.home() / '.cache/ms-playwright', Path.home() / 'Library/Caches/ms-playwright']
    return any(path.is_file() for root in roots for pattern in ('chromium-*/chrome-linux/chrome','chromium-*/chrome-linux64/chrome','chromium-*/chrome-win/chrome.exe','chromium-*/chrome-mac/Chromium.app/Contents/MacOS/Chromium') for path in root.glob(pattern))


def listing(sid=None):
    from ..agent import tools
    from ..agent_plus.tools import SPECS as mission_specs
    from ..connectors import manager
    catalog = {spec.name for spec in [*tools.all_specs(),*mission_specs]}
    models = db.list_installed()
    identity = store.identity(sid)
    from ..agent import inventory
    from ..workspace import state
    usable = inventory.usable_models()
    local = lambda kind: any(model.kind == kind and model.runtime != 'openrouter' for model in usable)
    root = state.get(sid).root if sid else None
    workspace_ready = bool(root and Path(root).is_dir())
    session = db.get_session(sid) if sid else None
    selected_model = session.model if session else (identity.model or settings.load().default_chat_model)
    model_check = model_checks.get(selected_model) if selected_model else None
    browser_ready = browser_installed()
    connections = [item for item in manager.list() if item.status == 'connected']
    definitions = [
      ('execution','Sequential agent and persistent missions',['start_mission','plan_work','complete_mission','resolve_action'],True,'Choose an installed tool-capable reasoning model.'),
      ('subagents','Bounded subagents',['delegate_task','delegation_status','cancel_delegation'],identity.allow_subagents,'Enable subagents in Agent settings; the parent retains ownership.'),
      ('construction','Research, build and validate missing tools',['research_tool','invoke_skill'],True,'Generated tools must pass their declared cases before reuse.'),
      ('discovery','BM25 and bounded regex tool discovery',['search_tools','load_tools'],True,'Schemas load as needed to keep small-model context manageable.'),
      ('composition','Ordered calls and local tool scripts',['execute_tools','run_tool_script'],True,'Nested actions retain normal approvals and scope.'),
      ('coding','Files, terminal, Git and local code review',['read_file','write_file','edit_file','run_command','run_python','git_workspace','review_code'],True,'Select a workspace. Commands run with local-user authority unless a container is configured. Code review requires local constrained decoding and checks source citations.'),
      ('web','Web, image, news and social research',['research_search','read_social_thread','fetch_url'],True,'Uses the local conversation browser and public search pages; account walls remain in effect.'),
      ('browser','Browser interaction and diagnostics',['browser_action','browser_navigate','browser_read'],True,'Requires installed Edge or Chrome; user takeover is respected.'),
      ('desktop','Native desktop input and screenshots',['computer_action'],osenv.desktop_backend()[0] and identity.desktop_control,osenv.desktop_backend()[1] + '; enable desktop control and review input actions. Portable backends need live OS acceptance.'),
      ('knowledge','Scoped memory and provenance',['knowledge_search','knowledge_save'],True,'Agent, conversation and workspace facts support expiry and revision checks.'),
      ('retrieval','Lexical and local semantic document collections',['index_documents','search_documents'],True,'Semantic mode needs an already installed local Ollama embedding model and a fully indexed collection.'),
      ('artifacts','Editable and versioned artifacts',['artifact_save','artifact_read'],True,'HTML previews are isolated. Stale revisions and completion evidence are invalidated.'),
      ('office-files','DOCX, XLSX, PPTX and PDF operations',['office_file','office_file_help'],envs.is_ready('python'),'The CPU document environment installs on first approved use. Formula caches need a spreadsheet engine.'),
      ('live-documents','Live Word, Excel and PowerPoint editing',sorted(name for name in catalog if name.startswith('document__')),bool(documents.list_all(sid)),'Connect a document-scoped editor. Native Office uses trusted HTTPS, Office.js and a sideloaded manifest.'),
      ('applications','MCP and HTTP application tools',sorted(name for name in catalog if '__' in name and not name.startswith('document__')),bool(connections or any(item.enabled for item in services.list_all())),'Reviewed application and specialist-service starters require configured endpoints and account permissions; broader operations come from OpenAPI or MCP.'),
      ('plugins','Native and Claude plugin import',['plugin_list','plugin_read_file'],True,'Imported hooks do not execute. New skills and connections require review.'),
      ('advisor','Optional planning advisor',['consult_advisor'],bool(identity.advisor_model),'Select an advisor. Remote advice obeys the mission spending budget.'),
      ('proactive','Scheduled and event-triggered work',['wake_schedule','notify_user'],True,'The host and computer must stay running. Sign-in registration is available in Connections.'),
      ('monitors','Read-only source watches',['monitor_status'],any(item['enabled'] for item in monitors.listing(sid)),'Configure a concrete read-only source and observation field. First read establishes a baseline; changes wake the owner.'),
      ('channels','Incoming messages and scoped replies',['channel_messages','channel_reply'],any(item.enabled and (not sid or item.session_id==sid) for item in channels.listing()),'Configure exact sender/conversation grants and a signed provider subscription on your HTTPS gateway.'),
      ('google-files','Google mail attachments and Drive transfers',['google_workspace_file'],any(item.enabled and item.base_url in ('https://gmail.googleapis.com/gmail/v1','https://www.googleapis.com/drive/v3') for item in services.list_all()),'Authorize a matching Gmail or Drive service. Replies, uploads and downloads retain ordinary approval.'),
      ('notifications','Durable inbox and independent notifications',['notify_user'],True,'Desktop delivery and encrypted browser push are opt-in. Browser push uses the browser vendor relay.'),
      ('voice','Continuous local voice conversation',['text_to_speech','transcribe'],any(model.kind=='stt' and model.runtime=='faster-whisper' for model in models) and any(model.kind=='voice' and model.runtime!='openrouter' for model in models),'Requires local Whisper and speech models. Playback mutes transcription by default; recognized-speech interruption is opt-in. Approvals use buttons; microphone/echo acceptance is still required.'),
      ('media-inspection','Video and audio inspection',['inspect_media'],bool(media.find('ffprobe') and media.find('ffmpeg')),'Install FFmpeg and FFprobe in Media tools. Samples up to 12 timestamped frames without generation.'),
      ('animation','Declarative animation directing and exact-frame export',['animation_catalog','animation_recipe','animation_project','animation_validate','animation_render','animation_prepare_voice','animation_analyze_audio'],bool(media.find('ffprobe') and media.find('ffmpeg') and browser_installed()),'Canvas and software WebGL export require FFmpeg, FFprobe and a Playwright-compatible browser. Voice preparation separately requires a configured speech model/provider.'),
      ('generation','Images, editing, video, speech and music',['generate_image','edit_image','generate_video','text_to_speech','generate_music','clone_voice','separate_audio'],any(model.kind in ('image','video','music') and model.runtime!='openrouter' for model in models),'Generation uses configured runtimes and model limits. OpenRouter remains supported; no paid calls are needed for local testing.'),
      ('utility','Calculation, weather, conversion and clocks',['calculate','get_weather','convert','world_time'],True,'Weather and exchange rates use their existing public data endpoints.'),
    ]
    readiness = {
        'execution': bool(model_check and model_check['tools']),
        'construction': bool(model_check and model_check['tools']),
        'coding': workspace_ready,
        'retrieval': workspace_ready,
        'browser': browser_ready,
        'web': browser_ready,
        'voice': local('stt') and local('voice'),
        'generation': all(local(kind) for kind in ('image', 'video', 'voice', 'music')),
    }
    result = []
    for key,name,selected,ready,requires in definitions:
        ready = readiness.get(key, ready)
        status = 'ready' if ready else 'setup'
        verified = False
        if key in ('execution', 'construction'):
            status = 'ready' if ready else ('unknown' if selected_model else 'setup')
            verified = bool(ready)
            requires += ' Run Verify tool protocol to record structured-call and result-readback evidence.'
        if key == 'desktop' and not osenv.desktop_backend()[0]: status = 'unsupported'
        if key in ('web', 'applications','channels','google-files') and ready:
            status = 'unknown'
            requires += ' Configuration is present; live access is not established by this inventory.'
        result.append(CapabilityFamily(id=key,name=name,status=status,verified=verified,
                                      tools=[tool for tool in selected if tool in catalog],requirements=requires))
    for kind, names in [('image', ['generate_image','edit_image']), ('video',['generate_video']),
                        ('voice',['text_to_speech','clone_voice']), ('stt',['transcribe']),
                        ('music',['generate_music'])]:
        result.append(CapabilityFamily(id='generation-' + kind, name=kind.capitalize() + ' models',
            status='ready' if local(kind) else 'setup', tools=[n for n in names if n in catalog],
            requirements='Requires an installed usable local ' + kind + ' model. A model listing is not an inference check.'))
    return result
