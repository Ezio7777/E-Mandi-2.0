export type Role = "farmer" | "buyer" | "admin";
export type Locale = "en" | "hi" | "kn";
export type Grade = "A" | "B" | "C";

export interface UserDto {
  id: string;
  name: string;
  email?: string;
  phone?: string;
  role: Role;
  avatarUrl?: string;
  isDemo?: boolean;
  location?: string;
}

export interface AuthSessionDto {
  user: UserDto;
  /** Present only if the backend uses bearer tokens instead of httpOnly cookies. */
  accessToken?: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

export interface ImageDto {
  id: string;
  objectKey: string;
  url: string;
}

export interface UploadInitDto {
  uploadUrl: string;
  fields?: Record<string, string>;
  objectKey: string;
}

export type ListingStatus = "draft" | "pending_review" | "active" | "sold_out" | "rejected";

export interface ListingDto {
  id: string;
  crop: string;
  grade: Grade;
  quantityKg: number;
  pricePerKg: number;
  location: string;
  farmerName: string;
  farmerVerified?: boolean;
  images: ImageDto[];
  status: ListingStatus;
  availableFrom?: string;
  createdAt: string;
}

export interface ListingFilters {
  q?: string;
  crop?: string;
  grade?: Grade;
  minPrice?: number;
  maxPrice?: number;
  minQuantity?: number;
  location?: string;
  sort?: "newest" | "price_asc" | "price_desc" | "quantity_desc";
  page?: number;
}

export interface CreateListingInput {
  crop: string;
  quantityKg: number;
  location: string;
  pricePerKg: number;
  imageKeys: string[];
  gradingJobId: string;
}

export interface GradingResultDto {
  jobId: string;
  grade: Grade;
  confidence: number; // 0..1
  defectPercent: number;
  explanation: string;
  issues: string[];
  provider?: string;
  gradedAt: string;
  manualReviewRecommended: boolean;
}

export type GradingJobStatus = "queued" | "analyzing" | "ready" | "failed";
export interface GradingJobDto {
  jobId: string;
  status: GradingJobStatus;
  progress?: number;
  result?: GradingResultDto;
}

export interface PriceSuggestionDto {
  suggested: number;
  rangeMin: number;
  rangeMax: number;
  referencePrice: number;
  trend: "up" | "down" | "stable";
  explanation: string;
  source?: string;
}

export type MatchFactor = "grade" | "quantity" | "location" | "price" | "availability";
export interface MatchReasonDto {
  factor: MatchFactor;
  matched: boolean;
  detail: string;
}
export interface MatchDto {
  listingId: string;
  score: number;
  listing: ListingDto;
  reasons: MatchReasonDto[];
}

export interface RequirementDto {
  id: string;
  crop: string;
  quantityKg: number;
  desiredGrade: Grade;
  destination: string;
  deliveryDate: string;
  maxBudget: number;
  status: "matching" | "matched" | "closed";
  createdAt: string;
}
export type CreateRequirementInput = Omit<RequirementDto, "id" | "status" | "createdAt">;

export type OrderStatus =
  | "created" | "reserved" | "payment_confirmed" | "farmer_confirmed" | "fulfilled" | "completed"
  | "cancelled" | "refunded" | "disputed";

export interface OrderDto {
  id: string;
  transactionId?: string;
  listing: ListingDto;
  farmerName: string;
  buyerName: string;
  quantityKg: number;
  pricePerKg: number;
  totalAmount: number;
  status: OrderStatus;
  paymentStatus: PaymentStatus;
  timeline: { step: OrderStatus; at?: string }[];
  createdAt: string;
}

export type PaymentStatus = "not_started" | "pending" | "success" | "failed" | "refunded" | "disputed";

export interface PaymentSessionDto {
  orderId: string;
  provider: string;
  providerOrderId: string;
  amount: number;
  currency: string;
  publicKey?: string;
  status: PaymentStatus;
}

export type Severity = "low" | "medium" | "high";
export interface FlaggedActivityDto {
  id: string;
  severity: Severity;
  event: string;
  entity: string;
  reason: string;
  recommendedAction: string;
  at: string;
}

export interface ApprovalDto {
  id: string;
  title: string;
  reason: string;
  status: "pending" | "approved" | "rejected" | "review_requested";
  history: { at: string; actor: string; action: string; note?: string }[];
}

export interface AuditLogDto {
  id: string; at: string; actor: string; action: string; entity: string; detail?: string;
}

export interface AdminAnalyticsDto {
  totalUsers: number; activeFarmers: number; activeBuyers: number; listings: number;
  transactions: number; transactionValue: number; flaggedActivities: number;
  series: { label: string; value: number }[];
}

export interface FarmerDashboardDto {
  activeListings: number; availableQuantityKg: number; pendingOrders: number; earnings: number;
  gradingSummary: { A: number; B: number; C: number };
  sales: { label: string; value: number }[];
  prices: { label: string; value: number }[];
}

export interface NotificationDto {
  id: string; title: string; body?: string; read: boolean; at: string;
}

export interface VoiceReplyDto {
  transcript: string;
  answer: string;
  audioUrl?: string;
}
