import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      colors: {
        // Mirrors the design tokens from the legacy HTML demo so the
        // visual contract stays consistent.
        bg:        '#0a0e1a',
        surface:   '#131825',
        surface2:  '#1a2030',
        border:    'rgba(255,255,255,.08)',
        text:      '#e5e7eb',
        textSoft:  '#9ca3af',
        textMute:  '#6b7280',
        primary:   '#a78bfa',
        secondary: '#38bdf8',
        success:   '#34d399',
        warning:   '#fbbf24',
        danger:    '#f87171',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'sans-serif'],
        mono: ['SF Mono', 'Consolas', 'monospace'],
      },
      backgroundImage: {
        'brand-grad': 'linear-gradient(135deg, #a78bfa 0%, #38bdf8 100%)',
      },
    },
  },
  plugins: [],
};

export default config;
