<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise and the definition: word for word everywhere (docs/positioning.md) -->
<p><b>Um assistente comandado por voz que dirige seus modelos, seus agentes de programação e seu computador.</b></p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="Última versão" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="Licença: Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="Estrelas no GitHub" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://trendshift.io/repositories/91076?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-91076" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/91076" alt="Dodaios%2FDodaios | Trendshift" width="250" height="55"/></a>
</p>

<p>
  <a href="#instalação">Instalação</a> ·
  <a href="#seus-planos-e-chaves">Seus planos</a> ·
  <a href="#documentação">Documentação</a> ·
  <a href="https://dodaios.ai">Site</a> ·
  <a href="https://discord.gg/x7USduHxbc">Discord</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.md">English</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.zh-CN.md">简体中文</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ja.md">日本語</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.es.md">Español</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.hi.md">हिन्दी</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ar.md">العربية</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.fr.md">Français</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.bn.md">বাংলা</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ru.md">Русский</a> ·
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.id.md">Bahasa Indonesia</a>
</p>

</div>

O Dodaios é um programa de código aberto em Python, instalado localmente, que
roda como aplicativo de desktop ou como servidor sem tela com interface no
navegador, no Windows, no macOS e no Linux. Ele transforma um assistente
pessoal de IA na central de controle do trabalho que você faz no computador.

No centro fica um assistente "principal" com quem você pode falar por voz
(palavra de ativação, ditado, conversa falada em tempo real e, como prévia
inicial, chamadas telefônicas), pelo chat ou por um celular pareado. Ele não
fica preso a um único provedor e funciona com Claude, OpenAI, Gemini ou modelos
locais do Ollama. Ele resolve tarefas sozinho usando ferramentas, uso do
computador, plugins, CLIs e servidores MCP. Acima de tudo, ele repassa o
trabalho para agentes de programação. Eles rodam lado a lado em um Agentic IDE
integrado, como terminais reais do Claude Code ou do Codex, no seu computador
ou nos seus próprios servidores via SSH. Cada um tem um codinome pelo qual você
pode chamá-lo, e há integração com Git e divisão de tarefas. Existe ainda uma
"sociedade" de agentes persistentes, com nome, que trocam mensagens entre si.

O trabalho de longo prazo fica por conta da memória (sobre você, as pessoas ao
seu redor e a própria persona do assistente), tarefas permanentes, fluxos de
trabalho, skills e uma administração opcional da vida pessoal. O assistente
também cria os próprios resultados, como documentos, apresentações, planilhas
e painéis, e pode propor e construir as skills, rotinas e agentes que estão
faltando. Uma camada de confiança define limites rígidos: fora do Bypass
permissions, movimentar dinheiro, lidar com credenciais, excluir algo de forma
permanente e o primeiro contato com alguém novo sempre precisam da sua
confirmação. Em resumo, o Dodaios é um sistema operacional para agentes de IA,
comandado por voz e rodando localmente, que faz de um único assistente o
maestro dos seus modelos, dos seus agentes de programação e do seu próprio
computador.

https://github.com/user-attachments/assets/37cdc5a5-30d6-49c8-92ff-3454a075569f

<p align="center">
  <sub>Uma gravação real a 60 quadros por segundo, reproduzida na mesma velocidade em que foi gravada; as esperas pelos modelos foram cortadas. Foi gravada com Claude Fable 5.2 e Claude Opus 5.5 pelo Claude Code. A alteração no código, os testes e o commit são reais. <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>Assistir ao vídeo</b></a> (MP4, 42 s, 2,5 MB)</sub>
</p>

## Instalação

macOS e Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

Windows, no PowerShell:

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

O instalador configura o próprio ambiente Python, adiciona um atalho de
inicialização e abre o aplicativo. Na primeira execução, você dá um nome ao
assistente (que também é a palavra de ativação), conecta um modelo e escolhe
como quer falar com ele. Para programar, instale pelo menos um agente de
programação, como o Claude Code ou o Codex, e faça login nele.

```bash
dodaios            # start the desktop app
dodaios update     # install the newest release
```

<details>
<summary>Instaladores de desktop, pipx e servidores</summary>

<br />

Baixe o instalador para o seu sistema na versão mais recente:

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage, x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

Cada versão traz os checksums em `installers-SHA256SUMS.txt`. Os instaladores
ainda não são assinados: o Windows mostra um aviso, e o macOS pede que você
permita o aplicativo uma vez em Ajustes do Sistema, em Privacidade e
Segurança. A
[política de assinatura de código](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
explica em que pé isso está.

Com o pipx você instala o pacote de servidor, menor e sem atalho de desktop. Em
um servidor Linux sem tela, o instalador aceita `--headless`, e
`dodaios serve` inicia apenas a interface no navegador:

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # browser interface only, for a server without a screen
```

O Dodaios roda em Windows, macOS e Linux baseado em glibc, de 64 bits. O
instalador de terminal funciona em x86-64 e Arm64 e precisa do Python 3.11 a
3.14 e do Git; ele baixa o Python se estiver faltando e se oferece para
instalar o Git se não houver. Placa de vídeo é opcional. Até agora, só o
Windows 11 tem uma validação ao vivo registrada.
[Guia de instalação](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[Plataformas suportadas](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[Como rodar em um servidor](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## Seus planos e chaves

O Dodaios não custa nada: não há conta Dodaios nem plano pago. Ele não vende
acesso a modelos e nunca faz login por você. Ele inicia a ferramenta oficial
de linha de comando de cada agente de programação, e você faz login em cada uma
por conta própria, então os agentes rodam nos planos e chaves que você já tem.
O Claude Code, por exemplo, exige um plano pago do Claude. O uso de cada
serviço segue os termos do próprio serviço.
[Provedores e chaves de API](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## Bom saber

- **Seus dados.** Chats, memória, documentos e configurações são arquivos no
  computador que roda o Dodaios. Um modelo ou um serviço conectado recebe o
  que precisa para a sua parte de uma solicitação. O login nos plugins do
  Google, do Slack ou do Figma passa por um pequeno serviço de tokens mantido
  pelo projeto.
  [Privacidade e dados locais](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)
- **Perguntar antes.** Um chat novo começa em Bypass permissions, em que nada
  é perguntado. Escolha um modo que pergunte e os quatro limites rígidos acima
  sempre vão esperar o seu sim.
  [Segurança e aprovações](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)
- **Ainda não está pronto.** As chamadas telefônicas precisam do seu próprio
  número Twilio e são uma prévia inicial. A maioria dos plugins ainda tem o
  selo Preview. O app do celular é um aplicativo web servido pelo seu
  computador.

## Documentação

O [tour pelos recursos](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)
mostra cada parte em uma única página, com imagens. Os mesmos guias estão no
aplicativo, em **Docs**, com busca.
[Configuração inicial](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) ·
[Solução de problemas](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md) ·
[Arquitetura](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)

## Como contribuir

Correções, testes, relatos de plataformas e documentação são bem-vindos. O
[guia de contribuição](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)
leva você de um fork até uma verificação aprovada em cerca de dez minutos.
Perguntas e ideias vão para o [Discord](https://discord.gg/x7USduHxbc).

Obrigado a todas as pessoas que já entregaram algo aqui:

<!-- contributors:start -->

<a href="https://github.com/rubenluetke"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=96" width="48" height="48" alt="rubenluetke" title="rubenluetke"></a> <a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=96" width="48" height="48" alt="dannyward630" title="dannyward630"></a> <a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=96" width="48" height="48" alt="dennisheidederamirez-coder" title="dennisheidederamirez-coder"></a> <a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=96" width="48" height="48" alt="ANO3457" title="ANO3457"></a> <a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=96" width="48" height="48" alt="PilarJ" title="PilarJ"></a> <a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=96" width="48" height="48" alt="Idee-Wird-App" title="Idee-Wird-App"></a> <a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=96" width="48" height="48" alt="CodeByPeace" title="CodeByPeace"></a> <a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=96" width="48" height="48" alt="jaydenhawkes123" title="jaydenhawkes123"></a> <a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=96" width="48" height="48" alt="alibaba080290" title="alibaba080290"></a> <a href="https://github.com/dovellx"><img src="https://avatars.githubusercontent.com/u/109219673?u=fdc67e8b78b3aa9cd5fb58f3c5a55c3445585c9e&v=4&s=96" width="48" height="48" alt="dovellx" title="dovellx"></a> <!-- i18n-allow -->
<a href="https://github.com/eljeffeg"><img src="https://avatars.githubusercontent.com/u/161904?u=38ce201214d8460536ec43ebb967955704d51345&v=4&s=96" width="48" height="48" alt="eljeffeg" title="eljeffeg"></a> <a href="https://github.com/martiroca06"><img src="https://avatars.githubusercontent.com/u/229811558?v=4&s=96" width="48" height="48" alt="martiroca06" title="martiroca06"></a> <a href="https://github.com/morfeus48235-glitch"><img src="https://avatars.githubusercontent.com/u/297425892?v=4&s=96" width="48" height="48" alt="morfeus48235-glitch" title="morfeus48235-glitch"></a> <a href="https://github.com/Oscar-Williams"><img src="https://avatars.githubusercontent.com/u/319719771?u=43c7bbf42a4f99b44a66bae0c1972b7ed72c44f2&v=4&s=96" width="48" height="48" alt="Oscar-Williams" title="Oscar-Williams"></a> <a href="https://github.com/Sgangalossa"><img src="https://avatars.githubusercontent.com/u/336517156?u=0a255499355232fbf86ae8f56c11ec59c43f76b9&v=4&s=96" width="48" height="48" alt="Sgangalossa" title="Sgangalossa"></a> <a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=96" width="48" height="48" alt="tianxingjian2406" title="tianxingjian2406"></a> <a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=96" width="48" height="48" alt="Uddoo" title="Uddoo"></a> <a href="https://github.com/Virtuluso-azores"><img src="https://avatars.githubusercontent.com/u/263487091?v=4&s=96" width="48" height="48" alt="Virtuluso-azores" title="Virtuluso-azores"></a> <a href="https://github.com/xiangnuans"><img src="https://avatars.githubusercontent.com/u/24558814?v=4&s=96" width="48" height="48" alt="xiangnuans" title="xiangnuans"></a> <a href="https://github.com/YannisG23"><img src="https://avatars.githubusercontent.com/u/132681092?u=f7c0391b17c8490513e6bf5571256291527c12ff&v=4&s=96" width="48" height="48" alt="YannisG23" title="YannisG23"></a> <!-- i18n-allow -->

<!-- contributors:end -->

## Licença

[Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE),
com a atribuição em
[NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE). O nome e o
logotipo são cobertos pela
[política de marca](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md).
O Dodaios é um projeto independente: os produtos com que ele trabalha pertencem
aos seus criadores, e dar suporte a uma ferramenta não significa que o criador
dela aprova o Dodaios.
Até outubro de 2026 ele se chamava Personal Jarvis
([por que o nome mudou](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)).
Os patrocinadores estão em [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md).
