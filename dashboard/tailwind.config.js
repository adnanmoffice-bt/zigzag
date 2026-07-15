/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#0A0D14',
        muted: '#6B7280',
        surface: '#F7F8FA',
        line: '#E6E8EC',
        accent: { DEFAULT: '#635BFF', soft: '#EEEDFF', dark: '#4B44D6' },
        gold: { DEFAULT: '#B8860B', soft: '#FBF6E9' },
        win: '#16A34A',
        loss: '#DF1B41',
        warn: '#D97706',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)',
        pop: '0 4px 12px rgba(16,24,40,.08), 0 12px 32px rgba(16,24,40,.10)',
      },
    },
  },
  plugins: [],
}
