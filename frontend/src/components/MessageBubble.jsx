import { Volume2 } from 'lucide-react';
import AdvisoryCard from './AdvisoryCard';
import AlertCard from './AlertCard';
import ClimateCard from './ClimateCard';
import ForecastCard from './ForecastCard';
import WeatherCard from './WeatherCard';

function Card({ card, lang }) {
  switch (card.type) {
    case 'weather':
      return <WeatherCard data={card.data} lang={lang} />;
    case 'alert':
      return <AlertCard bundle={card.data} lang={lang} />;
    case 'advisory':
      return <AdvisoryCard data={card.data} />;
    case 'climate':
      return <ClimateCard data={card.data} />;
    case 'forecast':
      return <ForecastCard data={card.data} />;
    default:
      return null;
  }
}

export default function MessageBubble({ message, lang, onReplay }) {
  const mine = message.role === 'user';

  if (mine) {
    return (
      <div className="flex justify-end">
        <p className="max-w-[80%] rounded-2xl rounded-br-sm bg-raised px-4 py-2.5 text-[14px] leading-relaxed text-haze">
          {message.content}
        </p>
      </div>
    );
  }

  return (
    <div className="max-w-[92%] space-y-3">
      {(message.cards || []).map((card, i) => (
        <Card key={i} card={card} lang={lang} />
      ))}

      {message.content && (
        <div className="group flex items-start gap-2">
          <p className="whitespace-pre-wrap text-[14.5px] leading-relaxed text-haze">
            {message.content}
            {message.streaming && (
              <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 animate-breathe bg-signal" />
            )}
          </p>
          {!message.streaming && onReplay && (
            <button
              type="button"
              onClick={() => onReplay(message.content)}
              className="mt-1 shrink-0 rounded p-1 text-mute opacity-0 transition hover:text-signal focus-visible:opacity-100 group-hover:opacity-100"
              aria-label="Read this reply aloud"
            >
              <Volume2 size={15} />
            </button>
          )}
        </div>
      )}
    </div>
  );
}
