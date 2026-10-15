# Stage 25 — wire format, refund restock, certificate PDFs

## Wire format (global)
- Every success body is `{ "data": ..., "meta": ... }`; every error is `{ "error": { code, message, details, requestId } }`.
- All JSON keys are `camelCase` (schemas derive from `CamelModel`; free-form blobs use `CamelBlob`). Query parameters stay `snake_case`.
- Match `score` and the per-factor scores are 0–100 (rounded to 0.1); stored values stay 0–1.

## Refund auto-restock (migration 0005)
- Payment commit stamps `orders.stock_committed_at`. A **full** completed refund returns each item's quantity to its listing
  (`SOLD`/`RESERVED` → `ACTIVE` when stock > 0), once (`orders.restocked_at`), with audit `order.restocked` and a farmer notification.
- Partial refunds never restock. Orders whose sale was never committed (late-payment auto-refund of a cancelled order) are not restocked.
- Cancelled-after-paid orders restock only when their refund completes.

## Quality certificates (migration 0006)
- Farmer: `POST /documents/init` → direct S3 upload (application/pdf, ≤ `DOCUMENT_MAX_BYTES`) → `POST /documents/confirm`.
  Max `DOCUMENT_MAX_PER_LISTING` per listing; listing must be DRAFT/ACTIVE/REVIEW_REQUIRED.
- Server validation: `%PDF-` magic, `%%EOF`, pypdf parse, ≤ `DOCUMENT_MAX_PAGES`, rejects encrypted files and any
  JavaScript / OpenAction / Launch / embedded files / forms. Invalid uploads are deleted from S3 immediately.
- Review: `GET /documents/admin/queue`, `POST /documents/{id}/verify|reject` (admin, not demo, decided once, audited, farmer notified).
- Visibility: owner/admin see all; everyone else sees only `VERIFIED`. Reads are always short-lived presigned URLs (never CDN).
- Orphan sweeper treats `listing_documents.s3_key` as known keys.
- A verified document is evidence for humans only; it never alters grade, price or inventory.
- Listings expose `verifiedDocumentCount` (additive).
