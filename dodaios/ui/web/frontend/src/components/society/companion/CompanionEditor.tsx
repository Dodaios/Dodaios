import { useT } from "@/i18n";
import { Switch } from "@/components/ui/switch";
import { type CompanionAppearance } from "./appearance";
import { CompanionMark } from "./CompanionMark";
import "../calmSheet.css";
import { PetSprite } from "@/components/pets/PetSprite";
import { JarvisOrbMark } from "@/components/pets/DodaiosOrbMark";
import { ShaderPetMark } from "@/components/pets/ShaderPetMark";
import { usePets } from "@/hooks/usePets";
import { CUBE_CAT } from "./petCompanions";
import gigiMark from "@/assets/gigi-companion-avatar.png";
import { lazy, Suspense } from "react";
const CompanionPreview = lazy(() => import("./CompanionPreview").then(m => ({ default: m.CompanionPreview })));

/** An agent's look is one of the pets from My Pets; shapes and pixel creatures are no longer offered. */
export function CompanionEditor({ value, onChange, disabled = false, lead = false, preview3d = true }: {
  value: CompanionAppearance; onChange: (next: CompanionAppearance) => void; disabled?: boolean; lead?: boolean;
  /** Kept for callers; pets have no level-locked looks. */
  agentId?: string;
  /** The 3D turntable needs its own WebGL context; dialogs outside the map skip it. */
  preview3d?: boolean;
}) {
  const t = useT();
  const update = (patch: Partial<CompanionAppearance>) => onChange({ ...value, ...patch });
  const petsQuery = usePets();
  const pets = petsQuery.data?.pets ?? [];
  return <fieldset disabled={disabled} className="flex min-w-0 flex-col gap-5 p-4" data-testid="companion-editor">
    <div className="flex items-center gap-5 rounded-[20px] bg-secondary/50 p-5">
      {lead ? <img src={gigiMark} width={88} height={88} alt="" /> : <CompanionMark appearance={value} size={88} />}
      <div><h3 className="text-[14px] font-medium">{t("society.companion.title")}</h3><p className="mt-1 text-[13px] leading-snug text-muted-foreground">{t("society.companion.hint")}</p></div>
    </div>
    {preview3d && <Suspense fallback={null}><CompanionPreview appearance={value} lead={lead} /></Suspense>}
    {!lead && <div data-testid="companion-pet-picker"><span className="mb-1 block text-[14px] font-medium">{t("society.companion.pet")}</span>
      <p className="mb-2 text-[13px] text-muted-foreground">{pets.length || petsQuery.isLoading ? t("society.companion.pet_hint") : t("society.companion.no_pets")}</p>
      <div className="flex flex-wrap gap-2">{pets.map(pet => <button key={pet.id} type="button" title={pet.name}
        aria-label={pet.name} aria-pressed={value.pet === pet.id} onClick={() => update({ pet: pet.id })}
        className="calm-tile h-14 w-14" data-on={value.pet === pet.id}>
        {pet.kind === "shader"
          ? <ShaderPetMark className="h-10 w-10" />
          : pet.kind === "scene"
            ? <JarvisOrbMark className="h-10 w-10" />
            : <PetSprite pet={pet} state={value.pet === pet.id ? "success" : "idle"} px={44} />}
      </button>)}
      <button type="button" title={t("pets.cube_cat.title")} aria-label={t("pets.cube_cat.title")}
        aria-pressed={value.pet === CUBE_CAT.id} onClick={() => update({ pet: CUBE_CAT.id })}
        className="calm-tile h-14 min-w-14 px-2 text-[12px]" data-on={value.pet === CUBE_CAT.id} data-testid="cube-cat-wear">
        {t("pets.cube_cat.short")}
      </button>
      </div>
    </div>}
    <label className="flex items-center justify-between gap-3 text-[14px]">{t("society.companion.visible")}
      <Switch checked={value.enabled} onCheckedChange={enabled => update({ enabled })} aria-label={t("society.companion.visible")} />
    </label>
  </fieldset>;
}
