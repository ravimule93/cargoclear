import type { Metadata } from "next";
import { LiveRegionRoot } from "@/components/a11y/LiveRegion";
import "./globals.css";
import "@/styles/workbench.css";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "CargoClear-JAPAC — Customs Document Assessment Workbench",
  description: "Pre-submission customs document assessment for cross-border trade. Decision support only: the authorised agent decides.",
  icons: {
    icon: [{ url: "/cargoclear-logo.webp", type: "image/webp" }],
    shortcut: ["/cargoclear-logo.webp"],
    apple: [{ url: "/cargoclear-logo.webp", type: "image/webp" }],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function() {
                try {
                  var stored = localStorage.getItem('cargoclear-theme');
                  if (!stored) {
                    var m = document.cookie.match(/(?:^|; )cargoclear_theme=([^;]*)/);
                    if (m) stored = decodeURIComponent(m[1]);
                  }
                  var isDark = stored === 'dark' || (!stored && window.matchMedia('(prefers-color-scheme: dark)').matches);
                  var root = document.documentElement;
                  if (isDark) {
                    root.classList.remove('light');
                    root.classList.add('dark');
                    root.setAttribute('data-theme', 'dark');
                  } else {
                    root.classList.remove('dark');
                    root.classList.add('light');
                    root.setAttribute('data-theme', 'light');
                  }
                } catch(e) {}
              })();
            `,
          }}
        />
      </head>
      <body className="antialiased">
        <LiveRegionRoot>{children}</LiveRegionRoot>
      </body>
    </html>
  );
}
