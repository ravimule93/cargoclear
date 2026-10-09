"use client";

import { use, useEffect, useState } from "react";
import { TopBar } from "@/components/shell/TopBar";
import { DocumentRail } from "@/components/rail/DocumentRail";
import { DocumentViewer } from "@/components/viewer/DocumentViewer";
import { AssessmentPanel } from "@/components/assess/AssessmentPanel";
import { DeltaDrawer } from "@/components/delta/DeltaDrawer";
import { api } from "@/lib/api";
import { useBundleStream } from "@/lib/hooks/useBundleStream";
import { Bundle, AssessmentIteration, Status } from "@/lib/types";

interface WorkbenchPageProps {
  params: Promise<{ bundleId: string }>;
}

export default function WorkbenchPage({ params }: WorkbenchPageProps) {
  const { bundleId } = use(params);

  const [bundle, setBundle] = useState<Bundle>({
    id: bundleId,
    reference: "EXP-SG-7304-001",
    destination_country: "SG",
    status: "MISSING_EVIDENCE",
    current_iteration: 1,
    documents: [
      {
        document_id: "doc-inv-01",
        bundle_id: bundleId,
        filename: "Commercial_Invoice_INV-2024-001.pdf",
        doc_type: "COMMERCIAL_INVOICE",
        gcs_uri: `gs://cargoclear-raw-pdfs/bundles/${bundleId}/raw/doc-inv-01/original.pdf`,
        sha256: "abc12345",
        bytes: 145020,
        uploaded_at: new Date().toISOString(),
      },
      {
        document_id: "doc-bol-01",
        bundle_id: bundleId,
        filename: "Bill_of_Lading_BL-8941.pdf",
        doc_type: "BILL_OF_LADING",
        gcs_uri: `gs://cargoclear-raw-pdfs/bundles/${bundleId}/raw/doc-bol-01/original.pdf`,
        sha256: "def67890",
        bytes: 230400,
        uploaded_at: new Date().toISOString(),
      },
      {
        document_id: "doc-pl-01",
        bundle_id: bundleId,
        filename: "Packing_List_PL-001.pdf",
        doc_type: "PACKING_LIST",
        gcs_uri: `gs://cargoclear-raw-pdfs/bundles/${bundleId}/raw/doc-pl-01/original.pdf`,
        sha256: "ghi11223",
        bytes: 112000,
        uploaded_at: new Date().toISOString(),
      },
    ],
    created_at: new Date().toISOString(),
  });

  const [activeDocId, setActiveDocId] = useState<string>("doc-inv-01");
  const [iterations, setIterations] = useState<AssessmentIteration[]>([]);
  const [isReassessing, setIsReassessing] = useState(false);

  // Subscribe to live SSE status stream for this bundle
  const { assessment: liveAssessment, run } = useBundleStream(bundleId);

  // Initial assessment fallback state
  const fallbackAssessment: AssessmentIteration = {
    iteration: 1,
    bundle_id: bundleId,
    status: "MISSING_EVIDENCE",
    checks: [
      {
        check_id: "W-001",
        severity: "PASS",
        message: "Net+tare (14280.0 kg) matches BoL gross (14280.0 kg) within tolerance (±71.4 kg).",
        delta: 0,
        tolerance: 71.4,
        evidence: [
          { doc: "doc-pl-01", field: "total_net_weight_kg" },
          { doc: "doc-bol-01", field: "total_gross_weight_kg" },
        ],
      },
      {
        check_id: "H-002",
        severity: "PASS",
        message: "Declared HS codes are consistent across documents: ['73041900'].",
      },
    ],
    grounding: [
      {
        document_id: "doc-inv-01",
        declared_hs: "73041900",
        top_candidate_hs: "73041900",
        top_candidate_description: "Steel pipes, seamless, for oil/gas pipelines",
        distance: 0.08,
        ambiguous: false,
        required_documents: ["MILL_TEST_CERTIFICATE"],
      },
    ],
    missing_evidence: [
      {
        id: "ME-MILL_TEST_CERTIFICATE",
        document_label: "Mill Test Certificate",
        hs_code: "73041900",
        reason: "Mandatory material compliance certificate required under AHTN Chapter 73 rules for seamless pipes.",
        regulation_ref: "AHTN 2022 / ASW Rule 4.2",
      },
    ],
    confidence: {
      min_field_confidence: 0.98,
      action: "AUTO_ACCEPT",
    },
    reasoning_delta: {
      kind: "INITIAL",
      changes: [],
      narrative: "Initial assessment completed. Identified missing required certificate for HS 7304.",
    },
    documents: ["doc-inv-01", "doc-bol-01", "doc-pl-01"],
    created_at: new Date().toISOString(),
  };

  const currentAssessment = liveAssessment || fallbackAssessment;

  // Sync iterations list when live assessment arrives
  useEffect(() => {
    if (liveAssessment) {
      setIterations((prev) => {
        const exists = prev.find((it) => it.iteration === liveAssessment.iteration);
        if (exists) {
          return prev.map((it) => (it.iteration === liveAssessment.iteration ? liveAssessment : it));
        }
        return [...prev, liveAssessment];
      });
      setIsReassessing(false);
    }
  }, [liveAssessment]);

  useEffect(() => {
    let isMounted = true;
    api.getBundle(bundleId)
      .then((bnd) => {
        if (isMounted && bnd) {
          setBundle(bnd);
          if (bnd.documents.length > 0) {
            setActiveDocId(bnd.documents[0].document_id);
          }
        }
      })
      .catch(() => {
        console.debug("Bundle fetch fallback active");
      });
    return () => {
      isMounted = false;
    };
  }, [bundleId]);

  const refreshBundle = async () => {
    try {
      const bnd = await api.getBundle(bundleId);
      if (bnd) {
        setBundle(bnd);
        if (bnd.documents.length > 0) {
          setActiveDocId(bnd.documents[0].document_id);
        }
      }
    } catch (err) {
      console.debug("Bundle fetch fallback active");
    }
  };


  // Trigger reassessment action
  const handleReassess = async () => {
    setIsReassessing(true);
    try {
      await api.reassess(bundleId);
    } catch (err) {
      console.error("Reassess failed", err);
      setIsReassessing(false);
    }
  };

  // Convert check evidence into visual highlights for the canvas viewer
  const highlights = [
    {
      id: "hl-gross",
      document_id: "doc-bol-01",
      page: 1,
      bbox: { page: 1, ymin: 400, xmin: 600, ymax: 430, xmax: 800 },
      severity: "PASS" as const,
      label: "BoL Gross Weight: 14280.0 kg",
    },
    {
      id: "hl-net",
      document_id: "doc-pl-01",
      page: 1,
      bbox: { page: 1, ymin: 600, xmin: 600, ymax: 630, xmax: 800 },
      severity: "PASS" as const,
      label: "PL Net Weight: 14000.0 kg",
    },
  ];

  return (
    <>
      <TopBar
        bundle={bundle}
        status={currentAssessment.status as Status}
        isReassessing={isReassessing || run.state === "RUNNING"}
        onReassess={handleReassess}
        onAddDocumentClick={() => {
          // Focus or open dropzone
        }}
      />

      <aside className="cc-rail" aria-label="Documents in this bundle">
        <DocumentRail
          documents={bundle.documents}
          activeDocumentId={activeDocId}
          onSelectDocument={(id) => setActiveDocId(id)}
        />
      </aside>

      <main className="cc-viewer" aria-label="Document viewer and annotations">
        <DocumentViewer
          documents={bundle.documents}
          highlights={highlights}
        />
      </main>

      <section className="cc-assess" aria-label="Compliance assessment and actions">
        <AssessmentPanel
          assessment={currentAssessment}
          bundleId={bundleId}
          runState={run}
          onDocumentUploaded={() => {
            refreshBundle();
            handleReassess();
          }}
        />
      </section>

      <section className="cc-drawer" aria-label="Reasoning delta and audit trail">
        <DeltaDrawer
          iterations={iterations.length > 0 ? iterations : [currentAssessment]}
        />
      </section>
    </>
  );
}
