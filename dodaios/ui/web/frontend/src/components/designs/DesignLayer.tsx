/**
 * Mounted once at the app root: loads the designs, keeps the active one's
 * colours on the document (store/designs) and draws its moving background
 * for the appearance on screen.
 */
import { useEffect } from "react";
import { DesignBackdrop } from "@/components/designs/DesignBackdrop";
import { useThemeValue } from "@/hooks/useTheme";
import { paintDesign, useDesignsStore } from "@/store/designs";

export function DesignLayer() {
  const theme = useThemeValue();
  const current = useDesignsStore((s) => s.current);
  const load = useDesignsStore((s) => s.load);

  useEffect(() => {
    // The boot script painted the cached copy; repaint from the store so the
    // style element and the class agree, then ask the backend for the truth.
    paintDesign(useDesignsStore.getState().current);
    void load();
  }, [load]);

  if (!current) return null;
  return <DesignBackdrop background={current.background} dark={theme === "dark"} />;
}
