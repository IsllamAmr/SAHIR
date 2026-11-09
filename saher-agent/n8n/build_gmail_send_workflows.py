r"""Builds two n8n workflows for Saher's approved email sending, plus the empty send-only Google credential.
Run:  python build_gmail_send_workflows.py   then import_gmail_send_into_n8n.bat (it stops nothing: stop n8n first).

1. "Saher - send approved Gmail" (POST /webhook/saher-send-gmail): forwards ONE ready-made message (base64url MIME,
   built and approved in Saher) to Gmail's messages.send. It uses the NEW credential "Gmail - Saher (send only)",
   whose only scope is gmail.send: it cannot read, delete or change mail. No retries (retryOnFail is off), so a
   message is never sent twice by n8n.
2. "Saher - check Sent (read-only)" (GET /webhook/saher-sent-check?mid=<Message-ID>): asks Gmail whether a message
   with that Message-ID exists (used when a send timed out, before anything is retried). It uses the EXISTING
   read-only credential "Gmail - Saher (read only)", which is not modified.
Both check the local X-Saher-Key (saher-manager\n8n_key.txt)."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
KEY = open(os.path.join(ROOT, "saher-manager", "n8n_key.txt"), encoding="utf-8").read().strip()
CRED_TYPE = "googleOAuth2Api"
SEND_CRED = {"id": "saherGmailSend01", "name": "Gmail - Saher (send only)"}
READ_CRED = {"id": "saherGmailRead01", "name": "Gmail - Saher (read only)"}  # existing, untouched

check_send_key = f"""// Only Saher (which knows the local key) may send. The message arrives fully built and approved.
const j = $input.first().json;
const h = j.headers || {{}};
const raw = (j.body && typeof j.body.raw === 'string') ? j.body.raw : '';
return [{{ json: {{ allowed: h['x-saher-key'] === '{KEY}' && raw.length > 0, raw }} }}];"""

sent_ok = r"""// Gmail's own answer: the message id and thread id are the proof that it was sent.
const r = $input.first().json;
return [{ json: { ok: true, id: r.id || '', threadId: r.threadId || '', labelIds: r.labelIds || [] } }];"""

send_error = r"""// definitive = Gmail refused, so nothing was sent. Otherwise the outcome is unknown and Saher checks Sent first.
const e = $input.first().json;
const msg = JSON.stringify(e.error || e).slice(0, 400);
let error = 'unknown', definitive = false;
if (/invalid_grant|refresh|credential|No credentials|access token|401|Unauthorized/i.test(msg)) { error = 'not_connected'; definitive = true; }
else if (/403|insufficient|scope|PERMISSION_DENIED|forbidden/i.test(msg)) { error = 'no_permission'; definitive = true; }
else if (/\b400\b|Invalid To|invalidArgument|Recipient address required|bad request/i.test(msg)) { error = 'bad_request'; definitive = true; }
else if (/\b429\b|rateLimit|quota/i.test(msg)) { error = 'rate_limited'; definitive = true; }
return [{ json: { ok: false, error, definitive, detail: msg } }];"""

check_mid_key = f"""// Only Saher may ask. mid = the Message-ID Saher put in the approved message.
const j = $input.first().json;
const h = j.headers || {{}};
const mid = String((j.query && j.query.mid) || '').replace(/[<>\\s]/g, '');
return [{{ json: {{ allowed: h['x-saher-key'] === '{KEY}' && /^saher-[0-9a-f]{{16,64}}@saher\\.local$/.test(mid), mid }} }}];"""

found = r"""const r = $input.first().json;
const m = (r.messages || [])[0];
return [{ json: { ok: true, found: !!m, id: m ? m.id : '', threadId: m ? m.threadId : '' } }];"""

check_error = r"""const e = $input.first().json;
const msg = JSON.stringify(e.error || e).slice(0, 300);
const notConnected = /credential|token|auth|401|403|consent|refresh|invalid_grant/i.test(msg);
return [{ json: { ok: false, error: notConnected ? 'not_connected' : 'gmail_error', detail: msg } }];"""


def node(prefix, n, name, typ, version, pos, params, **extra):
    return dict({"parameters": params, "id": f"{prefix}{n:02d}-0000-4000-8000-0000000000{n:02d}", "name": name,
                 "type": typ, "typeVersion": version, "position": pos}, **extra)


def code(prefix, n, name, js, pos):
    return node(prefix, n, name, "n8n-nodes-base.code", 2, pos, {"jsCode": js})


def if_true(prefix, n, name, field, pos):
    return node(prefix, n, name, "n8n-nodes-base.if", 2.2, pos, {
        "conditions": {"options": {"caseSensitive": True, "typeValidation": "strict", "version": 2},
                       "conditions": [{"id": f"c{n}", "leftValue": "={{ $json." + field + " }}", "rightValue": True,
                                       "operator": {"type": "boolean", "operation": "true", "singleValue": True}}],
                       "combinator": "and"}, "options": {}})


def respond(prefix, n, name, body, pos, status=None):
    return node(prefix, n, name, "n8n-nodes-base.respondToWebhook", 1.1, pos,
                {"respondWith": "json", "responseBody": body, "options": {"responseCode": status} if status else {}})


def webhook(prefix, method, path, pos):
    return node(prefix, 1, "Saher asks", "n8n-nodes-base.webhook", 2, pos,
                {"httpMethod": method, "path": path, "responseMode": "responseNode", "options": {}},
                webhookId=f"{prefix}01-bbbb-4000-8000-000000000001")


c = lambda name: {"node": name, "type": "main", "index": 0}
SETTINGS = {"executionOrder": "v1", "saveDataSuccessExecution": "none", "saveDataErrorExecution": "none",
            "saveManualExecutions": False}

P = "7b5e00"
send_nodes = [
    webhook(P, "POST", "saher-send-gmail", [0, 0]),
    code(P, 2, "Check Saher key", check_send_key, [220, 0]),
    if_true(P, 3, "Key OK?", "allowed", [440, 0]),
    node(P, 4, "Send ONE approved message", "n8n-nodes-base.httpRequest", 4.2, [660, -100], {
        "method": "POST", "url": "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        "authentication": "predefinedCredentialType", "nodeCredentialType": CRED_TYPE,
        "sendBody": True, "contentType": "json", "specifyBody": "json",
        "jsonBody": "={{ JSON.stringify({ raw: $json.raw }) }}", "options": {"timeout": 30000}},
        credentials={CRED_TYPE: SEND_CRED}, onError="continueErrorOutput", retryOnFail=False,
        notes="gmail.send only. No retry: a timeout is checked in Sent by Saher before anything else happens."),
    code(P, 5, "Sent: Gmail ids", sent_ok, [880, -200]),
    code(P, 6, "Not sent or unknown", send_error, [880, 0]),
    respond(P, 7, "Reply to Saher", "={{ JSON.stringify($json) }}", [1100, -100]),
    respond(P, 8, "Refuse", "{\"ok\": false, \"error\": \"forbidden\", \"definitive\": true}", [660, 150], 403),
]
send_conn = {
    "Saher asks": {"main": [[c("Check Saher key")]]},
    "Check Saher key": {"main": [[c("Key OK?")]]},
    "Key OK?": {"main": [[c("Send ONE approved message")], [c("Refuse")]]},
    "Send ONE approved message": {"main": [[c("Sent: Gmail ids")], [c("Not sent or unknown")]]},
    "Sent: Gmail ids": {"main": [[c("Reply to Saher")]]},
    "Not sent or unknown": {"main": [[c("Reply to Saher")]]},
}

Q = "7b5f00"
check_nodes = [
    webhook(Q, "GET", "saher-sent-check", [0, 0]),
    code(Q, 2, "Check Saher key", check_mid_key, [220, 0]),
    if_true(Q, 3, "Key OK?", "allowed", [440, 0]),
    node(Q, 4, "Search by Message-ID (GET only)", "n8n-nodes-base.httpRequest", 4.2, [660, -100], {
        "method": "GET",
        "url": "=https://gmail.googleapis.com/gmail/v1/users/me/messages?maxResults=1&includeSpamTrash=true&q={{ encodeURIComponent('rfc822msgid:' + $json.mid) }}",
        "authentication": "predefinedCredentialType", "nodeCredentialType": CRED_TYPE, "options": {"timeout": 30000}},
        credentials={CRED_TYPE: READ_CRED}, onError="continueErrorOutput", notes="Read-only search, existing credential."),
    code(Q, 5, "Found?", found, [880, -200]),
    code(Q, 6, "Gmail problem", check_error, [880, 0]),
    respond(Q, 7, "Reply to Saher", "={{ JSON.stringify($json) }}", [1100, -100]),
    respond(Q, 8, "Refuse", "{\"ok\": false, \"error\": \"forbidden\"}", [660, 150], 403),
]
check_conn = {
    "Saher asks": {"main": [[c("Check Saher key")]]},
    "Check Saher key": {"main": [[c("Key OK?")]]},
    "Key OK?": {"main": [[c("Search by Message-ID (GET only)")], [c("Refuse")]]},
    "Search by Message-ID (GET only)": {"main": [[c("Found?")], [c("Gmail problem")]]},
    "Found?": {"main": [[c("Reply to Saher")]]},
    "Gmail problem": {"main": [[c("Reply to Saher")]]},
}

workflows = {
    "saher-send-workflow.json": {"id": "saherGmailSend001", "name": "Saher - send approved Gmail", "active": False,
                                 "nodes": send_nodes, "connections": send_conn, "settings": SETTINGS, "pinData": {}},
    "saher-sent-check-workflow.json": {"id": "saherGmailSentChk1", "name": "Saher - check Sent (read-only)",
                                       "active": False, "nodes": check_nodes, "connections": check_conn,
                                       "settings": SETTINGS, "pinData": {}},
}
credential = [{"id": SEND_CRED["id"], "name": SEND_CRED["name"], "type": CRED_TYPE, "data": {
    "grantType": "authorizationCode",
    "authUrl": "https://accounts.google.com/o/oauth2/v2/auth",
    "accessTokenUrl": "https://oauth2.googleapis.com/token",
    "clientId": "", "clientSecret": "",
    "scope": "https://www.googleapis.com/auth/gmail.send",
    "authQueryParameters": "access_type=offline&prompt=consent", "authentication": "body"}}]

for name, wf in workflows.items():
    with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)
with open(os.path.join(HERE, "gmail-send-credential-empty.json"), "w", encoding="utf-8") as f:
    json.dump(credential, f, ensure_ascii=False, indent=2)
print("wrote", ", ".join(workflows), "and gmail-send-credential-empty.json (no Google secrets)")
