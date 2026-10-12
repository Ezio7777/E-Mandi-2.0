import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { Role } from "@/types";

interface TourState {
  activeTour: Role | null;
  stepIndex: number;
  completed: Role[];
  dismissed: boolean;
  /** true only right after a tour finishes, so the toast never fires from rehydrated state */
  celebrate: boolean;
}
const initialState: TourState = { activeTour: null, stepIndex: 0, completed: [], dismissed: false, celebrate: false };

const tourSlice = createSlice({
  name: "tour",
  initialState,
  reducers: {
    tourStarted(state, a: PayloadAction<Role>) { state.activeTour = a.payload; state.stepIndex = 0; state.dismissed = false; state.celebrate = false; },
    stepChanged(state, a: PayloadAction<number>) { state.stepIndex = Math.max(0, a.payload); },
    tourSkipped(state) { state.activeTour = null; state.dismissed = true; state.celebrate = false; },
    tourCompleted(state) {
      if (state.activeTour && !state.completed.includes(state.activeTour)) state.completed.push(state.activeTour);
      state.activeTour = null; state.stepIndex = 0; state.celebrate = true;
    },
    tourAck(state) { state.celebrate = false; },
    /** Clears any running tour without marking it skipped (logout, role change). */
    tourReset(state) { state.activeTour = null; state.stepIndex = 0; state.celebrate = false; },
    tourRestarted(state, a: PayloadAction<Role>) { state.activeTour = a.payload; state.stepIndex = 0; state.dismissed = false; state.celebrate = false; },
  },
});
export const { tourStarted, stepChanged, tourSkipped, tourCompleted, tourAck, tourReset, tourRestarted } = tourSlice.actions;
export default tourSlice.reducer;
