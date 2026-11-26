/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: 'hsl(var(--canvas))',
        panel: {
          DEFAULT: 'hsl(var(--panel))',
          muted: 'hsl(var(--panel-muted))',
          elevated: 'hsl(var(--panel-elevated))',
        },
        ink: {
          DEFAULT: 'hsl(var(--ink))',
          secondary: 'hsl(var(--ink-secondary))',
          subtle: 'hsl(var(--ink-subtle))',
          inverse: 'hsl(var(--ink-inverse))',
        },
        line: {
          DEFAULT: 'hsl(var(--line))',
          strong: 'hsl(var(--line-strong))',
        },
        action: {
          DEFAULT: 'hsl(var(--action))',
          hover: 'hsl(var(--action-hover))',
          soft: 'hsl(var(--action-soft))',
          foreground: 'hsl(var(--action-foreground))',
        },
        ring: 'hsl(var(--ring))',
        status: {
          ok: 'hsl(var(--status-ok))',
          'ok-soft': 'hsl(var(--status-ok-soft))',
          warn: 'hsl(var(--status-warn))',
          'warn-soft': 'hsl(var(--status-warn-soft))',
          bad: 'hsl(var(--status-bad))',
          'bad-soft': 'hsl(var(--status-bad-soft))',
          info: 'hsl(var(--status-info))',
          'info-soft': 'hsl(var(--status-info-soft))',
        },
        metric: {
          docs: 'hsl(var(--metric-docs))',
          chunks: 'hsl(var(--metric-chunks))',
          latency: 'hsl(var(--metric-latency))',
          queue: 'hsl(var(--metric-queue))',
        },
        /* Legacy aliases — map old class names to new tokens during migration */
        surface: 'hsl(var(--panel))',
        subtle: 'hsl(var(--panel-muted))',
        default: 'hsl(var(--line))',
        strong: 'hsl(var(--line-strong))',
        fg: 'hsl(var(--ink))',
        muted: 'hsl(var(--ink-secondary))',
        brand: {
          DEFAULT: 'hsl(var(--action))',
          dark: 'hsl(var(--action-hover))',
          light: 'hsl(var(--action-soft))',
        },
        success: {
          bg: 'hsl(var(--status-ok-soft))',
          text: 'hsl(var(--status-ok))',
          border: 'hsl(var(--status-ok))',
        },
        warning: {
          bg: 'hsl(var(--status-warn-soft))',
          text: 'hsl(var(--status-warn))',
          border: 'hsl(var(--status-warn))',
        },
        danger: {
          bg: 'hsl(var(--status-bad-soft))',
          text: 'hsl(var(--status-bad))',
          border: 'hsl(var(--status-bad))',
        },
        info: {
          bg: 'hsl(var(--status-info-soft))',
          text: 'hsl(var(--status-info))',
          border: 'hsl(var(--status-info))',
        },
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      fontFamily: {
        sans: [
          '"Plus Jakarta Sans"',
          'ui-sans-serif',
          'system-ui',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(8px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'pulse-soft': {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.55' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.4s ease-out both',
        'pulse-soft': 'pulse-soft 2s ease-in-out infinite',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}
