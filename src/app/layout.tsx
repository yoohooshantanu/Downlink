import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Orbitwatch — Ground Station Telemetry",
  description: "SatNOGS Telemetry Intelligence Platform",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} min-h-screen antialiased`}
        style={{
          fontFamily: "var(--font-sans), 'Inter', system-ui, sans-serif",
          backgroundColor: "#0a0e14",
          color: "#cdd9e5",
        }}
      >
        {children}
      </body>
    </html>
  );
}
