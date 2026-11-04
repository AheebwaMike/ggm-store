/** @type {import('tailwindcss').Config} */
module.exports = {
  // Every file that can contain Tailwind class names. Add a path here if you add templates elsewhere.
  content: [
    './templates/**/*.html',
    './marketplace/templates/**/*.html',
    './marketplace/**/*.py',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        brand: {
          50: '#fff7ed',
          100: '#ffedd5',
          200: '#fed7aa',
          500: '#f97316',
          600: '#ea580c',
          700: '#c2410c',
          800: '#9a3412',
        },
        canvas: '#f4f5f7',
      },
      boxShadow: {
        card: '0 1px 2px rgba(15,23,42,.05), 0 6px 16px -8px rgba(15,23,42,.14)',
        bar: '0 10px 30px -8px rgba(15,23,42,.45)',
        header: '0 8px 24px -12px rgba(194,65,12,.6)',
      },
    },
  },
  plugins: [],
};