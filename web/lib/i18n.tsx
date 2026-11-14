"use client";

// Interface languages (FR19).  English text is the key; Spanish comes from the dictionary below and
// falls back to English when a string has no translation.  Verdicts are written by the server's
// templates in the requested language, so every analysis request sends `lang`.

import { createContext, useCallback, useContext, useEffect, useState } from "react";

export type Lang = "en" | "es";
export const LANGS: { id: Lang; label: string }[] = [
  { id: "en", label: "English" },
  { id: "es", label: "Español" },
];

const ES: Record<string, string> = {
  // navigation and chrome
  Explore: "Explorar",
  Compare: "Comparar",
  "Moves together": "Se mueven juntos",
  "Start here": "Por dónde empezar",
  "Ask the AI": "Pregunta a la IA",
  Method: "Método",
  "Skip to content": "Saltar al contenido",
  "Earth system trend detective": "Detective de tendencias del sistema Tierra",
  "Colour theme": "Tema de color",
  "Auto (follow the device)": "Automático (según el dispositivo)",
  Light: "Claro",
  Dark: "Oscuro",
  "Full width": "Ancho completo",
  "Switch to a centred layout": "Cambiar a un diseño centrado",
  "Switch to full width": "Cambiar a ancho completo",
  Language: "Idioma",
  "A trend is not a cause.": "Una tendencia no es una causa.",
  "You are offline: showing results saved on this device.": "Sin conexión: se muestran resultados guardados en este dispositivo.",
  // explore
  "Is this place really changing?": "¿De verdad está cambiando este lugar?",
  "Pick what (a NASA variable) and where (search, a preset, or draw a box). MegavirTrace answers what is changing, where, how much, and whether it is significant: two independent tests must agree, after allowing for year-to-year memory.":
    "Elige qué (una variable de la NASA) y dónde (busca, usa una región predefinida o dibuja un recuadro). MegavirTrace responde qué está cambiando, dónde, cuánto y si es significativo: dos pruebas independientes deben coincidir, teniendo en cuenta la memoria de un año a otro.",
  "Choose what, where and how": "Elige qué, dónde y cómo",
  What: "Qué",
  Where: "Dónde",
  How: "Cómo",
  "Loading…": "Cargando…",
  "(not loaded yet)": "(aún sin cargar)",
  "test data": "datos de prueba",
  "synthetic data": "datos sintéticos",
  "Search a country, state or city…": "Busca un país, estado o ciudad…",
  "Or choose a preset region": "O elige una región predefinida",
  "Presets…": "Regiones…",
  "Draw a box": "Dibujar un recuadro",
  "Drawing… drag on the map": "Dibujando… arrastra en el mapa",
  "Drag on the map to draw a box": "Arrastra en el mapa para dibujar un recuadro",
  "Type a box": "Escribir un recuadro",
  West: "Oeste",
  South: "Sur",
  East: "Este",
  North: "Norte",
  "Use box": "Usar recuadro",
  "Chosen:": "Elegido:",
  Places: "Lugares",
  Country: "País",
  "State / province": "Estado / provincia",
  "City (1° box)": "Ciudad (recuadro de 1°)",
  Preset: "Región predefinida",
  Yearly: "Anual",
  Season: "Estación",
  "Monthly anomalies": "Anomalías mensuales",
  "Raw months": "Meses sin procesar",
  "Dec–Feb": "dic–feb",
  "Mar–May": "mar–may",
  "Jun–Aug": "jun–ago",
  "Sep–Nov": "sep–nov",
  From: "Desde",
  to: "hasta",
  first: "inicio",
  last: "fin",
  "About {name} ({source})": "Sobre {name} ({source})",
  "What it is:": "Qué es:",
  "Why it can trend:": "Por qué puede cambiar:",
  "Caveat:": "Advertencia:",
  "Loaded {a} to {b} on a {res}° grid ({kind} data).": "Cargado de {a} a {b} en una malla de {res}° (datos {kind}).",
  "Not loaded yet.": "Aún sin cargar.",
  "Computing… the first analysis of a region can take a few seconds; repeats are instant.":
    "Calculando… el primer análisis de una región puede tardar unos segundos; las repeticiones son instantáneas.",
  "Updating…": "Actualizando…",
  "Raw months are shown as measured; the statistics use monthly anomalies (each month compared with the same month in other years).":
    "Los meses se muestran tal como se midieron; las estadísticas usan anomalías mensuales (cada mes comparado con el mismo mes de otros años).",
  "Where is it changing?": "¿Dónde está cambiando?",
  "The statistics": "Las estadísticas",
  "Computed in {ms} ms the first time; stored and reused for this data version.":
    "Calculado en {ms} ms la primera vez; guardado y reutilizado para esta versión de los datos.",
  "Yearly values": "Valores anuales",
  "Seasonal values": "Valores estacionales",
  "Monthly anomalies (seasonal cycle removed)": "Anomalías mensuales (sin el ciclo estacional)",
  "Raw monthly values": "Valores mensuales sin procesar",
  "Trend (Sen's slope)": "Tendencia (pendiente de Sen)",
  "95% range of the trend": "Rango del 95 % de la tendencia",
  // chart
  "Show table": "Ver tabla",
  "Show chart": "Ver gráfico",
  Period: "Periodo",
  "Trend line": "Línea de tendencia",
  "{title}. {n} values from {a} to {b}, in {units}. Use the left and right arrow keys to read values, or open the table.":
    "{title}. {n} valores de {a} a {b}, en {units}. Usa las flechas izquierda y derecha para leer los valores, o abre la tabla.",
  // verdict and tiles
  "Significant trend: both tests agree": "Tendencia significativa: las dos pruebas coinciden",
  "No clear trend": "Sin tendencia clara",
  "Mixed evidence: the tests disagree": "Evidencia mixta: las pruebas no coinciden",
  "Cannot be tested reliably": "No se puede evaluar con fiabilidad",
  "TEST DATA — a small development sample of real NASA data, not a final result.":
    "DATOS DE PRUEBA: una pequeña muestra de desarrollo de datos reales de la NASA, no un resultado final.",
  "SYNTHETIC DATA — made-up numbers for software testing only.": "DATOS SINTÉTICOS: números inventados solo para probar el software.",
  Caveats: "Advertencias",
  "Source:": "Fuente:",
  "reference paper": "artículo de referencia",
  grid: "malla",
  "data v{v}": "datos v{v}",
  engine: "motor",
  fingerprint: "huella",
  Statistics: "Estadísticas",
  "Rate (Sen's slope)": "Ritmo (pendiente de Sen)",
  "Least-squares rate": "Ritmo por mínimos cuadrados",
  "per decade · 95% range {a} to {b}": "por década · rango del 95 %: {a} a {b}",
  "Mann–Kendall test": "Prueba de Mann–Kendall",
  "Least-squares test": "Prueba de mínimos cuadrados",
  "seasonal test, ": "prueba estacional, ",
  "τ = {tau}, corrected for memory": "τ = {tau}, corregida por memoria",
  "t-test with {neff} effective values of {n}": "prueba t con {neff} valores efectivos de {n}",
  "Year-to-year memory": "Memoria de un año a otro",
  "lag-1 autocorrelation, small-sample corrected (raw {raw})": "autocorrelación de retardo 1, corregida para muestras pequeñas (bruta {raw})",
  "Size against the noise": "Tamaño frente al ruido",
  "trend over the record ÷ scatter = {r}": "tendencia en el registro ÷ dispersión = {r}",
  small: "pequeño",
  moderate: "moderado",
  large: "grande",
  "very large": "muy grande",
  "Years needed to detect": "Años necesarios para detectarla",
  "{n} years": "{n} años",
  "{n} more than this record": "{n} más que este registro",
  "this record is long enough for a trend this size": "este registro basta para una tendencia de este tamaño",
  Robustness: "Robustez",
  Fragile: "Frágil",
  Holds: "Se mantiene",
  "changes direction in a half or without one year": "cambia de dirección en una mitad o sin un año",
  "both halves, no end years, any one year left out": "ambas mitades, sin los años extremos, quitando cualquier año",
  "Change of pace": "Cambio de ritmo",
  "Not tested": "No evaluado",
  "yearly or seasonal values only": "solo con valores anuales o estacionales",
  "Speeding up": "Se acelera",
  "Slowing down": "Se frena",
  "Changed direction": "Cambió de dirección",
  Steady: "Constante",
  "{a} then {b} {units} per decade": "{a} y luego {b} {units} por década",
  "no clear change in pace (p {p})": "sin cambio claro de ritmo (p {p})",
  "Extra clues (exploratory)": "Pistas extra (exploratorias)",
  "Take it away:": "Llévatelo:",
  "Notebook (recomputes every number)": "Cuaderno (recalcula cada número)",
  "Embeddable card": "Tarjeta para insertar",
  "Ask the AI scientist to explain this result": "Pide a la científica IA que explique este resultado",
  Explain: "Explicar",
  "Thinking…": "Pensando…",
  // map
  "Map view": "Vista del mapa",
  "Flat map (2D)": "Mapa plano (2D)",
  "Globe (3D)": "Globo (3D)",
  "Show raw view (no false-discovery fading)": "Ver sin filtrar (sin atenuar los falsos descubrimientos)",
  "Colour scale": "Escala de colores",
  "{units} per decade": "{units} por década",
  "{n} of {m} cells pass the false-discovery test (faded cells do not; q ≤ {q}, tuned for neighbouring cells that move together, Wilks 2016).":
    "{n} de {m} celdas superan la prueba de falsos descubrimientos (las atenuadas no; q ≤ {q}, ajustada para celdas vecinas que se mueven juntas, Wilks 2016).",
  "Which cells pass depends on the region tested: the false-discovery control runs over this region's cells.":
    "Qué celdas superan la prueba depende de la región evaluada: el control de falsos descubrimientos se aplica a las celdas de esta región.",
  "Based on {basis}.": "Basado en {basis}.",
  "Dashed box: the only area this variable has data for so far.": "Recuadro discontinuo: la única zona con datos de esta variable por ahora.",
  "Cell map:": "Mapa de celdas:",
  "Map. Drag or use the arrow keys to move, plus and minus to zoom.": "Mapa. Arrastra o usa las flechas para moverte, y más y menos para acercar.",
  // GLOBE
  "Ground truth: NASA GLOBE observations": "Verificación en tierra: observaciones GLOBE de la NASA",
  "Show GLOBE ground observations": "Ver observaciones GLOBE en tierra",
  "Fetching GLOBE observations… (the first time can take a minute)": "Obteniendo observaciones GLOBE… (la primera vez puede tardar un minuto)",
  "Move together": "Se mueven juntos",
  "GLOBE sites": "Sitios GLOBE",
  "GLOBE ground observations": "Observaciones GLOBE en tierra",
  // compare
  "Compare two places": "Comparar dos lugares",
  "Region A": "Región A",
  "Region B": "Región B",
  "The trends really differ": "Las tendencias realmente difieren",
  "No clear difference": "Sin diferencia clara",
  "Difference in trend": "Diferencia de tendencia",
  "Test on the difference": "Prueba sobre la diferencia",
  "both tests must agree": "las dos pruebas deben coincidir",
  "Smallest detectable": "Mínimo detectable",
  "per decade, with this record": "por década, con este registro",
  "How much they move together": "Cuánto se mueven juntas",
  "shared ups and downs cancel in the difference": "los altibajos comunes se cancelan en la diferencia",
  "Trend in A": "Tendencia en A",
  "Trend in B": "Tendencia en B",
  significant: "significativa",
  "not significant": "no significativa",
  "The two regions": "Las dos regiones",
  "Find regions with opposite trends": "Buscar regiones con tendencias opuestas",
  "Find opposite trends": "Buscar tendencias opuestas",
  "Scanning presets…": "Revisando regiones…",
  // related
  "Do two things move together?": "¿Se mueven juntas dos cosas?",
  "Variable A": "Variable A",
  "Variable B": "Variable B",
  "Longest delay": "Retraso máximo",
  "same month only": "solo el mismo mes",
  "{n} months": "{n} meses",
  "They move together": "Se mueven juntas",
  "No clear relationship": "Sin relación clara",
  "Related is not caused by.": "Relacionado no significa causado.",
  // start
  "Where do I start?": "¿Por dónde empiezo?",
  "1. What kind of place?": "1. ¿Qué tipo de lugar?",
  "2. What are you curious about?": "2. ¿Qué te da curiosidad?",
  "Suggested variables": "Variables sugeridas",
  "Explore it": "Explorarla",
  "What is changing here?": "¿Qué está cambiando aquí?",
  "Test every variable": "Evaluar todas las variables",
  "Testing every variable…": "Evaluando todas las variables…",
  Place: "Lugar",
  // ask
  "Ask the AI scientist": "Pregunta a la científica IA",
  "Your question": "Tu pregunta",
  Ask: "Preguntar",
  "Running the analyses…": "Ejecutando los análisis…",
  "Tutor mode: guide me with questions instead of explaining": "Modo tutor: guíame con preguntas en lugar de explicar",
  // methods
  "Method & data": "Método y datos",
  "How a verdict is made": "Cómo se elabora un veredicto",
  "Checked against NASA's own numbers": "Comprobado con las cifras de la propia NASA",
  "Data sources": "Fuentes de datos",
  References: "Referencias",
  "The detailed method below is in English.": "El método detallado de abajo está en inglés.",
};

const DICTS: Record<Lang, Record<string, string>> = { en: {}, es: ES };

type Ctx = { lang: Lang; setLang: (l: Lang) => void; t: (s: string, vars?: Record<string, string | number>) => string };

const I18n = createContext<Ctx>({ lang: "en", setLang: () => {}, t: (s) => s });

function fill(s: string, vars?: Record<string, string | number>) {
  return vars ? s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m)) : s;
}

export function LangProvider({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  useEffect(() => {
    const saved = localStorage.getItem("mt-lang");
    const pick = saved === "es" || saved === "en" ? saved : navigator.language?.toLowerCase().startsWith("es") ? "es" : "en";
    setLangState(pick);
  }, []);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    localStorage.setItem("mt-lang", l);
  }, []);
  const t = useCallback((s: string, vars?: Record<string, string | number>) => fill(DICTS[lang][s] ?? s, vars), [lang]);
  return <I18n.Provider value={{ lang, setLang, t }}>{children}</I18n.Provider>;
}

export const useI18n = () => useContext(I18n);

export const THEME_ES: Record<string, string> = {
  Heat: "Calor",
  "Water cycle": "Ciclo del agua",
  "Soil and land water": "Suelo y agua en tierra",
  "Air quality": "Calidad del aire",
  Fire: "Incendios",
  Vegetation: "Vegetación",
  Ocean: "Océano",
};

/** A variable's name (and other text) in the current language. */
export function varText(v: { name: string; definition?: string; why_it_can_trend?: string; caveat?: string; i18n?: Record<string, Record<string, unknown>> } | null | undefined, lang: Lang, key: "name" | "definition" | "why_it_can_trend" | "caveat" = "name"): string {
  if (!v) return "";
  const loc = lang !== "en" ? (v.i18n?.[lang]?.[key] as string | undefined) : undefined;
  return loc ?? (v[key] as string) ?? "";
}
