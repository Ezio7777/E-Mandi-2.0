import { createSlice, type PayloadAction } from "@reduxjs/toolkit";

interface UiState { sidebarCollapsed: boolean; drawerOpen: boolean; wizardDraftExists: boolean }
const initialState: UiState = { sidebarCollapsed: false, drawerOpen: false, wizardDraftExists: false };

const uiSlice = createSlice({
  name: "ui",
  initialState,
  reducers: {
    sidebarToggled(state) { state.sidebarCollapsed = !state.sidebarCollapsed; },
    drawerToggled(state, a: PayloadAction<boolean | undefined>) { state.drawerOpen = a.payload ?? !state.drawerOpen; },
    wizardDraftChanged(state, a: PayloadAction<boolean>) { state.wizardDraftExists = a.payload; },
  },
});
export const { sidebarToggled, drawerToggled, wizardDraftChanged } = uiSlice.actions;
export default uiSlice.reducer;
