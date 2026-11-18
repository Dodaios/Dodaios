<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise: word for word everywhere (docs/positioning.md) -->
<p><b>Votre chef de cabinet pour agents de code.</b></p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="Dernière version" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="Licence : Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="Étoiles GitHub" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://trendshift.io/repositories/91076?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-91076" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/91076" alt="Dodaios%2FDodaios | Trendshift" width="250" height="55"/></a>
</p>

<p>
  <a href="#installation">Installation</a> ·
  <a href="#vos-abonnements-et-vos-clés">Vos abonnements</a> ·
  <a href="#documentation">Documentation</a> ·
  <a href="https://dodaios.ai">Site web</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ja.md">日本語</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.es.md">Español</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.hi.md">हिन्दी</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ar.md">العربية</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.bn.md">বাংলা</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.pt-BR.md">Português (Brasil)</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ru.md">Русский</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.id.md">Bahasa Indonesia</a>
</p>

</div>

Vous avez Claude Code dans un terminal, Codex dans un autre, et un onglet de
chat où vous copiez des plans dans un sens puis dans l'autre. Dodaios met fin à
cela. C'est une couche au-dessus de tous vos agents de code : vous dites ce que
vous voulez, à la voix ou par chat, et un seul assistant prend le relais. Il
rédige le brief, lance le bon agent dans son Agentic IDE intégré, le surveille
pendant qu'il travaille et vous prévient quand il a fini ou a besoin de vous.
Lancez cinq agents à la fois et sachez exactement ce que chacun a fait.

Open source, et il tourne sur votre ordinateur. Fonctionne avec votre
abonnement Claude ou ChatGPT, avec des clés API Claude, OpenAI et Gemini, ou
avec des modèles Ollama locaux.

https://github.com/user-attachments/assets/37cdc5a5-30d6-49c8-92ff-3454a075569f

<p align="center">
  <sub>Un vrai enregistrement à 60 images par seconde, lu à la vitesse du tournage ; les temps d'attente des modèles ont été coupés. Il a été enregistré avec Claude Fable 5.2 et Claude Opus 5.5 via Claude Code. La modification du code, les exécutions de tests et le commit sont réels. <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>Voir la vidéo</b></a> (MP4, 42 s, 2,5 Mo)</sub>
</p>

## Installation

macOS et Linux :

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

Windows, dans PowerShell :

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

L'installateur met en place son propre environnement Python, ajoute un lanceur
et ouvre l'application. Au premier démarrage, vous donnez un nom à l'assistant
(c'est aussi le mot d'activation), vous connectez un modèle et vous choisissez
comment lui parler. Pour le travail de code, installez au moins un agent de
code, comme Claude Code ou Codex, et connectez-vous-y.

```bash
dodaios            # start the desktop app
dodaios update     # install the newest release
```

<details>
<summary>Installateurs de bureau, pipx et serveurs</summary>

<br />

Téléchargez l'installateur pour votre système depuis la dernière version :

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage, x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

Chaque version indique les sommes de contrôle dans `installers-SHA256SUMS.txt`.
Les installateurs ne sont pas encore signés : Windows affiche un avertissement,
et macOS vous demande d'autoriser l'application une fois dans Réglages Système,
sous Confidentialité et sécurité. La
[politique de signature du code](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
explique où en est ce point.

Avec pipx, vous obtenez le paquet serveur, plus léger, sans lanceur de bureau.
Sur un serveur Linux sans écran, l'installateur accepte `--headless`, et
`dodaios serve` ne démarre que l'interface web :

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # browser interface only, for a server without a screen
```

Dodaios fonctionne sous Windows, macOS et Linux basé sur glibc, en 64 bits.
L'installateur en ligne de commande fonctionne sur x86-64 et Arm64 et nécessite
Python 3.11 à 3.14 et Git ; il récupère Python s'il manque et propose
d'installer Git s'il manque. Une carte graphique est facultative. Pour
l'instant, seul Windows 11 a une validation en conditions réelles consignée.
[Guide d'installation](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[Plateformes prises en charge](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[L'exécuter sur un serveur](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## Vos abonnements et vos clés

Dodaios ne coûte rien : pas de compte Dodaios, pas d'offre payante. Il ne vend
aucun accès à des modèles et ne se connecte jamais à votre place. Il lance
l'outil en ligne de commande officiel de chaque agent de code, et vous vous
connectez vous-même à chacun d'eux : les agents tournent donc avec les
abonnements et les clés que vous avez déjà. Claude Code, par exemple, nécessite
un abonnement Claude payant. Votre utilisation de chaque service est régie par
les conditions propres à ce service.
[Fournisseurs et clés API](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## Bon à savoir

- **Vos données.** Les chats, la mémoire, les documents et les réglages sont
  des fichiers sur l'ordinateur qui exécute Dodaios. Un modèle ou un service
  connecté reçoit ce dont il a besoin pour sa part d'une requête. La connexion
  aux plugins Google, Slack ou Figma passe par un petit service de jetons que
  le projet fait tourner.
  [Confidentialité et données locales](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)
- **Demander d'abord.** Un nouveau chat démarre en Bypass permissions, où rien
  n'est demandé. Choisissez un mode qui demande, et les quatre limites strictes
  ci-dessus attendront toujours votre accord.
  [Sécurité et approbations](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)
- **Pas encore terminé.** Les appels téléphoniques nécessitent votre propre
  numéro Twilio et sont en avant-première. La plupart des plugins portent
  encore un badge Preview. L'application mobile est une application web servie
  par votre ordinateur.

## Documentation

La [visite des fonctionnalités](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)
présente chaque partie sur une seule page, avec des images. Les mêmes guides se
trouvent dans l'application sous **Docs**, avec une recherche.
[Premier démarrage](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) ·
[Dépannage](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md) ·
[Architecture](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)

## Contribuer

Les correctifs, les tests, les retours sur les plateformes et la documentation
sont les bienvenus. Le
[guide de contribution](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)
vous mène d'un fork à une vérification réussie en une dizaine de minutes. Les
questions et les idées, c'est sur [Discord](https://discord.gg/x7USduHxbc).

Merci à toutes celles et ceux qui ont livré quelque chose ici :

<!-- contributors:start -->

<a href="https://github.com/rubenluetke"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=96" width="48" height="48" alt="rubenluetke" title="rubenluetke"></a> <a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=96" width="48" height="48" alt="dannyward630" title="dannyward630"></a> <a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=96" width="48" height="48" alt="dennisheidederamirez-coder" title="dennisheidederamirez-coder"></a> <a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=96" width="48" height="48" alt="ANO3457" title="ANO3457"></a> <a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=96" width="48" height="48" alt="PilarJ" title="PilarJ"></a> <a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=96" width="48" height="48" alt="Idee-Wird-App" title="Idee-Wird-App"></a> <a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=96" width="48" height="48" alt="CodeByPeace" title="CodeByPeace"></a> <a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=96" width="48" height="48" alt="jaydenhawkes123" title="jaydenhawkes123"></a> <a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=96" width="48" height="48" alt="alibaba080290" title="alibaba080290"></a> <a href="https://github.com/dovellx"><img src="https://avatars.githubusercontent.com/u/109219673?u=fdc67e8b78b3aa9cd5fb58f3c5a55c3445585c9e&v=4&s=96" width="48" height="48" alt="dovellx" title="dovellx"></a> <!-- i18n-allow -->
<a href="https://github.com/eljeffeg"><img src="https://avatars.githubusercontent.com/u/161904?u=38ce201214d8460536ec43ebb967955704d51345&v=4&s=96" width="48" height="48" alt="eljeffeg" title="eljeffeg"></a> <a href="https://github.com/martiroca06"><img src="https://avatars.githubusercontent.com/u/229811558?v=4&s=96" width="48" height="48" alt="martiroca06" title="martiroca06"></a> <a href="https://github.com/morfeus48235-glitch"><img src="https://avatars.githubusercontent.com/u/297425892?v=4&s=96" width="48" height="48" alt="morfeus48235-glitch" title="morfeus48235-glitch"></a> <a href="https://github.com/Oscar-Williams"><img src="https://avatars.githubusercontent.com/u/319719771?u=43c7bbf42a4f99b44a66bae0c1972b7ed72c44f2&v=4&s=96" width="48" height="48" alt="Oscar-Williams" title="Oscar-Williams"></a> <a href="https://github.com/Sgangalossa"><img src="https://avatars.githubusercontent.com/u/336517156?u=0a255499355232fbf86ae8f56c11ec59c43f76b9&v=4&s=96" width="48" height="48" alt="Sgangalossa" title="Sgangalossa"></a> <a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=96" width="48" height="48" alt="tianxingjian2406" title="tianxingjian2406"></a> <a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=96" width="48" height="48" alt="Uddoo" title="Uddoo"></a> <a href="https://github.com/Virtuluso-azores"><img src="https://avatars.githubusercontent.com/u/263487091?v=4&s=96" width="48" height="48" alt="Virtuluso-azores" title="Virtuluso-azores"></a> <a href="https://github.com/xiangnuans"><img src="https://avatars.githubusercontent.com/u/24558814?v=4&s=96" width="48" height="48" alt="xiangnuans" title="xiangnuans"></a> <a href="https://github.com/YannisG23"><img src="https://avatars.githubusercontent.com/u/132681092?u=f7c0391b17c8490513e6bf5571256291527c12ff&v=4&s=96" width="48" height="48" alt="YannisG23" title="YannisG23"></a> <!-- i18n-allow -->

<!-- contributors:end -->

## Licence

[Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE),
avec l'attribution figurant dans
[NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE). Le nom et le
logo sont couverts par la
[politique de marque](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md).
Dodaios est un projet indépendant : les produits avec lesquels il fonctionne
appartiennent à leurs éditeurs, et la prise en charge d'un outil ne signifie pas
que son éditeur approuve Dodaios.
Jusqu'en octobre 2026, il s'appelait Personal Jarvis
([pourquoi le nom a changé](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)).
Les sponsors figurent dans [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md).
