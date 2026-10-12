import { api } from "./client";
import type { CreateListingInput, FarmerDashboardDto, ListingDto, ListingFilters, Paginated } from "@/types";

export const listingsApi = {
  marketplace: (f: ListingFilters) => api.get<Paginated<ListingDto>>("/listings", { ...f }),
  mine: () => api.get<ListingDto[]>("/farmer/listings"),
  byId: (id: string) => api.get<ListingDto>(`/listings/${id}`),
  create: (input: CreateListingInput) => api.post<ListingDto>("/listings", input),
  remove: (id: string) => api.delete<void>(`/listings/${id}`),
  farmerDashboard: () => api.get<FarmerDashboardDto>("/farmer/dashboard"),
};
