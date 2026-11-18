<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise: word for word everywhere (docs/positioning.md) -->
<p><b>Будьте CEO своих агентов для программирования, а не их нянькой.</b></p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="Последний релиз" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="Лицензия: Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="Звёзды на GitHub" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://trendshift.io/repositories/91076?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-91076" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/91076" alt="Dodaios%2FDodaios | Trendshift" width="250" height="55"/></a>
</p>

<p>
  <a href="#установка">Установка</a> ·
  <a href="#ваши-подписки-и-ключи">Ваши подписки</a> ·
  <a href="#документация">Документация</a> ·
  <a href="https://dodaios.ai">Сайт</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ja.md">日本語</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.es.md">Español</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.hi.md">हिन्दी</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ar.md">العربية</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.fr.md">Français</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.bn.md">বাংলা</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.pt-BR.md">Português (Brasil)</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.id.md">Bahasa Indonesia</a>
</p>

</div>

У вас Claude Code в одном терминале, Codex в другом и вкладка чата, куда вы
копируете планы туда и обратно. Dodaios с этим покончит. Это слой над всеми
вашими агентами для программирования: вы говорите, что нужно, голосом или в
чате, а дальше всё берёт на себя один ассистент. Он пишет задание, запускает
нужного агента во встроенной Agentic IDE, следит за его работой и сообщает,
когда тот закончил или вы ему нужны. Запустите пять агентов одновременно и
точно знайте, что сделал каждый.

Открытый исходный код, работает на вашем компьютере. Подходит ваша подписка
Claude или ChatGPT, API-ключи Claude, OpenAI и Gemini или локальные модели
Ollama.

https://github.com/user-attachments/assets/37cdc5a5-30d6-49c8-92ff-3454a075569f

<p align="center">
  <sub>Настоящая запись с частотой 60 кадров в секунду, воспроизведённая с той скоростью, с какой она снималась; ожидание ответов моделей вырезано. Записано с Claude Fable 5.2 и Claude Opus 5.5 через Claude Code. Изменение кода, запуски тестов и коммит — настоящие. <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>Смотреть видео</b></a> (MP4, 42 с, 2,5 МБ)</sub>
</p>

## Установка

macOS и Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

Windows, в PowerShell:

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

Установщик создаёт собственное окружение Python, добавляет ярлык запуска и
открывает приложение. При первом запуске вы даёте ассистенту имя (оно же
служит словом активации), подключаете одну модель и выбираете, как будете с
ним общаться. Для работы с кодом установите хотя бы одного агента для
программирования, например Claude Code или Codex, и войдите в него.

```bash
dodaios            # start the desktop app
dodaios update     # install the newest release
```

<details>
<summary>Настольные установщики, pipx и серверы</summary>

<br />

Скачайте установщик для своей системы из последнего релиза:

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage, x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

В каждом релизе контрольные суммы указаны в `installers-SHA256SUMS.txt`.
Установщики пока не подписаны: Windows показывает предупреждение, а macOS
просит один раз разрешить приложение в Системных настройках, в разделе
«Конфиденциальность и безопасность». О текущем положении дел говорится в
[политике подписи кода](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md).

Через pipx вы получаете более лёгкий серверный пакет, без ярлыка на рабочем
столе. На Linux-сервере без экрана установщик принимает `--headless`, а
`dodaios serve` запускает только веб-интерфейс:

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # browser interface only, for a server without a screen
```

Dodaios работает на 64-битных Windows, macOS и Linux на базе glibc.
Установщик для терминала работает на x86-64 и Arm64, ему нужны Python от 3.11
до 3.14 и Git; недостающий Python он скачает сам, а недостающий Git предложит
установить. Видеокарта не обязательна. Пока что задокументированная проверка
в реальной работе есть только для Windows 11.
[Руководство по установке](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[Поддерживаемые платформы](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[Запуск на сервере](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## Ваши подписки и ключи

Dodaios ничего не стоит: ни аккаунта Dodaios, ни платного тарифа. Он не
продаёт доступ к моделям и никогда не входит в сервисы за вас. Он запускает
официальную консольную утилиту каждого агента для программирования, а входите
в каждую из них вы сами, поэтому агенты работают на тех подписках и ключах,
которые у вас уже есть. Например, для Claude Code нужна платная подписка
Claude. Использование каждого сервиса регулируется его собственными условиями.
[Провайдеры и API-ключи](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## Полезно знать

- **Ваши данные.** Чаты, память, документы и настройки — это файлы на
  компьютере, на котором работает Dodaios. Модель или подключённый сервис
  получает то, что нужно для его части запроса. Вход в плагины Google, Slack
  или Figma проходит через небольшой сервис токенов, который поддерживает проект.
  [Конфиденциальность и локальные данные](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)
- **Сначала спросить.** Новый чат начинается в режиме Bypass permissions, где
  ничего не спрашивается. Выберите режим с запросами — и четыре жёстких
  ограничения, описанных выше, всегда будут ждать вашего согласия.
  [Безопасность и подтверждения](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)
- **Ещё не готово.** Для телефонных звонков нужен собственный номер Twilio, и
  это ранняя предварительная версия. Большинство плагинов пока помечены
  значком Preview. Мобильное приложение — это веб-приложение, которое отдаёт
  ваш компьютер.

## Документация

[Обзор возможностей](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)
показывает все части на одной странице, с картинками. Те же руководства есть в
приложении в разделе **Docs**, с поиском.
[Первая настройка](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) ·
[Устранение неполадок](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md) ·
[Архитектура](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)

## Участие в разработке

Мы рады исправлениям, тестам, отчётам о работе на разных платформах и
документации.
[Руководство для участников](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)
проведёт вас от форка до пройденной проверки примерно за десять минут.
Вопросы и идеи — в [Discord](https://discord.gg/x7USduHxbc).

Спасибо всем, кто уже что-то здесь выпустил:

<!-- contributors:start -->

<a href="https://github.com/rubenluetke"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=96" width="48" height="48" alt="rubenluetke" title="rubenluetke"></a> <a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=96" width="48" height="48" alt="dannyward630" title="dannyward630"></a> <a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=96" width="48" height="48" alt="dennisheidederamirez-coder" title="dennisheidederamirez-coder"></a> <a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=96" width="48" height="48" alt="ANO3457" title="ANO3457"></a> <a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=96" width="48" height="48" alt="PilarJ" title="PilarJ"></a> <a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=96" width="48" height="48" alt="Idee-Wird-App" title="Idee-Wird-App"></a> <a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=96" width="48" height="48" alt="CodeByPeace" title="CodeByPeace"></a> <a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=96" width="48" height="48" alt="jaydenhawkes123" title="jaydenhawkes123"></a> <a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=96" width="48" height="48" alt="alibaba080290" title="alibaba080290"></a> <a href="https://github.com/dovellx"><img src="https://avatars.githubusercontent.com/u/109219673?u=fdc67e8b78b3aa9cd5fb58f3c5a55c3445585c9e&v=4&s=96" width="48" height="48" alt="dovellx" title="dovellx"></a> <!-- i18n-allow -->
<a href="https://github.com/eljeffeg"><img src="https://avatars.githubusercontent.com/u/161904?u=38ce201214d8460536ec43ebb967955704d51345&v=4&s=96" width="48" height="48" alt="eljeffeg" title="eljeffeg"></a> <a href="https://github.com/martiroca06"><img src="https://avatars.githubusercontent.com/u/229811558?v=4&s=96" width="48" height="48" alt="martiroca06" title="martiroca06"></a> <a href="https://github.com/morfeus48235-glitch"><img src="https://avatars.githubusercontent.com/u/297425892?v=4&s=96" width="48" height="48" alt="morfeus48235-glitch" title="morfeus48235-glitch"></a> <a href="https://github.com/Oscar-Williams"><img src="https://avatars.githubusercontent.com/u/319719771?u=43c7bbf42a4f99b44a66bae0c1972b7ed72c44f2&v=4&s=96" width="48" height="48" alt="Oscar-Williams" title="Oscar-Williams"></a> <a href="https://github.com/Sgangalossa"><img src="https://avatars.githubusercontent.com/u/336517156?u=0a255499355232fbf86ae8f56c11ec59c43f76b9&v=4&s=96" width="48" height="48" alt="Sgangalossa" title="Sgangalossa"></a> <a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=96" width="48" height="48" alt="tianxingjian2406" title="tianxingjian2406"></a> <a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=96" width="48" height="48" alt="Uddoo" title="Uddoo"></a> <a href="https://github.com/Virtuluso-azores"><img src="https://avatars.githubusercontent.com/u/263487091?v=4&s=96" width="48" height="48" alt="Virtuluso-azores" title="Virtuluso-azores"></a> <a href="https://github.com/xiangnuans"><img src="https://avatars.githubusercontent.com/u/24558814?v=4&s=96" width="48" height="48" alt="xiangnuans" title="xiangnuans"></a> <a href="https://github.com/YannisG23"><img src="https://avatars.githubusercontent.com/u/132681092?u=f7c0391b17c8490513e6bf5571256291527c12ff&v=4&s=96" width="48" height="48" alt="YannisG23" title="YannisG23"></a> <!-- i18n-allow -->

<!-- contributors:end -->

## Лицензия

[Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE),
с указанием авторства в
[NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE). Название и
логотип защищены
[политикой в отношении товарных знаков](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md).
Dodaios — независимый проект: продукты, с которыми он работает, принадлежат их
создателям, и поддержка какого-либо инструмента не означает, что его создатель
одобряет Dodaios.
До октября 2026 года проект назывался Personal Jarvis
([почему сменилось название](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)).
Спонсоры перечислены в [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md).
