<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise: word for word everywhere (docs/positioning.md) -->
<p><b>अपने कोडिंग एजेंटों के CEO बनें, बेबीसिटर नहीं।</b></p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="नई रिलीज़" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="लाइसेंस: Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="GitHub स्टार" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://trendshift.io/repositories/91076?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-91076" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/91076" alt="Dodaios%2FDodaios | Trendshift" width="250" height="55"/></a>
</p>

<p>
  <a href="#इंस्टॉल">इंस्टॉल</a> ·
  <a href="#आपके-प्लान-और-कीज़">आपके प्लान</a> ·
  <a href="#डॉक्यूमेंटेशन">डॉक्यूमेंटेशन</a> ·
  <a href="https://dodaios.ai">वेबसाइट</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ja.md">日本語</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.es.md">Español</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ar.md">العربية</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.fr.md">Français</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.bn.md">বাংলা</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.pt-BR.md">Português (Brasil)</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ru.md">Русский</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.id.md">Bahasa Indonesia</a>
</p>

</div>

एक टर्मिनल में Claude Code, दूसरे में Codex, और एक चैट टैब जहाँ आप योजनाएँ इधर-उधर कॉपी करते रहते हैं। Dodaios इसे खत्म करता है। यह आपके सभी कोडिंग एजेंटों के ऊपर एक परत है: आप आवाज़ या चैट से बताते हैं कि आपको क्या चाहिए, और एक असिस्टेंट आगे का काम संभाल लेता है। यह ब्रीफ़ लिखता है, अपने बिल्ट-इन Agentic IDE में सही एजेंट शुरू करता है, काम के दौरान नज़र रखता है, और काम पूरा होने पर या आपकी ज़रूरत पड़ने पर आपको बताता है। एक साथ पाँच एजेंट चलाइए और फिर भी ठीक-ठीक जानिए कि हर एक ने क्या किया।

ओपन सोर्स, और आपके कंप्यूटर पर चलता है। आपके Claude या ChatGPT सब्सक्रिप्शन, Claude, OpenAI और Gemini की API कुंजियों, या लोकल Ollama मॉडल के साथ काम करता है।

https://github.com/user-attachments/assets/37cdc5a5-30d6-49c8-92ff-3454a075569f

<p align="center">
  <sub>60 फ़्रेम प्रति सेकंड की एक असली रिकॉर्डिंग, उसी स्पीड पर चलाई गई जिस पर इसे फ़िल्माया गया था; मॉडल के इंतज़ार वाले हिस्से काट दिए गए हैं। इसे Claude Code के ज़रिए Claude Fable 5.2 और Claude Opus 5.5 के साथ रिकॉर्ड किया गया। कोड में बदलाव, टेस्ट रन और कमिट असली हैं। <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>वीडियो देखें</b></a> (MP4, 42 सेकंड, 2.5 MB)</sub>
</p>

## इंस्टॉल

macOS और Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

Windows, PowerShell में:

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

इंस्टॉलर अपना अलग Python एनवायरनमेंट सेट करता है, एक लॉन्चर जोड़ता है और ऐप खोल
देता है। पहली बार शुरू करने पर आप असिस्टेंट को एक नाम देते हैं (यही वेक वर्ड भी है),
एक मॉडल जोड़ते हैं और चुनते हैं कि उससे कैसे बात करनी है। कोडिंग के काम के लिए कम से कम
एक कोडिंग एजेंट, जैसे Claude Code या Codex, इंस्टॉल करें और उसमें साइन इन करें।

```bash
dodaios            # start the desktop app
dodaios update     # install the newest release
```

<details>
<summary>डेस्कटॉप इंस्टॉलर, pipx और सर्वर</summary>

<br />

नई रिलीज़ से अपने सिस्टम के लिए इंस्टॉलर डाउनलोड करें:

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage, x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

हर रिलीज़ के checksum `installers-SHA256SUMS.txt` में दिए होते हैं। इंस्टॉलर अभी साइन
नहीं किए गए हैं: Windows एक चेतावनी दिखाता है, और macOS आपसे System Settings में,
Privacy & Security के अंदर, ऐप को एक बार अनुमति देने को कहता है। यह काम कहाँ तक पहुँचा
है, यह
[कोड साइनिंग पॉलिसी](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
में लिखा है।

pipx से आपको छोटा सर्वर पैकेज मिलता है, जिसमें डेस्कटॉप लॉन्चर नहीं होता। बिना स्क्रीन
वाले Linux सर्वर पर इंस्टॉलर `--headless` लेता है, और `dodaios serve` सिर्फ़ ब्राउज़र
इंटरफ़ेस शुरू करता है:

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # browser interface only, for a server without a screen
```

Dodaios 64-बिट Windows, macOS और glibc पर आधारित Linux पर चलता है। टर्मिनल इंस्टॉलर
x86-64 और Arm64 पर काम करता है और इसके लिए Python 3.11 से 3.14 और Git चाहिए; Python न
हो तो यह उसे ले आता है, और Git न हो तो उसे इंस्टॉल करने का विकल्प देता है। ग्राफ़िक्स
कार्ड ज़रूरी नहीं है। अब तक सिर्फ़ Windows 11 पर ही असली मशीन पर जाँच की मंज़ूरी दर्ज है।
[इंस्टॉल गाइड](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[प्लेटफ़ॉर्म सपोर्ट](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[सर्वर पर चलाना](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## आपके प्लान और कीज़

Dodaios का कोई खर्च नहीं है: न कोई Dodaios अकाउंट, न कोई पेड टियर। यह मॉडल का
एक्सेस नहीं बेचता और कभी आपकी जगह साइन इन नहीं करता। यह हर कोडिंग एजेंट का आधिकारिक
कमांड-लाइन टूल शुरू करता है, और हर एक में आप खुद साइन इन करते हैं, इसलिए एजेंट उन्हीं
प्लान और कीज़ पर चलते हैं जो आपके पास पहले से हैं। उदाहरण के लिए, Claude Code के लिए
पेड Claude प्लान चाहिए। हर सर्विस का इस्तेमाल उसी सर्विस की अपनी शर्तों के हिसाब से होता है।
[प्रोवाइडर और API कीज़](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## जानने लायक बातें

- **आपका डेटा।** चैट, मेमोरी, डॉक्यूमेंट और सेटिंग्स उसी कंप्यूटर पर फ़ाइलों के रूप में
  रहती हैं जिस पर Dodaios चलता है। किसी मॉडल या जुड़ी हुई सर्विस को सिर्फ़ उतना मिलता है
  जितना उसे किसी रिक्वेस्ट में अपने हिस्से के लिए चाहिए। Google, Slack या Figma प्लगइन
  में साइन इन एक छोटी token सर्विस से होकर जाता है, जिसे यह प्रोजेक्ट चलाता है।
  [प्राइवेसी और लोकल डेटा](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)
- **पहले पूछना।** नई चैट Bypass permissions पर शुरू होती है, जहाँ कुछ भी नहीं पूछा
  जाता। पूछने वाला कोई मोड चुनें, तो ऊपर बताई गई चार पक्की सीमाएँ हमेशा आपकी हाँ का
  इंतज़ार करती हैं।
  [सुरक्षा और मंज़ूरी](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)
- **अभी अधूरा।** फ़ोन कॉल के लिए आपका अपना Twilio नंबर चाहिए और यह अभी शुरुआती
  प्रीव्यू है। ज़्यादातर प्लगइन पर अभी भी Preview बैज लगा है। फ़ोन ऐप एक वेब ऐप है,
  जिसे आपका कंप्यूटर सर्व करता है।

## डॉक्यूमेंटेशन

[फ़ीचर टूर](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)
हर हिस्से को एक ही पेज पर, तस्वीरों के साथ दिखाता है। यही गाइड ऐप में **Docs** के
अंदर भी हैं, सर्च के साथ।
[पहली बार सेटअप](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) ·
[समस्या का हल](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md) ·
[आर्किटेक्चर](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)

## योगदान

फ़िक्स, टेस्ट, प्लेटफ़ॉर्म रिपोर्ट और डॉक्यूमेंटेशन का स्वागत है।
[योगदान गाइड](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)
आपको fork से लेकर पास होने वाले चेक तक लगभग दस मिनट में पहुँचा देती है। सवाल और
आइडिया [Discord](https://discord.gg/x7USduHxbc) पर भेजें।

उन सभी का शुक्रिया जिन्होंने यहाँ कुछ न कुछ शिप किया है:

<!-- contributors:start -->

<a href="https://github.com/rubenluetke"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=96" width="48" height="48" alt="rubenluetke" title="rubenluetke"></a> <a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=96" width="48" height="48" alt="dannyward630" title="dannyward630"></a> <a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=96" width="48" height="48" alt="dennisheidederamirez-coder" title="dennisheidederamirez-coder"></a> <a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=96" width="48" height="48" alt="ANO3457" title="ANO3457"></a> <a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=96" width="48" height="48" alt="PilarJ" title="PilarJ"></a> <a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=96" width="48" height="48" alt="Idee-Wird-App" title="Idee-Wird-App"></a> <a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=96" width="48" height="48" alt="CodeByPeace" title="CodeByPeace"></a> <a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=96" width="48" height="48" alt="jaydenhawkes123" title="jaydenhawkes123"></a> <a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=96" width="48" height="48" alt="alibaba080290" title="alibaba080290"></a> <a href="https://github.com/dovellx"><img src="https://avatars.githubusercontent.com/u/109219673?u=fdc67e8b78b3aa9cd5fb58f3c5a55c3445585c9e&v=4&s=96" width="48" height="48" alt="dovellx" title="dovellx"></a> <!-- i18n-allow -->
<a href="https://github.com/eljeffeg"><img src="https://avatars.githubusercontent.com/u/161904?u=38ce201214d8460536ec43ebb967955704d51345&v=4&s=96" width="48" height="48" alt="eljeffeg" title="eljeffeg"></a> <a href="https://github.com/martiroca06"><img src="https://avatars.githubusercontent.com/u/229811558?v=4&s=96" width="48" height="48" alt="martiroca06" title="martiroca06"></a> <a href="https://github.com/morfeus48235-glitch"><img src="https://avatars.githubusercontent.com/u/297425892?v=4&s=96" width="48" height="48" alt="morfeus48235-glitch" title="morfeus48235-glitch"></a> <a href="https://github.com/Oscar-Williams"><img src="https://avatars.githubusercontent.com/u/319719771?u=43c7bbf42a4f99b44a66bae0c1972b7ed72c44f2&v=4&s=96" width="48" height="48" alt="Oscar-Williams" title="Oscar-Williams"></a> <a href="https://github.com/Sgangalossa"><img src="https://avatars.githubusercontent.com/u/336517156?u=0a255499355232fbf86ae8f56c11ec59c43f76b9&v=4&s=96" width="48" height="48" alt="Sgangalossa" title="Sgangalossa"></a> <a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=96" width="48" height="48" alt="tianxingjian2406" title="tianxingjian2406"></a> <a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=96" width="48" height="48" alt="Uddoo" title="Uddoo"></a> <a href="https://github.com/Virtuluso-azores"><img src="https://avatars.githubusercontent.com/u/263487091?v=4&s=96" width="48" height="48" alt="Virtuluso-azores" title="Virtuluso-azores"></a> <a href="https://github.com/xiangnuans"><img src="https://avatars.githubusercontent.com/u/24558814?v=4&s=96" width="48" height="48" alt="xiangnuans" title="xiangnuans"></a> <a href="https://github.com/YannisG23"><img src="https://avatars.githubusercontent.com/u/132681092?u=f7c0391b17c8490513e6bf5571256291527c12ff&v=4&s=96" width="48" height="48" alt="YannisG23" title="YannisG23"></a> <!-- i18n-allow -->

<!-- contributors:end -->

## लाइसेंस

[Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE),
साथ में
[NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE) में दिया गया attribution।
नाम और लोगो
[ट्रेडमार्क पॉलिसी](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md)
के दायरे में आते हैं। Dodaios एक स्वतंत्र प्रोजेक्ट है: जिन प्रोडक्ट के साथ यह काम करता है,
वे उनके बनाने वालों के हैं, और किसी टूल को सपोर्ट करने का मतलब यह नहीं है कि उसका बनाने
वाला Dodaios को मंज़ूरी देता है। अक्टूबर 2026 तक इसका नाम Personal Jarvis था
([नाम क्यों बदला](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/))।
स्पॉन्सर [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md) में हैं।
