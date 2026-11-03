/**
 * Words of the Unreal Verse launcher card, in the app's five UI languages.
 * Kept beside the card while it sits behind the `verse.unreal_preview` flag;
 * they move into the `ship` locale chunk with the three.js deletion PR.
 */
import type { UiLanguage } from "@/i18n";

export type LauncherKey =
  | "title"
  | "open"
  | "quick_duel"
  | "stop"
  | "retry"
  | "starting"
  | "status.not_installed"
  | "status.unsupported"
  | "status.stopped"
  | "status.running"
  | "status.crashed"
  | "state.booting"
  | "state.visible"
  | "state.panel"
  | "state.dormant"
  | "state.exiting"
  | "crash_report"
  | "failed"
  | "install.download"
  | "install.size"
  | "install.hint"
  | "install.downloading"
  | "install.verifying"
  | "install.installing"
  | "install.cancel"
  | "install.cancelled"
  | "install.resume"
  | "install.failed"
  | "install.unavailable"
  | "install.retry"
  | "settings.title"
  | "settings.description"
  | "settings.installed"
  | "settings.not_installed"
  | "settings.remove"
  | "settings.removing"
  | "settings.confirm"
  | "settings.unavailable";

type Table = Record<LauncherKey, string>;

const en: Table = {
  title: "Unreal Verse",
  open: "Open the Verse",
  quick_duel: "Quick duel",
  stop: "Close",
  retry: "Start again",
  starting: "Starting…",
  "status.not_installed": "The Unreal Verse is optional and not installed yet.",
  "status.unsupported": "This computer's graphics card cannot run the Unreal Verse. Everything else keeps working.",
  "status.stopped": "Ready to start.",
  "status.running": "Running",
  "status.crashed": "The Verse stopped after repeated crashes.",
  "state.booting": "starting",
  "state.visible": "on screen",
  "state.panel": "in the side panel",
  "state.dormant": "resting in the background",
  "state.exiting": "closing",
  crash_report: "Crash report folder",
  failed: "That did not work: {reason}",
  "install.download": "Download the Verse",
  "install.size": "Download size: {size}",
  "install.hint": "It is not part of the app install; you can remove it again in Settings.",
  "install.downloading": "Downloading… {done} of {total}",
  "install.verifying": "Checking the package…",
  "install.installing": "Installing…",
  "install.cancel": "Cancel",
  "install.cancelled": "Download paused. It continues where it stopped.",
  "install.resume": "Continue the download",
  "install.failed": "The download did not work: {reason}",
  "install.unavailable": "The Verse download is not available yet.",
  "install.retry": "Try again",
  "settings.title": "Unreal Verse",
  "settings.description": "The optional 3D Verse is downloaded separately and can be removed at any time. The classic Verse stays.",
  "settings.installed": "Installed, version {version}",
  "settings.not_installed": "Not installed. Download it from the Verse view.",
  "settings.remove": "Remove the Verse",
  "settings.removing": "Removing…",
  "settings.confirm": "Remove the Verse from this computer? You can download it again later.",
  "settings.unavailable": "The Verse status could not be read.",
};

const de: Table = {
  title: "Unreal Verse", // i18n-allow
  open: "Verse öffnen", // i18n-allow
  quick_duel: "Schnelles Duell", // i18n-allow
  stop: "Schließen", // i18n-allow
  retry: "Neu starten", // i18n-allow
  starting: "Startet…", // i18n-allow
  "status.not_installed": "Das Unreal Verse ist optional und noch nicht installiert.", // i18n-allow
  "status.unsupported": "Die Grafikkarte dieses Computers kann das Unreal Verse nicht ausführen. Alles andere funktioniert weiter.", // i18n-allow
  "status.stopped": "Bereit zum Start.", // i18n-allow
  "status.running": "Läuft", // i18n-allow
  "status.crashed": "Das Verse wurde nach wiederholten Abstürzen angehalten.", // i18n-allow
  "state.booting": "startet", // i18n-allow
  "state.visible": "im Bild", // i18n-allow
  "state.panel": "im Seitenpanel", // i18n-allow
  "state.dormant": "ruht im Hintergrund", // i18n-allow
  "state.exiting": "wird geschlossen", // i18n-allow
  crash_report: "Ordner mit dem Absturzbericht", // i18n-allow
  failed: "Das hat nicht geklappt: {reason}", // i18n-allow
  "install.download": "Verse herunterladen", // i18n-allow
  "install.size": "Downloadgröße: {size}", // i18n-allow
  "install.hint": "Es gehört nicht zur App-Installation; in den Einstellungen kannst du es wieder entfernen.", // i18n-allow
  "install.downloading": "Lädt herunter… {done} von {total}", // i18n-allow
  "install.verifying": "Paket wird geprüft…", // i18n-allow
  "install.installing": "Wird installiert…", // i18n-allow
  "install.cancel": "Abbrechen", // i18n-allow
  "install.cancelled": "Download pausiert. Er geht dort weiter, wo er aufgehört hat.", // i18n-allow
  "install.resume": "Download fortsetzen", // i18n-allow
  "install.failed": "Der Download hat nicht geklappt: {reason}", // i18n-allow
  "install.unavailable": "Der Verse-Download ist noch nicht verfügbar.", // i18n-allow
  "install.retry": "Noch einmal versuchen", // i18n-allow
  "settings.title": "Unreal Verse", // i18n-allow
  "settings.description": "Das optionale 3D-Verse wird separat heruntergeladen und lässt sich jederzeit entfernen. Das klassische Verse bleibt.", // i18n-allow
  "settings.installed": "Installiert, Version {version}", // i18n-allow
  "settings.not_installed": "Nicht installiert. Du kannst es in der Verse-Ansicht herunterladen.", // i18n-allow
  "settings.remove": "Verse entfernen", // i18n-allow
  "settings.removing": "Wird entfernt…", // i18n-allow
  "settings.confirm": "Das Verse von diesem Computer entfernen? Du kannst es später wieder herunterladen.", // i18n-allow
  "settings.unavailable": "Der Verse-Status konnte nicht gelesen werden.", // i18n-allow
};

const es: Table = {
  title: "Unreal Verse",
  open: "Abrir el Verse",
  quick_duel: "Duelo rápido",
  stop: "Cerrar",
  retry: "Iniciar de nuevo",
  starting: "Iniciando…",
  "status.not_installed": "El Unreal Verse es opcional y aún no está instalado.",
  "status.unsupported": "La tarjeta gráfica de este ordenador no puede ejecutar el Unreal Verse. Todo lo demás sigue funcionando.",
  "status.stopped": "Listo para iniciar.",
  "status.running": "En marcha",
  "status.crashed": "El Verse se detuvo tras varios fallos seguidos.",
  "state.booting": "iniciando",
  "state.visible": "en pantalla",
  "state.panel": "en el panel lateral",
  "state.dormant": "en reposo en segundo plano",
  "state.exiting": "cerrando",
  crash_report: "Carpeta del informe de fallos",
  failed: "No ha funcionado: {reason}",
  "install.download": "Descargar el Verse",
  "install.size": "Tamaño de la descarga: {size}",
  "install.hint": "No forma parte de la instalación de la app; puedes quitarlo en Ajustes.",
  "install.downloading": "Descargando… {done} de {total}",
  "install.verifying": "Comprobando el paquete…",
  "install.installing": "Instalando…",
  "install.cancel": "Cancelar",
  "install.cancelled": "Descarga en pausa. Continuará donde se quedó.",
  "install.resume": "Continuar la descarga",
  "install.failed": "La descarga no ha funcionado: {reason}",
  "install.unavailable": "La descarga del Verse aún no está disponible.",
  "install.retry": "Intentar de nuevo",
  "settings.title": "Unreal Verse",
  "settings.description": "El Verse 3D opcional se descarga por separado y se puede quitar en cualquier momento. El Verse clásico se queda.",
  "settings.installed": "Instalado, versión {version}",
  "settings.not_installed": "No instalado. Descárgalo desde la vista del Verse.",
  "settings.remove": "Quitar el Verse",
  "settings.removing": "Quitando…",
  "settings.confirm": "¿Quitar el Verse de este ordenador? Puedes volver a descargarlo más tarde.",
  "settings.unavailable": "No se pudo leer el estado del Verse.",
};

const pt: Table = {
  title: "Unreal Verse",
  open: "Abrir o Verse",
  quick_duel: "Duelo rápido",
  stop: "Fechar",
  retry: "Iniciar de novo",
  starting: "Iniciando…",
  "status.not_installed": "O Unreal Verse é opcional e ainda não está instalado.",
  "status.unsupported": "A placa de vídeo deste computador não consegue executar o Unreal Verse. Todo o resto continua funcionando.",
  "status.stopped": "Pronto para iniciar.",
  "status.running": "Em execução",
  "status.crashed": "O Verse parou após falhas repetidas.",
  "state.booting": "iniciando",
  "state.visible": "na tela",
  "state.panel": "no painel lateral",
  "state.dormant": "em repouso em segundo plano",
  "state.exiting": "fechando",
  crash_report: "Pasta do relatório de falha",
  failed: "Não funcionou: {reason}",
  "install.download": "Baixar o Verse",
  "install.size": "Tamanho do download: {size}",
  "install.hint": "Ele não faz parte da instalação do app; você pode removê-lo nas Configurações.",
  "install.downloading": "Baixando… {done} de {total}",
  "install.verifying": "Verificando o pacote…",
  "install.installing": "Instalando…",
  "install.cancel": "Cancelar",
  "install.cancelled": "Download pausado. Ele continua de onde parou.",
  "install.resume": "Continuar o download",
  "install.failed": "O download não funcionou: {reason}",
  "install.unavailable": "O download do Verse ainda não está disponível.",
  "install.retry": "Tentar de novo",
  "settings.title": "Unreal Verse",
  "settings.description": "O Verse 3D opcional é baixado separadamente e pode ser removido a qualquer momento. O Verse clássico continua.",
  "settings.installed": "Instalado, versão {version}",
  "settings.not_installed": "Não instalado. Baixe-o na tela do Verse.",
  "settings.remove": "Remover o Verse",
  "settings.removing": "Removendo…",
  "settings.confirm": "Remover o Verse deste computador? Você pode baixá-lo de novo depois.",
  "settings.unavailable": "Não foi possível ler o status do Verse.",
};

const zh: Table = {
  title: "Unreal Verse",
  open: "打开 Verse",
  quick_duel: "快速对决",
  stop: "关闭",
  retry: "重新启动",
  starting: "正在启动…",
  "status.not_installed": "Unreal Verse 是可选组件，尚未安装。",
  "status.unsupported": "此电脑的显卡无法运行 Unreal Verse。其他功能照常可用。",
  "status.stopped": "可以启动。",
  "status.running": "运行中",
  "status.crashed": "Verse 多次崩溃后已停止。",
  "state.booting": "正在启动",
  "state.visible": "显示中",
  "state.panel": "在侧边面板中",
  "state.dormant": "在后台休眠",
  "state.exiting": "正在关闭",
  crash_report: "崩溃报告文件夹",
  failed: "操作失败：{reason}",
  "install.download": "下载 Verse",
  "install.size": "下载大小：{size}",
  "install.hint": "它不包含在应用安装中；可在设置中再次移除。",
  "install.downloading": "正在下载… {done} / {total}",
  "install.verifying": "正在校验安装包…",
  "install.installing": "正在安装…",
  "install.cancel": "取消",
  "install.cancelled": "下载已暂停，会从中断处继续。",
  "install.resume": "继续下载",
  "install.failed": "下载失败：{reason}",
  "install.unavailable": "Verse 下载暂不可用。",
  "install.retry": "重试",
  "settings.title": "Unreal Verse",
  "settings.description": "可选的 3D Verse 需单独下载，可随时移除。经典 Verse 保持不变。",
  "settings.installed": "已安装，版本 {version}",
  "settings.not_installed": "未安装。可在 Verse 视图中下载。",
  "settings.remove": "移除 Verse",
  "settings.removing": "正在移除…",
  "settings.confirm": "要从此电脑移除 Verse 吗？之后可以重新下载。",
  "settings.unavailable": "无法读取 Verse 状态。",
};

export const LAUNCHER_STRINGS: Readonly<Record<UiLanguage, Table>> = { en, de, es, pt, zh };

export function launcherText(lang: UiLanguage, key: LauncherKey, vars: Record<string, string> = {}): string {
  const table = LAUNCHER_STRINGS[lang] ?? en;
  let text = table[key] ?? en[key];
  for (const [name, value] of Object.entries(vars)) text = text.split(`{${name}}`).join(value);
  return text;
}
