import type { Metadata } from "next";
import { LiveRegionRoot } from "@/components/a11y/LiveRegion";
import "./globals.css";
import "@/styles/workbench.css";

export const metadata: Metadata = {
  title: "CargoClear-JAPAC — Customs Adjudication Workbench",
  description: "Pre-submission adversarial customs adjudicator for cross-border trade",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <LiveRegionRoot>{children}</LiveRegionRoot>
      </body>
    </html>
  );
}
