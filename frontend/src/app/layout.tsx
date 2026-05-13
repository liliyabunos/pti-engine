import type { Metadata } from "next";
import "./globals.css";
import { QueryProvider } from "@/providers/QueryProvider";

export const metadata: Metadata = {
  metadataBase: new URL("https://fragranceindex.ai"),
  title: "FTI Market Terminal",
  description: "Fragrance Trend Intelligence — market terminal for fragrance trends",
  // SEO0: OpenGraph defaults — no og:image yet (PUB1 will add branded asset)
  openGraph: {
    type: "website",
    siteName: "FragranceIndex.ai",
    title: "FTI Market Terminal",
    description: "Fragrance Trend Intelligence — market terminal for fragrance trends",
  },
  twitter: {
    card: "summary",
    title: "FTI Market Terminal",
    description: "Fragrance Trend Intelligence — market terminal for fragrance trends",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="h-full bg-zinc-950 text-zinc-200">
        <QueryProvider>{children}</QueryProvider>
      </body>
    </html>
  );
}
