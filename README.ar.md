<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise: word for word everywhere (docs/positioning.md) -->
<p><b>مدير مكتبك لوكلاء البرمجة.</b></p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="أحدث إصدار" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="الترخيص: Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="نجوم GitHub" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://trendshift.io/repositories/91076?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-91076" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/91076" alt="Dodaios%2FDodaios | Trendshift" width="250" height="55"/></a>
</p>

<p>
  <a href="#التثبيت">التثبيت</a> ·
  <a href="#خططك-ومفاتيحك">خططك</a> ·
  <a href="#التوثيق">التوثيق</a> ·
  <a href="https://dodaios.ai">الموقع</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ja.md">日本語</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.es.md">Español</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.hi.md">हिन्दी</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.fr.md">Français</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.bn.md">বাংলা</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.pt-BR.md">Português (Brasil)</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ru.md">Русский</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.id.md">Bahasa Indonesia</a>
</p>

</div>

لديك Claude Code في طرفية، وCodex في أخرى، وتبويب دردشة تنسخ فيه الخطط ذهابًا وإيابًا. Dodaios ينهي ذلك. إنه طبقة فوق كل وكلاء البرمجة لديك: تقول ما تريد، بالصوت أو بالدردشة، ومساعد واحد يتولى الباقي. يكتب التكليف، ويشغّل الوكيل المناسب في Agentic IDE المدمج، ويراقبه أثناء العمل، ويخبرك عندما ينتهي أو يحتاج إليك. شغّل خمسة وكلاء في وقت واحد واعرف بدقة ما فعله كل واحد منهم.

مفتوح المصدر، ويعمل على حاسوبك. يعمل مع اشتراكك في Claude أو ChatGPT، أو مع مفاتيح API لـ Claude وOpenAI وGemini، أو مع نماذج Ollama المحلية.

https://github.com/user-attachments/assets/37cdc5a5-30d6-49c8-92ff-3454a075569f

<p align="center">
  <sub>تسجيل حقيقي بمعدل 60 إطارًا في الثانية، يُعرض بالسرعة نفسها التي صُوّر بها، مع حذف فترات انتظار النماذج. سُجّل باستخدام Claude Fable 5.2 وClaude Opus 5.5 عبر Claude Code. تعديل الشيفرة وتشغيل الاختبارات والإيداع (commit) كلها حقيقية. <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>شاهد الفيديو</b></a> (MP4، 42 ثانية، 2.5 ميغابايت)</sub>
</p>

## التثبيت

على macOS وLinux:

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

على Windows، في PowerShell:

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

يجهّز المثبّت بيئة Python خاصة به، ويضيف مشغّلًا، ثم يفتح التطبيق. عند التشغيل
الأول تمنح المساعد اسمًا (وهو أيضًا كلمة التنبيه)، وتوصل نموذجًا واحدًا، وتختار
الطريقة التي تريد التحدث بها إليه. ولأعمال البرمجة، ثبّت وكيل برمجة واحدًا على
الأقل، مثل Claude Code أو Codex، وسجّل الدخول إليه.

```bash
dodaios            # start the desktop app
dodaios update     # install the newest release
```

<details>
<summary>مثبّتات سطح المكتب وpipx والخوادم</summary>

<br />

نزّل المثبّت المناسب لنظامك من أحدث إصدار:

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage، x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

يسرد كل إصدار المجاميع الاختبارية في `installers-SHA256SUMS.txt`. المثبّتات
غير موقّعة بعد: يعرض Windows تحذيرًا، ويطلب منك macOS السماح للتطبيق مرة واحدة
في «إعدادات النظام»، ضمن «الخصوصية والأمن». وتوضح
[سياسة توقيع الشيفرة](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
أين وصل ذلك.

باستخدام pipx تحصل على حزمة الخادم الأصغر، دون مشغّل لسطح المكتب. وعلى خادم
Linux بلا شاشة، يقبل المثبّت الخيار `--headless`، ويشغّل الأمر
`dodaios serve` واجهة المتصفح وحدها:

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # browser interface only, for a server without a screen
```

يعمل Dodaios على أنظمة 64 بت: Windows وmacOS وLinux المبني على glibc. ويعمل
مثبّت الطرفية على x86-64 وArm64، ويحتاج إلى Python من 3.11 إلى 3.14 وإلى Git؛
فيجلب Python إن لم يكن موجودًا، ويعرض تثبيت Git إن كان مفقودًا. بطاقة الرسومات
اختيارية. حتى الآن، لم يُسجَّل اعتماد بعد تجربة حية إلا على Windows 11.
[دليل التثبيت](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[دعم المنصات](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[التشغيل على خادم](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## خططك ومفاتيحك

لا يكلّفك Dodaios شيئًا: لا حساب Dodaios ولا فئة مدفوعة. لا يبيع الوصول إلى
النماذج، ولا يسجّل الدخول نيابةً عنك أبدًا. فهو يشغّل أداة سطر الأوامر الرسمية لكل
وكيل برمجة، وتسجّل أنت الدخول إلى كلٍّ منها بنفسك، فتعمل الوكلاء بالخطط والمفاتيح
التي لديك أصلًا. فمثلًا، يحتاج Claude Code إلى خطة Claude مدفوعة. ويخضع استخدامك
لكل خدمة لشروط تلك الخدمة نفسها.
[المزوّدون ومفاتيح API](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## معلومات مفيدة

- **بياناتك.** الدردشات والذاكرة والمستندات والإعدادات ملفات على الحاسوب الذي
  يشغّل Dodaios. يحصل النموذج أو الخدمة المتصلة على ما يحتاجه لدوره في الطلب.
  ويمرّ تسجيل الدخول إلى إضافة Google أو Slack أو Figma عبر خدمة رموز صغيرة
  يديرها المشروع.
  [الخصوصية والبيانات المحلية](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)
- **السؤال أولًا.** تبدأ الدردشة الجديدة في وضع Bypass permissions، حيث لا يُطرح
  أي سؤال. اختر وضعًا يسأل، وستنتظر الحدود الصارمة الأربعة المذكورة أعلاه موافقتك
  دائمًا.
  [الأمان والموافقات](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)
- **لم يكتمل بعد.** تحتاج المكالمات الهاتفية إلى رقم Twilio خاص بك، وهي في مرحلة
  معاينة مبكرة. ولا تزال معظم الإضافات تحمل شارة Preview. أما تطبيق الهاتف فهو
  تطبيق ويب يقدّمه حاسوبك.

## التوثيق

تعرض [جولة الميزات](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)
كل جزء في صفحة واحدة، مع صور. والأدلة نفسها موجودة داخل التطبيق
ضمن **Docs**، مع إمكانية البحث.
[الإعداد عند التشغيل الأول](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) ·
[استكشاف الأخطاء وإصلاحها](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md) ·
[البنية المعمارية](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)

## المساهمة

نرحّب بالإصلاحات والاختبارات وتقارير المنصات والتوثيق. ينقلك
[دليل المساهمة](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)
من نسخة متفرّعة (fork) إلى فحص ناجح في نحو عشر دقائق. أرسل أسئلتك
وأفكارك إلى [Discord](https://discord.gg/x7USduHxbc).

شكرًا لكل من قدّم شيئًا هنا:

<!-- contributors:start -->

<a href="https://github.com/rubenluetke"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=96" width="48" height="48" alt="rubenluetke" title="rubenluetke"></a> <a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=96" width="48" height="48" alt="dannyward630" title="dannyward630"></a> <a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=96" width="48" height="48" alt="dennisheidederamirez-coder" title="dennisheidederamirez-coder"></a> <a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=96" width="48" height="48" alt="ANO3457" title="ANO3457"></a> <a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=96" width="48" height="48" alt="PilarJ" title="PilarJ"></a> <a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=96" width="48" height="48" alt="Idee-Wird-App" title="Idee-Wird-App"></a> <a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=96" width="48" height="48" alt="CodeByPeace" title="CodeByPeace"></a> <a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=96" width="48" height="48" alt="jaydenhawkes123" title="jaydenhawkes123"></a> <a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=96" width="48" height="48" alt="alibaba080290" title="alibaba080290"></a> <a href="https://github.com/dovellx"><img src="https://avatars.githubusercontent.com/u/109219673?u=fdc67e8b78b3aa9cd5fb58f3c5a55c3445585c9e&v=4&s=96" width="48" height="48" alt="dovellx" title="dovellx"></a> <!-- i18n-allow -->
<a href="https://github.com/eljeffeg"><img src="https://avatars.githubusercontent.com/u/161904?u=38ce201214d8460536ec43ebb967955704d51345&v=4&s=96" width="48" height="48" alt="eljeffeg" title="eljeffeg"></a> <a href="https://github.com/martiroca06"><img src="https://avatars.githubusercontent.com/u/229811558?v=4&s=96" width="48" height="48" alt="martiroca06" title="martiroca06"></a> <a href="https://github.com/morfeus48235-glitch"><img src="https://avatars.githubusercontent.com/u/297425892?v=4&s=96" width="48" height="48" alt="morfeus48235-glitch" title="morfeus48235-glitch"></a> <a href="https://github.com/Oscar-Williams"><img src="https://avatars.githubusercontent.com/u/319719771?u=43c7bbf42a4f99b44a66bae0c1972b7ed72c44f2&v=4&s=96" width="48" height="48" alt="Oscar-Williams" title="Oscar-Williams"></a> <a href="https://github.com/Sgangalossa"><img src="https://avatars.githubusercontent.com/u/336517156?u=0a255499355232fbf86ae8f56c11ec59c43f76b9&v=4&s=96" width="48" height="48" alt="Sgangalossa" title="Sgangalossa"></a> <a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=96" width="48" height="48" alt="tianxingjian2406" title="tianxingjian2406"></a> <a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=96" width="48" height="48" alt="Uddoo" title="Uddoo"></a> <a href="https://github.com/Virtuluso-azores"><img src="https://avatars.githubusercontent.com/u/263487091?v=4&s=96" width="48" height="48" alt="Virtuluso-azores" title="Virtuluso-azores"></a> <a href="https://github.com/xiangnuans"><img src="https://avatars.githubusercontent.com/u/24558814?v=4&s=96" width="48" height="48" alt="xiangnuans" title="xiangnuans"></a> <a href="https://github.com/YannisG23"><img src="https://avatars.githubusercontent.com/u/132681092?u=f7c0391b17c8490513e6bf5571256291527c12ff&v=4&s=96" width="48" height="48" alt="YannisG23" title="YannisG23"></a> <!-- i18n-allow -->

<!-- contributors:end -->

## الترخيص

يخضع المشروع لرخصة [Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE)،
مع الإسناد الوارد في
[NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE). أما الاسم
والشعار فتشملهما
[سياسة العلامة التجارية](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md).
إن Dodaios مشروع مستقل: المنتجات التي يعمل معها ملك لصانعيها، ودعمه لأداة ما
لا يعني أن صانعها يوافق على Dodaios. وحتى أكتوبر 2026 كان اسمه Personal Jarvis
([لماذا تغيّر الاسم](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)).
تجد الرعاة في [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md).
