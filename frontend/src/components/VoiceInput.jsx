import { Mic, Square } from 'lucide-react';
import { t } from '../i18n';

/**
 * Push-to-talk control. Recognition is owned by the useSpeech hook in App so
 * that the same instance also drives text-to-speech; this component is the
 * button plus its live state.
 *
 * `onTranscript` fires once with the final recognised sentence.
 */
export default function VoiceInput({ speech, lang, onTranscript, disabled }) {
  const { sttSupported, listening, interim, startListening, stopListening } = speech;

  if (!sttSupported) {
    return (
      <span className="px-2 text-[11px] leading-tight text-mute" title={t(lang, 'micUnsupported')}>
        {t(lang, 'micUnsupported')}
      </span>
    );
  }

  const toggle = () => {
    if (listening) stopListening();
    else startListening(onTranscript);
  };

  return (
    <div className="relative">
      {listening && interim && (
        <p className="absolute bottom-full left-1/2 mb-3 w-max max-w-[60vw] -translate-x-1/2 rounded-lg border border-hairline bg-deep px-3 py-1.5 text-[13px] text-haze/80">
          {interim}
        </p>
      )}

      <button
        type="button"
        onClick={toggle}
        disabled={disabled}
        aria-pressed={listening}
        aria-label={listening ? t(lang, 'listening') : t(lang, 'speak')}
        className={`relative grid h-11 w-11 place-items-center rounded-full transition disabled:opacity-40 ${
          listening ? 'bg-red text-haze' : 'bg-raised text-signal hover:bg-hairline'
        }`}
      >
        {listening && (
          <span className="absolute inset-0 animate-breathe rounded-full ring-2 ring-red" aria-hidden />
        )}
        {listening ? <Square size={16} fill="currentColor" /> : <Mic size={18} />}
      </button>
    </div>
  );
}
