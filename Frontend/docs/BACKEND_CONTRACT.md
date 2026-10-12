# Backend contract (what the frontend calls)

Generated from `src/lib/api/*.ts` and `src/types/index.ts`. Those files are the source of truth. If you change the backend, change them too.

## Conventions the frontend relies on

| Topic | Requirement |
|---|---|
| **JSON casing** | **camelCase** in requests and responses. FastAPI defaults to snake_case, so use Pydantic `alias_generator=to_camel` with `populate_by_name=True` (or `response_model_by_alias=True`). |
| **Base URL** | `NEXT_PUBLIC_API_URL`, no trailing slash. All paths below are relative to it. |
| **Auth** | Either an httpOnly session cookie (requests use `credentials: "include"`) or an `accessToken` returned in the login response, which the frontend keeps in memory and sends as `Authorization: Bearer`. |
| **CORS** | `Access-Control-Allow-Origin` must be the exact frontend origin (not `*`), `Access-Control-Allow-Credentials: true`, allow headers `Content-Type, Authorization`, methods `GET,POST,PUT,PATCH,DELETE,OPTIONS`. Cross-site cookies need `SameSite=None; Secure`. |
| **Errors** | Non-2xx with JSON `{ "message": string, "code"?: string }`. FastAPI's `{ "detail": string }` is also accepted. `401` makes the frontend clear its session and go to `/login`. `403` is shown as an error. |
| **204** | Allowed for logout, delete, mark-read. |
| **Roles** | `farmer`, `buyer`, `admin`. The backend must enforce them on every endpoint. The frontend only hides UI. |

## Auth

| Method & path | Body | Returns |
|---|---|---|
| `POST /auth/login` | `{ email, password }` | `AuthSessionDto` |
| `POST /auth/otp/request` | `{ phone }` (10-digit Indian mobile, optional `+91`) | `{ sent: boolean }` |
| `POST /auth/otp/verify` | `{ phone, code }` (6 digits) | `AuthSessionDto` |
| `POST /auth/google` | `{ credential }` (Google ID token, **verify server-side**) | `AuthSessionDto` |
| `POST /auth/demo` | `{ role: "farmer" \| "buyer" \| "admin" }` | `AuthSessionDto`, with `user.isDemo = true` |
| `POST /auth/logout` | none | 204 |
| `GET /auth/me` | none | `UserDto`, or 401 |

`AuthSessionDto = { user: UserDto, accessToken?: string }`
`UserDto = { id, name, email?, phone?, role, avatarUrl?, isDemo?, location? }`

**Demo accounts must be seeded** (listings, orders, payments, requirements, matches, flagged activity, approvals, audit logs) so the recruiter tour has real data.

## Uploads (presigned S3, browser uploads directly)

1. `POST /uploads/init` with `{ fileName, contentType, size }` returns `{ uploadUrl, fields?, objectKey }`. If `fields` is present the browser does a **multipart POST** (presigned POST) with those fields plus `file`. Otherwise it does a **PUT** with `Content-Type` set to the file's type. Set the bucket's CORS to allow the frontend origin.
2. `POST /uploads/confirm` with `{ objectKey }` returns `ImageDto { id, objectKey, url }`.
3. `POST /uploads/sample` with `{ sampleId: "tomato" | "potato" | "onion" | "cabbage" }` returns `ImageDto`. It may reuse a cached grading result by image hash.

Limits enforced client-side (also enforce on the server): 5 images per listing, 8 MB each, JPEG, PNG or WebP.

## Grading and pricing

| Method & path | Notes |
|---|---|
| `POST /grading` | `{ imageKeys: string[], cropName }` returns `{ jobId }` |
| `GET /grading/{jobId}` | `GradingJobDto { jobId, status: "queued"\|"analyzing"\|"ready"\|"failed", progress?, result? }` (polled every 1.2 s until `ready` or `failed`) |
| `GET /admin/grading` | `GradingJobDto[]` for the admin review table |
| `GET /pricing/suggest?crop&grade&location` | `PriceSuggestionDto { suggested, rangeMin, rangeMax, referencePrice, trend: "up"\|"down"\|"stable", explanation, source? }` (₹ per kg) |

`GradingResultDto = { jobId, grade: "A"\|"B"\|"C", confidence (0..1), defectPercent, explanation, issues: string[], provider?, gradedAt (ISO), manualReviewRecommended: boolean }`. Set `manualReviewRecommended` from your confidence threshold. The UI shows it verbatim.

## Listings

| Method & path | Returns |
|---|---|
| `GET /listings?q&crop&grade&minPrice&maxPrice&minQuantity&location&sort&page` | `Paginated<ListingDto>` = `{ items, total, page, pageSize }`. `sort` is `newest`, `price_asc`, `price_desc` or `quantity_desc`. Empty params are omitted. Return only `active` listings here. |
| `GET /listings/{id}` | `ListingDto` |
| `POST /listings` | body `{ crop, quantityKg, location, pricePerKg, imageKeys, gradingJobId }`. Returns `ListingDto`; use `status: "pending_review"` if admin approval is needed. |
| `DELETE /listings/{id}` | 204 (farmer's own) |
| `GET /farmer/listings` | `ListingDto[]` (own, any status) |
| `GET /farmer/dashboard` | `FarmerDashboardDto { activeListings, availableQuantityKg, pendingOrders, earnings, gradingSummary: {A,B,C}, sales: [{label,value}], prices: [{label,value}] }` |

`ListingDto = { id, crop, grade, quantityKg, pricePerKg, location, farmerName, farmerVerified?, images: ImageDto[], status, availableFrom?, createdAt }`
`status ∈ draft | pending_review | active | sold_out | rejected`

## Requirements and matching

| Method & path | Notes |
|---|---|
| `GET /requirements` | `RequirementDto[]` |
| `POST /requirements` | `{ crop, quantityKg, desiredGrade, destination, deliveryDate (YYYY-MM-DD), maxBudget }` returns `RequirementDto` with `status: "matching"` |
| `GET /matches?requirementId=` | `MatchDto[] = { listingId, score (0..1), listing: ListingDto, reasons: [{ factor, matched, detail }] }`. `factor ∈ grade \| quantity \| location \| price \| availability`. **Return all five factors**, with human-readable `detail`. The UI polls every 2 s right after a requirement is created. |

## Orders and payments

| Method & path | Notes |
|---|---|
| `GET /orders`, `GET /orders/{id}` | `OrderDto` (the caller's own) |
| `POST /orders` | `{ listingId, quantityKg }` returns `OrderDto` (reserve inventory) |
| `POST /orders/{id}/confirm` | farmer confirms. Returns `OrderDto` |
| `POST /orders/{id}/cancel` | returns `OrderDto` |
| `POST /payments/initiate` | `{ orderId }` returns `PaymentSessionDto { orderId, provider, providerOrderId, amount, currency, publicKey?, status }` |
| `POST /payments/confirm` | `{ orderId, ...providerPayload }`. **Verify the provider signature server-side**, then return `PaymentSessionDto`. |
| `GET /payments`, `GET /payments/{orderId}` | `PaymentSessionDto[]` / one (polled every 2.5 s while `pending`) |

`OrderDto = { id, transactionId?, listing, farmerName, buyerName, quantityKg, pricePerKg, totalAmount, status, paymentStatus, timeline: [{ step, at? }], createdAt }`
`status ∈ created | reserved | payment_confirmed | farmer_confirmed | fulfilled | completed | cancelled | refunded | disputed`
`paymentStatus ∈ not_started | pending | success | failed | refunded | disputed`
The timeline UI is fixed: `created → reserved → payment_confirmed → farmer_confirmed → fulfilled → completed`. Include `{ step, at }` for every step reached.

The frontend never needs a secret key. `publicKey` (or `NEXT_PUBLIC_PAYMENT_PUBLIC_KEY`) is publishable only. The provider widget hook is `src/features/payments/payment-provider.ts` and is **currently a sandbox stub**.

## Admin and notifications

| Method & path | Returns |
|---|---|
| `GET /admin/analytics` | `{ totalUsers, activeFarmers, activeBuyers, listings, transactions, transactionValue, flaggedActivities, series: [{label,value}] }` |
| `GET /admin/users` / `/admin/listings` / `/admin/transactions` | `UserDto[]` / `ListingDto[]` / `OrderDto[]` |
| `GET /admin/risk` | `FlaggedActivityDto[] = { id, severity: "low"\|"medium"\|"high", event, entity, reason, recommendedAction, at }`. Use hedged wording ("flagged for review"). |
| `GET /admin/approvals` | `ApprovalDto[] = { id, title, reason, status: "pending"\|"approved"\|"rejected"\|"review_requested", history: [{ at, actor, action, note? }] }` |
| `POST /admin/approvals/{id}` | `{ action: "approve"\|"reject"\|"request_review", note? }` returns `ApprovalDto`. **Write an audit-log entry.** |
| `GET /admin/audit-logs` | `AuditLogDto[] = { id, at, actor, action, entity, detail? }` |
| `GET /notifications` | `NotificationDto[] = { id, title, body?, read, at }` |
| `POST /notifications/{id}/read` | 204 |

## Voice

`POST /voice/ask` is `multipart/form-data` with `audio` (webm/opus blob) and `language` (`en` \| `hi` \| `kn`). It returns `{ transcript, answer, audioUrl? }`. If `audioUrl` is omitted, the browser reads the answer aloud with speech synthesis.

## WebSockets (optional)

`/ws/grading/{jobId}` pushes `GradingJobDto` and `/ws/orders/{id}` pushes `OrderDto` (JSON text frames, same shapes as the REST responses). If the backend has none, the frontend gives up after 2 failed attempts and keeps polling or using cached REST data. Nothing breaks.

## Frontend environment

`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` (optional), `NEXT_PUBLIC_GOOGLE_CLIENT_ID`, `NEXT_PUBLIC_PAYMENT_PUBLIC_KEY`, `NEXT_PUBLIC_APP_ENV`. Image hosts for `next/image` go in build-time `IMAGE_REMOTE_HOSTS` (your S3 bucket or CDN hostname, comma-separated).

## Reference implementation
`src/lib/demo/handler.ts` implements every endpoint above in-browser (used when no `NEXT_PUBLIC_API_URL` is set). It is the most precise reference for response shapes, status codes and role checks (401 unauthenticated, 403 wrong role, 400 validation, 404 missing).

## Quick compatibility check

`npm run mock-api` starts a stand-in that implements all of the above with seeded data (`tools/mock-api/server.mjs`). It is a handy reference for response shapes.
