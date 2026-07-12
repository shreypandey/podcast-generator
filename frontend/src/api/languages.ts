// The 11 Bulbul-speakable languages (10 Indian + Indian English) — the only supported set
// per REQUIREMENTS.md. Static metadata; no backend call needed for the create form.

export interface LangMeta {
  code: string;
  label: string; // English name
  native: string; // endonym
  flag: string; // emoji used as a lightweight glyph
}

export const LANGUAGES: LangMeta[] = [
  { code: "en-IN", label: "English", native: "English", flag: "🇬🇧" },
  { code: "hi-IN", label: "Hindi", native: "हिन्दी", flag: "🇮🇳" },
  { code: "bn-IN", label: "Bengali", native: "বাংলা", flag: "🇮🇳" },
  { code: "ta-IN", label: "Tamil", native: "தமிழ்", flag: "🇮🇳" },
  { code: "te-IN", label: "Telugu", native: "తెలుగు", flag: "🇮🇳" },
  { code: "mr-IN", label: "Marathi", native: "मराठी", flag: "🇮🇳" },
  { code: "gu-IN", label: "Gujarati", native: "ગુજરાતી", flag: "🇮🇳" },
  { code: "kn-IN", label: "Kannada", native: "ಕನ್ನಡ", flag: "🇮🇳" },
  { code: "ml-IN", label: "Malayalam", native: "മലയാളം", flag: "🇮🇳" },
  { code: "pa-IN", label: "Punjabi", native: "ਪੰਜਾਬੀ", flag: "🇮🇳" },
  { code: "od-IN", label: "Odia", native: "ଓଡ଼ିଆ", flag: "🇮🇳" },
];

const BY_CODE = new Map(LANGUAGES.map((l) => [l.code, l]));

export function lang(code: string): LangMeta {
  return BY_CODE.get(code) ?? { code, label: code, native: code, flag: "🌐" };
}
