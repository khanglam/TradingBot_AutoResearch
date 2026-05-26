import type { CampaignInfo } from '../api';

interface Props {
  campaigns: CampaignInfo[];
  selected: string;
  onSelect: (name: string) => void;
}

export function CampaignSelector({ campaigns, selected, onSelect }: Props) {
  return (
    <div className="flex items-center gap-2">
      {campaigns.map(c => {
        const running = c.running?.alive;
        return (
          <button
            key={c.name}
            onClick={() => onSelect(c.name)}
            className={[
              'btn capitalize',
              c.name === selected ? 'btn-primary' : '',
            ].join(' ')}
          >
            {c.name}
            {running && (
              <span className="ml-1 inline-block w-2 h-2 rounded-full bg-good animate-pulse" />
            )}
          </button>
        );
      })}
    </div>
  );
}
