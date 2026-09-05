/**
 * One source of truth for the warning colour scale, matching the IMD
 * four-colour convention: green (no action), yellow (be updated),
 * orange (be prepared), red (take action).
 */
export const SEVERITY = {
  green: { hex: '#1F8A5A', text: 'text-green', bg: 'bg-green/10', ring: 'ring-green/40', label: 'No action' },
  yellow: { hex: '#E8B62C', text: 'text-yellow', bg: 'bg-yellow/10', ring: 'ring-yellow/40', label: 'Be updated' },
  orange: { hex: '#E3762A', text: 'text-orange', bg: 'bg-orange/10', ring: 'ring-orange/40', label: 'Be prepared' },
  red: { hex: '#C7362C', text: 'text-red', bg: 'bg-red/10', ring: 'ring-red/40', label: 'Take action' },
};

export const sev = (key) => SEVERITY[key] || SEVERITY.green;

export const RANK = { green: 0, yellow: 1, orange: 2, red: 3 };

export function highest(list = []) {
  return list.reduce((acc, s) => (RANK[s] > RANK[acc] ? s : acc), 'green');
}
