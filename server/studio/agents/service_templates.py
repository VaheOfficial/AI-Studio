"""Reviewed starter operations; account authorization is configured separately."""
from __future__ import annotations
import re
from ..schemas_agents import ServiceCreate, ServiceOperation

S = {'type':'string'}
I = {'type':'integer','minimum':1,'maximum':100}
O = {'type':'object'}


def operation(identity, description, method, path, query=None, body=None):
    keys = re.findall(r'\{([^}]+)\}',path)
    properties = {key:S for key in keys}
    bindings = {key:{'location':'path','name':key} for key in keys}
    for key,schema in (query or {}).items():
        properties[key] = schema
        bindings[key] = {'location':'query','name':key}
    required = list(keys)
    if body:
        properties['request_body'] = body
        required.append('request_body')
    return ServiceOperation(id=identity,description=description,method=method,path=path,
        parameters={'type':'object','properties':properties,'required':required,'additionalProperties':False},
        bindings=bindings,body_field='request_body' if body else None,read_only=method=='GET')


def listing():
    op = operation
    definitions = [
      ('github','GitHub','https://api.github.com','https://docs.github.com/en/rest',
       'A fine-grained token with access to the chosen repositories, or a registered OAuth application.',[
        op('list_issues','List repository issues and pull requests','GET','/repos/{owner}/{repo}/issues',{'state':S,'per_page':I,'page':{'type':'integer','minimum':1}}),
        op('get_issue','Read an issue','GET','/repos/{owner}/{repo}/issues/{issue_number}'),
        op('create_issue','Create an issue','POST','/repos/{owner}/{repo}/issues',body={'type':'object','properties':{'title':S,'body':S,'labels':{'type':'array','items':S}},'required':['title']}),
        op('comment','Comment on an issue or pull request','POST','/repos/{owner}/{repo}/issues/{issue_number}/comments',body={'type':'object','properties':{'body':S},'required':['body']}),
        op('list_pull_requests','List pull requests','GET','/repos/{owner}/{repo}/pulls',{'state':S,'per_page':I}),
        op('create_pull_request','Create a pull request from an existing pushed branch','POST','/repos/{owner}/{repo}/pulls',body={'type':'object','properties':{'title':S,'body':S,'head':S,'base':S,'draft':{'type':'boolean'}},'required':['title','head','base']}),
       ]),
      ('slack','Slack','https://slack.com/api','https://docs.slack.dev/reference/methods/',
       'A Slack app token. History, search and messaging require their corresponding scopes and channel access.',[
        op('channels','List accessible conversations','GET','/conversations.list',{'cursor':S,'limit':I,'types':S}),
        op('history','Read a conversation history','GET','/conversations.history',{'channel':S,'cursor':S,'limit':I,'oldest':S,'latest':S}),
        op('thread','Read replies to a message','GET','/conversations.replies',{'channel':S,'ts':S,'cursor':S,'limit':I}),
        op('search','Search messages with a user token that permits search','GET','/search.messages',{'query':S,'count':I}),
        op('send_message','Send a message to an accessible channel','POST','/chat.postMessage',body={'type':'object','properties':{'channel':S,'text':S,'thread_ts':S},'required':['channel','text']}),
       ]),
      ('gmail','Gmail','https://gmail.googleapis.com/gmail/v1','https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages',
       'Google OAuth application with Gmail scopes. Sending requires a base64url encoded RFC 2822 message.',[
        op('search_messages','Search mailbox messages','GET','/users/me/messages',{'q':S,'pageToken':S,'maxResults':I}),
        op('read_message','Read a mailbox message','GET','/users/me/messages/{id}',{'format':S}),
        op('read_thread','Read a mailbox thread','GET','/users/me/threads/{id}',{'format':S}),
        op('draft','Create a mail draft','POST','/users/me/drafts',body={'type':'object','properties':{'message':{'type':'object','properties':{'raw':S},'required':['raw']}},'required':['message']}),
        op('send','Send encoded mail','POST','/users/me/messages/send',body={'type':'object','properties':{'raw':S,'threadId':S},'required':['raw']}),
        op('profile','Read the authorized mailbox identity','GET','/users/me/profile'),
        op('delete_draft','Delete a draft','DELETE','/users/me/drafts/{id}'),
        op('update_draft','Replace a draft with an encoded message','PUT','/users/me/drafts/{id}',body={'type':'object','properties':{'message':O},'required':['message']}),
        op('history','Read mailbox changes after a stored history identifier','GET','/users/me/history',{'startHistoryId':S,'historyTypes':S,'pageToken':S,'maxResults':I}),
        op('labels','List mailbox labels','GET','/users/me/labels'),
        op('modify','Apply or remove labels on a message','POST','/users/me/messages/{id}/modify',body={'type':'object','properties':{'addLabelIds':{'type':'array','items':S},'removeLabelIds':{'type':'array','items':S}}}),
        op('trash','Move a message to trash','POST','/users/me/messages/{id}/trash'),
       ]),
      ('google-calendar','Google Calendar','https://www.googleapis.com/calendar/v3','https://developers.google.com/workspace/calendar/api/v3/reference/events',
       'Google OAuth application with Calendar scopes; calendarId can be primary.',[
        op('calendars','List accessible calendars','GET','/users/me/calendarList',{'pageToken':S,'maxResults':I}),
        op('events','List calendar events','GET','/calendars/{calendarId}/events',{'q':S,'timeMin':S,'timeMax':S,'pageToken':S,'maxResults':I}),
        op('create_event','Create an event with start/end date or dateTime objects','POST','/calendars/{calendarId}/events',body={'type':'object','properties':{'summary':S,'description':S,'start':O,'end':O,'attendees':{'type':'array','items':O}},'required':['start','end']}),
        op('update_event','Patch a calendar event','PATCH','/calendars/{calendarId}/events/{eventId}',body=O),
        op('read_event','Read an event and its current version','GET','/calendars/{calendarId}/events/{eventId}'),
        op('delete_event','Delete an event','DELETE','/calendars/{calendarId}/events/{eventId}'),
        op('free_busy','Read busy intervals for selected calendars','POST','/freeBusy',body={'type':'object','properties':{'timeMin':S,'timeMax':S,'items':{'type':'array','items':O}},'required':['timeMin','timeMax','items']}),
       ]),
      ('google-drive','Google Drive','https://www.googleapis.com/drive/v3','https://developers.google.com/workspace/drive/api/reference/rest/v3/files',
       'Google OAuth application with Drive scopes. File content upload uses an application-specific adapter or browser upload.',[
        op('files','Search accessible file metadata','GET','/files',{'q':S,'fields':S,'pageToken':S,'pageSize':I}),
        op('read_file','Read file metadata','GET','/files/{fileId}',{'fields':S}),
        op('create_file','Create file metadata or a folder','POST','/files',body={'type':'object','properties':{'name':S,'mimeType':S,'parents':{'type':'array','items':S}},'required':['name']}),
        op('update_file','Update file metadata','PATCH','/files/{fileId}',body=O),
        op('delete_file','Delete a file','DELETE','/files/{fileId}'),
        op('permissions','List file sharing permissions','GET','/files/{fileId}/permissions',{'pageToken':S,'pageSize':I}),
        op('share','Create an explicit file sharing permission','POST','/files/{fileId}/permissions',{'sendNotificationEmail':{'type':'boolean'}},body=O),
       ]),
      ('google-sheets','Google Sheets','https://sheets.googleapis.com/v4','https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets.values',
       'Google OAuth application with Sheets scopes. Batch requests are native Sheets request objects.',[
        op('read_sheet','Read spreadsheet structure','GET','/spreadsheets/{spreadsheetId}',{'fields':S}),
        op('read_cells','Read values from an A1 range','GET','/spreadsheets/{spreadsheetId}/values/{range}'),
        op('write_cells','Write a rectangular range; choose RAW or USER_ENTERED','PUT','/spreadsheets/{spreadsheetId}/values/{range}',{'valueInputOption':S},body={'type':'object','properties':{'values':{'type':'array','items':{'type':'array','items':{}}},'majorDimension':S},'required':['values']}),
        op('batch_update','Apply formatting, charts and structural requests','POST','/spreadsheets/{spreadsheetId}:batchUpdate',body={'type':'object','properties':{'requests':{'type':'array','items':O}},'required':['requests']}),
       ]),
      ('google-docs','Google Docs','https://docs.googleapis.com/v1','https://developers.google.com/workspace/docs/api/reference/rest/v1/documents',
       'Google OAuth application with Docs scopes. Batch edits can include writeControl for revision checks.',[
        op('read_document','Read document structure and revision','GET','/documents/{documentId}'),
        op('create_document','Create a document','POST','/documents',body={'type':'object','properties':{'title':S},'required':['title']}),
        op('batch_update','Apply text and document formatting requests','POST','/documents/{documentId}:batchUpdate',body={'type':'object','properties':{'requests':{'type':'array','items':O},'writeControl':O},'required':['requests']}),
       ]),
      ('google-slides','Google Slides','https://slides.googleapis.com/v1','https://developers.google.com/workspace/slides/api/reference/rest/v1/presentations',
       'Google OAuth application with Slides scopes. Batch edits accept native presentation request objects.',[
        op('read_presentation','Read slides and page elements','GET','/presentations/{presentationId}'),
        op('create_presentation','Create a presentation','POST','/presentations',body={'type':'object','properties':{'title':S},'required':['title']}),
        op('batch_update','Apply slide, text and shape requests','POST','/presentations/{presentationId}:batchUpdate',body={'type':'object','properties':{'requests':{'type':'array','items':O},'writeControl':O},'required':['requests']}),
       ]),
      ('microsoft','Microsoft 365','https://graph.microsoft.com/v1.0','https://learn.microsoft.com/en-us/graph/api/overview',
       'Microsoft Entra application with delegated Mail, Calendar or Files permissions for the selected operations.',[
        op('mail','List mailbox messages','GET','/me/messages',{'$search':S,'$filter':S,'$select':S,'$top':I}),
        op('read_mail','Read a mailbox message','GET','/me/messages/{id}'),
        op('draft_mail','Create a mail draft','POST','/me/messages',body={'type':'object','properties':{'subject':S,'body':O,'toRecipients':{'type':'array','items':O}},'required':['subject','body']}),
        op('send_mail','Send mail','POST','/me/sendMail',body={'type':'object','properties':{'message':O,'saveToSentItems':{'type':'boolean'}},'required':['message']}),
        op('events','List calendar events','GET','/me/events',{'$filter':S,'$select':S,'$top':I}),
        op('create_event','Create a calendar event','POST','/me/events',body={'type':'object','properties':{'subject':S,'body':O,'start':O,'end':O,'attendees':{'type':'array','items':O}},'required':['subject','start','end']}),
        op('files','List OneDrive root children','GET','/me/drive/root/children',{'$select':S,'$top':I}),
       ]),
      ('notion','Notion','https://api.notion.com/v1','https://developers.notion.com/reference/intro',
       'A Notion integration with shared page access. Configure the required Notion-Version header for the operations used.',[
        op('search','Search accessible page titles','POST','/search',body={'type':'object','properties':{'query':S,'start_cursor':S,'page_size':I}}),
        op('read_page','Read page metadata','GET','/pages/{page_id}'),
        op('read_blocks','Read a page or block’s children','GET','/blocks/{block_id}/children',{'start_cursor':S,'page_size':I}),
        op('append_blocks','Append native block objects','PATCH','/blocks/{block_id}/children',body={'type':'object','properties':{'children':{'type':'array','items':O}},'required':['children']}),
       ]),
      ('linear','Linear','https://api.linear.app','https://linear.app/developers/graphql',
       'A Linear API key (raw Authorization header) or OAuth token. Query and mutation bodies follow the Linear GraphQL schema.',[
        op('graphql','Execute a reviewed GraphQL query or mutation','POST','/graphql',body={'type':'object','properties':{'query':S,'variables':O},'required':['query']}),
       ]),
      ('nominatim','Local place search','http://127.0.0.1:8081','https://nominatim.org/release-docs/latest/api/Search/',
       'Configure a self-hosted Nominatim instance or a provider you are authorized to use. The public OSM foundation endpoint is not configured by this starter. Results are geographical records, not business reviews or current opening hours.',[
        op('search_places','Search configured geographical place records; request jsonv2 format','GET','/search',{'q':S,'format':{'type':'string','enum':['jsonv2']},'limit':{'type':'integer','minimum':1,'maximum':20},'countrycodes':S}),
        op('reverse_place','Read a place record near latitude and longitude; request jsonv2 format','GET','/reverse',{'lat':{'type':'number','minimum':-90,'maximum':90},'lon':{'type':'number','minimum':-180,'maximum':180},'format':{'type':'string','enum':['jsonv2']}}),
       ]),
      ('osrm','Local routes','http://127.0.0.1:5000','https://project-osrm.org/docs/v5.24.0/api/',
       'Configure a local OSRM instance with the required regional map and transport profile. The profile name does not change the server’s prepared transport data. Durations reflect the configured data, without live traffic.',[
        op('route','Read routes between longitude,latitude pairs separated by semicolons','GET','/route/v1/{profile}/{coordinates}',{'steps':{'type':'boolean'},'overview':{'type':'string','enum':['false','simplified','full']},'geometries':{'type':'string','enum':['geojson','polyline']}}),
        op('travel_matrix','Read a travel-time matrix between supplied coordinates','GET','/table/v1/{profile}/{coordinates}',{'annotations':{'type':'string','enum':['duration','distance','duration,distance']}}),
       ]),
      ('openligadb','OpenLigaDB sports','https://api.openligadb.de','https://api.openligadb.de/index.html',
       'Public community-maintained match data for supported leagues. Read league and season identifiers first. Results may be delayed or incomplete; this is not coverage of every sports league.',[
        op('leagues','Read supported league shortcuts and seasons','GET','/getavailableleagues'),
        op('matches','Read season fixtures and available match results','GET','/getmatchdata/{leagueShortcut}/{leagueSeason}'),
        op('table','Read a supported league table','GET','/getbltable/{leagueShortcut}/{leagueSeason}'),
       ]),
      ('hubspot','HubSpot CRM','https://api.hubapi.com','https://developers.hubspot.com/docs/api/developer-guides-resources',
       'A HubSpot private-app or OAuth bearer token with CRM object scopes. Uses the documented 2026-09 object endpoints; review property names and tenant permissions.',[
        op('list_contacts','Read contact records','GET','/crm/objects/2026-09/contacts',{'limit':I,'after':S,'properties':S}),
        op('read_contact','Read one contact record','GET','/crm/objects/2026-09/contacts/{contactId}',{'properties':S}),
        op('create_contact','Create a contact with reviewed properties','POST','/crm/objects/2026-09/contacts',body={'type':'object','properties':{'properties':O},'required':['properties']}),
        op('update_contact','Update a contact’s explicit properties','PATCH','/crm/objects/2026-09/contacts/{contactId}',body={'type':'object','properties':{'properties':O},'required':['properties']}),
        op('list_deals','Read deal records','GET','/crm/objects/2026-09/deals',{'limit':I,'after':S,'properties':S}),
       ]),
    ]
    for key,_,_,_,_,operations in definitions:
        if key=='nominatim':
            for item in operations:
                item.parameters['required']=['q','format'] if item.id=='search_places' else ['lat','lon','format']
    return [{'id':key,'documentation':documentation,'requirements':requirements,
      'service':ServiceCreate(name=name,base_url=url,operations=operations).model_dump()} for key,name,url,documentation,requirements,operations in definitions]
