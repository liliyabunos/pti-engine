import type { Metadata } from "next";
import "./globals.css";
import { QueryProvider } from "@/providers/QueryProvider";

export const metadata: Metadata = {
  metadataBase: new URL("https://fragranceindex.ai"),
  title: "FTI Market Terminal",
  description: "Fragrance Trend Intelligence — market terminal for fragrance trends",
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
