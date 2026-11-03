"""Office add-in manifests for the authenticated local document gateway."""
from __future__ import annotations
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape


def manifest(host: str, base_url: str):
    hosts = {'word': ('Document', 'WordApi', '1.3'), 'excel': ('Workbook', 'ExcelApi', '1.9'), 'powerpoint': ('Presentation', 'PowerPointApi', '1.4')}
    if host not in hosts:
        raise ValueError('Choose word, excel or powerpoint')
    parsed = urlsplit(base_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('Office add-ins require a trusted HTTPS origin')
    origin = escape(base_url.rstrip('/'), {'"': '&quot;'})
    app, requirement, version = hosts[host]
    identity = uuid.uuid5(uuid.NAMESPACE_URL, 'grom-office-' + host)
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<OfficeApp xmlns="http://schemas.microsoft.com/office/appforoffice/1.1" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:type="TaskPaneApp">
<Id>{identity}</Id><Version>0.3.3.0</Version><ProviderName>Grom AI Studio</ProviderName><DefaultLocale>en-US</DefaultLocale>
<DisplayName DefaultValue="Grom Agents"/><Description DefaultValue="Connect this document to your local agent with scoped commands and approvals."/>
<IconUrl DefaultValue="{origin}/office/icon.png"/><SupportUrl DefaultValue="{origin}/office"/>
<AppDomains><AppDomain>{origin}</AppDomain></AppDomains><Hosts><Host Name="{app}"/></Hosts>
<Requirements><Sets DefaultMinVersion="{version}"><Set Name="{requirement}" MinVersion="{version}"/></Sets></Requirements>
<DefaultSettings><SourceLocation DefaultValue="{origin}/office?host={host}"/></DefaultSettings><Permissions>ReadWriteDocument</Permissions>
</OfficeApp>'''


def page():
    return Path(__file__).with_name('office.html').read_text(encoding='utf-8')
