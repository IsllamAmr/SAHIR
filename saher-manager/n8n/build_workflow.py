r"""Builds the n8n workflow "Saher - unread emails (read-only)" and the empty Outlook credential it uses.
Run once:  python build_workflow.py   then import both files with import_into_n8n.bat (n8n must be stopped).
The workflow only makes one Microsoft Graph GET request. It never sends, moves, deletes, drafts or marks mail as read."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = open(os.path.join(HERE, "..", "n8n_key.txt"), encoding="utf-8").read().strip()
CRED_ID = "saherOutlookRead1"
CRED_NAME = "Outlook - Saher (read only)"

# GET only. receivedDateTime has to come first in $filter for Graph to accept $orderby on it.
GRAPH_URL = ("https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages"
             "?$filter=receivedDateTime ge 2000-01-01T00:00:00Z and isRead eq false"
             "&$orderby=receivedDateTime desc&$top=5"
             "&$select=id,subject,from,receivedDateTime,bodyPreview,body,isRead,hasAttachments,importance")

check_key = f"""// Only Saher (which knows the local key) may ask for email summaries.
const h = $input.first().json.headers || {{}};
return [{{ json: {{ allowed: h['x-saher-key'] === '{KEY}' }} }}];"""

shape = r"""// Keep only what Saher needs. Bodies are cut to 2000 characters for the 4k-context model.
const res = $input.first().json;
const list = Array.isArray(res.value) ? res.value : [];
const emails = list.slice(0, 5).map(m => ({
  id: m.id,
  from_name: m.from?.emailAddress?.name || '',
  from_address: m.from?.emailAddress?.address || '',
  subject: m.subject || '',
  received: m.receivedDateTime || '',
  is_read: m.isRead === true,
  has_attachments: m.hasAttachments === true,
  importance: m.importance || 'normal',
  body: String((m.body?.content) || m.bodyPreview || '').replace(/\r/g, '').replace(/\n{3,}/g, '\n\n').trim().slice(0, 2000),
}));
return [{ json: { ok: true, source: 'outlook', emails } }];"""

graph_error = r"""// Outlook is not connected, the sign-in expired, or Graph refused the request.
const e = $input.first().json;
const msg = JSON.stringify(e.error || e).slice(0, 300);
const notConnected = /credential|token|auth|401|403|consent|refresh/i.test(msg);
return [{ json: { ok: false, error: notConnected ? 'not_connected' : 'graph_error', detail: msg } }];"""

nodes = [
    {"parameters": {"httpMethod": "GET", "path": "saher-unread", "responseMode": "responseNode",
                    "options": {"allowedOrigins": "http://127.0.0.1:8768"}},
     "id": "5a4e0001-0000-4000-8000-000000000001", "name": "Saher asks", "type": "n8n-nodes-base.webhook",
     "typeVersion": 2, "position": [0, 0], "webhookId": "5a4e0001-aaaa-4000-8000-000000000001"},
    {"parameters": {"jsCode": check_key}, "id": "5a4e0002-0000-4000-8000-000000000002", "name": "Check Saher key",
     "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [220, 0]},
    {"parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict", "version": 2},
                                   "conditions": [{"id": "c1", "leftValue": "={{ $json.allowed }}", "rightValue": True,
                                                   "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                                   "combinator": "and"}, "options": {}},
     "id": "5a4e0003-0000-4000-8000-000000000003", "name": "Key OK?", "type": "n8n-nodes-base.if",
     "typeVersion": 2.2, "position": [440, 0]},
    {"parameters": {"method": "GET", "url": GRAPH_URL, "authentication": "predefinedCredentialType",
                    "nodeCredentialType": "microsoftOutlookOAuth2Api", "sendHeaders": True,
                    "headerParameters": {"parameters": [{"name": "Prefer", "value": "outlook.body-content-type=\"text\""}]},
                    "options": {"timeout": 30000}},
     "id": "5a4e0004-0000-4000-8000-000000000004", "name": "Read 5 unread (GET only)",
     "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [660, -100],
     "credentials": {"microsoftOutlookOAuth2Api": {"id": CRED_ID, "name": CRED_NAME}},
     "onError": "continueErrorOutput",
     "notes": "Read-only: one GET to Microsoft Graph. Reading this way does not mark mail as read."},
    {"parameters": {"jsCode": shape}, "id": "5a4e0005-0000-4000-8000-000000000005", "name": "Shape for Saher",
     "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [880, -200]},
    {"parameters": {"jsCode": graph_error}, "id": "5a4e0006-0000-4000-8000-000000000006", "name": "Outlook problem",
     "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [880, 0]},
    {"parameters": {"respondWith": "json", "responseBody": "={{ JSON.stringify($json) }}", "options": {}},
     "id": "5a4e0007-0000-4000-8000-000000000007", "name": "Reply to Saher", "type": "n8n-nodes-base.respondToWebhook",
     "typeVersion": 1.1, "position": [1100, -100]},
    {"parameters": {"respondWith": "json", "responseBody": "{\"ok\": false, \"error\": \"forbidden\"}",
                    "options": {"responseCode": 403}},
     "id": "5a4e0008-0000-4000-8000-000000000008", "name": "Refuse", "type": "n8n-nodes-base.respondToWebhook",
     "typeVersion": 1.1, "position": [660, 150]},
]
connections = {
    "Saher asks": {"main": [[{"node": "Check Saher key", "type": "main", "index": 0}]]},
    "Check Saher key": {"main": [[{"node": "Key OK?", "type": "main", "index": 0}]]},
    "Key OK?": {"main": [[{"node": "Read 5 unread (GET only)", "type": "main", "index": 0}],
                         [{"node": "Refuse", "type": "main", "index": 0}]]},
    "Read 5 unread (GET only)": {"main": [[{"node": "Shape for Saher", "type": "main", "index": 0}],
                                          [{"node": "Outlook problem", "type": "main", "index": 0}]]},
    "Shape for Saher": {"main": [[{"node": "Reply to Saher", "type": "main", "index": 0}]]},
    "Outlook problem": {"main": [[{"node": "Reply to Saher", "type": "main", "index": 0}]]},
}
workflow = {"id": "saherUnread5RO01", "name": "Saher - unread emails (read-only)", "active": False,
            "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "saveDataSuccessExecution": "none",
            "saveDataErrorExecution": "none", "saveManualExecutions": False}, "pinData": {}}

TENANT = "YOUR-TENANT-ID"  # replaced by the Directory (tenant) ID from Entra
credential = {"id": CRED_ID, "name": CRED_NAME, "type": "microsoftOutlookOAuth2Api", "data": {
    "grantType": "authorizationCode", "clientCredentialType": "clientSecret",
    "authUrl": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize",
    "accessTokenUrl": f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/token",
    "clientId": "", "clientSecret": "",
    "customScopes": True, "enabledScopes": "openid offline_access Mail.Read",
    "authQueryParameters": "response_mode=query&prompt=select_account", "authentication": "body",
    "graphApiBaseUrl": "https://graph.microsoft.com", "useShared": False}}

with open(os.path.join(HERE, "saher-unread-workflow.json"), "w", encoding="utf-8") as f:
    json.dump(workflow, f, ensure_ascii=False, indent=2)
with open(os.path.join(HERE, "outlook-credential-empty.json"), "w", encoding="utf-8") as f:
    json.dump([credential], f, ensure_ascii=False, indent=2)
print("wrote saher-unread-workflow.json and outlook-credential-empty.json (the credential has no Microsoft secrets; the workflow holds only the local Saher key)")
