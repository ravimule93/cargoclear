"use client";

import React, { createContext, useContext, useState, useCallback } from "react";

type Politeness = "polite" | "assertive";
type AnnounceFn = (message: string, politeness?: Politeness) => void;

const AnnounceContext = createContext<AnnounceFn>(() => {});

export const useAnnounce = () => useContext(AnnounceContext);

export function LiveRegionRoot({ children }: { children: React.ReactNode }) {
  const [politeMessage, setPoliteMessage] = useState("");
  const [assertiveMessage, setAssertiveMessage] = useState("");

  const announce: AnnounceFn = useCallback((message, politeness = "polite") => {
    if (politeness === "assertive") {
      setAssertiveMessage("");
      requestAnimationFrame(() => setAssertiveMessage(message));
    } else {
      setPoliteMessage("");
      requestAnimationFrame(() => setPoliteMessage(message));
    }
  }, []);

  return (
    <AnnounceContext.Provider value={announce}>
      {children}

      {/* Polite region for regular background progress updates */}
      <div
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
      >
        {politeMessage}
      </div>

      {/* Assertive alert region for critical regulatory contradictions or immediate errors */}
      <div
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
        className="sr-only"
      >
        {assertiveMessage}
      </div>
    </AnnounceContext.Provider>
  );
}
