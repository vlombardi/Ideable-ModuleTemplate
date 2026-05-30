/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  prefix: 'template-',
  corePlugins: {
    preflight: false,
  },
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'hsl(var(--template-border))',
        input: 'hsl(var(--template-input))',
        ring: 'hsl(var(--template-ring))',
        background: 'hsl(var(--template-background))',
        foreground: 'hsl(var(--template-foreground))',
        primary: {
          DEFAULT: 'hsl(var(--template-primary))',
          foreground: 'hsl(var(--template-primary-foreground))',
        },
        secondary: {
          DEFAULT: 'hsl(var(--template-secondary))',
          foreground: 'hsl(var(--template-secondary-foreground))',
        },
        destructive: {
          DEFAULT: 'hsl(var(--template-destructive))',
          foreground: 'hsl(var(--template-destructive-foreground))',
        },
        muted: {
          DEFAULT: 'hsl(var(--template-muted))',
          foreground: 'hsl(var(--template-muted-foreground))',
        },
        accent: {
          DEFAULT: 'hsl(var(--template-accent))',
          foreground: 'hsl(var(--template-accent-foreground))',
        },
        popover: {
          DEFAULT: 'hsl(var(--template-popover))',
          foreground: 'hsl(var(--template-popover-foreground))',
        },
        card: {
          DEFAULT: 'hsl(var(--template-card))',
          foreground: 'hsl(var(--template-card-foreground))',
        },
      },
      borderRadius: {
        lg: 'var(--template-radius)',
        md: 'calc(var(--template-radius) - 2px)',
        sm: 'calc(var(--template-radius) - 4px)',
      },
    },
  },
  plugins: [],
}
