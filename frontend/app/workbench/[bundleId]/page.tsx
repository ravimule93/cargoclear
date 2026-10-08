import { TopBar } from "@/components/shell/TopBar";
import { DocumentRail } from "@/components/rail/DocumentRail";
import { DocumentViewer } from "@/components/viewer/DocumentViewer";
import { AssessmentPanel } from "@/components/assess/AssessmentPanel";
import { DeltaDrawer } from "@/components/delta/DeltaDrawer";
import { Bundle, AssessmentIteration } from "@/lib/types";

interface WorkbenchPageProps {
  params: Promise<{ bundleId: string }>;
}

export default async function WorkbenchPage({ params }: WorkbenchPageProps) {
  const { bundleId } = await params;

  // Initial skeleton mock data fallback until Phase 1 Firestore is online
  const fallbackBundle: Bundle = {
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
  };

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
        id: "ME-MTC",
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

  return (
    <>
      <TopBar bundle={fallbackBundle} status={fallbackAssessment.status} />

      <aside className="cc-rail" aria-label="Documents in this bundle">
        <DocumentRail documents={fallbackBundle.documents} />
      </aside>

      <main className="cc-viewer" aria-label="Document viewer and annotations">
        <DocumentViewer
          documents={fallbackBundle.documents}
          highlights={[]}
        />
      </main>

      <section className="cc-assess" aria-label="Compliance assessment and actions">
        <AssessmentPanel assessment={fallbackAssessment} bundleId={bundleId} />
      </section>

      <section className="cc-drawer" aria-label="Reasoning delta and audit trail">
        <DeltaDrawer iterations={[fallbackAssessment]} />
      </section>
    </>
  );
}
