import { createContext, useContext, useMemo, type ReactNode } from "react";

type Lang = "zh" | "en";

interface I18nValue {
  lang: Lang;
  setLang: (lang: Lang) => void;
  tr: (zh: string, en: string) => string;
}

const I18nContext = createContext<I18nValue>({
  lang: "zh",
  setLang: () => undefined,
  tr: (zh) => zh,
});

export function I18nProvider({ lang, setLang, children }: {
  lang: Lang;
  setLang: (lang: Lang) => void;
  children: ReactNode;
}) {
  const value = useMemo<I18nValue>(() => ({
    lang,
    setLang,
    tr: (zh, en) => (lang === "en" ? en : zh),
  }), [lang, setLang]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  return useContext(I18nContext);
}
