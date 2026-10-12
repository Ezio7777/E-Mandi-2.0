import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { Role } from "@/types";

interface TourState {
  activeTour: Role | null;
  stepIndex: number;
  completed: Role[];
  dismissed: boolean;
  /** true only right after a tour finishes, so the toast never fires from rehydrated state */
  celebrate: boolean;
  /** Ask the Sell wizard to show this step with demo data (tour only, never persisted). */
  wizardGoal: { goal: number; sample: boolean } | null;
  /** Ask a form to fill itself with demo values (tour only, never persisted). */
  fill: "requirement" | null;
}
const initialState: TourState = { activeTour: null, stepIndex: 0, completed: [], dismissed: false, celebrate: false, wizardGoal: null, fill: null };

const tourSlice = createSlice({
  name: "tour",
  initialState,
  reducers: {
    tourStarted(state, a: PayloadAction<Role>) { state.activeTour = a.payload; state.stepIndex = 0; state.dismissed = false; state.celebrate = false; },
    stepChanged(state, a: PayloadAction<number>) { state.stepIndex = Math.max(0, a.payload); },
    tourSkipped(state) { state.activeTour = null; state.dismissed = true; state.celebrate = false; state.wizardGoal = null; state.fill = null; },
    tourCompleted(state) {
      if (state.activeTour && !state.completed.includes(state.activeTour)) state.completed.push(state.activeTour);
      state.activeTour = null; state.stepIndex = 0; state.celebrate = true; state.wizardGoal = null; state.fill = null;
    },
    tourAck(state) { state.celebrate = false; },
    driveSet(state, a: PayloadAction<{ wizardGoal: TourState["wizardGoal"]; fill: TourState["fill"] }>) { state.wizardGoal = a.payload.wizardGoal; state.fill = a.payload.fill; },
    /** Clears any running tour without marking it skipped (logout, role change). */
    tourReset(state) { state.activeTour = null; state.stepIndex = 0; state.celebrate = false; state.wizardGoal = null; state.fill = null; },
    tourRestarted(state, a: PayloadAction<Role>) { state.activeTour = a.payload; state.stepIndex = 0; state.dismissed = false; state.celebrate = false; },
  },
});
export const { tourStarted, stepChanged, tourSkipped, tourCompleted, tourAck, driveSet, tourReset, tourRestarted } = tourSlice.actions;
export default tourSlice.reducer;
