const defaultTheme = require("tailwindcss/defaultTheme");

module.exports = {
  content: [
    "./app/templates/**/*.{html,js}",
    "./app/static/src/**/*.{js,ts}",
    "./docs/**/*.{md,mdx}",
    "./Updated UI/**/*.html",
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          primary: "var(--primary-color)",
          background: "var(--background-color)",
          approve: "var(--approve-button-color)",
          reject: "var(--reject-button-color)",
          neutral: "var(--general-btn-color)",
        },
      },
      fontFamily: {
        display: ["Inter", ...defaultTheme.fontFamily.sans],
      },
      boxShadow: {
        card: "0 8px 24px rgba(15, 23, 42, 0.08)",
      },
      borderRadius: {
        xl: "0.75rem",
      },
    },
  },
  plugins: [require("@tailwindcss/forms")],
};
