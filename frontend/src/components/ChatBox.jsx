import { useEffect, useRef, useState } from 'react';
import { ArrowUp } from 'lucide-react';
import MessageBubble from './MessageBubble';
import VoiceInput from './VoiceInput';
import { t } from '../i18n';

export default function ChatBox({ messages, lang, busy, speech, onSend, onReplay, toolHint }) {
  const [draft, setDraft] = useState('');
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages, toolHint]);

  const submit = (text) => {
    const value = (text ?? draft).trim();
    if (!value || busy) return;
    setDraft('');
    onSend(value);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-4 pb-4 pt-5 sm:px-6">
        {messages.length === 0 && (
          <div className="mx-auto max-w-lg py-10">
            <p className="text-[15px] leading-relaxed text-haze/80">{t(lang, 'empty')}</p>
            <div className="mt-5 flex flex-wrap gap-2">
              {t(lang, 'starters').map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => submit(s)}
                  className="rounded-full border border-hairline bg-surface px-3 py-1.5 text-left text-[13px] text-haze/85 transition hover:border-signal hover:text-haze"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} lang={lang} onReplay={onReplay} />
        ))}

        {toolHint && (
          <p className="flex items-center gap-2 text-[13px] text-mute">
            <span className="h-1.5 w-1.5 animate-breathe rounded-full bg-signal" />
            {t(lang, 'thinking')} · {toolHint.replace(/_/g, ' ')}
          </p>
        )}

        <div ref={endRef} />
      </div>

      <div className="border-t border-hairline bg-deep/95 px-4 py-3 backdrop-blur sm:px-6">
        <div className="flex items-end gap-2">
          <VoiceInput
            speech={speech}
            lang={lang}
            disabled={busy}
            onTranscript={(text) => submit(text)}
          />

          <div className="flex flex-1 items-end rounded-2xl border border-hairline bg-surface focus-within:border-signal">
            <textarea
              ref={inputRef}
              rows={1}
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                e.target.style.height = 'auto';
                e.target.style.height = `${Math.min(e.target.scrollHeight, 140)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  submit();
                }
              }}
              placeholder={t(lang, 'placeholder')}
              className="max-h-36 flex-1 resize-none bg-transparent px-4 py-3 text-[14.5px] text-haze outline-none placeholder:text-mute"
            />
            <button
              type="button"
              onClick={() => submit()}
              disabled={busy || !draft.trim()}
              aria-label={t(lang, 'send')}
              className="m-1.5 grid h-8 w-8 place-items-center rounded-full bg-signal text-deep transition disabled:bg-hairline disabled:text-mute"
            >
              <ArrowUp size={16} strokeWidth={2.5} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
