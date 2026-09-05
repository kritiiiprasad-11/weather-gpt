import { useCallback, useEffect, useRef, useState } from 'react';
import { speechTag } from '../i18n';

/**
 * Wraps the two halves of the Web Speech API.
 *
 * Recognition (STT): Chrome, Edge and Safari 14.1+. Firefox has none, so
 * `supported` is false there and the UI hides the mic (the backend exposes
 * /api/voice/transcribe as the server-side fallback).
 *
 * Synthesis (TTS): available almost everywhere, but the installed voices vary.
 * We pick the closest voice for the chosen language and fall back to the
 * browser default rather than staying silent.
 */
export function useSpeech(lang) {
  const Recognition =
    typeof window !== 'undefined' &&
    (window.SpeechRecognition || window.webkitSpeechRecognition);

  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState('');
  const [speaking, setSpeaking] = useState(false);
  const [voices, setVoices] = useState([]);
  const recognitionRef = useRef(null);
  const onResultRef = useRef(null);

  // Voice list loads asynchronously in Chrome.
  useEffect(() => {
    if (!('speechSynthesis' in window)) return;
    const load = () => setVoices(window.speechSynthesis.getVoices());
    load();
    window.speechSynthesis.addEventListener('voiceschanged', load);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', load);
  }, []);

  const startListening = useCallback(
    (onResult) => {
      if (!Recognition) return false;
      stopSpeaking();
      onResultRef.current = onResult;

      const rec = new Recognition();
      rec.lang = speechTag(lang);
      rec.interimResults = true;
      rec.continuous = false;
      rec.maxAlternatives = 1;

      rec.onresult = (event) => {
        let finalText = '';
        let partial = '';
        for (let i = event.resultIndex; i < event.results.length; i += 1) {
          const r = event.results[i];
          if (r.isFinal) finalText += r[0].transcript;
          else partial += r[0].transcript;
        }
        setInterim(partial);
        if (finalText) {
          setInterim('');
          onResultRef.current?.(finalText.trim());
        }
      };
      rec.onerror = () => {
        setListening(false);
        setInterim('');
      };
      rec.onend = () => {
        setListening(false);
        setInterim('');
      };

      recognitionRef.current = rec;
      rec.start();
      setListening(true);
      return true;
    },
    [Recognition, lang]
  );

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    setListening(false);
    setInterim('');
  }, []);

  const speak = useCallback(
    (text) => {
      if (!('speechSynthesis' in window) || !text) return;
      window.speechSynthesis.cancel();

      const tag = speechTag(lang);
      const utter = new SpeechSynthesisUtterance(
        // Strip anything that reads badly out loud.
        text.replace(/[*_#`]/g, '').replace(/\s+/g, ' ').trim()
      );
      utter.lang = tag;
      utter.rate = 0.95;
      utter.pitch = 1;
      const match =
        voices.find((v) => v.lang === tag) ||
        voices.find((v) => v.lang?.startsWith(tag.split('-')[0]));
      if (match) utter.voice = match;
      utter.onstart = () => setSpeaking(true);
      utter.onend = () => setSpeaking(false);
      utter.onerror = () => setSpeaking(false);
      window.speechSynthesis.speak(utter);
    },
    [lang, voices]
  );

  const stopSpeaking = useCallback(() => {
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
    setSpeaking(false);
  }, []);

  useEffect(() => () => {
    recognitionRef.current?.abort?.();
    if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  }, []);

  return {
    sttSupported: Boolean(Recognition),
    ttsSupported: typeof window !== 'undefined' && 'speechSynthesis' in window,
    listening,
    interim,
    speaking,
    startListening,
    stopListening,
    speak,
    stopSpeaking,
  };
}
