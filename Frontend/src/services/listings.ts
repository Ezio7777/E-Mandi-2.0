"use client";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { listingsApi } from "@/lib/api";
import { queryKeys } from "@/lib/query/keys";
import type { CreateListingInput, ListingDto, ListingFilters } from "@/types";

export const useMarketplace = (f: ListingFilters) =>
  useQuery({ queryKey: queryKeys.listings.list(f), queryFn: () => listingsApi.marketplace(f), placeholderData: keepPreviousData });
export const useMyListings = () => useQuery({ queryKey: queryKeys.listings.mine, queryFn: listingsApi.mine });
export const useListing = (id: string) => useQuery({ queryKey: queryKeys.listings.detail(id), queryFn: () => listingsApi.byId(id) });
export const useFarmerDashboard = () => useQuery({ queryKey: queryKeys.dashboard.farmer, queryFn: listingsApi.farmerDashboard });

export function useCreateListing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (i: CreateListingInput) => listingsApi.create(i),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.listings.all });
      void qc.invalidateQueries({ queryKey: queryKeys.dashboard.farmer });
    },
  });
}

export function useDeleteListing() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => listingsApi.remove(id),
    // Optimistic: remove from "mine" instantly, roll back on error.
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: queryKeys.listings.mine });
      const prev = qc.getQueryData<ListingDto[]>(queryKeys.listings.mine);
      qc.setQueryData<ListingDto[]>(queryKeys.listings.mine, (cur) => cur?.filter((l) => l.id !== id));
      return { prev };
    },
    onError: (_e, _id, ctx) => ctx?.prev && qc.setQueryData(queryKeys.listings.mine, ctx.prev),
    onSettled: () => void qc.invalidateQueries({ queryKey: queryKeys.listings.all }),
  });
}
