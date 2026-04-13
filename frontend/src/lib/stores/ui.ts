import { create } from "zustand";

interface UIState {
  // Dashboard
  selectedEntityId: string | null;
  setSelectedEntityId: (id: string | null) => void;

  // Screener panel
  screenerFiltersOpen: boolean;
  setScreenerFiltersOpen: (open: boolean) => void;
  toggleScreenerFilters: () => void;

  // Entity chart mode
  chartMetric: "composite_market_score" | "mention_count" | "momentum";
  setChartMetric: (
    metric: "composite_market_score" | "mention_count" | "momentum",
  ) => void;
}

export const useUIStore = create<UIState>((set) => ({
  selectedEntityId: null,
  setSelectedEntityId: (id) => set({ selectedEntityId: id }),

  screenerFiltersOpen: false,
  setScreenerFiltersOpen: (open) => set({ screenerFiltersOpen: open }),
  toggleScreenerFilters: () =>
    set((s) => ({ screenerFiltersOpen: !s.screenerFiltersOpen })),

  chartMetric: "composite_market_score",
  setChartMetric: (metric) => set({ chartMetric: metric }),
}));
