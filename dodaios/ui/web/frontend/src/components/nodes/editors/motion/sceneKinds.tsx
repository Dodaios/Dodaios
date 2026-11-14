/**
 * How each scene type and transition is shown in the editor: its icon and the
 * keys of its name. One table, so the timeline, the add menu and the
 * inspector never disagree about what a "stat" looks like.
 */
import type { ComponentType, SVGProps } from "react";
import {
  ArrowRightLeft,
  BarChartHorizontal,
  Blend,
  Flag,
  Hash,
  Image as ImageIcon,
  LineChart,
  List,
  ListOrdered,
  Quote,
  Scissors,
  Type,
  Heading1,
  ZoomIn,
} from "lucide-react";

import type { SceneKind, Transition } from "./motionModel";

type Icon = ComponentType<SVGProps<SVGSVGElement>>;

export const SCENE_ICONS: Record<SceneKind, Icon> = {
  title: Heading1,
  text: Type,
  bullets: List,
  stat: Hash,
  bars: BarChartHorizontal,
  chart: LineChart,
  steps: ListOrdered,
  quote: Quote,
  image: ImageIcon,
  end: Flag,
};

export const TRANSITION_ICONS: Record<Transition, Icon> = {
  fade: Blend,
  slide: ArrowRightLeft,
  zoom: ZoomIn,
  cut: Scissors,
};

export function kindKey(kind: SceneKind): string {
  return `nodes.editor.motion.kinds.${kind}`;
}

export function transitionKey(transition: Transition): string {
  return `nodes.editor.motion.transitions.${transition}`;
}
