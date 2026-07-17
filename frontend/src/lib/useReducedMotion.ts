"use client";

import { useEffect, useState } from "react";

// Reads the user's OS/browser reduced-motion preference. CSS-driven
// animation/transition durations are already neutralized globally (see
// globals.css); this hook lets JS-driven timing (e.g. the analyze pipeline's
// stage-advance schedule) shorten itself too -- stages still progress
// sequentially, just without the cinematic pacing.
export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(query.matches);
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  return reduced;
}
