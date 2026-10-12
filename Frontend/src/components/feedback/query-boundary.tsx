"use client";
import type { UseQueryResult } from "@tanstack/react-query";
import { ErrorState } from "./error-state";

interface Props<T> {
  query: UseQueryResult<T>;
  skeleton: React.ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: React.ReactNode;
  children: (data: T) => React.ReactNode;
}

/** One place that guarantees loading / error+retry / empty / data. No blank screens. */
export function QueryBoundary<T>({ query, skeleton, isEmpty, empty, children }: Props<T>) {
  if (query.isPending) return <>{skeleton}</>;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => query.refetch()} />;
  if (isEmpty?.(query.data) && empty) return <>{empty}</>;
  return <>{children(query.data)}</>;
}
