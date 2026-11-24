/**
 * The provider-tier building blocks shared by every screen that lets a user
 * configure a provider: the API Keys page's realtime tab (connection, test
 * and state pieces) and the voice section's "API Keys" tab (the `stt` and
 * `dictation` tiers as whole card lists).
 */

export type { ProviderTier } from "@/hooks/useProviders";
export { makeProviderCategories, useTierHealth, LocalModeNotice, CategoryHero, GuidancePanel } from "./tier/tierShared";
export type { LucideIcon, CategoryMeta } from "./tier/tierShared";
export { ProviderCategory, TierSection } from "./tier/ProviderCategory";
export { ProviderCard } from "./tier/ProviderCard";
export { ProviderTestControl, ActiveControl, BaseUrlField, AuthWidget, CODEX_STATUS_KEY_BY_REASON } from "./tier/ProviderControls";
export { managedRuntimeBadge } from "./tier/LocalRuntimePanel";
export type { ManagedRuntimeBadge } from "./tier/LocalRuntimePanel";
export { OllamaRuntimePanel, LibraryBrowser, LocalModelDownloadPanel } from "./tier/OllamaPanels";
export { StateChip, Tag, PROVIDER_STATE_CHIPS, providerStateChip, StatusBadge } from "./tier/ProviderChips";
export type { ProviderStateChip } from "./tier/ProviderChips";
