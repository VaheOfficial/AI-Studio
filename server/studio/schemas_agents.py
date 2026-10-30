"""Mirrors api/contracts/agents.ts."""
from __future__ import annotations
from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator
from .schemas import AgentSession
from .schemas_agent_plus import AgentPlusMission


class AgentIdentity(BaseModel):
    id: str
    name: str = Field(min_length=1, max_length=120)
    instructions: str = Field(default='', max_length=16000)
    model: str | None = None
    advisor_model: str | None = None
    allow_subagents: bool = True
    max_subagents: int = Field(default=2, ge=0, le=8)
    sandbox: Literal['process', 'container'] = 'process'
    desktop_control: bool = False
    created_at: str
    updated_at: str


class IdentityPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    instructions: str | None = Field(default=None, max_length=16000)
    model: str | None = None
    advisor_model: str | None = None
    allow_subagents: bool | None = None
    max_subagents: int | None = Field(default=None, ge=0, le=8)
    sandbox: Literal['process', 'container'] | None = None
    desktop_control: bool | None = None

    @model_validator(mode='after')
    def concrete_values(self):
        for name in self.model_fields_set - {'model', 'advisor_model'}:
            if getattr(self, name) is None:
                raise ValueError(name + ' cannot be null')
        return self


class CapabilityEntry(BaseModel):
    name: str
    description: str
    origin: Literal['builtin', 'connector', 'mission']
    needs_approval: bool
    parameters: dict[str, Any] | None = None


class AgentKnowledge(BaseModel):
    id: str
    scope: Literal['agent', 'workspace', 'chat']
    scope_id: str
    text: str
    source: str
    expires_at: str | None = None
    created_at: str
    updated_at: str


class KnowledgeCreate(BaseModel):
    scope: Literal['agent', 'workspace', 'chat'] = 'agent'
    scope_id: str = 'main'
    text: str = Field(min_length=1, max_length=8000)
    source: str = Field(default='', max_length=2000)
    expires_at: str | None = None


class KnowledgeUpdate(KnowledgeCreate):
    updated_at: str


class AgentSkill(BaseModel):
    id: str
    name: str
    version: int
    description: str
    instructions: str
    permissions: list[str]
    dependencies: list[str]
    capability_id: str | None = None
    source_session_id: str | None = None
    code_hash: str | None = None
    enabled: bool = True
    created_at: str


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=4000)
    instructions: str = Field(min_length=1, max_length=32000)
    permissions: list[str] = Field(default_factory=list, max_length=100)
    dependencies: list[str] = Field(default_factory=list, max_length=100)
    capability_id: str | None = None
    source_session_id: str | None = None


class AgentArtifact(BaseModel):
    id: str
    session_id: str
    title: str
    kind: Literal['markdown', 'html', 'json', 'text']
    version: int
    content: str
    content_hash: str
    created_at: str
    updated_at: str


class ArtifactCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    kind: Literal['markdown', 'html', 'json', 'text'] = 'markdown'
    content: str = Field(max_length=1000000)
    id: str | None = None
    version: int | None = None


class AgentDelegation(BaseModel):
    id: str
    parent_session_id: str
    session_id: str
    task_id: str
    objective: str
    allowed_tools: list[str]
    max_requests: int
    requests: int = 0
    status: str
    result: str | None = None
    error: str | None = None
    created_at: str


class DelegateCreate(BaseModel):
    objective: str = Field(min_length=1, max_length=16000)
    title: str | None = None
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    max_requests: int = Field(default=20, ge=1, le=100)
    model: str | None = None


class ActionConstraint(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    operator: Literal['eq', 'in', 'gte', 'lte', 'prefix', 'host']
    value: Any

    @model_validator(mode='after')
    def valid_value(self):
        import math
        if self.operator == 'in' and not isinstance(self.value, list):
            raise ValueError('in requires a list')
        if self.operator in ('gte', 'lte') and (isinstance(self.value, bool) or not isinstance(self.value, (int, float))):
            raise ValueError('Numeric constraints require a number')
        if self.operator in ('gte', 'lte') and not math.isfinite(self.value):
            raise ValueError('Numeric constraints must be finite')
        if self.operator in ('prefix', 'host') and not isinstance(self.value, str):
            raise ValueError('String constraints require a string')
        return self


class ActionRule(BaseModel):
    tool: str = Field(min_length=1, max_length=200)
    constraints: list[ActionConstraint] = Field(default_factory=list, max_length=30)
    max_calls: int | None = Field(default=None, ge=1, le=100000)
    expires_at: str | None = None


class ActionPolicy(BaseModel):
    enabled: bool = False
    rules: list[ActionRule] = Field(default_factory=list, max_length=100)
    deny_unlisted_effects: bool = True
    block_opaque_execution: bool = True
    version: int = Field(default=0, ge=0)


class DelegationFollowup(BaseModel):
    message: str = Field(min_length=1, max_length=16000)
    additional_requests: int = Field(default=10, ge=1, le=100)


class SourceMonitorCreate(BaseModel):
    session_id: str
    name: str = Field(min_length=1, max_length=120)
    tool: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    select: str = ''
    interval_seconds: int = Field(default=300, ge=30, le=86400)
    prompt: str = Field(min_length=1, max_length=8000)
    notify_initial: bool = False
    record_memory: bool = False
    enabled: bool = True


class AgentChannelCreate(BaseModel):
    session_id: str
    name: str = Field(min_length=1, max_length=120)
    provider: Literal['slack', 'telegram', 'webhook']
    secret: str = Field(min_length=16, max_length=4000)
    allowed_senders: list[str] = Field(min_length=1, max_length=100)
    allowed_conversations: list[str] = Field(min_length=1, max_length=100)
    send_tool: str | None = None
    send_arguments: dict[str, Any] = Field(default_factory=dict)
    recipient_path: str = '/request_body/channel'
    text_path: str = '/request_body/text'
    enabled: bool = True


class AgentChannel(BaseModel):
    id: str
    session_id: str
    name: str
    provider: Literal['slack', 'telegram', 'webhook']
    allowed_senders: list[str]
    allowed_conversations: list[str]
    send_tool: str | None = None
    enabled: bool
    created_at: str


class AgentWake(BaseModel):
    id: str
    session_id: str
    prompt: str
    wake_at: str | None = None
    topic: str | None = None
    status: Literal['scheduled', 'ready', 'running', 'done', 'paused', 'failed', 'cancelled']
    result: str | None = None
    created_at: str


class WakeCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=16000)
    wake_at: str | None = None
    topic: str | None = Field(default=None, max_length=200)


class AgentDevice(BaseModel):
    id: str
    name: str
    scopes: list[str]
    enabled: bool
    created_at: str
    last_seen: str | None = None


class AgentsOverview(BaseModel):
    identities: list[AgentIdentity]
    sessions: list[AgentSession]
    missions: list[AgentPlusMission]
    delegations: list[AgentDelegation]
    wakes: list[AgentWake]
    legacy_swarms: list[dict[str, str]]


class EvAgentsUpdate(BaseModel):
    type: Literal['agents.update'] = 'agents.update'
    area: str
    session_id: str | None = None


class AgentHost(BaseModel):
    service: bool
    data_identity: str
    gateway_running: bool
    gateway_url: str
    gateway_tls: bool = False
    supports_service_install: bool


class OAuthConfig(BaseModel):
    target: Literal['mcp', 'service'] = 'mcp'
    connector_id: str
    authorize_url: str
    token_url: str
    client_id: str
    client_secret: str | None = None
    scopes: list[str] = Field(default_factory=list)


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ['read'], max_length=10)
    session_ids: list[str] = Field(min_length=1, max_length=100)


class DeviceGrant(BaseModel):
    device: AgentDevice
    token: str
    session_ids: list[str]


class ArtifactRevision(BaseModel):
    version: int
    content_hash: str
    updated_at: str


class LiveDocumentTool(BaseModel):
    name: str
    description: str = ''
    parameters: dict[str, Any]


class LiveDocument(BaseModel):
    id: str
    session_id: str
    title: str
    kind: str
    tools: list[LiveDocumentTool]


class ApplicationCall(BaseModel):
    session_id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentEventDelivery(BaseModel):
    event_id: str = Field(min_length=1, max_length=200)
    payload: dict[str, Any] = Field(default_factory=dict)


class OAuthConnection(BaseModel):
    connector_id: str
    authorized: bool
    expires_at: float | None = None


class PluginSummary(BaseModel):
    id: str
    version: str
    skill_ids: list[str]
    connector_ids: list[str]


class AgentConnections(BaseModel):
    vault_available: bool
    oauth: list[OAuthConnection]
    plugins: list[PluginSummary]


class PluginReview(BaseModel):
    id: str
    version: str
    skills: list[SkillCreate]
    connectors: list[dict[str, Any]]
    source_files: dict[str, str]
    warnings: list[str]
    imported: bool


class ParameterBinding(BaseModel):
    location: Literal['path', 'query']
    name: str


class ServiceOperation(BaseModel):
    id: str = Field(min_length=1, max_length=120)
    description: str = Field(default='', max_length=4000)
    method: Literal['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD']
    path: str = Field(min_length=1, max_length=2000)
    parameters: dict[str, Any]
    bindings: dict[str, ParameterBinding] = Field(default_factory=dict)
    body_field: str | None = None
    read_only: bool = False


class AgentService(BaseModel):
    id: str
    name: str
    base_url: str
    enabled: bool
    headers: dict[str, str]
    operations: list[ServiceOperation]
    created_at: str


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str
    headers: dict[str, str] = Field(default_factory=dict, max_length=40)
    operations: list[ServiceOperation] = Field(default_factory=list, max_length=500)
    enabled: bool = False


class ServiceImport(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_url: str
    document: dict[str, Any]
    headers: dict[str, str] = Field(default_factory=dict, max_length=40)


class AgentNotification(BaseModel):
    id: str
    session_id: str
    kind: Literal['completed','approval','question','error','notice']
    title: str
    body: str
    read: bool = False
    created_at: str


class NotificationSettings(BaseModel):
    web_push: bool = False
    native_desktop: bool = False
    contact: str = Field(default='mailto:local@localhost', max_length=300)


class PushSubscriptionInput(BaseModel):
    endpoint: str = Field(max_length=4000)
    keys: dict[str, str]


class ApplicationContext(BaseModel):
    session_id: str
    content: str = Field(max_length=16000)


class ServiceReview(BaseModel):
    service: ServiceCreate
    warnings: list[str]


class ServiceTemplate(BaseModel):
    id: str
    documentation: str
    requirements: str
    service: ServiceCreate


class CapabilityFamily(BaseModel):
    id: str
    name: str
    status: Literal['ready','setup','unknown','unsupported']
    verified: bool = False
    tools: list[str]
    requirements: str


class ApplicationResourceContent(BaseModel):
    uri: str
    text: str | None = None
    blob: str | None = None
    mimeType: str | None = None
    meta: dict[str, Any] | None = Field(default=None,alias='_meta')


class ApplicationResource(BaseModel):
    contents: list[ApplicationResourceContent]


class GatewayVoiceModel(BaseModel):
    id: str
    name: str
    runtime: str


class GatewayDictationHello(BaseModel):
    token: str = Field(max_length=200)
    model_id: str | None = Field(default=None,max_length=200)
    language: str | None = Field(default=None,max_length=30)


class GatewayTrustRequest(BaseModel):
    confirmed: Literal[True]
