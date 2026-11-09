r"""Builds the n8n workflow "Saher - unread Gmail (read-only)" and the empty Google credential it uses.
Run once:  python build_gmail_workflow.py   then import both files with import_gmail_into_n8n.bat (n8n must be stopped).
The credential only asks Google for gmail.readonly, so it cannot send, delete, label or mark mail as read even by mistake.
The workflow makes GET requests only: one list of the 5 newest unread inbox messages, then one GET per message."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
KEY = open(os.path.join(HERE, "..", "n8n_key.txt"), encoding="utf-8").read().strip()
CRED_ID = "saherGmailRead01"
CRED_NAME = "Gmail - Saher (read only)"
CRED_TYPE = "googleOAuth2Api"  # generic Google OAuth2: unlike n8n's Gmail credential, its scope is ours to choose
CRED = {CRED_TYPE: {"id": CRED_ID, "name": CRED_NAME}}

LIST_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages?q=is%3Aunread%20in%3Ainbox&maxResults=5"
GET_URL = "=https://gmail.googleapis.com/gmail/v1/users/me/messages/{{ $json.id }}?format=full"

check_key = f"""// Only Saher (which knows the local key) may ask for email summaries.
const h = $input.first().json.headers || {{}};
return [{{ json: {{ allowed: h['x-saher-key'] === '{KEY}' }} }}];"""

ids = r"""// One item per unread message id (newest first, as Gmail lists them).
const list = $input.first().json.messages || [];
if (!list.length) return [{ json: { any: false } }];
return list.slice(0, 5).map(m => ({ json: { any: true, id: m.id } }));"""

shape = r"""// Keep only what Saher needs. Bodies are cut to 2000 characters for the 4k-context model.
function decode(data) {
  const b64 = String(data).replace(/-/g, '+').replace(/_/g, '/');
  if (typeof Buffer !== 'undefined') return Buffer.from(b64, 'base64').toString('utf8');
  return new TextDecoder().decode(Uint8Array.from(atob(b64), c => c.charCodeAt(0)));
}
function walk(p, out) {
  if (!p) return;
  if (p.filename && p.body && p.body.attachmentId) out.attachments = true;
  else if (p.mimeType === 'text/plain' && p.body && p.body.data) out.plain.push(decode(p.body.data));
  else if (p.mimeType === 'text/html' && p.body && p.body.data) out.html.push(decode(p.body.data));
  (p.parts || []).forEach(q => walk(q, out));
}
function htmlToText(h) {
  return h.replace(/<(style|script|head)[\s\S]*?<\/\1>/gi, ' ').replace(/<br\s*\/?>|<\/(p|div|tr|li|h\d)>/gi, '\n')
    .replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/[ \t]+/g, ' ');
}
const emails = $input.all().map(item => {
  const m = item.json;
  const headers = {};
  (m.payload && m.payload.headers || []).forEach(h => { headers[h.name.toLowerCase()] = h.value; });
  const from = headers['from'] || '';
  const match = from.match(/^\s*"?([^"<]*?)"?\s*<([^>]+)>\s*$/);
  const out = { plain: [], html: [], attachments: false };
  walk(m.payload, out);
  const body = out.plain.length ? out.plain.join('\n') : out.html.length ? htmlToText(out.html.join('\n')) : (m.snippet || '');
  return {
    id: m.id,
    from_name: match ? match[1].trim() : '',
    from_address: match ? match[2].trim() : from.trim(),
    subject: headers['subject'] || '',
    received: m.internalDate ? new Date(Number(m.internalDate)).toISOString() : '',
    is_read: !(m.labelIds || []).includes('UNREAD'),
    has_attachments: out.attachments,
    importance: 'normal',
    body: body.replace(/\r/g, '').replace(/\n\s*\n\s*\n+/g, '\n\n').trim().slice(0, 2000),
  };
});
return [{ json: { ok: true, source: 'gmail', emails } }];"""

empty = r"""return [{ json: { ok: true, source: 'gmail', emails: [] } }];"""

google_error = r"""// Gmail is not connected, the sign-in expired, or Google refused the request.
const e = $input.first().json;
const msg = JSON.stringify(e.error || e).slice(0, 300);
const notConnected = /credential|token|auth|401|403|consent|refresh|invalid_grant/i.test(msg);
return [{ json: { ok: false, error: notConnected ? 'not_connected' : 'graph_error', detail: msg } }];"""


def code(name, js, n, pos):
    return {"parameters": {"jsCode": js}, "id": f"6a4e00{n:02d}-0000-4000-8000-0000000000{n:02d}", "name": name,
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": pos}


def get(name, url, n, pos, note):
    return {"parameters": {"method": "GET", "url": url, "authentication": "predefinedCredentialType",
                           "nodeCredentialType": CRED_TYPE, "options": {"timeout": 30000}},
            "id": f"6a4e00{n:02d}-0000-4000-8000-0000000000{n:02d}", "name": name,
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": pos, "credentials": CRED,
            "onError": "continueErrorOutput", "notes": note}


def respond(name, body, n, pos, code_=None):
    opts = {"responseCode": code_} if code_ else {}
    return {"parameters": {"respondWith": "json", "responseBody": body, "options": opts},
            "id": f"6a4e00{n:02d}-0000-4000-8000-0000000000{n:02d}", "name": name,
            "type": "n8n-nodes-base.respondToWebhook", "typeVersion": 1.1, "position": pos}


def if_true(name, field, n, pos):
    return {"parameters": {"conditions": {"options": {"caseSensitive": True, "typeValidation": "strict", "version": 2},
                                          "conditions": [{"id": f"c{n}", "leftValue": "={{ $json." + field + " }}",
                                                          "rightValue": True, "operator": {"type": "boolean",
                                                          "operation": "true", "singleValue": True}}],
                                          "combinator": "and"}, "options": {}},
            "id": f"6a4e00{n:02d}-0000-4000-8000-0000000000{n:02d}", "name": name, "type": "n8n-nodes-base.if",
            "typeVersion": 2.2, "position": pos}


nodes = [
    {"parameters": {"httpMethod": "GET", "path": "saher-unread-gmail", "responseMode": "responseNode",
                    "options": {"allowedOrigins": "http://127.0.0.1:8768"}},
     "id": "6a4e0001-0000-4000-8000-000000000001", "name": "Saher asks", "type": "n8n-nodes-base.webhook",
     "typeVersion": 2, "position": [0, 0], "webhookId": "6a4e0001-bbbb-4000-8000-000000000001"},
    code("Check Saher key", check_key, 2, [220, 0]),
    if_true("Key OK?", "allowed", 3, [440, 0]),
    get("List 5 unread (GET only)", LIST_URL, 4, [660, -100], "Read-only: lists ids of the 5 newest unread inbox messages."),
    code("Message ids", ids, 5, [880, -200]),
    if_true("Any unread?", "any", 6, [1100, -200]),
    get("Read each message (GET only)", GET_URL, 7, [1320, -300], "Read-only: reading this way does not mark mail as read."),
    code("Shape for Saher", shape, 8, [1540, -400]),
    code("No unread", empty, 9, [1320, -100]),
    code("Gmail problem", google_error, 10, [1540, 0]),
    respond("Reply to Saher", "={{ JSON.stringify($json) }}", 11, [1760, -200]),
    respond("Refuse", "{\"ok\": false, \"error\": \"forbidden\"}", 12, [660, 150], 403),
]
c = lambda node: {"node": node, "type": "main", "index": 0}
connections = {
    "Saher asks": {"main": [[c("Check Saher key")]]},
    "Check Saher key": {"main": [[c("Key OK?")]]},
    "Key OK?": {"main": [[c("List 5 unread (GET only)")], [c("Refuse")]]},
    "List 5 unread (GET only)": {"main": [[c("Message ids")], [c("Gmail problem")]]},
    "Message ids": {"main": [[c("Any unread?")]]},
    "Any unread?": {"main": [[c("Read each message (GET only)")], [c("No unread")]]},
    "Read each message (GET only)": {"main": [[c("Shape for Saher")], [c("Gmail problem")]]},
    "Shape for Saher": {"main": [[c("Reply to Saher")]]},
    "No unread": {"main": [[c("Reply to Saher")]]},
    "Gmail problem": {"main": [[c("Reply to Saher")]]},
}
workflow = {"id": "saherGmail5RO001", "name": "Saher - unread Gmail (read-only)", "active": False,
            "nodes": nodes, "connections": connections, "settings": {"executionOrder": "v1", "saveDataSuccessExecution": "none",
            "saveDataErrorExecution": "none", "saveManualExecutions": False}, "pinData": {}}

credential = {"id": CRED_ID, "name": CRED_NAME, "type": CRED_TYPE, "data": {
    "grantType": "authorizationCode",
    "authUrl": "https://accounts.google.com/o/oauth2/v2/auth",
    "accessTokenUrl": "https://oauth2.googleapis.com/token",
    "clientId": "", "clientSecret": "",
    "scope": "https://www.googleapis.com/auth/gmail.readonly",
    "authQueryParameters": "access_type=offline&prompt=consent", "authentication": "body"}}

with open(os.path.join(HERE, "saher-gmail-workflow.json"), "w", encoding="utf-8") as f:
    json.dump(workflow, f, ensure_ascii=False, indent=2)
with open(os.path.join(HERE, "gmail-credential-empty.json"), "w", encoding="utf-8") as f:
    json.dump([credential], f, ensure_ascii=False, indent=2)
print("wrote saher-gmail-workflow.json and gmail-credential-empty.json (no Google secrets; the workflow holds only the local Saher key)")
