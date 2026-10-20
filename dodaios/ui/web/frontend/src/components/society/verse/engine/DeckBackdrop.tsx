/**
 * A deck's photograph and its depth: the plate layer and the occluders, added
 * to the scene while the deck is on screen and disposed when it leaves.
 */
import { useEffect, useState, type ReactNode } from "react";
import { useThree } from "@react-three/fiber";
import type { Group } from "three";
import type { Deck } from "../content/deck";
import type { StageRuntime } from "../runtime";
import { PlateLayer } from "./plateLayer";
import { disposeOccluders, loadOccluders } from "./occluders";
import { StageRenderer } from "./StageRenderer";
import { liveLoad } from "./liveLoad";

interface Props {
  runtime: StageRuntime;
  deck: Deck;
  debug: boolean;
  /** The stage is on screen (a hidden stage gives its full-resolution tiles back). */
  awake: boolean;
  /** The plate's overview is on screen (the stage hides its loading state). */
  onReady: (deck: Deck) => void;
  onError: (error: Error) => void;
  children?: ReactNode;
}

export function DeckBackdrop({ runtime, deck, debug, awake, onReady, onError, children }: Props) {
  const scene = useThree((s) => s.scene);
  const invalidate = useThree((s) => s.invalidate);
  const [plate, setPlate] = useState<PlateLayer | null>(null);
  const [occluders, setOccluders] = useState<Group | null>(null);

  useEffect(() => {
    const layer = new PlateLayer(deck);
    layer.onChange = invalidate;
    scene.add(layer.group);
    setPlate(layer);
    // A switch away (or a rebuilt renderer) aborts the load: neither the abort nor a late result may count.
    const stop = liveLoad(layer.load(), () => onReady(deck), onError);
    return () => {
      stop();
      scene.remove(layer.group);
      layer.dispose();
      setPlate(null);
    };
    // The callbacks are the stage's and stable enough; a new deck is what rebuilds the plate.
  }, [deck, scene]);

  // Off screen the full-resolution tiles go back; the overview stays for a quick return.
  useEffect(() => {
    if (!awake) plate?.trim();
  }, [awake, plate]);

  useEffect(() => {
    if (!deck.occludersUrl) return;
    const abort = new AbortController();
    let group: Group | null = null;
    // Without occluders actors would walk in front of walls: a real failure fails the deck.
    const stop = liveLoad(loadOccluders(deck.occludersUrl, abort.signal), (g) => {
      group = g;
      scene.add(g);
      setOccluders(g);
    }, onError);
    return () => {
      stop();
      abort.abort();
      if (group) { scene.remove(group); disposeOccluders(group); }
      setOccluders(null);
    };
  }, [deck, scene]);

  if (!plate) return null;
  return (
    <>
      <StageRenderer runtime={runtime} deck={deck} plate={plate} debug={debug} />
      {(occluders || !deck.occludersUrl) && children}
    </>
  );
}
