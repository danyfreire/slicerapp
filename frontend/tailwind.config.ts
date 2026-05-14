import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx}", "./components/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#171413",
        paper: "#fbfaf6",
        fuzz: "#e85d2a",
        moss: "#3d6b52",
        gold: "#e4b84f",
      },
    },
  },
  plugins: [],
};

export default config;
