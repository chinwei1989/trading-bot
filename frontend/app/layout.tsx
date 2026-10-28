import type { Metadata } from "next";
import "./globals.css";
import { SiteNav } from "@/components/SiteNav";

export const metadata: Metadata = {
  title: "NOVA · Trading Operations",
  description: "Read-only paper trading operations dashboard",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <SiteNav />
        <main className="shell">{children}</main>
        <footer className="footer">
          Paper only · no order controls · live capital remains gated.
        </footer>
      </body>
    </html>
  );
}
