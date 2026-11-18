/**
 * Settings → Behavior → Nodes as they are built: whether the node window
 * opens by itself beside the conversation when an agent makes a node there
 * (components/nodes/live/autoOpen.ts, docs/node-live-build.md). Default on.
 */
import { useEffect, useState } from "react";

import { Switch } from "@/components/ui/switch";
import { useT } from "@/i18n";
import { isNodeAutoOpenEnabled, onNodeAutoOpenChange, setNodeAutoOpenEnabled } from "@/lib/nodeAutoOpen";
import { SettingsCard, SettingsRow, SettingsSection } from "@/views/settings/SettingsLayout";

export function NodeLiveGroup() {
  const t = useT();
  const [enabled, setEnabled] = useState(isNodeAutoOpenEnabled);
  useEffect(() => onNodeAutoOpenChange(() => setEnabled(isNodeAutoOpenEnabled())), []);
  return (
    <SettingsSection title={t("settings_view.node_live.title")}>
      <SettingsCard>
        <SettingsRow
          id="settings-node-live-open"
          title={t("settings_view.node_live.open_title")}
          description={t("settings_view.node_live.open_description")}
          control={
            <Switch
              checked={enabled}
              aria-label={t("settings_view.node_live.open_title")}
              data-testid="settings-node-live-open"
              onCheckedChange={(next) => {
                setEnabled(next);
                setNodeAutoOpenEnabled(next);
              }}
            />
          }
        />
      </SettingsCard>
    </SettingsSection>
  );
}
