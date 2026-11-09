> **تحديث 2026-10-18:** هذا الدليل قديم (رابط 127.0.0.1 وحساب شخصي). الدليل المعتمد لحساب العمل ورابط localhost في `saher-manager\README.md`.

# ربط Outlook بساهر (قراءة فقط)

سير العمل الجاهز: `saher-outlook-readonly.json` في نفس المجلد.
يقرأ آخر 3 إيميلات، ويعطي أحدثها لساهر (allam-7b-saher على Ollama المحلي) يلخصه ويقترح رد. ما يرسل ولا يحذف ولا ينقل أي شي.

## 1. نوع الحساب
- **حساب شخصي** (outlook.com / hotmail / live): يشتغل. لكن مايكروسوفت أحياناً تطلب منك تفتح حساب Azure مجاني (يطلب بطاقة للتحقق فقط) قبل ما تسمح لك تسجل تطبيق. إذا طلبها، قرر أنت، وأقدر أشرح البديل.
- **حساب عمل/جامعة**: غالباً مدير النظام لازم يوافق على التطبيق، وبعض الجهات تمنعه. لو كذا، كلمه قبل.

## 2. تسجيل التطبيق في Azure (Entra)
1. افتح https://entra.microsoft.com ثم **App registrations** ثم **New registration**.
2. الاسم: `Saher n8n local`.
3. Supported account types:
   - حساب شخصي: **Accounts in any organizational directory and personal Microsoft accounts**.
   - حساب عمل فقط: **Single tenant**. وبعدها في n8n غيّر كلمة `common` في **Authorization URL** و **Access Token URL** إلى **Directory (tenant) ID** من صفحة Overview.
4. Redirect URI: النوع **Web**، والقيمة بالضبط:
   `http://127.0.0.1:5678/rest/oauth2-credential/callback`
5. بعد الإنشاء: من **Certificates & secrets** سوّ **New client secret**. انسخ الـ Value (يظهر مرة وحدة) وحطه مباشرة في n8n. **لا تلصقه في الشات.**
6. من **Overview** انسخ **Application (client) ID**.

## 3. الصلاحيات (الحد الأدنى)
في **API permissions** ثم Microsoft Graph ثم **Delegated**، أضف فقط:

| الصلاحية | وش تسوي |
|---|---|
| `openid` | تسمح بتسجيل الدخول والتعرف على حسابك. ما تقرأ بيانات. |
| `offline_access` | تخلي n8n يجدد الدخول بنفسه بدل ما تسجل كل ساعة. |
| `Mail.Read` | قراءة إيميلاتك فقط. ما تقدر ترسل ولا تحذف ولا تنقل. |

**لا تضيف**: `Mail.Send` (إرسال باسمك)، `Mail.ReadWrite` (تعديل وحذف ونقل)، ولا شي فيه `.Shared` أو Contacts أو Calendars.

## 4. في n8n (مهم)
1. Overview ثم ⋯ ثم **Import from File** واختر `saher-outlook-readonly.json`.
2. افتح عقدة **Read 3 recent emails** ثم Credential ثم **Create new**.
3. حط Client ID و Client Secret.
4. **فعّل Custom Scopes** واكتب في Enabled Scopes بالضبط:
   `openid offline_access Mail.Read`
   (بدون هذي الخطوة n8n يطلب افتراضياً Mail.Send و Mail.ReadWrite وغيرها.)
5. اضغط **Connect my account**. صفحة مايكروسوفت لازم تعرض فقط: تسجيل الدخول، الوصول المستمر، وقراءة البريد. لو شفت "Send mail" أو "Read and write" **وقف** ولا توافق.
6. ارجع وشغّل **Execute workflow**. النتيجة تطلع في عقدة **Show result**.

ملاحظة: العقدة تقرأ من كل المجلدات (بما فيها المرسل). بعد الربط تقدر تختار Inbox من Filters ثم Folders to Include.
