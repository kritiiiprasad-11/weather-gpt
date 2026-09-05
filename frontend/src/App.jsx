import { useCallback, useEffect, useRef, useState } from 'react';
import { CloudSun, Map as MapIcon, Search, Volume2, VolumeX } from 'lucide-react';
import ChatBox from './components/ChatBox';
import ConditionsRail from './components/ConditionsRail';
import LanguageSelector from './components/LanguageSelector';
import MapPanel from './components/MapPanel';
import { api, openAlertSocket, streamChat } from './api/client';
import { useSpeech } from './hooks/useSpeech';
import { useDragResize, useMediaQuery } from './hooks/useDragResize';
import { sev } from './severity';
import { t } from './i18n';

const uid = () => Math.random().toString(36).slice(2);
const SESSION = uid();
const FALLBACK = { latitude: 19.076, longitude: 72.8777, name: 'Mumbai' };

export default function App() {
  const [lang, setLang] = useState('en');
  const [place, setPlace] = useState(null); // {latitude, longitude, name}
  const [current, setCurrent] = useState(null);
  const [bundle, setBundle] = useState(null);
  const [loadingConditions, setLoadingConditions] = useState(true);
  const [messages, setMessages] = useState([]);
  const [busy, setBusy] = useState(false);
  const [toolHint, setToolHint] = useState(null);
  const [autoSpeak, setAutoSpeak] = useState(true);
  const [showMap, setShowMap] = useState(false);
  const [query, setQuery] = useState('');
  const [notice, setNotice] = useState(null);

  const speech = useSpeech(lang);
  const abortRef = useRef(null);

  // Draggable map drawer: a vertical grab handle on desktop, a horizontal one
  // when the drawer becomes a bottom sheet on small screens.
  const isDesktop = useMediaQuery('(min-width: 1024px)');
  const drawer = useDragResize({
    axis: isDesktop ? 'x' : 'y',
    initial: isDesktop ? 340 : 260,
    min: isDesktop ? 260 : 160,
    max: isDesktop ? 720 : 520,
    storageKey: isDesktop ? 'wg:map-width' : 'wg:map-height',
  });

  // -- location ------------------------------------------------------------
  useEffect(() => {
    if (!navigator.geolocation) {
      setPlace(FALLBACK);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) =>
        setPlace({
          latitude: pos.coords.latitude,
          longitude: pos.coords.longitude,
          name: null,
        }),
      () => {
        setNotice(t(lang, 'locationDenied'));
        setPlace(FALLBACK);
      },
      { timeout: 8000, maximumAge: 300000 }
    );
    // Runs once: language changes should not re-prompt for location.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // -- conditions + warnings for the active point --------------------------
  const refreshConditions = useCallback(async (p) => {
    if (!p) return;
    setLoadingConditions(true);
    try {
      const params = { lat: p.latitude, lon: p.longitude };
      const [cur, alerts] = await Promise.all([api.current(params), api.alerts(params)]);
      setCurrent(cur);
      setBundle(alerts);
      setPlace((prev) => ({ ...prev, name: prev?.name || cur.location?.name }));
    } catch (e) {
      setNotice(e.message);
    } finally {
      setLoadingConditions(false);
    }
  }, []);

  useEffect(() => {
    refreshConditions(place);
  }, [place?.latitude, place?.longitude, refreshConditions]);

  // Server pushes fresh threshold checks so a warning arrives without asking.
  useEffect(() => {
    if (!place) return undefined;
    const ws = openAlertSocket(place.latitude, place.longitude, setBundle);
    return () => ws.close();
  }, [place?.latitude, place?.longitude]);

  // The whole top edge carries the current hazard colour.
  useEffect(() => {
    document.documentElement.style.setProperty(
      '--sev',
      sev(bundle?.overall_severity || 'green').hex
    );
  }, [bundle?.overall_severity]);

  // -- place search --------------------------------------------------------
  const search = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    try {
      const hits = await api.geocode(query.trim());
      if (hits.length) {
        setPlace({ latitude: hits[0].latitude, longitude: hits[0].longitude, name: hits[0].name });
        setQuery('');
        setNotice(null);
      }
    } catch (err) {
      setNotice(err.message);
    }
  };

  // -- chat ----------------------------------------------------------------
  const send = async (text) => {
    speech.stopSpeaking();
    const userMsg = { id: uid(), role: 'user', content: text };
    const replyId = uid();
    setMessages((m) => [
      ...m,
      userMsg,
      { id: replyId, role: 'assistant', content: '', cards: [], streaming: true },
    ]);
    setBusy(true);
    setToolHint(null);

    const history = messages.slice(-8).map(({ role, content }) => ({ role, content }));
    abortRef.current = new AbortController();
    let full = '';

    const patch = (fn) =>
      setMessages((m) => m.map((msg) => (msg.id === replyId ? fn(msg) : msg)));

    try {
      await streamChat(
        {
          message: text,
          history,
          latitude: place?.latitude,
          longitude: place?.longitude,
          language: lang,
          session_id: SESSION,
        },
        (event) => {
          if (event.type === 'tool') setToolHint(event.name);
          if (event.type === 'card') {
            patch((msg) => ({ ...msg, cards: [...msg.cards, event.card] }));
            // A warning card arriving mid-answer also refreshes the rail.
            if (event.card.type === 'alert') setBundle(event.card.data);
          }
          if (event.type === 'token') {
            full += event.text;
            patch((msg) => ({ ...msg, content: msg.content + event.text }));
          }
          if (event.type === 'error') {
            patch((msg) => ({ ...msg, content: event.message }));
          }
          if (event.type === 'done') setToolHint(null);
        },
        abortRef.current.signal
      );
    } catch (err) {
      full = t(lang, 'error');
      patch((msg) => ({ ...msg, content: full }));
    } finally {
      patch((msg) => ({ ...msg, streaming: false }));
      setBusy(false);
      setToolHint(null);
      if (autoSpeak && full) speech.speak(full);
    }
  };

  const severity = bundle?.overall_severity || 'green';

  return (
    <div className="flex h-full flex-col bg-deep">
      <div className="severity-edge h-[3px] w-full shrink-0" aria-hidden />

      <header className="flex flex-wrap items-center gap-3 border-b border-hairline px-4 py-3 sm:px-6">
        <div className="flex items-center gap-2">
          <CloudSun size={20} className="text-signal" aria-hidden />
          <h1 className="text-[17px] font-semibold tracking-tight text-haze">WeatherGPT</h1>
          <span className="hidden text-[13px] text-mute sm:inline">{t(lang, 'tagline')}</span>
        </div>

        <form onSubmit={search} className="order-3 flex w-full items-center gap-2 sm:order-none sm:ml-4 sm:w-auto sm:flex-1 sm:max-w-xs">
          <div className="flex flex-1 items-center gap-2 rounded-full border border-hairline bg-surface px-3 focus-within:border-signal">
            <Search size={14} className="text-mute" aria-hidden />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t(lang, 'searchPlace')}
              aria-label={t(lang, 'searchPlace')}
              className="w-full bg-transparent py-1.5 text-[13px] text-haze outline-none placeholder:text-mute"
            />
          </div>
        </form>

        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setAutoSpeak((v) => !v);
              speech.stopSpeaking();
            }}
            aria-pressed={autoSpeak}
            title={t(lang, 'readAloud')}
            className={`grid h-9 w-9 place-items-center rounded-full border border-hairline transition ${
              autoSpeak ? 'bg-surface text-signal' : 'text-mute hover:text-haze'
            }`}
          >
            {autoSpeak ? <Volume2 size={16} /> : <VolumeX size={16} />}
          </button>

          <button
            type="button"
            onClick={() => setShowMap((v) => !v)}
            aria-pressed={showMap}
            title={t(lang, 'map')}
            className={`grid h-9 w-9 place-items-center rounded-full border border-hairline transition lg:hidden ${
              showMap ? 'bg-surface text-signal' : 'text-mute hover:text-haze'
            }`}
          >
            <MapIcon size={16} />
          </button>

          <LanguageSelector value={lang} onChange={setLang} />
        </div>
      </header>

      {notice && (
        <p className="border-b border-hairline bg-surface px-4 py-2 text-[12px] text-mute sm:px-6">
          {notice}
        </p>
      )}

      <main
        className="grid min-h-0 flex-1 lg:grid-cols-[264px_minmax(0,1fr)_340px]"
        style={
          isDesktop
            ? { gridTemplateColumns: `264px minmax(0,1fr) ${drawer.size}px` }
            : undefined
        }
      >
        <aside className="border-b border-hairline lg:border-b-0 lg:border-r">
          <ConditionsRail
            current={current}
            bundle={bundle}
            lang={lang}
            loading={loadingConditions}
          />
        </aside>

        <section className="min-h-0">
          <ChatBox
            messages={messages}
            lang={lang}
            busy={busy}
            speech={speech}
            toolHint={toolHint}
            onSend={send}
            onReplay={(text) => speech.speak(text)}
          />
        </section>

        <aside
          className={`map-drawer relative border-hairline lg:block lg:border-l ${
            drawer.dragging ? 'is-resizing' : ''
          } ${showMap ? 'block border-t lg:border-t-0' : 'hidden'}`}
          style={!isDesktop && showMap ? { height: `${drawer.size}px` } : undefined}
        >
          <div className="map-drawer-handle" {...drawer.handleProps}>
            <span className="map-drawer-grip" aria-hidden />
          </div>
          <div className="map-drawer-body h-full w-full">
            <MapPanel
              lat={place?.latitude}
              lon={place?.longitude}
              name={current?.location?.name}
              severity={severity}
              onPick={(latitude, longitude) => setPlace({ latitude, longitude, name: null })}
            />
          </div>
        </aside>
      </main>
    </div>
  );
}
