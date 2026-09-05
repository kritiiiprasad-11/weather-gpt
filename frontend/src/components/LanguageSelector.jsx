import { Languages } from 'lucide-react';
import { LANGUAGES } from '../i18n';

export default function LanguageSelector({ value, onChange }) {
  return (
    <label className="flex items-center gap-1.5 rounded-full border border-hairline bg-surface pl-3 pr-1.5 text-[13px] text-haze">
      <Languages size={14} className="text-mute" aria-hidden />
      <span className="sr-only">Language</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="cursor-pointer appearance-none bg-transparent py-1.5 pr-1 text-[13px] text-haze outline-none"
      >
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code} className="bg-deep text-haze">
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}
