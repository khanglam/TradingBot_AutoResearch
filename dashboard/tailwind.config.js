/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0a0a0b',
        panel: '#111114',
        border: '#1f1f24',
        text: '#e5e5ea',
        muted: '#8a8a93',
        accent: '#7c5cff',
        good: '#3ddc84',
        bad: '#ff4d6d',
        warn: '#ffb84d',
      },
      fontFamily: {
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'monospace'],
      },
    },
  },
  plugins: [],
};
