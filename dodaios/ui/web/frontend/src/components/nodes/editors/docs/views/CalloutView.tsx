/**
 * A callout in the document: the coloured box the page draws for a
 * `> [!TIP]` quote, with its text editable in place and its tone switchable
 * from a small menu in its corner.
 */
import { NodeViewContent, NodeViewWrapper, type NodeViewProps } from "@tiptap/react";
import { AlertOctagon, AlertTriangle, ChevronDown, Info, Lightbulb, MessageSquareWarning, type LucideIcon } from "lucide-react";

import { useT } from "@/i18n";
import { MenuItem, Popover, ToolbarButton } from "../../controls";
import { CALLOUT_TONES, isCalloutTone, type CalloutTone } from "../markdown/parse";

export const TONE_ICON: Record<CalloutTone, LucideIcon> = {
  note: Info,
  tip: Lightbulb,
  important: MessageSquareWarning,
  warning: AlertTriangle,
  caution: AlertOctagon,
};

export function CalloutView({ node, updateAttributes, editor }: NodeViewProps) {
  const t = useT();
  const tone: CalloutTone = isCalloutTone(node.attrs.tone) ? node.attrs.tone : "note";
  const Icon = TONE_ICON[tone];
  const toneName = t(`nodes.editor.docs.callout.tones.${tone}`);
  return (
    <NodeViewWrapper
      as="aside"
      className="doc-callout"
      data-tone={tone}
      role="note"
      aria-label={toneName}
      data-testid="docs-callout"
    >
      <div className="doc-callout-icon" contentEditable={false}>
        <Icon className="h-4 w-4" aria-hidden />
      </div>
      <NodeViewContent className="doc-callout-body" />
      {editor.isEditable && (
        <div className="doc-callout-tone" contentEditable={false}>
          <Popover
            role="menu"
            align="end"
            label={t("nodes.editor.docs.callout.tone")}
            trigger={
              <ToolbarButton
                label={`${t("nodes.editor.docs.callout.tone")}: ${toneName}`}
                icon={<ChevronDown aria-hidden />}
                className="h-6 w-6"
                data-testid="docs-callout-tone"
              />
            }
          >
            {(close) =>
              CALLOUT_TONES.map((value) => {
                const ItemIcon = TONE_ICON[value];
                return (
                  <MenuItem
                    key={value}
                    label={t(`nodes.editor.docs.callout.tones.${value}`)}
                    icon={<ItemIcon aria-hidden />}
                    checked={value === tone}
                    onClick={() => {
                      updateAttributes({ tone: value });
                      close();
                    }}
                  />
                );
              })
            }
          </Popover>
        </div>
      )}
    </NodeViewWrapper>
  );
}
