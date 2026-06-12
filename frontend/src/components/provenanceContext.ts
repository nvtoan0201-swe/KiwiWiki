// Context + hook for the provenance overlay, split out from the provider
// component so each file is a clean fast-refresh boundary.

import { createContext, useContext } from "react";

import type { ConfidenceLabel, Provenance } from "../api/types";

export interface TraceRequest {
  projectId: string;
  /** Output entity id (gap id, report id, analysis id, …) — looked up server-side. */
  refId?: string;
  /** Trace everything tied to one source instead. */
  sourceId?: string;
  /** Already-resolved provenance rows (skips the fetch). */
  rows?: Provenance[];
  /** The claim text being traced, for the header. */
  claimText?: string;
  confidenceLabel?: ConfidenceLabel | null;
}

export interface ProvenanceContextValue {
  openTrace: (req: TraceRequest) => void;
}

export const ProvenanceCtx = createContext<ProvenanceContextValue>({ openTrace: () => {} });

export function useProvenanceTrace(): ProvenanceContextValue {
  return useContext(ProvenanceCtx);
}
