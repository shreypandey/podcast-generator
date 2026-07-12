import type { RunLanguages } from "../api";
import { lang as meta } from "../api/languages";

export function LanguageSwitcher({
  languages,
  value,
  onChange,
}: {
  languages: RunLanguages;
  value: string;
  onChange: (code: string) => void;
}) {
  if (languages.requested.length <= 1) return null;
  return (
    <div className="langbar" role="group" aria-label="Language">
      {languages.requested.map((code) => {
        const ready = languages.ready.includes(code);
        const m = meta(code);
        return (
          <button
            key={code}
            className="lang-tab"
            aria-pressed={value === code}
            disabled={!ready}
            onClick={() => ready && onChange(code)}
            title={ready ? m.label : `${m.label} — rendering…`}
          >
            <span className="flag">{m.flag}</span>
            {m.label}
            {!ready && <span className="faint" style={{ fontSize: 11 }}>…</span>}
          </button>
        );
      })}
    </div>
  );
}
