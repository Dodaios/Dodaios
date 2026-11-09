import { useUiLanguage } from "@/i18n";

/**
 * The panel stream's own strings, in every UI locale. They stay beside the component while the
 * Unreal Verse is behind the `verse.unreal_preview` flag; the deletion PR moves them into the
 * locale files with the rest of the Verse strings.
 */
type TextKey =
  | "notInstalled"
  | "notInstalledHint"
  | "download"
  | "connecting"
  | "verseOpen"
  | "verseOpenHint"
  | "unavailable"
  | "unavailableHint"
  | "failed"
  | "retry"
  | "label";
export type VerseStreamText = Readonly<Record<TextKey, string>>;

const STRINGS: Readonly<Record<"en" | "de" | "es" | "pt" | "zh", VerseStreamText>> = {
  en: {
    notInstalled: "The Verse is not downloaded",
    notInstalledHint: "The Verse is an optional download. Once it is on this computer, it shows here.",
    download: "Download the Verse",
    connecting: "Starting the Verse view…",
    verseOpen: "Verse is open",
    verseOpenHint: "The Verse is showing in its own window.",
    unavailable: "The Verse view is not available",
    unavailableHint: "It needs the Unreal Verse installed and a graphics card that can run it.",
    failed: "The Verse view could not start",
    retry: "Try again",
    label: "Dodaios Verse, live view",
  },
  de: {
    notInstalled: "Das Verse ist nicht heruntergeladen", // i18n-allow: German locale strings
    notInstalledHint: "Das Verse ist ein optionaler Download. Sobald es auf diesem Computer ist, erscheint es hier.", // i18n-allow: German locale strings
    download: "Verse herunterladen", // i18n-allow: German locale strings
    connecting: "Verse-Ansicht startet…", // i18n-allow: German locale strings
    verseOpen: "Verse ist geöffnet", // i18n-allow: German locale strings
    verseOpenHint: "Das Verse läuft gerade in seinem eigenen Fenster.", // i18n-allow: German locale strings
    unavailable: "Die Verse-Ansicht ist nicht verfügbar", // i18n-allow: German locale strings
    unavailableHint: "Sie braucht das installierte Unreal-Verse und eine Grafikkarte, die es ausführen kann.", // i18n-allow: German locale strings
    failed: "Die Verse-Ansicht konnte nicht starten", // i18n-allow: German locale strings
    retry: "Erneut versuchen", // i18n-allow: German locale strings
    label: "Dodaios Verse, Live-Ansicht", // i18n-allow: German locale strings
  },
  es: {
    notInstalled: "El Verse no está descargado",
    notInstalledHint: "El Verse es una descarga opcional. Cuando esté en este ordenador, aparecerá aquí.",
    download: "Descargar el Verse",
    connecting: "Iniciando la vista del Verse…",
    verseOpen: "El Verse está abierto",
    verseOpenHint: "El Verse se muestra en su propia ventana.",
    unavailable: "La vista del Verse no está disponible",
    unavailableHint: "Necesita el Verse de Unreal instalado y una tarjeta gráfica capaz de ejecutarlo.",
    failed: "No se pudo iniciar la vista del Verse",
    retry: "Reintentar",
    label: "Dodaios Verse, vista en directo",
  },
  pt: {
    notInstalled: "O Verse não está transferido",
    notInstalledHint: "O Verse é uma transferência opcional. Quando estiver neste computador, aparece aqui.",
    download: "Transferir o Verse",
    connecting: "Iniciando a vista do Verse…",
    verseOpen: "O Verse está aberto",
    verseOpenHint: "O Verse está a ser mostrado na sua própria janela.",
    unavailable: "A vista do Verse não está disponível",
    unavailableHint: "Precisa do Verse do Unreal instalado e de uma placa gráfica capaz de o executar.",
    failed: "Não foi possível iniciar a vista do Verse",
    retry: "Tentar novamente",
    label: "Dodaios Verse, vista ao vivo",
  },
  zh: {
    notInstalled: "尚未下载 Verse",
    notInstalledHint: "Verse 是可选下载内容。下载到这台电脑后，就会显示在这里。",
    download: "下载 Verse",
    connecting: "正在启动 Verse 视图…",
    verseOpen: "Verse 已打开",
    verseOpenHint: "Verse 正在自己的窗口中显示。",
    unavailable: "Verse 视图不可用",
    unavailableHint: "需要安装 Unreal Verse 以及能够运行它的显卡。",
    failed: "无法启动 Verse 视图",
    retry: "重试",
    label: "Dodaios Verse 实时视图",
  },
};

export function verseStreamText(lang: string): VerseStreamText {
  return (STRINGS as Readonly<Record<string, VerseStreamText>>)[lang] ?? STRINGS.en;
}

export function useVerseStreamText(): VerseStreamText {
  return verseStreamText(useUiLanguage());
}

export const VERSE_STREAM_LOCALES = Object.keys(STRINGS);
