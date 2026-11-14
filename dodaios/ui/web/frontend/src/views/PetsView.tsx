import { useEffect, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useReducedMotion } from "framer-motion";
import { Check, Loader2, PawPrint, Plus, Trash2 } from "lucide-react";

import { PageHeader } from "@/components/layout/PageHeader";
import { CreatePetDialog } from "@/components/pets/CreatePetDialog";
import { PetSprite, integerScaleFor } from "@/components/pets/PetSprite";
import { Button } from "@/components/ui/button";
import { pickActivePet, useDeletePet, usePets, useSelectPet } from "@/hooks/usePets";
import { useT } from "@/i18n";
import { PET_STATES } from "@/lib/petStates";
import type { Pet } from "@/lib/petsApi";
import { cn } from "@/lib/utils";
import { useEventStore } from "@/store/events";

/**
 * Settings → My Pets — the pets the app draws (`docs/pets.md`).
 *
 * Pets live inside the app only: the active pet is how the assistant looks in
 * the app, agents can wear any pet, and the Verse walks the active one. Top to
 * bottom: what a pet is; the active pet playing through all its states; then
 * every pet as a tile, plus "Create pet".
 *
 * Everything reads from one query (`usePets`), which the `PetChanged` event
 * refreshes, so another window moves this page too.
 */

/** How long the big preview holds each state before showing the next. */
const STATE_CYCLE_MS = 2500;
/** Largest edge of the big preview and of a grid tile's sprite, in px. */
const HERO_SPRITE_PX = 168;
const TILE_SPRITE_PX = 96;

function useStateCycle(enabled: boolean): number {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    if (!enabled) {
      setIndex(0);
      return;
    }
    const timer = window.setInterval(
      () => setIndex((current) => (current + 1) % PET_STATES.length),
      STATE_CYCLE_MS,
    );
    return () => window.clearInterval(timer);
  }, [enabled]);
  return index;
}

export function PetsView() {
  const t = useT();
  const pushToast = useEventStore((s) => s.pushToast);
  const pets = usePets();
  const select = useSelectPet();
  const remove = useDeletePet();

  const [createOpen, setCreateOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Pet | null>(null);

  const data = pets.data;
  // A pet that is gone (or the old "none") falls back the way the app's own marks do.
  const activePet = pickActivePet(data);

  const describe = (pet: Pet) => {
    const key = `pets.builtin.${pet.id}.description`;
    const localized = pet.builtin ? t(key) : key;
    return localized !== key ? localized : pet.description;
  };

  function choose(petId: string) {
    if (!data || activePet?.id === petId || select.isPending) return;
    select.mutate(petId, {
      onError: (error) =>
        pushToast("error", t("pets.save_error").replace("{0}", (error as Error).message)),
    });
  }

  function confirmDelete() {
    const pet = pendingDelete;
    if (!pet) return;
    remove.mutate(pet.id, {
      onSuccess: () => pushToast("success", t("pets.deleted").replace("{0}", pet.name)),
      onError: (error) =>
        pushToast("error", t("pets.save_error").replace("{0}", (error as Error).message)),
      onSettled: () => setPendingDelete(null),
    });
  }

  return (
    <div
      data-testid="pets-view"
      className="flex h-full flex-col overflow-y-auto bg-background px-8 pb-10 scrollbar-jarvis"
    >
      <div className="w-full max-w-[1400px]">
        <PageHeader
          icon={<PawPrint />}
          title={t("pets.title")}
          description={t("pets.subtitle")}
        />

        {pets.isError ? (
          <div className="rounded-xl border border-border bg-card p-5" role="alert">
            <p className="text-base text-destructive">
              {t("pets.load_error").replace("{0}", (pets.error as Error).message)}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => void pets.refetch()}
            >
              {t("common.retry")}
            </Button>
          </div>
        ) : (
          <>
            <ActivePetCard
              pet={activePet}
              loading={!data}
              description={activePet ? describe(activePet) : ""}
            />

            <div className="mb-3 mt-8 flex items-center justify-between gap-4">
              <h2 className="text-lg font-semibold text-foreground-strong">{t("pets.my_pets")}</h2>
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="pets-create"
                disabled={!data}
                onClick={() => setCreateOpen(true)}
              >
                <Plus aria-hidden />
                {t("pets.create")}
              </Button>
            </div>

            <ul
              data-testid="pets-grid"
              className="grid gap-3 [grid-template-columns:repeat(auto-fill,minmax(200px,1fr))]"
            >
              {!data ? (
                [0, 1, 2, 3].map((index) => (
                  <li
                    key={index}
                    aria-hidden
                    className="h-[196px] animate-pulse rounded-xl border border-border bg-foreground/5"
                  />
                ))
              ) : (
                <>
                  {data.pets.map((pet) => (
                    <li key={pet.id}>
                      <PetTile
                        id={pet.id}
                        name={pet.name}
                        description={describe(pet)}
                        selected={activePet?.id === pet.id}
                        disabled={select.isPending}
                        onSelect={() => choose(pet.id)}
                        selectedLabel={t("pets.selected")}
                        onDelete={pet.builtin ? undefined : () => setPendingDelete(pet)}
                        deleteLabel={t("pets.delete_named").replace("{0}", pet.name)}
                      >
                        <PetSprite
                          pet={pet}
                          state="idle"
                          scale={integerScaleFor(pet.frame_size, TILE_SPRITE_PX)}
                        />
                      </PetTile>
                    </li>
                  ))}
                </>
              )}
            </ul>
          </>
        )}
      </div>

      <CreatePetDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(pet) => {
          pushToast("success", t("pets.created").replace("{0}", pet.name));
          choose(pet.id);
        }}
      />

      <DeletePetDialog
        pet={pendingDelete}
        busy={remove.isPending}
        onCancel={() => setPendingDelete(null)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function ActivePetCard({
  pet,
  loading,
  description,
}: {
  pet: Pet | null;
  loading: boolean;
  description: string;
}) {
  const t = useT();
  const reduced = useReducedMotion() ?? false;
  const stateIndex = useStateCycle(Boolean(pet) && !reduced);
  const state = PET_STATES[stateIndex];
  const stateLabel = t(`pets.states.${state}`);

  return (
    <section
      data-testid="pets-active-card"
      aria-label={t("pets.preview_title")}
      className="grid gap-5 rounded-xl border border-border bg-card p-5 lg:grid-cols-[minmax(0,300px)_minmax(0,1fr)]"
    >
      <div className="flex flex-col items-center justify-center gap-3 rounded-lg bg-secondary/60 px-4 py-5">
        <div className="grid h-[180px] w-full place-items-center">
          {loading ? (
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" aria-hidden />
          ) : pet ? (
            <PetSprite
              pet={pet}
              state={state}
              scale={integerScaleFor(pet.frame_size, HERO_SPRITE_PX)}
              label={`${pet.name}: ${stateLabel}`}
            />
          ) : null}
        </div>
        {pet && (
          <span
            data-testid="pets-state-label"
            className="rounded-full border border-border bg-background px-2.5 py-0.5 text-xs font-medium text-muted-foreground"
          >
            {stateLabel}
          </span>
        )}
      </div>

      <div className="flex min-w-0 flex-col">
        <p className="text-sm text-muted-foreground">{t("pets.preview_title")}</p>
        <p className="mt-0.5 truncate text-lg font-semibold text-foreground-strong">
          {loading ? " " : pet ? pet.name : t("pets.none_name")}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">{loading ? "" : description}</p>
      </div>
    </section>
  );
}

function PetTile({
  id,
  name,
  description,
  selected,
  disabled,
  selectedLabel,
  onSelect,
  onDelete,
  deleteLabel,
  children,
}: {
  id: string;
  name: string;
  description: string;
  selected: boolean;
  disabled: boolean;
  selectedLabel: string;
  onSelect: () => void;
  onDelete?: () => void;
  deleteLabel?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="group relative h-full">
      <button
        type="button"
        data-testid={`pet-tile-${id}`}
        aria-pressed={selected}
        disabled={disabled && !selected}
        onClick={onSelect}
        className={cn(
          "flex h-full w-full flex-col rounded-xl border bg-card p-3 text-left transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          selected
            ? "border-accent ring-1 ring-accent"
            : "border-border hover:border-border-strong",
        )}
      >
        <div className="grid h-28 w-full place-items-center overflow-hidden rounded-lg bg-secondary/60">
          {children}
        </div>
        <div className="mt-3 flex min-w-0 items-center gap-2 pr-6">
          <span className="truncate text-base font-medium text-foreground">{name}</span>
          {selected && (
            <span className="inline-flex shrink-0 items-center gap-1 text-xs font-medium text-accent">
              <Check className="h-3.5 w-3.5" aria-hidden />
              {selectedLabel}
            </span>
          )}
        </div>
        {/* Two lines keep the tiles even; the title carries the rest, so a
            long description can be read without selecting the pet. */}
        <p title={description} className="mt-0.5 line-clamp-2 text-sm text-muted-foreground">
          {description}
        </p>
      </button>
      {onDelete && (
        <button
          type="button"
          data-testid={`pet-delete-${id}`}
          aria-label={deleteLabel}
          title={deleteLabel}
          onClick={onDelete}
          className="absolute bottom-3 right-3 grid h-7 w-7 place-items-center rounded-md text-muted-foreground opacity-70 transition-colors hover:bg-secondary hover:text-destructive hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <Trash2 className="h-4 w-4" aria-hidden />
        </button>
      )}
    </div>
  );
}

function DeletePetDialog({
  pet,
  busy,
  onCancel,
  onConfirm,
}: {
  pet: Pet | null;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const t = useT();
  return (
    <Dialog.Root open={pet !== null} onOpenChange={(open) => !open && !busy && onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[80] bg-scrim/75 backdrop-blur-sm data-[state=open]:animate-in data-[state=open]:fade-in-0 motion-reduce:animate-none" />
        <Dialog.Content
          data-testid="delete-pet-dialog"
          className="fixed inset-0 z-[80] m-auto h-fit w-[min(400px,calc(100vw-32px))] rounded-2xl border border-border bg-popover p-6 text-popover-foreground shadow-float outline-none data-[state=open]:animate-in data-[state=open]:fade-in-0 data-[state=open]:zoom-in-95 motion-reduce:animate-none"
        >
          <Dialog.Title className="text-base font-semibold text-foreground-strong">
            {t("pets.delete_title").replace("{0}", pet?.name ?? "")}
          </Dialog.Title>
          <Dialog.Description className="mt-1.5 text-sm text-muted-foreground">
            {t("pets.delete_body")}
          </Dialog.Description>
          <div className="mt-6 flex justify-end gap-2">
            <Button type="button" variant="ghost" disabled={busy} onClick={onCancel}>
              {t("common.cancel")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              data-testid="delete-pet-confirm"
              disabled={busy}
              onClick={onConfirm}
            >
              {busy && <Loader2 className="animate-spin" aria-hidden />}
              {t("pets.delete")}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
