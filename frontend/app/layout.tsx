import type { Metadata } from "next";
import { LiveRegionRoot } from "@/components/a11y/LiveRegion";
import "./globals.css";
import "@/styles/workbench.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "CargoClear-JAPAC — Customs Document Assessment Workbench",
  description: "Pre-submission customs document assessment for cross-border trade. Decision support only: the authorised agent decides.",
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
