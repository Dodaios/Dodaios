<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise: word for word everywhere (docs/positioning.md) -->
<p><b>Todos tus agentes de programación en un solo chat.</b></p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="Última versión" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-FAFAFA?labelColor=0A0A0A" alt="Licencia: MIT" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="Estrellas en GitHub" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://trendshift.io/repositories/91076?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-91076" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/91076" alt="Dodaios%2FDodaios | Trendshift" width="250" height="55"/></a>
</p>

<p>
  <a href="#instalación">Instalación</a> ·
  <a href="#tus-planes-y-claves">Tus planes</a> ·
  <a href="#documentación">Documentación</a> ·
  <a href="https://dodaios.ai">Sitio web</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ja.md">日本語</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.hi.md">हिन्दी</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ar.md">العربية</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.fr.md">Français</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.bn.md">বাংলা</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.pt-BR.md">Português (Brasil)</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ru.md">Русский</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.id.md">Bahasa Indonesia</a>
</p>

</div>

Tienes Claude Code en una terminal, Codex en otra y una pestaña de chat donde
copias planes de un lado a otro. Dodaios acaba con eso. Es una capa por encima
de todos tus agentes de programación: dices lo que quieres, por voz o por chat,
y un asistente se encarga del resto. Escribe las instrucciones, lanza el agente
adecuado en su Agentic IDE integrado, lo vigila mientras trabaja y te avisa
cuando termina o te necesita. Ejecuta cinco agentes a la vez y sabrás
exactamente qué hizo cada uno.

Código abierto, y se ejecuta en tu computadora. Funciona con tu suscripción de
Claude o ChatGPT, con claves de API de Claude, OpenAI y Gemini, o con modelos
locales de Ollama.

https://github.com/user-attachments/assets/37cdc5a5-30d6-49c8-92ff-3454a075569f

<p align="center">
  <sub>Una grabación real a 60 fotogramas por segundo, reproducida a la misma velocidad a la que se grabó; las esperas a los modelos están recortadas. Se grabó con Claude Fable 5.2 y Claude Opus 5.5 a través de Claude Code. El cambio de código, las pruebas y el commit son reales. <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>Ver el video</b></a> (MP4, 42 s, 2,5 MB)</sub>
</p>

## Instalación

macOS y Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

Windows, en PowerShell:

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

El instalador prepara su propio entorno de Python, añade un lanzador y abre la
aplicación. En el primer inicio le das un nombre al asistente (que también es
la palabra de activación), conectas un modelo y eliges cómo quieres hablar con
él. Para programar, instala al menos un agente de programación, como Claude
Code o Codex, e inicia sesión en él.

```bash
dodaios            # start the desktop app
dodaios update     # install the newest release
```

<details>
<summary>Instaladores de escritorio, pipx y servidores</summary>

<br />

Descarga el instalador para tu sistema desde la última versión:

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage, x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

Cada versión incluye las sumas de verificación en `installers-SHA256SUMS.txt`.
Los instaladores todavía no están firmados: Windows muestra una advertencia, y
macOS te pide que permitas la aplicación una vez en Ajustes del Sistema, en
Privacidad y seguridad. La
[política de firma de código](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
explica en qué punto está eso.

Con pipx obtienes el paquete de servidor, más pequeño y sin lanzador de
escritorio. En un servidor Linux sin pantalla, el instalador acepta
`--headless`, y `dodaios serve` inicia solo la interfaz web:

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # browser interface only, for a server without a screen
```

Dodaios funciona en Windows, macOS y Linux basado en glibc, de 64 bits. El
instalador de terminal funciona en x86-64 y Arm64 y necesita Python 3.11 a 3.14
y Git; descarga Python si falta y se ofrece a instalar Git si no está. La
tarjeta gráfica es opcional. Por ahora solo Windows 11 tiene una validación en
vivo registrada.
[Guía de instalación](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[Plataformas compatibles](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[Ejecutarlo en un servidor](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## Tus planes y claves

Dodaios no cuesta nada: no hay cuenta de Dodaios ni plan de pago. No vende
acceso a modelos y nunca inicia sesión por ti. Lanza la herramienta oficial de
línea de comandos de cada agente de programación, y tú inicias sesión en cada
una, así que los agentes funcionan con los planes y las claves que ya tienes.
Claude Code, por ejemplo, necesita un plan de pago de Claude. El uso de cada
servicio se rige por los términos de ese servicio.
[Proveedores y claves de API](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## Conviene saber

- **Tus datos.** Los chats, la memoria, los documentos y los ajustes son
  archivos en la computadora donde se ejecuta Dodaios. Un modelo o un servicio
  conectado recibe lo que necesita para su parte de una petición. El inicio de
  sesión en los plugins de Google, Slack o Figma pasa por un pequeño servicio
  de tokens que mantiene el proyecto.
  [Privacidad y datos locales](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)
- **Preguntar antes.** Un chat nuevo empieza en Bypass permissions, donde no se
  pregunta nada. Elige un modo que pregunte y los cuatro límites estrictos de
  arriba siempre esperarán tu sí.
  [Seguridad y aprobaciones](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)
- **Aún sin terminar.** Las llamadas telefónicas necesitan tu propio número de
  Twilio y son una vista previa temprana. La mayoría de los plugins todavía
  llevan la etiqueta Preview. La app del teléfono es una aplicación web que
  sirve tu computadora.

## Documentación

El [recorrido por las funciones](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)
muestra cada parte en una sola página, con imágenes. Las mismas guías están en
la aplicación, en **Docs**, con búsqueda.
[Configuración inicial](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) ·
[Solución de problemas](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md) ·
[Arquitectura](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)

## Contribuir

Las correcciones, pruebas, informes de plataformas y documentación son
bienvenidos. La
[guía para contribuir](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)
te lleva de un fork a una comprobación superada en unos diez minutos. Las
preguntas e ideas, en [Discord](https://discord.gg/x7USduHxbc).

Gracias a todas las personas que ya han aportado algo aquí:

<!-- contributors:start -->

<a href="https://github.com/rubenluetke"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=96" width="48" height="48" alt="rubenluetke" title="rubenluetke"></a> <a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=96" width="48" height="48" alt="dannyward630" title="dannyward630"></a> <a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=96" width="48" height="48" alt="dennisheidederamirez-coder" title="dennisheidederamirez-coder"></a> <a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=96" width="48" height="48" alt="ANO3457" title="ANO3457"></a> <a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=96" width="48" height="48" alt="PilarJ" title="PilarJ"></a> <a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=96" width="48" height="48" alt="Idee-Wird-App" title="Idee-Wird-App"></a> <a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=96" width="48" height="48" alt="CodeByPeace" title="CodeByPeace"></a> <a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=96" width="48" height="48" alt="jaydenhawkes123" title="jaydenhawkes123"></a> <a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=96" width="48" height="48" alt="alibaba080290" title="alibaba080290"></a> <a href="https://github.com/dovellx"><img src="https://avatars.githubusercontent.com/u/109219673?u=fdc67e8b78b3aa9cd5fb58f3c5a55c3445585c9e&v=4&s=96" width="48" height="48" alt="dovellx" title="dovellx"></a> <!-- i18n-allow -->
<a href="https://github.com/eljeffeg"><img src="https://avatars.githubusercontent.com/u/161904?u=38ce201214d8460536ec43ebb967955704d51345&v=4&s=96" width="48" height="48" alt="eljeffeg" title="eljeffeg"></a> <a href="https://github.com/martiroca06"><img src="https://avatars.githubusercontent.com/u/229811558?v=4&s=96" width="48" height="48" alt="martiroca06" title="martiroca06"></a> <a href="https://github.com/morfeus48235-glitch"><img src="https://avatars.githubusercontent.com/u/297425892?v=4&s=96" width="48" height="48" alt="morfeus48235-glitch" title="morfeus48235-glitch"></a> <a href="https://github.com/Oscar-Williams"><img src="https://avatars.githubusercontent.com/u/319719771?u=43c7bbf42a4f99b44a66bae0c1972b7ed72c44f2&v=4&s=96" width="48" height="48" alt="Oscar-Williams" title="Oscar-Williams"></a> <a href="https://github.com/Sgangalossa"><img src="https://avatars.githubusercontent.com/u/336517156?u=0a255499355232fbf86ae8f56c11ec59c43f76b9&v=4&s=96" width="48" height="48" alt="Sgangalossa" title="Sgangalossa"></a> <a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=96" width="48" height="48" alt="tianxingjian2406" title="tianxingjian2406"></a> <a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=96" width="48" height="48" alt="Uddoo" title="Uddoo"></a> <a href="https://github.com/Virtuluso-azores"><img src="https://avatars.githubusercontent.com/u/263487091?v=4&s=96" width="48" height="48" alt="Virtuluso-azores" title="Virtuluso-azores"></a> <a href="https://github.com/xiangnuans"><img src="https://avatars.githubusercontent.com/u/24558814?v=4&s=96" width="48" height="48" alt="xiangnuans" title="xiangnuans"></a> <a href="https://github.com/YannisG23"><img src="https://avatars.githubusercontent.com/u/132681092?u=f7c0391b17c8490513e6bf5571256291527c12ff&v=4&s=96" width="48" height="48" alt="YannisG23" title="YannisG23"></a> <!-- i18n-allow -->

<!-- contributors:end -->

## Licencia

[MIT License](https://github.com/Dodaios/Dodaios/blob/main/LICENSE),
con la atribución en
[NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE). El nombre y el
logotipo están cubiertos por la
[política de marca](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md).
Dodaios es un proyecto independiente: los productos con los que funciona
pertenecen a sus creadores, y que admita una herramienta no significa que su
creador respalde Dodaios.
Hasta octubre de 2026 se llamaba Personal Jarvis
([por qué cambió el nombre](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)).
Los patrocinadores están en [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md).
