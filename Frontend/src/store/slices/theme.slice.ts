import { createSlice, type PayloadAction } from "@reduxjs/toolkit";
import type { Locale } from "@/types";

export type ThemePreference = "light" | "dark" | "system";
interface ThemeState { preference: ThemePreference; locale: Locale }
const initialState: ThemeState = { preference: "system", locale: "en" };

/** Mirrors next-themes (which persists) plus the UI language preference. */
const themeSlice = createSlice({
  name: "theme",
  initialState,
  reducers: {
    preferenceChanged(state, a: PayloadAction<ThemePreference>) { state.preference = a.payload; },
    localeChanged(state, a: PayloadAction<Locale>) { state.locale = a.payload; },
  },
});
export const { preferenceChanged, localeChanged } = themeSlice.actions;
export default themeSlice.reducer;
