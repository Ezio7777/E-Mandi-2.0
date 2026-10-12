"use client";
import { CircleHelp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAppDispatch, useAppSelector } from "@/store/hooks";
import { tourRestarted } from "@/store/slices/tour.slice";

/** Header entry point: starts (or restarts) the walkthrough for the signed-in role. */
export function TourLauncher({ onStart }: { onStart?: () => void }) {
  const dispatch = useAppDispatch();
  const role = useAppSelector((s) => s.auth.role);
  if (!role) return null;
  return (
    <Button variant="ghost" size="icon" aria-label="Start guided tour" onClick={() => { onStart?.(); dispatch(tourRestarted(role)); }}>
      <CircleHelp />
    </Button>
  );
}
