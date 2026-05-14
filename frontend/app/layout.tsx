import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SlicerApp",
  description: "Clips verticales con hooks editables.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
