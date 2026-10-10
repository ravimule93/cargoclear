import type { AppMode, AssessmentIteration } from "@/lib/types";

interface DemoBannerProps {
  /** From GET /meta; undefined until it has loaded (or if it failed). */
  appMode?: AppMode;
  /** From the latest assessment; may be undefined until the backend populates it. */
  dataSource?: AssessmentIteration["data_source"];
}

export const DEMO_BANNER_TEXT =
  "DEMO MODE - extraction uses synthetic fixtures keyed on filename, not a real document reading.";

/** Whether the banner applies: demo app mode, or the assessment says it came from fixtures. */
export function isDemoData(appMode?: AppMode, dataSource?: AssessmentIteration["data_source"]): boolean {
  return appMode === "demo" || dataSource === "fixture";
}

export function DemoBanner({ appMode, dataSource }: DemoBannerProps) {
  if (!isDemoData(appMode, dataSource)) return null;

  return (
    <div role="note" data-testid="demo-banner" className="cc-banner">
      {DEMO_BANNER_TEXT}
    </div>
  );
}
