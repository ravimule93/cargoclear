# CargoClear data retention policy

Customer evidence artifacts are retained for **90 days**: original PDFs, derived PDFs, processed page images, extraction-adjacent storage metadata, and transform metadata in the dedicated `RAW_BUCKET`.

Cloud Storage Object Lifecycle Management enforces deletion at age 90 days through `infra/storage/cargoclear-artifact-lifecycle-90-days.json`. The setup script previews by default; apply only after reviewing the dedicated bucket's existing lifecycle rules:

```bash
export RAW_BUCKET=cargoclear-raw-pdfs
APPLY_RETENTION_POLICY=yes bash infra/storage/setup_artifact_retention.sh
```

## Audit records and legal hold

Assessment audit records are Firestore records, not artifacts in `RAW_BUCKET`. They have **no automatic TTL** and remain retained under legal hold until an authorised legal/compliance owner releases them. The 90-day artifact lifecycle is not permission to destroy audit records.

The lifecycle policy assumes `RAW_BUCKET` is dedicated to CargoClear evidence artifacts. Do not apply it to a shared bucket.
