"use client";
import { createContext, useContext, useState, ReactNode } from "react";
import { translations, Lang } from "./translations";

type LangContextValue = {
  lang: Lang;
  t: typeof translations["en"];
  toggleLang: () => void;
};

const LangContext = createContext<LangContextValue>({
  lang: "en",
  t: translations.en,
  toggleLang: () => {},
});

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>("en");
  const toggleLang = () => setLang((l) => (l === "en" ? "ur" : "en"));
  return (
    <LangContext.Provider
      value={{ lang, t: translations[lang], toggleLang }}
    >
      <div dir={lang === "ur" ? "rtl" : "ltr"}>{children}</div>
    </LangContext.Provider>
  );
}

export const useLang = () => useContext(LangContext);
