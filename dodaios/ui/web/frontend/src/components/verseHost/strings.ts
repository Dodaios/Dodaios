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
  | "failed";

type Table = Record<LauncherKey, string>;

const en: Table = {
  title: "Unreal Verse",
  open: "Open the Verse",
  quick_duel: "Quick duel",
  stop: "Close",
  retry: "Start again",
  starting: "Starting…",
  "status.not_installed": "The Unreal Verse is not installed on this computer.",
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
};

const de: Table = {
  title: "Unreal Verse", // i18n-allow
  open: "Verse öffnen", // i18n-allow
  quick_duel: "Schnelles Duell", // i18n-allow
  stop: "Schließen", // i18n-allow
  retry: "Neu starten", // i18n-allow
  starting: "Startet…", // i18n-allow
  "status.not_installed": "Das Unreal Verse ist auf diesem Computer nicht installiert.", // i18n-allow
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
};

const es: Table = {
  title: "Unreal Verse",
  open: "Abrir el Verse",
  quick_duel: "Duelo rápido",
  stop: "Cerrar",
  retry: "Iniciar de nuevo",
  starting: "Iniciando…",
  "status.not_installed": "El Unreal Verse no está instalado en este ordenador.",
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
};

const pt: Table = {
  title: "Unreal Verse",
  open: "Abrir o Verse",
  quick_duel: "Duelo rápido",
  stop: "Fechar",
  retry: "Iniciar de novo",
  starting: "Iniciando…",
  "status.not_installed": "O Unreal Verse não está instalado neste computador.",
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
};

const zh: Table = {
  title: "Unreal Verse",
  open: "打开 Verse",
  quick_duel: "快速对决",
  stop: "关闭",
  retry: "重新启动",
  starting: "正在启动…",
  "status.not_installed": "此电脑上未安装 Unreal Verse。",
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
};

export const LAUNCHER_STRINGS: Readonly<Record<UiLanguage, Table>> = { en, de, es, pt, zh };

export function launcherText(lang: UiLanguage, key: LauncherKey, vars: Record<string, string> = {}): string {
  const table = LAUNCHER_STRINGS[lang] ?? en;
  let text = table[key] ?? en[key];
  for (const [name, value] of Object.entries(vars)) text = text.split(`{${name}}`).join(value);
  return text;
}
