# ساهر للمدراء (نص فقط، على جهازك)

صفحة محادثة مع ساهر (ALLaM 7B على Ollama، شخصية v5) تقدر تجيب **آخر ٥ إيميلات غير مقروءة** من صندوق الوارد في Outlook عن طريق n8n المحلي، وتعرض المرسل والعنوان والتاريخ، وتلخص كل إيميل، وتقترح رد تنسخه بنفسك.

**قراءة فقط:** الطلب الوحيد لمايكروسوفت هو `GET` واحد على Microsoft Graph. ساهر ما يرسل، ولا يحذف، ولا ينقل، ولا يعلّم أي إيميل كمقروء، ولا يسوي مسودات. ما ينحفظ شي على القرص.

## التشغيل

1. تأكد إن Ollama شغال.
2. شغّل `..\n8n\start-n8n.bat` واستنى دقيقتين (لازم للإيميل بس).
3. شغّل `start_saher_manager.bat`. الصفحة تفتح على http://127.0.0.1:8768
4. اضغط **آخر ٥ إيميلات غير مقروءة**، أو اكتب «وش عندي إيميلات؟».

`start_saher_manager_test.bat` نفس الشي، بس يضيف قائمة **المصدر** فيها صناديق تجريبية (mock): ٥ إيميلات، صندوق فاضي، إيميلات فيها أوامر خبيثة، Outlook غير مربوط، n8n طافي. أي نتيجة تجريبية مكتوب عليها «تجريبي (mock)».

الملفات القديمة ما تغيرت: `saher-app\start_saher.bat` (v4) و `start_saher_v5.bat` (v5) يشتغلون مثل قبل.

## ربط Outlook (مرة وحدة، حساب عمل، Single tenant)

### أ. في Microsoft Entra
1. افتح https://entra.microsoft.com وسجّل بحساب العمل.
2. **App registrations** ثم **New registration**:
   - Name: `Saher n8n local`
   - Supported account types: **Accounts in this organizational directory only (Single tenant)**
   - Redirect URI: النوع **Web**، والقيمة بالضبط: `http://localhost:5678/rest/oauth2-credential/callback`
   - اضغط **Register**.
3. من **Overview** انسخ **Application (client) ID** و **Directory (tenant) ID**. (هذول مو أسرار.)
4. **API permissions** ثم **Add a permission** ثم Microsoft Graph ثم **Delegated permissions**، وأضف بس: `openid`، `offline_access`، `Mail.Read`.
   - احذف `User.Read` اللي تنضاف تلقائياً (⋯ ثم Remove permission). ساهر ما يحتاجها. إذا طلع خطأ وقت تسجيل الدخول يطلبها، رجّعها: هي بس تقرأ اسمك وبريدك من ملفك.
   - لا تضيف `Mail.ReadWrite` ولا `Mail.Send` ولا أي شي فيه Shared.
5. **Certificates & secrets** ثم **New client secret**. انسخ الـ **Value** (يطلع مرة وحدة) وحطه مباشرة في n8n في الخطوة ب. لا تلصقه في الشات ولا في أي ملف.

إذا Entra قال إنك ما تقدر تسجل تطبيقات، أو صفحة الموافقة قالت **Need admin approval**: وقف هنا. هذا قرار قسم IT. عطهم اسم التطبيق والصلاحيات الثلاث فوق.

### ب. في n8n
1. افتح **http://localhost:5678** (لازم `localhost` مو `127.0.0.1`، وإلا يفشل الرجوع من مايكروسوفت لأن كوكي الدخول مربوط بالاسم).
2. **Overview** ثم **Credentials** ثم **Outlook - Saher (read only)** (جاهز وفاضي).
3. حط **Client ID** و **Client Secret**.
4. في **Authorization URL** و **Access Token URL** بدّل `YOUR-TENANT-ID` بالـ Directory (tenant) ID.
5. تأكد إن **Custom Scopes** مفعّل، و **Enabled Scopes** بالضبط: `openid offline_access Mail.Read`
6. تأكد إن **OAuth Redirect URL** المكتوب في الصفحة هو `http://localhost:5678/rest/oauth2-credential/callback`
7. **Save** ثم **Connect my account**. صفحة مايكروسوفت لازم تطلب بس: تسجيل الدخول، الاحتفاظ بالوصول، وقراءة بريدك. لو شفت "Send mail" أو "Read and write" **لا توافق**.
8. ارجع لساهر واضغط الزر. بعدها افتح Outlook وتأكد إن الإيميلات اللي لخصها ساهر **لسا غير مقروءة**.

## وش يصير مع كل إيميل
- يشيل أي سطر يحاول يعطي أوامر للمساعد قبل ما يوصل للنموذج، ويحط تنبيه.
- الإيميل اللي فيه أوامر للمساعد، أو يطلب فلوس مع رابط، ما ينكتب له رد مقترح أبداً.
- الرد المقترح يخاطب المرسل بصيغة الجمع (لكم، منكم) عشان ما نخمن جنسه من اسمه. إذا ظهرت صيغة مذكر أو مؤنث مفرد، يعيد المحاولة مرة، وإذا بقت ينبهك.
- أي رقم أو يوم في الرد المقترح مو موجود في الإيميل نفسه يطلع له تنبيه «ممكن ساهر اخترعها».
- الإيميل الإنجليزي ينكتب رده بالإنجليزي، والملخص بالعربي.
- طلبات مثل «أرسل له» أو «احذفه» يرد عليها البرنامج نفسه (مو النموذج): ما أقدر.

## الملفات
| ملف | وش هو |
|---|---|
| `server.py` | السيرفر على 127.0.0.1:8768 (يرفض أي طلب من موقع ثاني) |
| `mail.py` | جلب الإيميلات، التعليمات للنموذج، فحوص الأمان والصياغة |
| `index.html`, `logo.svg` | الواجهة (RTL، فاتح/داكن، كمبيوتر/جوال) والشعار |
| `mock\` | إيميلات تجريبية مخترعة |
| `n8n\build_workflow.py` | يبني `saher-unread-workflow.json` و `outlook-credential-empty.json` |
| `n8n\import_into_n8n.bat` | يستوردهم في n8n (n8n لازم يكون طافي). **لا تشغله بعد ما تربط Outlook** لأنه يمسح الربط. |
| `n8n_key.txt` | مفتاح محلي بين ساهر و n8n عشان ما يقدر غيره يطلب الإيميلات |

إعدادات: `SAHER_MODEL`, `SAHER_PORT` (8768), `SAHER_PERSONA`, `SAHER_NO_BROWSER=1`, `SAHER_TEST=1`.
