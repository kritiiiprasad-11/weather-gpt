/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        deep: '#08222C',
        surface: '#0E3240',
        raised: '#154356',
        hairline: '#1E5468',
        haze: '#DCE7E7',
        mute: '#7C9DA8',
        signal: '#4FC3D9',
        green: '#1F8A5A',
        yellow: '#E8B62C',
        orange: '#E3762A',
        red: '#C7362C',
      },
      fontFamily: {
        sans: ['Archivo', 'Noto Sans Devanagari', 'Noto Sans Tamil', 'Noto Sans Bengali', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        readout: ['3.75rem', { lineHeight: '1', letterSpacing: '-0.04em' }],
      },
      keyframes: {
        breathe: { '0%,100%': { opacity: '0.35' }, '50%': { opacity: '1' } },
        rise: { from: { opacity: '0', transform: 'translateY(6px)' }, to: { opacity: '1', transform: 'none' } },
      },
      animation: {
        breathe: 'breathe 1.8s ease-in-out infinite',
        rise: 'rise 220ms ease-out',
      },
    },
  },
  plugins: [],
};
