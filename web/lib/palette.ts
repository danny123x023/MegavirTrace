// Colour roles for charts and maps.  Categorical slots 1-2 (values, trend) were run through the
// dataviz validator in both modes: all checks pass (CVD ΔE 24.7 light / 26.8 dark).  The
// diverging arms are matched step for step in OKLab lightness around a neutral gray midpoint.

export const DIVERGING = {
  light: {
    mid: "#f0efec",
    negative: ["#86b6ef", "#3987e5", "#256abf", "#104281"], // blue, weak -> strong
    positive: ["#ea9a93", "#d75853", "#b13f3c", "#762221"], // red, weak -> strong (same OKLab L per step)
  },
  dark: {
    mid: "#383835",
    negative: ["#1c5cab", "#2a78d6", "#5598e7", "#9ec5f4"],
    positive: ["#9e3432", "#c74845", "#dd716a", "#f1aea8"],
  },
};

// Variables where "more" reads naturally as blue (water); for the rest "more" is red.
const POSITIVE_IS_BLUE = new Set(["rainfall", "downpour", "evapotranspiration", "topsoil_moisture", "soil_moisture", "land_water", "sea_level"]);

export function divergingFor(variable: string, dark: boolean) {
  const p = dark ? DIVERGING.dark : DIVERGING.light;
  return POSITIVE_IS_BLUE.has(variable)
    ? { mid: p.mid, positive: p.negative, negative: p.positive }
    : { mid: p.mid, positive: p.positive, negative: p.negative };
}

export function isDark(): boolean {
  if (typeof document === "undefined") return false;
  const t = document.documentElement.dataset.theme;
  if (t === "dark") return true;
  if (t === "light") return false;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
}
