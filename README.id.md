<div align="center">

<a href="https://dodaios.ai">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-dark.svg" />
    <img src="https://raw.githubusercontent.com/Dodaios/Dodaios/main/assets/brand/dodaios-logo-on-light.svg" alt="Dodaios" width="112" />
  </picture>
</a>

<h1>Dodaios</h1>

<!-- the promise: word for word everywhere (docs/positioning.md) -->
<p><b>Semua agen coding Anda dalam satu chat.</b></p>

<p>
  <a href="https://github.com/Dodaios/Dodaios/releases/latest"><img src="https://img.shields.io/github/v/release/Dodaios/Dodaios?label=release&amp;labelColor=0A0A0A&amp;color=FAFAFA" alt="Rilis terbaru" /></a>
  <a href="https://github.com/Dodaios/Dodaios/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-Apache_2.0-FAFAFA?labelColor=0A0A0A" alt="Lisensi: Apache 2.0" /></a>
  <a href="https://github.com/Dodaios/Dodaios/stargazers"><img src="https://img.shields.io/github/stars/Dodaios/Dodaios?labelColor=0A0A0A&amp;color=FAFAFA&amp;logo=github" alt="Bintang GitHub" /></a>
  <a href="https://discord.gg/x7USduHxbc"><img src="https://img.shields.io/badge/discord-join-FAFAFA?labelColor=0A0A0A&amp;logo=discord&amp;logoColor=white" alt="Discord" /></a>
</p>

<p>
  <a href="https://trendshift.io/repositories/91076?utm_source=repository-badge&amp;utm_medium=badge&amp;utm_campaign=badge-repository-91076" target="_blank" rel="noopener noreferrer"><img src="https://trendshift.io/api/badge/repositories/91076" alt="Dodaios%2FDodaios | Trendshift" width="250" height="55"/></a>
</p>

<p>
  <a href="#instalasi">Instalasi</a> ·
  <a href="#paket-dan-kunci-anda">Paket Anda</a> ·
  <a href="#dokumentasi">Dokumentasi</a> ·
  <a href="https://dodaios.ai">Situs web</a> ·
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
  <a href="https://github.com/Dodaios/Dodaios/blob/main/README.ru.md">Русский</a>
</p>

</div>

Anda punya Claude Code di satu terminal, Codex di terminal lain, dan tab chat
tempat Anda menyalin rencana bolak-balik. Dodaios mengakhiri itu. Dodaios
adalah lapisan di atas semua agen coding Anda: Anda bilang apa yang Anda mau,
lewat suara atau chat, dan satu asisten mengurus sisanya. Ia menulis brief,
menjalankan agen yang tepat di Agentic IDE bawaannya, memantaunya selama
bekerja, dan memberi tahu Anda saat agen selesai atau membutuhkan Anda.
Jalankan lima agen sekaligus dan tetap tahu persis apa yang dikerjakan
masing-masing.

Open source, dan berjalan di komputer Anda. Bekerja dengan langganan Claude
atau ChatGPT Anda, dengan API key untuk Claude, OpenAI dan Gemini, atau dengan
model Ollama lokal.

https://github.com/user-attachments/assets/37cdc5a5-30d6-49c8-92ff-3454a075569f

<p align="center">
  <sub>Rekaman asli pada 60 frame per detik, diputar dengan kecepatan yang sama seperti saat direkam; waktu tunggu model dipotong. Direkam dengan Claude Fable 5.2 dan Claude Opus 5.5 melalui Claude Code. Perubahan kode, eksekusi tes, dan commit-nya sungguhan. <a href="https://github.com/Dodaios/Dodaios/blob/main/assets/demo/readme/dodaios-demo.mp4"><b>Tonton videonya</b></a> (MP4, 42 dtk, 2,5 MB)</sub>
</p>

## Instalasi

macOS dan Linux:

```bash
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash
```

Windows, di PowerShell:

```powershell
irm https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.ps1 | iex
```

Installer menyiapkan lingkungan Python-nya sendiri, menambahkan launcher, lalu
membuka aplikasi. Saat pertama kali dijalankan, Anda memberi nama pada asisten (nama
itu sekaligus menjadi wake word), menghubungkan satu model, dan memilih cara Anda
ingin berbicara dengannya. Untuk pekerjaan coding, instal minimal satu agen coding,
seperti Claude Code atau Codex, lalu masuk ke akunnya.

```bash
dodaios            # start the desktop app
dodaios update     # install the newest release
```

<details>
<summary>Installer desktop, pipx, dan server</summary>

<br />

Unduh installer untuk sistem Anda dari rilis terbaru:

| Windows | macOS | Linux |
| --- | --- | --- |
| [Dodaios-Setup-x64.exe](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Setup-x64.exe) | [Apple Silicon](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-arm64.dmg) · [Intel](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-macOS-x64.dmg) | [AppImage, x86_64](https://github.com/Dodaios/Dodaios/releases/latest/download/Dodaios-Linux-x86_64.AppImage) |

Setiap rilis mencantumkan checksum di `installers-SHA256SUMS.txt`. Installer
belum ditandatangani: Windows menampilkan peringatan, dan macOS meminta Anda
mengizinkan aplikasi sekali di Pengaturan Sistem, pada bagian Privasi & Keamanan.
[Kebijakan penandatanganan kode](https://github.com/Dodaios/Dodaios/blob/main/docs/code-signing-policy.md)
menjelaskan perkembangannya.

Dengan pipx, Anda mendapatkan paket server yang lebih kecil, tanpa launcher desktop.
Di server Linux tanpa layar, installer menerima opsi `--headless`, dan
`dodaios serve` hanya menjalankan antarmuka browser:

```bash
pipx install dodaios
curl -fsSL https://raw.githubusercontent.com/Dodaios/Dodaios/main/install/install.sh | bash -s -- --headless
dodaios serve      # browser interface only, for a server without a screen
```

Dodaios berjalan di Windows, macOS, dan Linux berbasis glibc, semuanya 64-bit.
Installer terminal bekerja di x86-64 dan Arm64 serta membutuhkan Python 3.11
hingga 3.14 dan Git; Python yang belum ada akan diunduh, dan Git yang belum ada
akan ditawarkan untuk diinstal. Kartu grafis bersifat opsional. Sejauh ini, baru
Windows 11 yang memiliki persetujuan uji langsung yang tercatat.
[Panduan instalasi](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/install-dodaios.md) ·
[Dukungan platform](https://github.com/Dodaios/Dodaios/blob/main/docs/product/reference/platform-support.md) ·
[Menjalankannya di server](https://github.com/Dodaios/Dodaios/blob/main/docs/headless-vps-deployment.md)

</details>

## Paket dan kunci Anda

Dodaios gratis: tidak ada akun Dodaios, tidak ada paket berbayar. Dodaios tidak
menjual akses model dan tidak pernah masuk ke akun atas nama Anda. Dodaios menjalankan
tool command-line resmi dari setiap agen coding, dan Anda masuk ke masing-masing
sendiri, sehingga agen berjalan dengan paket dan kunci yang sudah Anda miliki.
Claude Code, misalnya, membutuhkan paket Claude berbayar. Penggunaan Anda atas
setiap layanan tunduk pada ketentuan layanan tersebut.
[Penyedia dan kunci API](https://github.com/Dodaios/Dodaios/blob/main/docs/product/personalize-and-connect/providers-and-api-keys.md)

## Perlu diketahui

- **Data Anda.** Chat, memori, dokumen, dan pengaturan disimpan sebagai file di
  komputer yang menjalankan Dodaios. Model atau layanan yang terhubung hanya
  mendapatkan apa yang dibutuhkan untuk bagiannya dalam sebuah permintaan. Masuk ke
  plugin Google, Slack, atau Figma melewati layanan token kecil yang dijalankan
  oleh proyek ini.
  [Privasi dan data lokal](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/privacy-and-local-data.md)
- **Bertanya dulu.** Chat baru dimulai dalam Bypass permissions, di mana tidak ada
  yang ditanyakan. Pilih mode yang bertanya, maka keempat batas keras di atas selalu
  menunggu persetujuan Anda.
  [Keamanan dan persetujuan](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/safety-and-approvals.md)
- **Belum selesai.** Panggilan telepon memerlukan nomor Twilio Anda sendiri dan masih
  berupa pratinjau awal. Sebagian besar plugin masih membawa lencana Preview.
  Aplikasi ponselnya adalah aplikasi web yang disajikan oleh komputer Anda.

## Dokumentasi

[Tur fitur](https://github.com/Dodaios/Dodaios/blob/main/docs/feature-tour.md)
menampilkan setiap bagian dalam satu halaman, lengkap dengan gambar. Panduan yang
sama ada di dalam aplikasi pada **Docs**, lengkap dengan pencarian.
[Penyiapan awal](https://github.com/Dodaios/Dodaios/blob/main/docs/product/start-here/first-run-setup.md) ·
[Pemecahan masalah](https://github.com/Dodaios/Dodaios/blob/main/docs/product/privacy-safety-and-support/troubleshooting.md) ·
[Arsitektur](https://github.com/Dodaios/Dodaios/blob/main/docs/architecture-overview.md)

## Berkontribusi

Perbaikan, tes, laporan platform, dan dokumentasi sangat diterima.
[Panduan kontribusi](https://github.com/Dodaios/Dodaios/blob/main/CONTRIBUTING.md#your-first-contribution-in-10-minutes)
membawa Anda dari fork hingga pemeriksaan yang lolos dalam sekitar sepuluh menit.
Pertanyaan dan ide bisa disampaikan di [Discord](https://discord.gg/x7USduHxbc).

Terima kasih kepada semua yang telah menyumbangkan sesuatu di sini:

<!-- contributors:start -->

<a href="https://github.com/rubenluetke"><img src="https://avatars.githubusercontent.com/u/226271791?v=4&s=96" width="48" height="48" alt="rubenluetke" title="rubenluetke"></a> <a href="https://github.com/dannyward630"><img src="https://avatars.githubusercontent.com/u/71604164?v=4&s=96" width="48" height="48" alt="dannyward630" title="dannyward630"></a> <a href="https://github.com/dennisheidederamirez-coder"><img src="https://avatars.githubusercontent.com/u/338621144?v=4&s=96" width="48" height="48" alt="dennisheidederamirez-coder" title="dennisheidederamirez-coder"></a> <a href="https://github.com/ANO3457"><img src="https://avatars.githubusercontent.com/u/187025195?v=4&s=96" width="48" height="48" alt="ANO3457" title="ANO3457"></a> <a href="https://github.com/PilarJ"><img src="https://avatars.githubusercontent.com/u/2921746?v=4&s=96" width="48" height="48" alt="PilarJ" title="PilarJ"></a> <a href="https://github.com/Idee-Wird-App"><img src="https://avatars.githubusercontent.com/u/330157118?v=4&s=96" width="48" height="48" alt="Idee-Wird-App" title="Idee-Wird-App"></a> <a href="https://github.com/CodeByPeace"><img src="https://avatars.githubusercontent.com/u/228503734?v=4&s=96" width="48" height="48" alt="CodeByPeace" title="CodeByPeace"></a> <a href="https://github.com/jaydenhawkes123"><img src="https://avatars.githubusercontent.com/u/7899343?v=4&s=96" width="48" height="48" alt="jaydenhawkes123" title="jaydenhawkes123"></a> <a href="https://github.com/alibaba080290"><img src="https://avatars.githubusercontent.com/u/59247334?v=4&s=96" width="48" height="48" alt="alibaba080290" title="alibaba080290"></a> <a href="https://github.com/dovellx"><img src="https://avatars.githubusercontent.com/u/109219673?u=fdc67e8b78b3aa9cd5fb58f3c5a55c3445585c9e&v=4&s=96" width="48" height="48" alt="dovellx" title="dovellx"></a> <!-- i18n-allow -->
<a href="https://github.com/eljeffeg"><img src="https://avatars.githubusercontent.com/u/161904?u=38ce201214d8460536ec43ebb967955704d51345&v=4&s=96" width="48" height="48" alt="eljeffeg" title="eljeffeg"></a> <a href="https://github.com/martiroca06"><img src="https://avatars.githubusercontent.com/u/229811558?v=4&s=96" width="48" height="48" alt="martiroca06" title="martiroca06"></a> <a href="https://github.com/morfeus48235-glitch"><img src="https://avatars.githubusercontent.com/u/297425892?v=4&s=96" width="48" height="48" alt="morfeus48235-glitch" title="morfeus48235-glitch"></a> <a href="https://github.com/Oscar-Williams"><img src="https://avatars.githubusercontent.com/u/319719771?u=43c7bbf42a4f99b44a66bae0c1972b7ed72c44f2&v=4&s=96" width="48" height="48" alt="Oscar-Williams" title="Oscar-Williams"></a> <a href="https://github.com/Sgangalossa"><img src="https://avatars.githubusercontent.com/u/336517156?u=0a255499355232fbf86ae8f56c11ec59c43f76b9&v=4&s=96" width="48" height="48" alt="Sgangalossa" title="Sgangalossa"></a> <a href="https://github.com/tianxingjian2406"><img src="https://avatars.githubusercontent.com/u/247943876?v=4&s=96" width="48" height="48" alt="tianxingjian2406" title="tianxingjian2406"></a> <a href="https://github.com/Uddoo"><img src="https://avatars.githubusercontent.com/u/19704816?v=4&s=96" width="48" height="48" alt="Uddoo" title="Uddoo"></a> <a href="https://github.com/Virtuluso-azores"><img src="https://avatars.githubusercontent.com/u/263487091?v=4&s=96" width="48" height="48" alt="Virtuluso-azores" title="Virtuluso-azores"></a> <a href="https://github.com/xiangnuans"><img src="https://avatars.githubusercontent.com/u/24558814?v=4&s=96" width="48" height="48" alt="xiangnuans" title="xiangnuans"></a> <a href="https://github.com/YannisG23"><img src="https://avatars.githubusercontent.com/u/132681092?u=f7c0391b17c8490513e6bf5571256291527c12ff&v=4&s=96" width="48" height="48" alt="YannisG23" title="YannisG23"></a> <!-- i18n-allow -->

<!-- contributors:end -->

## Lisensi

[Apache License 2.0](https://github.com/Dodaios/Dodaios/blob/main/LICENSE),
dengan atribusi di
[NOTICE](https://github.com/Dodaios/Dodaios/blob/main/NOTICE). Nama dan
logonya diatur oleh
[kebijakan merek dagang](https://github.com/Dodaios/Dodaios/blob/main/TRADEMARK.md).
Dodaios adalah proyek independen: produk yang digunakan bersamanya adalah milik
pembuatnya masing-masing, dan dukungan terhadap suatu tool tidak berarti pembuatnya
menyetujui Dodaios. Hingga Oktober 2026, proyek ini bernama Personal Jarvis
([mengapa namanya berubah](https://dodaios.ai/blog/personal-jarvis-is-now-dodaios/)).
Daftar sponsor ada di [SPONSORS.md](https://github.com/Dodaios/Dodaios/blob/main/SPONSORS.md).
