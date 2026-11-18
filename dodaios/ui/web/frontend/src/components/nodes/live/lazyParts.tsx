/**
 * The live build's pieces for places in the app's entry bundle (the chat
 * card, the node window's first frame). Their code arrives in its own chunk
 * a moment later, so the app's start stays within its budget
 * (scripts/ci/check_frontend_bundle_budget.py); until then the same room
 * holds a plain stand-in, so nothing moves.
 */
import { Suspense, lazy, type ReactNode } from "react";

import type { CardType } from "../nodeModel";

const Skeleton = lazy(() => import("./NodeSkeleton").then((module) => ({ default: module.NodeSkeleton })));
const TypeIcon = lazy(() => import("../NodeTypeIcon").then((module) => ({ default: module.NodeTypeIcon })));

/** The type's skeleton (`NodeSkeleton`). */
export function LazyNodeSkeleton({ type, className }: { type: CardType; className?: string }) {
  return (
    <Suspense fallback={<div className="h-full w-full" aria-busy="true" />}>
      <Skeleton type={type} className={className} />
    </Suspense>
  );
}

/** The type's line icon (`NodeTypeIcon`); `fallback` stands in while it loads. */
export function LazyNodeTypeIcon({ type, className, fallback }: { type: CardType; className?: string; fallback: ReactNode }) {
  return (
    <Suspense fallback={fallback}>
      <TypeIcon type={type} className={className} />
    </Suspense>
  );
}
