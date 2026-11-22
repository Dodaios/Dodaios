/**
 * A fenced `mermaid` block as the diagram it describes, in the app's colours.
 * While the library loads and draws, the figure's place is held; a text that
 * is no diagram stays the code it is.
 */
import { useEffect, useState } from "react";

import { CodeBlock } from "@/components/docs/CodeBlock";
import { useThemeValue } from "@/hooks/useTheme";
import { renderMermaid } from "@/lib/mermaidRender";
import { appSkin, appSurface, RenderedFence, RenderedFencePending } from "./RenderedFence";

type Drawn = { code: string; theme: string; svg: string | null };

export function MermaidFence({ code }: { code: string }) {
  const theme = useThemeValue();
  const [drawn, setDrawn] = useState<Drawn | null>(null);

  useEffect(() => {
    let alive = true;
    renderMermaid(code, theme === "dark", appSkin(theme), appSurface(theme))
      .then((svg) => { if (alive) setDrawn({ code, theme, svg }); })
      .catch(() => { if (alive) setDrawn({ code, theme, svg: null }); });
    return () => { alive = false; };
  }, [code, theme]);

  // The last drawing stays until the next one is ready, so a theme change does not blink.
  if (!drawn) return <RenderedFencePending />;
  if (drawn.svg === null) return <CodeBlock language="mermaid" code={code} dense />;
  return <RenderedFence language="svg" code={drawn.svg} source={code} sourceLanguage="mermaid" themed />;
}
